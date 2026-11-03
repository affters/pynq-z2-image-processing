"""Jupyter live controls. Call show_demo(bitfile) on the PYNQ board."""
import io
import threading
import time

import numpy as np
from PIL import Image

from image_accelerator import ImageAccelerator
from image_demo import camera_frame
from image_reference import MODES, process_reference


def _png(image):
    data = io.BytesIO()
    Image.fromarray(image).save(data, format="PNG")
    return data.getvalue()


def show_demo(bitfile, camera=0):
    """Return controls; Stop releases camera/FPGA before another session starts."""
    import cv2
    import ipywidgets as widgets
    from IPython.display import display

    mode = widgets.Dropdown(options=[(name, number) for number, name in MODES.items()], description="Mode")
    start = widgets.Button(description="Start")
    stop = widgets.Button(description="Stop", disabled=True)
    input_view = widgets.Image(format="png", width=384, height=288)
    output_view = widgets.Image(format="png", width=384, height=288)
    status = widgets.Label(value="Stopped. Mode changes take effect on the next frame.")
    state = dict(thread=None, event=threading.Event())

    def work():
        capture, accelerator = None, None
        failure = None
        try:
            accelerator = ImageAccelerator(bitfile)
            capture = cv2.VideoCapture(camera)
            if not capture.isOpened():
                raise RuntimeError("USB camera cannot open")
            # Validate every newly selected mode once against the integer CPU reference.
            checked_modes = set()
            frames, period = 0, time.perf_counter()
            while not state["event"].is_set():
                rgb = camera_frame(capture)
                selected = mode.value
                processed, seconds = accelerator.process(rgb, selected)
                if selected not in checked_modes:
                    if not np.array_equal(processed, process_reference(rgb, selected)):
                        raise AssertionError("Pixel comparison failed for mode %d" % selected)
                    checked_modes.add(selected)
                input_view.value = _png(rgb)
                output_view.value = _png(processed)
                frames += 1
                elapsed = time.perf_counter()-period
                status.value = "FPGA %s | %.2f ms control+DMA | %.1f completed frames/s (Python loop)" % (
                    MODES[selected], seconds*1000, frames/max(elapsed, 1e-9))
                # This is the Python capture/process/widget-submission loop rate;
                # the browser render rate and sensor exposure latency are not measured.
                if elapsed > 2:
                    frames, period = 0, time.perf_counter()
        except Exception as error:
            failure = error
        finally:
            status.value = "Stopping: releasing camera and DMA..."
            cleanup_errors = []
            if capture is not None:
                try:
                    capture.release()
                except Exception as error:
                    cleanup_errors.append(str(error))
            if accelerator is not None:
                try:
                    accelerator.close()
                except Exception as error:
                    cleanup_errors.append(str(error))
            if cleanup_errors:
                status.value = "Cleanup failed; restart disabled: " + "; ".join(cleanup_errors)
                start.disabled, stop.disabled = True, True
            else:
                status.value = "Stopped" if failure is None else "Stopped: %s" % failure
                start.disabled, stop.disabled = False, True

    def begin(_):
        if state["thread"] is not None and state["thread"].is_alive():
            return
        state["event"].clear()
        start.disabled, stop.disabled = True, False
        state["thread"] = threading.Thread(target=work, daemon=True)
        state["thread"].start()

    def end(_):
        state["event"].set()
        stop.disabled = True
        status.value = "Stopping after the current frame..."

    start.on_click(begin)
    stop.on_click(end)
    panel = widgets.VBox([widgets.HBox([mode, start, stop]),
                          widgets.HBox([input_view, output_view]), status])
    display(panel)
    return panel
