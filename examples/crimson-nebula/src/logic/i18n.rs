// ---------------------------------------------------------------------------
// logic/i18n.rs
// Purpose : Localization: string tables per locale, lookup through a fallback chain (fr-CA -> fr -> en),
//           {name} placeholders, one/other plurals, and the pseudo-locale that finds i18n bugs before a translator
//           does.
// Usage   : let tables = i18n::parse_tables(&text)?;                 // {"en": {"greet": "Hello, {name}!"}, ...}
//           i18n::tr(&tables, "fr-CA", "greet", &[("name", "Ana")]);
//           i18n::tr_plural(&tables, "fr", "apples", 3, &[]);         // looks up "apples.other" with {n} = 3
//           i18n::pseudo("Play")                                       // "[Pláý~~]": test layouts with it
// Notes   : A missing key returns the key itself, so it shows on screen instead of an empty label. Plurals
//           cover one/other (French counts 0 as one; Japanese, Chinese and Korean have no plural); a language
//           with more forms needs its rule added to plural(). Tested in tests/golden.rs against
//           data/golden/shell.json (tools/golden_vectors.py is the reference).
//
// Pseudocode:
//   tr: for loc in [locale, its base language, "en"]: the key in that table? fill {name} from args, return it
//   pseudo: accent each letter, keep {name} and %s %d %i %f %% as they are, pad with ~ by
//   ceil(visible * PSEUDO_GROWTH), wrap in [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;

use serde_json::Value;

// ---- Tunables ------------------------------------------------------------------
pub const FALLBACK_LOCALE: &str = "en";
/// The pseudo-locale pads each string by this share of its visible length (translations of English run longer).
pub const PSEUDO_GROWTH: f64 = 0.40;

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
    for loc in locale_chain(locale) {
        if let Some(text) = tables.get(&loc).and_then(|t| t.get(key)) {
            return fill(text, args);
        }
    }
    key.to_string()
}

/// The plural category of n in locale: "one" or "other".
pub fn plural(locale: &str, n: i64) -> &'static str {
    match base_locale(locale) {
        "ja" | "zh" | "ko" => "other",
        "fr" if n == 0 || n == 1 => "one",
        "fr" => "other",
        _ if n == 1 => "one",
        _ => "other",
    }
}

/// tr of "<key>.<category>" with {n} set to n (on top of args).
pub fn tr_plural(tables: &Tables, locale: &str, key: &str, n: i64, args: &[(&str, &str)]) -> String {
    let n_text = n.to_string();
    let mut all: Vec<(&str, &str)> = args.iter().copied().filter(|(name, _)| *name != "n").collect();
    all.push(("n", &n_text));
    tr(tables, locale, &format!("{key}.{}", plural(locale, n)), &all)
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
