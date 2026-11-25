# Android Barcode Scanner Benchmark

A professional Android benchmarking application that compares **Dynamsoft Barcode Reader SDK** vs **Google ML Kit** barcode scanning performance across multiple input sources.

This app lives inside the synthetic benchmark repository, next to the dataset it
measures and the runner that drives it, so an on-device run needs nothing but this
clone: build the app, start its HTTP server, and run
[`android/run_benchmark.py`](../run_benchmark.py). The results in
`review/android/summary.json` were produced from exactly this tree.

https://github.com/user-attachments/assets/a30de920-1bda-4024-b6a9-7de459e163ae

## Features

### Benchmark Modes

-   **Image File Benchmark**: Load an image from gallery and compare decoding performance
-   **Video File Benchmark**: Process video frames and compare multi-frame scanning performance
-   **Live Camera Testing**: Real-time barcode scanning with both SDKs

### Remote Benchmark (Web Server)

-   Built-in web server for remote file upload
-   Upload images or videos from your desktop PC browser
-   View benchmark results directly in your browser
-   Beautiful, responsive web UI

### Detailed Results

-   Side-by-side comparison of decoding time
-   Barcode count comparison
-   Visual progress bars for time comparison
-   Detailed list of detected barcodes with format and content

### Supported Barcode Formats

Both SDKs support a wide range of barcode formats including:
-   1D: Code 128, Code 39, Code 93, Codabar, EAN-13, EAN-8, ITF, UPC-A, UPC-E
-   2D: QR Code, Data Matrix, PDF417, Aztec

## Prerequisites

- Android device running Android 5.0 (API 21) or higher
- Obtain a [30-day Trial License](https://www.dynamsoft.com/customer/license/trialLicense/?product=dcv&package=cross-platform) for Dynamsoft Barcode Reader

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/Dynamsoft/datasets-from-dynamsoft.git
cd datasets-from-dynamsoft/synthetic-benchmark/android/mlkit-dbr-benchmark
```

### 2. Open in Android Studio

Open the `mlkit-dbr-benchmark` folder in Android Studio.

### 3. Barcode formats and the ZXing-C++ switch

`BenchmarkConfig.applyDynamsoftSettings()` keeps the built-in `ReadBarcodes_Default`
preset and widens `barcodeFormatIds` to `BF_ALL`, because the preset's `BF_DEFAULT`
omits postal codes, MaxiCode, DotCode, MSI, Pharmacode and Micro QR. The same method
lets `USE_CUSTOM_TEMPLATE` replace the preset with a full template JSON.

`BenchmarkConfig.ENABLE_ZXING` defaults to `false`. The zxing-cpp Android wrapper
aborts the process on a small number of images (`JNI ... Invalid BarcodeFormat`
followed by SIGABRT) in 3.0.2 and 3.1.1 alike, and narrowing the reader to the 15
scored formats still ended a 1,300-image pass around image 1,076. The reader is
therefore compiled in but never called: the home-screen entry stays visible at 45%
alpha and explains itself on tap, and the result screen drops the ZXing column.
Everything behind the switch is intact, so setting it to `true` brings the reader
back for a build that can live with the crash.

### 4. License Key

The application requires a valid license key from Dynamsoft to function. Update the license key in `MainActivity.java`:

```java
// MainActivity.java
LicenseManager.initLicense(
    "YOUR_LICENSE_KEY",
    this, (isSuccessful, error) -> { ... }
);
```

### 5. Build and Run

Connect your Android device and run the application:

```bash
.\gradlew.bat assembleDebug
.\gradlew.bat installDebug
```

## Usage

### On-Device Benchmarking

1. Grant camera and storage permissions when prompted
2. Choose an input source:
   - **Image File**: Select an image with barcodes
   - **Video File**: Select a video containing barcodes
   - **Dynamsoft Camera**: Live scanning with Dynamsoft SDK
   - **MLkit Camera**: Live scanning with Google MLkit
3. View the benchmark results comparing both SDKs

### Remote Benchmarking (Web Server)

1. Enable the **Web Server** toggle on the home screen
2. Note the displayed URL (e.g., `http://192.168.1.100:8080`)
3. Open the URL in a desktop browser on the same network
4. Drag & drop or select an image/video file
5. Click "Run Benchmark" to process the file on the Android device
6. View detailed results in your browser

   <img width="600" alt="dynamsoft-mlkit-barcode-scanner-benchmark" src="https://github.com/user-attachments/assets/62cbecbb-3b0b-4574-b70d-177ed2997d67" />

## Blog
[Dynamsoft Barcode Reader vs Google ML Kit: A Comprehensive Accuracy Comparison for Android Developers](https://www.dynamsoft.com/codepool/dynamsoft-vs-mlkit-barcode-scanner-accuracy-comparison.html)
