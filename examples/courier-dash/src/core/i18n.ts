// ---------------------------------------------------------------------------
// i18n.ts
// Purpose : Localization: string tables with a fallback chain (fr-CA -> fr -> en), {name} placeholders,
//           CLDR plurals, clean-language variants with a word mask, and the pseudo-locale that makes
//           untranslated, truncated or glyph-less text obvious. Checked against data/golden/shell.json "tr",
//           "plural", "plural_rules", "tr_clean", "mask_words", "mature_words" and "pseudo".
// Usage   : const i = new I18n(tables, "fr")       // tables: { en: {...}, fr: {...} } from data/i18n/*.json
//           i.t("menu.play") ; i.t("greet", { name }) ; i.tn("apples", 3)
//           i.locale = "pseudo"                     // every string through pseudo(): "[Pláý~~]"
//           i.clean = true ; i.mature = { en: [...] } // content.clean_language: @clean lines, words masked
//           pure parts: tr(tables, locale, key, args, clean, words), plural(locale, n), pseudo(text),
//           maskWords(text, words), matureWords(fileText)
// Notes   : No Phaser import (Vitest runs it). A missing key returns the key itself, so it shows on screen
//           (and the pseudo check flags it: it has no brackets). Placeholders {name}, %s, %d, %i, %f and %%
//           pass through pseudo() unchanged. Argument values are formatted with String(v). The plural rules are
//           CLDR 46's for whole numbers (tools/golden_vectors.py PLURAL_FAMILIES is the spec); the word mask
//           walks code points with the reference's pinned ranges and case fold, so it agrees with every port.
//
// Pseudocode:
//   localeChain(l) = [l, its language part, "en"] without repeats
//   tr: per locale of the chain, key@clean (when clean) then key; fill; clean -> maskWords(text, words)
//   trPlural: per locale, key.<that locale's category> then key.other (each with @clean first), then the next
//   pseudo: accented look-alikes, 40 % more length as "~", wrapped in [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plural rules, the .other fallback per
//           locale, @clean variants, maskWords and matureWords, I18n.clean and I18n.mature (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compileWords and maskWordSet; I18n folds its word list
//           once per locale and list (setting I18n.mature or the locale drops the cache), not on every t()
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const FALLBACK_LOCALE = "en";
export const PSEUDO_LOCALE = "pseudo";
export const CLEAN_SUFFIX = "@clean"; // "guard.insult@clean": the line with the clean-language setting on
export const GRAWLIX = "#@$%"; // the mask, one character per code point, again from the start for each word
const PSEUDO_GROWTH = 0.40; // translated text runs about 40 % longer than English (SOP-19)
const PSEUDO: Record<string, string> = {
  a: "á", e: "é", i: "í", o: "ó", u: "ú", c: "ç", n: "ñ", y: "ý",
  A: "Á", E: "É", I: "Í", O: "Ó", U: "Ú", C: "Ç", N: "Ñ", Y: "Ý",
};
// CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES)
const PLURAL_LANGUAGES: Record<string, string> = {
  other: "ja zh ko vi th id ms lo my km yo ig jv su",
  one: "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr",
  zero_one: "hi bn fa gu kn hy",
  one_many: "es it ca",
  zero_one_many: "fr pt",
  one_21: "is mk",
  fil: "fil tl",
  east_slavic: "ru uk be",
  pl: "pl",
  cs: "cs sk",
  lt: "lt",
  balkan: "hr sr bs",
  ro: "ro mo",
  lv: "lv",
  he: "he",
  sl: "sl",
  ga: "ga",
  ar: "ar",
  cy: "cy",
};
const PLURAL_LOCALE_FAMILIES: Record<string, string> = { "pt-pt": "one_many" }; // a region with its own rule
const MILLION = 1000000;
// code point ranges that are never part of a word (the reference's MASK_BOUNDARY_RANGES)
const MASK_BOUNDARY_RANGES: [number, number][] = [
  [0x0080, 0x00bf], [0x00d7, 0x00d7], [0x00f7, 0x00f7], [0x2000, 0x2bff], [0x2e00, 0x2e7f], [0x3000, 0x303f],
  [0xfe00, 0xfe0f], [0xfe10, 0xfe1f], [0xfe30, 0xfe6f], [0xfeff, 0xfeff], [0xff00, 0xff0f], [0xff1a, 0xff20],
  [0xff3b, 0xff40], [0xff5b, 0xff65], [0x1f000, 0x1faff],
];

