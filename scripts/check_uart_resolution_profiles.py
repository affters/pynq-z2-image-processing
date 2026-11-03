"""Offline profile/geometry boundaries. Never opens UART, camera or Tk."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zlib

import cv2
import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
from uart_image_client import (FrameClient, REQUEST, RESPONSE, RESPONSE_MAGIC,
                               UARTProtocolError, resolution_profile)
from uart_camera_demo import read_camera_rgb
import uart_live_demo as live
from check_camera_preview_contract import Capture, Widget
from test_uart_resolution import fixed_frame, scalar_reference
import test_uart_resolution as batch
from image_reference import process_reference


class Device:
    """Partial-byte fake device with an independently selected actual profile."""
    def __init__(self, width, height, fault=None):
        self.width, self.height, self.fault = width, height, fault
        self.pending, self.received = bytearray(), bytearray()
        self.timeout = self.write_timeout = 0.01
        self.closed = False
        self.requests = []

    def reset_input_buffer(self):
        self.pending.clear()

    def close(self):
        self.closed = True

    def read(self, wanted):
        count = min(wanted, len(self.pending), 983)
        body = bytes(self.pending[:count])
        del self.pending[:count]
        return body

    def write(self, data):
        accepted = min(len(data), 1777)
        self.received.extend(data[:accepted])
        if len(self.received) >= REQUEST.size:
            header = REQUEST.unpack(self.received[:REQUEST.size])
            _, seq, command, mode, width, height, count, crc = header
            if len(self.received) >= REQUEST.size + count:
                payload = bytes(self.received[REQUEST.size:REQUEST.size + count])
                assert zlib.crc32(payload) & 0xFFFFFFFF == crc
                self.requests.append((command, mode, width, height, payload))
                if command == 1:
                    body = (b"pynq_uart_image_v1" if self.width == 128 else
                            b"pynq_uart_image_256x192_v1")
                    if self.fault == "identity":
                        body = b"x" * len(body)
                    out_width, out_height, core = self.width, self.height, 0
                else:
                    assert (width, height, count) == (self.width, self.height, self.width * self.height * 3)
                    assert payload == fixed_frame(0, width, height).tobytes()
                    out_width, out_height = ((width, height) if mode in (0, 4)
                                             else (width - 2, height - 2))
                    body = (np.arange(out_width * out_height, dtype=np.uint32) % 251).astype(np.uint8).tobytes()
                    core = 2
                response = [RESPONSE_MAGIC, seq, 0, out_width, out_height,
                            len(body), zlib.crc32(body) & 0xFFFFFFFF, core]
                if command == 2:
                    if self.fault == "shape":
                        response[3] -= 1
                    elif self.fault == "oversize":
                        response[5] = self.width * self.height + 1
                    elif self.fault == "crc":
                        response[6] ^= 1
                self.pending.extend(RESPONSE.pack(*response) + body)
                del self.received[:REQUEST.size + count]
        return accepted


def main():
    checks = []
    for width, height in ((128, 96), (256, 192)):
        image = fixed_frame(0, width, height)
        device = Device(width, height)
        with FrameClient("HOST_PROFILE", transport=device, width=width, height=height) as client:
            for mode in range(5):
                actual, metrics = client.process(image, mode)
                shape = (height, width) if mode in (0, 4) else (height - 2, width - 2)
                expected = (np.arange(np.prod(shape), dtype=np.uint32) % 251).astype(np.uint8).reshape(shape)
                assert np.array_equal(actual, expected)
                assert metrics["request_payload_bytes"] == width * height * 3
                assert metrics["response_payload_bytes"] == int(np.prod(shape))
        assert device.closed
        # Camera conversion still reads exactly once and produces selected RGB bytes.
        bgr = np.random.default_rng(width).integers(0, 256, (480, 640, 3), dtype=np.uint8)
        capture = Capture(bgr)
        rgb, source_shape, source = read_camera_rgb(capture, True, width, height)
        assert capture.reads == 1 and source_shape == [480, 640, 3]
        assert np.array_equal(source, bgr[..., ::-1])
        expected_rgb = cv2.cvtColor(cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        assert rgb.tobytes() == expected_rgb.tobytes()
        # Both fixed inputs must agree with the independent Python-integer path.
        for index in (0, 1):
            fixed = fixed_frame(index, width, height)
            for mode in range(5):
                assert np.array_equal(process_reference(fixed, mode), scalar_reference(fixed, mode))
        checks.append({"name": "%dx%d_five_modes_transport_capture_and_dual_reference" % (width, height), "passed": True})

    for width, height, device_width, device_height in ((128, 96, 256, 192), (256, 192, 128, 96)):
        device = Device(device_width, device_height)
        client = FrameClient("HOST_WRONG_PROFILE", transport=device, width=width, height=height)
        try:
            client.open()
        except UARTProtocolError:
            pass
        else:
            raise AssertionError("Cross-profile firmware was accepted")
        assert client.closed and device.closed
        checks.append({"name": "reject_%dx%d_host_on_%dx%d_device" % (width, height, device_width, device_height), "passed": True})

    for fault in ("identity", "shape", "oversize", "crc"):
        device = Device(256, 192, fault)
        client = FrameClient("HOST_FAULT", transport=device, width=256, height=192)
        try:
            client.open()
            client.process(fixed_frame(0, 256, 192), 1)
        except UARTProtocolError:
            pass
        else:
            raise AssertionError("Invalid 256 profile response accepted: " + fault)
        assert device.closed and client.closed
        checks.append({"name": "reject_256_" + fault, "passed": True})

    device = Device(256, 192)
    with FrameClient("HOST_BAD_INPUT", transport=device, width=256, height=192) as client:
        sent = len(device.requests)
        try:
            client.process(np.zeros((96, 128, 3), dtype=np.uint8), 0)
        except ValueError:
            pass
        else:
            raise AssertionError("128 input accepted by 256 host")
        assert len(device.requests) == sent
    for size in ((128, 192), (256, 96), (320, 240), (True, 96), (128.0, 96)):
        try:
            resolution_profile(*size)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsupported profile accepted")
    checks.append({"name": "reject_input_shape_and_unsupported_profiles_before_io", "passed": True})

    # Exercise the actual render path with PIL-only stubs: 256 output uses 2x.
    demo = live.LiveDemo.__new__(live.LiveDemo)
    demo.input_label, demo.output_label = Widget(), Widget()
    demo.input_panel, demo.output_panel = Widget(), Widget()
    demo.metrics = SimpleNamespace(set=lambda value: None)
    demo.evidence = SimpleNamespace(set=lambda value: None)
    original_view = [True]
    demo.show_source = SimpleNamespace(get=lambda: original_view[0])
    rgb = fixed_frame(0, 256, 192)
    actual = process_reference(rgb, 1)
    metrics = {"mode": 1, "source_bgr_shape": [480, 640, 3], "frame": 0,
               "uart_roundtrip_seconds": 1.2, "verified_loop_frames_per_second": 0.8}
    source = cv2.resize(rgb, (640, 480))
    event = (rgb, actual, metrics, str(ROOT / "output/uart_live/session_stub"), source)
    with patch.object(live.ImageTk, "PhotoImage", lambda picture: picture.copy()):
        demo.render_frame(event)
        assert "256×192" in demo.input_panel.properties["text"]
        assert "254×190" in demo.output_panel.properties["text"]
        assert demo.output_label.properties["image"].size == (508, 380)
        assert np.array_equal(np.asarray(demo.output_label.properties["image"]),
                              np.repeat(np.repeat(actual, 2, axis=0), 2, axis=1))
        original_view[0] = False
        demo.refresh_preview()
        assert demo.input_label.properties["image"].size == (512, 384)
        assert "放大2倍" in demo.input_panel.properties["text"]
    checks.append({"name": "256_renderer_true_geometry_and_2x_display", "passed": True})

    # Exercise the actual batch writer/summary gates without using any device.
    class BatchClient:
        fault = None
        instances = []

        def __init__(self, port, baudrate, timeout, width, height):
            self.width, self.height, self.closed = width, height, False
            self.firmware_info = resolution_profile(width, height)[2].decode("ascii")
            self.info_roundtrip_seconds = 0.01
            self.instances.append(self)

        def open(self):
            return self

        def process(self, rgb, mode):
            actual = scalar_reference(rgb, mode)
            checksum = zlib.crc32(actual.tobytes()) & 0xFFFFFFFF
            return actual, {"uart_roundtrip_seconds": 0.01, "sequence": 1,
                            "core_status": 2, "response_crc32": checksum ^ (self.fault == "crc"),
                            "request_payload_bytes": rgb.nbytes, "response_payload_bytes": actual.nbytes}

        def close(self):
            self.closed = True
            if self.fault == "cleanup":
                raise RuntimeError("injected close failure")

    with tempfile.TemporaryDirectory(prefix="resolution_profiles_", dir=ROOT / "tmp") as name:
        folder = Path(name).resolve()
        assert folder.is_relative_to(ROOT.resolve())
        for action, fault, info in (("fixed", None, False), ("info", None, True),
                                    ("crc_fail", "crc", False), ("cleanup_fail", "cleanup", False)):
            output = folder / action
            BatchClient.fault = fault
            argv = ["--port", "HOST_BATCH", "--width", "256", "--height", "192", "--output", str(output)]
            if info:
                argv += ["--info"]
            elif fault:
                argv += ["--frames", "1", "--mode", "0"]
            with patch.object(batch, "FrameClient", BatchClient), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = batch.main(argv)
            result = json.loads((output / "result.json").read_text(encoding="utf-8"))
            assert BatchClient.instances[-1].closed
            if fault:
                assert code == 1 and result["requested_action_passed"] is False
                assert result["error"] if fault == "crc" else result["cleanup_errors"]
            elif info:
                assert code == 0 and result["info_handshake_passed"]
                assert not result["hardware_test"] and result["actual_fpga_frames_verified"] == 0
            else:
                assert code == 0 and len(result["cases"]) == 10
                assert result["actual_output_pixels"] == 486168
                assert result["error"] is None and result["cleanup_errors"] == []
                assert len(result["inputs"]) == 2 and not result["camera_test"]
                assert all(item["independent_scalar_reference_match"] and item["exact_match"]
                           for item in result["cases"])
            checks.append({"name": "batch_" + action + "_summary_and_cleanup", "passed": True})
    print(json.dumps({"all_passed": True, "hardware_access": False,
                      "gui_window_created": False, "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
