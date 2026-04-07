# Datasets from Dynamsoft

A collection of image datasets provided by [Dynamsoft](https://www.dynamsoft.com/) for testing and benchmarking barcode reading performance. New datasets will be added to this repository over time.

## Datasets

### 1. [pdf417-small-module-size](./pdf417-small-module-size/)

Images of PDF417 barcodes with small module sizes, designed to test decoder performance under challenging low-density conditions. Includes 11 images and accompanying annotations.

| Field | Details |
|:------|:--------|
| Symbology | PDF417 |
| Images | 11 |
| Annotations | Included |

---

### 2. [skewed-datamatrix](./skewed-datamatrix/)

Real-world photos of Data Matrix barcodes captured at skewed angles. Useful for evaluating a decoder's perspective-correction and skew-tolerance capabilities.

| Field | Details |
|:------|:--------|
| Symbology | Data Matrix |
| Images | 42 |
| Annotations | — |

---

### 3. [UPS-Synthetic-Labels](./UPS-Synthetic-Labels/)

Synthetic UPS-style shipping label images created to test decoding of **Code128** and **MaxiCode** symbologies. Each label contains two Code128 barcodes (tracking and reference) and one MaxiCode. Images do not represent real shipments or personal data.

| Field | Details |
|:------|:--------|
| Symbologies | Code128 (×2), MaxiCode (×1) per label |
| Labels | 18 unique synthetic labels |
| Annotation format | JSON |
| License | CC BY 4.0 — *"UPS Synthetic Shipping Label Dataset, Dynamsoft, 2025."* |

---

### 4. [video-based-testing](./video-based-testing/)

Frame-level annotations extracted from video sequences, covering a range of challenging real-world conditions. Organized into two sub-categories:

#### Single-code scenarios

| Video | Scenario |
|:------|:---------|
| `damaged_qrcode_1080p` | Partially damaged QR Code |
| `EAN_13-distance` | EAN-13 scanned from varying distances |
| `EAN_13-motion-blur` | EAN-13 with motion blur |
| `reflective_surface_qrcode_1080p` | QR Code on a reflective surface |
| `rotated_vertical_ITF_1080p` | Vertically rotated ITF barcode |
| `wide_to_close_datamatrix_1080p` | Data Matrix scanned from wide to close range |

#### Multi-code batch scenarios

| Video | Scenario |
|:------|:---------|
| `batch_code39_1080p` | Multiple Code 39 barcodes in frame |
| `batch_dark_environment_1d_1080p` | 1D barcodes in a dark environment |
| `batch_datamatrix_1080p` | Multiple Data Matrix codes in frame |
| `batch_EAN13_1080p` | Multiple EAN-13 barcodes in frame |
| `batch_inverted_datamatrix_1080p` | Inverted (light-on-dark) Data Matrix codes |
| `batch_rotated_small_pdf417_1080p` | Small, rotated PDF417 barcodes |

Annotation files are in CSV format and reference 1080p video frames.

---

## Purpose

These datasets are intended for:

- Benchmarking barcode reading SDKs (e.g., [Dynamsoft Barcode Reader](https://www.dynamsoft.com/barcode-reader/overview/))
- Evaluating decoder robustness across challenging conditions
- Developing and tuning barcode detection algorithms
