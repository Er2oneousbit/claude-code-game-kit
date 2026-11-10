// ---------------------------------------------------------------------------
// I18n.cpp
// Purpose : Implementation of lookup, plurals and the pseudo-locale (see I18n.hpp).
// Usage   : compiled into the `core` library; call through I18n.hpp.
// Notes   : Works on UTF-8 bytes: '{', '}' and '%' are ASCII and never appear inside a multi-byte
//           character, so scanning bytes is safe; lengths count characters (code points), not bytes.
//           The accented look-alikes are written as UTF-8 byte escapes so the result does not depend on
//           the compiler's source or execution character set.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "core/I18n.hpp"

#include <cmath>

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

std::string tr(const StringTables& tables, const std::string& locale, const std::string& key, const TrArgs& args) {
    for (const std::string& loc : locale_chain(locale)) {
        const auto table = tables.find(loc);
        if (table == tables.end()) {
            continue;
        }
        const auto entry = table->second.find(key);
        if (entry != table->second.end()) {
            return fill(entry->second, args);
        }
    }
    return key;
}

std::string plural(const std::string& locale, long long n) {
    const std::string base = base_language(locale);
    if (base == "ja" || base == "zh" || base == "ko") {
        return "other";
    }
    if (base == "fr") {
        return n == 0 || n == 1 ? "one" : "other";
    }
    return n == 1 ? "one" : "other";
}

std::string tr_plural(const StringTables& tables, const std::string& locale, const std::string& key, long long n,
                      const TrArgs& args) {
    TrArgs a = args;
    a["n"] = std::to_string(n);
    return tr(tables, locale, key + "." + plural(locale, n), a);
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

std::string tr_pseudo(const StringTables& tables, const std::string& key, const TrArgs& args) {
    const auto table = tables.find(kFallbackLocale);
    if (table == tables.end()) {
        return key;
    }
    const auto entry = table->second.find(key);
    if (entry == table->second.end()) {
        return key;   // missing: shown bare, so the layout check flags it as untranslated
    }
    return fill(pseudo_ascii(entry->second), args);
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
