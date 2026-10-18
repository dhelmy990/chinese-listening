#pragma once

#include <cmath>
#include <codecvt>
#include <locale>
#include <stdexcept>
#include <string>
#include <vector>

namespace ning {
inline void validate_mel_shape(size_t length, int frames) {
    if (frames != 3000 || length != 128u * 3000u)
        throw std::invalid_argument("Turbo mel input must have shape [1, 128, 3000]");
}

inline void validate_finite(const std::vector<float>& values) {
    for (float value : values)
        if (!std::isfinite(value))
            throw std::invalid_argument("Audio features must be finite");
}

inline void validate_prompt(const std::vector<int>& prompt) {
    if (prompt.empty() || prompt.size() >= 448)
        throw std::invalid_argument("Whisper prompt must contain 1 to 447 tokens");
    for (int token : prompt)
        if (token < 0 || token >= 51866)
            throw std::invalid_argument("Whisper prompt token is outside the Turbo vocabulary");
}

// JNI's modified UTF-8 corrupts supplementary characters in SentencePiece tokens.
inline std::string to_utf8(const std::u16string& text) {
    return std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t>{}.to_bytes(text);
}

inline std::u16string from_utf8(const std::string& text) {
    return std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t>{}.from_bytes(text);
}
} // namespace ning
