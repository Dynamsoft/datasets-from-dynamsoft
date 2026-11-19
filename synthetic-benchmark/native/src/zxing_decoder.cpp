#include "decoder_adapter.h"
#include "normalization.h"

#include <BarcodeFormat.h>
#include <ImageView.h>
#include <ReadBarcode.h>
#include <ReaderOptions.h>
#include <Version.h>

#include <algorithm>
#include <chrono>
#include <stdexcept>

namespace bench {
namespace {

class ZxingDecoder final : public IDecoderAdapter {
public:
    ZxingDecoder(int max_symbols, const std::string& formats)
    {
        const auto selected = formats.empty() ? ZXing::BarcodeFormats{ZXing::BarcodeFormat::All}
                                              : ZXing::BarcodeFormatsFromString(formats);
        if (selected.empty()) throw std::invalid_argument("ZXing format list is empty");
        options_.formats(selected)
            .tryHarder(true).tryRotate(true).tryInvert(true).tryDownscale(true)
            .binarizer(ZXing::Binarizer::LocalAverage).isPure(false)
            .maxNumberOfSymbols(static_cast<std::uint8_t>(std::clamp(max_symbols, 1, 255)))
            .validateOptionalChecksum(false).returnErrors(false)
            .eanAddOnSymbol(ZXing::EanAddOnSymbol::Read).textMode(ZXing::TextMode::Plain);
    }

    std::string name() const override { return "zxing-cpp"; }
    std::string version() const override { return ZXING_VERSION_STR; }

    DecodeRun decode(const ImageBuffer& image) override
    {
        DecodeRun run;
        try {
            const ZXing::ImageView view(image.rgb.data(), image.width, image.height,
                                        ZXing::ImageFormat::RGB, image.stride);
            const auto begin = std::chrono::steady_clock::now();
            const auto barcodes = ZXing::ReadBarcodes(view, options_);
            run.decode_time = std::chrono::steady_clock::now() - begin;
            for (const auto& barcode : barcodes) {
                if (!barcode.isValid()) continue;
                DecodedBarcode result;
                result.canonical_format = canonicalFormat(ZXing::ToString(barcode.format()));
                if (result.canonical_format == "CODE_128" && barcode.symbologyIdentifier() == "]C1")
                    result.canonical_format = "GS1_128";
                result.raw_bytes.assign(barcode.bytes().begin(), barcode.bytes().end());
                result.text = barcode.text();
                run.results.push_back(std::move(result));
            }
        } catch (const std::exception& e) {
            run.error = e.what();
        }
        return run;
    }

private:
    ZXing::ReaderOptions options_;
};

} // namespace

std::unique_ptr<IDecoderAdapter> createZxingDecoder(int max_symbols, const std::string& formats)
{
    return std::make_unique<ZxingDecoder>(max_symbols, formats);
}

} // namespace bench
