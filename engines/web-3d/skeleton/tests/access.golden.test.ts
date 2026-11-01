// ---------------------------------------------------------------------------
// access.golden.test.ts
// Purpose : Runs data/golden/access.json through src/core/audioAccess.ts: the slider gain every bus gets (nested
//           trees, cycles, bad values) and the arrow every caption point gets, exactly as the reference.
// Usage   : python tools/dev.py test
// Notes   : A case type this file does not know fails, so a new vector type added to
//           tools/audio/wavesmith/access.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { captionArrow, captionDirection, userBusGains } from "../src/core/audioAccess";
import { loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("access.json");

const RUNNERS: Record<string, (c: GoldenCase) => void> = {
  access_gains: (c) => {
    c.steps.forEach((s: any, i: number) => {
      const got = userBusGains(s.buses, s.sliders);
      expect(Object.keys(got).sort(), `step ${i}`).toEqual(Object.keys(s.expect).sort());
      for (const [bus, want] of Object.entries(s.expect)) expect(got[bus], `step ${i} ${bus}`).toBeCloseTo(want as number, 9);
    });
  },
  access_arrow: (c) => {
    c.steps.forEach((s: any, i: number) => {
      expect(captionDirection(s.dx, s.dy, s.half_w, s.half_h), `step ${i}`).toBe(s.dir);
      expect(captionArrow(s.dx, s.dy, s.half_w, s.half_h), `step ${i}`).toBe(s.arrow);
    });
  },
};

describe("audio accessibility golden vectors (data/golden/access.json)", () => {
  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = RUNNERS[c.type];
      if (!run) throw new Error(`unknown case type ${c.type}: update this test`);
      run(c);
    });
  }
});

// {{FOOTER}}
