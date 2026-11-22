"""Verify the generated inventory, file hashes, dimensions and ground-truth geometry."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from barcode_quality import GEOMETRY_RULE, POLARITY_EFFECTS, QUALITY_RULE, image_failure
from capture_effects import CAPTURE_PROFILES, COMBINATIONS
from expand_corpus import ALL_FORMATS, MAX_SYMBOLS, MIXED, SCHEMA as EXPANDED_SCHEMA, msi_check_digit
from rendering import ATLAS, BACKGROUNDS, EFFECTS, FORMATS, ROOT, encode_plan, with_check_digit
from generate_by_format import (APPEARANCES, BACKGROUND_NAMES, EXTENDED_FORMATS, MULTI_COMPOSITIONS,
                                DATASET, NO_BARCODE, SCHEMA, SIMILARITY_RULE, SINGLE_COMPOSITIONS,
                                asset_hashes, near_duplicate, relative_image, signature)


def read_jsonl(path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expand_upce(text):
    system, a, b, c, d, e, suffix, check = text
    if suffix in "012":
        return f"{system}{a}{b}{suffix}0000{c}{d}{e}{check}"
    if suffix == "3":
        return f"{system}{a}{b}{c}00000{d}{e}{check}"
    if suffix == "4":
        return f"{system}{a}{b}{c}{d}00000{e}{check}"
    return f"{system}{a}{b}{c}{d}{e}0000{suffix}{check}"


def valid_added_payload(fmt, text):
    if fmt == "MSI_CODE":
        return text.isdigit() and 9 <= len(text) <= 12 and msi_check_digit(text[:-1]) == text[-1]
    if fmt == "PHARMACODE_ONE_TRACK":
        return text.isdigit() and 3 <= int(text) <= 131070 and text == str(int(text))
    if fmt == "DOTCODE":
        return re.fullmatch(r"SYN-[A-Z0-9]{14,36}", text) is not None
    if fmt == "GS1_128":
        match = re.fullmatch(r"\(01\)([0-9]{14})(?:\(10\)[A-Z0-9]{1,20})?", text)
        return match is not None and with_check_digit(match[1][:-1]) == match[1]
    if fmt in ("IATA_2_OF_5", "POSTNET", "USPS_INTELLIGENT_MAIL"):
        allowed_lengths = {"IATA_2_OF_5": (8, 10, 12, 14), "POSTNET": (5, 9, 11),
                           "USPS_INTELLIGENT_MAIL": (20, 25, 29, 31)}
        return (len(text) in allowed_lengths[fmt] and text.isdigit()
                and (fmt != "USPS_INTELLIGENT_MAIL" or text[1] in "01234"))
    if fmt == "KIX":
        return re.fullmatch(r"[1-9][0-9]{3}[A-Z]{2}[0-9]{1,3}(?:X[A-Z])?", text) is not None
    if fmt == "ROYAL_MAIL":
        return re.fullmatch(r"[A-Z]{1,2}[0-9]{2,3}[A-Z]{2}[0-9][A-Z]", text) is not None
    return True


def load_image(source, row):
    path = Path(row["relative_path"])
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Invalid image path {path}")
    data = (source / path).read_bytes()
    if sha256(data).hexdigest() != row["image_sha256"]:
        raise ValueError(f"Image differs from the manifest: {path}")
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def inverted(row):
    return bool(POLARITY_EFFECTS.intersection(row["effects"])) or any(item["inverted"] for item in row["ground_truth"])


def references(row):
    return {"symbols": [
        {"encoder": ALL_FORMATS[item["format"]], "options": item["encoder_options"],
         "text": item["text"][:-1] if item["format"] == "MSI_CODE" else item["text"]}
        for item in row["ground_truth"]
    ]}


def check_barcode_patterns(source, rows, work, *, check_geometry=True):
    rejected = {row["sample_id"]: "inversion" for row in rows if inverted(row)}
    candidates = [row for row in rows if row["ground_truth"] and not inverted(row)]
    work.mkdir()
    encoded = encode_plan([references(row) for row in candidates], work)
    with encoded.open(encoding="utf-8") as source_masks:
        for index, (row, masks) in enumerate(zip(candidates, source_masks, strict=True), 1):
            reason = image_failure(load_image(source, row), row["ground_truth"], json.loads(masks),
                                   check_geometry=check_geometry)
            if reason:
                rejected[row["sample_id"]] = reason
            if index % 2000 == 0:
                print(f"Screened {index:,}/{len(candidates):,} positive frames", flush=True)
    return rejected


def validate_capture(sample, profiles, combinations, capture_effects):
    frame = sample["frame_transform"]
    effects = set(sample["effects"])
    key = sample["sample_id"]
    scenario = sample["scenario"]
    require(set(frame) & capture_effects == effects and 1 <= sample["severity"] <= 3, f"Invalid capture parameters {key}")
    if scenario == "combined":
        require(any(effects == set(combo) for combo in combinations), f"Unknown combined capture case {key}")
    else:
        require(effects == {scenario} and scenario in profiles, f"Wrong capture profile {key}")
    if effects & {"frame_rotation", "frame_perspective"}:
        require("homography" in frame, f"Missing frame transform {key}")
    if "glare" in frame:
        require(frame["glare_spot"][2] > 0, f"Missing radial glare {key}")
    if "blur_stack" in frame:
        require(all(value > 0 for value in frame["blur_stack"]) and "motion_angle_degrees" in frame, f"Incomplete blur stack {key}")
    if "motion_blur" in frame:
        require(frame["motion_blur"] > 0 and "motion_angle_degrees" in frame, f"Incomplete motion blur {key}")
    if "high_density" in frame:
        require(5 <= len(sample["ground_truth"]) <= MAX_SYMBOLS, f"Incorrect density {key}")
    if "frame_crop" in frame:
        crop = frame["crop"]
        require(crop["requested"] == frame["frame_crop"] and min(crop["retained"]) < 1
                and min(crop["retained"]) + .005 >= crop["requested"], f"Ineffective frame crop {key}")
    homography = np.array(frame.get("homography", np.eye(3)), dtype=np.float64)
    offset = np.array(frame.get("crop", {}).get("rect", [0, 0])[:2])
    output_size = np.array([sample["width"], sample["height"]])
    pixel_scale = output_size / np.array(frame["pre_scale_size"])
    for item in sample["ground_truth"]:
        if "module_size" in frame:
            require(abs(item["nominal_px_per_module"] - frame["module_size"]) <= .015,
                    f"Module target was not achieved {key}")
        if "frame_padding" in frame:
            require(abs(item["cell_fill_ratio"] - 1 / frame["frame_padding"]) <= .0001,
                    f"Frame padding target was not achieved {key}")
        for before, after in (("scene_polygon", "polygon"), ("scene_label_polygon", "label_polygon")):
            projected = cv2.perspectiveTransform(np.float64([item[before]]), homography)[0] - offset
            projected = (projected + .5) * pixel_scale - .5
            require(np.allclose(projected, np.array(item[after]), rtol=0, atol=.002), f"Annotation transform differs {key}")
            if after == "label_polygon":
                require((projected >= -.01).all() and (projected <= output_size - .98).all(), f"Clipped label {key}")


def validate(dataset, expected_images):
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    manifest = dataset / "manifest.jsonl"
    expanded = inventory["schema"] in {EXPANDED_SCHEMA, "synthetic-barcode-v4"}
    curated = expanded and "curation" in inventory
    grouped = inventory["schema"] in {SCHEMA, "synthetic-barcode-v2"} or expanded
    strict_quality = inventory["schema"] in {SCHEMA, EXPANDED_SCHEMA} or "quality_rule" in inventory
    if strict_quality:
        require(inventory["quality_rule"] == QUALITY_RULE, "Unexpected image quality rule")
    if "geometry_rule" in inventory:
        require(inventory["geometry_rule"] == GEOMETRY_RULE, "Unexpected barcode geometry rule")
    effects_by_label = EFFECTS if strict_quality else (*EFFECTS, "inversion")
    profiles = CAPTURE_PROFILES if strict_quality else tuple(
        "frame_inversion" if profile == "motion_blur" else profile for profile in CAPTURE_PROFILES)
    combinations = COMBINATIONS if strict_quality else (
        *COMBINATIONS[:2], ("frame_inversion", "jpeg_compression", "blur_stack", "noise", "low_resolution"), COMBINATIONS[3])
    capture_effects = set(profiles).union(*combinations)
    require(grouped or inventory["schema"] == "synthetic-barcode-v1", "Unknown inventory schema")
    expected_formats = ALL_FORMATS if expanded else EXTENDED_FORMATS if grouped else FORMATS
    expected_backgrounds = BACKGROUND_NAMES if grouped else BACKGROUNDS
    if grouped:
        require(inventory["background_sha256"] == asset_hashes(), "Background atlas hashes differ")
        require(inventory["similarity_rule"] == SIMILARITY_RULE, "Unexpected similarity thresholds")
    else:
        require(sha256(ATLAS.read_bytes()).hexdigest() == inventory["atlas_sha256"], "Background atlas hash differs")
        require(set(FORMATS) <= set(json.loads((ROOT / "native/symbologies.json").read_text())),
                "Encoder and benchmark symbology lists differ")
    manifest_data = manifest.read_bytes()
    require(sha256(manifest_data).hexdigest() == inventory["manifest_sha256"], "Manifest hash differs")
    base_count = inventory.get("base_images", 0)
    if expanded and not curated:
        prefix = b"".join(manifest_data.splitlines(keepends=True)[:base_count])
        require(sha256(prefix).hexdigest() == inventory["base_manifest_sha256"], "Original annotation prefix changed")
    formats, scenarios, effects, backgrounds, multiplicities = (Counter() for _ in range(5))
    directories, compositions, appearances = (Counter() for _ in range(3))
    paths, hashes, payloads = set(), set(), set()
    coverage = {fmt: (set(), set(), set()) for fmt in expected_formats}
    accepted = []
    rerenders = 0
    capture_coverage, subsets, module_sizes = Counter(), Counter(), set()
    for index, sample in enumerate(read_jsonl(manifest)):
        key = f"syn2-{index + 1:05d}" if grouped else f"syn-{index + 1:05d}"
        subset = sample.get("subset", "base")
        if curated:
            key = sample["sample_id"]
            pattern = r"syn[24]-\d{5}" if subset == "base" else r"syn[34]-\d{5}"
            require(re.fullmatch(pattern, key) is not None and subset in {"base", "new-format", "capture", "mixed"},
                    f"Unexpected curated sample ID or subset {key}")
        elif expanded and index >= base_count:
            key = f"syn3-{index + 1 - base_count:05d}"
            require(subset in {"new-format", "capture", "mixed"}, f"Unexpected expansion subset {key}")
        else:
            require(subset == "base", f"Unexpected base subset {key}")
        subsets[subset] += 1
        truth_items = sample["ground_truth"]
        if grouped:
            group = sample["format_group"]
            require(group in expected_formats or group == NO_BARCODE or (expanded and group == MIXED),
                    f"Unknown format directory {key}")
            actual_formats = {item["format"] for item in truth_items}
            if group == MIXED:
                require(subset == "mixed" and len(actual_formats) >= 2, f"Invalid mixed group {key}")
            else:
                require(subset != "mixed" and actual_formats == ({group} if group != NO_BARCODE else set()),
                        f"Mixed or misplaced symbols {key}")
            require(len({(item["format"], item["text"]) for item in truth_items}) == len(truth_items),
                    f"Repeated payload in one image {key}")
            relative = relative_image(group, key)
            directories[group] += 1
            compositions[sample["composition"]] += 1
            appearances[sample["appearance"]] += 1
            rerenders += sample["render_attempt"]
            if group != NO_BARCODE:
                require(sample["appearance"] in APPEARANCES, f"Unknown label appearance {key}")
                allowed = SINGLE_COMPOSITIONS if len(truth_items) == 1 else MULTI_COMPOSITIONS if len(truth_items) <= 4 else ("dense-grid",)
                require(sample["composition"] in allowed, f"Incorrect layout for symbol count {key}")
                if group != MIXED and subset in {"base", "new-format"}:
                    scene_coverage, scenario_coverage, style_coverage = coverage[group]
                    scene_coverage.add(sample["background"])
                    scenario_coverage.add(sample["scenario"])
                    style_coverage.add(sample["appearance"])
        else:
            relative = f"images/{index // 500:02d}/{key}.jpg"
        require(sample["sample_id"] == key and sample["relative_path"] == relative, f"Unexpected ID/path {key}")
        paths.add(relative)
        data = (dataset / relative).read_bytes()
        digest = sha256(data).hexdigest()
        require(digest == sample["image_sha256"] and digest not in hashes, f"Hash mismatch or duplicate {key}")
        hashes.add(digest)
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        width, height = sample["width"], sample["height"]
        require(image is not None and image.shape[:2] == (height, width), f"Incorrect image dimensions {key}")
        if grouped:
            fingerprint = signature(image)
            match = near_duplicate(fingerprint, accepted)
            require(match is None, f"Near-duplicate image pair under declared thresholds: {match}, {key}")
            accepted.append((key, *fingerprint))
        require(sample["background"] in expected_backgrounds, f"Unknown background {key}")
        capture = subset in {"capture", "mixed"}
        require(set(sample["effects"]) <= (capture_effects if capture else set(effects_by_label)), f"Unknown effect {key}")
        require((sample["scenario"] == "negative") == (not sample["ground_truth"]), f"Missing or extra truth {key}")
        require(len(sample["ground_truth"]) <= (MAX_SYMBOLS if capture else 4), f"Too many symbols {key}")
        scenario, severity, effects_applied = sample["scenario"], sample["severity"], sample["effects"]
        if capture:
            validate_capture(sample, profiles, combinations, capture_effects)
            capture_coverage[(group, tuple(effects_applied))] += 1
            if "module_size" in effects_applied:
                module_sizes.add(sample["frame_transform"]["module_size"])
        elif scenario == "clean":
            require(severity == 0 and not effects_applied, f"Invalid clean control {key}")
        elif scenario == "combined":
            require(1 <= severity <= 3 and len(set(effects_applied)) == severity + 1, f"Invalid combined effects {key}")
        elif scenario != "negative":
            require(effects_applied == [scenario] and (severity == 0 if scenario == "inversion" else 1 <= severity <= 3),
                    f"Invalid effect or severity {key}")
        backgrounds[sample["background"]] += 1
        effects.update(sample["effects"])
        multiplicities[len(sample["ground_truth"])] += 1
        scenarios[sample["scenario"]] += 1
        for truth in truth_items:
            fmt, text = truth["format"], truth["text"]
            require(fmt in expected_formats and text.isascii() and text and (fmt, text) not in payloads,
                    f"Invalid or duplicate ground truth {key}")
            require(valid_added_payload(fmt, text), f"Invalid {fmt} payload {key}")
            payloads.add((fmt, text))
            if fmt == "CODE_93":
                require(truth["encoder_options"].get("includecheck") is True, f"Missing Code 93 checksums {key}")
            require(truth["inverted"] == bool({"inversion", "frame_inversion"} & set(effects_applied)), f"Wrong polarity metadata {key}")
            require((0 < truth["occluded_fraction"] < 1) == ("occlusion" in effects_applied), f"Wrong occlusion metadata {key}")
            if fmt in ("EAN_13", "EAN_8", "UPC_A", "UPC_E"):
                length = {"EAN_13": 13, "EAN_8": 8, "UPC_A": 12, "UPC_E": 8}[fmt]
                require(len(text) == length and text.isdigit(), f"Invalid {fmt} payload {key}")
                gtin = expand_upce(text) if fmt == "UPC_E" else text
                require(with_check_digit(gtin[:-1]) == gtin, f"Bad {fmt} check digit {key}")
            polygon = np.array(truth["polygon"], dtype=np.float32)
            require(polygon.shape == (4, 2) and np.isfinite(polygon).all() and (polygon >= 0).all()
                    and (polygon < [width, height]).all() and cv2.isContourConvex(polygon)
                    and cv2.contourArea(polygon) > 0, f"Invalid polygon {key}")
            formats[fmt] += 1
    image_roots = ("images", "controls") if grouped else ("images",)
    require(paths == {path.relative_to(dataset).as_posix() for root in image_roots
                      for path in (dataset / root).rglob("*.jpg")},
            "Dataset contains missing or unlisted JPEGs")
    require(len(paths) == inventory["images"] == expected_images, "Image count differs")
    require(sum(formats.values()) == inventory["barcodes"], "Barcode count differs")
    require(set(formats) == set(expected_formats), "Missing format coverage")
    if not grouped or expected_images >= 3000:
        require(set(backgrounds) == set(expected_backgrounds), "Missing background coverage")
    expected_controls = inventory["curation"]["controls"] if curated else round((base_count if expanded else expected_images) * .02)
    require(multiplicities[0] == expected_controls, "Wrong number of negative images")
    if not expanded:
        require(sum(multiplicities[n] for n in (2, 3, 4)) == round(expected_images * .16), "Wrong number of multi-code images")
    counts = {"by_format": formats, "by_scenario": scenarios, "by_effect": effects,
              "by_background": backgrounds, "by_symbol_count": multiplicities}
    if grouped:
        counts.update(by_directory=directories, by_composition=compositions, by_appearance=appearances)
        image_counts = [directories[fmt] for fmt in expected_formats]
        if not expanded:
            require(max(image_counts) - min(image_counts) <= 1, "Image counts differ across format directories")
        require(rerenders == inventory.get("rerenders", inventory.get("similarity_rerenders")), "Unexpected rerender count")
        if expected_images >= 3000:
            required_scenarios = set(effects_by_label) | {"clean", "combined"}
            checked_formats = expected_formats if not expanded or inventory["expansion"]["new_format_images"] >= 36 else EXTENDED_FORMATS
            for fmt in checked_formats:
                scene_coverage, scenario_coverage, style_coverage = coverage[fmt]
                require(set(expected_backgrounds) == scene_coverage and required_scenarios == scenario_coverage
                        and set(APPEARANCES) == style_coverage, f"Incomplete scene variation for {fmt}")
        if expanded:
            settings = inventory["expansion"]
            counts["by_subset"] = subsets
            expected_capture = {(fmt, (profile,)): settings["stress_per_profile"] for fmt in ALL_FORMATS for profile in profiles}
            expected_capture.update({(MIXED, (profile,)): settings["mixed_per_profile"] for profile in profiles})
            expected_capture.update({(MIXED, combo): settings["mixed_per_profile"] for combo in combinations})
            if curated:
                require(capture_coverage.keys() == expected_capture.keys() and
                        all(0 < capture_coverage[key] <= count if key[0] == MIXED else capture_coverage[key] == count
                            for key, count in expected_capture.items()), "Incomplete curated capture coverage")
            else:
                require(subsets["new-format"] == (len(ALL_FORMATS) - len(EXTENDED_FORMATS)) * settings["new_format_images"],
                        "Wrong number of extra-format frames")
                require(capture_coverage == expected_capture, "Incomplete expanded capture coverage")
            if max(settings["stress_per_profile"], settings["mixed_per_profile"]) >= 6:
                minimum_pitch = QUALITY_RULE["min_requested_px_per_module"] if strict_quality else 1
                require(module_sizes == set(range(minimum_pitch, 7)), "Incomplete module-pitch sweep")
            if max(settings["stress_per_profile"] + 4, settings["mixed_per_profile"]) >= 12:
                require(max(multiplicities) == MAX_SYMBOLS, "Missing highest-density cases")
    for field, observed in counts.items():
        require(inventory[field] == {str(key): value for key, value in observed.items()}, f"Incorrect {field}")
    print(f"Verified {len(paths):,} JPEGs with unique hashes and {sum(formats.values()):,} barcode annotations")
    if grouped:
        print(f"Verified {len(formats)} single-format directories and zero near-duplicate pairs under the declared thresholds")
    if strict_quality:
        with TemporaryDirectory(prefix=".quality-", dir=dataset.parent) as work:
            rows = list(read_jsonl(manifest))
            rejected = check_barcode_patterns(dataset, rows, Path(work) / "screen",
                                               check_geometry="geometry_rule" in inventory)
            require(not rejected, f"Quality rule failed for {list(rejected.items())[:12]}")
        print("Verified normal polarity and retained barcode structure in every positive image", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--expected-images", type=int, default=8000)
    args = parser.parse_args()
    validate(args.dataset, args.expected_images)
