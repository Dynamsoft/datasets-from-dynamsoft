"""Score completed browser runs using the shared synthetic matching rules."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score import bucket_record, match, rates, score_rows, timing_ms
from validate import read_jsonl, require


def score_full_dataset(dataset, runs):
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    manifest = dataset / "manifest.jsonl"
    manifest_hash = sha256(manifest.read_bytes()).hexdigest()
    require(manifest_hash == inventory["manifest_sha256"], "Manifest hash differs from inventory")
    samples = {sample["sample_id"]: sample for sample in read_jsonl(manifest)}
    require(len(samples) == inventory["images"], "Unexpected number of unique samples")
    rows = {key: {} for key in samples}
    coverage_file = Path(__file__).resolve().parents[1] / "native" / "symbologies.json"
    coverage = json.loads(coverage_file.read_text(encoding="utf-8"))
    columns = {"zxing-wasm": 0, "dynamsoft-dbr-js": 1, "scandit-web-datacapture": 2}
    metadata = {"manifest_sha256": manifest_hash, "decoders": {}, "browser_measurements": []}
    for run in runs:
        config = json.loads((run / "run.json").read_text(encoding="utf-8"))
        environment = json.loads((run / "environment.json").read_text(encoding="utf-8"))
        browser = environment["browser"]
        results = run / "results.jsonl"
        require(config["manifest_sha256"] == manifest_hash and config["repetitions"] == 1,
                "Browser report requires one pass over the verified manifest")
        readers = set(config["decoders"])
        require(readers and readers <= columns.keys() and readers == set(browser["decoders"])
                and not readers.intersection(metadata["decoders"]), "Unexpected or repeated browser decoder")
        if "dynamsoft-dbr-js" in readers:
            require(config["dbr_template"] == "ReadBarcodes_Default" and browser["dbr_formats"] == "BF_ALL",
                    "Browser Dynamsoft settings differ from the benchmark protocol")
        for decoder in sorted(readers):
            metadata["decoders"][decoder] = {
                "version": config["versions"][decoder],
                "supported_formats": sorted(fmt for fmt in inventory["by_format"] if coverage[fmt][columns[decoder]]),
            }
        for row in read_jsonl(results):
            key, decoder = row["sample_id"], row["decoder"]
            require(key in rows and decoder in readers and decoder not in rows[key] and row["repetition"] == 0,
                    f"Unexpected or duplicate result {key} {decoder}")
            require(isinstance(row["decode_ns"], int) and row["decode_ns"] >= 0
                    and row["decoder_version"] == config["versions"][decoder], f"Invalid browser record {key} {decoder}")
            require(not (row["error"] or "").startswith("input_pipeline_error:"), f"Image could not be loaded: {key}")
            rows[key][decoder] = row
        metadata["browser_measurements"].append({"decoders": sorted(readers), "environment": environment,
                                                 "config": config, "results_sha256": sha256(results.read_bytes()).hexdigest()})
    decoders = tuple(name for name in ("dynamsoft-dbr-js", "scandit-web-datacapture", "zxing-wasm") if name in metadata["decoders"])
    require(decoders and all(set(sample) == set(decoders) for sample in rows.values()), "Missing browser decoder records")
    return score_rows(metadata, inventory, samples, rows, decoders, "synthetic-browser-score-v2")


def summarize(manifest, run):
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
    results = run / "results.jsonl"
    require(sha256(manifest.read_bytes()).hexdigest() == metadata["manifest_sha256"], "Manifest hash differs")
    samples = {sample["sample_id"]: sample["ground_truth"] for sample in read_jsonl(manifest)}
    decoders = metadata["decoders"]
    repetitions = metadata["repetitions"]
    stats = {decoder: Counter() for decoder in decoders}
    times = {decoder: [] for decoder in decoders}
    versions = {decoder: set() for decoder in decoders}
    seen = set()
    for row in read_jsonl(results):
        key, decoder, repetition = row["sample_id"], row["decoder"], row["repetition"]
        require(key in samples and decoder in stats and 0 <= repetition < repetitions
                and (key, decoder, repetition) not in seen, f"Unexpected or duplicate result {key} {decoder} {repetition}")
        seen.add((key, decoder, repetition))
        truth = samples[key]
        pairs, _, extras = match(truth, row["predictions"])
        bucket_record(stats[decoder], len(truth), len(pairs), len(extras), row["error"])
        times[decoder].append(row["decode_ns"] / 1_000_000)
        versions[decoder].add(row["decoder_version"])
    require(len(seen) == len(samples) * len(decoders) * repetitions, "Missing browser results")
    return {
        "protocol": "synthetic-browser-score-v1",
        "run": metadata,
        "results_sha256": sha256(results.read_bytes()).hexdigest(),
        "decoders": {
            decoder: dict(rates(stats[decoder]), timing_ms=timing_ms(times[decoder]), versions=sorted(versions[decoder]))
            for decoder in decoders
        },
    }


if __name__ == "__main__":
    manifest_path, run_path = map(Path, sys.argv[1:])
    summary = summarize(manifest_path, run_path)
    (run_path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
