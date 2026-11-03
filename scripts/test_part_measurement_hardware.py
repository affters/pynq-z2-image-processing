"""Two finite real-UART Sobel/host-geometry cases; never opens a camera.

Run only after the live GUI releases UART. This is a digital-pixel geometry
acceptance, not physical millimetre accuracy or independent FPGA metrology.
Importing opens no device and writes no output.
"""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid
import zlib

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
from image_reference import process_reference
from part_measurement import analyze_edges, render_measurement_overlay
from uart_camera_demo import save_verified_case
from uart_image_client import BAUDRATES, FrameClient, resolution_profile
from test_uart_resolution import save_input, scalar_reference


def input_frame(frame, width, height):
    """One black rectangular cell region on white, then an all-white control."""
    if frame not in (0, 1):
        raise ValueError("The finite corpus has exactly two frames")
    rgb = np.full((height, width, 3), 255, np.uint8)
    if frame == 0:
        rgb[height // 3:2 * height // 3, width // 4:3 * width // 4] = 0
    return rgb


def assert_geometry(measurement, frame, width, height):
    """Check analytic Sobel outer pixel-centre spans, never real-world accuracy."""
    if frame == 0:
        # A filled step boundary yields two outer Sobel pixel rows/columns.
        # Their centre-to-centre span is the source region's cell count plus 1.
        target_long, target_short = sorted((3 * width // 4 - width // 4 + 1,
                                           2 * height // 3 - height // 3 + 1), reverse=True)
        if measurement["status"] != "ok":
            raise AssertionError("Known rectangle did not yield a valid enclosed contour")
        if (abs(measurement["long_px"] - target_long) > 1
                or abs(measurement["short_px"] - target_short) > 1):
            raise AssertionError("Rectangle differs from analytic Sobel outer spans")
        expectation = dict(status="ok", long_px=target_long, short_px=target_short,
                           tolerance_px=1,
                           definition="Sobel outer-envelope pixel-centre span, not source cell count")
    else:
        if measurement["status"] != "no_contour":
            raise AssertionError("Uniform white control yielded a contour")
        if any(measurement[name] is not None for name in ("long_px", "short_px", "long_mm", "short_mm")):
            raise AssertionError("Uniform white control yielded an invalid size")
        expectation = dict(status="no_contour", long_px=None, short_px=None)
    if measurement["mm_per_pixel"] is not None or measurement["long_mm"] is not None or measurement["short_mm"] is not None:
        raise AssertionError("Uncalibrated digital test must not report millimetres")
    return expectation


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, choices=BAUDRATES, default=2000000)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=192)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        args.width, args.height, _ = resolution_profile(args.width, args.height)
    except ValueError as exc:
        parser.error(str(exc))
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    return args


def main(argv=None):
    args = arguments(argv)
    output = args.output
    if output is None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_utc_")
        output = ROOT / "output/part_measurement" / ("run_" + stamp + uuid.uuid4().hex[:8])
    # No existing directory, even empty, can be reused. Refuse before any device I/O.
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    result = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  source="fixed_digital_rectangle_and_uniform_white", width=args.width, height=args.height,
                  port=args.port, baudrate=args.baud, timeout_seconds=args.timeout, mode=2,
                  hardware_access_attempted=False, info_handshake_passed=False,
                  hardware_test_attempted=False, hardware_test=False,
                  camera_opened=False, camera_test=False, physical_accuracy_verified=False,
                  geometry_location="host_after_verified_fpga_sobel",
                  linux_test=False, sd_used=False, flash_written=False,
                  planned_frames=2, planned_output_pixels=2 * (args.width - 2) * (args.height - 2),
                  actual_fpga_frames_verified=0, actual_geometry_frames_verified=0,
                  actual_output_pixels=0, inputs=[], cases=[], source_sha256={},
                  all_requested_frames_passed=False, requested_action_passed=False,
                  error=None, cleanup_errors=[],
                  scope="Real FPGA Sobel pixels and host digital-contour geometry; no camera object or physical-mm accuracy test.",
                  timing_note="UART roundtrip includes transport and ARM/DMA/PL; not isolated PL latency or GUI FPS.")
    client = None
    try:
        for source in (Path(__file__).resolve(), ROOT / "software/part_measurement.py",
                       ROOT / "software/uart_image_client.py", ROOT / "software/image_reference.py",
                       ROOT / "scripts/test_uart_resolution.py", ROOT / "scripts/filter_reference.py"):
            result["source_sha256"][source.relative_to(ROOT).as_posix()] = sha256(source)
        result["hardware_access_attempted"] = True
        client = FrameClient(args.port, baudrate=args.baud, timeout=args.timeout,
                             width=args.width, height=args.height)
        client.open()
        result.update(info_handshake_passed=True, firmware_info=client.firmware_info,
                      info_roundtrip_seconds=client.info_roundtrip_seconds)
        print("PART_MEASUREMENT_INFO_PASS profile=%dx%d" % (args.width, args.height), flush=True)
        inputs = output / "inputs"
        inputs.mkdir()
        for frame in (0, 1):
            rgb = input_frame(frame, args.width, args.height)
            input_record = save_input(inputs, frame, rgb, None)
            result["inputs"].append(input_record)
            expected = process_reference(rgb, 2)
            independent = scalar_reference(rgb, 2)
            if not np.array_equal(expected, independent):
                raise AssertionError("Independent integer and vectorized Sobel references disagree")
            result["hardware_test_attempted"] = True
            actual, details = client.process(rgb, 2)
            if actual.dtype != np.uint8 or actual.shape != (args.height - 2, args.width - 2):
                raise AssertionError("Real response Sobel dtype/shape differs from selected profile")
            if details["request_payload_bytes"] != rgb.nbytes or details["response_payload_bytes"] != actual.nbytes:
                raise AssertionError("Transport lengths differ from saved input/output bytes")
            actual_bytes = actual.tobytes()
            actual_hash = hashlib.sha256(actual_bytes).hexdigest()
            if details["response_crc32"] != zlib.crc32(actual_bytes) & 0xFFFFFFFF:
                raise AssertionError("Saved actual CRC differs from response CRC")
            details.update(input_rgb_sha256=input_record["input_rgb_sha256"],
                           actual_sha256=actual_hash, independent_scalar_reference_match=True,
                           geometry_verified=False)
            case_dir = output / ("frame%d_mode2" % frame)
            metrics = save_verified_case(case_dir, rgb, actual, expected, details, frame, 2, None)
            result["cases"].append(metrics)
            difference = np.abs(actual.astype(np.int16) - expected.astype(np.int16)).astype(np.uint8)
            for name, array in (("actual", actual), ("expected", expected), ("difference", difference)):
                (case_dir / (name + ".gray")).write_bytes(array.tobytes())
            result["actual_output_pixels"] += actual.size
            if not metrics["exact_match"]:
                raise AssertionError("Real FPGA Sobel differs from both integer references")
            result["hardware_test"] = True
            result["actual_fpga_frames_verified"] += 1
            # Geometry is deliberately downstream of successful FPGA verification.
            measurement = analyze_edges(actual)
            measurement.update(physical_accuracy_verified=False, source="verified_fpga_sobel",
                               frame=frame, actual_sha256=actual_hash,
                               actual_response_crc32=details["response_crc32"])
            overlay = render_measurement_overlay(actual, measurement)
            if actual.tobytes() != actual_bytes:
                raise AssertionError("Geometry or overlay mutated verified FPGA pixels")
            measurement_path = case_dir / "measurement.json"
            measurement_path.write_text(json.dumps(measurement, indent=2, allow_nan=False), encoding="utf-8")
            overlay.save(case_dir / "measurement_overlay.png")
            expectation = assert_geometry(measurement, frame, args.width, args.height)
            metrics.update(geometry_verified=True, measurement_status=measurement["status"],
                           analytic_expectation=expectation,
                           measurement_path=measurement_path.relative_to(output).as_posix(),
                           measurement_sha256=sha256(measurement_path),
                           artifact_sha256={name: sha256(case_dir / name) for name in
                                            ("pixels.npz", "actual.gray", "expected.gray", "difference.gray",
                                             "measurement_overlay.png")})
            (case_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, allow_nan=False), encoding="utf-8")
            result["actual_geometry_frames_verified"] += 1
            print("PART_MEASUREMENT_FRAME_PASS frame=%d pixels=%d geometry=%s" %
                  (frame, actual.size, measurement["status"]), flush=True)
        result["all_requested_frames_passed"] = (
            len(result["cases"]) == 2 and result["actual_fpga_frames_verified"] == 2
            and result["actual_geometry_frames_verified"] == 2
            and result["actual_output_pixels"] == result["planned_output_pixels"])
        result["requested_action_passed"] = result["all_requested_frames_passed"]
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        result["requested_action_passed"] = result["all_requested_frames_passed"] = False
        print("PART_MEASUREMENT_FAILED " + result["error"], file=sys.stderr, flush=True)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                result["cleanup_errors"].append("uart: %s" % exc)
        if result["error"] or result["cleanup_errors"]:
            result["requested_action_passed"] = result["all_requested_frames_passed"] = False
        result["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            (output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        except Exception as exc:
            print("PART_MEASUREMENT_RESULT_WRITE_FAILED %s" % exc, file=sys.stderr, flush=True)
            result["requested_action_passed"] = False
        print("PART_MEASUREMENT_EVIDENCE=" + str(output), flush=True)
    if not result["requested_action_passed"]:
        return 1
    print("PART_MEASUREMENT_HARDWARE_VERIFY_PASS frames=2 pixels=%d" % result["actual_output_pixels"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
