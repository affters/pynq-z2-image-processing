"""Cross-check vectorized runtime reference against scalar golden algorithms."""
import json
from pathlib import Path
import sys

import numpy as np
from filter_reference import equalize, window_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"software"))
from image_reference import pack_rgb, process_reference


def main():
    rng = np.random.RandomState(20261029)
    cases, pixels = 0, 0
    for width, height in ((3, 3), (5, 4), (128, 96)):
        for rgb in (rng.randint(0, 256, (height, width, 3)).astype(np.uint8),
                    np.full((height, width, 3), 128, dtype=np.uint8),
                    np.zeros((height, width, 3), dtype=np.uint8),
                    np.full((height, width, 3), 255, dtype=np.uint8)):
            packed = pack_rgb(rgb)
            unpacked = np.stack(((packed >> 16)&255, (packed >> 8)&255, packed&255), axis=1).reshape(rgb.shape)
            assert np.array_equal(rgb, unpacked), "Packing or channel order mismatch"
            gray = [(77*int(r)+150*int(g)+29*int(b)+128)//256 for r, g, b in rgb.reshape(-1, 3)]
            for mode in range(5):
                expected = gray if mode == 0 else equalize(gray) if mode == 4 else window_filter(gray, width, height, mode)
                actual = process_reference(rgb, mode).ravel().tolist()
                assert actual == expected, "Reference mismatch %sx%s mode%s" % (width, height, mode)
                pixels += len(actual)
                cases += 1
    result = dict(cases=cases, compared_pixels=pixels, exact_match=True, hardware_test=False)
    output = Path(__file__).resolve().parents[1]/"output"/"software"
    output.mkdir(parents=True, exist_ok=True)
    (output/"reference_verification.json").write_text(json.dumps(result, indent=2), encoding="ascii")
    print("SOFTWARE_REFERENCE_PASS cases=%d pixels=%d" % (cases, pixels))


if __name__ == "__main__":
    main()
