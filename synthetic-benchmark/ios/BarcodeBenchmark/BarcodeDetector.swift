//
//  BarcodeDetector.swift
//  BarcodeBenchmark
//
//  Barcode detector implementations for Dynamsoft, MLKit, and Apple Vision
//

import UIKit
import AVFoundation
import Vision
import CoreImage

// MARK: - Dynamsoft Barcode Detector

/// One CIContext for the whole app. Creating one per frame costs more than the
/// pixel buffer conversion it performs.
extension CIContext {
    static let shared = CIContext(options: [.cacheIntermediates: false])
}

#if canImport(DynamsoftCaptureVisionBundle)
import DynamsoftCaptureVisionBundle
import DynamsoftBarcodeReaderBundle

class DynamsoftBarcodeDetector: NSObject, BarcodeDetector, LicenseVerificationListener {

    private let cvr: CaptureVisionRouter
    /// nil = license check still in flight, false = rejected or expired.
    private(set) var licenseVerified: Bool?

    override init() {
        cvr = CaptureVisionRouter()
        super.init()
        LicenseManager.initLicense(BenchmarkConfig.dynamsoftLicenseKey, verificationDelegate: self)
        // The built-in preset ships BF_DEFAULT, which omits MaxiCode, DotCode,
        // postal codes, MSI and Pharmacode — 1,900+ symbols in the synthetic
        // corpus. Widen it to BF_ALL the same way the native and Android
        // runners do, so the four readers face the same format list.
        do {
            let settings = try cvr.getSimplifiedSettings("ReadBarcodes_Default")
            settings.barcodeSettings?.barcodeFormatIds = DynamsoftCaptureVisionBundle.BarcodeFormat(rawValue: 0xFFFF_FFFE_FFFF_FFFF)
            try cvr.updateSettings("ReadBarcodes_Default", settings: settings)
        } catch {
            print("Dynamsoft settings error: \(error.localizedDescription)")
        }
    }

    func onLicenseVerified(_ isSuccess: Bool, error: Error?) {
        licenseVerified = isSuccess
        if !isSuccess {
            print("Dynamsoft license error: \(error?.localizedDescription ?? "Unknown error")")
        }
    }

    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        let result = cvr.captureFromImage(image, templateName: "ReadBarcodes_Default")
        return parseResult(result, imageSize: image.size)
    }

    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = CIContext.shared.createCGImage(ciImage, from: ciImage.extent) else {
            throw DetectionError.invalidImage
        }
        return try await detectBarcodes(in: UIImage(cgImage: cgImage))
    }

    private func parseResult(_ result: CapturedResult, imageSize: CGSize) -> [BarcodeInfo] {
        guard let items = result.decodedBarcodesResult?.items else { return [] }
        return items.map { item in
            // DSQuadrilateral exposes a pre-computed boundingRect — no need to iterate points.
            let bounds: CGRect? = {
                guard imageSize.width > 0, imageSize.height > 0 else { return nil }
                let br = item.location.boundingRect
                return CGRect(
                    x: br.minX / imageSize.width,
                    y: br.minY / imageSize.height,
                    width: br.width / imageSize.width,
                    height: br.height / imageSize.height)
            }()
            return BarcodeInfo(format: item.formatString ?? "", text: item.text ?? "", decodeTimeMs: 0, normalizedBounds: bounds)
        }
    }
}

#else

class DynamsoftBarcodeDetector: BarcodeDetector {
    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        throw DetectionError.notInitialized
    }
    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        throw DetectionError.notInitialized
    }
}

#endif

// MARK: - MLKit Barcode Detector

#if canImport(MLKitBarcodeScanning)
import MLKitBarcodeScanning
import MLKitVision

class MLKitBarcodeDetector: BarcodeDetector {

    private let scanner: MLKitBarcodeScanning.BarcodeScanner

