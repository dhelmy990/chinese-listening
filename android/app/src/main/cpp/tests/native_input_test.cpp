#include "../native_input.h"

#include <cassert>
#include <limits>

template <typename F> void rejects(F call) {
    bool rejected = false;
    try { call(); } catch (const std::invalid_argument&) { rejected = true; }
    assert(rejected);
}

int main() {
    ning::validate_mel_shape(128 * 3000, 3000);
    rejects([] { ning::validate_mel_shape(128 * 2999, 3000); });
    rejects([] { ning::validate_mel_shape(0, 0); });
    rejects([] { ning::validate_mel_shape(128 * 3001, 3001); });
    ning::validate_finite({0.0f, -2.0f, 1.0f});
    rejects([] { ning::validate_finite({std::numeric_limits<float>::quiet_NaN()}); });
    rejects([] { ning::validate_finite({std::numeric_limits<float>::infinity()}); });
    ning::validate_prompt({50258, 50260, 50360, 50364});
    rejects([] { ning::validate_prompt({}); });
    rejects([] { ning::validate_prompt({-1}); });
    rejects([] { ning::validate_prompt({51866}); });
    rejects([] { ning::validate_prompt(std::vector<int>(448, 1)); });
    const std::u16string unicode = u"▁中文\U0001f600";
    const std::string utf8 = "\xe2\x96\x81\xe4\xb8\xad\xe6\x96\x87\xf0\x9f\x98\x80";
    assert(ning::to_utf8(unicode) == utf8);
    assert(ning::from_utf8(utf8) == unicode);
}
