// ---------------------------------------------------------------------------
// logic/i18n.rs
// Purpose : Localization: string tables per locale, lookup through a fallback chain (fr-CA -> fr -> en),
//           {name} placeholders, CLDR plurals, clean-language variants with a word mask, and the pseudo-locale that
//           finds i18n bugs before a translator does.
// Usage   : let tables = i18n::parse_tables(&text)?;                 // {"en": {"greet": "Hello, {name}!"}, ...}
//           i18n::tr(&tables, "fr-CA", "greet", &[("name", "Ana")]);
//           i18n::tr_plural(&tables, "fr", "apples", 3, &[]);         // looks up "apples.other" with {n} = 3
//           i18n::pseudo("Play")                                       // "[Pláý~~]": test layouts with it
//           i18n::tr_clean(&tables, "en", "guard.insult", &[], true, &words) // @clean line, listed words masked
// Notes   : A missing key returns the key itself, so it shows on screen instead of an empty label. Plurals are
//           CLDR 46's rules for whole numbers (tools/golden_vectors.py PLURAL_FAMILIES); each locale of the chain
//           uses its own rule and falls back to its .other. With clean on (content.clean_language) each locale gives
//           key@clean, then key, and the filled text goes through mask_words (code points, the reference's pinned
//           ranges and case fold). Tested in tests/golden.rs against data/golden/shell.json.
//
// Pseudocode:
//   tr: for loc in [locale, its base language, "en"]: the key in that table? fill {name} from args, return it
//   pseudo: accent each letter, keep {name} and %s %d %i %f %% as they are, pad with ~ by
//   ceil(visible * PSEUDO_GROWTH), wrap in [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plurals with the .other fallback per
//           locale, tr_clean and tr_plural_clean (@clean variants), mask_words and mature_words (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compile_words, mask_word_set and the _set forms of
//           tr_clean and tr_plural_clean, so the shell folds its word list once, not on every t() (#207)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;

use serde_json::Value;

// ---- Tunables ------------------------------------------------------------------
pub const FALLBACK_LOCALE: &str = "en";
/// The pseudo-locale pads each string by this share of its visible length (translations of English run longer).
pub const PSEUDO_GROWTH: f64 = 0.40;
/// "guard.insult@clean": the line with the clean-language setting on (#207).
pub const CLEAN_SUFFIX: &str = "@clean";
/// The mask: one character per code point, from the start again for each word.
pub const GRAWLIX: &str = "#@$%";
/// CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES).
const PLURAL_LANGUAGES: &[(&str, &str)] = &[
    ("other", "ja zh ko vi th id ms lo my km yo ig jv su"),
    (
        "one",
        "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr",
    ),
    ("zero_one", "hi bn fa gu kn hy"),
    ("one_many", "es it ca"),
    ("zero_one_many", "fr pt"),
    ("one_21", "is mk"),
    ("fil", "fil tl"),
    ("east_slavic", "ru uk be"),
    ("pl", "pl"),
    ("cs", "cs sk"),
    ("lt", "lt"),
    ("balkan", "hr sr bs"),
    ("ro", "ro mo"),
    ("lv", "lv"),
    ("he", "he"),
    ("sl", "sl"),
    ("ga", "ga"),
    ("ar", "ar"),
    ("cy", "cy"),
];
/// Code point ranges that are never part of a word (the reference's MASK_BOUNDARY_RANGES).
const MASK_BOUNDARY_RANGES: &[(u32, u32)] = &[
    (0x0080, 0x00BF),
    (0x00D7, 0x00D7),
    (0x00F7, 0x00F7),
    (0x2000, 0x2BFF),
    (0x2E00, 0x2E7F),
    (0x3000, 0x303F),
    (0xFE00, 0xFE0F),
    (0xFE10, 0xFE1F),
    (0xFE30, 0xFE6F),
    (0xFEFF, 0xFEFF),
    (0xFF00, 0xFF0F),
    (0xFF1A, 0xFF20),
    (0xFF3B, 0xFF40),
    (0xFF5B, 0xFF65),
    (0x1F000, 0x1FAFF),
];

/// key -> text for one locale.
pub type Table = BTreeMap<String, String>;
/// locale ("en", "fr", "fr-CA") -> its table.
pub type Tables = BTreeMap<String, Table>;

/// String tables from JSON text: {"en": {"menu.play": "Play"}, "fr": {...}}. Non-string entries are an error.
pub fn parse_tables(text: &str) -> Result<Tables, String> {
    let value: Value = serde_json::from_str(text).map_err(|e| format!("not JSON: {e}"))?;
    tables_from_value(&value)
}

