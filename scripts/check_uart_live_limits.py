"""Host-only regression checks for bounded GUI runs and evidence-path display.

No Tk window is created and all camera/UART resources are stubs. The actual
worker, case writer, cleanup and poll/control gate are exercised.
"""
import argparse
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
import uart_live_demo as live


class Value:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)


def worker_case(base, name, limit, stop_after=None, mismatch=False, cleanup_fault=False):
    events = []
    stop = threading.Event()
    owners = {}

    class Capture:
        def release(self):
            events.append("camera_release")
            if cleanup_fault:
                raise RuntimeError("injected release fault")

    class Client:
        def __init__(self, *args, **kwargs):
            self.firmware_info = "stub firmware"
            self.frames = 0
            owners["uart"] = self

        def open(self):
            events.append("uart_open")

        def process(self, rgb, mode):
            self.frames += 1
            assert mode == 0
            assert rgb.shape == (96, 128, 3)
            # Independent constant gray fixture; the worker still runs the real
            # reference and save_verified_case and decides whether it matches.
            actual = np.full((96, 128), 0 if mismatch else 128, dtype=np.uint8)
            if stop_after is not None and self.frames >= stop_after:
                stop.set()  # Stop arrives while a current transaction completes.
            return actual, {"uart_roundtrip_seconds": 0.01}

        def close(self):
            events.append("uart_close")

    def open_camera(name):
        events.append("camera_open")
        return Capture(), {"selected": {"name": name, "index": 0, "vid": "0c45", "pid": "6366"}}

    demo = live.LiveDemo.__new__(live.LiveDemo)
    demo.args = SimpleNamespace(output_root=base / name, timeout=1,
                                camera_name="MF200 Camera", max_frames=limit)
    demo._mode = 0
    demo._mode_lock = threading.Lock()
    demo._events = queue.Queue()
    demo._frames = queue.Queue(maxsize=1)
    demo._stop = stop
    demo._thread = None
    demo._terminal = None
    demo._cleanup_failed = False
    demo._close_requested = False
    demo.root = SimpleNamespace(after=lambda *args: None)
    demo.camera_info, demo.status, demo.evidence = Value(), Value(), Value()
    demo.start_button, demo.stop_button = Widget(), Widget()
    demo.port_entry, demo.baud_box = Widget(), Widget()
    demo.render_frame = lambda event: None  # Avoid ImageTk/Tk creation in host proof.
    with patch.object(live, "FrameClient", Client), \
         patch.object(live, "open_selected_camera", open_camera), \
         patch.object(live, "read_camera_rgb", lambda capture: (np.full((96, 128, 3), 128, dtype=np.uint8), [480, 640, 3])):
        demo.worker("HOST_STUB", 2000000, stop)
    files = list((base / name).glob("session_*/result.json"))
    assert len(files) == 1
    result = json.loads(files[0].read_text(encoding="utf-8"))
    assert events[-2:] == ["camera_release", "uart_close"], events
    assert events.count("camera_release") == events.count("uart_close") == 1
    demo.poll()
    assert "Users" not in demo.evidence.value and str(ROOT) not in demo.evidence.value
    if cleanup_fault:
        assert result["cleanup_errors"] == ["camera: injected release fault"]
        assert not result["camera_test"]
        assert demo._cleanup_failed and demo.start_button.state == "disabled"
        before = events[:]
        demo.start()  # The real restart gate must return without touching devices.
        assert events == before and demo._thread is None
    else:
        assert result["cleanup_errors"] == []
        assert demo.start_button.state == "normal"
    if mismatch:
        assert result["error"].startswith("AssertionError:")
        assert not result["camera_test"] and not result["frame_limit_reached"]
        assert len(result["cases"]) == 1 and not result["cases"][0]["exact_match"]
    else:
        assert result["error"] is None
        assert all(c["exact_match"] for c in result["cases"])
        expected_frames = min(limit, stop_after) if limit and stop_after else limit or stop_after
        assert len(result["cases"]) == expected_frames
        assert result["frame_limit_reached"] == bool(limit and expected_frames == limit)
        assert result["camera_test"] == (not cleanup_fault)
    assert result["max_frames"] == limit
    return {"case": name, "frames": len(result["cases"]), "passed": True}


def main():
    results = []
    temp_parent = (ROOT / "tmp").resolve()
    temp_parent.mkdir(exist_ok=True)
    # The generated temporary directory is verified inside the workspace before
    # TemporaryDirectory performs its eventual recursive cleanup.
    with tempfile.TemporaryDirectory(prefix="uart_live_limits_", dir=temp_parent) as name:
        base = Path(name).resolve()
        assert base.is_relative_to(ROOT.resolve())
        for kwargs in [dict(name="frame_limit", limit=3),
                       dict(name="early_stop", limit=5, stop_after=1),
                       dict(name="continuous_default", limit=0, stop_after=2),
                       dict(name="mismatch", limit=3, mismatch=True),
                       dict(name="cleanup_gate", limit=1, cleanup_fault=True)]:
            results.append(worker_case(base, **kwargs))
    inside = ROOT / "output/uart_live/session_example"
    assert live.evidence_display_path(inside) == "output/uart_live/session_example"
    external = Path.home() / "capture_private" / "session_external"
    assert live.evidence_display_path(external) == "session_external"
    results.append(dict(case="path_display", passed=True))
    assert live.nonnegative_frames("0") == 0 and live.nonnegative_frames("10") == 10
    try:
        live.nonnegative_frames("-1")
    except argparse.ArgumentTypeError:
        pass
    else:
        raise AssertionError("Negative frame limit accepted")
    results.append(dict(case="frame_limit_argument", passed=True))
    print(json.dumps({"all_passed": True, "hardware_access": False,
                      "gui_window_created": False, "cases": results}, indent=2))


if __name__ == "__main__":
    main()
