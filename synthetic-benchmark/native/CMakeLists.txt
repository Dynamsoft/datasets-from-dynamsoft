cmake_minimum_required(VERSION 3.18)
project(synthetic_barcode_benchmark LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(ZXING_SOURCE_DIR "" CACHE PATH "ZXing-C++ v3.1.1 source directory")
set(DCV_ROOT "" CACHE PATH "Local Dynamsoft Capture Vision SDK root")
set(DCV_LIB_DIR "${DCV_ROOT}/lib/linux/x64" CACHE PATH "Dynamsoft SDK libraries and adjacent Models directory")
if(NOT EXISTS "${ZXING_SOURCE_DIR}/CMakeLists.txt" OR NOT EXISTS "${DCV_ROOT}/include/DynamsoftCaptureVisionRouter.h")
    message(FATAL_ERROR "Set ZXING_SOURCE_DIR and DCV_ROOT to the provisioned SDKs")
endif()

set(ZXING_READERS ON CACHE BOOL "" FORCE)
set(ZXING_WRITERS OFF CACHE BOOL "" FORCE)
set(ZXING_EXAMPLES OFF CACHE BOOL "" FORCE)
set(ZXING_EXAMPLES_QT OFF CACHE BOOL "" FORCE)
add_subdirectory("${ZXING_SOURCE_DIR}" zxing EXCLUDE_FROM_ALL)

find_package(nlohmann_json REQUIRED)
find_path(SCANDIT_INCLUDE_DIR Scandit/ScBarcodeScanner.h REQUIRED)
find_library(SCANDIT_LIBRARY NAMES scanditsdk REQUIRED)

add_executable(synthetic_benchmark
    main.cpp
    src/hash.cpp
    src/image_loader.cpp
    src/normalization.cpp
    src/zxing_decoder.cpp
    src/dynamsoft_decoder.cpp
    src/scandit_decoder.cpp
)
target_compile_definitions(synthetic_benchmark PRIVATE BENCH_HAS_SCANDIT=1)
target_include_directories(synthetic_benchmark PRIVATE
    include stb "${DCV_ROOT}/include" "${SCANDIT_INCLUDE_DIR}")
target_link_directories(synthetic_benchmark PRIVATE "${DCV_LIB_DIR}")
target_link_libraries(synthetic_benchmark PRIVATE ZXing::Core nlohmann_json::nlohmann_json
    DynamsoftCore DynamsoftLicense DynamsoftCaptureVisionRouter DynamsoftUtility DynamsoftBarcodeReader
    "${SCANDIT_LIBRARY}" pthread)
