"""Run the synthetic barcode benchmark through the Python SDK bindings.

The protocol mirrors ``native/main.cpp`` and ``browser/web/benchmark.js``:

* the verified manifest is the only source of images and ground truth;
* each JPEG is loaded once with OpenCV and the same ndarray is handed to both
  readers, so image loading never enters the decode clock;
* each reader gets 24 warm-up calls before the measured pass;
* decoder order is shuffled per image with a seeded PRNG;
* one JSONL record per (image, decoder) records the decode call, its timing,
  every returned prediction and any explicit decoder error.

Only the decode call is timed. The runner does not score the results: use
``python/score.py`` (or ``report.py --python-run``) to produce the summary.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sys
import time
from hashlib import sha256
from importlib.metadata import version as package_version
from pathlib import Path

import cv2
import zxingcpp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dynamsoft_capture_vision_bundle import (  # noqa: E402
    BarcodeReaderModule,
    CaptureVisionRouter,
    EnumBarcodeFormat,
    EnumErrorCode,
    EnumPresetTemplate,
    LicenseManager,
)

DBR_NAME = "dynamsoft-dbr-python"
ZXING_NAME = "zxing-python"
DECODERS = (DBR_NAME, ZXING_NAME)
TEMPLATE_NAME = "ReadBarcodes_Default"
ZXING_FORMAT_NAMES = ("Aztec", "Codabar", "Code128", "Code39", "Code93", "DataMatrix",
                      "EAN13", "EAN8", "ITF", "MaxiCode", "MicroQRCode", "PDF417",
                      "QRCode", "UPCA", "UPCE")
PRESET_FILE = ROOT / "native/config/dynamsoft-preset.json"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def supported_formats() -> dict[str, list[str]]:
    """Reuse the native symbology coverage table for the two Python bindings."""
    coverage = json.loads((ROOT / "native/symbologies.json").read_text(encoding="utf-8"))
    return {
        ZXING_NAME: sorted(fmt for fmt, values in coverage.items() if values[0]),
        DBR_NAME: sorted(fmt for fmt, values in coverage.items() if values[1]),
    }


class DynamsoftReader:
    def __init__(self, license_key: str) -> None:
        error_code, error_message = LicenseManager.init_license(license_key)
        ok = {int(EnumErrorCode.EC_OK)}
        if hasattr(EnumErrorCode, "EC_LICENSE_CACHE_USED"):
            ok.add(int(EnumErrorCode.EC_LICENSE_CACHE_USED))
        require(int(error_code) in ok, f"Dynamsoft license failed: {error_code}, {error_message}")
        self.router = CaptureVisionRouter()
        code, message = self.router.init_settings_from_file(str(PRESET_FILE))
        require(int(code) == 0, f"Could not load the DBR template: {code}, {message}")
        code, message, settings = self.router.get_simplified_settings(TEMPLATE_NAME)
        require(int(code) == 0 and settings is not None,
                f"Could not read simplified settings: {code}, {message}")
        settings.barcode_settings.barcode_format_ids = EnumBarcodeFormat.BF_ALL
        settings.barcode_settings.expected_barcodes_count = 0
        settings.barcode_settings.max_threads_in_one_task = 1
        code, message = self.router.update_settings(TEMPLATE_NAME, settings)
        require(int(code) == 0, f"Could not apply BF_ALL: {code}, {message}")
        self.template = TEMPLATE_NAME
        self.version = str(BarcodeReaderModule.get_version())

    @property
    def settings(self) -> dict:
        return {"preset": TEMPLATE_NAME, "barcode_format_ids": "BF_ALL",
                "expected_barcodes_count": 0, "max_threads_in_one_task": 1,
                "config_sha256": sha256(PRESET_FILE.read_bytes()).hexdigest()}

    def decode(self, image):
        begin = time.perf_counter_ns()
        try:
            captured = self.router.capture(image, self.template)
            decode_ns = time.perf_counter_ns() - begin
            if captured is None:
                return [], decode_ns, "decoder_error: Dynamsoft returned a null captured result"
            error_code = int(captured.get_error_code())
            if error_code != int(EnumErrorCode.EC_OK):
                return [], decode_ns, f"decoder_error: {error_code}, {captured.get_error_string()}"
            predictions = []
            for item in captured.get_items():
                raw = item.get_bytes() if hasattr(item, "get_bytes") else b""
                if isinstance(raw, str):
                    raw_hex = raw.encode("utf-8").hex()
                else:
                    raw_hex = bytes(raw or b"").hex()
                predictions.append({
                    "format": str(item.get_format_string() if hasattr(item, "get_format_string") else ""),
                    "text": str(item.get_text() if hasattr(item, "get_text") else ""),
                    "raw_bytes_hex": raw_hex,
                })
            return predictions, decode_ns, None
        except Exception as exc:  # the SDK raises on timeouts and bad input
            return [], time.perf_counter_ns() - begin, f"decoder_error: {exc}"


class ZxingReader:
    def __init__(self) -> None:
        self.formats = zxingcpp.BarcodeFormats(
            [getattr(zxingcpp.BarcodeFormat, name) for name in ZXING_FORMAT_NAMES])
        self.version = package_version("zxing-cpp")

    @property
    def settings(self) -> dict:
        return {"formats": ",".join(ZXING_FORMAT_NAMES), "try_rotate": True,
                "try_invert": True, "try_downscale": True,
                "binarizer": "LocalAverage", "text_mode": "Plain",
                "ean_add_on_symbol": "Read", "max_symbols": "not exposed by the Python wheel"}

    def decode(self, image):
        begin = time.perf_counter_ns()
        try:
            results = zxingcpp.read_barcodes(
                image,
                formats=self.formats,
                try_rotate=True,
                try_downscale=True,
                try_invert=True,
                text_mode=zxingcpp.TextMode.Plain,
                binarizer=zxingcpp.Binarizer.LocalAverage,
                is_pure=False,
                ean_add_on_symbol=zxingcpp.EanAddOnSymbol.Read,
                return_errors=False,
            )
            decode_ns = time.perf_counter_ns() - begin
            predictions = []
            for item in results:
                fmt = str(getattr(item.format, "name", item.format))
                # ZXing-C++ reports GS1-128 as Code 128 with a ]C1 identifier.
                if fmt == "Code128" and str(getattr(item, "symbology_identifier", "")) == "]C1":
                    fmt = "GS1_128"
                predictions.append({
                    "format": fmt,
                    "text": str(getattr(item, "text", "")),
                    "raw_bytes_hex": bytes(getattr(item, "bytes", b"") or b"").hex(),
                })
            return predictions, decode_ns, None
        except Exception as exc:
            return [], time.perf_counter_ns() - begin, f"decoder_error: {exc}"


def environment() -> dict:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine().lower(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "logical_processors": os.cpu_count(),
        "python": platform.python_version(),
        "zxing_cpp": package_version("zxing-cpp"),
        "dynamsoft_capture_vision_bundle": package_version("dynamsoft-capture-vision-bundle"),
        "opencv": package_version("opencv-python"),
        "numpy": package_version("numpy"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset-by-format")
    parser.add_argument("--output", type=Path, default=ROOT / "results/python")
    parser.add_argument("--license-file", type=Path, default=ROOT / "licenses/dynamsoft-dbr.txt")
    parser.add_argument("--license-key", default=os.environ.get("DYNAMSOFT_LICENSE_KEY", ""))
    parser.add_argument("--warmup", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--limit", type=int, default=0, help="Smoke-test prefix size; 0 runs the whole corpus")
    parser.add_argument("--resume", action="store_true", help="Skip (sample, decoder) pairs already in results.jsonl")
    args = parser.parse_args()

    dataset = args.dataset
    inventory = json.loads((dataset / "inventory.json").read_text(encoding="utf-8"))
    manifest_file = dataset / "manifest.jsonl"
    manifest_hash = sha256(manifest_file.read_bytes()).hexdigest()
    require(manifest_hash == inventory["manifest_sha256"], "Manifest hash differs from inventory")
    samples = list(read_jsonl(manifest_file))
    require(len(samples) == inventory["images"], "Unexpected number of manifest samples")
    if args.limit:
        samples = samples[:args.limit]
    require(args.limit or len(samples) == 8000, "Expected the complete 8,000-image corpus")

    license_key = args.license_key or args.license_file.read_text(encoding="utf-8").strip()
    require(bool(license_key), "A Dynamsoft license is required")
    readers = {DBR_NAME: DynamsoftReader(license_key), ZXING_NAME: ZxingReader()}

    args.output.mkdir(parents=True, exist_ok=True)
    results_file = args.output / "results.jsonl"
    completed = set()
    if args.resume and results_file.exists():
        completed = {(row["sample_id"], row["decoder"]) for row in read_jsonl(results_file)}
        print(f"Resuming: {len(completed):,} existing records", flush=True)

    # Warm up both readers on the first images, outside the measured pass.
    warmup_successes = {name: 0 for name in DECODERS}
    warmup_images = min(args.warmup, len(samples))
    for sample in samples[:warmup_images]:
        image = cv2.imread(str(dataset / sample["relative_path"]), cv2.IMREAD_COLOR)
        if image is None:
            continue
        for name in DECODERS:
            _, _, error = readers[name].decode(image)
            warmup_successes[name] += int(error is None)
    for name in DECODERS:
        require(warmup_successes[name] > 0, f"{name} failed every warm-up call")

    rng = random.Random(args.seed)
    partial = args.output / "results.jsonl.partial"
    if args.resume and results_file.exists():
        partial.write_bytes(results_file.read_bytes())
    with partial.open("w", encoding="utf-8", newline="\n") as sink:
        for index, sample in enumerate(samples, start=1):
            key = sample["sample_id"]
            begin = time.perf_counter_ns()
            image = cv2.imread(str(dataset / sample["relative_path"]), cv2.IMREAD_COLOR)
            load_ns = time.perf_counter_ns() - begin
            order = list(DECODERS)
            rng.shuffle(order)
            for name in order:
                if (key, name) in completed:
                    continue
                if image is None:
                    predictions, decode_ns, error = [], 0, "input_pipeline_error: image could not be loaded"
                else:
                    predictions, decode_ns, error = readers[name].decode(image)
                row = {"sample_id": key, "decoder": name,
                       "decoder_version": readers[name].version, "repetition": 0,
                       "image_load_ns": load_ns, "decode_ns": decode_ns,
                       "error": error, "predictions": predictions}
                sink.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
            if index % 250 == 0 or index == len(samples):
                sink.flush()
                print(f"Decoded {index:,} / {len(samples):,} images", flush=True)
    partial.replace(results_file)

    versions = {name: readers[name].version for name in DECODERS}
    coverage = supported_formats()
    env = environment()
    run_metadata = {
        "schema": "synthetic-python-run-v1",
        "dataset_schema": inventory["schema"],
        "selection": "all",
        "source_images": len(samples),
        "manifest_sha256": manifest_hash,
        "results_sha256": sha256(results_file.read_bytes()).hexdigest(),
        "images": len(samples),
        "warmup_calls_per_sdk": warmup_images,
        "order_seed": args.seed,
        "decoder_processes": 1,
        "repetitions": 1,
        "environment": env,
        "decoders": {
            DBR_NAME: {"version": versions[DBR_NAME], "runtime_configuration": "",
                       "settings": readers[DBR_NAME].settings, "supported_formats": coverage[DBR_NAME]},
            ZXING_NAME: {"version": versions[ZXING_NAME], "runtime_configuration": "",
                         "settings": readers[ZXING_NAME].settings, "supported_formats": coverage[ZXING_NAME]},
        },
    }
    (args.output / "run.json").write_text(json.dumps(run_metadata, indent=2) + "\n", encoding="utf-8")
    (args.output / "environment.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    print(f"Complete: {len(samples):,} images across {len(DECODERS)} readers", flush=True)


if __name__ == "__main__":
    main()
