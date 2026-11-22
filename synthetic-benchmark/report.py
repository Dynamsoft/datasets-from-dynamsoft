"""Build a local, browser-readable review from the verified manifest and raw results."""

import argparse
import json
import os
from pathlib import Path

from browser.score import score_full_dataset
from capture_effects import CAPTURE_PROFILES
from rendering import ROOT
from generate_by_format import DATASET
from score import image_outcome, score


SCENARIOS = ("clean", "perspective", "rotation", "blur", "low_resolution", "low_contrast",
             "noise", "occlusion", "combined", *CAPTURE_PROFILES, "negative")

NAMES = {
    "dynamsoft-dbr": "Dynamsoft Barcode Reader",
    "scandit-linux": "Scandit Linux SDK",
    "zxing-cpp": "ZXing-C++",
    "dynamsoft-dbr-js": "Dynamsoft Barcode Reader for Web",
    "scandit-web-datacapture": "Scandit Data Capture SDK for Web",
    "zxing-wasm": "zxing-wasm",
}


def gallery(samples):
    entries = []
    for scenario in SCENARIOS:
        group = [sample for sample in samples.values() if sample["scenario"] == scenario
                 and (scenario != "combined" or sample.get("subset", "base") == "base")]
        if group:
            entries.append([scenario, group[len(group) // 2]["sample_id"]])
    capture = [sample for sample in samples.values()
               if sample["scenario"] == "combined" and sample.get("subset") == "capture"]
    if capture:
        entries.append(["capture_combined", capture[len(capture) // 2]["sample_id"]])
    multi = [sample for sample in samples.values() if sample.get("format_group") == "MIXED_SYMBOLOGIES"]
    if multi:
        entries.append(["mixed", max(multi, key=lambda sample: len(sample["ground_truth"]))["sample_id"]])
    return entries


def relative(path, parent):
    return Path(os.path.relpath(path.resolve(), parent.resolve())).as_posix()


def display_row(row):
    matched = len(row["pairs"])
    outcome = image_outcome(matched + len(row["missed"]), matched, len(row["extra"]), row["error"])
    return [round(row["decode_ns"] / 1_000_000, 4), row["error"], row["missed"], row["extra"],
            [[item["format"], item["text"]] for item in row["predictions"]], row["unsupported"], len(row["wrong"]), outcome]


def create_report(dataset, output, run=None, browser_runs=None):
    if browser_runs:
        summary, samples, rows = score_full_dataset(dataset, browser_runs)
        runtime = "JavaScript / WebAssembly"
        other_report = ROOT / "review/index.html"
    else:
        summary, samples, rows = score(dataset, run)
        runtime = "C++ / Linux"
        other_report = ROOT / "review/browser/index.html"
    decoders = tuple(summary["decoders"])
    output.mkdir(parents=True, exist_ok=True)
    compact_samples = []
    for key, sample in samples.items():
        results = [display_row(rows[key][reader]) for reader in decoders]
        compact_samples.append([key, sample["relative_path"], sample["scenario"], sample["severity"],
                                sample["background"], sample["width"], sample["height"], sample["effects"],
                                [[item["format"], item["text"], item["polygon"]] for item in sample["ground_truth"]], results])
    source_runs = browser_runs or [run]
    run_files = [{"results": relative(source / "results.jsonl", output),
                  "config": relative(source / "run.json", output),
                  "environment": relative(source / "environment.json", output) if browser_runs else None}
                 for source in source_runs]
    content = {"summary": summary, "decoders": decoders, "samples": compact_samples,
               "names": {name: NAMES[name] for name in decoders}, "runtime": runtime,
               "gallery": gallery(samples), "image_base": relative(dataset, output),
               "links": {"manifest": relative(dataset / "manifest.jsonl", output),
                         "runs": run_files, "other_report": relative(other_report, output),
                         "atlas": relative(ROOT / "backgrounds/atlas.png", output),
                         "method": relative(ROOT / "README.md", output)}}
    template = (ROOT / "report-template.html").read_text(encoding="utf-8")
    embedded = json.dumps(content, separators=(",", ":")).replace("<", "\\u003c")
    (output / "index.html").write_text(template.replace("__BENCHMARK_DATA__", embedded), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Review generated for {len(samples):,} images and {len(samples) * len(decoders):,} decoded records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", type=Path)
    source.add_argument("--browser-run", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / ("review/browser" if args.browser_run else "review")
    create_report(args.dataset, output, args.run, args.browser_run)
