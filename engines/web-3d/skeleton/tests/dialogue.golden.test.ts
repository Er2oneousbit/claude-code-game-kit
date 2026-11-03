// ---------------------------------------------------------------------------
// dialogue.golden.test.ts
// Purpose : Runs data/golden/dialogue.json through the subtitle typewriter (revealCount in src/core/dialogue.ts): a
//           reveal list that fits the text is followed, one that does not is ignored and the line types at 30
//           characters a second or fast enough to finish within its duration, code points counted.
// Usage   : python tools/dev.py test
// Notes   : A case type this file does not know fails, so a new vector type added to
//           tools/audio/wavesmith/dialogue.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { dialogueFrom, revealCount } from "../src/core/dialogue";
import { loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("dialogue.json");

const RUNNERS: Record<string, (c: GoldenCase) => void> = {
  reveal_count: (c) => {
    c.steps.forEach((s: any, i: number) => {
      const line = dialogueFrom({ version: 1, lines: { x: s.line } }).lines.x;
      expect(revealCount(line, s.t), `step ${i} (${s.about}, t=${s.t})`).toBe(s.expect);
    });
  },
};

describe("dialogue golden vectors (data/golden/dialogue.json)", () => {
  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = RUNNERS[c.type];
      if (!run) throw new Error(`unknown case type ${c.type}: update this test`);
      run(c);
    });
  }
});

// {{FOOTER}}
