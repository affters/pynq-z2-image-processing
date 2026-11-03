"""Host-only fault-injection checks; never import PYNQ or touch hardware."""
import gc
import hashlib
import json
from pathlib import Path
import sys
import threading
import types
import weakref

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
import image_accelerator as driver
import live_notebook as notebook


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeBuffer:
    """Model PynqBuffer's idempotent free and destructor, without allocation."""
    def __init__(self, name, events):
        self.name, self.events, self.freed = name, events, False

    def freebuffer(self):
        if not self.freed:
            self.events.append("free:" + self.name)
            self.freed = True

    def __del__(self):
        self.freebuffer()


class FakeMMIO:
    def __init__(self, mode, events):
        self.mode, self.events = mode, events

    def write(self, address, value):
        assert (address, value) == (0, 4), "Expected reset of both DMA channels"
        self.events.append("dma_reset")

    def read(self, address):
        if address == 0:
            return 4 if self.mode == "reset_stuck" else 0
        if address == 4:
            return 0 if self.mode == "tx_not_halted" else 1
        if address == 0x34:
            return 0 if self.mode == "rx_not_halted" else 1
        raise AssertionError("Unexpected MMIO read: 0x%x" % address)


def check_driver_failure(mode):
    events = []
    accelerator = driver.ImageAccelerator.__new__(driver.ImageAccelerator)
    accelerator.timeout = 0.002
    accelerator.closed, accelerator.healthy = False, True
    accelerator.dma = types.SimpleNamespace(mmio=FakeMMIO(mode, events))
    accelerator.gpio = types.SimpleNamespace(write=lambda address, value: events.append("core_reset"))
    accelerator.input_buffer = FakeBuffer("input", events)
    accelerator.output_buffers = {False: FakeBuffer("full", events), True: FakeBuffer("crop", events)}
    reference = weakref.ref(accelerator)
    if mode != "healthy":
        expected_error = TimeoutError if mode == "reset_stuck" else RuntimeError
        for _ in range(2):
            try:
                accelerator.close()
            except expected_error:
                pass
            else:
                raise AssertionError("Injected cleanup fault did not fail")
            assert not accelerator.closed and not accelerator.healthy
            assert driver._faulted_accelerators == [accelerator], "Quarantine must retain one strong reference"
            assert not any(event.startswith("free:") for event in events)
        del accelerator
        gc.collect()
        assert reference() is not None, "Faulted owner was collected before DMA was halted"
        assert not any(event.startswith("free:") for event in events), "Destructor released an active buffer"
        accelerator = reference()
        accelerator.dma.mmio.mode = "healthy"
    accelerator.close()
    assert accelerator.closed and not accelerator.healthy
    assert driver._faulted_accelerators == [], "Successful retry must leave quarantine"
    assert sorted(event for event in events if event.startswith("free:")) == ["free:crop", "free:full", "free:input"]
    completed_events = events[:]
    accelerator.close()
    assert events == completed_events, "Successful close must be idempotent"
    del accelerator
    gc.collect()
    assert reference() is None
    assert events == completed_events, "Destruction must not double-free buffers"
    return dict(case="driver_" + mode, passed=True, buffers_freed=3,
                retained_across_gc=mode != "healthy", successful_retry=mode != "healthy")


