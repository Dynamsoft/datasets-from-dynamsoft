# Python binding benchmark

This runner measures the two pip-installable Python readers on the same
verified 8,000-image corpus used by the C++ / Linux and JavaScript / WebAssembly
runs. It writes one JSONL record per (image, decoder) and reuses the shared
matching rules in `../score.py`, so the three reports are directly comparable.

| Decoder | Package | Version |
| --- | --- | --- |
| `dynamsoft-dbr-python` | `dynamsoft-capture-vision-bundle` | 3.6.5000 (DBR 11.6.50.1028) |
| `zxing-python` | `zxing-cpp` | 3.1.1 |

## Protocol

* `dataset-by-format/manifest.jsonl` is the only source of images and ground
  truth. Its SHA-256 is checked against `inventory.json` before any decode.
* Each JPEG is loaded once with `cv2.imread` and the same ndarray is passed to
  both readers. `image_load_ns` is recorded separately and never enters the
  decode clock.
* Both readers get 24 warm-up calls before the measured pass. Decoder order is
  shuffled per image with a seeded PRNG (`20261119`).
* Dynamsoft uses `ReadBarcodes_Default` from `native/config/dynamsoft-preset.json`
  with `BF_ALL`, `expectedBarcodesCount = 0` and one thread per task. ZXing-C++
  uses the same explicit format list as the native runner, `LocalAverage`
  binarizer, `Plain` text mode and `Read` for EAN add-on symbols. The Python
  wheel does not expose `tryHarder` or `maxNumberOfSymbols`; it enables its own
  harder search by default in `read_barcodes`.
* The decode timer covers the reader call and the ndarray-to-SDK input
  conversion it requires. Result matching, JSON serialization and report
  generation are outside the clock.
* `GS1_128` is recovered from ZXing's `]C1` symbology identifier. Format names
  are normalized by `score.normalized_key`, which also folds UPC-A / EAN-13,
  CODE_39 extensions and postal check characters.

## Run

```sh
python -m pip install -r python/requirements.txt
python python/run_benchmark.py \
  --dataset dataset-by-format \
  --output results/python \
  --license-file licenses/dynamsoft-dbr.txt
```

`DYNAMSOFT_LICENSE_KEY` is accepted instead of `--license-file`. Use
`--resume` to continue an interrupted pass and `--limit N` for a smoke test.
The runner writes `results.jsonl`, `run.json` and `environment.json` into the
output directory; `run.json` stores the SHA-256 of the manifest and the raw
results so a reviewer can detect any post-run edit.

## Score and review

```sh
python python/score.py --run results/python --output review/python/summary.json
python report.py --python-run results/python
```

`review/python/index.html` lists every no-read and incomplete image by reader,
links to the original JPEG, and reports per-symbol recall, precision, shared
format coverage, multi-code results and false positives on the 200
background-only controls.
