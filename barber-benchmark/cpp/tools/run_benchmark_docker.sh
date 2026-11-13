#!/usr/bin/env bash
# Reproduce the three-way BarBeR benchmark (ZXing-C++, DBR, Scandit Linux) in a
# linux/amd64 container. Scandit's Linux SDK .deb is not redistributable, so it
# must be placed under third_party/ before building.
#
# This copy lives in datasets-from-dynamsoft/barber-benchmark/cpp/. Layout:
#   barber-benchmark/
#     licenses/          user-supplied trial keys (never committed)
#     dcv/               Dynamsoft Capture Vision SDK (user-supplied)
#     cpp/               this benchmark (zxing-cpp submodule must be checked out)
#
# Usage (Git Bash on Windows):
#   tools/run_benchmark_docker.sh smoke
#   tools/run_benchmark_docker.sh full
#   tools/run_benchmark_docker.sh shell
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(cd "$BENCH_DIR/.." && pwd)"
DBR_KEY_FILE="$PROJECT_DIR/licenses/dynamsoft-dbr.txt"
SCANDIT_KEY_FILE="$PROJECT_DIR/licenses/scandit-linux.txt"
IMAGE_NAME="${BENCH_IMAGE:-barber-benchmark:scandit-8.7.1}"
DATASET_IMAGES="${BARBER_IMAGES:-D:/images/BarBeR_Dataset/BarBeR - Dataset/dataset/images}"
ACTION="${1:-smoke}"

winpath() {
    if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

# Both commercial keys must be applied for by the user. See ../licenses/README.md.
for key_file in "$DBR_KEY_FILE" "$SCANDIT_KEY_FILE"; do
    if [[ ! -f "$key_file" ]]; then
        echo "Missing $key_file" >&2
        echo "Copy the matching .example file in licenses/ and apply for your own trial key." >&2
        echo "See licenses/README.md (keys are excluded from Git)." >&2
        exit 1
    fi
done

if [[ ! -d "$PROJECT_DIR/dcv" ]]; then
    echo "Missing $PROJECT_DIR/dcv — the Dynamsoft Capture Vision SDK is not redistributable." >&2
    echo "Download it and place the SDK root at that path before running." >&2
    exit 1
fi

if [[ ! -f "$BENCH_DIR/third_party/scandit-barcodescanner-linux_8.7.1/libscandit-barcodescanner-8.7.1-amd64.deb" ]]; then
    echo "Missing the Scandit Linux SDK .deb under third_party/ (not redistributable)." >&2
    echo "Download it from the Scandit dashboard and place it there before running." >&2
    exit 1
fi

docker build --platform linux/amd64 -f "$BENCH_DIR/Dockerfile" -t "$IMAGE_NAME" "$BENCH_DIR"

MOUNTS=(
    --platform linux/amd64
    -v "$(winpath "$PROJECT_DIR")":/workspace/project
    -v "$(winpath "$DATASET_IMAGES")":/images:ro
    -w /workspace/project/cpp
    -e "DYNAMSOFT_LICENSE_KEY=$(tr -d '\r\n' < "$DBR_KEY_FILE")"
    -e "SCANDIT_LICENSE_KEY=$(tr -d '\r\n' < "$SCANDIT_KEY_FILE")"
)

# The Linux DCV build resolves model files relative to the directory the .so
# files were linked from, not next to the executable. Stage a private copy of
# the SDK inside the container with Models/ beside the libraries. Its preset
# template also needs explicit CaptureVisionModelOptions (see
# configs/dbr_preset_templates_linux.json), which fixes "Model file is not found".
BUILD='set -e
B=/workspace/project/cpp
rm -rf /tmp/dcv
cp -a /workspace/project/dcv /tmp/dcv
cp -a /tmp/dcv/resource/Models /tmp/dcv/lib/linux/x64/Models
cmake -S "$B" -B /tmp/build -DCMAKE_BUILD_TYPE=Release -DDCV_ROOT=/tmp/dcv
cmake --build /tmp/build --target barcode_benchmark -j "$(nproc)"'

# Keys are passed as environment variables; main.cpp readLicense() prefers
# DYNAMSOFT_LICENSE_KEY / SCANDIT_LICENSE_KEY over --*-license-key-file.
common_args="--images /images
             --decoders zxing-cpp,dynamsoft-dbr,scandit-linux
             --zxing-config \$B/configs/zxing_all_supported.json
             --scandit-config \$B/configs/scandit_all_supported.json
             --dbr-config \$B/configs/dbr_preset_templates_linux.json
             --dbr-template ReadBarcodes_Default
             --scandit-data-dir /var/tmp/scandit
             --repetitions 1"

case "$ACTION" in
    shell)
        exec docker run --rm -it "${MOUNTS[@]}" "$IMAGE_NAME" bash -c "$BUILD; exec bash"
        ;;
    smoke|full)
        if [[ "$ACTION" == "smoke" ]]; then
            MANIFEST=manifests/smoke_manifest.jsonl
            OUTPUT=results/smoke_linux
            SUBCOMMAND=smoke
        else
            MANIFEST=manifests/benchmark_manifest.jsonl
            OUTPUT=results/full_linux
            SUBCOMMAND=run
        fi
        RUN="cd /tmp/build
./barcode_benchmark $SUBCOMMAND \
  $common_args \
  --manifest \$B/$MANIFEST \
  --output \$B/$OUTPUT"
        docker run --rm "${MOUNTS[@]}" "$IMAGE_NAME" bash -c "$BUILD
$RUN"
        ;;
    *)
        echo "unknown action: $ACTION (use smoke, full or shell)" >&2
        exit 2
        ;;
esac
