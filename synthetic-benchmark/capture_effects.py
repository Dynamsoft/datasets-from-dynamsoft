"""Apply controlled capture effects after composing the label scene."""

import math

import cv2
import numpy as np

from barcode_quality import module_pitch
from rendering import resolution_factor, scale_polygons


CAPTURE_PROFILES = (
    "module_size", "frame_padding", "frame_rotation", "frame_perspective", "frame_crop",
    "jpeg_compression", "frame_low_contrast", "uneven_lighting", "glare", "motion_blur",
    "blur_stack", "high_density",
)
COMBINATIONS = (
    ("frame_rotation", "uneven_lighting", "glare", "low_resolution"),
    ("frame_perspective", "frame_crop", "frame_padding", "frame_low_contrast"),
    ("jpeg_compression", "motion_blur", "noise", "low_resolution"),
    ("frame_rotation", "frame_perspective", "frame_crop", "symbol_tilt", "blur_stack", "noise"),
)
CAPTURE_EFFECTS = set(CAPTURE_PROFILES).union(*COMBINATIONS)


def warp_frame(canvas, truth, parameters, rng):
    height, width = canvas.shape[:2]
    corners = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    perturbed = corners.copy()
    strength = parameters.get("frame_perspective", 0)
    if strength:
        amount = strength * .15 * min(width, height)
        perturbed += np.float32([[rng.uniform(-amount, amount), rng.uniform(-amount, amount)] for _ in corners])
    perspective = cv2.getPerspectiveTransform(corners, perturbed)
    rotate = cv2.getRotationMatrix2D((width / 2, height / 2), -parameters.get("frame_rotation", 0), 1)
    transform = np.vstack((rotate, [0, 0, 1])) @ perspective
    outer = cv2.perspectiveTransform(corners[None], transform)[0]
    low = np.floor(outer.min(axis=0)).astype(int)
    high = np.ceil(outer.max(axis=0)).astype(int)
    transform = np.array([[1, 0, -low[0]], [0, 1, -low[1]], [0, 0, 1]]) @ transform
    for symbol in truth:
        for field in ("polygon", "label_polygon"):
            symbol[field] = cv2.perspectiveTransform(np.float32([symbol[field]]), transform)[0].tolist()
    output = cv2.warpPerspective(canvas, transform, tuple(high - low + 1), borderMode=cv2.BORDER_REPLICATE)
    return output, transform.tolist()


def crop_frame(canvas, truth, requested, rng):
    height, width = canvas.shape[:2]
    label_points = np.array([point for symbol in truth for point in symbol["label_polygon"]])
    lower = np.maximum(0, np.floor(label_points.min(axis=0)).astype(int) - 8)
    upper = np.minimum([width, height], np.ceil(label_points.max(axis=0)).astype(int) + 9)
    sizes = np.maximum([round(width * requested), round(height * requested)], upper - lower)
    bounds = np.array([width, height])
    low = np.maximum(0, upper - sizes)
    high = np.minimum(lower, bounds - sizes)
    left, top = (rng.randint(int(a), int(b)) for a, b in zip(low, high, strict=True))
    crop_width, crop_height = map(int, sizes)
    for symbol in truth:
        for field in ("polygon", "label_polygon"):
            symbol[field] = [[x - left, y - top] for x, y in symbol[field]]
    return canvas[top:top + crop_height, left:left + crop_width], {
        "requested": requested, "rect": [left, top, crop_width, crop_height],
        "retained": [round(crop_width / width, 5), round(crop_height / height, 5)],
    }


def apply_optics(canvas, truth, parameters, rng):
    if "uneven_lighting" in parameters:
        height, width = canvas.shape[:2]
        angle = rng.uniform(0, 2 * np.pi)
        horizontal, vertical = np.cos(angle), np.sin(angle)
        x = np.linspace(-.5, .5, width, dtype=np.float32)[None, :] * horizontal
        y = np.linspace(-.5, .5, height, dtype=np.float32)[:, None] * vertical
        t = (x + y) / (abs(horizontal) + abs(vertical)) + .5
        canvas = np.rint(canvas * (1 - parameters["uneven_lighting"] * t[:, :, None])).astype(np.uint8)
        parameters["lighting_angle_degrees"] = round(math.degrees(angle), 4)
    if "glare" in parameters:
        height, width = canvas.shape[:2]
        point = np.mean(rng.choice(truth)["polygon"], axis=0)
        x, y = point + (rng.uniform(-.06, .06) * width, rng.uniform(-.06, .06) * height)
        radius = max(width, height) * rng.uniform(.20, .42)
        rows, columns = np.ogrid[:height, :width]
        distance = np.sqrt((columns - x) ** 2 + (rows - y) ** 2) / radius
        glow = np.interp(distance, [0, .55, 1], [1, .45, 0]).astype(np.float32)
        canvas = np.clip(canvas + (255 * parameters["glare"] * glow[:, :, None]), 0, 255).astype(np.uint8)
        parameters["glare_spot"] = [round(float(x), 3), round(float(y), 3), round(radius, 3)]
    if "frame_low_contrast" in parameters:
        canvas = np.clip(128 + (canvas.astype(np.float32) - 128) * parameters["frame_low_contrast"], 0, 255).astype(np.uint8)
    return canvas


