"""Real MF200 camera -> RGB24 UART -> ARM/DMA/FPGA acceptance test.

Only the explicitly matched MF200 DirectShow device is opened. No default
camera fallback, SD access, firmware loading, or Linux boot is performed.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

import numpy as np
from PIL import Image

from image_reference import MODES, process_reference
from uart_image_client import BAUDRATES, FrameClient, HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[1]
CAMERA_VID = "0c45"
CAMERA_PID = "6366"


def enumerate_windows_cameras():
    if os.name != "nt":
        raise RuntimeError("This explicit DirectShow camera selector requires Windows")
    helper = ROOT / "software" / "list_windows_cameras.ps1"
    if not helper.is_file():
        raise FileNotFoundError("Missing read-only DirectShow camera inventory helper")
    candidates = [shutil.which("pwsh.exe"), shutil.which("pwsh"),
                  str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PowerShell" / "7" / "pwsh.exe"),
                  shutil.which("powershell.exe")]
    shell = next((item for item in candidates if item and Path(item).is_file()), None)
    if shell is None:
        raise RuntimeError("PowerShell is required for the explicit camera inventory")
    result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
                            check=True, capture_output=True, encoding="utf-8-sig", timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    devices = json.loads(result.stdout)
    if not isinstance(devices, list):
        raise RuntimeError("Camera inventory is not a JSON array")
    seen = set()
    for device in devices:
        if (not isinstance(device, dict) or type(device.get("index")) is not int
                or device["index"] < 0 or device["index"] in seen
                or not isinstance(device.get("name"), str)
                or not isinstance(device.get("path"), str)):
            raise RuntimeError("Invalid or ambiguous DirectShow inventory")
        seen.add(device["index"])
    return devices


def select_camera(devices, camera_name):
    matches = [device for device in devices
               if device["name"].casefold() == camera_name.casefold()
               and "vid_" + CAMERA_VID in device["path"].casefold()
               and "pid_" + CAMERA_PID in device["path"].casefold()]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one named MF200 VID_0C45/PID_6366 device; no camera opened")
    return matches[0]


def anonymous_camera_metadata(devices, selected):
    def row(device):
        path = device["path"].casefold()
        vid, pid = re.search(r"vid_([0-9a-f]{4})", path), re.search(r"pid_([0-9a-f]{4})", path)
        return dict(index=device["index"], name=device["name"],
                    vid=vid.group(1) if vid else None, pid=pid.group(1) if pid else None)
    return dict(selected=row(selected), inventory=[row(device) for device in devices],
                unique_device_paths_omitted=True)


def read_camera_rgb(capture):
    import cv2
    ok, bgr = capture.read()
    if (not ok or bgr is None or bgr.dtype != np.uint8 or bgr.ndim != 3
            or bgr.shape[2] != 3 or min(bgr.shape[:2]) < 1):
        raise RuntimeError("Selected MF200 camera did not return a nonempty uint8 BGR frame")
    source_shape = list(bgr.shape)
    resized = cv2.resize(bgr, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    if rgb.shape != (HEIGHT, WIDTH, 3) or rgb.dtype != np.uint8:
        raise RuntimeError("Camera conversion produced an invalid fixed RGB input")
    return np.ascontiguousarray(rgb), source_shape


def open_selected_camera(camera_name="MF200 Camera", warmup_frames=20):
    import cv2
    devices = enumerate_windows_cameras()
    selected = select_camera(devices, camera_name)
    capture = cv2.VideoCapture(selected["index"], cv2.CAP_DSHOW)
    try:
        if not capture.isOpened():
            raise RuntimeError("Cannot open the explicitly selected MF200 DirectShow index")
        if capture.getBackendName().upper() != "DSHOW":
            raise RuntimeError("Unexpected capture backend; DirectShow selection is required")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        deadline = time.monotonic() + 15.0
        valid = 0
        attempts = 0
        shape = None
        while valid < warmup_frames:
            if time.monotonic() > deadline or attempts >= warmup_frames + 30:
                raise TimeoutError("MF200 warm-up did not complete within its deadline")
            attempts += 1
            try:
                _, shape = read_camera_rgb(capture)
                valid += 1
            except RuntimeError:
                continue
        # Detect hotplug/reordering during setup instead of opening index zero.
        selected_after = select_camera(enumerate_windows_cameras(), camera_name)
        if selected_after != selected:
            raise RuntimeError("Camera inventory changed during setup; refusing an ambiguous device")
        metadata = anonymous_camera_metadata(devices, selected)
        metadata.update(backend="DSHOW", warmup_frames=valid,
                        source_bgr_shape=shape, processed_rgb_shape=[HEIGHT, WIDTH, 3],
                        resize="OpenCV INTER_AREA", conversion="BGR to RGB")
        return capture, metadata
    except Exception:
        capture.release()
        raise


def create_result_directory(output=None, category="uart_camera"):
    if output is None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_utc_")
        output = ROOT / "output" / category / ("run_" + stamp + uuid.uuid4().hex[:8])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    return output.resolve()


def save_verified_case(directory, rgb, actual, expected, details, frame, mode, source_shape):
    difference = np.abs(actual.astype(np.int16) - expected.astype(np.int16)).astype(np.uint8)
    metrics = dict(details)
    metrics.update(frame=frame, mode=mode, mode_name=MODES[mode], source_bgr_shape=source_shape,
                   input_rgb_shape=list(rgb.shape), output_shape=list(actual.shape),
                   exact_match=bool(np.array_equal(actual, expected)),
                   mismatch_pixels=int(np.count_nonzero(difference)), max_abs_error=int(difference.max()))
    directory.mkdir(exist_ok=False)
    np.savez(directory / "pixels.npz", rgb=rgb, actual=actual, expected=expected, difference=difference)
    for name, array in (("input", rgb), ("actual", actual), ("expected", expected), ("difference", difference)):
        Image.fromarray(array).save(directory / (name + ".png"))
    (directory / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, choices=BAUDRATES, default=115200)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--camera-name", default="MF200 Camera")
    parser.add_argument("--frames", type=int, choices=(1, 2), default=2)
    parser.add_argument("--mode", choices=["all"] + [str(mode) for mode in MODES], default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    directory = create_result_directory(args.output)
    modes = list(MODES) if args.mode == "all" else [int(args.mode)]
    planned = args.frames * len(modes)
    result = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  port=args.port, baudrate=args.baud, source="real_mf200_camera",
                  camera_capture_test=False, camera_test=False, linux_test=False,
                  sd_used=False, hardware_test=False, planned_frames=planned, cases=[],
                  all_requested_frames_passed=False, cleanup_errors=[], error=None,
                  timing_note="UART roundtrip includes serial transfer and board processing, not PL latency; camera capture/reference/display are separate.")
    capture = client = None
    try:
        client = FrameClient(args.port, baudrate=args.baud, timeout=args.timeout)
        client.open()
        result.update(firmware_info=client.firmware_info, info_handshake_passed=True)
        capture, camera = open_selected_camera(args.camera_name)
        result["camera"] = camera
        result["camera_capture_test"] = True
        for index in range(args.frames):
            capture_started = time.perf_counter()
            rgb, shape = read_camera_rgb(capture)
            capture_seconds = time.perf_counter() - capture_started
            for mode in modes:
                reference_started = time.perf_counter()
                expected = process_reference(rgb, mode)
                reference_seconds = time.perf_counter() - reference_started
                actual, details = client.process(rgb, mode)
                details.update(capture_resize_seconds=capture_seconds,
                               host_numpy_reference_seconds=reference_seconds,
                               input_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())
                metrics = save_verified_case(directory / ("frame%d_mode%d" % (index, mode)),
                                             rgb, actual, expected, details, index, mode, shape)
                result["cases"].append(metrics)
                if not metrics["exact_match"]:
                    raise AssertionError("Real camera FPGA/reference mismatch")
                result["hardware_test"] = True
                print("UART_CAMERA_FRAME_PASS frame=%d mode=%d pixels=%d" %
                      (index, mode, actual.size), flush=True)
        result["all_requested_frames_passed"] = (len(result["cases"]) == planned
                                                  and all(row["exact_match"] for row in result["cases"]))
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        print("UART_CAMERA_FAILED " + result["error"], file=sys.stderr, flush=True)
    finally:
        # Close independently: a failed camera release must not skip UART close.
        for name, resource, close in (("camera", capture, "release"), ("uart", client, "close")):
            if resource is not None:
                try:
                    getattr(resource, close)()
                except Exception as exc:
                    result["cleanup_errors"].append("%s: %s" % (name, exc))
        if result["error"] or result["cleanup_errors"]:
            result["all_requested_frames_passed"] = False
        result["camera_test"] = bool(result["camera_capture_test"] and result["hardware_test"]
                                     and result["all_requested_frames_passed"])
        result["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("UART_CAMERA_EVIDENCE=" + str(directory), flush=True)
    if not result["camera_test"]:
        return 1
    print("UART_CAMERA_VERIFY_PASS frames=%d" % planned, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
