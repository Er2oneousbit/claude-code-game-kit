// ---------------------------------------------------------------------------
// music.golden.test.ts
// Purpose : Runs data/golden/music.json through the TypeScript music director: the beat grid in samples and every
//           scripted transition plan (quantize, loop wrap, fades, stingers, synced entries), exactly.
// Usage   : python tools/dev.py test
// Notes   : A case type this file does not know fails, so a new vector type added to tools/audio/wavesmith/music.py cannot be
//           skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { beatSample, planTransition } from "../src/core/musicDirector";
import { loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("music.json");

const RUNNERS: Record<string, (c: GoldenCase) => void> = {
  music_grid: (c) => {
    c.steps.forEach((s: any, i: number) => expect(beatSample(s.k, s.bpm, s.rate), `step ${i}`).toBe(s.sample));
  },
  music_plan: (c) => {
    c.steps.forEach((s: any, i: number) => {
      expect(planTransition(c.params, s.from, s.since, s.entry, s.to, s.now), `step ${i}`).toEqual(s.expect);
    });
  },
};

// music.py raises on a quantize it does not know and plans "stinger": "" as no stinger; no golden plan reaches either
describe("music director errors (the golden params with one rule changed)", () => {
  const params = golden.cases.find((c) => c.type === "music_plan")!.params;
  const withRule = (from: string, to: string, key: string, value: unknown) => {
    const copy = JSON.parse(JSON.stringify(params));
    const rule = copy.transitions.find((r: any) => r.from === from && r.to === to);
    rule[key] = value;
    return copy;
  };
  it("a misspelt quantize is an error, not a phrase", () => {
    const typo = withRule("combat", "explore", "quantize", "bars");
    expect(() => planTransition(typo, "combat", 5000, 0, "explore", 50000)).toThrow("unknown quantize bars");
  });
  it("an empty stinger name plays no stinger", () => {
    const p = planTransition(withRule("*", "waltz", "stinger", ""), "explore", 0, 0, "waltz", 70000);
    expect([p.stinger_at, p.to_start_at]).toEqual([null, p.switch_at]);
  });
});

describe("music golden vectors (data/golden/music.json)", () => {
  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = RUNNERS[c.type];
      if (!run) throw new Error(`unknown case type ${c.type}: update this test`);
      run(c);
    });
  }
});