    init() {
        let options = BarcodeScannerOptions(formats: .all)
        scanner = MLKitBarcodeScanning.BarcodeScanner.barcodeScanner(options: options)
    }

    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        let visionImage = VisionImage(image: image)
        visionImage.orientation = image.imageOrientation
        let imgW = image.size.width
        let imgH = image.size.height
        return try await withCheckedThrowingContinuation { continuation in
            scanner.process(visionImage) { [weak self] barcodes, error in
                guard let self = self else {
                    continuation.resume(returning: [])
                    return
                }
                if let error = error {
                    continuation.resume(throwing: DetectionError.detectionFailed(error.localizedDescription))
                    return
                }
                let results = (barcodes ?? []).map { barcode -> BarcodeInfo in
                    var bounds: CGRect?
                    if imgW > 0 && imgH > 0 {
                        let f = barcode.frame
                        bounds = CGRect(x: f.minX / imgW, y: f.minY / imgH,
                                        width: f.width / imgW, height: f.height / imgH)
                    }
                    return BarcodeInfo(
                        format: self.mapFormat(barcode.format),
                        text: barcode.rawValue ?? barcode.displayValue ?? "",
                        decodeTimeMs: 0,
                        normalizedBounds: bounds
                    )
                }
                continuation.resume(returning: results)
            }
        }
    }

    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = CIContext.shared.createCGImage(ciImage, from: ciImage.extent) else {
            throw DetectionError.invalidImage
        }
        return try await detectBarcodes(in: UIImage(cgImage: cgImage))
    }

    private func mapFormat(_ format: MLKitBarcodeScanning.BarcodeFormat) -> String {
        if format.contains(.qrCode)    { return "QR_CODE" }
        if format.contains(.code128)   { return "CODE_128" }
        if format.contains(.code39)    { return "CODE_39" }
        if format.contains(.code93)    { return "CODE_93" }
        if format.contains(.codaBar)   { return "CODABAR" }
        if format.contains(.dataMatrix){ return "DATA_MATRIX" }
        if format.contains(.EAN13)     { return "EAN_13" }
        if format.contains(.EAN8)      { return "EAN_8" }
        if format.contains(.ITF)       { return "ITF" }
        if format.contains(.UPCA)      { return "UPC_A" }
        if format.contains(.UPCE)      { return "UPC_E" }
        if format.contains(.PDF417)    { return "PDF417" }
        if format.contains(.aztec)     { return "AZTEC" }
        return "UNKNOWN"
    }
}

#else

class MLKitBarcodeDetector: BarcodeDetector {
    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        throw DetectionError.notInitialized
    }
    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        throw DetectionError.notInitialized
    }
}

#endif

// MARK: - Apple Vision Barcode Detector
class VisionBarcodeDetector: BarcodeDetector {
    
    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        guard let cgImage = image.cgImage else {
            throw DetectionError.invalidImage
        }
        