export type Table = Record<string, string>;
export type Tables = Record<string, Table>;
export type Args = Record<string, unknown>;
export type PluralCategory = "zero" | "one" | "two" | "few" | "many" | "other";
/** A word list folded once (compileWords): what the mask matches against. */
export type WordSet = ReadonlySet<string>;
export type Words = readonly string[] | WordSet;

const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);
const language = (locale: string) => locale.split("-")[0].split("_")[0];
const FAMILY_OF: Record<string, string> = {};
for (const [fam, langs] of Object.entries(PLURAL_LANGUAGES)) for (const l of langs.split(" ")) FAMILY_OF[l] = fam;

export function localeChain(locale: string, fallback = FALLBACK_LOCALE): string[] {
  const chain: string[] = [];
  for (const loc of [locale, language(locale), fallback]) if (loc && !chain.includes(loc)) chain.push(loc);
  return chain;
}

/** Replaces {name} with args[name]; unknown names stay as written. */
export function fill(text: string, args: Args): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    if (text[i] === "{") {
      const j = text.indexOf("}", i);
      if (j > i) {
        const name = text.slice(i + 1, j);
        if (own(args, name)) {
          out += String(args[name]);
          i = j + 1;
          continue;
        }
      }
    }
    out += text[i];
    i += 1;
  }
  return out;
}

/** One table's text for key: its @clean variant first when clean is on, else the key itself; null if neither. */
function pick(table: Table | undefined, key: string, clean: boolean): string | null {
  if (!table) return null;
  if (clean && own(table, key + CLEAN_SUFFIX)) return table[key + CLEAN_SUFFIX];
  return own(table, key) ? table[key] : null;
}

/** The raw template for key through the fallback chain (per locale: @clean first when clean), or null. */
export function lookup(tables: Tables, locale: string, key: string, clean = false): string | null {
  for (const loc of localeChain(locale)) {
    const text = pick(own(tables, loc) ? tables[loc] : undefined, key, clean);
    if (text !== null) return text;
  }
  return null;
}

function finish(text: string, args: Args, clean: boolean, words: Words): string {
  const out = fill(text, args);
  if (!clean) return out;
  return Array.isArray(words) ? maskWords(out, words as readonly string[]) : maskWordSet(out, words as WordSet);
}

/** A string through the fallback chain; a missing key returns the key itself, so it shows. With clean (the
 *  content.clean_language setting) each locale gives key@clean, then key, and the filled text is masked. */
export function tr(tables: Tables, locale: string, key: string, args: Args = {}, clean = false,
  words: Words = []): string {
  const text = lookup(tables, locale, key, clean);
  return text === null ? key : finish(text, args, clean, words);
}

/** The plural rule family of a locale: its full name (pt-PT), then its language, then English's rule. */
export function pluralFamily(locale: string): string {
  const norm = locale.replace(/_/g, "-").toLowerCase();
  for (const [name, fam] of Object.entries(PLURAL_LOCALE_FAMILIES)) {
    if (norm === name || norm.startsWith(name + "-")) return fam;
  }
  const lang = norm.split("-")[0];
  return own(FAMILY_OF, lang) ? FAMILY_OF[lang] : "one";
}

/** The CLDR plural category of a whole number (a negative one counts as its absolute value). */
export function plural(locale: string, count: number): PluralCategory {
  const fam = pluralFamily(locale);
  const n = Math.abs(Math.trunc(count));
  const m10 = n % 10;
  const m100 = n % 100;
  switch (fam) {
    case "other":
      return "other";
    case "one":
      return n === 1 ? "one" : "other";
    case "zero_one":
      return n <= 1 ? "one" : "other";
    case "one_many":
    case "zero_one_many":
      if (n === 1 || (n === 0 && fam === "zero_one_many")) return "one";
      return n !== 0 && n % MILLION === 0 ? "many" : "other";
    case "one_21":
      return m10 === 1 && m100 !== 11 ? "one" : "other";
    case "fil":
      return m10 === 4 || m10 === 6 || m10 === 9 ? "other" : "one";
    case "east_slavic":
    case "balkan":
      if (m10 === 1 && m100 !== 11) return "one";
      if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) return "few";
      return fam === "east_slavic" ? "many" : "other";
    case "pl":
      if (n === 1) return "one";
      return m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14) ? "few" : "many";
    case "cs":
      return n === 1 ? "one" : n >= 2 && n <= 4 ? "few" : "other";
    case "lt":
      if (m100 >= 11 && m100 <= 19) return "other";
      return m10 === 1 ? "one" : m10 >= 2 ? "few" : "other";
    case "ro":
      if (n === 1) return "one";
      return n === 0 || (m100 >= 1 && m100 <= 19) ? "few" : "other";
    case "lv":
      if (m10 === 0 || (m100 >= 11 && m100 <= 19)) return "zero";
      return m10 === 1 ? "one" : "other";
    case "he":
      return n === 1 ? "one" : n === 2 ? "two" : "other";
    case "sl":
      return m100 === 1 ? "one" : m100 === 2 ? "two" : m100 === 3 || m100 === 4 ? "few" : "other";
    case "ga":
      return n === 1 ? "one" : n === 2 ? "two" : n >= 3 && n <= 6 ? "few" : n >= 7 && n <= 10 ? "many" : "other";
    case "ar":
      if (n <= 2) return (["zero", "one", "two"] as const)[n];
      return m100 >= 3 && m100 <= 10 ? "few" : m100 >= 11 ? "many" : "other";
    case "cy":
      return n === 0 ? "zero" : n === 1 ? "one" : n === 2 ? "two" : n === 3 ? "few" : n === 6 ? "many" : "other";
    default:
      throw new Error(`unknown plural family ${fam}`);
  }
}

