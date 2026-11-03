"""Prepare and verify actual JTAG/DDR/DMA image-core experiments."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import uuid

import numpy as np
from PIL import Image
from filter_reference import window_filter, equalize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"software"))
from image_demo import synthetic_rgb


def prepare(args):
    if args.directory.exists() and any(args.directory.iterdir()):
        raise ValueError("Use a new/empty fixture directory; old hardware evidence must be preserved")
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory/"run_id.txt").write_text(uuid.uuid4().hex, encoding="ascii")
    rgb = synthetic_rgb()
    frames = [rgb, np.full_like(rgb, 128)]
    cases = []
    for frame, pixels in enumerate(frames):
        words = [(int(r) << 16) | (int(g) << 8) | int(b) for r, g, b in pixels.reshape(-1, 3)]
        gray = [(77*(p >> 16)+150*((p >> 8)&255)+29*(p&255)+128) >> 8 for p in words]
        input_file = "input_frame%d.bin" % frame
        (args.directory/input_file).write_bytes(struct.pack("<%dI" % len(words), *words))
        Image.fromarray(pixels).save(args.directory/("input_frame%d.png" % frame))
        for mode in range(5):
            expected = gray if mode == 0 else equalize(gray) if mode == 4 else window_filter(gray, 128, 96, mode)
            name = "frame%d_mode%d" % (frame, mode)
            (args.directory/(name+"_expected.bin")).write_bytes(struct.pack("<%dI" % len(expected), *expected))
            cases.append(dict(name=name, frame=frame, mode=mode, input_file=input_file,
                              input_pixels=len(words), output_pixels=len(expected),
                              output_width=126 if mode in (1, 2, 3) else 128,
                              output_height=94 if mode in (1, 2, 3) else 96))
    (args.directory/"cases.json").write_text(json.dumps(cases, indent=2), encoding="ascii")
    commands = ["set image_cases {\n"]
    commands += ["  {%s %d %s %d %d}\n" % (c["name"], c["mode"], c["input_file"], c["input_pixels"], c["output_pixels"]) for c in cases]
    commands.append("}\n")
    (args.directory/"cases.tcl").write_text("".join(commands), encoding="ascii")
    print("HARDWARE_FIXTURES_READY cases=%d" % len(cases))


def verify(args):
    cases = json.loads((args.directory/"cases.json").read_text())
    log = (args.directory/"jtag.log").read_text(encoding="utf-8", errors="replace")
    run_id = (args.directory/"run_id.txt").read_text().strip()
    if len(run_id) != 32 or "JTAG_IMAGE_PASS run_id=%s cases=10" % run_id not in log:
        raise AssertionError("Hardware completion marker absent")
    expected_names = ["frame%d_mode%d" % (frame, mode) for frame in range(2) for mode in range(5)]
    if len(cases) != 10 or [c["name"] for c in cases] != expected_names:
        raise AssertionError("Hardware case manifest is incomplete or unexpected")
    comparisons = []
    for index, case in enumerate(cases):
        name = case["name"]
        frame, mode = divmod(index, 5)
        if (case["frame"] != frame or case["mode"] != mode or
                case["input_file"] != "input_frame%d.bin" % frame or
                case["output_width"] != (126 if mode in (1, 2, 3) else 128) or
                case["output_height"] != (94 if mode in (1, 2, 3) else 96)):
            raise AssertionError("Case metadata differs from the fixed test contract")
        count = 11844 if case["mode"] in (1, 2, 3) else 12288
        if case["input_pixels"] != 12288 or case["output_pixels"] != count:
            raise AssertionError("Unexpected case dimensions")
        actual = (args.directory/(name+"_actual.bin")).read_bytes()
        expected = (args.directory/(name+"_expected.bin")).read_bytes()
        source = (args.directory/case["input_file"]).read_bytes()
        inputs = struct.unpack("<12288I", source)
        gray = [(77*(p >> 16)+150*((p >> 8)&255)+29*(p&255)+128) >> 8 for p in inputs]
        golden = gray if case["mode"] == 0 else equalize(gray) if case["mode"] == 4 else window_filter(gray, 128, 96, case["mode"])
        if expected != struct.pack("<%dI" % len(golden), *golden):
            raise AssertionError("Stored expected output differs from recomputed reference")
        if actual != expected:
            raise AssertionError("Hardware pixel/length mismatch: %s" % name)
        words = struct.unpack("<%dI" % case["output_pixels"], actual)
        image = Image.new("L", (case["output_width"], case["output_height"]))
        image.putdata(words)
        image.save(args.directory/(name+"_fpga.png"))
        comparisons.append(dict(name=name, pixels=len(words), exact_match=True,
                                actual_sha256=hashlib.sha256(actual).hexdigest()))
    result = dict(hardware_test=True, run_id=run_id, transport="JTAG debug -> DDR -> AXI DMA -> PL -> AXI DMA -> DDR -> JTAG debug",
                  cases=comparisons, total_compared_pixels=sum(c["pixels"] for c in comparisons),
                  exact_match=True, camera_test=False, linux_test=False,
                  timing_note="JTAG/host polling is not an FPS or PL-latency measurement")
    (args.directory/"verification.json").write_text(json.dumps(result, indent=2), encoding="ascii")
    print("HARDWARE_VERIFY_PASS cases=%d pixels=%d" % (len(cases), result["total_compared_pixels"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "verify"])
    parser.add_argument("directory", type=Path)
    options = parser.parse_args()
    prepare(options) if options.action == "prepare" else verify(options)
