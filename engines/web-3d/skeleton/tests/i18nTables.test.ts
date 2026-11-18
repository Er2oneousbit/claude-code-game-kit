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
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): the folded word cache follows new lists and the locale,
//           and t() with 3000 words costs a tenth of folding per call or less
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import en from "../data/i18n/en.json";
import fr from "../data/i18n/fr.json";
import mature from "../data/i18n/mature/en.json";
import { I18n, PSEUDO_LOCALE, matureWords, maskWords, tr, type Tables } from "../src/core/i18n";

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

  it("the folded word cache follows a new list and the locale (#207)", () => {
    const i = new I18n({ en: { bye: "Damn, bye {name}." }, fr: { bye: "Merde, salut {name}." } }, "en");
    i.clean = true;
    i.mature = { en: ["damn"] };
    expect(i.t("bye", { name: "Bob" })).toBe("#@$%, bye Bob.");
    i.mature = { en: ["bob"] };                                        // a new list: the cache must not keep "damn"
    expect(i.t("bye", { name: "Bob" })).toBe("Damn, bye #@$.");
    i.mature = { en: ["bob"], fr: ["merde"] };
    i.locale = "fr";                                                    // a new chain: fr's words join
    expect(i.t("bye", { name: "Bob" })).toBe("#@$%#, salut #@$.");
  });

  it("t() with clean language and a long word list stays cheap (timing printed)", () => {
    const words = Array.from({ length: 3000 }, (_, k) => `word${k}`);
    const tables: Tables = { en: { label: "A settings label with {name} in it" } };
    const i = new I18n(tables, "en");
    i.clean = true;
    i.mature = { en: words };
    const labels = 400;                                                  // about one settings screen's labels
    let t0 = performance.now();
    for (let k = 0; k < labels; k++) tr(tables, "en", "label", { name: "x" }, true, words);   // the old path
    const uncached = performance.now() - t0;
    t0 = performance.now();
    for (let k = 0; k < labels; k++) i.t("label", { name: "x" });
    const cached = performance.now() - t0;
    console.log(`T_COST ${labels} labels, ${words.length} words: uncached ${uncached.toFixed(1)} ms, cached ${cached.toFixed(1)} ms`);
    expect(maskWords("word7 here", words)).toBe("#@$%# here");
    expect(cached).toBeLessThan(uncached / 10);                         // folded once, not per label
  });
});

// {{FOOTER}}
