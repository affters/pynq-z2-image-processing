"""Read-only integrity, pixel and provenance checks for the working bundle.

This opens no camera, serial port, JTAG connection or MMIO. It requires NumPy.
It does not turn historical JSON claims into a new hardware run.
"""
from collections import Counter
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import statistics
import sys
import zipfile
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
from image_reference import process_reference

NEW = "output/uart_firmware/build_20261101_015010_utc_b719be66"
OLD = "output/uart_firmware/build_20261031_022051_utc_8f9d3191"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def records(value):
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and "sha256" in value:
            yield value
        for item in value.values():
            yield from records(item)
    elif isinstance(value, list):
        for item in value:
            yield from records(item)


def verify_case(directory, case):
    with np.load(ROOT / directory / "pixels.npz", allow_pickle=False) as data:
        rgb = data["rgb"] if "rgb" in data.files else np.load(ROOT / directory / ".." / "inputs" / f"frame{case['frame']}.npy", allow_pickle=False)
        actual = data["actual"]
        golden = process_reference(rgb, case["mode"])
        assert rgb.shape == (96, 128, 3) and rgb.dtype == np.uint8
        assert actual.dtype == np.uint8 and np.array_equal(actual, golden), directory
        assert np.array_equal(data["expected"], golden), directory
        assert not np.any(data["difference"]), directory
        assert list(actual.shape) == case["output_shape"]
        assert len(actual.tobytes()) == case["response_payload_bytes"]
        assert zlib.crc32(actual.tobytes()) == case["response_crc32"]
        if "input_rgb_sha256" in case:
            assert sha(rgb.tobytes()) == case["input_rgb_sha256"]
        assert case["exact_match"] and case["mismatch_pixels"] == 0 and case["max_abs_error"] == 0
        return actual.size, rgb.copy(), actual.copy()


def batch(base, pixels=120216, cases=10):
    result = read(base + "/result.json")
    assert result.get("error") is None and not result.get("cleanup_errors", [])
    assert result["hardware_test"] and not result["linux_test"]
    assert len(result["cases"]) == cases
    total, values = 0, {}
    for case in result["cases"]:
        directory = f"{base}/frame{case['frame']}_mode{case['mode']}"
        size, rgb, actual = verify_case(directory, case)
        total += size
        values[(case["frame"], case["mode"])] = (rgb, actual)
    assert total == pixels
    return result, values


