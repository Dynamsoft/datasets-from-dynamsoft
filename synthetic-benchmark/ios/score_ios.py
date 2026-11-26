"""Score an iOS benchmark pass against the dataset manifest.

Reuses the dataset's own matching rules (normalized_key / match / image_outcome
inside score.py), so the iOS numbers are computed exactly like the native,
browser, Python and Android runs: one-to-one format and payload matching, a
wrong read counts against the image, controls must come back empty.

    python ios/score_ios.py --dataset dataset-by-format \\
        --results .runs/ios-2026-11/results.jsonl --output review/ios/summary.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from score import score_rows

DECODERS = ("dynamsoft-dbr", "google-mlkit", "apple-vision", "zxing-cpp-ios")

# Dynamsoft Barcode Reader 11.6 has no IATA 2 of 5 decoder, so those symbols sit
# outside its supported list - the same split the native and Android runners use.
DBR_UNSUPPORTED = {"IATA_2_OF_5"}

# ML Kit exposes 13 symbologies. GS1-128 labels are Code 128 symbols with an FNC1
# prefix, so ML Kit reports them as CODE_128 and the payload normalizer maps them
# back; that group counts as supported.
MLKIT_FORMATS = {
    "AZTEC", "CODABAR", "CODE_128", "CODE_39", "CODE_93", "DATA_MATRIX",
    "EAN_13", "EAN_8", "GS1_128", "ITF", "PDF_417", "QR_CODE", "UPC_A", "UPC_E",
}

# VNDetectBarcodesRequest covers these symbologies. UPC-A arrives as a
# zero-prefixed EAN-13 and GS1-128 as Code 128 with FNC1, both folded back by the
# normalizer, so they count as supported even without a separate Vision mode.
VISION_FORMATS = {
    "AZTEC", "CODABAR", "CODE_128", "CODE_39", "CODE_93", "DATA_MATRIX",
    "EAN_13", "EAN_8", "GS1_128", "ITF", "PDF_417", "QR_CODE", "UPC_A", "UPC_E",
}

# ZXing-C++ 3.1.1 decodes 16 of the 24 symbologies in the corpus. It has no
# DotCode, MSI, IATA 2 of 5, postal or Pharmacode reader, so those symbols are
# unsupported rather than missed.
ZXING_FORMATS = {
    "AZTEC", "CODABAR", "CODE_128", "CODE_39", "CODE_93", "DATA_MATRIX",
    "EAN_13", "EAN_8", "GS1_128", "ITF", "MAXICODE", "MICRO_QR", "PDF_417",
    "QR_CODE", "UPC_A", "UPC_E",
}

SOURCE = {
    "dynamsoft-dbr": "dynamsoft",
    "google-mlkit": "mlkit",
    "apple-vision": "vision",
    "zxing-cpp-ios": "zxingcpp",
}


def predictions(sdk_result):
    out = []
    for item in sdk_result.get("barcodes") or []:
        out.append({"format": str(item.get("format") or "UNKNOWN"), "text": item.get("text") or ""})
    return out


def load(dataset, results):
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    samples = {}
    for line in (dataset / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            sample = json.loads(line)
            samples[sample["sample_id"]] = sample
    rows = {}
    for line in results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        response = record["response"]
        sample_id = record["sample_id"]
        rows.setdefault(sample_id, {})
        if not isinstance(response, dict):
            continue
        if response.get("error") and "dynamsoft" not in response:
            # Whole-request failure: every requested reader counts as a no-read.
            for decoder in SOURCE:
                rows[sample_id][decoder] = {"predictions": [], "error": str(response["error"]), "decode_ns": 0}
            continue
        for decoder, key in SOURCE.items():
            sdk = response.get(key)
            if sdk is None:
                continue  # reader not requested for this pass
            error = sdk.get("error")
            rows[sample_id][decoder] = {
                "predictions": predictions(sdk),
                "error": str(error) if error else None,
                "decode_ns": int(round(float(sdk.get("timeMs") or 0) * 1_000_000)),
            }
    return inventory, samples, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("dataset-by-format"))
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="")
    parser.add_argument("--partial", action="store_true", help="score only the samples recorded so far")
    args = parser.parse_args()

    inventory, samples, rows = load(args.dataset, args.results)
    if args.partial:
        samples = {key: value for key, value in samples.items() if key in rows}
        inventory = dict(inventory)
        inventory["images"] = len(samples)
        inventory["barcodes"] = sum(len(sample["ground_truth"]) for sample in samples.values())
    all_formats = set(inventory["by_format"])
    missing = [] if args.partial else sorted(set(samples) - set(rows))
    if missing:
        raise SystemExit("%d samples without results, first: %s" % (len(missing), missing[:5]))
    extra = sorted(set(rows) - set(samples))
    if extra:
        raise SystemExit("results contain unknown samples: %s" % extra[:5])
    decoders = [d for d in DECODERS if all(d in by_decoder for by_decoder in rows.values())]
    if not decoders:
        raise SystemExit("no decoder appears in every record")
    for sample_id, by_decoder in rows.items():
        for decoder in decoders:
            if decoder not in by_decoder:
                raise SystemExit("missing %s for %s" % (decoder, sample_id))

    metadata = {
        "images": len(samples),
        "dataset_schema": inventory["schema"],
        "device": args.device,
        "decoders": {
            "dynamsoft-dbr": {"supported_formats": sorted(all_formats - DBR_UNSUPPORTED)},
            "google-mlkit": {"supported_formats": sorted(MLKIT_FORMATS & all_formats)},
            "apple-vision": {"supported_formats": sorted(VISION_FORMATS & all_formats)},
            "zxing-cpp-ios": {"supported_formats": sorted(ZXING_FORMATS & all_formats)},
        },
    }
    metadata["decoders"] = {name: value for name, value in metadata["decoders"].items() if name in decoders}
    summary, _, _ = score_rows(metadata, inventory, samples, rows, decoders, "synthetic-ios-v1")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("%-22s %8s %8s %8s %8s %8s" % ("decoder", "exact%", "wrong", "no-read", "recall", "mean ms"))
    for decoder in decoders:
        s = summary["decoders"][decoder]
        print("%-22s %7.2f%% %8d %8d %7.2f%% %8.1f" % (
            decoder, 100 * s["exact_image_rate"], s["wrong_read_images"], s["no_read_images"],
            100 * s["recall"], s["timing_ms"]["mean"]))
    print("\nshared formats:", len(summary["shared_formats"]), "of", len(all_formats))


if __name__ == "__main__":
    main()
