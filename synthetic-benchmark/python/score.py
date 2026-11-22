"""Score a completed Python run with the shared synthetic matching rules."""
from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from score import score_rows  # noqa: E402
from validate import read_jsonl, require  # noqa: E402

DECODERS = ("dynamsoft-dbr-python", "zxing-python")
PROTOCOL = "synthetic-python-score-v1"


def score_python_run(dataset: Path, run: Path):
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    manifest_file = dataset / "manifest.jsonl"
    manifest_hash = sha256(manifest_file.read_bytes()).hexdigest()
    require(manifest_hash == inventory["manifest_sha256"], "Manifest hash differs from inventory")
    metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
    results_file = run / "results.jsonl"
    require(metadata["manifest_sha256"] == manifest_hash, "Run used a different manifest")
    require(sha256(results_file.read_bytes()).hexdigest() == metadata["results_sha256"],
            "Results hash differs from run metadata")
    require(set(metadata["decoders"]) == set(DECODERS), "Unexpected decoder set")
    require(metadata.get("repetitions") == 1, "Only one measured pass is supported")
    samples = {sample["sample_id"]: sample for sample in read_jsonl(manifest_file)}
    require(len(samples) == inventory["images"] == metadata["images"],
            "Unexpected number of unique samples")
    rows = {key: {} for key in samples}
    for row in read_jsonl(results_file):
        key, decoder = row["sample_id"], row["decoder"]
        require(key in rows and decoder in DECODERS and decoder not in rows[key],
                f"Unexpected or duplicate result {key} {decoder}")
        require(row["repetition"] == 0 and isinstance(row["decode_ns"], int)
                and row["decode_ns"] >= 0, f"Invalid timing {key} {decoder}")
        require(row["decoder_version"] == metadata["decoders"][decoder]["version"],
                f"Decoder version differs {key} {decoder}")
        require(not (row["error"] or "").startswith("input_pipeline_error:"),
                f"Image could not be loaded: {key}")
        rows[key][decoder] = row
    require(all(set(sample) == set(DECODERS) for sample in rows.values()),
            "Missing decoder/sample results")
    return score_rows(metadata, inventory, samples, rows, DECODERS, PROTOCOL)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset-by-format")
    parser.add_argument("--run", type=Path, default=ROOT / "results/python")
    parser.add_argument("--output", type=Path, default=ROOT / "review/python/summary.json")
    args = parser.parse_args()
    summary, _, _ = score_python_run(args.dataset, args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for name, values in summary["decoders"].items():
        print(f"{name}: exact {values['exact_images']:,}/{values['images']:,} "
              f"({values['exact_image_rate'] * 100:.2f}%), mean {values['timing_ms']['mean']:.2f} ms")


if __name__ == "__main__":
    main()
