"""Offline geometry acceptance; no UART, camera, Tk or real accuracy claims."""
import datetime
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software"))
from image_reference import process_reference
from part_measurement import analyze_edges, calibration_scale, render_measurement_overlay


def rectangle(long_side=80, short_side=36, angle=0, center=(126, 94), shape=(190, 254)):
    image = np.zeros(shape, np.uint8)
    box = np.rint(cv2.boxPoints((center, (long_side, short_side), angle))).astype(np.int32)
    cv2.polylines(image, [box], True, 255, 1)
    return image


def expect_value_error(callback):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("Invalid input was accepted")


def main():
    rows = []
    def check(name, callback):
        callback()
        rows.append(dict(name=name, passed=True))
        print("PART_MEASUREMENT_PASS " + name)

    geometry = []
    for angle in (0, 17, 43, 90):
        def exercise(angle=angle):
            edges = rectangle(angle=angle)
            before = edges.copy()
            value = analyze_edges(edges)
            assert value["status"] == "ok"
            assert abs(value["long_px"] - 80) <= 2 and abs(value["short_px"] - 36) <= 2
            assert value["long_mm"] is None and value["short_mm"] is None
            assert np.array_equal(edges, before)
            json.dumps(value, allow_nan=False)
            geometry.append(dict(angle=angle, result=value))
        check("known_rectangle_angle_%d" % angle, exercise)

    def scaled():
        scale = calibration_scale((10, 10), (110, 10), 50)
        assert scale == .5
        value = analyze_edges(rectangle(), mm_per_pixel=scale)
        assert abs(value["long_mm"] - 40) <= 1 and abs(value["short_mm"] - 18) <= 1
        assert calibration_scale((0, 0), (8, 0), 8) == 1
    check("known_reference_pixel_to_mm", scaled)

    def selection():
        edges = np.zeros((190, 254), np.uint8)
        cv2.rectangle(edges, (15, 20), (105, 75), 255, 1)
        cv2.rectangle(edges, (155, 100), (205, 125), 255, 1)
        edges[15, 230] = 255
        value = analyze_edges(edges)
        assert value["status"] == "ok" and value["eligible_contours"] == 2
        assert abs(value["long_px"] - 90) < .01
        selected = analyze_edges(edges, roi=[145, 90, 220, 140])
        assert selected["status"] == "ok" and abs(selected["long_px"] - 50) < .01
        assert min(p[0] for p in selected["box_points"]) >= 155
    check("largest_external_contour_and_roi_coordinates", selection)

    def missing():
        assert analyze_edges(np.zeros((190, 254), np.uint8))["status"] == "no_contour"
        assert analyze_edges(rectangle(), threshold=255)["status"] == "no_contour"
        assert analyze_edges(rectangle(long_side=8, short_side=5), min_area=80)["status"] == "no_contour"
    check("blank_threshold_and_tiny_rejection", missing)

    def clipped():
        edges = rectangle()
        value = analyze_edges(edges, roi=[100, 50, 200, 140])
        assert value["status"] == "truncated"
        for field in ("long_px", "short_px", "long_mm", "short_mm", "area_px2", "perimeter_px"):
            assert value[field] is None
        image = np.zeros((100, 120), np.uint8)
        cv2.rectangle(image, (0, 15), (70, 70), 255, 1)
        assert analyze_edges(image)["status"] == "truncated"
    check("roi_and_image_boundary_reject_sizes", clipped)

    def invalid():
        for value in ([0, 0, 254, 190.0], [20, 20, 10, 50], [-1, 0, 50, 60],
                      [0, 0, 255, 190], [0, 0, 2, 2], [False, 0, 20, 20]):
            expect_value_error(lambda value=value: analyze_edges(rectangle(), roi=value))
        for value in (None, np.zeros((2, 2), np.uint8), np.zeros((20, 20, 3), np.uint8), np.zeros((20, 20), float)):
            expect_value_error(lambda value=value: analyze_edges(value))
        for threshold in (-1, 256, 40.0, True):
            expect_value_error(lambda threshold=threshold: analyze_edges(rectangle(), threshold=threshold))
        for value in (0, -1, float("nan"), float("inf"), True):
            expect_value_error(lambda value=value: analyze_edges(rectangle(), min_area=value))
            expect_value_error(lambda value=value: analyze_edges(rectangle(), mm_per_pixel=value))
    check("invalid_roi_image_and_settings", invalid)

    def bad_calibration():
        for p0, p1, mm in (((0, 0), (7.99, 0), 20), ((0, 0), (0, 0), 20),
                           ((0, 0), (10, float("nan")), 20), ((0, 0), (10, 0), 0),
                           ((0, 0), (10, 0), float("inf")), ((True, 0), (10, 0), 20)):
            expect_value_error(lambda p0=p0, p1=p1, mm=mm: calibration_scale(p0, p1, mm))
    check("short_zero_nonfinite_reference_rejected", bad_calibration)

    def overlay():
        edges = rectangle()
        original = edges.tobytes()
        result = analyze_edges(edges, roi=[40, 35, 220, 170], mm_per_pixel=.5)
        before_result = json.dumps(result, sort_keys=True)
        annotated = render_measurement_overlay(edges, result, [(45, 150), (145, 150)])
        assert annotated.mode == "RGB" and annotated.size == (254, 190)
        assert edges.tobytes() == original and json.dumps(result, sort_keys=True) == before_result
        assert not np.array_equal(np.asarray(annotated), np.repeat(edges[..., None], 3, axis=2))
        blank = np.zeros((190, 254), np.uint8)
        no_contour = analyze_edges(blank, roi=[20, 20, 120, 100])
        annotated_blank = np.asarray(render_measurement_overlay(blank, no_contour))
        assert tuple(annotated_blank[50, 20]) == (0, 191, 255)
    check("independent_overlay_raw_bytes_preserved", overlay)

    def reference_path():
        rgb = np.zeros((192, 256, 3), np.uint8)
        rgb[60:111, 70:171] = 255
        sobel = process_reference(rgb, 2)
        assert sobel.shape == (190, 254)
        value = analyze_edges(sobel)
        assert value["status"] == "ok"
        assert abs(value["long_px"] - 100) <= 3 and abs(value["short_px"] - 50) <= 3
        assert value["measurement_location"] == "host_after_verified_fpga_sobel"
    check("integer_sobel_reference_geometry", reference_path)

    def adjacent_label():
        edges = np.zeros((150, 180), np.uint8)
        cv2.rectangle(edges, (40, 40), (120, 90), 255, 1)
        # A narrow two-pixel background gap separates an adjacent L-shaped label
        # from the part. Closing can merge it into the outer measurement contour.
        cv2.line(edges, (123, 70), (123, 95), 255, 1)
        cv2.line(edges, (123, 95), (134, 95), 255, 1)
        before = edges.copy()
        default = analyze_edges(edges)
        explicit = analyze_edges(edges, close_gaps=True)
        separate = analyze_edges(edges, close_gaps=False)
        assert default == explicit
        assert separate["status"] == default["status"] == "ok"
        assert separate["selected_contour"]["bounding_rect"] == [40, 40, 81, 51]
        assert abs(separate["long_px"] - 80) < .01 and abs(separate["short_px"] - 50) < .01
        assert default["long_px"] > separate["long_px"] + 5
        assert default["selected_contour"]["bounding_rect"][2] > 81
        assert separate["detected_contours"] == 2 and default["detected_contours"] == 1
        assert (separate["close_gaps"], separate["closing_kernel_size"]) == (False, 1)
        assert (default["close_gaps"], default["closing_kernel_size"]) == (True, 3)
        assert np.array_equal(edges, before)
    check("disable_closing_separates_adjacent_label_from_rectangle", adjacent_label)

    def closing_contract():
        edges = rectangle(angle=17)
        binary = np.where(edges > 40, 255, 0).astype(np.uint8)
        padded = np.pad(binary, 2, mode="constant")
        # The former algorithm always applied this exact padded 3x3 closing.
        old_mask = cv2.morphologyEx(padded, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8),
                                   borderType=cv2.BORDER_CONSTANT, borderValue=0)[2:-2, 2:-2]
        previous = analyze_edges(old_mask, close_gaps=False)
        current = analyze_edges(edges)
        for key in ("status", "selected_contour", "box_points", "long_px", "short_px",
                    "area_px2", "perimeter_px", "detected_contours", "eligible_contours"):
            assert current[key] == previous[key]
        for bad in (None, 0, 1, "false", [], np.bool_(False)):
            expect_value_error(lambda bad=bad: analyze_edges(edges, close_gaps=bad))
        for closing in (False, True):
            no_part = analyze_edges(np.zeros_like(edges), close_gaps=closing)
            assert no_part["status"] == "no_contour"
            assert no_part["close_gaps"] is closing
            assert no_part["closing_kernel_size"] == (3 if closing else 1)
    check("closing_default_compatibility_and_strict_bool", closing_contract)

    output = ROOT / "tmp/part_measurement/offline_geometry_qa.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   status="offline_geometry_passed", hardware_access=False,
                   camera_opened=False, physical_accuracy_verified=False,
                   scope="Synthetic pixel geometry and reference scale; no true object or precision claim.",
                   checks=rows, geometry=geometry,
                   source_sha256={str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (ROOT / "software/part_measurement.py", Path(__file__).resolve())})
    output.write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8")
    print("PART_MEASUREMENT_OFFLINE_OK checks=%d evidence=%s" % (len(rows), output))


if __name__ == "__main__":
    main()
