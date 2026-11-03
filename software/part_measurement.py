"""Host geometry from a verified FPGA Sobel frame; importing opens no device.

Lengths describe the minimum-area *outer* rectangle in pixel-centre coordinates.
One ruler gives a uniform planar scale, not perspective/lens correction. Keep the
camera perpendicular to the measurement plane and the reference in that plane.
This is a demonstration measurement, not a calibrated precision instrument.
"""
import math
from numbers import Integral, Real

import cv2
import numpy as np
from PIL import Image, ImageDraw


def _positive(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(name + " must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(name + " must be a finite positive number")
    return number


def _point(value, name):
    try:
        if len(value) != 2:
            raise ValueError
        if any(isinstance(item, (bool, np.bool_)) or not isinstance(item, Real) for item in value):
            raise ValueError
        result = tuple(float(item) for item in value)
        if not all(math.isfinite(item) for item in result):
            raise ValueError
        return result
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + " must contain two finite coordinates") from exc


def calibration_scale(p0, p1, known_mm):
    """Return mm/pixel from a same-plane reference line at least 8 pixels long."""
    p0, p1 = _point(p0, "p0"), _point(p1, "p1")
    known_mm = _positive(known_mm, "known_mm")
    distance = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if not math.isfinite(distance) or distance < 8:
        raise ValueError("Calibration line must span at least 8 output pixels")
    scale = known_mm / distance
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Calibration scale is not finite and positive")
    return scale


def _image_and_roi(edges, roi):
    if not isinstance(edges, np.ndarray) or edges.dtype != np.uint8 or edges.ndim != 2:
        raise ValueError("edges must be a two-dimensional uint8 array")
    height, width = edges.shape
    if min(height, width) < 3:
        raise ValueError("edges must be at least 3 by 3 pixels")
    if roi is None:
        return height, width, (0, 0, width, height)
    try:
        if len(roi) != 4 or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Integral) for v in roi):
            raise ValueError
        x0, y0, x1, y1 = (int(v) for v in roi)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("roi must contain four integer coordinates") from exc
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("roi must be ordered and inside the output image")
    if x1 - x0 < 3 or y1 - y0 < 3:
        raise ValueError("roi must span at least 3 by 3 pixels")
    return height, width, (x0, y0, x1, y1)


