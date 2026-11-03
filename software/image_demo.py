"""Run on the PYNQ board: save actual FPGA outputs and reproducible metrics."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from image_accelerator import ImageAccelerator
from image_reference import MODES, process_reference


def synthetic_rgb(width=128, height=96):
    x, y = np.meshgrid(np.arange(width), np.arange(height))
    rng = np.random.RandomState(20261029)
    image = np.stack((x*255//max(1, width-1), y*255//max(1, height-1),
                      ((x//8+y//8) % 2)*180+35), axis=2)
    return np.clip(image+rng.randint(-15, 16, image.shape), 0, 255).astype(np.uint8)


def camera_frame(capture):
    import cv2
    ok, bgr = capture.read()
    if not ok:
        raise RuntimeError("USB camera read failed")
    resized = cv2.resize(bgr, (ImageAccelerator.WIDTH, ImageAccelerator.HEIGHT), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)


def measure(accelerator, rgb, mode):
    started = time.perf_counter()
    expected = process_reference(rgb, mode)
    cpu_seconds = time.perf_counter()-started
    actual, dma_seconds = accelerator.process(rgb, mode)
    difference = np.abs(actual.astype(np.int16)-expected.astype(np.int16))
    result = dict(mode=mode, name=MODES[mode], input_shape=list(rgb.shape),
                  output_shape=list(actual.shape), exact_match=bool(np.array_equal(actual, expected)),
                  mismatch_pixels=int(np.count_nonzero(difference)),
                  max_abs_error=int(difference.max()), cpu_numpy_seconds=cpu_seconds,
                  fpga_control_dma_seconds=dma_seconds)
    if not result["exact_match"]:
        raise AssertionError("FPGA/reference mismatch: %r" % result)
    return actual, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bitfile", required=True)
    parser.add_argument("--source", default="synthetic", help="synthetic, camera, or RGB image file")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--mode", default="all", choices=["all"]+[str(m) for m in MODES])
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("board_results"))
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be a new or empty directory to preserve existing evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    capture = None
    modes = list(MODES) if args.mode == "all" else [int(args.mode)]
    if args.source == "camera":
        import cv2
        capture = cv2.VideoCapture(args.camera)
        if not capture.isOpened():
            raise RuntimeError("Cannot open USB camera /dev/video%d" % args.camera)
        input_rgb = None
    elif args.source == "synthetic":
        input_rgb = synthetic_rgb()
    else:
        image = Image.open(args.source).convert("RGB").resize((128, 96), getattr(Image, "Resampling", Image).BOX)
        input_rgb = np.asarray(image)
    results = []
    try:
        with ImageAccelerator(args.bitfile) as accelerator:
            for mode in modes:
                # One unreported warm-up; benchmark samples are subsequent frames.
                rgb = camera_frame(capture) if capture is not None else input_rgb
                measure(accelerator, rgb, mode)
                for index in range(args.frames):
                    frame_started = time.perf_counter()
                    rgb = camera_frame(capture) if capture is not None else input_rgb
                    output, result = measure(accelerator, rgb, mode)
                    result.update(index=index, source=args.source,
                                  capture_compare_process_seconds=time.perf_counter()-frame_started)
                    results.append(result)
                    if index == 0:
                        prefix = args.output/("mode%d" % mode)
                        Image.fromarray(rgb).save(str(prefix)+"_input.png")
                        Image.fromarray(output).save(str(prefix)+"_fpga.png")
                        np.savez(str(prefix)+"_pixels.npz", rgb=rgb, actual=output,
                                 expected=process_reference(rgb, mode))
                print("BOARD_MODE_PASS mode=%d frames=%d" % (mode, args.frames))
    finally:
        if capture is not None:
            capture.release()
        manifest = dict(hardware_test=True, source=args.source,
                        bitfile_sha256=__import__("hashlib").sha256(Path(args.bitfile).read_bytes()).hexdigest(),
                        samples=results, all_requested_frames_passed=len(results) == len(modes)*args.frames,
                        timing_note="control_dma excludes RGB packing, capture, reference, display; CPU is NumPy reference only")
        (args.output/"measurements.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("BOARD_VERIFY_PASS samples=%d output=%s" % (len(results), args.output))


if __name__ == "__main__":
    main()
