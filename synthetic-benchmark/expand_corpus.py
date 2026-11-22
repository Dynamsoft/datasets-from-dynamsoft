"""Append the demo's capture cases to a verified v2 grouped image corpus."""

import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import shutil
import string
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from barcode_quality import GEOMETRY_RULE, QUALITY_RULE, image_failure
from capture_effects import CAPTURE_PROFILES, COMBINATIONS, capture_frame
from rendering import (DEMO_ADDITIONS, EFFECTS, ROOT, SEED, dump, effect_strength, encode_jpeg, encode_plan,
                      read_backgrounds, render_symbol, retry_frame_size)
from generate_by_format import (APPEARANCES, ATLAS_SPECS, BACKGROUND_NAMES, DATASET, EXTENDED_FORMATS,
                                MULTI_COMPOSITIONS, SCHEMA as BASE_SCHEMA, SINGLE_COMPOSITIONS, SIZES,
                                accept_frame, balanced_draw, layout_boxes, make_extended_symbol,
                                make_scene, relative_image, render, signature)

SCHEMA = "synthetic-barcode-v5"
ALL_FORMATS = EXTENDED_FORMATS | DEMO_ADDITIONS
MIXED = "MIXED_SYMBOLOGIES"
MAX_SYMBOLS = 16


def msi_check_digit(text):
    digits = [int(character) * (2 if index % 2 == 0 else 1) for index, character in enumerate(reversed(text))]
    return str(-sum(value - 9 if value > 9 else value for value in digits) % 10)


def plan_symbol(fmt, rng, used):
    if fmt in EXTENDED_FORMATS:
        return make_extended_symbol(fmt, rng, used)
    while True:
        options = {}
        if fmt == "DOTCODE":
            raw = "SYN-" + "".join(rng.choices(string.ascii_uppercase + string.digits, k=rng.randint(14, 36)))
            expected = raw
        elif fmt == "MSI_CODE":
            raw = "".join(rng.choices(string.digits, k=rng.randint(8, 11)))
            expected = raw + msi_check_digit(raw)
            options.update(includecheck=True, height=round(rng.uniform(8, 17), 2))
        else:
            raw = str(rng.randint(3, 131070))
            expected = raw
            options["height"] = round(rng.uniform(8, 17), 2)
        if (fmt, expected) not in used:
            used.add((fmt, expected))
            return {"format": fmt, "encoder": DEMO_ADDITIONS[fmt], "text": raw,
                    "expected_text": expected, "options": options}


def parameters(effects, index, rng):
    fraction = (index % 8) / 7
    values = {
        "module_size": (2, 2, 3, 4, 5, 6, 2, 4)[index % 8],
        "frame_padding": round(1.2 + 2.8 * fraction, 2),
        "frame_rotation": round(rng.choice((-1, 1)) * (4 + 21 * fraction), 2),
        "frame_perspective": round(.06 + .24 * fraction, 3),
        "frame_crop": round(.40 + .48 * fraction, 3),
        "jpeg_compression": (15, 23, 32, 42, 53, 64, 75, 84)[index % 8],
        "frame_low_contrast": round(.92 - .62 * fraction, 3),
        "uneven_lighting": round(.14 + .52 * fraction, 3),
        "glare": round(.12 + .45 * fraction, 3),
        "motion_blur": round(3 + fraction * 14, 2),
        "blur_stack": [round(.55 + 1.45 * fraction, 2), round(3 + 23 * fraction, 2)],
        "high_density": True,
        "noise": round(4 + fraction * 11, 2),
        "low_resolution": round(.85 - fraction * .35, 3),
        "symbol_tilt": 20 + 55 * fraction,
    }
    return {effect: values[effect] for effect in effects}