        return try await withCheckedThrowingContinuation { continuation in
            let request = VNDetectBarcodesRequest { request, error in
                if let error = error {
                    continuation.resume(throwing: DetectionError.detectionFailed(error.localizedDescription))
                    return
                }
                
                guard let results = request.results as? [VNBarcodeObservation] else {
                    continuation.resume(returning: [])
                    return
                }
                
                let barcodes = results.map { observation -> BarcodeInfo in
                    let format = self.mapSymbology(observation.symbology)
                    let text = observation.payloadStringValue ?? ""
                    // boundingBox origin is bottom-left; flip Y for top-left screen coords
                    let bb = observation.boundingBox
                    let bounds = CGRect(x: bb.minX, y: 1.0 - bb.maxY, width: bb.width, height: bb.height)
                    return BarcodeInfo(format: format, text: text, decodeTimeMs: 0, normalizedBounds: bounds)
                }
                
                continuation.resume(returning: barcodes)
            }
            
            // Request all supported barcode types
            request.symbologies = [
                .qr,
                .code128,
                .code39,
                .code93,
                .ean8,
                .ean13,
                .upce,
                .pdf417,
                .aztec,
                .dataMatrix,
                .codabar,
                .itf14
            ]
            
            let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
            
            do {
                try handler.perform([request])
            } catch {
                continuation.resume(throwing: DetectionError.detectionFailed(error.localizedDescription))
            }
        }
    }
    
    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        return try await withCheckedThrowingContinuation { continuation in
            let request = VNDetectBarcodesRequest { request, error in
                if let error = error {
                    continuation.resume(throwing: DetectionError.detectionFailed(error.localizedDescription))
                    return
                }
                
                guard let results = request.results as? [VNBarcodeObservation] else {
                    continuation.resume(returning: [])
                    return
                }
                
                let barcodes = results.map { observation -> BarcodeInfo in
                    let format = self.mapSymbology(observation.symbology)
                    let text = observation.payloadStringValue ?? ""
                    // boundingBox origin is bottom-left; flip Y for top-left screen coords
                    let bb = observation.boundingBox
                    let bounds = CGRect(x: bb.minX, y: 1.0 - bb.maxY, width: bb.width, height: bb.height)
                    return BarcodeInfo(format: format, text: text, decodeTimeMs: 0, normalizedBounds: bounds)
                }
                
                continuation.resume(returning: barcodes)
            }
            
            request.symbologies = [
                .qr,
                .code128,
                .code39,
                .code93,
                .ean8,
                .ean13,
                .upce,
                .pdf417,
                .aztec,
                .dataMatrix,
                .codabar,
                .itf14
            ]
            
            let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
            
            do {
                try handler.perform([request])
            } catch {
                continuation.resume(throwing: DetectionError.detectionFailed(error.localizedDescription))
            }
        }
    }
    
    private func mapSymbology(_ symbology: VNBarcodeSymbology) -> String {
        switch symbology {
        case .qr:
            return "QR_CODE"
        case .code128:
            return "CODE_128"
        case .code39:
            return "CODE_39"
        case .code93:
            return "CODE_93"
        case .ean8:
            return "EAN_8"
        case .ean13:
            return "EAN_13"
        case .upce:
            return "UPC_E"
        case .pdf417:
            return "PDF417"
        case .aztec:
            return "AZTEC"
        case .dataMatrix:
            return "DATA_MATRIX"
        case .codabar:
            return "CODABAR"
        case .itf14:
            return "ITF"
        default:
            return "UNKNOWN"
        }
    }
}

// MARK: - ZXing-CPP Barcode Detector

#if canImport(ZXingCpp)
import ZXingCpp
import CoreVideo

class ZXingCppBarcodeDetector: BarcodeDetector {

    private let reader: ZXIBarcodeReader

