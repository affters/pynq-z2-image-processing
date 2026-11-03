"""Host-only proof that source preview preserves the FPGA input and output."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import cv2

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
import uart_camera_demo as camera
import uart_live_demo as live


class Capture:
    def __init__(self, bgr):
        self.bgr = bgr
        self.reads = 0

    def read(self):
        self.reads += 1
        return True, self.bgr.copy()


class Widget:
    def __init__(self):
        self.properties = {}

    def configure(self, **kwargs):
        self.properties.update(kwargs)

    def winfo_width(self):
        return 540

    def winfo_height(self):
        return 405


def main():
    backup = ROOT / "tmp/camera_clarity_20261103/source_before/uart_camera_demo.py"
    previous = None
    if backup.is_file():
        spec = importlib.util.spec_from_file_location("camera_before_source_preview", backup)
        previous = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(previous)
    rng = np.random.default_rng(20261103)
    fixtures = [np.full((480, 640, 3), [17, 91, 203], dtype=np.uint8),
                rng.integers(0, 256, (480, 640, 3), dtype=np.uint8),
                rng.integers(0, 256, (61, 107, 3), dtype=np.uint8)]
    for bgr in fixtures:
        captures = [Capture(bgr) for _ in range(3)]
        original = previous.read_camera_rgb(captures[0]) if previous is not None else None
        default = camera.read_camera_rgb(captures[1])
        extended = camera.read_camera_rgb(captures[2], include_source=True)
        assert len(default) == 2 and len(extended) == 3
        assert default[1] == extended[1] == list(bgr.shape)
        assert all(capture.reads == 1 for capture in captures[1:])
        assert default[0].shape == extended[0].shape == (96, 128, 3)
        expected_fixed = cv2.resize(bgr[:, :, ::-1], (128, 96), interpolation=cv2.INTER_AREA)
        assert default[0].tobytes() == extended[0].tobytes() == expected_fixed.tobytes()
        if original is not None:
            assert captures[0].reads == 1 and original[1] == list(bgr.shape)
            assert extended[0].tobytes() == original[0].tobytes()
        assert extended[2].dtype == np.uint8 and extended[2].flags.c_contiguous
        assert np.array_equal(extended[2], bgr[:, :, ::-1])

    demo = live.LiveDemo.__new__(live.LiveDemo)
    demo.input_label, demo.output_label = Widget(), Widget()
    demo.input_panel, demo.output_panel = Widget(), Widget()
    demo.metrics = SimpleNamespace(set=lambda value: None)
    demo.evidence = SimpleNamespace(set=lambda value: None)
    original_view = [True]
    demo.show_source = SimpleNamespace(get=lambda: original_view[0])
    source = fixtures[1][:, :, ::-1].copy()
    fixed, shape = camera.read_camera_rgb(Capture(fixtures[1]))
    actual = np.arange(96 * 128, dtype=np.uint8).reshape(96, 128)
    metrics = dict(mode=0, source_bgr_shape=shape, frame=0,
                   uart_roundtrip_seconds=0.3, verified_loop_frames_per_second=3.2)
    event = (fixed, actual, metrics, str(ROOT / "output/uart_live/session_stub"), source)
    with patch.object(live.ImageTk, "PhotoImage", lambda picture: picture.copy()):
        demo.render_frame(event)
        assert demo.input_label.properties["image"].size == (540, 405)
        assert "640×480" in demo.input_panel.properties["text"]
        assert "128×96" in demo.input_panel.properties["text"]
        expected_output = np.repeat(np.repeat(actual, 4, axis=0), 4, axis=1)
        assert np.array_equal(np.asarray(demo.output_label.properties["image"]), expected_output)
        original_view[0] = False
        demo.refresh_preview()
        assert demo._display_event is event
        assert np.array_equal(np.asarray(demo.input_label.properties["image"]),
                              np.repeat(np.repeat(fixed, 4, axis=0), 4, axis=1))
        assert np.array_equal(np.asarray(demo.output_label.properties["image"]), expected_output)
    print(json.dumps({"passed": True, "hardware_access": False, "gui_window_created": False,
                      "source_fixtures": len(fixtures), "fixed_rgb_matches_independent_resize": True,
                      "legacy_snapshot_compared": previous is not None,
                      "legacy_fixed_rgb_byte_identical": True if previous is not None else None,
                      "one_capture_read_per_call": True, "source_rgb_channel_order": "RGB",
                      "preview_aspect_and_toggle_passed": True,
                      "hardware_output_display_unchanged": True}, indent=2))


if __name__ == "__main__":
    main()
