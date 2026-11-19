# Synthetic Barcode Benchmark

A still-image benchmark for barcode readers. The dataset contains **8,000 JPEGs**,
**11,372 annotated symbols**, **24 symbologies**, and **36 synthetic backgrounds**.
The native and browser runners use the same manifest and scoring rules.

- [Browse images by symbology](dataset-by-format/review.html)
- [Open the C++ / Linux report](review/index.html) and [summary JSON](review/summary.json)
- [Open the JavaScript / WebAssembly report](review/browser/index.html) and [summary JSON](review/browser/summary.json)
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
Perceptual hashes and color thumbnails screen for near-duplicates. Corpus
curation also used readability observations from the native readers, so the
reported results describe performance on this curated comparison set.

### Generate and verify a new corpus

The following commands create a fresh 8,000-image corpus. Use the report's
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

The native runner loads each image once as RGB and passes the same frame to
every SDK. It runs 24 warm-up calls per SDK, shuffles reader order per image with
a fixed seed, and measures the decode calls separately from image loading.
