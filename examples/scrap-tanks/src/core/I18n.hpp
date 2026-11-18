// ---------------------------------------------------------------------------
// I18n.hpp
// Purpose : Localization logic: string lookup through a locale fallback chain with {name} placeholders,
//           CLDR plural categories, clean-language variants with a word mask, and the pseudo-locale that finds
//           untranslated, truncated and unsupported text before a translator does. Plain C++, UTF-8 std::string
//           everywhere, no SDL.
// Usage   : const core::StringTables tables = core::string_tables_from_json(json_from_data_i18n);
//           core::tr(tables, "fr-CA", "greet", {{"name", player}})     // "Bonjour, Ana !"
//           core::tr_plural(tables, "fr", "apples", count)            // key "apples.one" / "apples.other"
//           core::pseudo(core::tr(tables, "en", "menu.play"))         // "[Pláý~~]" while testing layouts
//           core::tr(tables, "en", "guard.insult", {}, true, words)    // the @clean line, listed words masked
// Notes   : fr-CA falls back to fr, then en. A missing key returns the key itself, so it shows on screen
//           instead of an empty label. Plural rules are CLDR 46's for whole numbers (tools/golden_vectors.py
//           PLURAL_FAMILIES); each locale of the chain uses its own rule and falls back to its .other. With clean
//           on (content.clean_language) each locale gives key@clean, then key, and the filled text goes through
//           mask_words: a code point scan with the reference's pinned ranges and case fold. Matches
//           tools/golden_vectors.py, checked against data/golden/shell.json.
//
// Pseudocode:
//   locale_chain("fr-CA") = ["fr-CA", "fr", "en"] (duplicates and empty entries dropped)
//   tr: the first table in the chain that has key, with {name} replaced from args; else key
//   pseudo: every character -> accented look-alike, placeholders ({x} %s %d %i %f %%) unchanged,
//           then ceil(visible characters * kPseudoGrowth) tildes, all inside [ ]
//   pseudo_ascii: the same with every character kept (no accents); tr_pseudo: English -> pseudo_ascii -> fill
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): pseudo_ascii and tr_pseudo for the 8x8 font (#275)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plurals with the .other fallback per locale,
//           @clean variants, mask_words and mature_words (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compile_words, mask_word_set and WordCache, so the
//           shell folds its word list once per locale and list, not on every t() (#207)
// ---------------------------------------------------------------------------
#pragma once

#include <cstddef>
#include <cstdint>
#include <set>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

using StringTable = std::map<std::string, std::string>;   // key -> text
using StringTables = std::map<std::string, StringTable>;  // locale -> table
using TrArgs = std::map<std::string, std::string>;        // placeholder name -> value
using WordList = std::vector<std::string>;                // the game's words for the clean-language mask
using WordSet = std::set<std::vector<std::uint32_t>>;     // a WordList folded once (compile_words)

// ---- Tunables ----
constexpr const char* kFallbackLocale = "en";
constexpr const char* kPseudoLocale = "pseudo";   // the layout-test locale (dev.py smoke --drive pseudo --locale pseudo)
constexpr double kPseudoGrowth = 0.40;  // pseudo text is 40 % longer (translated English runs about that long, SOP-19)
constexpr const char* kCleanSuffix = "@clean";   // "guard.insult@clean": the line with clean language on (#207)
constexpr const char* kGrawlix = "#@$%";         // the mask: one character per code point, again for each word

// Number of characters (code points) in UTF-8 text.
std::size_t utf8_length(std::string_view text);

// The locales to try in order: locale, its language, then the fallback.
std::vector<std::string> locale_chain(const std::string& locale, const std::string& fallback = kFallbackLocale);

// The text for key in the first locale of the chain that has it (per locale key@clean first when clean is on),
// placeholders filled, then masked with words when clean is on; key itself when none has it.
std::string tr(const StringTables& tables, const std::string& locale, const std::string& key,
               const TrArgs& args = {}, bool clean = false, const WordList& words = {});

// The CLDR plural category of a whole number for locale: zero, one, two, few, many or other.
std::string plural(const std::string& locale, long long n);

// "<key>.<category>" through the chain, each locale with its own category, then its "<key>.other"; {n} set to n.
// Nothing anywhere: "<key>.<category>" itself.
std::string tr_plural(const StringTables& tables, const std::string& locale, const std::string& key, long long n,
                      const TrArgs& args = {}, bool clean = false, const WordList& words = {});

// text with every whole word that is in words (case folded, code points) replaced by a same-length grawlix.
std::string mask_words(const std::string& text, const WordList& words);

// The folded set mask_word_set matches against: build it once per word list (t() runs for every label every frame).
WordSet compile_words(const WordList& words);

// mask_words with the list compiled already.
std::string mask_word_set(const std::string& text, const WordSet& wanted);

// tr() and tr_plural() with the words compiled already (the shell's cache).
std::string tr(const StringTables& tables, const std::string& locale, const std::string& key, const TrArgs& args,
               bool clean, const WordSet& words);
std::string tr_plural(const StringTables& tables, const std::string& locale, const std::string& key, long long n,
                      const TrArgs& args, bool clean, const WordSet& words);

// The word lists per locale and the chain's folded set: get() folds once per locale; set_lists() drops the fold.
class WordCache {
public:
    void set_lists(std::map<std::string, WordList> lists);
    const std::map<std::string, WordList>& lists() const { return lists_; }
    // The folded words of every locale in locale's chain (a fallback line can come from any of them).
    const WordSet& get(const std::string& locale);
    int folds() const { return folds_; }   // how many times get() folded (tests)

private:
    std::map<std::string, WordList> lists_;
    std::string locale_;
    WordSet set_;
    bool valid_ = false;
    int folds_ = 0;
};

// A word list file's words (data/i18n/mature/<locale>.json: {"words": [...]}); anything else is no words.
WordList mature_words(const nlohmann::json& j);

// The pseudo-locale version of text (see Notes).
std::string pseudo(const std::string& text);

// The same without accents (#275): bracketed and 40 % longer, ASCII kept ASCII. The shell's 8x8 debug font draws
// ASCII only, so its pseudo locale uses this form: it still finds clipped and untranslated text, not missing glyphs.
std::string pseudo_ascii(const std::string& text);

// The pseudo locale's tr(): the English text through pseudo_ascii(), then the placeholders filled (their values stay
// as they are). A key English lacks comes back bare, without brackets, so a layout check flags it.
std::string tr_pseudo(const StringTables& tables, const std::string& key, const TrArgs& args = {},
                      bool clean = false);

// From JSON {"en": {"menu.play": "Play", ...}, "fr": {...}}; non-string entries are skipped.
StringTables string_tables_from_json(const nlohmann::json& j);

}  // namespace core