/** The template of key.<category> through the chain, each locale with its own category, then its .other. */
export function lookupPlural(tables: Tables, locale: string, key: string, n: number, clean = false): string | null {
  for (const loc of localeChain(locale)) {
    const table = own(tables, loc) ? tables[loc] : undefined;
    const cat = plural(loc, n);
    for (const c of cat === "other" ? ["other"] : [cat, "other"]) {
      const text = pick(table, `${key}.${c}`, clean);
      if (text !== null) return text;
    }
  }
  return null;
}

export function trPlural(tables: Tables, locale: string, key: string, n: number, args: Args = {}, clean = false,
  words: Words = []): string {
  const text = lookupPlural(tables, locale, key, n, clean);
  return text === null ? `${key}.${plural(locale, n)}` : finish(text, { ...args, n }, clean, words);
}

// ---- the word mask (#207) ------------------------------------------------------
export function isWordChar(cp: number): boolean {
  if (cp < 0x80) return (cp >= 0x30 && cp <= 0x39) || (cp >= 0x41 && cp <= 0x5a) || (cp >= 0x61 && cp <= 0x7a);
  for (const [lo, hi] of MASK_BOUNDARY_RANGES) if (cp >= lo && cp <= hi) return false;
  return true;
}

/** The pinned case fold (the reference's fold_char): one code point to one code point. */
export function foldChar(cp: number): number {
  if ((cp >= 0x41 && cp <= 0x5a) || (cp >= 0xc0 && cp <= 0xde && cp !== 0xd7)) return cp + 0x20;
  if (cp === 0x130) return 0x69;
  if (cp === 0x178) return 0xff;
  if (((cp >= 0x100 && cp <= 0x12f) || (cp >= 0x132 && cp <= 0x137) || (cp >= 0x14a && cp <= 0x177)) && cp % 2 === 0) return cp + 1;
  if (((cp >= 0x139 && cp <= 0x148) || (cp >= 0x179 && cp <= 0x17e)) && cp % 2 === 1) return cp + 1;
  if (cp >= 0x391 && cp <= 0x3ab && cp !== 0x3a2) return cp + 0x20;
  if (cp === 0x386) return 0x3ac;
  if (cp >= 0x388 && cp <= 0x38a) return cp + 0x25;
  if (cp === 0x38c) return 0x3cc;
  if (cp === 0x38e || cp === 0x38f) return cp + 0x3f;
  if (cp === 0x3c2) return 0x3c3;
  if (cp >= 0x400 && cp <= 0x40f) return cp + 0x50;
  if (cp >= 0x410 && cp <= 0x42f) return cp + 0x20;
  return cp;
}

const codePoints = (s: string): number[] => Array.from(s, (c) => c.codePointAt(0) as number);
const foldKey = (cps: readonly number[]): string => cps.map(foldChar).join(",");

/** The folded set the mask matches against: build it once per word list (t() runs for every label every frame). */
export function compileWords(words: readonly string[]): WordSet {
  const wanted = new Set<string>();
  for (const w of words) {
    const cps = codePoints(w);
    if (cps.length > 0 && cps.every(isWordChar)) wanted.add(foldKey(cps));
  }
  return wanted;
}

/** text with every whole word that is in words (case folded) replaced by a same-length grawlix. */
export function maskWords(text: string, words: readonly string[]): string {
  return maskWordSet(text, compileWords(words));
}

