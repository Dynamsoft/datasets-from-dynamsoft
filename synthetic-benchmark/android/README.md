# Android on-device benchmark

The Android pass runs the same 8,000 images through the same scoring rules as the
native, browser and Python runners, on a real phone.

```text
android/
  mlkit-dbr-benchmark/   Android app: Dynamsoft Barcode Reader + Google ML Kit
  run_benchmark.py       uploads each JPEG to POST /api/benchmark, appends JSON
  score_android.py       scores the pass with score.py's own matching rules
  digest.py              prints the tables used in the write-up
```

## How a pass works

1. Build and install the app (`cd mlkit-dbr-benchmark && ./gradlew.bat installDebug`).
2. Open it, switch on **Web Server** on the home screen. The app serves on port 8080.
3. Forward the port over USB: `adb forward tcp:18081 tcp:8080`. The phone's own
   address is only needed for Wi-Fi uploads from another machine, and
   `adb reverse` does not work for this direction.
4. Run the pass, score it, print the digest:

```sh
python android/run_benchmark.py --dataset dataset-by-format \
  --output .runs/android-next/results.jsonl --decoders dbr,mlkit
python android/score_android.py --results .runs/android-next/results.jsonl \
  --output review/android/summary.json
python android/digest.py --summary review/android/summary.json
```

Use the Python interpreter that already has this repository's dependencies
(`score.py` imports `expand_corpus`, which imports OpenCV and NumPy).

## The endpoint

`POST /api/benchmark`, multipart form data:

| Field | Value |
| --- | --- |
| `file` | the image (or video) |
| `fileType` | `image` or `video` |
| `decoders` | optional, comma-separated subset of `dbr,mlkit,zxing` |

The response carries one object per reader with `timeMs`, `count` and a
`barcodes` array of `{format, text}`. The scorer normalises the format names
(`MAXICODE`, `RM4SCC`, `PDF_417`, …) through the repository's `CANONICAL` map,
so on-device and desktop results stay comparable.

## Configuration that matters

- **All formats.** The app keeps the built-in `ReadBarcodes_Default` preset and
  sets `barcodeFormatIds = BF_ALL` through `getSimplifiedSettings()` /
  `updateSettings()`. The preset's `BF_DEFAULT` omits postal codes, MaxiCode,
  DotCode, MSI, Pharmacode and Micro QR, which would silently zero 1,900+ symbols.
- **Coverage accounting.** Dynamsoft has no IATA 2 of 5 decoder, so those symbols
  are listed as unsupported rather than missed. ML Kit has no decoder for ten of
  the 24 symbologies; GS1-128 counts as supported because it is Code 128 with an
  FNC1 prefix and ML Kit reports it as `CODE_128`.
- **ZXing-C++ is off.** The zxing-cpp Android wrapper aborts the process with a JNI
  `Invalid BarcodeFormat` on a small number of images in both 3.0.2 and 3.1.1.
  `BenchmarkConfig.ENABLE_ZXING` defaults to `false`, which hides its UI and keeps
  `decoders` at `dbr,mlkit`.

## Result of the last pass

`review/android/summary.json` — OPPO PLG110, Android 17, 8,000 images:

| | Dynamsoft 11.6.4000 | ML Kit 17.3.0 |
| --- | ---: | ---: |
| Symbols matched | 9,220 / 11,372 (81.08%) | 5,603 / 11,372 (49.27%) |
| Exact images | 6,374 (79.68%) | 4,101 (51.26%) |
| Shared-format recall | 92.53% | 85.11% |
| Mean / median / p95 | 62.6 / 35 / 187 ms | 48.3 / 45 / 95 ms |
