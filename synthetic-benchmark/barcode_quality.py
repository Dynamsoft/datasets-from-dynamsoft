"""Check that rendered frames retain the printed barcode pattern."""

import base64

import cv2
import numpy as np


QUALITY_RULE = {
    "sampling_version": 1,
    "min_requested_px_per_module": 2,
    "min_horizontal_px_per_module": 0.75,
    "max_occluded_area": 0.22,
    "min_median_edge_luma": 12,
    "min_retained_edge_fraction": 0.58,
    "retained_edge_luma": 6,
}
GEOMETRY_RULE = {"min_corner_sine": 0.60, "min_opposite_edge_ratio": 0.50, "protect_qr_finders": True}
GRID_FORMATS = {"AZTEC", "DATA_MATRIX", "DOTCODE", "MAXICODE", "MICRO_QR", "PDF_417", "QR_CODE"}
POLARITY_EFFECTS = {"inversion", "frame_inversion"}


def ink_mask(png):
    bitmap = cv2.imdecode(np.frombuffer(base64.b64decode(png), np.uint8), cv2.IMREAD_GRAYSCALE)
    foreground = cv2.compare(bitmap, 127, cv2.CMP_LT)
    x, y, width, height = cv2.boundingRect(foreground)
    return 255 - bitmap[y:y + height, x:x + width]


def source_module_pitch(symbol):
    return symbol.get("raster_module_pitch", symbol["ink_mask_size"][0] / 30 if symbol["format"] == "MAXICODE"
                      else symbol["encoder_options"].get("scale", 4))


def module_pitch(symbol):
    width = symbol["ink_mask_size"][0]
    a, b, c, d = np.float32(symbol["polygon"])
    return float((np.linalg.norm(b - a) + np.linalg.norm(c - d)) / 2 * source_module_pitch(symbol) / max(width - 1, 1))


def covers_qr_finder(fmt, width, height, module, obstruction):
    if obstruction is None or fmt not in {"QR_CODE", "MICRO_QR"}:
        return False
    size = min(width, height, 7 * module)
    locations = [(0, 0)]
    if fmt == "QR_CODE":
        locations.extend(((width - size, 0), (0, height - size)))
    left, top, w, h = obstruction
    return any(left < x + size and left + w > x and top < y + size and top + h > y for x, y in locations)


def geometry_failure(symbol):
    polygon = np.asarray(symbol["polygon"], dtype=np.float64)
    if not cv2.isContourConvex(polygon.astype(np.float32)):
        return "excessive_perspective"
    edges = np.roll(polygon, -1, axis=0) - polygon
    lengths = np.linalg.norm(edges, axis=1)
    units = edges / lengths[:, None]
    preceding = np.roll(units, 1, axis=0)
    sine = abs(preceding[:, 0] * units[:, 1] - preceding[:, 1] * units[:, 0])
    opposite = np.roll(lengths, 2)
    ratio = np.minimum(lengths, opposite) / np.maximum(lengths, opposite)
    if (min(sine) < GEOMETRY_RULE["min_corner_sine"] or min(ratio) < GEOMETRY_RULE["min_opposite_edge_ratio"]):
        return "excessive_perspective"
    if covers_qr_finder(symbol["format"], *symbol["ink_mask_size"], source_module_pitch(symbol),
                        symbol["occlusion_mask_rect"]):
        return "occluded_finder"
    return None


def edge_samples(mask, horizontal, offset, obstruction):
    plane = mask if horizontal else mask.T
    left = plane[:, :-2 * offset]
    right = plane[:, 2 * offset:]
    if not left.size:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32), np.empty(0, np.float32)
    rows, columns = np.nonzero(left != right)
    start = np.float32(np.column_stack((columns, rows) if horizontal else (rows, columns)))
    stop = start.copy()
    stop[:, 0 if horizontal else 1] += 2 * offset
    direction = np.where(left[rows, columns], 1, -1)
    if obstruction is not None:
        x, y, width, height = obstruction
        low, high = np.array([x, y]), np.array([x + width, y + height])
        visible = ~(((start >= low) & (start < high)).all(axis=1)
                    | ((stop >= low) & (stop < high)).all(axis=1))
        start, stop, direction = start[visible], stop[visible], direction[visible]
    if len(start) > 1024:
        picked = np.linspace(0, len(start) - 1, 1024, dtype=int)
        return start[picked], stop[picked], direction[picked]
    return start, stop, direction


def pattern_failure(gray, symbol, png):
    requested = symbol.get("nominal_px_per_module")
    if (module_pitch(symbol) < QUALITY_RULE["min_horizontal_px_per_module"] or
            requested is not None and requested < QUALITY_RULE["min_requested_px_per_module"] - .015):
        return "subpixel_pattern"
    if symbol["occluded_fraction"] > QUALITY_RULE["max_occluded_area"]:
        return "oversized_occlusion"
    mask = ink_mask(png) > 127
    height, width = mask.shape
    if [width, height] != symbol["ink_mask_size"]:
        raise ValueError("Reference mask dimensions differ from the annotation")
    source = np.float32([(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)])
    transform = cv2.getPerspectiveTransform(source, np.float32(symbol["polygon"]))
    offset = max(1, round(source_module_pitch(symbol) * (.35 if symbol["format"] == "MAXICODE" else .5)))
    directions = (True, False) if symbol["format"] in GRID_FORMATS else (True,)
    for horizontal in directions:
        before, after, sign = edge_samples(mask, horizontal, offset, symbol["occlusion_mask_rect"])
        if not len(sign):
            return "weak_pattern"
        points = cv2.perspectiveTransform(np.vstack((before, after))[None], transform)
        values = cv2.remap(gray, points[:, :, 0].copy(), points[:, :, 1].copy(), cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE).astype(np.float32).ravel()
        luma = (values[len(sign):] - values[:len(sign)]) * sign
        if (np.median(luma) < QUALITY_RULE["min_median_edge_luma"] or
                np.mean(luma >= QUALITY_RULE["retained_edge_luma"]) < QUALITY_RULE["min_retained_edge_fraction"]):
            return "weak_pattern"
    return None


def image_failure(image, truth, pngs, *, check_geometry=True):
    if not truth:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for symbol, png in zip(truth, pngs, strict=True):
        reason = (geometry_failure(symbol) if check_geometry else None) or pattern_failure(gray, symbol, png)
        if reason:
            return reason
    return None