def main(expected_llm_counts=None):
    manifest = read("manifest.json")
    listed = set(manifest["files"])
    present = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
               and "__pycache__" not in p.parts and ".venv-uart" not in p.parts}
    # Checks that generate new software results should be run after this one.
    assert present == listed | {"manifest.json"}, sorted(present ^ (listed | {"manifest.json"}))
    for relative, record in manifest["files"].items():
        pp = PurePosixPath(relative)
        assert not pp.is_absolute() and ".." not in pp.parts
        assert re.fullmatch(r"[A-Za-z0-9_./-]+", relative), relative
        raw = (ROOT / relative).read_bytes()
        assert sha(raw) == record["sha256"] and len(raw) == record["bytes"], relative
        path = ROOT / relative
        if path.suffix == ".py":
            ast.parse(raw.decode("utf-8-sig"), filename=relative)
        if path.suffix == ".md":
            for link in re.findall(r"\]\(([^)]+)\)", raw.decode("utf-8-sig")):
                if not re.match(r"https?://|#", link):
                    assert (path.parent / link.split("#")[0]).exists(), (relative, link)
        if path.suffix in {".bit", ".hwh", ".xsa", ".elf"}:
            # Generated artifacts retain their vendor notices and binary bytes.
            # XSA members are inspected in addition to the outer ZIP checksum.
            if path.suffix == ".xsa":
                with zipfile.ZipFile(path) as archive:
                    assert archive.testzip() is None
    comparison = read("output/uart_transport_comparison_20261101.json")
    references = {}
    for record in records(comparison):
        relative = record["path"]
        raw = (ROOT / relative).read_bytes()
        assert sha(raw) == record["sha256"].lower(), relative
        assert record["bytes"] == len(raw)
        references[relative] = record["sha256"]
    old, old_pixels = batch(OLD + "/resume_all_20261031_080130_utc")
    new, new_pixels = batch(NEW + "/all_modes_2m")
    camera, _ = batch(NEW + "/camera_all_modes_2m")
    assert camera["camera_test"] and camera["camera_capture_test"] and not camera["sd_used"]
    first, _ = batch(NEW + "/first_gray_2m", pixels=12288, cases=1)
    assert old_pixels.keys() == new_pixels.keys()
    for key in old_pixels:
        assert all(np.array_equal(a, b) for a, b in zip(old_pixels[key], new_pixels[key])), key
    medians = [statistics.median(c["uart_roundtrip_seconds"] for c in x["cases"]) for x in (old, new)]
    assert abs(medians[0] - 4.2839638) < 1e-7 and abs(medians[1] - 0.30025745) < 1e-7
    for build, source in [(OLD, "firmware/baselines/uart_115200"), (NEW, NEW + "/source_snapshot")]:
        record = read(build + "/manifest.json")
        assert sha((ROOT / build / "uart_image.elf").read_bytes()) == record["elf_sha256"].lower()
        for name, expected in record["source_hashes"].items():
            assert sha((ROOT / source / name).read_bytes()) == expected.lower()
    assert sha((ROOT / NEW / "uart_image.elf").read_bytes()) == "f60d7dbdb7d0983e76acd46ed0aa59d28410240864cf7678bd51dda9fa788328"
    assert sha((ROOT / "output/image_system/image_system.bit").read_bytes()) == "ebe2f73d9fd2d605629cb751a734b0da2db1341e9c1e7d21a415979a0a65f3eb"
    assert sha((ROOT / "output/image_system/ps7_init.tcl").read_bytes()) == "05ff63c18d43e9d8b6b117ab9e5463d76b8235266daec17327d23e09fecc788b"
    gui = []
    for session, count, modes in [("session_20261101_020150_fddafc3e", 2299, {0:306, 1:315, 2:314, 3:426, 4:938}), ("session_20261101_021530_75398c2c", 981, {4:981})]:
        result = read("output/uart_live/" + session + "/result.json")
        assert len(result["cases"]) == count and Counter(c["mode"] for c in result["cases"]) == modes
        assert result.get("error") is None and result["cleanup_errors"] == [] and result["camera_test"]
        assert all(c["exact_match"] and c["mismatch_pixels"] == 0 and c["max_abs_error"] == 0 for c in result["cases"])
        assert result["all_modes_verified"] == (len(modes) == 5)
        gui.append(count)
    selection = read("evidence/selection.json")
    for sample in selection["gui_samples"]:
        result = read("output/uart_live/" + sample["session"] + "/result.json")
        case = next(c for c in result["cases"] if c["frame"] == sample["frame"] and c["mode"] == sample["mode"])
        verify_case(sample["directory"], case)
    llm = read("llm_logs/conversation_submission_anonymous_manifest.json")
    raw = (ROOT / "llm_logs/conversation_submission_anonymous.jsonl").read_bytes()
    assert sha(raw) == llm["output_sha256"] and len(raw) == llm["output_bytes"]
    messages = [json.loads(line) for line in raw.decode().splitlines()]
    # Preserve the original v4 default; a newer package passes manifest-bound
    # counts explicitly instead of rewriting the archived snapshot's scope.
    if expected_llm_counts is None:
        expected_llm_counts = {"user":83, "assistant":173}
    assert len(messages) == sum(expected_llm_counts.values())
    assert Counter(x["role"] for x in messages) == expected_llm_counts
    assert not (ROOT / "llm_logs/conversation_visible.jsonl").exists()
    print(json.dumps({"all_passed": True, "payload_files": len(listed), "comparison_references": len(references), "fixed_batch_pixels_each": 120216, "real_camera_pixels": 120216, "first_gray_pixels": 12288, "gui_summary_frame_counts": gui, "gui_raw_samples_verified": len(selection["gui_samples"]), "transaction_medians_seconds": medians, "historical_evidence_rechecked_offline": True, "hardware_access_in_this_check": False}, indent=2))


if __name__ == "__main__":
    main()
