"""Print the tables an article needs from an Android summary.json."""

import argparse
import json
from pathlib import Path

ORDER = [
    "AZTEC", "CODABAR", "CODE_128", "CODE_39", "CODE_93", "DATA_MATRIX", "DOTCODE",
    "EAN_13", "EAN_8", "GS1_128", "IATA_2_OF_5", "ITF", "KIX", "MAXICODE", "MICRO_QR",
    "MSI_CODE", "PDF_417", "PHARMACODE_ONE_TRACK", "POSTNET", "QR_CODE", "ROYAL_MAIL",
    "UPC_A", "UPC_E", "USPS_INTELLIGENT_MAIL",
]


def pct(value, digits=2):
    return "n/a" if value is None else f"{100 * value:.{digits}f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.summary.read_text(encoding="utf-8"))
    decoders = list(data["decoders"])
    labels = {"dynamsoft-dbr": "DBR", "google-mlkit": "ML Kit", "zxing-cpp-android": "ZXing"}

    print("== totals ==")
    for decoder in decoders:
        s = data["decoders"][decoder]
        t = s["timing_ms"]
        print(f"{labels.get(decoder, decoder):10s} exact {s['exact_images']:5d}/{s['images']} ({pct(s['exact_image_rate'])})"
              f"  wrong {s['wrong_read_images']:4d}  no-read {s['no_read_images']:5d}  incomplete {s['incomplete_images']:4d}"
              f"  recall {pct(s['recall'])}  precision {pct(s['precision'])}"
              f"  mean {t['mean']:.1f} / p50 {t['p50']:.1f} / p95 {t['p95']:.1f} ms")
        print(f"{'':10s} supported truth {s['supported_truth']} recall {pct(s['supported_recall'])} |"
              f" shared truth {s['shared_truth']} recall {pct(s['shared_recall'])} |"
              f" unsupported misses {s['unsupported_misses']}")

    print("\n== images by outcome ==")
    for decoder in decoders:
        s = data["decoders"][decoder]
        print(f"{labels.get(decoder, decoder):10s} exact {s['exact_images']} wrong {s['wrong_read_images']}"
              f" no-read {s['no_read_images']} incomplete {s['incomplete_images']}")

    print("\n== controls (negative images) ==")
    for decoder in decoders:
        s = data["decoders"][decoder]
        print(f"{labels.get(decoder, decoder):10s} negatives {s['negative_images']} with predictions {s['negative_images_with_predictions']}"
              f" rate {pct(s['negative_image_false_positive_rate'], 3)}")

    print("\n== by format (recall) ==")
    header = f"{'format':24s}" + "".join(f"{labels.get(d, d):>18s}" for d in decoders)
    print(header)
    for fmt in ORDER:
        cells = []
        for decoder in decoders:
            entry = data["decoders"][decoder]["by_format"].get(fmt)
            if not entry or "correct" not in entry:
                cells.append(f"{'-':>18s}")
            elif not entry["enabled"]:
                cells.append(f"{'unsupported':>18s}")
            else:
                cells.append(f"{entry['correct']:>6d}/{entry['truth']:<5d}{100 * entry['recall']:6.1f}%")
        print(f"{fmt:24s}" + "".join(cells))

    print("\n== by symbol count ==")
    keys = sorted({k for d in decoders for k in data["decoders"][d]["by_symbol_count"]}, key=int)
    print(f"{'symbols':8s}{'images':>8s}" + "".join(f"{labels.get(d, d):>22s}" for d in decoders))
    for key in keys:
        row = [f"{key:8s}"]
        count = data["decoders"][decoders[0]]["by_symbol_count"][key]["images"]
        row.append(f"{count:8d}")
        for decoder in decoders:
            entry = data["decoders"][decoder]["by_symbol_count"][key]
            row.append(f"{pct(entry['recall'], 1):>12s}{entry['exact_images']:>10d}")
        print("".join(row))

    print("\n== by scenario ==")
    scenarios = sorted({k for d in decoders for k in data["decoders"][d]["by_scenario"]})
    print(f"{'scenario':22s}{'images':>8s}" + "".join(f"{labels.get(d, d):>14s}" for d in decoders))
    for name in scenarios:
        row = [f"{name:22s}", f"{data['decoders'][decoders[0]]['by_scenario'][name]['images']:8d}"]
        row += [f"{pct(data['decoders'][d]['by_scenario'][name]['recall'], 1):>14s}" for d in decoders]
        print("".join(row))

    print("\n== cross reader ==")
    print(json.dumps(data["cross_reader"], indent=None)[:400])


if __name__ == "__main__":
    main()
