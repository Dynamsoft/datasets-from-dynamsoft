//
//  BenchmarkConfig.swift
//  BarcodeBenchmark
//
//  Global configuration for benchmark settings
//

import Foundation
import ZXingCpp

class BenchmarkConfig {
    
    /// Toggle to show/hide benchmark time in UI
    static var showBenchmarkTime: Bool = false
    
    /// Toggle to use custom Dynamsoft template or default built-in template
    static var useCustomTemplate: Bool = false
    
    /// Web server port
    static let serverPort: UInt16 = 8080

    /// Bring the HTTP endpoint up on launch so a benchmark pass can start
    /// without tapping the toggle. Set to false to start it manually.
    static let autoStartServer: Bool = true

    /// zxing-cpp is a C++ core built by Swift Package Manager, so it inherits the
    /// app's optimization level. A Debug build compiles it at -O0, which measured
    /// ~13x slower on an iPhone 11 — numbers from that build compare nothing.
    static var isOptimizedBuild: Bool {
        #if DEBUG
        return false
        #else
        return true
        #endif
    }

    static var buildDescription: String {
        isOptimizedBuild ? "Release build" : "Debug build: ZXing-C++ timings are ~13x too slow"
    }
    
    /// Frame extraction interval for video processing (in seconds)
    static let frameInterval: Double = 0.5

    /// Upper bound on symbols per image. zxing-cpp's iOS wrapper defaults to 255,
    /// which keeps the multi-symbol scan running over every pyramid layer and the
    /// inverted bitmap even after the last symbol on the frame was found.
    static let zxingMaxSymbols: Int = 16

    /// The symbologies this corpus actually contains, matching the explicit list
    /// the C++ runner hands to zxing-cpp. Leaving the reader on "every format"
    /// adds GS1 DataBar, which has no checksum to reject a bad read, and it
    /// returns hundreds of spurious DataBar payloads on textured backgrounds.
    static let zxingFormats: [ZXIFormat] = [
        .AZTEC, .CODABAR, .CODE_39, .CODE_93, .CODE_128, .DATA_MATRIX,
        .EAN_8, .EAN_13, .ITF, .MAXICODE, .PDF_417, .QR_CODE,
        .MICRO_QR_CODE, .UPC_A, .UPC_E
    ]

    /// Dynamsoft Barcode Reader trial license. Request your own at
    /// https://www.dynamsoft.com/customer/license/trialLicense/?product=dcv&package=cross-platform
    static let dynamsoftLicenseKey: String = "DLS2eyJoYW5kc2hha2VDb2RlIjoiMjM0ODEwLU1qTTBPREV3TFZSeWFXRnNVSEp2YWciLCJtYWluU2VydmVyVVJMIjoiaHR0cHM6Ly9tZGxzLmR5bmFtc29mdG9ubGluZS5jb20vIiwib3JnYW5pemF0aW9uSUQiOiIyMzQ4MTAiLCJzdGFuZGJ5U2VydmVyVVJMIjoiaHR0cHM6Ly9zZGxzLmR5bmFtc29mdG9ubGluZS5jb20vIiwiY2hlY2tDb2RlIjoxNzYwOTE2OTkyfQ=="
    
    /// Dynamsoft Capture Vision Router template JSON
    static let dynamsoftTemplateJSON: String = """
    {
        "GlobalParameter": {
            "IntraOpNumThreads": 2
        },
        "CaptureVisionTemplates": [
            {
                "ImageROIProcessingNameArray": ["ROI_Default"],
                "Name": "ReadBarcodes_Default",
                "MaxParallelTasks": 0,
                "Timeout": 100
            }
        ],
        "TargetROIDefOptions": [
            {
                "Name": "ROI_Default",
                "TaskSettingNameArray": ["Task_Default"]
            }
        ],
        "BarcodeReaderTaskSettingOptions": [
            {
                "Name": "Task_Default",
                "BarcodeFormatIds": ["BF_DEFAULT"],
                "ExpectedBarcodesCount": 0,
                "MaxThreadsInOneTask": 1,
                "SectionArray": [
                    {
                        "ImageParameterName": "ip",
                        "Section": "ST_BARCODE_LOCALIZATION",
                        "StageArray": [
                            {
                                "Stage": "SST_LOCALIZE_CANDIDATE_BARCODES",
                                "LocalizationModes": [
                                    {
                                        "Mode": "LM_SCAN_DIRECTLY",
                                        "ModelNameArray": null
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "ImageParameterName": "ip",
                        "Section": "ST_BARCODE_DECODING",
                        "StageArray": [
                            {
                                "Stage": "SST_DECODE_BARCODES",
                                "DeblurModes": [
                                    {
                                        "Mode": "DM_DIRECT_BINARIZATION"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "ImageParameterOptions": [
            {
                "ApplicableStages": [
                    {
                        "ImageScaleSetting": {
                            "EdgeLengthThreshold": 100000,
                            "ScaleType": "ST_SCALE_DOWN"
                        },
                        "Stage": "SST_SCALE_IMAGE"
                    },
                    {
                        "GrayscaleTransformationModes": [
                            {
                                "Mode": "GTM_ORIGINAL"
                            }
                        ],
                        "Stage": "SST_TRANSFORM_GRAYSCALE"
                    }
                ],
                "Name": "ip"
            }
        ]
    }
    """
}

// MARK: - Barcode Format Enum
enum BarcodeFormat: String, CaseIterable {
    case code128 = "CODE_128"
    case code39 = "CODE_39"
    case code93 = "CODE_93"
    case codabar = "CODABAR"
    case dataMatrix = "DATA_MATRIX"
    case ean13 = "EAN_13"
    case ean8 = "EAN_8"
    case itf = "ITF"
    case qrCode = "QR_CODE"
    case upcA = "UPC_A"
    case upcE = "UPC_E"
    case pdf417 = "PDF417"
    case aztec = "AZTEC"
    case unknown = "UNKNOWN"
}
