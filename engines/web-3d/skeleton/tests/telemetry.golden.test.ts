// ---------------------------------------------------------------------------
// telemetry.golden.test.ts
// Purpose : Runs data/golden/telemetry.json through src/core/userData.ts: the telemetry.csv header, the session id
//           and every row (time format, CSV quoting), so every engine's telemetry.csv has the same columns.
// Usage   : python tools/dev.py test
// Notes   : A case type this file does not know fails, so a new vector type added to tools/golden_vectors.py
//           cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { SESSION_LENGTH, TELEMETRY_HEADER, newSession, telemetryRow } from "../src/core/userData";
import { loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("telemetry.json");

const RUNNERS: Record<string, (c: GoldenCase) => void> = {
  telemetry_format: (c) => {
    expect(TELEMETRY_HEADER).toBe(c.header);
    expect(SESSION_LENGTH).toBe(c.session_length);
    // the lowest and highest ids a random source can give, and some in between
    for (const rand of [() => 0, () => 0.999999, Math.random, Math.random]) {
      const sid = newSession(rand);
      expect(sid.length, sid).toBe(c.session_length);
      for (const ch of sid) expect(c.session_chars.includes(ch), `${sid} holds ${ch}`).toBe(true);
    }
  },
  telemetry_row: (c) => {
    c.points.forEach(([unixS, session, event, detail, want]: [number, string, string, string, string], i: number) =>
      expect(telemetryRow(unixS, session, event, detail), `point ${i}`).toBe(want),
    );
  },
};

describe("telemetry golden vectors (data/golden/telemetry.json)", () => {
  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = Object.prototype.hasOwnProperty.call(RUNNERS, c.type) ? RUNNERS[c.type] : undefined;
      if (!run) throw new Error(`unknown case type "${c.type}": add a runner for it (tools/golden_vectors.py is the spec)`);
      run(c);
    });
  }
});

// {{FOOTER}}
