// ---------------------------------------------------------------------------
// audio.golden.test.ts
// Purpose : Runs every case of data/golden/audio.json through the TypeScript audio director (variant picks, pitch
//           and volume draws, cooldowns, voice caps, ducking envelopes).
// Usage   : python tools/dev.py test
// Notes   : One test per case. A case type this file does not know fails, so a new vector type added to
//           tools/audio/wavesmith/audio_events.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { AudioDirector } from "../src/core/audioDirector";
import { expectClose, loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("audio.json");
const TOL = golden.tolerance;

type Runner = (c: GoldenCase) => void;

const RUNNERS: Record<string, Runner> = {
  audio_director: (c) => {
    const d = new AudioDirector(c.params);
    c.steps.forEach((step: any, i: number) => {
      if (step.call === "play") return expectClose(d.play(step.event, step.t_ms), step.expect, TOL, `step ${i}`);
      if (step.call === "duck") return expectClose(d.duck(step.t_ms), step.expect, TOL, `step ${i}`);
      throw new Error(`step ${i}: unknown call ${step.call}`);
    });
  },
};

describe("audio golden vectors (data/golden/audio.json)", () => {
  it("has cases", () => {
    expect(golden.cases.length).toBeGreaterThan(0);
  });

  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = Object.prototype.hasOwnProperty.call(RUNNERS, c.type) ? RUNNERS[c.type] : undefined;
      if (!run) throw new Error(`unknown case type "${c.type}": add a runner for it (tools/audio/wavesmith/audio_events.py is the spec)`);
      run(c);
    });
  }
});

// {{FOOTER}}
