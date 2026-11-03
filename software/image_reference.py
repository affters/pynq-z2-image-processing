"""Vectorized CPU reference for the documented integer FPGA algorithms."""
import numpy as np

MODES = {0: "gray", 1: "gaussian", 2: "sobel", 3: "sharpen", 4: "equalize"}


def pack_rgb(rgb):
    image = np.asarray(rgb)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected HxWx3 uint8 RGB, not BGR")
    wide = image.astype(np.uint32)
    return ((wide[..., 0] << 16) | (wide[..., 1] << 8) | wide[..., 2]).ravel()


def process_reference(rgb, mode):
    if mode not in MODES:
        raise ValueError("Mode must be 0..4")
    image = np.asarray(rgb)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected HxWx3 uint8 RGB, not BGR")
    pixels = image.astype(np.int32)
    gray = (77*pixels[..., 0] + 150*pixels[..., 1] + 29*pixels[..., 2] + 128) >> 8
    if mode == 0:
        return gray.astype(np.uint8)
    if mode == 4:
        histogram = np.bincount(gray.ravel(), minlength=256)
        cdf = histogram.cumsum(dtype=np.int64)
        minimum = cdf[np.flatnonzero(histogram)[0]]
        denominator = gray.size - minimum
        if denominator == 0:
            return gray.astype(np.uint8)
        lut = (np.maximum(cdf-minimum, 0)*255 + denominator//2)//denominator
        return np.clip(lut, 0, 255).astype(np.uint8)[gray]
    if min(gray.shape) < 3:
        raise ValueError("Window filters need width and height >=3")
    a, b, c = gray[:-2, :-2], gray[:-2, 1:-1], gray[:-2, 2:]
    d, e, f = gray[1:-1, :-2], gray[1:-1, 1:-1], gray[1:-1, 2:]
    g, h, i = gray[2:, :-2], gray[2:, 1:-1], gray[2:, 2:]
    if mode == 1:
        output = (a+2*b+c+2*d+4*e+2*f+g+2*h+i+8) >> 4
    elif mode == 2:
        gx, gy = c+2*f+i-a-2*d-g, g+2*h+i-a-2*b-c
        output = (np.abs(gx)+np.abs(gy)) >> 2
    else:
        output = 5*e-b-d-f-h
    return np.clip(output, 0, 255).astype(np.uint8)