/// String tables from an already parsed JSON object.
pub fn tables_from_value(value: &Value) -> Result<Tables, String> {
    let locales = value.as_object().ok_or("string tables must be an object of locales")?;
    let mut out = Tables::new();
    for (locale, table) in locales {
        let entries = table
            .as_object()
            .ok_or(format!("{locale}: must be an object of strings"))?;
        let mut t = Table::new();
        for (key, text) in entries {
            let text = text.as_str().ok_or(format!("{locale}.{key}: not a string"))?;
            t.insert(key.clone(), text.to_string());
        }
        out.insert(locale.clone(), t);
    }
    Ok(out)
}

/// The language part of a locale: "fr-CA" and "fr_FR" -> "fr".
pub fn base_locale(locale: &str) -> &str {
    let lang = locale.split('-').next().unwrap_or(locale);
    lang.split('_').next().unwrap_or(lang)
}

/// [locale, its base language, FALLBACK_LOCALE] without repeats or empty entries.
pub fn locale_chain(locale: &str) -> Vec<String> {
    let mut chain: Vec<String> = Vec::new();
    for loc in [locale, base_locale(locale), FALLBACK_LOCALE] {
        if !loc.is_empty() && !chain.iter().any(|c| c == loc) {
            chain.push(loc.to_string());
        }
    }
    chain
}

/// Replaces {name} with its value from args; an unknown {name} stays as written.
fn fill(text: &str, args: &[(&str, &str)]) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(c) = rest.chars().next() {
        if c == '{'
            && let Some(end) = rest.find('}')
            && let Some((_, value)) = args.iter().find(|(name, _)| *name == &rest[1..end])
        {
            out.push_str(value);
            rest = &rest[end + 1..];
            continue;
        }
        out.push(c);
        rest = &rest[c.len_utf8()..];
    }
    out
}

/// The text for key in locale (through the fallback chain) with {name} placeholders filled; the key itself if no
/// table has it.
pub fn tr(tables: &Tables, locale: &str, key: &str, args: &[(&str, &str)]) -> String {
    tr_clean(tables, locale, key, args, false, &[])
}

/// One table's text for key: key@clean first when clean is on, else key.
fn pick<'a>(tables: &'a Tables, loc: &str, key: &str, clean: bool) -> Option<&'a String> {
    let table = tables.get(loc)?;
    if clean && let Some(text) = table.get(&format!("{key}{CLEAN_SUFFIX}")) {
        return Some(text);
    }
    table.get(key)
}

fn finish(text: &str, args: &[(&str, &str)], clean: bool, words: &WordSet) -> String {
    let out = fill(text, args);
    if clean && !words.is_empty() {
        mask_word_set(&out, words)
    } else {
        out
    }
}

/// A word list folded once (compile_words): what the mask matches against.
pub type WordSet = std::collections::BTreeSet<Vec<u32>>;

/// tr with the clean-language switch (#207): per locale of the chain key@clean, then key; with clean on the filled
/// text is masked with words (placeholder values included).
pub fn tr_clean(
    tables: &Tables,
    locale: &str,
    key: &str,
    args: &[(&str, &str)],
    clean: bool,
    words: &[String],
) -> String {
    let set = if clean { compile_words(words) } else { WordSet::new() };
    tr_clean_set(tables, locale, key, args, clean, &set)
}

/// tr_clean with the words compiled already (the shell's cache).
pub fn tr_clean_set(
    tables: &Tables,
    locale: &str,
    key: &str,
    args: &[(&str, &str)],
    clean: bool,
    words: &WordSet,
) -> String {
    for loc in locale_chain(locale) {
        if let Some(text) = pick(tables, &loc, key, clean) {
            return finish(text, args, clean, words);
        }
    }
    key.to_string()
}

/// The plural rule family: the full locale (pt-PT) first, then its language, then English's rule.
fn plural_family(locale: &str) -> &'static str {
    let norm = locale.replace('_', "-").to_lowercase();
    if norm == "pt-pt" || norm.starts_with("pt-pt-") {
        return "one_many";
    }
    let lang = norm.split('-').next().unwrap_or("");
    PLURAL_LANGUAGES
        .iter()
        .find(|(_, langs)| langs.split(' ').any(|l| l == lang))
        .map_or("one", |(fam, _)| fam)
}

