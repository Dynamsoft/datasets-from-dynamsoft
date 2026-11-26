//
//  BarcodeBenchmarkApp.swift
//  BarcodeBenchmark
//
//  iOS Barcode Benchmark App - Compares Dynamsoft, MLKit, and Apple Vision
//

import SwiftUI

@main
struct BarcodeBenchmarkApp: App {
    @StateObject private var viewModel = BenchmarkViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(viewModel)
        }
    }
}
