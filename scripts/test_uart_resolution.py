"""Explicit fixed/camera acceptance for 128x96 and 256x192 UART profiles.

Importing does not open devices. INFO proves identity/geometry only; image
acceptance also compares every actual output with two integer references.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
import zlib

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
from image_reference import MODES, process_reference
from uart_camera_demo import open_selected_camera, read_camera_rgb, save_verified_case
from uart_image_client import BAUDRATES, FrameClient
from filter_reference import equalize, window_filter


def fixed_frame(index, width, height):
    """Two deterministic inputs: structured color/edges, then uniform 128."""
    if index not in (0, 1):
        raise ValueError("The fixed corpus has exactly two input frames")
    if index == 1:
        return np.full((height, width, 3), 128, dtype=np.uint8)
    y, x = np.indices((height, width), dtype=np.uint32)
    rgb = np.empty((height, width, 3), dtype=np.uint8)
    rgb[..., 0] = (x * 255 // (width - 1)).astype(np.uint8)
    rgb[..., 1] = (y * 255 // (height - 1)).astype(np.uint8)
    rgb[..., 2] = (((x // 8 + y // 8) & 1) * 192 + 32).astype(np.uint8)
    # Include saturated color bars and high-contrast repeated vertical edges.
    colors = np.array(((0, 0, 0), (255, 255, 255), (255, 0, 0),
                       (0, 255, 0), (0, 0, 255), (255, 255, 0)), dtype=np.uint8)
    rgb[:height // 6] = colors[np.minimum(x[:height // 6] * 6 // width, 5)]
    band = rgb[height // 3:height // 2, width // 4:3 * width // 4]
    band[:] = (((np.arange(band.shape[1]) // 4) & 1) * 255)[None, :, None]
    return np.ascontiguousarray(rgb)


def scalar_reference(rgb, mode):
    """Independent Python integer path, avoiding vectorized gray arithmetic."""
    height, width, _ = rgb.shape
    gray = [(77 * int(r) + 150 * int(g) + 29 * int(b) + 128) >> 8
            for r, g, b in rgb.reshape(-1, 3)]
    if mode == 0:
        values, shape = gray, (height, width)
    elif mode == 4:
        values, shape = equalize(gray), (height, width)
    else:
        values = window_filter(gray, width, height, mode)
        shape = (height - 2, width - 2)
    return np.asarray(values, dtype=np.uint8).reshape(shape)


def save_input(directory, frame, rgb, source_shape):
    name = "frame%d" % frame
    raw = rgb.tobytes()
    Image.fromarray(rgb).save(directory / (name + ".png"))
    np.save(directory / (name + ".npy"), rgb, allow_pickle=False)
    (directory / (name + ".rgb")).write_bytes(raw)
    return dict(frame=frame, input_rgb_shape=list(rgb.shape),
                source_bgr_shape=source_shape,
                input_rgb_sha256=hashlib.sha256(raw).hexdigest(),
                input_rgb_bytes=len(raw), png="inputs/" + name + ".png",
                npy="inputs/" + name + ".npy", rgb="inputs/" + name + ".rgb")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, choices=BAUDRATES, default=2000000)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=192)
    parser.add_argument("--info", action="store_true")
    parser.add_argument("--source", choices=("fixed", "camera"), default="fixed")
    parser.add_argument("--camera-name", default="MF200 Camera")
    parser.add_argument("--frames", type=int, choices=(1, 2), default=2)
    parser.add_argument("--mode", choices=["all"] + [str(mode) for mode in MODES], default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if (args.width, args.height) not in ((128, 96), (256, 192)):
        parser.error("Supported profiles are exactly 128x96 and 256x192")
    return args


def main(argv=None):
    args = arguments(argv)
    directory = args.output
    if directory is None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_utc_")
        directory = ROOT / "output/uart_resolution" / ("run_" + stamp + uuid.uuid4().hex[:8])
    # Refuse every existing path, including an empty directory, before I/O.
    directory.mkdir(parents=True, exist_ok=False)
    directory = directory.resolve()
    modes = list(MODES) if args.mode == "all" else [int(args.mode)]
    planned = 0 if args.info else args.frames * len(modes)
    expected_pixels = 0 if args.info else args.frames * sum(
        (args.width - 2) * (args.height - 2) if mode in (1, 2, 3)
        else args.width * args.height for mode in modes)
    result = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  source="info_only" if args.info else args.source + "_rgb",
                  width=args.width, height=args.height,
                  port=args.port, baudrate=args.baud, timeout_seconds=args.timeout,
                  hardware_access_attempted=False, hardware_test_attempted=False,
                  info_handshake_passed=False, hardware_test=False,
                  camera_capture_test=False, camera_test=False,
                  linux_test=False, sd_used=False, planned_frames=planned,
                  planned_output_pixels=expected_pixels, actual_output_pixels=0,
                  actual_fpga_frames_verified=0, inputs=[], cases=[],
                  all_requested_frames_passed=None if args.info else False,
                  requested_action_passed=False, error=None, cleanup_errors=[],
                  timing_note="UART roundtrip includes transport and ARM/DMA/PL work; excludes capture, references and saving. It is not PL latency or displayed FPS.")
    capture = client = None
    try:
        result["hardware_access_attempted"] = True
        client = FrameClient(args.port, baudrate=args.baud, timeout=args.timeout,
                             width=args.width, height=args.height)
        client.open()
        result.update(info_handshake_passed=True, firmware_info=client.firmware_info,
                      info_roundtrip_seconds=client.info_roundtrip_seconds)
        print("UART_RESOLUTION_INFO_PASS width=%d height=%d firmware=%s" %
              (args.width, args.height, client.firmware_info), flush=True)
        if not args.info:
            input_directory = directory / "inputs"
            input_directory.mkdir()
            if args.source == "camera":
                capture, camera = open_selected_camera(args.camera_name, width=args.width, height=args.height)
                result.update(camera=camera, camera_capture_test=True)
            for frame in range(args.frames):
                started = time.perf_counter()
                if capture is not None:
                    rgb, source_shape = read_camera_rgb(capture, width=args.width, height=args.height)
                else:
                    rgb = fixed_frame(frame, args.width, args.height)
                    source_shape = None
                capture_seconds = time.perf_counter() - started
                if rgb.dtype != np.uint8 or rgb.shape != (args.height, args.width, 3):
                    raise AssertionError("Input does not match the explicitly selected profile")
                input_row = save_input(input_directory, frame, rgb, source_shape)
                result["inputs"].append(input_row)
                for mode in modes:
                    started = time.perf_counter()
                    expected = process_reference(rgb, mode)
                    independent = scalar_reference(rgb, mode)
                    reference_seconds = time.perf_counter() - started
                    if not np.array_equal(expected, independent):
                        raise AssertionError("Vectorized and independent scalar references disagree")
                    result["hardware_test_attempted"] = True
                    actual, details = client.process(rgb, mode)
                    shape = (args.height, args.width) if mode in (0, 4) else (args.height - 2, args.width - 2)
                    if actual.dtype != np.uint8 or actual.shape != shape:
                        raise AssertionError("Actual output dtype/shape differs from the selected mode")
                    if details["request_payload_bytes"] != rgb.nbytes or details["response_payload_bytes"] != actual.nbytes:
                        raise AssertionError("Response transport byte counts differ from saved arrays")
                    if details["response_crc32"] != zlib.crc32(actual.tobytes()) & 0xFFFFFFFF:
                        raise AssertionError("Saved output CRC differs from the validated response")
                    details.update(input_rgb_sha256=input_row["input_rgb_sha256"],
                                   host_references_seconds=reference_seconds,
                                   independent_scalar_reference_match=True,
                                   capture_resize_seconds=capture_seconds,
                                   input_width=args.width, input_height=args.height)
                    case_dir = directory / ("frame%d_mode%d" % (frame, mode))
                    metrics = save_verified_case(case_dir, rgb, actual, expected, details, frame, mode, source_shape)
                    for name, array in (("actual", actual), ("expected", expected), ("difference", np.abs(actual.astype(np.int16) - expected.astype(np.int16)).astype(np.uint8))):
                        (case_dir / (name + ".gray")).write_bytes(array.tobytes())
                    result["cases"].append(metrics)
                    result["actual_output_pixels"] += actual.size
                    if not metrics["exact_match"]:
                        raise AssertionError("Actual FPGA pixels differ from both integer references")
                    result["hardware_test"] = True
                    result["actual_fpga_frames_verified"] += 1
                    print("UART_RESOLUTION_FRAME_PASS frame=%d mode=%d pixels=%d roundtrip_seconds=%.6f" %
                          (frame, mode, actual.size, details["uart_roundtrip_seconds"]), flush=True)
            result["all_requested_frames_passed"] = (
                len(result["cases"]) == planned and result["actual_fpga_frames_verified"] == planned
                and result["actual_output_pixels"] == expected_pixels)
        result["requested_action_passed"] = (result["info_handshake_passed"] if args.info else
                                             result["all_requested_frames_passed"])
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["requested_action_passed"] = False
        print("UART_RESOLUTION_FAILED " + result["error"], file=sys.stderr, flush=True)
    finally:
        for name, resource, method in (("camera", capture, "release"), ("uart", client, "close")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception as exc:
                    result["cleanup_errors"].append("%s: %s" % (name, exc))
        if result["error"] or result["cleanup_errors"]:
            result["requested_action_passed"] = False
            if not args.info:
                result["all_requested_frames_passed"] = False
        result["camera_test"] = bool(result["camera_capture_test"] and result["hardware_test"]
                                     and result["requested_action_passed"])
        result["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("UART_RESOLUTION_EVIDENCE=" + str(directory), flush=True)
    if not result["requested_action_passed"]:
        return 1
    print("UART_RESOLUTION_VERIFY_PASS source=%s frames=%d pixels=%d" %
          (result["source"], planned, result["actual_output_pixels"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
