# Synthetic Barcode Benchmark

A still-image benchmark for barcode readers. The dataset contains **8,000 JPEGs**,
**11,372 annotated symbols**, **24 symbologies**, and **36 synthetic backgrounds**.
The native, browser, Python, Android and iOS runners use the same manifest and scoring rules.

- [Browse images by symbology](dataset-by-format/review.html)
- [Open the C++ / Linux report](review/index.html) and [summary JSON](review/summary.json)
- [Open the JavaScript / WebAssembly report](review/browser/index.html) and [summary JSON](review/browser/summary.json)
- [Open the Python report](review/python/index.html) and [summary JSON](review/python/summary.json)
- [Open the Android summary JSON](review/android/summary.json) — Dynamsoft Barcode Reader vs Google ML Kit on an OPPO PLG110
- [Open the iOS summary JSON](review/ios/summary.json) — four readers on an iPhone 11
- [Explore the reusable background scenes](backgrounds/README.md)

## JavaScript / WebAssembly results

Measured in headless Chrome 156 on Windows. Dynamsoft and zxing-wasm shared
one run. Scandit ran in a separate browser process. The runs overlapped for
part of the measurement window.

| Decoder | Correct images | Image accuracy | Wrong-read images | No read | Incomplete | Mean | Median | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dynamsoft Barcode Reader for Web 11.6.5000 | 6,496 / 8,000 | 81.20% | 67 | 1,050 | 387 | 118.28 ms | 43.95 ms | 330.70 ms |
| Scandit Data Capture SDK for Web 8.7.1 | 6,156 / 8,000 | 76.95% | 5 | 1,480 | 359 | 64.91 ms | 57.70 ms | 124.90 ms |
| zxing-wasm 3.1.2 | 3,851 / 8,000 | 48.14% | 54 | 3,832 | 263 | 25.63 ms | 19.90 ms | 72.20 ms |

Dynamsoft Barcode Reader for Web reported 3 decode timeouts. The table includes them in No read.

## C++ / Linux results

Measured in one pass over the same 8,000 images on Ubuntu 24.04 under WSL2.
Dynamsoft uses `ReadBarcodes_Default` with `BF_ALL`.

| Decoder | Correct images | Image accuracy | Wrong-read images | No read | Incomplete | Mean | Median | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dynamsoft Barcode Reader 11.6.50.29329 | 6,714 / 8,000 | 83.93% | 107 | 820 | 359 | 39.11 ms | 22.99 ms | 114.04 ms |
| Scandit Linux SDK 8.7.1 | 6,025 / 8,000 | 75.31% | 459 | 1,305 | 211 | 57.28 ms | 57.95 ms | 94.47 ms |
| ZXing-C++ 3.1.1 | 3,852 / 8,000 | 48.15% | 56 | 3,829 | 263 | 8.60 ms | 6.11 ms | 27.19 ms |

### Scandit across runtimes

