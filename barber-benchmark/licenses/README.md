# Trial licenses — supply your own

This directory holds **placeholders only**. No commercial license key is included in this
repository. The two commercial readers in the BarBeR benchmarks need keys you apply for yourself.

| File to create | Used by | Where to apply |
|:---------------|:--------|:---------------|
| `dynamsoft-dbr.txt` | Web/JS benchmark **and** C++/Linux benchmark (Dynamsoft Barcode Reader) | [Dynamsoft free 30-day trial](https://www.dynamsoft.com/customer/license/trialLicense/?product=dcv&package=cross-platform) |
| `scandit-web.txt` | Web/JS benchmark (Scandit Data Capture SDK for Web 8.7.1) | [Scandit trial](https://www.scandit.com/trial/) — create a **Web** license |
| `scandit-linux.txt` | C++/Linux benchmark (Scandit Barcode Scanner SDK for Linux 8.7.1) | [Scandit dashboard](https://ssl.scandit.com/dashboard/) — create a **Linux** license with the **tracking** feature for multi-code scanning |

ZXing (ZXing-C++ / zxing-wasm) is open source and needs no license.

## How to use

1. Copy each `*.txt.example` to the matching filename above (drop the `.example` suffix).
2. Paste **your own** trial key as the only content, on a single line, without quotes.
3. Keep the files local. They are excluded by `.gitignore` — never commit a filled key.

Alternatively, skip the files and use environment variables:

```bash
export DYNAMSOFT_LICENSE_KEY='...'
export SCANDIT_LICENSE_KEY='...'   # Web key for js/, Linux key for cpp/
```

- The JS harness also accepts both keys in the two license fields on its page.
- `js/tools/run_headless.mjs` reads `DYNAMSOFT_LICENSE_KEY` / `SCANDIT_LICENSE_KEY`, falling back
  to `dynamsoft-dbr.txt` / `scandit-web.txt`.
- `cpp/tools/run_benchmark_docker.sh` reads `dynamsoft-dbr.txt` / `scandit-linux.txt` and passes
  them into the container as `DYNAMSOFT_LICENSE_KEY` / `SCANDIT_LICENSE_KEY`.
- The C++ binary also accepts `--license-key-file` / `--scandit-license-key-file`; environment
  variables take priority.

> Scandit Web and Linux keys are **not interchangeable**. A Linux key must be generated for the
> Linux platform, needs network access for activation, and needs the "tracking" feature to scan
> multiple barcodes in one image.

The Dynamsoft Capture Vision SDK and Scandit's Linux `.deb` are proprietary and not
redistributable, so neither is bundled here. See the top-level README for provisioning them.
