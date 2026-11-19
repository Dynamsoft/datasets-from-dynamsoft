"""Shared barcode encoding and image rendering for the grouped corpus."""

import json
from pathlib import Path
import string
import subprocess

import cv2
import numpy as np

from barcode_quality import covers_qr_finder, ink_mask, module_pitch


ROOT = Path(__file__).resolve().parent
ATLAS = ROOT / "backgrounds/atlas.png"
SEED = 20261119
JPEG_QUALITY = 94
FORMATS = {
    "CODE_128": "code128", "CODE_39": "code39", "CODE_93": "code93",
    "CODABAR": "rationalizedCodabar", "ITF": "interleaved2of5", "EAN_13": "ean13",
    "EAN_8": "ean8", "UPC_A": "upca", "UPC_E": "upce", "QR_CODE": "qrcode",
    "MICRO_QR": "microqrcode", "DATA_MATRIX": "datamatrix", "PDF_417": "pdf417",
    "AZTEC": "azteccode", "MAXICODE": "maxicode",
}
ADDITIONAL_LINEAR_FORMATS = {
    "GS1_128": "gs1-128", "IATA_2_OF_5": "iata2of5",
    "KIX": "kix", "POSTNET": "postnet", "ROYAL_MAIL": "royalmail", "USPS_INTELLIGENT_MAIL": "onecode",
}
DEMO_ADDITIONS = {"DOTCODE": "dotcode", "MSI_CODE": "msi", "PHARMACODE_ONE_TRACK": "pharmacode"}
LINEAR = set(list(FORMATS)[:9]) | ADDITIONAL_LINEAR_FORMATS.keys() | {"MSI_CODE", "PHARMACODE_ONE_TRACK"}
BACKGROUNDS = (
    "corrugated-carton", "crumpled-receipt", "brushed-metal", "luggage-fabric",
    "blue-plastic-wrap", "glossy-package", "maroon-cardboard", "concrete",
    "overlapping-paper", "taped-carton", "olive-canvas", "polyethylene-film",
)
EFFECTS = ("perspective", "rotation", "blur", "low_resolution", "low_contrast", "noise", "occlusion")


