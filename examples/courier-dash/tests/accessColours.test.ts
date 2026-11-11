// ---------------------------------------------------------------------------
// accessColours.test.ts
// Purpose : The demo palette per colour-blind setting is data/access/colours.json, the file
//           tools/access/colour_check.py checks (#169): every colour the file names is what PALETTES holds.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import colourData from "../data/access/colours.json";
import { PALETTES } from "../src/shell/palettes";

describe("access colours", () => {
  it("are the palettes the demo draws", () => {
    const palettes = colourData.palettes as Record<string, Record<string, string>>;
    expect(Object.keys(PALETTES).sort()).toEqual(Object.keys(palettes).sort());
    for (const [mode, colours] of Object.entries(palettes)) {
      for (const [name, value] of Object.entries(colours)) {
        expect((PALETTES[mode] as Record<string, number>)[name], `${mode}.${name}`).toBe(parseInt(value.slice(1), 16));
      }
    }
  });
});
