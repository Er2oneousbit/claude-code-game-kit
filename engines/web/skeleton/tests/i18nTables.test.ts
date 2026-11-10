// ---------------------------------------------------------------------------
// i18nTables.test.ts
// Purpose : The shipped string tables (data/i18n/*.json): French uses only English keys and translates every one
//           (tools/check_i18n.py names the missing ones), and a key a partial table lacks falls back to English.
// Usage   : python tools/dev.py test
// Notes   : The shipped fr.json is complete (#272), so the fallback check uses a partial table of its own, as a
//           translation in progress would be.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import en from "../data/i18n/en.json";
import fr from "../data/i18n/fr.json";
import { I18n, type Tables } from "../src/core/i18n";

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
});

// {{FOOTER}}