/// The CLDR plural category of a whole number in locale (a negative one counts as its absolute value).
pub fn plural(locale: &str, count: i64) -> &'static str {
    let fam = plural_family(locale);
    let n = count.unsigned_abs();
    let (m10, m100) = (n % 10, n % 100);
    match fam {
        "other" => "other",
        "one" => {
            if n == 1 {
                "one"
            } else {
                "other"
            }
        }
        "zero_one" => {
            if n <= 1 {
                "one"
            } else {
                "other"
            }
        }
        "one_many" | "zero_one_many" => {
            if n == 1 || (n == 0 && fam == "zero_one_many") {
                "one"
            } else if n != 0 && n.is_multiple_of(1_000_000) {
                "many"
            } else {
                "other"
            }
        }
        "one_21" => {
            if m10 == 1 && m100 != 11 {
                "one"
            } else {
                "other"
            }
        }
        "fil" => {
            if matches!(m10, 4 | 6 | 9) {
                "other"
            } else {
                "one"
            }
        }
        "east_slavic" | "balkan" => {
            if m10 == 1 && m100 != 11 {
                "one"
            } else if (2..=4).contains(&m10) && !(12..=14).contains(&m100) {
                "few"
            } else if fam == "east_slavic" {
                "many"
            } else {
                "other"
            }
        }
        "pl" => {
            if n == 1 {
                "one"
            } else if (2..=4).contains(&m10) && !(12..=14).contains(&m100) {
                "few"
            } else {
                "many"
            }
        }
        "cs" => match n {
            1 => "one",
            2..=4 => "few",
            _ => "other",
        },
        "lt" => {
            if (11..=19).contains(&m100) {
                "other"
            } else if m10 == 1 {
                "one"
            } else if m10 >= 2 {
                "few"
            } else {
                "other"
            }
        }
        "ro" => {
            if n == 1 {
                "one"
            } else if n == 0 || (1..=19).contains(&m100) {
                "few"
            } else {
                "other"
            }
        }
        "lv" => {
            if m10 == 0 || (11..=19).contains(&m100) {
                "zero"
            } else if m10 == 1 {
                "one"
            } else {
                "other"
            }
        }
        "he" => match n {
            1 => "one",
            2 => "two",
            _ => "other",
        },
        "sl" => match m100 {
            1 => "one",
            2 => "two",
            3 | 4 => "few",
            _ => "other",
        },
        "ga" => match n {
            1 => "one",
            2 => "two",
            3..=6 => "few",
            7..=10 => "many",
            _ => "other",
        },
        "ar" => match n {
            0 => "zero",
            1 => "one",
            2 => "two",
            _ if (3..=10).contains(&m100) => "few",
            _ if m100 >= 11 => "many",
            _ => "other",
        },
        "cy" => match n {
            0 => "zero",
            1 => "one",
            2 => "two",
            3 => "few",
            6 => "many",
            _ => "other",
        },
        _ => "other",
    }
}

/// tr of "<key>.<category>" with {n} set to n (on top of args).
pub fn tr_plural(tables: &Tables, locale: &str, key: &str, n: i64, args: &[(&str, &str)]) -> String {
    tr_plural_clean(tables, locale, key, n, args, false, &[])
}

/// "<key>.<category>" through the chain, each locale with its own category, then its "<key>.other" (each @clean
/// first when clean is on); nothing anywhere: "<key>.<category>" itself.
pub fn tr_plural_clean(
    tables: &Tables,
    locale: &str,
    key: &str,
    n: i64,
    args: &[(&str, &str)],
    clean: bool,
    words: &[String],
) -> String {
    let set = if clean { compile_words(words) } else { WordSet::new() };
    tr_plural_clean_set(tables, locale, key, n, args, clean, &set)
}

/// tr_plural_clean with the words compiled already (the shell's cache).
pub fn tr_plural_clean_set(
    tables: &Tables,
    locale: &str,
    key: &str,
    n: i64,
    args: &[(&str, &str)],
    clean: bool,
    words: &WordSet,
) -> String {
    let n_text = n.to_string();
    let mut all: Vec<(&str, &str)> = args.iter().copied().filter(|(name, _)| *name != "n").collect();
    all.push(("n", &n_text));
    for loc in locale_chain(locale) {
        let cat = plural(&loc, n);
        let text = pick(tables, &loc, &format!("{key}.{cat}"), clean).or_else(|| {
            if cat == "other" {
                None
            } else {
                pick(tables, &loc, &format!("{key}.other"), clean)
            }
        });
        if let Some(text) = text {
            return finish(text, &all, clean, words);
        }
    }
    format!("{key}.{}", plural(locale, n))
}

// ---- the word mask (#207) ------------------------------------------------------------------------------------
pub fn is_word_char(cp: u32) -> bool {
    if cp < 0x80 {
        return (0x30..=0x39).contains(&cp) || (0x41..=0x5A).contains(&cp) || (0x61..=0x7A).contains(&cp);
    }
    !MASK_BOUNDARY_RANGES.iter().any(|&(lo, hi)| (lo..=hi).contains(&cp))
}

