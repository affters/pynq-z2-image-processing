"""Validate the temporary UART/ARM/DMA/PL path using the existing two RGB fixtures.

This command opens a real explicitly named serial port. It does not configure
JTAG/FPGA, boot Linux, or access SD/Flash. Load matching firmware first.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

import numpy as np
from PIL import Image

from image_reference import MODES, process_reference
from uart_image_client import BAUDRATES, FrameClient, HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "output" / "hardware" / "run_20261029_074543_utc"


def fixture_frame(directory, index):
    source = directory / ("input_frame%d.bin" % index)
    data = source.read_bytes()
    if len(data) != WIDTH * HEIGHT * 4:
        raise ValueError("Fixture input has unexpected size: " + str(source))
    words = np.frombuffer(data, dtype="<u4").reshape(HEIGHT, WIDTH)
    if np.any(words & 0xFF000000):
        raise ValueError("Fixture input has nonzero high bits: " + str(source))
    rgb = np.stack(((words >> 16) & 255, (words >> 8) & 255, words & 255), axis=-1).astype(np.uint8)
    return rgb, dict(path=str(source), sha256=hashlib.sha256(data).hexdigest())


def create_output(path):
    if path is None:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_utc_")
        path = ROOT / "output" / "uart_demo" / ("run_" + stamp + uuid.uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path.resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Explicit FTDI UART port, e.g. COM6")
    parser.add_argument("--baud", type=int, choices=BAUDRATES, default=115200)
    parser.add_argument("--timeout", type=float, default=20.0, help="Finite deadline per complete UART transaction")
    parser.add_argument("--info", action="store_true", help="Only perform the short firmware identity handshake")
    parser.add_argument("--frames", type=int, choices=(1, 2), default=2)
    parser.add_argument("--mode", choices=["all"] + [str(mode) for mode in MODES], default="all")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path, help="New directory; an existing path is always rejected")
    args = parser.parse_args(argv)
    output = create_output(args.output)
    modes = list(MODES) if args.mode == "all" else [int(args.mode)]
    planned = 0 if args.info else args.frames * len(modes)
    manifest = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    source="info_only" if args.info else "fixed_rgb_fixtures",
                    port=args.port, baudrate=args.baud, timeout_seconds=args.timeout,
                    info_handshake_passed=False, hardware_test_attempted=False,
                    hardware_test=False, actual_fpga_frames_verified=0,
                    camera_test=False, linux_test=False, planned_frames=planned,
                    all_requested_frames_passed=None if args.info else False,
                    requested_action_passed=False, cases=[], inputs=[], error=None,
                    timing_note="uart_roundtrip includes UART transfer, ARM control and FPGA work; excludes host RGB packing/reference/display. It is not PL latency or video FPS.")
    try:
        frames = []
        if not args.info:
            input_directory = output / "inputs"
            input_directory.mkdir()
            for index in range(args.frames):
                rgb, evidence = fixture_frame(args.fixtures, index)
                frames.append(rgb)
                manifest["inputs"].append(evidence)
                Image.fromarray(rgb).save(input_directory / ("frame%d.png" % index))
                (input_directory / ("frame%d.rgb" % index)).write_bytes(rgb.tobytes())
                np.save(input_directory / ("frame%d.npy" % index), rgb, allow_pickle=False)
        manifest["hardware_test_attempted"] = True
        with FrameClient(args.port, baudrate=args.baud, timeout=args.timeout) as client:
            manifest.update(info_handshake_passed=True, hardware_test=True,
                            firmware_info=client.firmware_info,
                            info_roundtrip_seconds=client.info_roundtrip_seconds)
            print("UART_INFO_PASS firmware=%s baud=%d" % (client.firmware_info, args.baud), flush=True)
            for index, rgb in enumerate(frames):
                for mode in modes:
                    case_name = "frame%d_mode%d" % (index, mode)
                    case_directory = output / case_name
                    case_directory.mkdir()
                    started = time.perf_counter()
                    expected = process_reference(rgb, mode)
                    reference_seconds = time.perf_counter() - started
                    actual, details = client.process(rgb, mode)
                    difference = np.abs(actual.astype(np.int16) - expected.astype(np.int16)).astype(np.uint8)
                    exact = bool(np.array_equal(actual, expected))
                    metrics = dict(details)
                    metrics.update(name=case_name, frame=index, mode=mode, mode_name=MODES[mode],
                                   input_shape=list(rgb.shape), output_shape=list(actual.shape),
                                   exact_match=exact, mismatch_pixels=int(np.count_nonzero(difference)),
                                   max_abs_error=int(difference.max()),
                                   host_numpy_reference_seconds=reference_seconds)
                    np.savez(case_directory / "pixels.npz", actual=actual, expected=expected, difference=difference)
                    for name, array in (("actual", actual), ("expected", expected), ("difference", difference)):
                        Image.fromarray(array).save(case_directory / (name + ".png"))
                        (case_directory / (name + ".gray")).write_bytes(array.tobytes())
                    (case_directory / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
                    manifest["cases"].append(metrics)
                    if not exact:
                        raise AssertionError("FPGA/reference mismatch in " + case_name)
                    manifest["actual_fpga_frames_verified"] += 1
                    print("UART_FRAME_PASS name=%s pixels=%d roundtrip_seconds=%.6f" %
                          (case_name, actual.size, details["uart_roundtrip_seconds"]), flush=True)
            if not args.info:
                manifest["all_requested_frames_passed"] = (
                    planned > 0 and len(manifest["cases"]) == planned
                    and manifest["actual_fpga_frames_verified"] == planned)
            manifest["requested_action_passed"] = (manifest["info_handshake_passed"] if args.info
                                                    else manifest["all_requested_frames_passed"])
    except Exception as exc:
        manifest["requested_action_passed"] = False
        if not args.info:
            manifest["all_requested_frames_passed"] = False
        manifest["error"] = "%s: %s" % (type(exc).__name__, exc)
        print("UART_VERIFY_FAILED " + manifest["error"], file=sys.stderr, flush=True)
    finally:
        manifest["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("UART_EVIDENCE=" + str(output), flush=True)
    if not manifest["requested_action_passed"]:
        return 1
    print("UART_VERIFY_PASS scope=%s frames=%d" % (manifest["source"], planned), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
