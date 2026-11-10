// ---------------------------------------------------------------------------
// I18n.hpp
// Purpose : Localization logic: string lookup through a locale fallback chain with {name} placeholders,
//           plural categories, and the pseudo-locale that finds untranslated, truncated and unsupported
//           text before a translator does. Plain C++, UTF-8 std::string everywhere, no SDL.
// Usage   : const core::StringTables tables = core::string_tables_from_json(json_from_data_i18n);
//           core::tr(tables, "fr-CA", "greet", {{"name", player}})     // "Bonjour, Ana !"
//           core::tr_plural(tables, "fr", "apples", count)            // key "apples.one" / "apples.other"
//           core::pseudo(core::tr(tables, "en", "menu.play"))         // "[Pláý~~]" while testing layouts
// Notes   : fr-CA falls back to fr, then en. A missing key returns the key itself, so it shows on screen
//           instead of an empty label. Plural rules cover one/other (English-like), French (0 and 1 are
//           "one") and Japanese, Chinese, Korean (always "other"); add a language's rule in plural() when
//           the game ships it. Matches tools/golden_vectors.py (tr, plural, pseudo), checked against
//           data/golden/shell.json.
//
// Pseudocode:
//   locale_chain("fr-CA") = ["fr-CA", "fr", "en"] (duplicates and empty entries dropped)
//   tr: the first table in the chain that has key, with {name} replaced from args; else key
//   pseudo: every character -> accented look-alike, placeholders ({x} %s %d %i %f %%) unchanged,
//           then ceil(visible characters * kPseudoGrowth) tildes, all inside [ ]
//   pseudo_ascii: the same with every character kept (no accents); tr_pseudo: English -> pseudo_ascii -> fill
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): pseudo_ascii and tr_pseudo for the 8x8 font (#275)
// ---------------------------------------------------------------------------
#pragma once

#include <cstddef>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

using StringTable = std::map<std::string, std::string>;   // key -> text
using StringTables = std::map<std::string, StringTable>;  // locale -> table
using TrArgs = std::map<std::string, std::string>;        // placeholder name -> value

// ---- Tunables ----
constexpr const char* kFallbackLocale = "en";
constexpr const char* kPseudoLocale = "pseudo";   // the layout-test locale (dev.py smoke --drive pseudo --locale pseudo)
constexpr double kPseudoGrowth = 0.40;  // pseudo text is 40 % longer (translated English runs about that long, SOP-19)

// Number of characters (code points) in UTF-8 text.
std::size_t utf8_length(std::string_view text);

// The locales to try in order: locale, its language, then the fallback.
std::vector<std::string> locale_chain(const std::string& locale, const std::string& fallback = kFallbackLocale);

// The text for key in the first locale of the chain that has it, placeholders filled; key itself when none has it.
std::string tr(const StringTables& tables, const std::string& locale, const std::string& key,
               const TrArgs& args = {});

// The plural category of n for locale: "one" or "other".
std::string plural(const std::string& locale, long long n);

// tr() of "<key>.<category>" with {n} set to n.
std::string tr_plural(const StringTables& tables, const std::string& locale, const std::string& key, long long n,
                      const TrArgs& args = {});

// The pseudo-locale version of text (see Notes).
std::string pseudo(const std::string& text);

// The same without accents (#275): bracketed and 40 % longer, ASCII kept ASCII. The shell's 8x8 debug font draws
// ASCII only, so its pseudo locale uses this form: it still finds clipped and untranslated text, not missing glyphs.
std::string pseudo_ascii(const std::string& text);

// The pseudo locale's tr(): the English text through pseudo_ascii(), then the placeholders filled (their values stay
// as they are). A key English lacks comes back bare, without brackets, so a layout check flags it.
std::string tr_pseudo(const StringTables& tables, const std::string& key, const TrArgs& args = {});

// From JSON {"en": {"menu.play": "Play", ...}, "fr": {...}}; non-string entries are skipped.
StringTables string_tables_from_json(const nlohmann::json& j);

}  // namespace core

// {{FOOTER}}
