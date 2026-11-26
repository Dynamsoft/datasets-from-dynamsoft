# iOS on-device benchmark

The iOS pass runs the same 8,000 images through the same scoring rules as the
native, browser, Python and Android runners, on a real iPhone. The app itself is
a SwiftUI benchmark harness: four readers behind one protocol, an image picker, a
video pass, live camera overlays, and an embedded HTTP server so a desktop can
drive a full pass without touching the phone.

| SDK | Type | Overlay |
| --- | --- | --- |
| **Dynamsoft Barcode Reader** | Commercial | Blue |
| **Google ML Kit** | Free | Green |
| **Apple Vision** | Native iOS | Purple |
| **ZXing-C++** | Open source | Orange |

Versions: Dynamsoft Barcode Reader 11.6.5000 (Capture Vision 3.6.5000, SPM), Google
ML Kit 8.0.0 (CocoaPods), Apple Vision (iOS SDK), ZXing-C++ 3.1.1 (SPM, pinned —
the same revision the C++ runner uses).

```text
ios/
  BarcodeBenchmark.xcworkspace/   workspace (CocoaPods for ML Kit, SPM for the rest)
  BarcodeBenchmark/               detectors, embedded HTTP server, benchmark UI
  run_benchmark.py                uploads each JPEG to POST /api/benchmark, appends JSON
  score_ios.py                    scores the pass with score.py's own matching rules
```

## How a pass works

1. Install Google ML Kit through CocoaPods, then open the **workspace**:

```sh
cd ios
pod install
open BarcodeBenchmark.xcworkspace
```

2. Build and install on the phone. The shared scheme builds **Release** — keep it
   that way (see [Build configuration](#build-configuration)).
3. Launch the app. The HTTP endpoint starts on port 8080 by itself and the home
   screen shows the address. The idle timer stays off while the server runs, so
   the screen does not lock mid-pass.
4. Run the pass and score it:

```sh
python ios/run_benchmark.py --dataset dataset-by-format \
  --host 169.254.35.41 --output .runs/ios-next/results.jsonl
python ios/score_ios.py --results .runs/ios-next/results.jsonl \
  --output review/ios/summary.json --device "iPhone 11, iOS 26.6.1"
```

`--host` is whatever the app prints. Over USB the phone also answers on its
point-to-point link address (`169.254.x.x`, listed by `arp -a` as
`<name>-iphone.local`), which is faster than Wi-Fi and does not depend on the
access point. `--limit` and the resume behaviour work like the Android runner: an
existing `results.jsonl` is never rewritten, only extended. Pass `--restart-cmd
"xcrun devicectl device process launch --terminate-existing --device <udid>
com.xiao.BarcodeBenchmark"` to relaunch the app automatically when a socket wedges.

## The endpoint

`POST /api/benchmark`, multipart form data:

| Field | Value |
| --- | --- |
| `file` | the image (or video) |
| `fileType` | `image` or `video` |
| `decoders` | optional, comma-separated subset of `dbr,mlkit,vision,zxing` |

The response carries one object per reader with `timeMs`, `count` and a
`barcodes` array of `{format, text}`. A reader that throws reports `error`
instead of an empty list, so a rejected license or a crashed SDK is scored as a
no-read rather than silently counted as "nothing on the image". `GET
/api/status` reports the Dynamsoft license state, and the runner refuses to start
a pass when it is not `valid`.

Readers run one after another on the same `UIImage`, and only the decode call is
timed. Upload, JSON encoding and connection setup stay outside the measurement.

## Configuration that matters

- **Dynamsoft uses `BF_ALL`.** The built-in `ReadBarcodes_Default` preset ships
  `BF_DEFAULT`, which omits MaxiCode, DotCode, postal codes, MSI and Pharmacode —
  1,900+ symbols in this corpus. The app widens `barcodeFormatIds` through
  `getSimplifiedSettings()` / `updateSettings()` exactly like the native and
  Android runners.
- **ZXing-C++ runs the native runner's options.** Try harder, rotate, invert and
  downscale, local-average binarizer, plain text, EAN add-on symbols,
  `maxNumberOfSymbols = 16`, and an explicit 15-format list. Two of those matter:
  the wrapper's default of 255 is less a cap than a promise never to stop scanning
  early, and "every format" pulls in GS1 DataBar, which has no checksum to reject a
  bad read and returns hundreds of spurious payloads on the corpus' textured
  backgrounds.
- **ML Kit and Vision are limited by their format lists.** ML Kit implements 13
  symbologies; Vision's `VNDetectBarcodesRequest` covers 12 plus the two that
  arrive as another format (UPC-A as zero-prefixed EAN-13, GS1-128 as Code 128
  with FNC1). Symbols outside a reader's list count as unsupported, not as misses,
  and are excluded from its supported recall.
- **ZXing-C++ 2.3.0 covers 16 of the 24 symbologies.** It has no DotCode, MSI,
  IATA 2 of 5, postal or Pharmacode reader. `score_ios.py` publishes the same
  split the Android run uses.

## Build configuration

zxing-cpp is a C++ core built by Swift Package Manager, so it inherits the app's
optimization level. In the Debug configuration Xcode passes `-O0`, and on an iPhone 11
a 4032 x 3024 frame took **9,657 ms** to decode instead of **690 ms** — 14× slower,
with identical results. The other three readers ship as prebuilt frameworks and are
unaffected, which is why an untuned build makes ZXing look far worse than it is.

The shared scheme pins Build and Run to Release. If you build Debug by hand the
home screen labels the run as a Debug build, so a pass cannot be recorded by
accident.

## Result of the last pass

`review/ios/summary.json` — iPhone 11, 8,000 images:

| | Dynamsoft 11.6.5000 | ML Kit 8.0.0 | Apple Vision | ZXing-C++ 3.1.1 |
| --- | ---: | ---: | ---: | ---: |
| Symbols matched | 9,242 / 11,372 (81.27%) | 5,590 (49.16%) | 5,689 (50.03%) | 5,549 (48.80%) |
| Exact images | 6,382 (79.77%) | 4,103 (51.29%) | 3,998 (49.98%) | 3,812 (47.65%) |
| Wrong-read images | 78 | 60 | 31 | 55 |
| Shared-format recall | 92.59% | 84.92% | 86.42% | 77.46% |
| Mean / median / p95 | 54.1 / 32.1 / 131.6 ms | 32.5 / 30.0 / 64.0 ms | 39.9 / 30.0 / 98.0 ms | 38.6 / 31.1 / 111.2 ms |

No reader returned a prediction on any of the 200 background-only controls. The pass
ran at about 5 images/s and completed in 25 minutes of decoding.

## Notes

- Every image is uploaded per pass, one TCP connection per request: the app's
  listener closes the socket after each response, and reusing it costs ~1.5 s of
  stalled read before the retry.
- A full pass takes about 25 minutes on an iPhone 11 at ~5 images/s.