/** maskWords with the list compiled already (compileWords). */
export function maskWordSet(text: string, wanted: WordSet): string {
  if (wanted.size === 0) return text;
  const cps = codePoints(text);
  let out = "";
  let i = 0;
  while (i < cps.length) {
    if (!isWordChar(cps[i])) {
      out += String.fromCodePoint(cps[i]);
      i += 1;
      continue;
    }
    let j = i;
    while (j < cps.length && isWordChar(cps[j])) j += 1;
    const word = cps.slice(i, j);
    if (wanted.has(foldKey(word))) for (let k = 0; k < word.length; k++) out += GRAWLIX[k % GRAWLIX.length];
    else out += String.fromCodePoint(...word);
    i = j;
  }
  return out;
}

/** A word list file's words (data/i18n/mature/<locale>.json: {"words": [...]}); anything else is no words. */
export function matureWords(text: string | null): string[] {
  let raw: unknown;
  try {
    raw = text === null ? {} : JSON.parse(text);
  } catch {
    return [];
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return [];
  const words = (raw as Record<string, unknown>).words;
  return Array.isArray(words) ? words.filter((w): w is string => typeof w === "string") : [];
}

/** The pseudo-locale version of text: accented, 40 % longer, in brackets; placeholders untouched. */
export function pseudo(text: string): string {
  const cs = Array.from(text); // code points, so an emoji counts once (as in the reference)
  const out: string[] = [];
  let visible = 0;
  let i = 0;
  while (i < cs.length) {
    const c = cs[i];
    if (c === "{") {
      const j = cs.indexOf("}", i);
      if (j > i) {
        out.push(cs.slice(i, j + 1).join(""));
        i = j + 1;
        continue;
      }
    }
    if (c === "%" && i + 1 < cs.length && "sdif%".includes(cs[i + 1])) {
      out.push(c + cs[i + 1]);
      i += 2;
      continue;
    }
    out.push(own(PSEUDO, c) ? PSEUDO[c] : c);
    visible += 1;
    i += 1;
  }
  return "[" + out.join("") + "~".repeat(Math.ceil(visible * PSEUDO_GROWTH)) + "]";
}

/** The game's translator: tables plus the current locale (which may be "pseudo"), the clean-language switch and
 *  the word lists per locale (data/i18n/mature/<locale>.json). Every shell string goes through t() and tn(). */
export class I18n {
  clean = false;
  private matureLists: Record<string, string[]> = {};
  private wordCache: { locale: string; set: WordSet } | null = null; // the chain's words, folded once

  constructor(public tables: Tables, public locale = FALLBACK_LOCALE) {}

  /** The word lists per locale; setting them drops the folded cache. */
  get mature(): Record<string, string[]> {
    return this.matureLists;
  }

  set mature(lists: Record<string, string[]>) {
    this.matureLists = lists;
    this.wordCache = null;
  }

  /** The chain's words folded once per locale and list (rebuilt after a locale change or new lists). */
  wordSet(): WordSet {
    if (this.wordCache === null || this.wordCache.locale !== this.locale) {
      this.wordCache = { locale: this.locale, set: compileWords(this.words()) };
    }
    return this.wordCache.set;
  }

  /** Locales with a table, plus the pseudo-locale. */
  get locales(): string[] {
    return [...Object.keys(this.tables).sort(), PSEUDO_LOCALE];
  }

  /** The word lists of every locale in the current chain (a fallback line can come from any of them). */
  words(): string[] {
    const loc = this.locale === PSEUDO_LOCALE ? FALLBACK_LOCALE : this.locale;
    return localeChain(loc).flatMap((l) => (own(this.matureLists, l) ? this.matureLists[l] : []));
  }

  t(key: string, args: Args = {}): string {
    if (this.locale !== PSEUDO_LOCALE) return tr(this.tables, this.locale, key, args, this.clean, this.clean ? this.wordSet() : []);
    const text = lookup(this.tables, FALLBACK_LOCALE, key, this.clean);
    return text === null ? key : fill(pseudo(text), args);
  }

  tn(key: string, n: number, args: Args = {}): string {
    if (this.locale !== PSEUDO_LOCALE) {
      return trPlural(this.tables, this.locale, key, n, args, this.clean, this.clean ? this.wordSet() : []);
    }
    const text = lookupPlural(this.tables, FALLBACK_LOCALE, key, n, this.clean);
    return text === null ? `${key}.${plural(FALLBACK_LOCALE, n)}` : fill(pseudo(text), { ...args, n });
  }

  has(key: string): boolean {
    return lookup(this.tables, this.locale === PSEUDO_LOCALE ? FALLBACK_LOCALE : this.locale, key) !== null;
  }
}