/// The pinned case fold (the reference's fold_char): one code point to one code point.
pub fn fold_char(cp: u32) -> u32 {
    match cp {
        0x41..=0x5A => cp + 0x20,
        0xC0..=0xDE if cp != 0xD7 => cp + 0x20,
        0x130 => 0x69,
        0x178 => 0xFF,
        0x100..=0x12F | 0x132..=0x137 | 0x14A..=0x177 if cp.is_multiple_of(2) => cp + 1,
        0x139..=0x148 | 0x179..=0x17E if cp % 2 == 1 => cp + 1,
        0x391..=0x3AB if cp != 0x3A2 => cp + 0x20,
        0x386 => 0x3AC,
        0x388..=0x38A => cp + 0x25,
        0x38C => 0x3CC,
        0x38E | 0x38F => cp + 0x3F,
        0x3C2 => 0x3C3,
        0x400..=0x40F => cp + 0x50,
        0x410..=0x42F => cp + 0x20,
        _ => cp,
    }
}

fn fold_word(s: &str) -> Vec<u32> {
    s.chars().map(|c| fold_char(c as u32)).collect()
}

/// The folded set the mask matches against: build it once per word list (t() runs for every label every frame).
pub fn compile_words(words: &[String]) -> WordSet {
    words
        .iter()
        .filter(|w| !w.is_empty() && w.chars().all(|c| is_word_char(c as u32)))
        .map(|w| fold_word(w))
        .collect()
}

/// text with every whole word that is in words (case folded) replaced by a same-length grawlix.
pub fn mask_words(text: &str, words: &[String]) -> String {
    mask_word_set(text, &compile_words(words))
}

/// mask_words with the list compiled already (compile_words).
pub fn mask_word_set(text: &str, wanted: &WordSet) -> String {
    let fold = fold_word;
    if wanted.is_empty() {
        return text.to_string();
    }
    let grawlix: Vec<char> = GRAWLIX.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut word = String::new();
    let flush = |word: &mut String, out: &mut String| {
        if wanted.contains(&fold(word)) {
            for k in 0..word.chars().count() {
                out.push(grawlix[k % grawlix.len()]);
            }
        } else {
            out.push_str(word);
        }
        word.clear();
    };
    for c in text.chars() {
        if is_word_char(c as u32) {
            word.push(c);
        } else {
            if !word.is_empty() {
                flush(&mut word, &mut out);
            }
            out.push(c);
        }
    }
    if !word.is_empty() {
        flush(&mut word, &mut out);
    }
    out
}

/// A word list file's words (data/i18n/mature/<locale>.json: {"words": [...]}, strings only); anything else is none.
pub fn mature_words(value: &Value) -> Vec<String> {
    value["words"]
        .as_array()
        .map(|a| a.iter().filter_map(|w| w.as_str().map(str::to_string)).collect())
        .unwrap_or_default()
}

fn accent(c: char) -> char {
    match c {
        'a' => 'á',
        'e' => 'é',
        'i' => 'í',
        'o' => 'ó',
        'u' => 'ú',
        'c' => 'ç',
        'n' => 'ñ',
        'y' => 'ý',
        'A' => 'Á',
        'E' => 'É',
        'I' => 'Í',
        'O' => 'Ó',
        'U' => 'Ú',
        'C' => 'Ç',
        'N' => 'Ñ',
        'Y' => 'Ý',
        other => other,
    }
}

/// The pseudo-locale: accented look-alikes (catches missing glyphs), 40 % longer (catches truncation), in
/// brackets (catches cut-off strings and text that skipped tr). {name}, %s, %d, %i, %f and %% pass through
/// unchanged and do not count toward the length.
pub fn pseudo(text: &str) -> String {
    let mut out = String::with_capacity(text.len() * 2);
    let mut visible = 0usize;
    let mut rest = text;
    while let Some(c) = rest.chars().next() {
        if c == '{'
            && let Some(end) = rest.find('}')
        {
            out.push_str(&rest[..=end]);
            rest = &rest[end + 1..];
            continue;
        }
        if c == '%'
            && let Some(next) = rest[1..].chars().next()
            && "sdif%".contains(next)
        {
            out.push(c);
            out.push(next);
            rest = &rest[1 + next.len_utf8()..];
            continue;
        }
        out.push(accent(c));
        visible += 1;
        rest = &rest[c.len_utf8()..];
    }
    let pad = (visible as f64 * PSEUDO_GROWTH).ceil() as usize;
    format!("[{out}{}]", "~".repeat(pad))
}
