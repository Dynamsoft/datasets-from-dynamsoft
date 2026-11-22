#include "normalization.h"

#include <cctype>
#include <unordered_map>

namespace bench {
std::string canonicalFormat(std::string_view value)
{
    static const std::unordered_map<std::string, std::string> names = {
        {"AZTECCODE", "AZTEC"}, {"CODE128", "CODE_128"}, {"GS1128", "GS1_128"},
        {"CODE39", "CODE_39"}, {"CODE39EXTENDED", "CODE_39"}, {"CODE39STD", "CODE_39"},
        {"CODE93", "CODE_93"}, {"DATAMATRIX", "DATA_MATRIX"}, {"EAN13", "EAN_13"},
        {"EAN13UPCA", "EAN_13"}, {"EAN8", "EAN_8"},
        {"IATA2OF5", "IATA_2_OF_5"}, {"IATA25", "IATA_2_OF_5"}, {"INTERLEAVED2OF5", "ITF"},
        {"MICROQR", "MICRO_QR"}, {"MICROQRCODE", "MICRO_QR"}, {"MSI", "MSI_CODE"},
        {"MSICODE", "MSI_CODE"}, {"MSIPLESSEY", "MSI_CODE"}, {"PDF417", "PDF_417"},
        {"PHARMACODEONETRACK", "PHARMACODE_ONE_TRACK"}, {"QR", "QR_CODE"}, {"QRCODE", "QR_CODE"},
        {"RM4SCC", "ROYAL_MAIL"}, {"ROYALMAIL4STATE", "ROYAL_MAIL"}, {"ROYALMAIL", "ROYAL_MAIL"},
        {"UPCA", "UPC_A"}, {"UPCE", "UPC_E"}, {"USPSINTELLIGENTMAIL", "USPS_INTELLIGENT_MAIL"},
    };
    std::string key;
    for (const unsigned char c : value)
        if (std::isalnum(c)) key += static_cast<char>(std::toupper(c));
    const auto found = names.find(key);
    return found == names.end() ? key : found->second;
}
}