def apply_sensor(canvas, parameters, rng, seed, pitch):
    if "blur_stack" in parameters or "motion_blur" in parameters:
        if "blur_stack" in parameters:
            gaussian, requested = parameters["blur_stack"]
            gaussian = round(min(gaussian, pitch * .40), 3)
            motion = round(min(requested, max(2, pitch * 1.65)), 3)
            parameters["blur_stack"] = [gaussian, motion]
            canvas = cv2.GaussianBlur(canvas, (0, 0), gaussian)
        else:
            motion = round(min(parameters["motion_blur"], max(2, pitch * 2)), 3)
            parameters["motion_blur"] = motion
        radius = math.ceil(motion / 2)
        size = radius * 2 + 1
        kernel = np.zeros((size, size), np.float32)
        angle = rng.uniform(0, np.pi)
        dx, dy = round(np.cos(angle) * motion / 2), round(np.sin(angle) * motion / 2)
        cv2.line(kernel, (radius - dx, radius - dy), (radius + dx, radius + dy), 1, 1)
        canvas = cv2.filter2D(canvas, -1, kernel / kernel.sum())
        parameters["motion_angle_degrees"] = round(math.degrees(angle), 4)
    if "noise" in parameters:
        noise = np.random.default_rng(seed).standard_normal((*canvas.shape[:2], 1), dtype=np.float32)
        canvas = np.clip(canvas.astype(np.float32) + noise * parameters["noise"], 0, 255).astype(np.uint8)
    if "jpeg_compression" in parameters:
        ok, jpeg = cv2.imencode(".jpg", canvas, (cv2.IMWRITE_JPEG_QUALITY, parameters["jpeg_compression"]))
        if not ok:
            raise ValueError("Capture JPEG round trip failed")
        canvas = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
    return canvas


def capture_frame(canvas, truth, settings, rng, seed):
    parameters = dict(settings)
    geometry = {}
    canvas = apply_optics(canvas, truth, parameters, rng)
    if "frame_rotation" in parameters or "frame_perspective" in parameters:
        canvas, geometry["homography"] = warp_frame(canvas, truth, parameters, rng)
    if "frame_crop" in parameters:
        canvas, geometry["crop"] = crop_frame(canvas, truth, parameters["frame_crop"], rng)
    pitch = max(.1, min(module_pitch(symbol) for symbol in truth))
    canvas = apply_sensor(canvas, parameters, rng, seed, pitch)
    geometry["pre_scale_size"] = [canvas.shape[1], canvas.shape[0]]
    if "low_resolution" in parameters:
        height, width = canvas.shape[:2]
        factor = resolution_factor(parameters["low_resolution"], pitch)
        parameters["low_resolution"] = factor
        size = (round(width * factor), round(height * factor))
        canvas = cv2.resize(canvas, size, interpolation=cv2.INTER_AREA)
        scale_polygons(truth, (width, height), size)
        for symbol in truth:
            label = {"polygon": symbol["label_polygon"]}
            scale_polygons([label], (width, height), size)
            symbol["label_polygon"] = label["polygon"]
    for symbol in truth:
        if "raster_module_pitch" in symbol:
            corners = np.array(symbol["polygon"])
            span = (np.linalg.norm(corners[1] - corners[0]) + np.linalg.norm(corners[2] - corners[3])) / 2
            source_span = symbol["ink_mask_size"][0] - 1
            symbol["nominal_px_per_module"] = round(span * symbol["raster_module_pitch"] / source_span, 3)
        symbol["label_polygon"] = [[round(x, 3), round(y, 3)] for x, y in symbol["label_polygon"]]
        symbol["polygon"] = [[round(x, 3), round(y, 3)] for x, y in symbol["polygon"]]
    parameters.update(geometry)
    return canvas, parameters
