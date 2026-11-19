#!/bin/sh
set -eu

project=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${ZXING_SOURCE_DIR:?Set ZXING_SOURCE_DIR to the ZXing-C++ source directory}"
: "${DCV_ROOT:?Set DCV_ROOT to the Dynamsoft Capture Vision SDK directory}"
build=${1:-"$project/../build"}
mkdir -p "$build"
build=$(CDPATH= cd -- "$build" && pwd)
libs="$build/dynamsoft-libs"

mkdir -p "$libs"
cp -L "$DCV_ROOT"/lib/linux/x64/*.so "$libs/"
cp -R "$DCV_ROOT/resource/Models" "$libs/"
cmake -S "$project" -B "$build" -DCMAKE_BUILD_TYPE=Release \
  -DZXING_SOURCE_DIR="$ZXING_SOURCE_DIR" -DDCV_ROOT="$DCV_ROOT" -DDCV_LIB_DIR="$libs"
cmake --build "$build"
