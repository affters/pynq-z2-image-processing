"""Bounded binary UART client for the temporary ARM/FPGA image firmware.

pyserial is imported only when a real port is opened. A transaction failure
closes the client; create a new instance and perform INFO again to recover.
UART round-trip timing includes board processing and is not PL latency.
"""
import math
import operator
import secrets
import struct
import threading
import time
import zlib

import numpy as np

REQUEST = struct.Struct("<8sIIIHHII")
RESPONSE = struct.Struct("<8sIIHHIII")
REQUEST_MAGIC = b"PYNQIMG1"
RESPONSE_MAGIC = b"PYNQRES1"
FIRMWARE_INFO = b"pynq_uart_image_v1"
WIDTH, HEIGHT = 128, 96
RGB_BYTES = WIDTH * HEIGHT * 3
MAX_RESPONSE_BYTES = WIDTH * HEIGHT
BAUDRATES = (115200, 1000000, 2000000)


class UARTProtocolError(RuntimeError):
    """An invalid, incomplete, or untrusted UART transaction."""


class UARTDeviceError(UARTProtocolError):
    """A nonzero status explicitly returned by the firmware."""

    def __init__(self, status, core_status):
        self.status = status
        self.core_status = core_status
        super().__init__("Firmware returned status=%d core_status=0x%08x" %
                         (status, core_status))


