// ---------------------------------------------------------------------------
// i18n.ts
// Purpose : Localization: string tables with a fallback chain (fr-CA -> fr -> en), {name} placeholders,
//           one/other plurals, and the pseudo-locale that makes untranslated, truncated or glyph-less text
//           obvious. Checked against data/golden/shell.json "tr", "plural" and "pseudo".
// Usage   : const i = new I18n(tables, "fr")       // tables: { en: {...}, fr: {...} } from data/i18n/*.json
//           i.t("menu.play") ; i.t("greet", { name }) ; i.tn("apples", 3)
//           i.locale = "pseudo"                     // every string through pseudo(): "[Pláý~~]"
//           pure parts: tr(tables, locale, key, args), plural(locale, n), pseudo(text)
// Notes   : No Phaser import (Vitest runs it). A missing key returns the key itself, so it shows on screen
//           (and the pseudo check flags it: it has no brackets). Placeholders {name}, %s, %d, %i, %f and %%
//           pass through pseudo() unchanged. Argument values are formatted with String(v).
//
// Pseudocode:
//   localeChain(l) = [l, its language part, "en"] without repeats ; tr = first table in the chain with the key
//   pseudo: accented look-alikes, 40 % more length as "~", wrapped in [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const FALLBACK_LOCALE = "en";
export const PSEUDO_LOCALE = "pseudo";
const PSEUDO_GROWTH = 0.40; // translated text runs about 40 % longer than English (SOP-19)
const PSEUDO: Record<string, string> = {
  a: "á", e: "é", i: "í", o: "ó", u: "ú", c: "ç", n: "ñ", y: "ý",
  A: "Á", E: "É", I: "Í", O: "Ó", U: "Ú", C: "Ç", N: "Ñ", Y: "Ý",
};
const NO_PLURAL = ["ja", "zh", "ko"]; // one form for every count
const ZERO_IS_ONE = ["fr"]; // 0 and 1 take the singular

export type Table = Record<string, string>;
export type Tables = Record<string, Table>;
export type Args = Record<string, unknown>;

const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);
const language = (locale: string) => locale.split("-")[0].split("_")[0];

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

/** The raw template for key through the fallback chain, or null. */
export function lookup(tables: Tables, locale: string, key: string): string | null {
  for (const loc of localeChain(locale)) {
    const table = own(tables, loc) ? tables[loc] : undefined;
    if (table && own(table, key)) return table[key];
  }
  return null;
}

/** A string through the fallback chain; a missing key returns the key itself, so it shows. */
export function tr(tables: Tables, locale: string, key: string, args: Args = {}): string {
  const text = lookup(tables, locale, key);
  return text === null ? key : fill(text, args);
}

export function plural(locale: string, n: number): "one" | "other" {
  const base = language(locale);
  if (NO_PLURAL.includes(base)) return "other";
  if (ZERO_IS_ONE.includes(base)) return n === 0 || n === 1 ? "one" : "other";
  return n === 1 ? "one" : "other";
}

export function trPlural(tables: Tables, locale: string, key: string, n: number, args: Args = {}): string {
  return tr(tables, locale, `${key}.${plural(locale, n)}`, { ...args, n });
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

/** The game's translator: tables plus the current locale (which may be "pseudo"). */
export class I18n {
  constructor(public tables: Tables, public locale = FALLBACK_LOCALE) {}

  /** Locales with a table, plus the pseudo-locale. */
  get locales(): string[] {
    return [...Object.keys(this.tables).sort(), PSEUDO_LOCALE];
  }

  t(key: string, args: Args = {}): string {
    if (this.locale !== PSEUDO_LOCALE) return tr(this.tables, this.locale, key, args);
    const text = lookup(this.tables, FALLBACK_LOCALE, key);
    return text === null ? key : fill(pseudo(text), args);
  }

  tn(key: string, n: number, args: Args = {}): string {
    const loc = this.locale === PSEUDO_LOCALE ? FALLBACK_LOCALE : this.locale;
    return this.t(`${key}.${plural(loc, n)}`, { ...args, n });
  }

  has(key: string): boolean {
    return lookup(this.tables, this.locale === PSEUDO_LOCALE ? FALLBACK_LOCALE : this.locale, key) !== null;
  }
}

// {{FOOTER}}
