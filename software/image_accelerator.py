"""PYNQ 2.7 simple-DMA driver. Board execution still requires validation.

Register and buffer contract: docs/image_system.md. No Linux image is included.
"""
import time
from pathlib import Path

import numpy as np
from image_reference import MODES, pack_rgb

# Retain physical buffers if hardware cannot be confirmed quiescent, even when
# callers drop their last reference. PynqBuffer's destructor also frees memory.
_faulted_accelerators = []


class ImageAccelerator:
    WIDTH, HEIGHT = 128, 96

    def __init__(self, bitfile, timeout=5.0):
        from pynq import Overlay, allocate
        bitfile = Path(bitfile)
        if not bitfile.is_file() or not bitfile.with_suffix(".hwh").is_file():
            raise FileNotFoundError("Matching .bit and .hwh files are required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self.overlay = Overlay(str(bitfile))
        self.dma = self.overlay.axi_dma_0
        self.gpio = self.overlay.axi_gpio_0.mmio
        self.gpio.write(0x04, 0)  # Channel 1: all output.
        self.gpio.write(0x0c, 0xffffffff)  # Channel 2: all input.
        self.gpio.write(0, 1 << 9)
        time.sleep(0.001)
        self.gpio.write(0, 0)
        self.input_buffer = allocate((self.WIDTH*self.HEIGHT,), dtype=np.uint32)
        self.output_buffers = {
            False: allocate((self.WIDTH*self.HEIGHT,), dtype=np.uint32),
            True: allocate(((self.WIDTH-2)*(self.HEIGHT-2),), dtype=np.uint32),
        }
        self.healthy = True
        self.closed = False

    def process(self, rgb, mode):
        if self.closed or not self.healthy:
            raise RuntimeError("Accelerator is closed or faulted; recreate it")
        if mode not in MODES:
            raise ValueError("Mode must be 0..4")
        if np.asarray(rgb).shape != (self.HEIGHT, self.WIDTH, 3):
            raise ValueError("This bitstream expects exactly 96x128 RGB pixels")
        self.input_buffer[:] = pack_rgb(rgb)
        cropped = mode in (1, 2, 3)
        output = self.output_buffers[cropped]
        # Time excludes RGB packing and the returned numpy copy. It includes
        # start/control, cache operations, both DMA transfers and PL processing.
        started = time.perf_counter()
        try:
            self.gpio.write(0, mode | (1 << 8))
            self.gpio.write(0, mode)
            self.dma.recvchannel.transfer(output)
            self.dma.sendchannel.transfer(self.input_buffer)
            deadline = time.monotonic() + self.timeout
            while True:
                status = self.gpio.read(8)
                tx = self.dma.mmio.read(0x04)
                rx = self.dma.mmio.read(0x34)
                if (tx | rx) & 0x70:
                    raise RuntimeError("DMA error tx=0x%x rx=0x%x" % (tx, rx))
                if status & 4:
                    raise RuntimeError("Core packet/control error: 0x%x" % status)
                if status & 2 and not status & 1 and tx & 2 and rx & 2:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Frame timeout status=0x%x tx=0x%x rx=0x%x" % (status, tx, rx))
                time.sleep(0.0001)
            # idle was verified above, so these waits do not wait for a live DMA.
            # recv wait also invalidates its noncoherent CPU cache.
            self.dma.sendchannel.wait()
            self.dma.recvchannel.wait()
            if self.dma.recvchannel.transferred != output.nbytes:
                raise RuntimeError("Unexpected output transfer length")
            elapsed = time.perf_counter() - started
            if np.any(output & np.uint32(0xffffff00)):
                raise RuntimeError("Nonzero reserved bits in FPGA output")
            shape = (self.HEIGHT-2, self.WIDTH-2) if cropped else (self.HEIGHT, self.WIDTH)
            return np.asarray(output & 255, dtype=np.uint8).reshape(shape).copy(), elapsed
        except Exception:
            self.healthy = False
            raise

    def close(self):
        if self.closed:
            return
        try:
            self.gpio.write(0, 1 << 9)
            # Reset both channels before releasing physical-memory buffers.
            self.dma.mmio.write(0, 4)
            deadline = time.monotonic() + self.timeout
            while self.dma.mmio.read(0) & 4:
                if time.monotonic() > deadline:
                    raise TimeoutError("DMA reset failed; buffers retained for safety")
                time.sleep(0.001)
            if not (self.dma.mmio.read(4) & 1 and self.dma.mmio.read(0x34) & 1):
                raise RuntimeError("DMA not halted; buffers retained")
        except Exception:
            self.healthy = False
            if self not in _faulted_accelerators:
                _faulted_accelerators.append(self)
            raise
        self.input_buffer.freebuffer()
        for buffer in self.output_buffers.values():
            buffer.freebuffer()
        self.closed = True
        self.healthy = False
        if self in _faulted_accelerators:
            _faulted_accelerators.remove(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
