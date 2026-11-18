// ---------------------------------------------------------------------------
// i18nTables.test.ts
// Purpose : The shipped string tables (data/i18n/*.json): French uses only English keys and translates every one
//           (tools/check_i18n.py names the missing ones), and a key a partial table lacks falls back to English.
// Usage   : python tools/dev.py test
// Notes   : The shipped fr.json is complete (#272), so the fallback check uses a partial table of its own, as a
//           translation in progress would be. The translator the shell uses honours the clean-language switch
//           in t(), tn() and the pseudo-locale (#207), and the shipped word list loads.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the clean-language path of I18n (#207)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import en from "../data/i18n/en.json";
import fr from "../data/i18n/fr.json";
import mature from "../data/i18n/mature/en.json";
import { I18n, PSEUDO_LOCALE, matureWords, type Tables } from "../src/core/i18n";

const EN = en as Record<string, string>;
const FR = fr as Record<string, string>;

describe("string tables", () => {
  it("French uses only English keys", () => {
    expect(Object.keys(FR).filter((k) => !(k in EN))).toEqual([]);
  });

  it("French translates every English key", () => {
    expect(Object.keys(EN).filter((k) => !(k in FR))).toEqual([]);
  });

  it("a key a partial table lacks falls back to English", () => {
    const partial: Tables = { en: EN, fr: { "menu.play": FR["menu.play"] } };
    const i = new I18n(partial, "fr");
    expect(i.t("menu.play")).toBe(FR["menu.play"]);
    expect(i.t("menu.juice")).toBe(EN["menu.juice"]);
    expect(i.t("no.such.key")).toBe("no.such.key");
  });

  it("the shipped word list is a word list, and empty", () => {
    expect(matureWords(JSON.stringify(mature))).toEqual([]);
  });

  it("the shell's translator honours clean language in t, tn and the pseudo-locale (#207)", () => {
    const tables: Tables = {
      en: { "bye": "Damn, bye {name}.", "bye@clean": "Bye {name}.", "hits.one": "{n} damn hit", "hits.other": "{n} hits",
        "hits.one@clean": "{n} hit" },
      fr: { "bye": "Merde, salut {name}." },
    };
    const i = new I18n(tables, "fr");
    i.mature = { fr: ["merde"], en: ["damn"] };
    expect(i.t("bye", { name: "Ana" })).toBe("Merde, salut Ana.");     // off: as written
    i.clean = true;
    expect(i.t("bye", { name: "Damn" })).toBe("#@$%#, salut #@$%.");   // fr stays fr; masked with both lists
    i.locale = "en";
    expect(i.t("bye", { name: "Ana" })).toBe("Bye Ana.");
    expect(i.tn("hits", 1)).toBe("1 hit");
    i.locale = PSEUDO_LOCALE;
    expect(i.t("bye", { name: "Ana" })).toBe("[Býé Ana.~~]");
  });
});

// {{FOOTER}}
