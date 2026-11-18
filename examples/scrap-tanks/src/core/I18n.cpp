// ---------------------------------------------------------------------------
// I18n.cpp
// Purpose : Implementation of lookup, CLDR plurals, @clean variants, the word mask and the pseudo-locale
//           (see I18n.hpp).
// Usage   : compiled into the `core` library; call through I18n.hpp.
// Notes   : Works on UTF-8 bytes: '{', '}' and '%' are ASCII and never appear inside a multi-byte
//           character, so scanning bytes is safe; lengths count characters (code points), not bytes.
//           The accented look-alikes are written as UTF-8 byte escapes so the result does not depend on
//           the compiler's source or execution character set.
//           The word mask decodes UTF-8 to code points itself (the reference counts code points).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plural families, the .other fallback per
//           locale, @clean lookups, mask_words and mature_words (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compile_words, mask_word_set, WordCache (#207)
// ---------------------------------------------------------------------------
#include "core/I18n.hpp"

#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <set>
#include <sstream>
#include <tuple>
#include <utility>

namespace core {

namespace {

// The base language of a locale tag: "fr-CA" -> "fr", "pt_BR" -> "pt".
std::string base_language(const std::string& locale) {
    const std::string first = locale.substr(0, locale.find('-'));
    return first.substr(0, first.find('_'));
}

// Replaces {name} with args[name]; unknown placeholders and lone braces stay as they are.
std::string fill(const std::string& text, const TrArgs& args) {
    std::string out;
    std::size_t i = 0;
    while (i < text.size()) {
        if (text[i] == '{') {
            const std::size_t j = text.find('}', i);
            if (j != std::string::npos) {
                const auto it = args.find(text.substr(i + 1, j - i - 1));
                if (it != args.end()) {
                    out += it->second;
                    i = j + 1;
                    continue;
                }
            }
        }
        out += text[i];
        ++i;
    }
    return out;
}

// The accented look-alike of an ASCII letter (UTF-8), or nullptr for characters that stay as they are.
const char* pseudo_char(char c) {
    switch (c) {
        case 'a': return "\xC3\xA1";  // a acute
        case 'e': return "\xC3\xA9";
        case 'i': return "\xC3\xAD";
        case 'o': return "\xC3\xB3";
        case 'u': return "\xC3\xBA";
        case 'c': return "\xC3\xA7";  // c cedilla
        case 'n': return "\xC3\xB1";  // n tilde
        case 'y': return "\xC3\xBD";
        case 'A': return "\xC3\x81";
        case 'E': return "\xC3\x89";
        case 'I': return "\xC3\x8D";
        case 'O': return "\xC3\x93";
        case 'U': return "\xC3\x9A";
        case 'C': return "\xC3\x87";
        case 'N': return "\xC3\x91";
        case 'Y': return "\xC3\x9D";
        default: return nullptr;
    }
}

bool is_utf8_continuation(char c) {
    return (static_cast<unsigned char>(c) & 0xC0) == 0x80;
}

}  // namespace

std::size_t utf8_length(std::string_view text) {
    std::size_t n = 0;
    for (const char c : text) {
        n += is_utf8_continuation(c) ? 0 : 1;
    }
    return n;
}

std::vector<std::string> locale_chain(const std::string& locale, const std::string& fallback) {
    std::vector<std::string> chain;
    for (const std::string& loc : {locale, base_language(locale), fallback}) {
        bool seen = false;
        for (const std::string& c : chain) {
            seen = seen || c == loc;
        }
        if (!loc.empty() && !seen) {
            chain.push_back(loc);
        }
    }
    return chain;
}

namespace {

// One table's text for key: key@clean first when clean is on, else key; nullptr when neither.
const std::string* pick(const StringTables& tables, const std::string& loc, const std::string& key, bool clean) {
    const auto table = tables.find(loc);
    if (table == tables.end()) {
        return nullptr;
    }
    if (clean) {
        const auto c = table->second.find(key + kCleanSuffix);
        if (c != table->second.end()) {
            return &c->second;
        }
    }
    const auto entry = table->second.find(key);
    return entry != table->second.end() ? &entry->second : nullptr;
}

std::string finish(const std::string& text, const TrArgs& args, bool clean, const WordSet& words) {
    std::string out = fill(text, args);
    return clean && !words.empty() ? mask_word_set(out, words) : out;
}

// CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES)
const std::map<std::string, std::string>& plural_languages() {
    static const std::map<std::string, std::string> m = {
        {"other", "ja zh ko vi th id ms lo my km yo ig jv su"},
        {"one", "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr"},
        {"zero_one", "hi bn fa gu kn hy"}, {"one_many", "es it ca"}, {"zero_one_many", "fr pt"},
        {"one_21", "is mk"}, {"fil", "fil tl"}, {"east_slavic", "ru uk be"}, {"pl", "pl"}, {"cs", "cs sk"},
        {"lt", "lt"}, {"balkan", "hr sr bs"}, {"ro", "ro mo"}, {"lv", "lv"}, {"he", "he"}, {"sl", "sl"},
        {"ga", "ga"}, {"ar", "ar"}, {"cy", "cy"},
    };
    return m;
}

// The rule family: the full locale (pt-PT: European Portuguese) first, then its language, then English's rule.
std::string plural_family(const std::string& locale) {
    std::string norm;
    for (const char c : locale) {
        norm += c == '_' ? '-' : static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    if (norm == "pt-pt" || norm.rfind("pt-pt-", 0) == 0) {
        return "one_many";
    }
    const std::string lang = norm.substr(0, norm.find('-'));
    for (const auto& [fam, langs] : plural_languages()) {
        std::istringstream words(langs);
        std::string w;
        while (words >> w) {
            if (w == lang) {
                return fam;
            }
        }
    }
    return "one";
}

}  // namespace

std::string tr(const StringTables& tables, const std::string& locale, const std::string& key, const TrArgs& args,
               bool clean, const WordList& words) {
    return tr(tables, locale, key, args, clean, clean ? compile_words(words) : WordSet{});
}

std::string tr(const StringTables& tables, const std::string& locale, const std::string& key, const TrArgs& args,
               bool clean, const WordSet& words) {
    for (const std::string& loc : locale_chain(locale)) {
        if (const std::string* text = pick(tables, loc, key, clean)) {
            return finish(*text, args, clean, words);
        }
    }
    return key;
}

std::string plural(const std::string& locale, long long count) {
    const std::string fam = plural_family(locale);
    const long long n = count < 0 ? -count : count;
    const long long m10 = n % 10;
    const long long m100 = n % 100;
    const auto in = [](long long v, long long lo, long long hi) { return v >= lo && v <= hi; };
    if (fam == "other") return "other";
    if (fam == "one") return n == 1 ? "one" : "other";
    if (fam == "zero_one") return n <= 1 ? "one" : "other";
    if (fam == "one_many" || fam == "zero_one_many") {
        if (n == 1 || (n == 0 && fam == "zero_one_many")) return "one";
        return n != 0 && n % 1000000 == 0 ? "many" : "other";
    }
    if (fam == "one_21") return m10 == 1 && m100 != 11 ? "one" : "other";
    if (fam == "fil") return m10 == 4 || m10 == 6 || m10 == 9 ? "other" : "one";
    if (fam == "east_slavic" || fam == "balkan") {
        if (m10 == 1 && m100 != 11) return "one";
        if (in(m10, 2, 4) && !in(m100, 12, 14)) return "few";
        return fam == "east_slavic" ? "many" : "other";
    }
    if (fam == "pl") {
        if (n == 1) return "one";
        return in(m10, 2, 4) && !in(m100, 12, 14) ? "few" : "many";
    }
    if (fam == "cs") return n == 1 ? "one" : in(n, 2, 4) ? "few" : "other";
    if (fam == "lt") {
        if (in(m100, 11, 19)) return "other";
        return m10 == 1 ? "one" : m10 >= 2 ? "few" : "other";
    }
    if (fam == "ro") {
        if (n == 1) return "one";
        return n == 0 || in(m100, 1, 19) ? "few" : "other";
    }
    if (fam == "lv") {
        if (m10 == 0 || in(m100, 11, 19)) return "zero";
        return m10 == 1 ? "one" : "other";
    }
    if (fam == "he") return n == 1 ? "one" : n == 2 ? "two" : "other";
    if (fam == "sl") return m100 == 1 ? "one" : m100 == 2 ? "two" : in(m100, 3, 4) ? "few" : "other";
    if (fam == "ga") return n == 1 ? "one" : n == 2 ? "two" : in(n, 3, 6) ? "few" : in(n, 7, 10) ? "many" : "other";
    if (fam == "ar") {
        if (n == 0) return "zero";
        if (n == 1) return "one";
        if (n == 2) return "two";
        return in(m100, 3, 10) ? "few" : m100 >= 11 ? "many" : "other";
    }
    if (fam == "cy") {
        switch (n) {
            case 0: return "zero";
            case 1: return "one";
            case 2: return "two";
            case 3: return "few";
            case 6: return "many";
            default: return "other";
        }
    }
    return "other";
}

std::string tr_plural(const StringTables& tables, const std::string& locale, const std::string& key, long long n,
                      const TrArgs& args, bool clean, const WordList& words) {
    return tr_plural(tables, locale, key, n, args, clean, clean ? compile_words(words) : WordSet{});
}

std::string tr_plural(const StringTables& tables, const std::string& locale, const std::string& key, long long n,
                      const TrArgs& args, bool clean, const WordSet& words) {
    TrArgs a = args;
    a["n"] = std::to_string(n);
    for (const std::string& loc : locale_chain(locale)) {
        const std::string cat = plural(loc, n);
        const std::string* text = pick(tables, loc, key + "." + cat, clean);
        if (text == nullptr && cat != "other") {
            text = pick(tables, loc, key + ".other", clean);
        }
        if (text != nullptr) {
            return finish(*text, a, clean, words);
        }
    }
    return key + "." + plural(locale, n);
}

// ---- the word mask (#207) ----------------------------------------------------------------------------------
namespace {

// The code point at byte i and how many bytes it takes; a stray byte counts as itself.
std::pair<std::uint32_t, std::size_t> decode_utf8(const std::string& s, std::size_t i) {
    const auto b = static_cast<unsigned char>(s[i]);
    std::size_t len = 1;
    std::uint32_t cp = b;
    if (b >= 0xF0) { len = 4; cp = b & 0x07u; }
    else if (b >= 0xE0) { len = 3; cp = b & 0x0Fu; }
    else if (b >= 0xC0) { len = 2; cp = b & 0x1Fu; }
    if (i + len > s.size()) {
        return {b, 1};
    }
    for (std::size_t k = 1; k < len; ++k) {
        cp = (cp << 6) | (static_cast<unsigned char>(s[i + k]) & 0x3Fu);
    }
    return {cp, len};
}

bool is_word_char(std::uint32_t cp) {
    if (cp < 0x80) {
        return (cp >= 0x30 && cp <= 0x39) || (cp >= 0x41 && cp <= 0x5A) || (cp >= 0x61 && cp <= 0x7A);
    }
    // the reference's MASK_BOUNDARY_RANGES: never part of a word
    static const std::uint32_t kRanges[][2] = {
        {0x0080, 0x00BF}, {0x00D7, 0x00D7}, {0x00F7, 0x00F7}, {0x2000, 0x2BFF}, {0x2E00, 0x2E7F},
        {0x3000, 0x303F}, {0xFE00, 0xFE0F}, {0xFE10, 0xFE1F}, {0xFE30, 0xFE6F}, {0xFEFF, 0xFEFF},
        {0xFF00, 0xFF0F}, {0xFF1A, 0xFF20}, {0xFF3B, 0xFF40}, {0xFF5B, 0xFF65}, {0x1F000, 0x1FAFF},
    };
    for (const auto& r : kRanges) {
        if (cp >= r[0] && cp <= r[1]) {
            return false;
        }
    }
    return true;
}

// The pinned case fold (the reference's fold_char): one code point to one code point.
std::uint32_t fold_char(std::uint32_t cp) {
    if ((cp >= 0x41 && cp <= 0x5A) || (cp >= 0xC0 && cp <= 0xDE && cp != 0xD7)) return cp + 0x20;
    if (cp == 0x130) return 0x69;
    if (cp == 0x178) return 0xFF;
    if (((cp >= 0x100 && cp <= 0x12F) || (cp >= 0x132 && cp <= 0x137) || (cp >= 0x14A && cp <= 0x177)) && cp % 2 == 0)
        return cp + 1;
    if (((cp >= 0x139 && cp <= 0x148) || (cp >= 0x179 && cp <= 0x17E)) && cp % 2 == 1) return cp + 1;
    if (cp >= 0x391 && cp <= 0x3AB && cp != 0x3A2) return cp + 0x20;
    if (cp == 0x386) return 0x3AC;
    if (cp >= 0x388 && cp <= 0x38A) return cp + 0x25;
    if (cp == 0x38C) return 0x3CC;
    if (cp == 0x38E || cp == 0x38F) return cp + 0x3F;
    if (cp == 0x3C2) return 0x3C3;
    if (cp >= 0x400 && cp <= 0x40F) return cp + 0x50;
    if (cp >= 0x410 && cp <= 0x42F) return cp + 0x20;
    return cp;
}

// A word as its folded code points, the bytes it spans and its length in code points.
struct Word {
    std::vector<std::uint32_t> folded;
    std::size_t from = 0, to = 0;
};

// Splits text into words and the gaps between them (a gap has an empty `folded`).
std::vector<Word> scan(const std::string& text) {
    std::vector<Word> parts;
    std::size_t i = 0;
    while (i < text.size()) {
        auto [cp, len] = decode_utf8(text, i);
        if (!is_word_char(cp)) {
            parts.push_back({{}, i, i + len});
            i += len;
            continue;
        }
        Word w;
        w.from = i;
        while (i < text.size()) {
            std::tie(cp, len) = decode_utf8(text, i);
            if (!is_word_char(cp)) {
                break;
            }
            w.folded.push_back(fold_char(cp));
            i += len;
        }
        w.to = i;
        parts.push_back(std::move(w));
    }
    return parts;
}

}  // namespace

WordSet compile_words(const WordList& words) {
    WordSet wanted;
    for (const std::string& w : words) {
        const std::vector<Word> parts = scan(w);
        if (parts.size() == 1 && !parts[0].folded.empty()) {
            wanted.insert(parts[0].folded);
        }
    }
    return wanted;
}

std::string mask_words(const std::string& text, const WordList& words) {
    return mask_word_set(text, compile_words(words));
}

void WordCache::set_lists(std::map<std::string, WordList> lists) {
    lists_ = std::move(lists);
    valid_ = false;
}

const WordSet& WordCache::get(const std::string& locale) {
    if (!valid_ || locale != locale_) {
        WordList words;
        for (const std::string& loc : locale_chain(locale)) {
            const auto list = lists_.find(loc);
            if (list != lists_.end()) {
                words.insert(words.end(), list->second.begin(), list->second.end());
            }
        }
        set_ = compile_words(words);
        locale_ = locale;
        valid_ = true;
        ++folds_;
    }
    return set_;
}

std::string mask_word_set(const std::string& text, const WordSet& wanted) {
    if (wanted.empty()) {
        return text;
    }
    const std::string grawlix = kGrawlix;
    std::string out;
    for (const Word& p : scan(text)) {
        if (!p.folded.empty() && wanted.count(p.folded) > 0) {
            for (std::size_t k = 0; k < p.folded.size(); ++k) {
                out += grawlix[k % grawlix.size()];
            }
        } else {
            out.append(text, p.from, p.to - p.from);
        }
    }
    return out;
}

WordList mature_words(const nlohmann::json& j) {
    WordList out;
    if (!j.is_object()) {
        return out;
    }
    const auto words = j.find("words");
    if (words == j.end() || !words->is_array()) {
        return out;
    }
    for (const auto& w : *words) {
        if (w.is_string()) {
            out.push_back(w.get<std::string>());
        }
    }
    return out;
}

namespace {

// pseudo() and pseudo_ascii(): the same walk, with or without the accented look-alikes.
std::string pseudo_text(const std::string& text, bool accents) {
    std::string out = "[";
    std::size_t visible = 0;
    std::size_t i = 0;
    while (i < text.size()) {
        const char c = text[i];
        if (c == '{') {
            const std::size_t j = text.find('}', i);
            if (j != std::string::npos) {  // a {name} placeholder passes through and does not count
                out.append(text, i, j - i + 1);
                i = j + 1;
                continue;
            }
        }
        if (c == '%' && i + 1 < text.size() && std::string_view("sdif%").find(text[i + 1]) != std::string_view::npos) {
            out.append(text, i, 2);  // printf-style placeholder or a literal %%
            i += 2;
            continue;
        }
        if (const char* look_alike = accents ? pseudo_char(c) : nullptr) {
            out += look_alike;
        } else {
            out += c;
        }
        // One visible character per code point: continuation bytes of a multi-byte character do not count
        visible += is_utf8_continuation(c) ? 0 : 1;
        ++i;
    }
    out.append(static_cast<std::size_t>(std::ceil(static_cast<double>(visible) * kPseudoGrowth)), '~');
    out += "]";
    return out;
}

}  // namespace

std::string pseudo(const std::string& text) {
    return pseudo_text(text, true);
}

std::string pseudo_ascii(const std::string& text) {
    return pseudo_text(text, false);
}

std::string tr_pseudo(const StringTables& tables, const std::string& key, const TrArgs& args, bool clean) {
    const std::string* text = pick(tables, kFallbackLocale, key, clean);
    if (text == nullptr) {
        return key;   // missing: shown bare, so the layout check flags it as untranslated
    }
    return fill(pseudo_ascii(*text), args);
}

StringTables string_tables_from_json(const nlohmann::json& j) {
    StringTables tables;
    if (!j.is_object()) {
        return tables;
    }
    for (const auto& [locale, table] : j.items()) {
        if (!table.is_object()) {
            continue;
        }
        StringTable& out = tables[locale];
        for (const auto& [key, text] : table.items()) {
            if (text.is_string()) {
                out[key] = text.get<std::string>();
            }
        }
    }
    return tables;
}

}  // namespace core
