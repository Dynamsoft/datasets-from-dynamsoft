"""Score verified benchmark records with one-to-one format and payload matching."""

import argparse
from collections import Counter, defaultdict, deque
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import mean, median

from expand_corpus import ALL_FORMATS
from rendering import with_check_digit
from generate_by_format import DATASET
from validate import expand_upce, read_jsonl, require


DECODERS = ("dynamsoft-dbr", "scandit-linux", "zxing-cpp")
CANONICAL = {fmt.replace("_", ""): fmt for fmt in ALL_FORMATS}
CANONICAL.update({"MICROQRCODE": "MICRO_QR", "CODE39EXTENDED": "CODE_39", "MSIPLESSEY": "MSI_CODE",
                  "RM4SCC": "ROYAL_MAIL", "ROYALMAIL4STATE": "ROYAL_MAIL", "AZTECCODE": "AZTEC",
                  "CODE39STD": "CODE_39", "CODE39EXT": "CODE_39", "ITF14": "ITF",
                  "QRCODEMODEL1": "QR_CODE", "QRCODEMODEL2": "QR_CODE"})
GS1 = re.compile(r"01([0-9]{14})(?:10[A-Z]{2}[0-9]{3,6})?\Z")
ROYAL_MAIL_BODY = re.compile(r"[A-Z]{1,2}[0-9]{2,3}[A-Z]{2}[0-9][A-Z]\Z")
ROYAL_MAIL_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def normalized_key(item):
    raw_format = item["format"]
    canonical = "".join(character for character in raw_format.upper() if character.isalnum())
    fmt = CANONICAL.get(canonical, raw_format)
    text = item["text"]
    if fmt in {"CODE_128", "GS1_128"}:
        candidate = re.sub(r"^(?:\]C1|\x1d|\{GS\}|\{FNC1\})+", "", text)
        candidate = re.sub(r"\((01|10)\)", r"\1", candidate)
        parsed = GS1.fullmatch(candidate)
        if parsed and with_check_digit(parsed[1][:-1]) == parsed[1]:
            return "GS1_128", candidate
    if fmt in ("UPC_A", "EAN_13") and len(text) == 13 and text.startswith("0") and text.isdigit():
        return "UPC_A", text[1:]
    if fmt == "UPC_E" and text.isascii() and text.isdigit():
        if len(text) == 8:
            text = expand_upce(text)
        if len(text) == 13 and text.startswith("0"):
            text = text[1:]
    if fmt == "CODABAR" and len(text) > 2 and text[0] in "ABCD" and text[-1] in "ABCD":
        text = text[1:-1]
    if fmt == "CODE_39" and len(text) > 2 and text[0] == text[-1] == "*":
        text = text[1:-1]
    if fmt == "POSTNET" and len(text) in (6, 10, 12) and text.isascii() and text.isdigit():
        if sum(map(int, text)) % 10 == 0:
            text = text[:-1]
    if fmt == "ROYAL_MAIL" and ROYAL_MAIL_BODY.fullmatch(text[:-1]):
        positions = [ROYAL_MAIL_ALPHABET.index(character) for character in text[:-1]]
        row = (sum(value // 6 + 1 for value in positions) - 1) % 6
        column = (sum(value % 6 + 1 for value in positions) - 1) % 6
        if text[-1] == ROYAL_MAIL_ALPHABET[row * 6 + column]:
            text = text[:-1]
    return fmt, text


def match(truth, predictions):
    remaining = defaultdict(deque)
    for index, expected in enumerate(truth):
        remaining[normalized_key(expected)].append(index)
    pairs, extras = [], []
    for index, prediction in enumerate(predictions):
        targets = remaining.get(normalized_key(prediction))
        if targets:
            pairs.append([targets.popleft(), index])
        else:
            extras.append(index)
    return pairs, sorted(index for targets in remaining.values() for index in targets), extras


def wrong_matches(truth, predictions, missed, extra, matched_keys):
    """Pair remaining annotations and predictions by payload first, then by format."""
    remaining_truth = {index: normalized_key(truth[index]) for index in missed}
    remaining_predictions = {}
    for index in extra:
        key = normalized_key(predictions[index])
        if key not in matched_keys:
            remaining_predictions[index] = key
    wrong = []
    for field in (1, 0):
        candidates = defaultdict(deque)
        for index, key in remaining_predictions.items():
            candidates[key[field]].append(index)
        for truth_index, key in list(remaining_truth.items()):
            if candidates[key[field]]:
                prediction_index = candidates[key[field]].popleft()
                wrong.append([truth_index, prediction_index])
                del remaining_truth[truth_index]
                del remaining_predictions[prediction_index]
    return wrong


def annotate(row, truth, supported):
    predictions, error = row["predictions"], row["error"]
    pairs, missed, extra = match(truth, predictions)
    unsupported = [index for index in missed if truth[index]["format"] not in supported]
    matched_keys = {normalized_key(truth[index]) for index, _ in pairs}
    eligible_misses = [index for index in missed if truth[index]["format"] in supported]
    wrong = wrong_matches(truth, predictions, eligible_misses, extra, matched_keys) if not error else []
    duplicates = sum(normalized_key(predictions[index]) in matched_keys for index in extra)
    row.update(pairs=pairs, missed=missed, extra=extra, unsupported=unsupported, wrong=wrong, duplicates=duplicates)


def read_run(dataset, run):
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
    manifest = dataset / "manifest.jsonl"
    results_file = run / "results.jsonl"
    require(sha256(manifest.read_bytes()).hexdigest() == inventory["manifest_sha256"] == metadata["manifest_sha256"],
            "Manifest hash differs from inventory or run")
    require(sha256(results_file.read_bytes()).hexdigest() == metadata["results_sha256"], "Results hash differs")
    require(set(metadata["decoders"]) == set(DECODERS), "Unexpected decoder set")
    if "dataset_schema" in metadata:
        require(metadata["dataset_schema"] == inventory["schema"], "Dataset schema differs from the recorded run")
    for decoder, config in (("dynamsoft-dbr", "dynamsoft-settings.json"), ("scandit-linux", "scandit-settings.json")):
        require(sha256((run / config).read_bytes()).hexdigest() == metadata["decoders"][decoder]["settings"]["config_sha256"],
                f"Configuration hash differs for {decoder}")
    samples = {sample["sample_id"]: sample for sample in read_jsonl(manifest)}
    require(len(samples) == inventory["images"] == metadata["images"], "Unexpected number of unique samples")
    rows = {key: {} for key in samples}
    for row in read_jsonl(results_file):
        key, decoder = row["sample_id"], row["decoder"]
        require(key in rows and decoder in DECODERS and decoder not in rows[key], f"Unexpected/duplicate result {key} {decoder}")
        require(isinstance(row["decode_ns"], int) and row["decode_ns"] >= 0, f"Invalid timing {key} {decoder}")
        rows[key][decoder] = row
    require(all(set(sample) == set(DECODERS) for sample in rows.values()), "Missing decoder/sample results")
    return metadata, inventory, samples, rows


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def image_outcome(truth, matched, extras, error):
    if error:
        return "no-read"
    if extras:
        return "wrong"
    if truth == matched:
        return "exact"
    return "incomplete" if matched else "no-read"


def bucket_record(counter, truth, matched, extras, error):
    outcome = image_outcome(truth, matched, extras, error)
    counter.update(images=1, truth=truth, correct=matched, false_positives=extras,
                   errors=int(bool(error)), exact_images=int(outcome == "exact"),
                   wrong_read_images=int(outcome == "wrong"), no_read_images=int(outcome == "no-read"),
                   incomplete_images=int(outcome == "incomplete"))
    if truth:
        counter.update(positive_images=1, fully_read_positive_images=int(truth == matched))
    else:
        counter.update(negative_images=1, negative_images_with_predictions=int(bool(extras)))


def rates(counter):
    values = dict(counter)
    values.update(misses=counter["truth"] - counter["correct"],
                  recall=ratio(counter["correct"], counter["truth"]),
                  precision=ratio(counter["correct"], counter["correct"] + counter["false_positives"]),
                  exact_image_rate=ratio(counter["exact_images"], counter["images"]),
                  full_positive_image_rate=ratio(counter["fully_read_positive_images"], counter["positive_images"]),
                  negative_image_false_positive_rate=ratio(counter["negative_images_with_predictions"], counter["negative_images"]))
    return values


def timing_ms(times):
    ordered = sorted(times)
    return {"mean": mean(ordered), "p50": median(ordered), "p95": ordered[(95 * len(ordered) - 1) // 100]}


def score(dataset, run):
    metadata, inventory, samples, rows = read_run(dataset, run)
    protocol = "synthetic-native-score-v3" if "dataset_schema" in metadata else "synthetic-barcode-v1"
    return score_rows(metadata, inventory, samples, rows, DECODERS, protocol)


def score_rows(metadata, inventory, samples, rows, decoders, protocol):
    totals, timing = {}, {}
    formats, clean_formats = {}, {}
    scenarios, tiers, counts, subsets = {}, {}, {}, {}
    diagnostics = {}
    all_formats = set(inventory["by_format"])
    supported = {decoder: set(metadata["decoders"][decoder].get("supported_formats", all_formats))
                 for decoder in decoders}
    require(all(values <= all_formats for values in supported.values()), "Unknown format in decoder coverage")
    shared_formats = set.intersection(*supported.values())
    supported_formats = set.union(*supported.values())
    cross_reader = Counter()
    shared_by_scenario = defaultdict(Counter)
    for decoder in decoders:
        totals[decoder] = Counter()
        timing[decoder] = []
        formats[decoder] = defaultdict(Counter)
        clean_formats[decoder] = defaultdict(Counter)
        scenarios[decoder] = defaultdict(Counter)
        tiers[decoder] = defaultdict(Counter)
        counts[decoder] = defaultdict(Counter)
        subsets[decoder] = defaultdict(Counter)
        diagnostics[decoder] = Counter()
    for key, sample in samples.items():
        truth = sample["ground_truth"]
        scenario = sample["scenario"]
        read_by_any = set()
        fully_read_by_any = False
        for decoder in decoders:
            row = rows[key][decoder]
            annotate(row, truth, supported[decoder])
            pairs, missed, extra = row["pairs"], row["missed"], row["extra"]
            wrong, unsupported = row["wrong"], row["unsupported"]
            error = row["error"]
            timing[decoder].append(row["decode_ns"] / 1_000_000)
            if error:
                diagnostics[decoder][error] += 1
            severity = f"{scenario}/{sample['severity']}"
            subset = sample.get("subset", "base")
            for counter in (totals[decoder], scenarios[decoder][scenario], tiers[decoder][severity],
                            counts[decoder][str(len(truth))], subsets[decoder][subset]):
                bucket_record(counter, len(truth), len(pairs), len(extra), error)
            duplicates = row["duplicates"]
            totals[decoder].update(wrong_reads=len(wrong), no_reads=len(missed) - len(wrong),
                                   unsupported_misses=len(unsupported),
                                   duplicate_predictions=duplicates, other_false_positives=len(extra) - duplicates)
            matched = {index for index, _ in pairs}
            read_by_any.update(matched)
            fully_read_by_any |= not error and len(matched) == len(truth)
            for index, item in enumerate(truth):
                f = item["format"]
                formats[decoder][f].update(truth=1, correct=int(index in matched))
                if scenario == "clean":
                    clean_formats[decoder][f].update(truth=1, correct=int(index in matched))
        for index, item in enumerate(truth):
            fmt = item["format"]
            if index in read_by_any:
                cross_reader["read_by_at_least_one"] += 1
            elif fmt in supported_formats:
                cross_reader["supported_unread_by_all"] += 1
            else:
                cross_reader["unsupported_unread_by_all"] += 1
            if fmt in shared_formats:
                shared_by_scenario[scenario].update(truth=1, read_by_at_least_one=int(index in read_by_any))
        if truth:
            cross_reader.update(positive_images=1, no_symbol_read_images=int(not read_by_any),
                                no_full_read_images=int(not fully_read_by_any))
    output = {"protocol": protocol, "inventory": inventory, "run": metadata, "shared_formats": sorted(shared_formats),
              "cross_reader": {"read_by_at_least_one": cross_reader["read_by_at_least_one"],
                               "supported_unread_by_all": cross_reader["supported_unread_by_all"],
                               "unsupported_unread_by_all": cross_reader["unsupported_unread_by_all"],
                               "positive_images": cross_reader["positive_images"],
                               "no_symbol_read_images": cross_reader["no_symbol_read_images"],
                               "no_full_read_images": cross_reader["no_full_read_images"],
                               "shared_formats_by_scenario": dict(sorted(shared_by_scenario.items()))},
              "decoders": {}}
    for decoder in decoders:
        stats = rates(totals[decoder])
        require(stats["truth"] == inventory["barcodes"] and stats["images"] == inventory["images"],
                f"Incorrect score denominators for {decoder}")
        require(sum(stats[field] for field in ("exact_images", "wrong_read_images", "no_read_images", "incomplete_images"))
                == stats["images"], f"Incorrect image outcome counts for {decoder}")
        for label, group in (("supported", supported[decoder]), ("shared", shared_formats)):
            eligible = sum(formats[decoder][fmt]["truth"] for fmt in group)
            correct = sum(formats[decoder][fmt]["correct"] for fmt in group)
            stats.update({f"{label}_truth": eligible, f"{label}_correct": correct, f"{label}_recall": ratio(correct, eligible)})
        stats["unsupported_truth"] = stats["truth"] - stats["supported_truth"]
        stats["supported_no_reads"] = stats["no_reads"] - stats["unsupported_misses"]
        stats.update(timing_ms=timing_ms(timing[decoder]), decoder_errors=dict(diagnostics[decoder]))
        for label, collection in (("by_format", formats), ("by_clean_format", clean_formats)):
            stats[label] = {name: dict(values, recall=ratio(values["correct"], values["truth"]),
                                       enabled=name in supported[decoder])
                            for name, values in sorted(collection[decoder].items())}
        for label, collection in (("by_scenario", scenarios), ("by_scenario_severity", tiers), ("by_symbol_count", counts),
                                  ("by_subset", subsets)):
            stats[label] = {name: rates(values) for name, values in sorted(collection[decoder].items())}
        output["decoders"][decoder] = stats
    return output, samples, rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary, _, _ = score(args.dataset, args.run)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
