"""Fixtures/checker for the complete RGB -> multi-mode AXI stream wrapper."""
import argparse
import hashlib
import json
from pathlib import Path
import random

from PIL import Image
from filter_reference import window_filter, equalize


def prepare(args):
    if min(args.width, args.height) < 3 or args.width*args.height > 65536:
        raise ValueError("Dimensions >=3; this testbench supports <=65536 pixels")
    args.directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261029)
    pixels = [(rng.randrange(256) << 16) | (rng.randrange(256) << 8) | rng.randrange(256)
              for _ in range(args.width*args.height)]
    pixels[:min(8, len(pixels))] = [0x000000, 0xffffff, 0xff0000, 0x00ff00,
                                     0x0000ff, 0xffff00, 0xff00ff, 0x00ffff][:min(8, len(pixels))]
    gray = [(77*(p >> 16) + 150*((p >> 8) & 255) + 29*(p & 255) + 128) >> 8 for p in pixels]
    expected = [gray] + [window_filter(gray, args.width, args.height, m) for m in (1, 2, 3)] + [equalize(gray)]
    for name, value in (("width.txt", args.width), ("height.txt", args.height), ("count.txt", len(pixels))):
        (args.directory/name).write_text(str(value)+"\n", encoding="ascii")
    (args.directory/"input_rgb.hex").write_text("".join("%06x\n" % v for v in pixels), encoding="ascii")
    for mode, values in enumerate(expected):
        (args.directory/("expected_mode%d.hex" % mode)).write_text("".join("%02x\n" % v for v in values), encoding="ascii")
    metadata = dict(width=args.width, height=args.height, input_pixels=len(pixels),
                    output_counts=[len(v) for v in expected], seed=20261029)
    (args.directory/"fixture.json").write_text(json.dumps(metadata, indent=2), encoding="ascii")
    print("AXIS_PREPARE_OK pixels=%d" % len(pixels))


def verify(args):
    metadata = json.loads((args.directory/"fixture.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for mode, count in enumerate(metadata["output_counts"]):
        expected = [int(v, 16) for v in (args.directory/("expected_mode%d.hex" % mode)).read_text().split()]
        actual_file = args.directory/("rtl_axis_mode%d.hex" % mode)
        actual = [int(v, 16) for v in actual_file.read_text().split()]
        if actual != expected:
            raise AssertionError("AXIS mode %d pixel/count mismatch: actual=%d expected=%d" % (mode, len(actual), count))
        (args.output/actual_file.name).write_bytes(actual_file.read_bytes())
        width = metadata["width"] - (2 if mode in (1, 2, 3) else 0)
        height = metadata["height"] - (2 if mode in (1, 2, 3) else 0)
        image = Image.new("L", (width, height))
        image.putdata(actual)
        image.save(args.output/("mode%d.png" % mode))
    metadata.update(exact_match=True, hardware_test=False,
                    input_sha256=hashlib.sha256((args.directory/"input_rgb.hex").read_bytes()).hexdigest())
    for name in ("input_rgb.hex", "fixture.json"):
        (args.output/name).write_bytes((args.directory/name).read_bytes())
    (args.output/"verification.json").write_text(json.dumps(metadata, indent=2), encoding="ascii")
    print("AXIS_VERIFY_OK modes=5")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "verify"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--height", type=int, default=96)
    options = parser.parse_args()
    prepare(options) if options.action == "prepare" else verify(options)