    /// `options` mirrors the C++ runner in `datasets-from-dynamsoft/synthetic-benchmark`:
    /// all formats, try harder / rotate / invert / downscale, local-average binarizer,
    /// plain text, and a symbol cap instead of the wrapper's default of 255.
    init(maxNumberOfSymbols: Int = BenchmarkConfig.zxingMaxSymbols) {
        let options = ZXIReaderOptions()
        options.formats = BenchmarkConfig.zxingFormats.map { NSNumber(value: $0.rawValue) }
        options.tryHarder = true
        options.tryRotate = true
        options.tryInvert = true
        options.tryDownscale = true
        options.isPure = false
        options.binarizer = .localAverage
        options.maxNumberOfSymbols = maxNumberOfSymbols
        options.eanAddOnSymbol = .read
        options.textMode = .plain
        reader = ZXIBarcodeReader(options: options)
    }

    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        guard let cgImage = image.cgImage else {
            throw DetectionError.invalidImage
        }
        let results = try reader.read(cgImage)
        return map(results, width: cgImage.width, height: cgImage.height)
    }

    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        let results = try reader.read(pixelBuffer)
        return map(results, width: CVPixelBufferGetWidth(pixelBuffer), height: CVPixelBufferGetHeight(pixelBuffer))
    }

    private func map(_ results: [ZXIResult], width: Int, height: Int) -> [BarcodeInfo] {
        return results.map { r in
            var bounds: CGRect?
            if width > 0 && height > 0 {
                let pos = r.position
                let xs = [pos.topLeft.x, pos.topRight.x, pos.bottomRight.x, pos.bottomLeft.x]
                let ys = [pos.topLeft.y, pos.topRight.y, pos.bottomRight.y, pos.bottomLeft.y]
                if let minX = xs.min(), let maxX = xs.max(),
                   let minY = ys.min(), let maxY = ys.max() {
                    bounds = CGRect(
                        x: CGFloat(minX) / CGFloat(width),
                        y: CGFloat(minY) / CGFloat(height),
                        width: CGFloat(maxX - minX) / CGFloat(width),
                        height: CGFloat(maxY - minY) / CGFloat(height)
                    )
                }
            }
            return BarcodeInfo(format: mapFormat(r.format), text: r.text, decodeTimeMs: 0, normalizedBounds: bounds)
        }
    }

    // ZXIFormat is an unscoped C NS_ENUM, so the cases import unchanged. Switching
    // on the cases instead of rawValue keeps this mapping valid across zxing-cpp
    // releases - 3.x inserted Telepen and split the DataBar variants, which moved
    // every constant after them.
    private func mapFormat(_ format: ZXIFormat) -> String {
        switch format {
        case .AZTEC:        return "AZTEC"
        case .CODABAR:      return "CODABAR"
        case .CODE_39:      return "CODE_39"
        case .CODE_93:      return "CODE_93"
        case .CODE_128:     return "CODE_128"
        case .DATA_BAR:     return "DATA_BAR"
        case .DATA_BAR_EXPANDED:          return "DATA_BAR_EXPANDED"
        case .DATA_BAR_STACKED:           return "DATA_BAR_STACKED"
        case .DATA_BAR_EXPANDED_STACKED:  return "DATA_BAR_EXPANDED_STACKED"
        case .DATA_BAR_LIMITED:           return "DATA_BAR_LIMITED"
        case .DATA_MATRIX:  return "DATA_MATRIX"
        case .DX_FILM_EDGE: return "DX_FILM_EDGE"
        case .TELEPEN:      return "TELEPEN"
        case .EAN_8:        return "EAN_8"
        case .EAN_13:       return "EAN_13"
        case .ITF:          return "ITF"
        case .MAXICODE:     return "MAXICODE"
        case .PDF_417:      return "PDF_417"
        case .QR_CODE:      return "QR_CODE"
        case .MICRO_QR_CODE: return "MICRO_QR"
        case .RMQR_CODE:    return "RMQR"
        case .UPC_A:        return "UPC_A"
        case .UPC_E:        return "UPC_E"
        default:            return "UNKNOWN"
        }
    }
}

#else

class ZXingCppBarcodeDetector: BarcodeDetector {
    func detectBarcodes(in image: UIImage) async throws -> [BarcodeInfo] {
        throw DetectionError.notInitialized
    }
    func detectBarcodes(in pixelBuffer: CVPixelBuffer) async throws -> [BarcodeInfo] {
        throw DetectionError.notInitialized
    }
}

#endif

// MARK: - Video Frame Extractor
class VideoFrameExtractor {
    
    static func extractFrames(from videoURL: URL, interval: Double) async throws -> [UIImage] {
        let asset = AVAsset(url: videoURL)
        let duration = try await asset.load(.duration)
        let durationSeconds = CMTimeGetSeconds(duration)
        
        let imageGenerator = AVAssetImageGenerator(asset: asset)
        imageGenerator.appliesPreferredTrackTransform = true
        imageGenerator.requestedTimeToleranceBefore = .zero
        imageGenerator.requestedTimeToleranceAfter = .zero
        
        var frames: [UIImage] = []
        var currentTime: Double = 0
        
        while currentTime < durationSeconds {
            let cmTime = CMTime(seconds: currentTime, preferredTimescale: 600)
            
            do {
                let cgImage = try imageGenerator.copyCGImage(at: cmTime, actualTime: nil)
                let image = UIImage(cgImage: cgImage)
                frames.append(image)
            } catch {
                print("Failed to extract frame at \(currentTime)s: \(error)")
            }
            
            currentTime += interval
        }
        
        return frames
    }
}
