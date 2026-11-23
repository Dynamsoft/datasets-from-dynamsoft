#include "decoder_adapter.h"
#include "hash.h"
#include "image_loader.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>
#include <sys/utsname.h>
#include <unistd.h>

namespace fs = std::filesystem;
using json = nlohmann::json;
using Clock = std::chrono::steady_clock;

namespace {
constexpr const char* template_name = "ReadBarcodes_Default";
constexpr int warmup_images = 24;
constexpr int max_symbols = 255;
using Decoders = std::array<std::unique_ptr<bench::IDecoderAdapter>, 3>;
using FormatSets = std::array<std::set<std::string>, 3>;

std::string requireLicense(const char* name)
{
    const char* value = std::getenv(name);
    if (!value || !*value) throw std::runtime_error(std::string("Missing ") + name);
    return value;
}

json loadJson(const fs::path& path)
{
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Cannot open " + path.string());
    return json::parse(input);
}

void saveJson(const fs::path& path, const json& value)
{
    std::ofstream output(path, std::ios::binary);
    output.exceptions(std::ios::badbit | std::ios::failbit);
    output << value.dump(2) << '\n';
    output.close();
}

std::pair<std::string, FormatSets> configure(const fs::path& plans, const fs::path& reference,
                                             const fs::path& output, const json& inventory)
{
    const auto symbologies = loadJson(plans);
    FormatSets logical, native;
    for (const auto& [format, count] : inventory.at("by_format").items()) {
        const auto& entry = symbologies.at(format);
        for (std::size_t reader = 0; reader < logical.size(); ++reader) {
            if (entry.at(reader).is_null()) continue;
            logical[reader].insert(format);
            native[reader].insert(entry.at(reader).get<std::string>());
        }
    }
    std::string zxing;
    for (const auto& format : native[0]) {
        if (!zxing.empty()) zxing += ',';
        zxing += format;
    }
    auto dbr = loadJson(reference);
    auto& tasks = dbr.at("BarcodeReaderTaskSettingOptions");
    const auto task = std::find_if(tasks.begin(), tasks.end(), [](const auto& entry) {
        return entry.at("Name") == "task-read-barcodes";
    });
    if (task == tasks.end()) throw std::runtime_error("Reference DBR preset task is missing");
    (*task)["BarcodeFormatIds"] = json::array({"BF_ALL"});
    saveJson(output / "dynamsoft-settings.json", dbr);
    saveJson(output / "scandit-settings.json", {{"multi_scan", true}, {"color_inverted", true},
        {"max_locations_per_frame_cap", 64}, {"symbologies", native[2]}});
    saveJson(output / "symbologies.json", symbologies);
    return {zxing, logical};
}

std::string bytesHex(const std::vector<std::uint8_t>& bytes)
{
    constexpr char digits[] = "0123456789abcdef";
    std::string result;
    result.reserve(bytes.size() * 2);
    for (const auto byte : bytes) {
        result += digits[byte >> 4];
        result += digits[byte & 15];
    }
    return result;
}

bench::ImageBuffer loadSample(const fs::path& dataset, const json& sample)
{
    const auto sample_id = sample.at("sample_id").get<std::string>();
    const fs::path relative = sample.at("relative_path").get<std::string>();
    if (relative.is_absolute() || std::find(relative.begin(), relative.end(), "..") != relative.end())
        throw std::runtime_error("Unsafe image path for " + sample_id);
    bench::ImageBuffer image;
    std::string error;
    if (!bench::loadImage(dataset / relative, image, error))
        throw std::runtime_error("Cannot read " + sample_id + ": " + error);
    if (sample.at("width") != image.width || sample.at("height") != image.height)
        throw std::runtime_error("Wrong dimensions for " + sample_id);
    return image;
}

std::string firstValue(const char* path, const std::string& prefix)
{
    std::ifstream input(path);
    for (std::string line; std::getline(input, line);) {
        if (!line.starts_with(prefix)) continue;
        const auto start = line.find_first_not_of(" \t\"", prefix.size());
        const auto end = line.find_last_not_of(" \t\"");
        if (start != std::string::npos && end >= start) return line.substr(start, end - start + 1);
    }
    return {};
}

void shutdownDecoders(Decoders& decoders, int status)
{
    std::mutex mutex;
    std::condition_variable condition;
    bool finished = false;
    // The Scandit 8.7.1 context release can block in the tested Linux container.
    // This process has closed its output files before reaching SDK teardown.
    std::thread watchdog([&] {
        std::unique_lock lock(mutex);
        if (!condition.wait_for(lock, std::chrono::seconds(15), [&] { return finished; })) {
            constexpr char message[] = "SDK shutdown exceeded 15 seconds. Exiting with the benchmark result status.\n";
            [[maybe_unused]] const auto written = ::write(STDERR_FILENO, message, sizeof(message) - 1);
            std::_Exit(status);
        }
    });
    for (auto& decoder : decoders) decoder.reset();
    {
        std::lock_guard lock(mutex);
        finished = true;
    }
    condition.notify_one();
    watchdog.join();
}

int run(const fs::path& dataset, const fs::path& output, const fs::path& symbologies,
        const fs::path& reference, Decoders& decoders)
{
    const auto dbr_key = requireLicense("DYNAMSOFT_LICENSE_KEY");
    const auto manifest_path = dataset / "manifest.jsonl";
    std::ifstream manifest(manifest_path, std::ios::binary);
    if (!manifest) throw std::runtime_error("Cannot open manifest: " + manifest_path.string());
    const auto inventory = loadJson(dataset / "inventory.json");
    const auto expected = inventory.at("images").get<std::size_t>();
    const auto manifest_hash = bench::sha256File(manifest_path);
    if (inventory.at("manifest_sha256") != manifest_hash)
        throw std::runtime_error("Manifest hash differs from inventory");
    if (!fs::create_directories(output)) throw std::runtime_error("Output already exists: " + output.string());

    const auto [formats, supported] = configure(symbologies, reference, output, inventory);
    int max_dataset_symbols = 0;
    for (const auto& [count, frames] : inventory.at("by_symbol_count").items())
        if (frames.get<std::size_t>() > 0) max_dataset_symbols = std::max(max_dataset_symbols, std::stoi(count));
    decoders[1] = bench::createDynamsoftDecoder((output / "dynamsoft-settings.json").string(), template_name,
                                               dbr_key, -1, true);
    fs::create_directory(output / "scandit-state");
    decoders[0] = bench::createZxingDecoder(max_symbols, formats);
    decoders[2] = bench::createScanditDecoder((output / "scandit-settings.json").string(),
                                             requireLicense("SCANDIT_LICENSE_KEY"),
                                             (output / "scandit-state").string(), max_dataset_symbols);
    if (decoders[2]->configuration() != "multi-scan")
        throw std::runtime_error("Scandit Linux requires tracking for a comparable multi-code run");
    const std::array<std::size_t, 3> order{0, 1, 2};

    json decoder_metadata = json::object();
    for (const auto reader : order) {
        const auto& decoder = decoders[reader];
        std::cout << decoder->name() << " " << decoder->version() << ' ' << decoder->configuration() << std::endl;
        decoder_metadata[decoder->name()] = {{"version", decoder->version()},
                                             {"runtime_configuration", decoder->configuration()},
                                             {"supported_formats", supported[reader]}};
    }
    decoder_metadata["dynamsoft-dbr"]["settings"] = {{"preset", template_name},
        {"expected_barcodes_count", 0}, {"barcode_format_ids", "BF_ALL"},
        {"config_sha256", bench::sha256File(output / "dynamsoft-settings.json")}};
    decoder_metadata["zxing-cpp"]["settings"] = {{"formats", formats}, {"max_symbols", max_symbols},
        {"try_harder", true}, {"try_rotate", true}, {"try_invert", true}, {"try_downscale", true},
        {"binarizer", "LocalAverage"}, {"text_mode", "Plain"}};
    decoder_metadata["scandit-linux"]["settings"] = {{"preset", "SC_PRESET_HIGH_EFFORT"},
        {"max_locations_per_frame", std::clamp(max_dataset_symbols * 2 + 8, 8, 64)}, {"color_inverted", true},
        {"config_sha256", bench::sha256File(output / "scandit-settings.json")}};

    std::array<std::size_t, 3> warmup_successes{};
    int calls = 0;
    for (std::string line; calls < warmup_images && std::getline(manifest, line);) {
        const auto sample = json::parse(line);
        const auto image = loadSample(dataset, sample);
        for (const auto index : order) {
            const auto attempt = decoders[index]->decode(image);
            warmup_successes[index] += !attempt.error;
        }
        ++calls;
    }
    if (!calls) throw std::runtime_error("No selected images");
    for (const auto index : order)
        if (!warmup_successes[index]) throw std::runtime_error(decoders[index]->name() + " failed every warm-up call");
    manifest.clear();
    manifest.seekg(0);
    const auto temporary_results = output / "results.jsonl.partial";
    std::ofstream results(temporary_results, std::ios::binary);
    results.exceptions(std::ios::badbit | std::ios::failbit);
    std::mt19937 rng(20261119);
    std::size_t count = 0, total = 0;
    for (std::string line; std::getline(manifest, line);) {
        ++total;
        const auto sample = json::parse(line);
        const auto sample_id = sample.at("sample_id").get<std::string>();
        const auto begin = Clock::now();
        const auto image = loadSample(dataset, sample);
        const auto load_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - begin).count();
        auto frame_order = order;
        std::shuffle(frame_order.begin(), frame_order.end(), rng);
        for (const auto index : frame_order) {
            const auto& decoder = decoders[index];
            const auto decoded = decoder->decode(image);
            json predictions = json::array();
            for (const auto& item : decoded.results)
                predictions.push_back({{"format", item.canonical_format}, {"text", item.text},
                    {"raw_bytes_hex", bytesHex(item.raw_bytes)}});
            const json row = {{"sample_id", sample_id}, {"image_load_ns", load_ns},
                {"decoder", decoder->name()}, {"decode_ns", decoded.decode_time.count()},
                {"error", decoded.error ? json(*decoded.error) : json(nullptr)}, {"predictions", predictions}};
            results << row.dump(-1, ' ', false, json::error_handler_t::replace) << '\n';
        }
        if (++count % 250 == 0) {
            results.flush();
            std::cout << "Decoded " << count << " / " << expected << " images" << std::endl;
        }
    }
    if (inventory.at("images") != total) throw std::runtime_error("Image count differs from inventory");
    if (count != expected) throw std::runtime_error("Selected image count differs from inventory");
    results.close();
    fs::rename(temporary_results, output / "results.jsonl");
    struct utsname platform{};
    if (uname(&platform) != 0) throw std::runtime_error("Cannot read platform information");
    const json environment = {{"os", firstValue("/etc/os-release", "PRETTY_NAME=")}, {"kernel", platform.release},
        {"architecture", platform.machine}, {"processor", firstValue("/proc/cpuinfo", "model name\t:")},
        {"logical_processors", sysconf(_SC_NPROCESSORS_ONLN)}, {"compiler", __VERSION__}};
    json run_metadata = {{"schema", "synthetic-native-run-v2"}, {"dataset_schema", inventory.at("schema")},
        {"selection", "all"}, {"source_images", total},
        {"manifest_sha256", manifest_hash},
        {"results_sha256", bench::sha256File(output / "results.jsonl")}, {"images", count},
        {"warmup_calls_per_sdk", calls}, {"order_seed", 20261119},
        {"decoder_processes", 1}, {"repetitions", 1}, {"environment", environment}, {"decoders", decoder_metadata}};
    saveJson(output / "run.json", run_metadata);
    std::cout << "Complete: " << count << " images across " << order.size() << " readers" << std::endl;
    return 0;
}
}  // namespace

int main(int argc, char** argv)
{
    if (argc != 5) {
        std::cerr << "Usage: synthetic_benchmark DATASET OUTPUT SYMBOLOGIES_JSON DBR_REFERENCE_JSON\n";
        return 2;
    }
    Decoders decoders;
    int status = 1;
    try {
        status = run(argv[1], argv[2], argv[3], argv[4], decoders);
    } catch (const std::exception& error) {
        std::cerr << error.what() << std::endl;
    }
    shutdownDecoders(decoders, status);
    return status;
}
