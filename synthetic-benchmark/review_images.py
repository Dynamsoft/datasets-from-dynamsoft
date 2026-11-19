"""Build a gallery for browsing the grouped corpus."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path

from expand_corpus import SCHEMA as EXPANDED_SCHEMA
from rendering import ROOT
from generate_by_format import DATASET, SCHEMA
from validate import read_jsonl


def preview_order(samples):
    pending = list(samples)
    seen = [set() for _ in range(6)]
    first_page = []
    # Favor a range of scenes, effects and layouts in the first contact sheet.
    weights = (4, 3, 3, 2, 2, 1)
    while pending and len(first_page) < 24:
        best = max(range(len(pending)), key=lambda index: sum(
            weight for weight, values, value in zip(weights, seen, pending[index][2:8], strict=True)
            if value not in values))
        item = pending.pop(best)
        for values, value in zip(seen, item[2:8], strict=True):
            values.add(value)
        first_page.append(item)
    return first_page + pending


def build_gallery(dataset):
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    if inventory["schema"] not in {SCHEMA, EXPANDED_SCHEMA, "synthetic-barcode-v2", "synthetic-barcode-v4"}:
        raise ValueError("This gallery requires a grouped corpus")
    groups = defaultdict(list)
    for sample in read_jsonl(dataset / "manifest.jsonl"):
        truth = sample["ground_truth"]
        groups[sample["format_group"]].append([
            sample["sample_id"], sample["relative_path"], sample["background"], sample["scenario"],
            sample["composition"], sample["appearance"], len(truth), sample["severity"], sample["width"],
            sample["height"], sample["effects"], [[item["format"], item["text"]] for item in truth],
            sample["frame_transform"] if sample.get("subset") in {"capture", "mixed"} else {},
        ])
    gallery = {"images": inventory["images"], "groups": {key: preview_order(rows) for key, rows in sorted(groups.items())},
               "format_count": len(inventory["by_format"]), "background_count": len(inventory["by_background"]),
               "method": Path(os.path.relpath(ROOT / "README.md", dataset)).as_posix()}
    template = (ROOT / "image-review-template.html").read_text(encoding="utf-8")
    payload = json.dumps(gallery, separators=(",", ":")).replace("<", "\\u003c")
    output = dataset / "review.html"
    output.write_text(template.replace("__GALLERY_DATA__", payload), encoding="utf-8")
    print(f"Wrote the image review gallery for {inventory['images']:,} images to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()
    build_gallery(args.dataset.resolve())