def dump(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def with_check_digit(body):
    total = sum(int(digit) * (3 if index % 2 == 0 else 1)
                for index, digit in enumerate(reversed(body)))
    return f"{body}{-total % 10}"


def make_symbol(fmt, rng, used):
    def digits(length):
        return "".join(rng.choices(string.digits, k=length))

    def ascii_token(length):
        return "".join(rng.choices(string.ascii_uppercase + string.digits, k=length))

    while True:
        options = {}
        if fmt == "EAN_13":
            data = with_check_digit(rng.choice("23456789") + digits(11))
        elif fmt == "EAN_8":
            data = with_check_digit(digits(7))
        elif fmt == "UPC_A":
            data = with_check_digit(rng.choice("23456789") + digits(10))
        elif fmt == "UPC_E":
            body = "0" + digits(5) + rng.choice("012")
            expanded = body[:3] + body[-1] + "0000" + body[3:6]
            data = body + with_check_digit(expanded)[-1]
        elif fmt == "CODABAR":
            data = rng.choice("ABCD") + digits(rng.randint(7, 12)) + rng.choice("ABCD")
        elif fmt == "ITF":
            data = digits(rng.choice((8, 10, 12, 16)))
        elif fmt == "MICRO_QR":
            data = digits(rng.randint(8, 13))
        elif fmt == "MAXICODE":
            options["mode"] = 4
            data = "SYN-" + ascii_token(rng.randint(21, 50))
        elif fmt in LINEAR:
            data = ascii_token(rng.randint(6, 15))
        else:
            length = rng.randint(18, 48)
            data = "SYN-" + ascii_token(length)
            if fmt == "QR_CODE" and rng.randrange(3) == 0:
                data = "https://example.invalid/" + ascii_token(length).lower()
        if fmt == "CODE_93":
            options["includecheck"] = True
        if (fmt, data) not in used:
            used.add((fmt, data))
            if fmt in LINEAR:
                options["height"] = round(rng.uniform(8, 17), 2)
            return {"format": fmt, "encoder": FORMATS[fmt], "text": data, "options": options}


def read_backgrounds(path=ATLAS, names=BACKGROUNDS):
    atlas = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if atlas is None:
        raise ValueError(f"Cannot open {path}")
    height, width = atlas.shape[:2]
    tiles = {}
    for index, name in enumerate(names):
        row, column = divmod(index, 4)
        tiles[name] = atlas[row * height // 3 + 4:(row + 1) * height // 3 - 4,
                            column * width // 4 + 4:(column + 1) * width // 4 - 4]
    return tiles


def fit_quad(patch, box, angle, perspective, scale_range, rng, ensure_convex=False, pixel_scale=None):
    x0, y0, x1, y1 = box
    height, width = patch.shape[:2]
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    corners = source - source.mean(axis=0)
    offsets = np.array([[rng.uniform(-perspective, perspective), rng.uniform(-perspective, perspective)]
                        for _ in source], dtype=np.float32) * (width, height)
    if ensure_convex and not cv2.isContourConvex((corners + offsets).astype(np.float32)):
        offsets *= .65
    corners += offsets
    radians = np.radians(angle)
    rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
    corners = corners @ rotation.T
    span = np.ptp(corners, axis=0)
    fit = min((x1 - x0) / span[0], (y1 - y0) / span[1])
    scale = fit * rng.uniform(*scale_range) if pixel_scale is None else min(.97 * fit, pixel_scale)
    corners *= scale
    center = (corners.max(axis=0) + corners.min(axis=0)) / 2
    slack_x, slack_y = ((x1 - x0) - span[0] * scale) / 2, ((y1 - y0) - span[1] * scale) / 2
    corners += ((x0 + x1) / 2 + slack_x * rng.uniform(-.78, .78) - center[0],
                (y0 + y1) / 2 + slack_y * rng.uniform(-.78, .78) - center[1])
    return cv2.getPerspectiveTransform(source, corners.astype(np.float32)), corners


def paste(canvas, patch, transform, corners):
    left, top = np.maximum(np.floor(corners.min(axis=0)).astype(int) - 1, 0)
    right, bottom = np.minimum(np.ceil(corners.max(axis=0)).astype(int) + 2, canvas.shape[1::-1])
    translate = np.array([[1, 0, -left], [0, 1, -top], [0, 0, 1]])
    rgba = cv2.warpPerspective(patch, translate @ transform, (right - left, bottom - top))
    destination = canvas[top:bottom, left:right]
    alpha = rgba[:, :, 3:4].astype(np.uint16)
    # Warping against transparent black has already premultiplied RGB on the edge.
    destination[:] = np.minimum(255, rgba[:, :, :3] + (destination * (255 - alpha) + 127) // 255)


def render_symbol(canvas, specification, png, box, effects, tier, rng, count,
                  appearance=None, scale=None, ambient_angle=0.0, capture=None, strength=1.0):
    fmt = specification["format"]
    ink = ink_mask(png)
    height, width = ink.shape
    quiet_x, quiet_y = (44, 22) if fmt in LINEAR else (20, 20)
    raster_scale = specification["options"].get("scale", 4)
    if capture and raster_scale != 4:
        quiet_x, quiet_y = (round(value * raster_scale / 4) for value in (quiet_x, quiet_y))
    left = quiet_x
    header = quiet_y
    footer = quiet_y
    if appearance == "retail-sticker":
        left += max(14, width // 16)
        footer += 38
    elif appearance == "hang-tag":
        left += max(36, width // 7)
        header += 34
        footer += 32
    label_width, label_height = width + 2 * left, height + header + footer
    patch = np.empty((label_height, label_width, 4), dtype=np.uint8)
    paper = np.array(rng.choice(((236, 240, 243), (218, 232, 241), (228, 236, 226),
                                 (229, 231, 238), (242, 242, 242))), dtype=np.int16)
    ink_color = np.array([rng.randint(9, 37)] * 3, dtype=np.int16)
    remaining_contrast = 1.0
    if "low_contrast" in effects:
        ranges = ((.50, .72), (.30, .48), (.18, .31))
        remaining_contrast = 1 - strength * (1 - rng.uniform(*ranges[tier - 1]))
        mid = (paper + ink_color) / 2
        paper = np.round(mid + (paper - mid) * remaining_contrast).astype(np.int16)
        ink_color = np.round(mid + (ink_color - mid) * remaining_contrast).astype(np.int16)
    shading = np.linspace(-rng.randint(0, 8), rng.randint(0, 8), label_width)[None, :, None]
    patch[:, :, :3] = np.clip(paper + shading, 0, 255)
    region = patch[header:header + height, left:left + width, :3]
    foreground = np.clip(ink_color + shading[:, left:left + width], 0, 255)
    region[:] = np.rint(region + (foreground - region) * (ink[:, :, None] / 255))
    patch[:, :, 3] = 255
    obstruction = None
    if "occlusion" in effects:
        area_scale = rng.uniform(*((.12, .22), (.23, .31), (.31, .38))[tier - 1]) * (.65 + .35 * strength)
        ow = max(1, int(width * area_scale * rng.uniform(.80, 1.15)))
        oh = max(1, int(height * area_scale * rng.uniform(.80, 1.30)))
        for attempt in range(25):
            ox, oy = rng.randint(0, width - ow), rng.randint(0, height - oh)
            obstruction = [ox, oy, ow, oh]
            if not covers_qr_finder(fmt, width, height, raster_scale, obstruction):
                break
            if attempt % 4 == 3:
                ow, oh = max(1, int(ow * .8)), max(1, int(oh * .8))
        else:
            ox, oy, ow, oh = width // 2, height // 2, 1, 1
            obstruction = [ox, oy, ow, oh]
        color = rng.choice(((163, 177, 185), (204, 212, 209), (107, 127, 145)))
        region[oy:oy + oh, ox:ox + ow] = color
    if appearance:
        finish_label(patch, appearance, (left, header, width, height), ink, ink_color,
                     remaining_contrast, obstruction, rng)
    angle = ambient_angle
    if "rotation" in effects:
        angle = rng.choice((-1, 1)) * rng.uniform(*((8, 23), (23, 52), (52, 179))[tier - 1])
    perspective = (.075, .13, .20)[tier - 1] * (.5 + .5 * strength) if "perspective" in effects else 0
    if scale is None:
        scale = (.78, .89) if count == 1 else (.74, .87)
    pitch = None
    pixel_scale = None
    if capture is not None and capture.get("module_size"):
        # BWIPP's regular grid is scaled in whole pixels. MaxiCode uses a hexagonal
        # grid drawn to physical dimensions, so estimate its horizontal pitch.
        pitch = width / 30 if fmt == "MAXICODE" else raster_scale
        pixel_scale = capture["module_size"] / pitch
    transform, label_corners = fit_quad(patch, box, angle, perspective, scale, rng,
                                        ensure_convex=bool(appearance), pixel_scale=pixel_scale)
    paste(canvas, patch, transform, label_corners)
    source_polygon = np.float32([[left, header], [left + width - 1, header],
                                 [left + width - 1, header + height - 1],
                                 [left, header + height - 1]])
    polygon = cv2.perspectiveTransform(source_polygon[None, :, :], transform)[0]
    metadata = {"format": fmt, "text": specification.get("expected_text", specification["text"]), "polygon": polygon.tolist(),
                "angle_degrees": round(angle, 3), "perspective_jitter": perspective,
                "inverted": False, "contrast_multiplier": round(remaining_contrast, 4),
                "ink_mask_size": [width, height], "encoder_options": specification["options"],
                "occlusion_mask_rect": obstruction,
                "occluded_fraction": round(ow * oh / (width * height), 5) if obstruction else 0}
    if capture is not None:
        metadata["label_polygon"] = label_corners.tolist()
        metadata["scene_polygon"] = polygon.tolist()
        metadata["scene_label_polygon"] = label_corners.tolist()
        if "frame_padding" in capture:
            extent = np.ptp(label_corners, axis=0)
            cell = (box[2] - box[0], box[3] - box[1])
            metadata["cell_fill_ratio"] = round(float(max(extent / cell)), 5)
        if pitch is not None:
            metadata["raster_module_pitch"] = round(pitch, 5)
    return metadata


def finish_label(patch, style, bounds, ink, ink_color, contrast, obstruction, rng):
    x, y, width, height = bounds
    patch_height, patch_width = patch.shape[:2]
    if style in ("retail-sticker", "hang-tag"):
        color = (*map(int, ink_color), 255)
        caption = rng.choice(("LOT", "REF", "ITEM", "BATCH", "QC")) + " " + f"{rng.randrange(10000):04d}"
        cv2.putText(patch, caption, (x, patch_height - 14), cv2.FONT_HERSHEY_SIMPLEX,
                    min(.73, width / 165), color, 1, cv2.LINE_AA)
        if style == "hang-tag":
            accent = (*rng.choice(((90, 119, 133), (145, 107, 71), (130, 104, 161))), 255)
            cv2.rectangle(patch, (x, 14), (patch_width - x - 1, 21), accent, cv2.FILLED)
            cv2.circle(patch, (x // 2, patch_height // 2), min(14, x // 5), (0, 0, 0, 0), -1, cv2.LINE_AA)
    if style == "laminated-sticker":
        rows, columns = np.ogrid[:patch_height, :patch_width]
        glare = np.exp(-((columns / patch_width + rows / patch_height * .55 - rng.uniform(.40, 1.05)) / .15) ** 2)
        patch[:, :, :3] = np.minimum(255, patch[:, :, :3] + glare[:, :, None] * rng.uniform(13, 30))
    if style in ("paper-label", "retail-sticker", "laminated-sticker", "hang-tag"):
        corner = min(13, patch_width // 12, patch_height // 12)
        if style == "hang-tag":
            corner *= 2
        for column, row, sx, sy in ((0, 0, 1, 1), (patch_width - 1, 0, -1, 1),
                                    (0, patch_height - 1, 1, -1), (patch_width - 1, patch_height - 1, -1, -1)):
            cv2.fillConvexPoly(patch, np.array([(column, row), (column + sx * corner, row),
                                               (column, row + sy * corner)]), (0, 0, 0, 0))
    if style == "direct-print":
        substrate = rng.randint(180, 220) if contrast < .99 else rng.randint(115, 179)
        patch[:, :, 3] = substrate
        region = patch[y:y + height, x:x + width]
        region[:, :, 3] = substrate + np.rint((255 - substrate) * (ink / 255))
        if obstruction:
            ox, oy, ow, oh = obstruction
            region[oy:oy + oh, ox:ox + ow, 3] = 255
    # The compositor expects premultiplied RGBA, including at cut edges and holes.
    patch[:, :, :3] = (patch[:, :, :3].astype(np.uint16) * patch[:, :, 3:4] + 127) // 255


def resolution_factor(requested, pitch):
    return max(requested, min(.95, 1.12 / pitch))


def retry_frame_size(width, height, retry):
    scale = 1 + .20 * min(5, retry // 4)
    return round(width * scale), round(height * scale)


def effect_strength(retry):
    return max(.35, 1 - .044 * max(0, retry - 2))


def apply_frame_effects(canvas, effects, tier, rng, seed, truth, strength=1.0):
    height, width = canvas.shape[:2]
    params = {"resolution_scale": 1.0, "noise_stddev": 0.0, "blur": None}
    pitch = max(.1, min((module_pitch(symbol) for symbol in truth), default=6))
    if "blur" in effects:
        if rng.random() < .66:
            sigma = min(.48 * pitch, rng.uniform(*((.65, 1.15), (1.15, 2.0), (2.0, 3.5))[tier - 1])) * strength
            canvas = cv2.GaussianBlur(canvas, (0, 0), sigma)
            params["blur"] = {"type": "gaussian", "sigma": round(sigma, 5)}
        else:
            requested = rng.choice(((3, 5), (7, 9), (13, 17))[tier - 1])
            size = min(max(3, 2 * int(pitch) + 1), 2 * max(1, round((requested // 2) * strength)) + 1)
            angle = rng.uniform(0, 180)
            dx, dy = np.rint(np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))]) * (size // 2)).astype(int)
            center = size // 2
            kernel = np.zeros((size, size), np.float32)
            cv2.line(kernel, (center - int(dx), center - int(dy)), (center + int(dx), center + int(dy)), 1, 1)
            canvas = cv2.filter2D(canvas, -1, kernel / kernel.sum())
            params["blur"] = {"type": "motion", "kernel_size": size, "angle_degrees": round(angle, 5)}
    if "low_resolution" in effects:
        requested = rng.uniform(*((.73, .84), (.49, .63), (.28, .41))[tier - 1])
        factor = resolution_factor(1 - (1 - requested) * strength, pitch)
        canvas = cv2.resize(canvas, (round(width * factor), round(height * factor)), interpolation=cv2.INTER_AREA)
        params["resolution_scale"] = round(factor, 5)
    if "noise" in effects:
        sigma = rng.uniform(*((4, 8), (10, 17), (21, 34))[tier - 1]) * strength
        noise = np.random.default_rng(seed).standard_normal((*canvas.shape[:2], 1), dtype=np.float32)
        canvas = np.clip(canvas.astype(np.float32) + noise * sigma, 0, 255).astype(np.uint8)
        params["noise_stddev"] = round(sigma, 5)
    return canvas, params


def choose_effects(scenario, tier, rng):
    effects = []
    if scenario == "combined":
        effects = sorted(rng.sample(EFFECTS, tier + 1))
    elif scenario == "negative":
        effects = rng.sample(("blur", "noise", "low_resolution"), rng.randrange(4))
        tier = rng.randint(1, 3) if effects else 0
    elif scenario != "clean":
        effects = [scenario]
    return effects, tier


def scale_polygons(ground_truth, before, after):
    width, height = before
    out_width, out_height = after
    for truth in ground_truth:
        # OpenCV's resize maps centers, so coordinates follow the same transform.
        truth["polygon"] = [[round((x + .5) * out_width / width - .5, 3),
                             round((y + .5) * out_height / height - .5, 3)]
                            for x, y in truth["polygon"]]


def encode_jpeg(canvas, sample_id):
    ok, image = cv2.imencode(".jpg", canvas, (cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY))
    if not ok:
        raise RuntimeError(f"Cannot encode {sample_id}")
    return image.tobytes()


def encode_plan(plan, directory):
    plan_path = directory / "plan.jsonl"
    plan_path.write_text("".join(dump(item) + "\n" for item in plan), encoding="utf-8")
    encodings = directory / "symbols.jsonl"
    with encodings.open("wb") as stream:
        subprocess.run(["node", str(ROOT / "encode.mjs"), str(plan_path)], stdout=stream, check=True)
    print(f"Encoded {sum(len(sample['symbols']) for sample in plan):,} symbols", flush=True)
    return encodings
