"""Offline integration checks for the production part-measurement GUI methods.

No Tk window, camera or UART is opened. Widgets/devices are stubs; the real
worker, case writer, callbacks and Pillow rendering path remain under test.
Synthetic pixels are not evidence of real-camera metrology accuracy.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
import uart_live_demo as live
from image_reference import process_reference
from part_measurement import analyze_edges


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, width=700, height=520):
        self.properties = {}
        self.width, self.height = width, height

    def configure(self, **kwargs):
        self.properties.update(kwargs)

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height


def demo_stub():
    demo = live.LiveDemo.__new__(live.LiveDemo)
    demo._measurement_lock = threading.Lock()
    demo._measurement_settings = dict(
        enabled=True, threshold=40, min_area=80, close_gaps=True, roi=None, mm_per_pixel=None,
        calibration_points=None, calibration_known_mm=None, version=1)
    demo._measurement_shape = None
    demo._calibration_pending = None
    demo._roi_drag_start = None
    demo._output_geometry = None
    demo._display_event = None
    demo.measurement_info = Value()
    demo.output_label = Widget()
    return demo


def worker_case(base, name, mode=2, mismatch=False, measurement_fault=False,
                inflight=False, close_gaps=True):
    demo = demo_stub()
    demo._measurement_settings["close_gaps"] = close_gaps
    demo.args = SimpleNamespace(output_root=base / name, timeout=1,
                                camera_name="MF200 Camera", max_frames=1,
                                width=256, height=192)
    demo._mode = mode
    demo._mode_lock = threading.Lock()
    demo._events = queue.Queue()
    demo._frames = queue.Queue(maxsize=1)
    events = []
    rgb = np.full((192, 256, 3), 240, np.uint8)
    rgb[50:140, 65:190] = 20

    class Client:
        firmware_info = "stub_256"

        def __init__(self, *args, **kwargs):
            pass

        def open(self):
            events.append("open")

        def process(self, source, selected):
            actual = process_reference(source, selected)
            if mismatch:
                actual = actual.copy()
                actual[0, 0] ^= 1
            if inflight:
                with demo._mode_lock:
                    demo._mode = 2
            return actual, dict(uart_roundtrip_seconds=0.01,
                                response_crc32=123)

        def close(self):
            events.append("uart_close")

    class Capture:
        def release(self):
            events.append("camera_release")

    def open_camera(*args, **kwargs):
        return Capture(), dict(selected=dict(name="MF200 Camera", index=0,
                                             vid="0c45", pid="6366"))

    def read_camera(*args, **kwargs):
        return rgb.copy(), [192, 256, 3], rgb.copy()

    analyzer = (patch.object(live, "analyze_edges",
                            side_effect=RuntimeError("injected geometry fault"))
                if measurement_fault else
                patch.object(live, "analyze_edges", wraps=analyze_edges))
    with patch.object(live, "FrameClient", Client), \
         patch.object(live, "open_selected_camera", open_camera), \
         patch.object(live, "read_camera_rgb", read_camera), analyzer as analyze:
        demo.worker("HOST_MEASUREMENT_STUB", 2000000, threading.Event())

    files = list((base / name).glob("session_*/result.json"))
    assert len(files) == 1
    result_path = files[0]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    case = result_path.parent / ("frame000000_mode%d" % mode)
    assert events[-2:] == ["camera_release", "uart_close"]
    assert events.count("camera_release") == events.count("uart_close") == 1
    assert result["cleanup_errors"] == []
    if mismatch:
        assert result["error"].startswith("AssertionError")
        assert analyze.call_count == 0 and not (case / "measurement.json").exists()
    elif measurement_fault:
        assert "injected geometry fault" in result["error"]
        assert not result["camera_test"]
    elif inflight or mode != 2:
        assert result["error"] is None and analyze.call_count == 0
        assert result["measurement_frames"] == 0
    else:
        assert result["error"] is None and result["measurement_frames"] == 1
        record = json.loads((case / "measurement.json").read_text(encoding="utf-8"))
        assert record["source"] == "verified_fpga_sobel"
        assert record["computation"] == "host"
        assert record["result"]["long_mm"] is None
        assert record["result"]["status"] == "ok"
        assert analyze.call_args.kwargs["close_gaps"] is close_gaps
        assert record["settings"]["close_gaps"] is close_gaps
        assert (case / "measurement_overlay.png").is_file()
        with Image.open(case / "actual.png") as picture:
            assert np.array_equal(np.asarray(picture), process_reference(rgb, 2))
    return demo, result, case, rgb


def run_checks():
    checks = []
    demo = demo_stub()
    for width, height, scale in ((254, 190, 2), (126, 94, 4)):
        demo._output_geometry = (width, height, scale)
        left = (700 - width * scale) / 2
        top = (520 - height * scale) / 2
        assert demo.output_point(left + 10.5 * scale, top + 20.5 * scale) == [10.5, 20.5]
        assert demo.output_point(left - 1, top) is None
        assert demo.output_point(left + width * scale, top) is None
        checks.append("%dx%d_scale%d_centered_coordinate_mapping" % (width, height, scale))
    snapshot = demo._measurement_snapshot()
    snapshot["roi"] = [1, 2, 3, 4]
    assert demo._measurement_snapshot()["roi"] is None
    checks.append("settings_snapshot_independent")

    temp_parent = (ROOT / "tmp").resolve()
    temp_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="part_gui_", dir=temp_parent) as name:
        base = Path(name).resolve()
        assert base.is_relative_to(temp_parent)
        demo, result, case, rgb = worker_case(base, "verified_output")
        checks.append("worker_verified_sobel_saves_distinct_overlay_and_json_preserves_raw")
        worker_case(base, "mismatch", mismatch=True)
        checks.append("worker_mismatch_never_measures_and_releases")
        worker_case(base, "geometry_fault", measurement_fault=True)
        checks.append("worker_geometry_fault_releases")
        worker_case(base, "inflight_mode", mode=0, inflight=True)
        checks.append("worker_completed_mode_not_changed_selector")

        actual = process_reference(rgb, 2)
        metrics = result["cases"][0]
        metrics["verified_loop_frames_per_second"] = 0.8
        demo.input_label, demo.input_panel, demo.output_panel = Widget(), Widget(), Widget()
        demo.metrics, demo.evidence, demo.show_source = Value(), Value(), Value(True)
        with patch.object(live.ImageTk, "PhotoImage", lambda picture: picture.copy()):
            event = (rgb, actual, metrics, str(case.parent), rgb)
            demo.render_frame(event)
            assert "电脑端测量叠加" in demo.output_panel.properties["text"]
            assert "尚未标定" in demo.measurement_info.value
            demo._update_measurement_settings(threshold=41)
            demo.render_frame(event)
            assert "电脑端测量叠加" not in demo.output_panel.properties["text"]
            assert "等待" in demo.measurement_info.value
            assert np.array_equal(np.asarray(demo.output_label.properties["image"]),
                                  np.repeat(np.repeat(actual, 2, axis=0), 2, axis=1))
        checks.append("renderer_stale_settings_suppresses_old_measurement")

        toggle_demo = demo_stub()
        assert toggle_demo._measurement_snapshot()["close_gaps"] is True
        toggle_demo.close_gaps_var = Value(False)
        toggle_demo.refresh_preview = lambda: None
        version_before = toggle_demo._measurement_snapshot()["version"]
        toggle_demo.gap_connection_toggled()
        snapshot = toggle_demo._measurement_snapshot()
        assert snapshot["close_gaps"] is False and snapshot["version"] > version_before
        snapshot["close_gaps"] = True
        assert toggle_demo._measurement_snapshot()["close_gaps"] is False
        _, gap_result, _, _ = worker_case(base, "no_gap_connection", close_gaps=False)
        assert gap_result["cases"][0]["measurement"]["result"]["close_gaps"] is False
        checks.append("gap_connection_toggle_snapshot_and_worker_argument")

    demo = demo_stub()
    demo._output_geometry = (254, 190, 2)
    demo._display_event = (None, None, {"mode": 2})
    demo.known_length_var = Value("20")
    demo.refresh_preview = lambda: None
    left, top = (700 - 508) / 2, (520 - 380) / 2

    def pointer(px, py):
        return SimpleNamespace(x=left + px * 2, y=top + py * 2)

    demo.begin_calibration()
    assert demo._calibration_pending is not None
    demo.measurement_pointer_down(pointer(20, 30))
    demo.measurement_pointer_up(pointer(20, 30))
    demo.measurement_pointer_down(pointer(60, 30))
    demo.measurement_pointer_up(pointer(60, 30))
    assert demo._measurement_snapshot()["mm_per_pixel"] == 0.5
    demo._reset_measurement_geometry()
    assert demo._measurement_snapshot()["mm_per_pixel"] is None
    assert demo._measurement_snapshot()["roi"] is None
    checks.append("calibration_two_point_and_reset_geometry")

    demo._update_measurement_settings(mm_per_pixel=0.5,
                                      calibration_points=[[1, 1], [20, 1]],
                                      calibration_known_mm=9.5)
    demo.known_length_var.set("NaN")
    demo.begin_calibration()
    assert demo._measurement_snapshot()["mm_per_pixel"] is None
    assert demo._calibration_pending is None
    checks.append("invalid_known_length_clears_previous_scale")

    demo.known_length_var.set("20")
    demo.begin_calibration()
    demo.measurement_pointer_down(pointer(10, 10))
    demo.measurement_pointer_down(pointer(11, 10))
    assert demo._measurement_snapshot()["mm_per_pixel"] is None
    assert demo._calibration_pending is None
    checks.append("too_short_calibration_line_rejected")

    demo.measurement_pointer_down(pointer(80, 70))
    demo.measurement_pointer_up(pointer(20, 10))
    assert demo._measurement_snapshot()["roi"] == [20, 10, 81, 71]
    checks.append("reverse_drag_normalized_exclusive_roi")
    roi = demo._measurement_snapshot()["roi"]
    demo.measurement_pointer_down(SimpleNamespace(x=left - 1, y=top))
    demo.measurement_pointer_up(pointer(25, 25))
    assert demo._measurement_snapshot()["roi"] == roi
    checks.append("outside_image_point_rejected")
    assert len(checks) == 14
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="Write a new JSON receipt; refuses an existing file")
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("Output already exists; choose a new receipt path")
    checks = run_checks()
    source = ROOT / "software/uart_live_demo.py"
    receipt = dict(passed=True, created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   hardware_access=False, gui_window_created=False,
                   source_file="software/uart_live_demo.py",
                   source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   scope="Production GUI worker/render/callback methods with synthetic arrays and stubs; no device or Tk window. Does not validate real-camera measurement accuracy.",
                   checks=checks)
    text = json.dumps(receipt, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            target.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