def make_plan(seed, used, new_format_images, stress_per_profile, mixed_per_profile):
    rng = random.Random(seed)
    extension = []

    def sample(group, fmts, scenario, tier, style, backdrop, composition, settings=None):
        symbols = [plan_symbol(fmt, rng, used) for fmt in fmts]
        if settings and "module_size" in settings:
            for symbol in symbols:
                if symbol["format"] != "MAXICODE":
                    symbol["options"]["scale"] = settings["module_size"]
        extension.append({"format_group": group, "scenario": scenario, "tier": tier, "appearance": style,
                          "background": backdrop, "composition": composition, "symbols": symbols,
                          "capture": settings})

    strata = [("clean", 0)] + [(effect, tier) for effect in (*EFFECTS, "combined") for tier in (1, 2, 3)]
    for fmt in DEMO_ADDITIONS:
        layouts = balanced_draw(SINGLE_COMPOSITIONS, new_format_images, rng)
        for index, ((scenario, severity), backdrop, style) in enumerate(zip(
                balanced_draw(strata, new_format_images, rng), balanced_draw(BACKGROUND_NAMES, new_format_images, rng),
                balanced_draw(APPEARANCES, new_format_images, rng), strict=True)):
            count = (2 + index // 6 % 3) if index % 6 == 0 else 1
            sample(fmt, [fmt] * count, scenario, severity, style, backdrop,
                   layouts[index] if count == 1 else rng.choice(MULTI_COMPOSITIONS))

    dense_counts = (5, 6, 8, 10, 11, 12, 14, MAX_SYMBOLS)
    for fmt in sorted(ALL_FORMATS):
        work = [(profile, index) for profile in CAPTURE_PROFILES for index in range(stress_per_profile)]
        for (profile, index), backdrop, style in zip(work, balanced_draw(BACKGROUND_NAMES, len(work), rng),
                                                    balanced_draw(APPEARANCES, len(work), rng), strict=True):
            count = dense_counts[index % len(dense_counts)] if profile == "high_density" else 1
            layout = "dense-grid" if count > 1 else "wide-shot" if profile == "frame_crop" else rng.choice(SINGLE_COMPOSITIONS)
            sample(fmt, [fmt] * count, profile, 1 + index % 8 * 3 // 8, style, backdrop, layout,
                   parameters((profile,), index, rng))

    profiles = [(name, (name,)) for name in CAPTURE_PROFILES] + [("combined", effects) for effects in COMBINATIONS]
    mixed_work = [(scenario, fx, index) for scenario, fx in profiles for index in range(mixed_per_profile)]
    for (scenario, fx, index), backdrop, style in zip(mixed_work, balanced_draw(BACKGROUND_NAMES, len(mixed_work), rng),
                                                   balanced_draw(APPEARANCES, len(mixed_work), rng), strict=True):
        count = 5 + index % 12 if scenario == "high_density" else 2 + index % 5
        if scenario in ("module_size", "frame_crop"):
            count = 2
        formats = rng.sample(list(ALL_FORMATS), count)
        if scenario == "module_size":
            layout = "stacked"
        elif count > 4:
            layout = "dense-grid"
        elif "frame_crop" in fx:
            layout = "clustered"
        else:
            layout = rng.choice(MULTI_COMPOSITIONS)
        sample(MIXED, formats, scenario, 1 + index % 8 * 3 // 8, style, backdrop, layout, parameters(fx, index, rng))

    rng.shuffle(extension)
    for index, row in enumerate(extension, 1):
        row.update(sample_id=f"syn3-{index:05d}", seed=rng.getrandbits(63))
    return extension


def dense_layout(width, height, count, rng):
    columns = min(5, math.ceil(math.sqrt(count * width / height)))
    rows = math.ceil(count / columns)
    cells = [(column * width // columns, row * height // rows,
              (column + 1) * width // columns, (row + 1) * height // rows)
             for row in range(rows) for column in range(columns)]
    rng.shuffle(cells)
    return cells[:count]


def module_frame(pngs, symbols, width, height):
    # Read PNG IHDR without a second pixel decode. Leave space around the
    # commanded pitch for the label, quiet zone and small ambient tilt.
    sizes = []
    for data, symbol in zip(pngs, symbols, strict=True):
        header = base64.b64decode(data[:32])
        w, h = (int.from_bytes(header[offset:offset + 4], "big") for offset in (16, 20))
        if symbol["format"] == "MAXICODE":
            w, h = 290, 290
        sizes.append((w, h))
    cell_width = max(w for w, _ in sizes) * 1.6 + 280
    cell_height = max(h + w * .15 for w, h in sizes) * 1.3 + 210
    return max(width, math.ceil(cell_width)), max(height, math.ceil(cell_height) * len(symbols))


def render_extension(sample, pngs, tiles, attempt):
    settings = sample["capture"]
    if settings is None:
        row, data, fingerprint, reason = render(sample, pngs, tiles, attempt)
        row["subset"] = "new-format"
        return row, data, fingerprint, reason

    settings = dict(settings)
    strength = effect_strength(attempt) * sample.get("initial_strength", 1)
    for name in ("frame_perspective", "uneven_lighting", "glare", "motion_blur", "noise"):
        if name in settings:
            settings[name] *= strength
    for name in ("frame_low_contrast", "low_resolution"):
        if name in settings:
            settings[name] = 1 - (1 - settings[name]) * strength
    if "blur_stack" in settings:
        settings["blur_stack"] = [value * strength for value in settings["blur_stack"]]
    if "jpeg_compression" in settings:
        settings["jpeg_compression"] = round(92 - (92 - settings["jpeg_compression"]) * strength)
    seed = sample["seed"] + attempt * 0x9E3779B97F4A7C15
    rng = random.Random(seed)
    symbols = sample["symbols"]
    count = len(symbols)
    layout = sample["composition"]
    width, height = rng.choice(SIZES)
    if count > 4:
        width, height = rng.choice(((1600, 1200), (1800, 1200), (1536, 1536), (2048, 1365)))
    width, height = retry_frame_size(width, height, attempt)
    if "module_size" in settings:
        width, height = module_frame(pngs, symbols, width, height)
    canvas, background = make_scene(tiles[sample["background"]], width, height, rng)
    if layout == "dense-grid":
        boxes, size = dense_layout(width, height, count, rng), (.72, .93)
    else:
        boxes, size = layout_boxes(width, height, count, layout, rng)
    if "frame_padding" in settings:
        size = (1 / settings["frame_padding"],) * 2
    elif "frame_crop" in settings:
        size = (.39, .56)
    if "module_size" in settings:
        boxes = [(0, index * height // count, width, (index + 1) * height // count) for index in range(count)]
    angle = settings.get("symbol_tilt", 4)
    truth = [render_symbol(canvas, symbol, png, box, (), 0, rng, count,
                           appearance=sample["appearance"], scale=size, ambient_angle=rng.uniform(-angle, angle),
                           capture=settings)
             for symbol, png, box in zip(symbols, pngs, boxes, strict=True)]
    canvas, frame = capture_frame(canvas, truth, settings, rng, seed)
    out_height, out_width = canvas.shape[:2]
    sample_id, group = sample["sample_id"], sample["format_group"]
    data = encode_jpeg(canvas, sample_id)
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    row = {"sample_id": sample_id, "relative_path": relative_image(group, sample_id),
           "image_sha256": sha256(data).hexdigest(), "width": out_width, "height": out_height,
           "source_size": [width, height], "format_group": group, "scenario": sample["scenario"],
           "severity": sample["tier"], "effects": list(settings), "seed": sample["seed"], "render_attempt": attempt,
           "composition": layout, "appearance": sample["appearance"], "background": sample["background"],
           "background_transform": background, "frame_transform": frame, "ground_truth": truth,
           "subset": "mixed" if group == MIXED else "capture"}
    return row, data, signature(decoded), image_failure(decoded, truth, pngs)


def copy_base_images(base, stage, rows):
    accepted, used = [], set()
    for row in rows:
        relative = Path(row["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid base path {relative}")
        source, destination = base / relative, stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        if sha256(data).hexdigest() != row["image_sha256"]:
            raise ValueError(f"Base image hash differs: {relative}")
        try:
            os.link(source, destination)
        except OSError:
            shutil.copyfile(source, destination)
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        accepted.append((row["sample_id"], *signature(image)))
        used.update((item["format"], item["text"]) for item in row["ground_truth"])
    return accepted, used


def update_counts(counters, row):
    for key in ("format_group", "scenario", "background", "composition", "appearance"):
        name = "directory" if key == "format_group" else key
        counters[f"by_{name}"][row[key]] += 1
    counters["by_format"].update(item["format"] for item in row["ground_truth"])
    counters["by_effect"].update(row["effects"])
    counters["by_symbol_count"][str(len(row["ground_truth"]))] += 1


def expand(base, output, seed, jobs, new_format_images, stress_per_profile, mixed_per_profile):
    cv2.setNumThreads(1)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = json.loads((base / "inventory.json").read_text(encoding="utf-8"))
    manifest = (base / "manifest.jsonl").read_bytes()
    if (inventory["schema"] != BASE_SCHEMA or inventory.get("quality_rule") != QUALITY_RULE
            or inventory.get("geometry_rule") != GEOMETRY_RULE
            or sha256(manifest).hexdigest() != inventory["manifest_sha256"]):
        raise ValueError("An intact base corpus with the current quality rule is required")
    rows = list(map(json.loads, manifest.splitlines()))
    tiles = {name: image for atlas, names in ATLAS_SPECS.items() for name, image in read_backgrounds(atlas, names).items()}
    counters = {key: Counter(value) for key, value in inventory.items() if key.startswith("by_")}
    subsets = Counter(base=len(rows))
    rerenders = 0
    with TemporaryDirectory(prefix=".generate-", dir=output.parent) as work:
        temp = Path(work)
        stage = temp / "dataset"
        accepted, used = copy_base_images(base, stage, rows)
        print(f"Preserved {len(accepted):,} base images", flush=True)
        plan = make_plan(seed, used, new_format_images, stress_per_profile, mixed_per_profile)
        encoded = encode_plan(plan, temp)
        for group in (*DEMO_ADDITIONS, MIXED):
            (stage / relative_image(group, "sample")).parent.mkdir(parents=True, exist_ok=True)
        path = stage / "manifest.jsonl"
        with (path.open("wb") as handle, encoded.open(encoding="utf-8") as symbols,
              ThreadPoolExecutor(max_workers=jobs) as pool):
            handle.write(manifest)
            for start in range(0, len(plan), 60):
                batch = [(sample, json.loads(next(symbols))) for sample in plan[start:start + 60]]
                tasks = [pool.submit(render_extension, sample, png, tiles, 0) for sample, png in batch]
                for (sample, png), task in zip(batch, tasks, strict=True):
                    row, data, fingerprint = accept_frame(task.result(), render_extension, sample, png, tiles, accepted)
                    rerenders += row["render_attempt"]
                    accepted.append((row["sample_id"], *fingerprint))
                    (stage / row["relative_path"]).write_bytes(data)
                    handle.write((dump(row) + "\n").encode("utf-8"))
                    update_counts(counters, row)
                    subsets[row["subset"]] += 1
                if (start + len(batch)) % 600 == 0 or start + len(batch) == len(plan):
                    print(f"Rendered {start + len(batch):,}/{len(plan):,} new images", flush=True)
            if next(symbols, None) is not None:
                raise ValueError("Encoder returned too many rows")
        inventory.update({key: dict(sorted(counts.items())) for key, counts in counters.items()})
        inventory.update(schema=SCHEMA, images=len(accepted), barcodes=sum(counters["by_format"].values()),
                         manifest_sha256=sha256(path.read_bytes()).hexdigest(), base_images=len(rows),
                         base_manifest_sha256=sha256(manifest).hexdigest(), by_subset=dict(sorted(subsets.items())),
                         rerenders=inventory["rerenders"] + rerenders, quality_rule=QUALITY_RULE,
                         geometry_rule=GEOMETRY_RULE, expansion_seed=seed,
                         expansion={"new_format_images": new_format_images, "stress_per_profile": stress_per_profile,
                                    "mixed_per_profile": mixed_per_profile, "max_symbols": MAX_SYMBOLS})
        (stage / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
        stage.rename(output)
    print(f"Finished {len(accepted):,} images and {inventory['barcodes']:,} annotations", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, default=ROOT / "dataset-by-format-expanded")
    parser.add_argument("--seed", type=int, default=SEED + 100)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--new-format-images", type=int, default=228)
    parser.add_argument("--stress-per-profile", type=int, default=8)
    parser.add_argument("--mixed-per-profile", type=int, default=13)
    args = parser.parse_args()
    if min(args.jobs, args.new_format_images, args.stress_per_profile, args.mixed_per_profile) < 1:
        parser.error("Counts and jobs must be positive")
    expand(args.base.resolve(), args.output.resolve(), args.seed, args.jobs, args.new_format_images,
           args.stress_per_profile, args.mixed_per_profile)