def analyze_edges(edges, *, roi=None, threshold=40, min_area=80, mm_per_pixel=None,
                  close_gaps=True):
    """Measure the largest external contour inside an exclusive-endpoint ROI.

    Supply only a Sobel output whose FPGA/reference equality was already checked.
    No source-camera RGB or hidden host edge detector is used. Threshold and one
    optional 3x3 closing operation connect small edge gaps; interior holes are not
    measured. Set close_gaps=False when closing joins nearby lettering or objects.
    A selected contour touching the ROI/image boundary is marked ``truncated``
    and has no valid size. An absent scale yields pixels only, with mm fields null.
    """
    height, width, bounds = _image_and_roi(edges, roi)
    if type(close_gaps) is not bool:
        raise ValueError("close_gaps must be a bool")
    if isinstance(threshold, (bool, np.bool_)) or not isinstance(threshold, Integral) or not 0 <= threshold <= 255:
        raise ValueError("threshold must be an integer between 0 and 255")
    min_area = _positive(min_area, "min_area")
    if mm_per_pixel is not None:
        mm_per_pixel = _positive(mm_per_pixel, "mm_per_pixel")
    x0, y0, x1, y1 = bounds
    # Pad before closing so objects that touch a crop edge remain detectable as
    # clipped instead of being erased by the morphology border convention.
    binary = np.where(edges[y0:y1, x0:x1] > threshold, 255, 0).astype(np.uint8)
    if close_gaps:
        padded = np.pad(binary, 2, mode="constant")
        closed = cv2.morphologyEx(padded, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8),
                                  borderType=cv2.BORDER_CONSTANT, borderValue=0)[2:-2, 2:-2]
    else:
        closed = binary
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    eligible, boundary_candidates = [], []
    for index, contour in enumerate(contours):
        area = float(cv2.contourArea(contour))
        points = contour.reshape(-1, 2)
        touches = bool(np.any(points[:, 0] <= 0) or np.any(points[:, 1] <= 0)
                       or np.any(points[:, 0] >= x1 - x0 - 1)
                       or np.any(points[:, 1] >= y1 - y0 - 1))
        if area >= min_area:
            eligible.append((index, contour, area, touches, area))
        # A cut-open rectangle may have near-zero enclosed contour area. Its
        # spatial extent still proves clipping, so do not label it a usable part
        # or silently select a smaller uncut object instead.
        _, _, bw, bh = cv2.boundingRect(contour)
        if touches and bw * bh >= min_area:
            boundary_candidates.append((index, contour, area, True, float(bw * bh)))
    result = dict(status="no_contour", input_shape=[height, width], roi=list(bounds),
                  threshold=int(threshold), min_area=min_area, close_gaps=close_gaps,
                  closing_kernel_size=3 if close_gaps else 1,
                  detected_contours=len(contours), eligible_contours=len(eligible),
                  selected_contour=None, box_points=None, long_px=None, short_px=None,
                  area_px2=None, perimeter_px=None, mm_per_pixel=mm_per_pixel,
                  long_mm=None, short_mm=None,
                  measurement_location="host_after_verified_fpga_sobel",
                  method="largest_external_contour_min_area_rectangle",
                  scale_assumption="uniform_same_plane_perpendicular_camera",
                  precision_claim="demonstration_only_no_accuracy_certificate")
    candidates = eligible + boundary_candidates
    if not candidates:
        return result
    index, local, contour_area, touches, _ = max(candidates, key=lambda item: item[4])
    global_contour = local.astype(np.float32) + np.array([[[x0, y0]]], np.float32)
    rectangle = cv2.minAreaRect(global_contour)
    box = cv2.boxPoints(rectangle)
    long_px, short_px = sorted((float(v) for v in rectangle[1]), reverse=True)
    bx, by, bw, bh = cv2.boundingRect(local)
    result.update(selected_contour=dict(index=index, point_count=len(local),
                                       contour_area_px2=contour_area, touches_boundary=touches,
                                       bounding_rect=[bx + x0, by + y0, bw, bh]),
                  box_points=box.astype(float).tolist())
    if touches:
        result["status"] = "truncated"
        return result
    if short_px <= 0 or not all(math.isfinite(v) for v in (long_px, short_px)):
        return result
    result.update(status="ok", long_px=long_px, short_px=short_px,
                  area_px2=contour_area, perimeter_px=float(cv2.arcLength(local, True)))
    if mm_per_pixel is not None:
        long_mm, short_mm = long_px * mm_per_pixel, short_px * mm_per_pixel
        if not all(math.isfinite(v) for v in (long_mm, short_mm)):
            raise ValueError("Scaled measurement overflow")
        result.update(long_mm=long_mm, short_mm=short_mm)
    return result


def render_measurement_overlay(edges, result, calibration_points=None):
    """Return a separate annotated PIL RGB image; raw FPGA bytes stay unchanged."""
    height, width, _ = _image_and_roi(edges, None)
    if not isinstance(result, dict) or result.get("input_shape") != [height, width]:
        raise ValueError("Result must describe this edge image shape")
    _, _, bounds = _image_and_roi(edges, result.get("roi"))
    output = Image.fromarray(edges).convert("RGB")
    draw = ImageDraw.Draw(output)
    x0, y0, x1, y1 = bounds
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="#00bfff", width=1)
    box = result.get("box_points")
    if box is not None:
        vertices = [_point(p, "box point") for p in box]
        if len(vertices) != 4:
            raise ValueError("A rectangle must have four box points")
        draw.line(vertices + vertices[:1], fill="#00ff60" if result["status"] == "ok" else "#ff6030", width=1)
    if calibration_points is not None:
        if len(calibration_points) != 2:
            raise ValueError("Calibration overlay requires two points")
        p0, p1 = (_point(p, "calibration point") for p in calibration_points)
        draw.line((p0, p1), fill="#ffe000", width=1)
        for px, py in (p0, p1):
            draw.ellipse((px - 2, py - 2, px + 2, py + 2), outline="#ffe000", width=1)
    if result["status"] == "ok":
        text = "%.1f x %.1f px" % (result["long_px"], result["short_px"])
        if result.get("long_mm") is not None:
            text += " | %.2f x %.2f mm" % (result["long_mm"], result["short_mm"])
    elif result["status"] == "truncated":
        text = "Clipped contour: widen ROI"
    else:
        text = "No closed contour"
    # The caption is only on this derived image, never on the verified raw output.
    caption_box = draw.textbbox((2, 2), text)
    draw.rectangle((0, 0, min(width - 1, caption_box[2] + 3), min(height - 1, caption_box[3] + 3)), fill="black")
    draw.text((2, 2), text, fill="white")
    return output
