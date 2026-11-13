# BarBeR Benchmark — Web (JavaScript/WASM) and C++ (Linux)

Two complete, auditable barcode-reading benchmarks built on the same public
[BarBeR](https://ditto.ing.unimore.it/barber/) real-world dataset, comparing **Dynamsoft Barcode
Reader**, **Scandit** and **ZXing**:

| Directory | Runtime | Decoders | Published results |
|:----------|:--------|:---------|:------------------|
| [`js/`](./js/) | Browser, JavaScript/WASM | `dynamsoft-barcode-reader-bundle` 11.6.5000, Scandit Data Capture SDK for Web 8.7.1, zxing-wasm 3.1.2 | [`js/report/index.html`](./js/report/index.html) |
| [`cpp/`](./cpp/) | Native C++, Linux/amd64 (Docker) | Dynamsoft Barcode Reader 11.6.50.29329, Scandit Barcode Scanner SDK for Linux 8.7.1, ZXing-C++ 3.1.1 | [`cpp/report/index.html`](./cpp/report/index.html) |

Both runs use the **same audited manifest**, the **same 8,411 scored ground-truth instances** and
the **same matching rules**. A combined, machine-readable view is in
[`results/combined-summary.json`](./results/combined-summary.json) /
[`results/combined-summary.csv`](./results/combined-summary.csv), with a lightweight visual
comparison at [`results/comparison.html`](./results/comparison.html).

---

## The BarBeR dataset

BarBeR (*"BarBeR: A Barcode Benchmarking Repository"*, ICPR 2024) is a public collection of
**real-world photographs** of barcodes, hosted by the University of Modena and Reggio Emilia at
<https://ditto.ing.unimore.it/barber/>. It was created for training and testing barcode
localization algorithms and for reproducing the paper's results. It aggregates **12 smaller public
datasets** of 1D and 2D barcodes with metadata rewritten into a unified VGG/VIA annotation format.

| Field | Value |
|:------|:------|
| Images | 8,748 real images (not synthetic) |
| Annotated barcodes | 9,818 (8,062 linear / 1,756 two-dimensional) |
| Symbologies | 18 barcode types across 19 annotation categories (14 × 1D, 4 × 2D, plus an undecodable `1D` class) |
| Annotation | 4-vertex polygon per barcode, plus type, PPE (pixels per element) and encoded string |
| Resolution range | 200×141 to 5,984×3,376 |
| PPE range | 1D 0.88–24.33, 2D 1.21–71.1 |
| 1D types | Code 128, Code 39, EAN-2, EAN-8, EAN-13, GS1-128, IATA 2 of 5, Intelligent Mail, Interleaved 2 of 5, Japan Post, KIX, PostNet, Royal Mail, UPC |
| 2D types | Aztec, Data Matrix, PDF417, QR Code |

### Audit used by both benchmarks

Both harnesses re-audit the dataset before every published run and ship the resulting manifest
(`js/manifests/`, `cpp/manifests/`) plus a per-file SHA-256 inventory
(`manifests/barber_source_files.json`):

- Start: **8,748** image records / **9,818** annotations.
- Exclude **853** images without reliable ground truth and **1** exact duplicate image.
- Final manifest: **7,894** unique images, **7,894** unique image hashes, **8,615** ground-truth
  barcode instances.
- **204** ground-truth payloads are the unreliable placeholder `^` and are excluded from scoring →
  **8,411 scored instances**.
- One repetition per decoder → **23,682 decode records per runtime**.

Scored ground truth by format (from the audited manifest):

| Format | Count | Format | Count |
|:-------|------:|:-------|------:|
| EAN-13 | 4,857 | ITF | 71 |
| QR Code | 1,324 | EAN-8 | 68 |
| Code 128 | 1,120 | Aztec | 26 |
| UPC-A | 319 | Japan Post | 17 |
| Code 39 | 198 | KIX / PostNet / GS1-128 / IATA 2 of 5 / Intelligent Mail | 22 |
| Royal Mail | 192 | | |
| Data Matrix | 110 | | |
| PDF417 | 87 | **Total** | **8,411** |

> **The dataset images themselves are not included in this repository** (size and
> redistribution terms). Download BarBeR from the official site and point `--images` at its
> `dataset/images/` folder. This repository ships the audited manifests, hashes, results and
> reports so every number can be re-checked without re-downloading the images.

---

## Licenses — apply for your own keys

**No license key is included in this repository.** Both commercial readers require a trial key you
apply for yourself. Placeholders and full instructions are in [`licenses/README.md`](./licenses/README.md).

| Key file to create | Used by | Apply here |
|:-------------------|:--------|:-----------|
| `licenses/dynamsoft-dbr.txt` | Web **and** C++ (Dynamsoft Barcode Reader) | [Dynamsoft free 30-day trial](https://www.dynamsoft.com/customer/license/trialLicense/?product=dcv&package=cross-platform) |
| `licenses/scandit-web.txt` | Web benchmark (Scandit SDK for **Web** 8.7.1) | [Scandit trial](https://www.scandit.com/trial/) |
| `licenses/scandit-linux.txt` | C++ benchmark (Scandit SDK for **Linux** 8.7.1) | [Scandit dashboard](https://ssl.scandit.com/dashboard/) — Linux platform, with the **tracking** feature |

Copy the matching `*.txt.example` template, paste your own key on one line, and keep it local (all
three filenames are git-ignored). Environment variables work too:
`DYNAMSOFT_LICENSE_KEY`, `SCANDIT_LICENSE_KEY` (the Web key for `js/`, the Linux key for `cpp/`).
Scandit Web and Linux keys are **not interchangeable**; a Linux key needs network activation.
ZXing (ZXing-C++ / zxing-wasm) is open source and needs no license.

Two proprietary SDKs are also **not redistributable** and therefore not bundled:

- The Dynamsoft Capture Vision SDK → place at `barber-benchmark/dcv/` for the C++ Docker run.
- Scandit's Linux `.deb` → place at `cpp/third_party/scandit-barcodescanner-linux_8.7.1/`.
- `cpp/zxing-cpp/` is a git submodule (ZXing-C++ v3.1.1) to check out before a native build.

---

## Results — Web / JavaScript (WASM)

Single headless Chrome session on Windows 11, Node 22.22.2, i5-13400F, one repetition.
Full details: [`js/README.md`](./js/README.md) and [`js/report/index.html`](./js/report/index.html).

| Decoder | Correct | Recall | Wrong reads | No read | Mean | Median | P95 |
|:--------|--------:|-------:|------------:|--------:|-----:|-------:|----:|
| Dynamsoft Barcode Reader JS 11.6.5000 | **7,638 / 8,411** | **90.81%** | 90 | 683 | 157.88 ms | 125.75 ms | 380.20 ms |
| Scandit Data Capture SDK 8.7.1 (Web) | 7,589 / 8,411 | 90.23% | **85** | 737 | **92.42 ms** | **76.80 ms** | **202.60 ms** |
| zxing-wasm 3.1.2 | 6,019 / 8,411 | 71.56% | 94 | 2,298 | 144.54 ms | 88.20 ms | 476.00 ms |

Scandit read 49 fewer ground-truth barcodes than DBR (‑0.58 points of recall) and 1,570 more than
zxing‑wasm (+18.67 points). It was fastest on every timing measure and produced the fewest wrong
reads.

> **Post-run correction (auditable):** the first Web pass labeled Scandit Code 128 results carrying
> `isGS1DataCarrier` as `GS1_128`, producing 171 spurious `wrong_format` outcomes (BarBeR has 4
> `GS1_128` vs 1,120 `CODE_128` annotations). The harness now labels all Code 128 results
> `CODE_128`, like the other two decoders, and the JSONL was re-scored with unchanged matching
> rules. Under the pre-correction labels and the v1 rules Scandit scored 7,287 / 8,411 (86.64%
> recall). Five images cannot be decoded by the browser and are counted as no-reads for all three
> decoders.

## Results — C++ / Linux (native)

Ubuntu 24.04 linux/amd64 container, 4 worker processes on disjoint manifest slices of the same
7,894-image manifest, one repetition. Full details: [`cpp/README.md`](./cpp/README.md) and
[`cpp/report/index.html`](./cpp/report/index.html).

| Decoder | Correct | Recall | Wrong reads | No read | Mean | Median | P95 |
|:--------|--------:|-------:|------------:|--------:|-----:|-------:|----:|
| Dynamsoft Barcode Reader 11.6.50.29329 (Linux) | **8,046 / 8,411** | **95.66%** | **89** | **276** | 444.05 ms | 261.60 ms | 1422.82 ms |
| Scandit Barcode Scanner SDK 8.7.1 (Linux) | 7,604 / 8,411 | 90.41% | 245 | 562 | 105.73 ms | 89.78 ms | **229.06 ms** |
| ZXing-C++ 3.1.1 | 6,031 / 8,411 | 71.70% | 100 | 2,280 | **70.90 ms** | **38.51 ms** | 265.90 ms |

Scandit read 442 fewer barcodes than DBR (‑5.25 points of recall) and 1,573 more than ZXing-C++
(+18.71 points). The gap to DBR comes from the no-read column rather than from misreads: Scandit
leaves 562 annotations unread against DBR's 276, and it also reads 156 more of them wrongly (245
against 89). Unsupported formats account for Scandit 23 (it has no JAPAN_POST / POSTNET symbology)
and ZXing-C++ 227; DBR supports every BarBeR symbology, so its whole no-read column is barcodes it
did not return. Six DBR frames returned "Operation timeout" and are counted as no-reads.

> **Timing caveat:** four worker processes shared 16 logical processors, so absolute decode times
> include CPU contention. The Linux DCV build also runs the official preset template with
> deep-learning models and is a different binary from the Windows/Web builds. **Decode times are
> not comparable across the two runtimes** — use them only to compare decoders within one run.

> **How the three outcome columns add up:** every one of the 8,411 annotations ends in exactly one
> of correct, wrong read or no read, and the three always sum to 8,411. A prediction that matches no
> annotation is not a fourth outcome — BarBeR's annotations are curated rather than exhaustive, so
> the harness cannot tell an unannotated barcode on the image from a hallucination, and it sets such
> predictions aside rather than charging them to any instance. That is also why no precision figure
> is reported: its denominator would be predictions rather than annotations, and on this dataset the
> ratio measures how much a decoder reads beyond the annotation file.

## Scoring protocol v2

The first publication of these tables used protocol v1. Three matching defects were found in review
and are now fixed; **no decoder was re-run and no decode time changed** — every record was re-scored
from the same predictions with `rematch` and now carries `"protocol": "protocol-v2"`.

1. **Underscored ground-truth labels.** The canonical-format table strips punctuation before lookup,
   so `ROYAL_MAIL`, `IATA_2_OF_5` and `USPS_INTELLIGENT_MAIL` reduced to `ROYALMAIL` /
   `IATA2OF5` / `USPSINTELLIGENTMAIL` and matched no decoder's supported set. Every reader was
   charged for that — 196 annotations in the Web run, 192 in the Linux run — and the Royal Mail
   codes the Linux decoders did return were set aside. Those three spellings now map to the names
   the decoders use.
2. **GS1 application identifiers in parentheses.** zxing-wasm reports `(90)85320` where the
   annotation holds the raw element string `9085320`. The parentheses are now unwrapped for
   Code 128, which recovers 61 readings.
3. **Royal Mail payload length.** The Linux DBR build returns 10 of the 11 characters the annotation
   holds. A one-character prefix now counts as the same reading, for that symbology only.

| Run | Decoder | v1 | v2 | Δ |
|:----|:--------|:---|---:|---:|
| Web | Dynamsoft Barcode Reader JS | 7,638 · 90.81% | 7,638 · 90.81% | — |
| Web | Scandit Data Capture SDK | 7,454 · 88.62% | 7,589 · 90.23% | +135 · +1.61 |
| Web | zxing-wasm | 5,958 · 70.84% | 6,019 · 71.56% | +61 · +0.72 |
| Linux | Dynamsoft Barcode Reader | 7,863 · 93.48% | 8,046 · 95.66% | +183 · +2.18 |
| Linux | Scandit Barcode Scanner SDK | 7,467 · 88.78% | 7,604 · 90.41% | +137 · +1.63 |
| Linux | ZXing-C++ | 6,031 · 71.70% | 6,031 · 71.70% | — |

The ranking is unchanged in both runtimes. The Linux DBR gain is larger than the Web DBR gain because
only the native build decodes Royal Mail at all.

## Cross-runtime observations

- **Scandit is remarkably consistent**: 90.23% recall on Web vs 90.41% on Linux, despite entirely
  different SDKs (Web WASM / Linux C API), engines and symbology configurations.
- **ZXing is likewise close**: 71.56% (zxing-wasm 3.1.2) vs 71.70% (ZXing-C++ 3.1.1), as expected
  from the same underlying C++ core.
- **DBR differs most**: 90.81% on Web vs 95.66% on Linux. The Linux build runs the deep-learning
  model preset template and detects more aggressively — it resolves 408 more of the 8,411
  annotations and leaves 407 fewer unread — and 183 of that gain is Royal Mail, which only the
  native build decodes. Those are two different product builds, not the same decoder in two
  languages.
- In both runtimes the ranking by recall is **DBR > Scandit > ZXing**, and Scandit consistently
  leads on decode latency.

---

## Method and scoring

Both harnesses follow the same protocol-v2 rules (the companion Python benchmark still runs v1):

- Every image is loaded once into a shared RGB888 / canvas buffer; **only the decoder call is
  timed**. Image loading, matching and serialization are excluded.
- Decoder order is shuffled per (image, repetition) with a seeded PRNG.
- Predictions and ground truth are matched one-to-one as multisets on canonical format plus exact
  normalized payload. UPC-A/EAN-13 leading zeros, Code 39 asterisks, Code 128 GS1 markers, GS1
  application identifiers in parentheses, a one-character Royal Mail prefix, HTML entities,
  trailing newlines and a leading `\000001` escape are normalized. The `^` placeholder is excluded
  and barcode location is not scored.
- Every annotation resolves to exactly one outcome: **correct**, **wrong read**
  (`wrong_text + wrong_format`) or **no read** (`not_found + unsupported_format + decoder_error`),
  and the three sum to the 8,411 scored annotations. A prediction that no annotation claims is
  discarded instead of being charged to an instance, because the annotation file is not exhaustive.
- Scandit reports EAN-13/UPC-A as one combined symbology (split by payload length) and has no
  JAPAN_POST/POSTNET symbology, which is the only reason it has any unsupported annotations at all.
  See [Scoring protocol v2](#scoring-protocol-v2) for what changed from the first publication.

---

## Reproduce

**Prepare the dataset** — download BarBeR and point `--images` at
`<BarBeR>/dataset/images/`. The expected layout is `Annotations/VIA/` + `dataset/images/`.

**Web run**

```bash
cd js
npm install                        # pinned zxing-wasm, DBR bundle, Scandit packages, puppeteer-core
DYNAMSOFT_LICENSE_KEY='...' SCANDIT_LICENSE_KEY='...' \
  node tools/run_headless.mjs \
    --images "D:/images/BarBeR_Dataset/BarBeR - Dataset/dataset/images" \
    --manifest manifests/benchmark_manifest.jsonl --output results/full
```

The runner starts the collector server, drives the harness in headless Chrome, resumes from any
records already present, restarts the browser periodically and finalizes automatically. Keys may
instead be pasted into the two license fields on `http://localhost:8790/`.

**C++ run** — provision `dcv/`, `cpp/zxing-cpp/` and the Scandit `.deb` as described above, then:

```bash
cd cpp
tools/run_benchmark_docker.sh smoke   # 10-image sanity check
tools/run_benchmark_docker.sh full    # all 7,894 images
```

**Regenerate the combined view** (no decoder re-run, reads the two shipped `summary.json` files):

```bash
node tools/build_combined_summary.mjs
```

## Data shipped here

| Path | Contents |
|:-----|:---------|
| [`results/comparison.html`](./results/comparison.html) | Lightweight side-by-side comparison with a recall chart |
| [`results/combined-summary.json`](./results/combined-summary.json), [`.csv`](./results/combined-summary.csv) | All 6 decoder results in machine-readable form |
| [`js/report/index.html`](./js/report/index.html), [`cpp/report/index.html`](./cpp/report/index.html) | Self-contained interactive reports with searchable per-image records |
| `js/results/full/`, `cpp/results/full_linux/` | Raw `results.jsonl` streams + `summary.json` |
| `js/manifests/`, `cpp/manifests/` | Audited manifest, smoke manifest, per-file SHA-256 inventory |
| `js/configs/`, `cpp/configs/` | Environment snapshots, symbology support, preset templates |

The large `results.json` packages and `report/downloads/` duplicates from the source projects are
omitted here; the raw JSONL streams and self-contained reports contain the same records.

## Disclosure

Dynamsoft, the developer of Dynamsoft Barcode Reader, built and published these benchmarks. ZXing
and Scandit are third-party products evaluated with their standard, publicly documented settings
and trial licenses. BarBeR is an independent public dataset; its standardized annotations were
produced with assistance from proprietary Datalogic software. Source hashes, exclusion lists,
configurations, raw records and generated reports are provided so any reviewer can re-check the
comparison. Results are measurements of one specific configuration and build, not a general claim
about product quality.
