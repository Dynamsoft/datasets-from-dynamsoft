"""Generate the image-review corpus, grouped by a single symbology per directory."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import platform
import random
import string
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from barcode_quality import GEOMETRY_RULE, QUALITY_RULE, image_failure
from rendering import (ADDITIONAL_LINEAR_FORMATS, ATLAS, BACKGROUNDS, EFFECTS, FORMATS, JPEG_QUALITY, ROOT, SEED,
                      apply_frame_effects, choose_effects, dump, effect_strength, encode_jpeg, encode_plan,
                      make_symbol, read_backgrounds, render_symbol, retry_frame_size, scale_polygons, with_check_digit)


DATASET = ROOT / "dataset-by-format"
SCHEMA = "synthetic-barcode-grouped-v3"
NO_BARCODE = "NO_BARCODE"
EXTENDED_FORMATS = FORMATS | ADDITIONAL_LINEAR_FORMATS
ATLAS_SPECS = {
    ATLAS: BACKGROUNDS,
    ROOT / "backgrounds/scenes-atlas-1.png": (
        "parcel-conveyor", "blue-tray-zip-pouch", "laptop-and-walnut", "pharmacy-blister-packs",
        "silver-mailer", "mustard-envelope", "luggage-zipper", "bottle-on-stone",
        "coral-carton", "white-storage-tote", "green-bag-terrazzo", "warehouse-shelf",
    ),
    ROOT / "backgrounds/scenes-atlas-2.png": (
        "parcel-on-blue-steel", "teal-plastic-tub", "clear-clamshell", "paper-on-ceramic",
        "pink-bubble-mailer", "red-retail-box", "gray-rubber-bin", "kraft-mailing-tube",
        "amber-poly-bag", "sage-tissue", "mint-dispatch-tray", "open-paper-bag",
    ),
}
BACKGROUND_NAMES = tuple(name for names in ATLAS_SPECS.values() for name in names)
APPEARANCES = ("paper-label", "retail-sticker", "direct-print", "hang-tag", "laminated-sticker")
SINGLE_COMPOSITIONS = ("close-up", "mid-shot", "wide-shot", "edge-positioned")
MULTI_COMPOSITIONS = ("stacked", "side-by-side", "staggered", "clustered", "scattered")
SIZES = ((512, 512), (576, 768), (600, 400), (640, 480), (640, 800), (672, 512),
         (720, 720), (768, 432), (800, 600), (896, 504), (960, 640), (1024, 512))
SIMILARITY_RULE = {"phash_max_distance": 8, "dhash_max_distance": 5,
                   "rgb_thumbnail_size": 24, "thumbnail_mae_max": 10.0}


def asset_hashes():
    return {path.name: sha256(path.read_bytes()).hexdigest() for path in ATLAS_SPECS}


def relative_image(group, sample_id):
    parent = "controls/no-barcode" if group == NO_BARCODE else f"images/{group}"
    return f"{parent}/{sample_id}.jpg"


def balanced_draw(options, count, rng):
    bag = [options[index % len(options)] for index in range(count)]
    rng.shuffle(bag)
    return bag


def make_extended_symbol(fmt, rng, used):
    if fmt in FORMATS:
        return make_symbol(fmt, rng, used)

    def digits(length):
        return "".join(rng.choices(string.digits, k=length))

    def letters(length):
        return "".join(rng.choices(string.ascii_uppercase, k=length))

    options = {}
    while True:
        if fmt == "GS1_128":
            text = "(01)" + with_check_digit("0" + digits(12))
            if rng.choice((True, False)):
                text += "(10)" + letters(2) + digits(rng.randint(3, 6))
            options["height"] = round(rng.uniform(9, 16), 2)
        elif fmt == "IATA_2_OF_5":
            text = digits(rng.choice((8, 10, 12, 14)))
            options["height"] = round(rng.uniform(8, 17), 2)
        elif fmt == "KIX":
            text = rng.choice("123456789") + digits(3) + letters(2) + str(rng.randint(1, 299))
            if rng.choice((True, False)):
                text += "X" + letters(1)
        elif fmt == "POSTNET":
            text = digits(rng.choice((5, 9, 11)))
        elif fmt == "ROYAL_MAIL":
            text = letters(rng.choice((1, 2))) + digits(rng.choice((1, 2))) + digits(1) + letters(2)
            text += digits(1) + letters(1)
        elif fmt == "USPS_INTELLIGENT_MAIL":
            tracking = digits(1) + rng.choice("01234") + digits(18)
            text = tracking + digits(rng.choice((0, 5, 9, 11)))
        else:
            raise ValueError(f"Unsupported format {fmt}")
        if (fmt, text) not in used:
            used.add((fmt, text))
            return {"format": fmt, "encoder": ADDITIONAL_LINEAR_FORMATS[fmt], "text": text, "options": options}


def make_plan(count, seed):
    rng = random.Random(seed)
    groups = list(EXTENDED_FORMATS)
    rng.shuffle(groups)
    strata = [("clean", 0)] + [(effect, tier) for effect in (*EFFECTS, "combined") for tier in (1, 2, 3)]
    positives = count - round(count * .02)
    multi = round(count * .16)
    plan, used = [], set()
    for index, fmt in enumerate(groups):
        size = (index + 1) * positives // len(groups) - index * positives // len(groups)
        group_multi = (index + 1) * multi // len(groups) - index * multi // len(groups)
        shuffled_strata = list(strata)
        rng.shuffle(shuffled_strata)
        mixes = set(rng.sample(range(size), group_multi))
        scenes = list(BACKGROUND_NAMES)
        rng.shuffle(scenes)
        backgrounds = balanced_draw(scenes, size, rng)
        appearances = balanced_draw(APPEARANCES, size, rng)
        singles = iter(balanced_draw(SINGLE_COMPOSITIONS, size - group_multi, rng))
        for number, ((scenario, tier), bg, style) in enumerate(
                zip(balanced_draw(shuffled_strata, size, rng), backgrounds, appearances, strict=True)):
            multiplicity = rng.choices((2, 3, 4), (70, 24, 6))[0] if number in mixes else 1
            composition = next(singles) if multiplicity == 1 else rng.choice(MULTI_COMPOSITIONS)
            plan.append({"format_group": fmt, "background": bg, "appearance": style,
                         "composition": composition, "scenario": scenario, "tier": tier,
                         "symbols": [make_extended_symbol(fmt, rng, used)
                                     for _ in range(multiplicity)]})
    for bg in balanced_draw(BACKGROUND_NAMES, count - positives, rng):
        plan.append({"format_group": NO_BARCODE, "background": bg, "appearance": "none",
                     "composition": "background-only", "scenario": "negative", "tier": 0, "symbols": []})
    rng.shuffle(plan)
    for index, sample in enumerate(plan, 1):
        sample.update(sample_id=f"syn2-{index:05d}", seed=rng.getrandbits(63))
    return plan


def make_scene(tile, width, height, rng):
    quarter_turns = rng.randrange(4)
    flip = rng.choice((True, False))
    tile = np.rot90(tile, quarter_turns)
    if flip:
        tile = tile[:, ::-1]
    tile_height, tile_width = tile.shape[:2]
    zoom = rng.uniform(.43, 1)
    ratio = width / height
    crop_height = round(min(tile_width / ratio, tile_height) * zoom)
    crop_width = min(tile_width, round(crop_height * ratio))
    x, y = rng.randint(0, tile_width - crop_width), rng.randint(0, tile_height - crop_height)
    resized = cv2.resize(tile[y:y + crop_height, x:x + crop_width], (width, height), interpolation=cv2.INTER_LINEAR)
    gain, bias = rng.uniform(.70, 1.21), rng.uniform(-15, 13)
    warmth = rng.uniform(-13, 13)
    angle = rng.uniform(0, np.pi * 2)
    falloff = rng.uniform(-58, 58)
    rows = np.linspace(-.5, .5, height, dtype=np.float32)[:, None]
    columns = np.linspace(-.5, .5, width, dtype=np.float32)[None, :]
    light = (columns * np.cos(angle) + rows * np.sin(angle)) * falloff + bias
    warmth_vector = np.float32([-warmth, 0, warmth])
    result = np.clip(resized.astype(np.float32) * gain + light[:, :, None] + warmth_vector, 0, 255)
    return result.astype(np.uint8), {"quarter_turns": quarter_turns, "mirrored": flip,
        "crop": [x, y, crop_width, crop_height], "gain": round(gain, 4), "bias": round(bias, 4),
        "warmth": round(warmth, 4), "gradient_angle": round(float(angle), 4), "gradient": round(falloff, 4)}


def layout_boxes(width, height, count, composition, rng):
    def scaled(rect):
        x0, y0, x1, y1 = rect
        return round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)

    if not count:
        return [], (0, 0)
    if count == 1:
        if composition == "edge-positioned":
            edge = rng.choice(((0, .06, .71, .92), (.29, .08, 1, .94), (.08, 0, .92, .70), (.06, .30, .94, 1)))
            return [scaled(edge)], (.50, .86)
        size = {"close-up": (.82, .96), "mid-shot": (.57, .81), "wide-shot": (.34, .52)}[composition]
        return [(0, 0, width, height)], size
    x, y = rng.uniform(.43, .57), rng.uniform(.43, .57)
    if composition == "stacked" or composition == "side-by-side":
        if composition == "stacked":
            slabs = [(rng.uniform(0, .18), i / count, rng.uniform(.81, 1), (i + 1) / count) for i in range(count)]
        else:
            if count == 2:
                slabs = [(0, .04, x, .96), (x, 0, 1, .96)]
            else:
                slabs = [(i / count, rng.uniform(0, .27), (i + 1) / count, rng.uniform(.74, 1)) for i in range(count)]
        return [scaled(rect) for rect in slabs], (.56, .92)
    grid = [(0, 0, x, y), (x, 0, 1, y), (0, y, x, 1), (x, y, 1, 1)]
    if composition == "staggered" and count == 2:
        diagonals = rng.choice(((0, 3), (1, 2)))
        return [scaled(grid[index]) for index in diagonals], (.60, .96)
    if composition == "clustered":
        grid = [(a * .77 + .11, b * .78 + .1, c * .77 + .11, d * .78 + .1) for a, b, c, d in grid]
    rng.shuffle(grid)
    return [scaled(rect) for rect in grid[:count]], (.54, .95)


def signature(image):
    size = SIMILARITY_RULE["rgb_thumbnail_size"]
    thumb = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    low = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    coefficients = cv2.dct(low)[:8, :8].ravel()
    adjacent = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    phash = int.from_bytes(np.packbits(coefficients > np.median(coefficients[1:])), "big")
    dhash = int.from_bytes(np.packbits(adjacent[:, 1:] > adjacent[:, :-1]), "big")
    return phash, dhash, thumb


def near_duplicate(candidate, accepted):
    phash, dhash, thumb = candidate
    phash_max = SIMILARITY_RULE["phash_max_distance"]
    dhash_max = SIMILARITY_RULE["dhash_max_distance"]
    mae_max = SIMILARITY_RULE["thumbnail_mae_max"]
    for previous_id, old_phash, old_dhash, old_thumb in accepted:
        if (phash ^ old_phash).bit_count() <= phash_max or (dhash ^ old_dhash).bit_count() <= dhash_max:
            if cv2.absdiff(thumb, old_thumb).mean() <= mae_max:
                return previous_id
    return None


def accept_frame(result, renderer, sample, pngs, tiles, accepted):
    for attempt in range(32):
        row, data, fingerprint, reason = result
        if reason is None and near_duplicate(fingerprint, accepted) is None:
            return row, data, fingerprint
        if attempt < 31:
            result = renderer(sample, pngs, tiles, attempt + 1)
    raise ValueError(f"Could not render a distinct image with a visible barcode pattern for {row['sample_id']}: "
                     f"{reason or 'near duplicate'}")


def render(sample, pngs, tiles, retry):
    render_seed = sample["seed"] + retry * 0x9E3779B97F4A7C15
    rng = random.Random(render_seed)
    scenario, composition, style = sample["scenario"], sample["composition"], sample["appearance"]
    fx = random.Random(sample["seed"])
    effects, tier = choose_effects(scenario, sample["tier"], fx)
    width, height = retry_frame_size(*rng.choice(SIZES), retry)
    backdrop = sample["background"]
    canvas, background_params = make_scene(tiles[backdrop], width, height, rng)
    symbols = sample["symbols"]
    boxes, size = layout_boxes(width, height, len(symbols), composition, rng)
    strength = effect_strength(retry) * sample.get("initial_strength", 1)
    ground_truth = [render_symbol(canvas, symbol, png, box, effects, tier, rng, len(symbols),
                                  appearance=style, scale=size, ambient_angle=rng.uniform(-7, 7), strength=strength)
                    for symbol, png, box in zip(symbols, pngs, boxes, strict=True)]
    canvas, frame = apply_frame_effects(canvas, effects, tier, rng, render_seed, ground_truth, strength)
    out_height, out_width = canvas.shape[:2]
    scale_polygons(ground_truth, (width, height), (out_width, out_height))
    sample_id, group = sample["sample_id"], sample["format_group"]
    path = relative_image(group, sample_id)
    data = encode_jpeg(canvas, sample_id)
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    row = {"sample_id": sample_id, "relative_path": path, "image_sha256": sha256(data).hexdigest(),
           "width": out_width, "height": out_height, "source_size": [width, height],
           "format_group": group, "scenario": scenario, "severity": tier, "effects": effects,
           "seed": sample["seed"], "render_attempt": retry, "composition": composition,
           "appearance": style, "background": backdrop, "background_transform": background_params,
           "frame_transform": frame, "ground_truth": ground_truth}
    return row, data, signature(decoded), image_failure(decoded, ground_truth, pngs)


def generate(count, seed, jobs, output):
    cv2.setNumThreads(1)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    tiles = {name: tile for path, names in ATLAS_SPECS.items()
             for name, tile in read_backgrounds(path, names).items()}
    plan = make_plan(count, seed)
    inventory = {"schema": SCHEMA, "seed": seed, "images": count, "jpeg_quality": JPEG_QUALITY,
                 "python": platform.python_version(), "numpy": np.__version__, "opencv": cv2.__version__,
                 "bwip_js": "4.11.4", "background_sha256": asset_hashes(), "similarity_rule": SIMILARITY_RULE,
                 "quality_rule": QUALITY_RULE, "geometry_rule": GEOMETRY_RULE}
    counters = {"by_format": Counter(), "by_directory": Counter(), "by_scenario": Counter(), "by_effect": Counter(),
                "by_background": Counter(), "by_symbol_count": Counter(), "by_composition": Counter(),
                "by_appearance": Counter()}
    accepted = []
    rejections = 0
    with TemporaryDirectory(prefix=".generate-", dir=output.parent) as temporary:
        temp = Path(temporary)
        encoded = encode_plan(plan, temp)
        stage = temp / "dataset"
        for group in (*EXTENDED_FORMATS, NO_BARCODE):
            (stage / relative_image(group, "sample")).parent.mkdir(parents=True)
        manifest_path = stage / "manifest.jsonl"
        with (encoded.open(encoding="utf-8") as symbols,
              manifest_path.open("w", encoding="utf-8", newline="\n") as manifest,
              ThreadPoolExecutor(max_workers=jobs) as pool):
            for start in range(0, count, 100):
                batch = [(sample, json.loads(next(symbols))) for sample in plan[start:start + 100]]
                pending = [pool.submit(render, sample, pngs, tiles, 0) for sample, pngs in batch]
                for (sample, pngs), task in zip(batch, pending, strict=True):
                    row, data, fingerprint = accept_frame(task.result(), render, sample, pngs, tiles, accepted)
                    rejections += row["render_attempt"]
                    accepted.append((row["sample_id"], *fingerprint))
                    (stage / row["relative_path"]).write_bytes(data)
                    manifest.write(dump(row) + "\n")
                    counters["by_format"].update(truth["format"] for truth in row["ground_truth"])
                    counters["by_effect"].update(row["effects"])
                    for name, value in (("directory", row["format_group"]), ("scenario", row["scenario"]),
                                        ("background", row["background"]), ("symbol_count", len(row["ground_truth"])),
                                        ("composition", row["composition"]), ("appearance", row["appearance"])):
                        counters[f"by_{name}"][value] += 1
                if (start + len(batch)) % 1000 == 0:
                    print(f"Rendered {start + len(batch):,}/{count:,}, rerendered {rejections:,} candidates",
                          flush=True)
            if next(symbols, None) is not None:
                raise ValueError("Encoder returned too many rows")
        inventory.update({name: dict(sorted(records.items())) for name, records in counters.items()})
        inventory.update(barcodes=sum(counters["by_format"].values()), rerenders=rejections,
                         manifest_sha256=sha256(manifest_path.read_bytes()).hexdigest())
        (stage / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
        stage.rename(output)
    print(f"Finished {count:,} images with {inventory['barcodes']:,} annotations and {rejections:,} rerenders", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=4804)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--output", type=Path, default=DATASET)
    args = parser.parse_args()
    if args.count < 100 or args.jobs < 1:
        parser.error("count must be at least 100 and jobs must be positive")
    generate(args.count, args.seed, args.jobs, args.output.resolve())