class FrameClient:
    """Own one explicit serial port; context entry performs INFO handshake.

    ``transport`` is dependency injection for offline tests only. With a real
    port, DTR/RTS and all flow-control modes are disabled before opening it.
    """

    def __init__(self, port, baudrate=115200, timeout=20.0, transport=None):
        if not isinstance(port, str) or not port.strip():
            raise ValueError("An explicit serial port is required")
        if baudrate not in BAUDRATES:
            raise ValueError("Supported diagnostic baudrates: %r" % (BAUDRATES,))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        self.port = port
        self.baudrate = baudrate
        self.timeout = float(timeout)
        self._test_transport = transport
        self._serial = None
        self._lock = threading.Lock()
        self._closed = False
        self._ready = False
        self._sequence = secrets.randbelow(0xFFFFFFFE) + 1
        self.firmware_info = None
        self.info_roundtrip_seconds = None

    @property
    def closed(self):
        return self._closed

    def _close_unlocked(self):
        serial_port, self._serial = self._serial, None
        self._closed = True
        self._ready = False
        if serial_port is not None:
            serial_port.close()

    def close(self):
        with self._lock:
            self._close_unlocked()

    def _invalidate(self):
        try:
            self._close_unlocked()
        except Exception:
            # Preserve the transaction error if device removal also breaks close.
            pass

    def open(self):
        with self._lock:
            if self._closed:
                raise UARTProtocolError("Client closed; create a new instance to handshake again")
            if self._ready:
                return self
            try:
                if self._test_transport is not None:
                    self._serial = self._test_transport
                else:
                    try:
                        import serial
                    except ImportError as exc:
                        raise RuntimeError("pyserial is required in the selected host environment") from exc
                    device = serial.Serial(port=None, baudrate=self.baudrate,
                                           timeout=min(0.1, self.timeout),
                                           write_timeout=min(1.0, self.timeout),
                                           xonxoff=False, rtscts=False, dsrdtr=False)
                    device.dtr = False
                    device.rts = False
                    device.port = self.port
                    self._serial = device
                    device.open()
                if hasattr(self._serial, "reset_input_buffer"):
                    self._serial.reset_input_buffer()
                payload, header, elapsed = self._exchange(1, 0, 0, 0, b"")
                if payload != FIRMWARE_INFO or (header[3], header[4]) != (WIDTH, HEIGHT):
                    raise UARTProtocolError("Unexpected firmware identity or dimensions")
                if header[7] != 0:
                    raise UARTProtocolError("INFO must not report a PL operation")
                self.firmware_info = payload.decode("ascii")
                self.info_roundtrip_seconds = elapsed
                self._ready = True
                return self
            except Exception:
                self._invalidate()
                raise

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.close()
        else:
            self._invalidate()
        return False

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("UART transaction deadline expired")
        return remaining

    def _read_exact(self, count, deadline):
        output = bytearray()
        while len(output) < count:
            next_timeout = min(0.1, self._remaining(deadline))
            # On Windows a timeout setter also reapplies the DCB/baud settings.
            # Avoid reconfiguring FTDI while its current reply is in flight.
            if self._serial.timeout != next_timeout:
                self._serial.timeout = next_timeout
            wanted = min(4096, count - len(output))
            data = self._serial.read(wanted)
            if not isinstance(data, (bytes, bytearray)) or len(data) > wanted:
                raise UARTProtocolError("Serial transport returned an invalid byte count")
            if data:
                output.extend(data)
        return bytes(output)

    def _write_all(self, data, deadline):
        offset = 0
        while offset < len(data):
            next_timeout = min(1.0, self._remaining(deadline))
            if self._serial.write_timeout != next_timeout:
                self._serial.write_timeout = next_timeout
            block = data[offset:offset + 4096]
            written = self._serial.write(block)
            if not isinstance(written, int) or not 0 < written <= len(block):
                raise UARTProtocolError("Serial transport did not write the requested bytes")
            offset += written

    def _response_header(self, deadline):
        # Permit a short startup banner, but never scan unbounded noise.
        prefix = bytearray(self._read_exact(len(RESPONSE_MAGIC), deadline))
        skipped = 0
        while prefix != RESPONSE_MAGIC:
            if skipped >= 512:
                raise UARTProtocolError("Response magic not found within startup-noise limit")
            del prefix[0]
            prefix.extend(self._read_exact(1, deadline))
            skipped += 1
        return RESPONSE.unpack(bytes(prefix) + self._read_exact(RESPONSE.size - 8, deadline))

    def _exchange(self, command, mode, width, height, payload):
        if self._serial is None or self._closed:
            raise UARTProtocolError("Serial port is not open")
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        sequence = self._sequence
        header = REQUEST.pack(REQUEST_MAGIC, sequence, command, mode, width, height,
                              len(payload), zlib.crc32(payload) & 0xFFFFFFFF)
        started = time.perf_counter()
        deadline = time.monotonic() + self.timeout
        self._write_all(header, deadline)
        self._write_all(payload, deadline)
        result = self._response_header(deadline)
        _, actual_sequence, status, out_width, out_height, size, checksum, core_status = result
        if actual_sequence != sequence:
            raise UARTProtocolError("Stale or incorrect response sequence")
        if size > MAX_RESPONSE_BYTES:
            raise UARTProtocolError("Response payload exceeds the fixed image limit")
        if status:
            if size != 0 or checksum != 0:
                raise UARTProtocolError("Error response must have an empty payload and CRC zero")
            raise UARTDeviceError(status, core_status)
        if command == 1:
            if size != len(FIRMWARE_INFO):
                raise UARTProtocolError("INFO payload length differs from the firmware contract")
        else:
            expected_shape = (WIDTH, HEIGHT) if mode in (0, 4) else (WIDTH - 2, HEIGHT - 2)
            if (out_width, out_height) != expected_shape or size != out_width * out_height:
                raise UARTProtocolError("Output shape or payload length differs from selected mode")
            if core_status & 7 != 2:
                raise UARTProtocolError("FPGA core did not report done without busy/error")
        data = self._read_exact(size, deadline)
        if zlib.crc32(data) & 0xFFFFFFFF != checksum:
            raise UARTProtocolError("Response CRC32 mismatch")
        return data, result, time.perf_counter() - started

    def process(self, rgb, mode):
        if isinstance(mode, (bool, np.bool_)):
            raise ValueError("mode must be an integer from 0 through 4")
        try:
            mode = operator.index(mode)
        except TypeError as exc:
            raise ValueError("mode must be an integer from 0 through 4") from exc
        if mode not in (0, 1, 2, 3, 4):
            raise ValueError("mode must be an integer from 0 through 4")
        image = np.asarray(rgb)
        if image.dtype != np.uint8 or image.shape != (HEIGHT, WIDTH, 3):
            raise ValueError("Expected a 96x128x3 uint8 RGB image")
        payload = np.ascontiguousarray(image).tobytes()
        if len(payload) != RGB_BYTES:
            raise ValueError("Unexpected fixed image byte count")
        with self._lock:
            if not self._ready or self._closed:
                raise UARTProtocolError("INFO handshake is required before processing")
            try:
                data, header, elapsed = self._exchange(2, int(mode), WIDTH, HEIGHT, payload)
                _, sequence, _, out_width, out_height, _, checksum, core_status = header
                result = np.frombuffer(data, dtype=np.uint8).reshape(out_height, out_width).copy()
                return result, dict(sequence=sequence, mode=int(mode), core_status=core_status,
                                    response_crc32=checksum, uart_roundtrip_seconds=elapsed,
                                    request_payload_bytes=len(payload), response_payload_bytes=len(data))
            except Exception:
                self._invalidate()
                raise