def check_notebook(case):
    events, controls = [], {}

    class Button:
        def __init__(self, description, disabled=False):
            self.description, self.disabled, self.callback = description, disabled, None

        def on_click(self, callback):
            self.callback = callback

        def click(self):
            assert not self.disabled, "Attempt to activate a disabled button"
            self.callback(self)

    class Label:
        def __init__(self, value):
            self.value = value

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, value):
            self._value = value
            events.append("status:" + value)

    class Box:
        def __init__(self, children):
            self.children = children

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target, self.alive = target, False

        def start(self):
            self.alive = True
            try:
                self.target()
            finally:
                self.alive = False

        def is_alive(self):
            return self.alive

    class Camera:
        def isOpened(self):
            return True

        def release(self):
            events.append("camera_release")
            if case == "camera_release_failure":
                raise RuntimeError("injected camera release failure")

    class Accelerator:
        def __init__(self, bitfile):
            events.append("accelerator_init")

        def process(self, rgb, mode):
            if case == "frame_failure":
                raise RuntimeError("injected frame failure")
            controls["stop"].click()
            return np.zeros((96, 128), dtype=np.uint8), 0.001

        def close(self):
            events.append("accelerator_close")
            if case == "dma_close_failure":
                raise RuntimeError("injected DMA close failure")

    widgets = types.ModuleType("ipywidgets")
    widgets.Button, widgets.Label, widgets.HBox, widgets.VBox = Button, Label, Box, Box
    widgets.Dropdown = lambda **kwargs: types.SimpleNamespace(value=kwargs["options"][0][1])
    widgets.Image = lambda **kwargs: types.SimpleNamespace(value=b"")
    cv2 = types.ModuleType("cv2")
    cv2.VideoCapture = lambda camera: Camera()
    ipython = types.ModuleType("IPython")
    display = types.ModuleType("IPython.display")
    display.display = lambda panel: None
    replacements = {"cv2": cv2, "ipywidgets": widgets, "IPython": ipython, "IPython.display": display}
    original_modules = {name: sys.modules.get(name) for name in replacements}
    original_fields = {name: getattr(notebook, name) for name in ("ImageAccelerator", "camera_frame", "_png", "threading")}
    try:
        sys.modules.update(replacements)
        notebook.ImageAccelerator = Accelerator
        notebook.camera_frame = lambda capture: np.zeros((96, 128, 3), dtype=np.uint8)
        notebook._png = lambda image: b"host-stub-png"
        notebook.threading = types.SimpleNamespace(Thread=ImmediateThread, Event=threading.Event)
        panel = notebook.show_demo("host-stub.bit")
        _, controls["start"], controls["stop"] = panel.children[0].children
        status = panel.children[2]
        before_start = len(events)
        controls["start"].click()
        active_events = events[before_start:]
        assert active_events.count("camera_release") == 1
        assert active_events.count("accelerator_close") == 1, "Camera cleanup failure must not skip DMA cleanup"
        terminal = active_events[-1]
        assert active_events.index("camera_release") < active_events.index("accelerator_close") < len(active_events)-1
        if case in ("dma_close_failure", "camera_release_failure"):
            assert terminal.startswith("status:Cleanup failed"), status.value
            assert controls["start"].disabled and controls["stop"].disabled
            assert not any(event.startswith("status:Stopped") for event in active_events)
        else:
            assert terminal.startswith("status:Stopped"), status.value
            assert not controls["start"].disabled and controls["stop"].disabled
            assert sum(event.startswith("status:Stopped") for event in active_events) == 1
        return dict(case="notebook_" + case, passed=True, cleanup_precedes_stopped=True,
                    restart_disabled=controls["start"].disabled)
    finally:
        for name, value in original_fields.items():
            setattr(notebook, name, value)
        for name, value in original_modules.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def main():
    files = (ROOT / "software" / "image_accelerator.py", ROOT / "software" / "live_notebook.py")
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    cases, failure = [], None
    original_time = driver.time
    try:
        assert driver._faulted_accelerators == [], "Host test requires a fresh, hardware-free process"
        driver.time = FakeClock()
        for mode in ("healthy", "reset_stuck", "tx_not_halted", "rx_not_halted"):
            cases.append(check_driver_failure(mode))
        driver.time = original_time
        for case in ("normal_stop", "frame_failure", "dma_close_failure", "camera_release_failure"):
            cases.append(check_notebook(case))
        for path in files:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == hashes[str(path.relative_to(ROOT))], "Source changed during checks; rerun"
    except Exception as error:
        failure = error
    finally:
        driver.time = original_time
    report = dict(hardware_test=False, test_method="host-only fault injection; no PYNQ imports, MMIO, or physical buffers",
                  source_sha256=hashes, passed=failure is None, cases=cases,
                  limitation="Checks Python ownership and UI cleanup ordering, not actual PYNQ DMA/reset hardware behavior")
    if failure is not None:
        report["error"] = "%s: %s" % (type(failure).__name__, failure)
    output = ROOT / "output" / "software"
    output.mkdir(parents=True, exist_ok=True)
    (output / "driver_lifecycle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failure is not None:
        raise failure
    print("DRIVER_LIFECYCLE_PASS cases=%d hardware_test=false" % len(cases))


if __name__ == "__main__":
    main()