Scandit Linux matched **9,267 / 11,372 annotated symbols (81.49%)**.
Scandit Web matched **8,743 / 11,372 (76.88%)**
and had more exact images (6,156 versus 6,025).
The Linux SDK returned 444 duplicate predictions. On 357 images,
it matched every annotation and the only extra predictions were repeats. The strict
image score marks these as wrong reads. The Web SDK read 301 of those
images exactly. Linux returns the newly recognized codes in high-effort multi-scan
mode with its temporal duplicate filter disabled. Web returns newly tracked codes
from BarcodeBatch.
[Scandit Linux settings](https://docs.scandit.com/stable/c_api/struct_sc_barcode_scanner_settings.html) ·
[Scandit Web BarcodeBatch session](https://docs.scandit.com/8.6/data-capture-sdk/web/barcode-capture/api/barcode-batch-session.html)

## Python results

Measured in one process on Windows 11 with Python 3.14.4, `zxing-cpp` 3.1.1 and
`dynamsoft-capture-vision-bundle` 3.6.5000 (DBR 11.6.50.1028). Both readers
receive the same OpenCV ndarray and use `BF_ALL` / the native format list.

| Decoder | Correct images | Image accuracy | Wrong-read images | No read | Incomplete | Mean | Median | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dynamsoft Barcode Reader (Python) | 6,701 / 8,000 | 83.76% | 103 | 827 | 369 | 51.88 ms | 26.06 ms | 152.30 ms |
| ZXing-C++ (Python) | 3,852 / 8,000 | 48.15% | 56 | 3,828 | 264 | 14.12 ms | 10.53 ms | 43.57 ms |

See [python/README.md](python/README.md) for the runner protocol. The Python
wheel does not expose `tryHarder` or `maxNumberOfSymbols`, so its ZXing settings
differ slightly from the native C++ runner even though the version is the same.

## Android results

Measured on one device: an OPPO PLG110 running Android 17, 8,000 images uploaded
one at a time to the app's HTTP endpoint over USB. Dynamsoft runs the built-in
`ReadBarcodes_Default` preset with `BarcodeFormatIds` widened to `BF_ALL`; ML Kit
uses `FORMAT_ALL_FORMATS`. The full pass took 23 minutes with no failed requests.

| Decoder | Correct images | Image accuracy | Wrong-read images | No read | Incomplete | Mean | Median | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dynamsoft Barcode Reader 11.6.4000 (BF_ALL) | 6,374 / 8,000 | 79.68% | 71 | 1,173 | 382 | 62.58 ms | 35.00 ms | 187.00 ms |
| Google ML Kit barcode-scanning 17.3.0 | 4,101 / 8,000 | 51.26% | 53 | 3,527 | 319 | 48.29 ms | 45.00 ms | 95.00 ms |

Symbol recall is **81.08% (9,220 / 11,372)** for Dynamsoft against **49.27%
(5,603 / 11,372)** for ML Kit, at 99.18% and 99.06% precision. Neither reader
returned a prediction on any of the 200 control images.

Most of the difference is format coverage. ML Kit implements 13 symbologies, and
GS1-128 decodes through its Code 128 reader, so 14 of the 24 are reachable: the
other 4,789 symbols (ten symbologies) have no decoder at all. On the 14 shared
formats the split is **92.53% against 85.11%** over 6,583 symbols, and on the
4,688 images whose symbols are all inside that set, 91.2% against 87.5% of images
decode exactly. Dynamsoft has no IATA 2 of 5 decoder either, so those 474 symbols
are outside its supported list and are excluded from its supported recall the same
way the native run excludes them.

## iOS results

Measured on one device: an iPhone 11 (iPhone12,1) running iOS 26.6.1, 8,000 images
uploaded one at a time to the app's HTTP endpoint over the USB link. Dynamsoft runs
the built-in `ReadBarcodes_Default` preset with `barcodeFormatIds` widened to
`BF_ALL`; ML Kit uses `FORMAT_ALL_FORMATS`; ZXing-C++ uses the same reader options
as the C++ runner, including its 15-format list. The full pass took 25 minutes.

| Decoder | Correct images | Image accuracy | Wrong-read images | No read | Incomplete | Mean | Median | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dynamsoft Barcode Reader 11.6.5000 (BF_ALL) | 6,382 / 8,000 | 79.77% | 78 | 1,166 | 374 | 54.15 ms | 32.05 ms | 131.60 ms |
| Google ML Kit 8.0.0 | 4,103 / 8,000 | 51.29% | 60 | 3,517 | 320 | 32.46 ms | 29.95 ms | 64.00 ms |
| Apple Vision (VNDetectBarcodesRequest) | 3,998 / 8,000 | 49.98% | 31 | 3,728 | 243 | 39.88 ms | 30.00 ms | 98.00 ms |
| ZXing-C++ 3.1.1 | 3,812 / 8,000 | 47.65% | 55 | 3,872 | 261 | 38.56 ms | 31.10 ms | 111.20 ms |

Symbol recall is **81.27% (9,242 / 11,372)** for Dynamsoft against 49.16% for ML Kit,
50.03% for Apple Vision and 48.80% for ZXing-C++, at 99.12%, 98.90%, 99.46% and 98.95%
precision. None of the four readers returned a prediction on any of the 200
background-only controls. On the 14 formats all four implement, the split is **92.59%**
for Dynamsoft, 86.42% for Apple Vision, 84.92% for ML Kit and 77.46% for ZXing-C++.

Two settings move these numbers more than the choice of SDK, and both are easy to miss
on iOS. The Dynamsoft preset ships `BF_DEFAULT`, which leaves MaxiCode, DotCode, postal
codes, MSI and Pharmacode undecoded until `barcodeFormatIds` is widened to `BF_ALL`. And
Xcode's Debug configuration compiles zxing-cpp's C++ core at `-O0`: one 4032 x 3024 frame
took 9,657 ms to decode in Debug and 690 ms in Release, with identical results. Run a
Release build, or the ZXing-C++ row measures the build configuration rather than the
reader. Every iOS ZXing-C++ row here lands within a point of the native Linux pass,
which is the check that the integration is configured like the C++ runner.

## Scoring

Every row uses 8,000 images as the denominator, including 200 background-only
controls. A correct image has a one-to-one match for every expected format and
payload, with no extra predictions. An empty response is correct on a control.
An SDK error counts as **No read**. For successful calls, **Wrong-read images**
have at least one unmatched prediction, **No read** images have expected
symbols and zero matches, and **Incomplete** images have some matches and no
unmatched predictions.

Each HTML report lists every No read and Incomplete filename by reader, links
to the original JPEG, and shows the annotations and returned values. It also
reports per-symbol recall, precision, supported and shared format coverage,
multi-code results, and false positives on controls. Each unmatched prediction
counts against precision. The format and payload matcher normalizes equivalent
representations such as UPC-A and its zero-prefixed EAN-13 representation.

## Dataset

The dataset has one directory per symbology, plus 153 mixed-symbology images
and 200 background-only controls. Positive images contain between 1 and 16
annotated symbols.

| Family | Symbologies |
| --- | --- |
| Linear | Codabar, Code 39, Code 93, Code 128, EAN-8, EAN-13, GS1-128, IATA 2 of 5, Interleaved 2 of 5, MSI, single-track Pharmacode, UPC-A, UPC-E |
| Postal | KIX, POSTNET, Royal Mail (RM4SCC), USPS Intelligent Mail |
| 2D | Aztec, Data Matrix, DotCode, MaxiCode (mode 4), Micro QR, PDF417, QR Code |

Seeded layouts compose BWIPP-generated labels over reusable scenes of packaging,
paper, fabric, and work surfaces. Images vary in payload, label placement, view,
framing, and background crop. Isolated and combined capture effects cover
perspective, rotation, defocus and motion blur, low resolution and contrast,
noise, JPEG compression, partial occlusion, uneven illumination, and glare.
The manifest records the JPEG hash, seed, applied effects, and each symbol's
format, payload, and final-image quadrilateral. [BWIPP via bwip-js](https://github.com/metafloor/bwip-js/)

The generator bounds projected shape distortion, preserves QR and Micro QR
finder patterns, and limits synthetic occlusion to 22% of a symbol. Blur and
downsampling account for barcode module size. The image quality screen uses the
encoder mask to measure expected dark-to-light transitions in the final JPEG.
Perceptual hashes and color thumbnails screen for near-duplicates, and every
accepted frame is recorded in the manifest before any reader runs.

### Generate and verify a new dataset

The following commands create a fresh 8,000-image dataset. Use the report's
manifest and corresponding JPEGs to reproduce the exact benchmark inputs.

```sh
python -m pip install -r requirements.txt
npm ci
python generate_by_format.py --output .runs/grouped-base
python expand_corpus.py --base .runs/grouped-base --output .runs/generated-8000
python validate.py --dataset .runs/generated-8000 --expected-images 8000
python review_images.py --dataset .runs/generated-8000
```

## Run the browser benchmark

Install Python dependencies with `python -m pip install -r requirements.txt`
from the benchmark root and run `npm ci` from `browser/`. The runner starts a
local collector and headless Chrome. Use `--chrome` to supply the Chrome
executable. Scandit uses BarcodeBatch.

Store your Dynamsoft license at `licenses/dynamsoft-dbr.txt` and your Scandit
Web license at `licenses/scandit-web.txt`, relative to the benchmark root.
The browser runner also accepts `DYNAMSOFT_LICENSE_KEY` and
`SCANDIT_LICENSE_KEY` as environment overrides. Git ignores `licenses/`.

```sh
npm run benchmark -- --chrome /path/to/chrome --output ../.runs/browser-next
```

The `--decoders` option selects a comma-separated set of `dynamsoft-dbr-js`,
`scandit-web-datacapture`, and `zxing-wasm`. The browser loads each JPEG into
one shared canvas and seeds the reader order per image. Decode timing includes
the SDK call and the input conversion it requires. Image loading is recorded
separately. Dynamsoft uses `ReadBarcodes_Default` with `BF_ALL`.
[Dynamsoft Web barcode format settings](https://www.dynamsoft.com/barcode-reader/docs/web/programming/javascript/api-reference/enum-barcode-format.html)

From the project root, generate the browser report. You can pass multiple run
directories when each reader has a complete pass over the same manifest.

```sh
python report.py --browser-run .runs/browser-next
```

## Run the C++ / Linux benchmark

Provision Ubuntu 24.04 amd64, the Dynamsoft Capture Vision Linux x64 SDK, and
ZXing-C++ 3.1.1. Place the Scandit Linux SDK 8.7.1 package at
`native/.vendor/scandit-amd64.deb`. Set `DCV_ROOT` and `ZXING_SOURCE_DIR`
to the absolute SDK and source paths, and provide a Dynamsoft license and a
Scandit Linux license with tracking in the environment. [ZXing-C++ source revision](https://github.com/zxing-cpp/zxing-cpp/tree/287c85df6f961c8efbfb5ffd736cd9457b8b890e)

Save the Linux key as `licenses/scandit-linux.txt` in the same local directory.

```sh
mkdir -p .runs
export DYNAMSOFT_LICENSE_KEY="$(cat licenses/dynamsoft-dbr.txt)"
export SCANDIT_LICENSE_KEY="$(cat licenses/scandit-linux.txt)"
docker build --platform linux/amd64 -t synthetic-benchmark-native native
docker run --rm --platform linux/amd64 \
  --mount "type=bind,source=$PWD,target=/workspace/project,readonly" \
  --mount "type=bind,source=$PWD/.runs,target=/runs" \
  --mount "type=bind,source=$DCV_ROOT,target=/deps/dcv,readonly" \
  --mount "type=bind,source=$ZXING_SOURCE_DIR,target=/deps/zxing,readonly" \
  -e DCV_ROOT=/deps/dcv -e ZXING_SOURCE_DIR=/deps/zxing \
  -e DYNAMSOFT_LICENSE_KEY -e SCANDIT_LICENSE_KEY \
  --workdir /workspace/project synthetic-benchmark-native sh -ec '
    CMAKE_BUILD_PARALLEL_LEVEL=4 sh native/build.sh /tmp/build
    export LD_LIBRARY_PATH=/tmp/build/dynamsoft-libs
    /tmp/build/synthetic_benchmark dataset-by-format /runs/native-next \
      native/symbologies.json native/config/dynamsoft-preset.json
  '
python report.py --run .runs/native-next
```

## Run the Python benchmark

Install the requirements from `python/requirements.txt`, store the Dynamsoft
license at `licenses/dynamsoft-dbr.txt` (or set `DYNAMSOFT_LICENSE_KEY`), then
run one pass over the verified dataset and build the report.

```sh
python -m pip install -r python/requirements.txt
python python/run_benchmark.py --dataset dataset-by-format --output results/python
python python/score.py --run results/python --output review/python/summary.json
python report.py --python-run results/python
```

`--resume` continues an interrupted pass; `--limit N` runs a smoke test. The
runner checks the manifest SHA-256 before decoding and records the raw results
SHA-256 in `run.json`.

The native runner loads each image once as RGB and passes the same frame to
every SDK. It runs 24 warm-up calls per SDK, shuffles reader order per image with
a fixed seed, and measures the decode calls separately from image loading.

## Run the Android benchmark

The app lives at [android/mlkit-dbr-benchmark](android/mlkit-dbr-benchmark) and the
runner scripts next to it, so the dataset, the app and the scorer are one clone.
Build it with the Android SDK, install it on a device, open the app and switch on
**Web Server**. The screen shows the phone's address; over USB you do not need it.

```sh
cd android/mlkit-dbr-benchmark && ./gradlew.bat installDebug   # or open it in Android Studio
adb forward tcp:18081 tcp:8080                                  # phone:8080 -> localhost:18081
python android/run_benchmark.py --dataset dataset-by-format   --output .runs/android-next/results.jsonl --decoders dbr,mlkit
python android/score_android.py --results .runs/android-next/results.jsonl   --output review/android/summary.json
python android/digest.py --summary review/android/summary.json
```

`run_benchmark.py` posts each JPEG to `POST /api/benchmark` as multipart form data
(`file`, `fileType=image`, optional `decoders`), appends the raw JSON response to
the output file and resumes from it after an interruption. Pass `--adb <path>` and
it restarts the app automatically if the server dies mid-pass.

`score_android.py` imports `score_rows` from the repository's own `score.py`, so
image outcomes, per-symbol matching and the format normalisation are identical to
the native and browser runs. `digest.py` prints the article-ready tables. Run both
with the Python that has this repository's dependencies installed.

The `--decoders` list also accepts `zxing`, which pulls in ZXing-C++ 3.1.1. Leave it
off: the zxing-cpp Android wrapper raises a JNI `Invalid BarcodeFormat` abort on a
small number of images, which kills the process no matter what the Java side does.
`BenchmarkConfig.ENABLE_ZXING` is `false` for that reason.

## Run the iOS benchmark

The app and the runner scripts live under [ios/](ios), so the dataset, the app and
the scorer are one clone. Install ML Kit through CocoaPods, open
`BarcodeBenchmark.xcworkspace`, and build the shared scheme — it builds Release on
purpose (see [ios/README.md](ios/README.md#build-configuration)). Launch the app; the
HTTP endpoint comes up on port 8080 by itself and the screen shows the address.

```sh
cd ios && pod install && open BarcodeBenchmark.xcworkspace
python ios/run_benchmark.py --dataset dataset-by-format \
  --host 169.254.35.41 --output .runs/ios-next/results.jsonl
python ios/score_ios.py --results .runs/ios-next/results.jsonl \
  --output review/ios/summary.json --device "iPhone 11, iOS 26.6.1"
```

`--host` accepts the Wi-Fi address the app prints or the USB link address
(`169.254.x.x`, visible in `arp -a` as `<name>-iphone.local`). The runner posts each
JPEG to `POST /api/benchmark` on a fresh connection — the app's listener drops the
socket after every response, and reusing it costs about 1.5 s of stalled read — then
appends the raw JSON and resumes from it after an interruption. `--restart-cmd` can
relaunch the app automatically when a socket wedges.

`score_ios.py` imports `score_rows` from the repository's own `score.py`, so image
outcomes and per-symbol matching match the native, browser, Python and Android runs.
The iOS ZXing-C++ numbers land within a point of the native Linux pass (47.65% versus
48.15% exact images, 55 versus 56 wrong-read images), which is the check that the
integration is configured like the C++ runner rather than tuned to the corpus.
