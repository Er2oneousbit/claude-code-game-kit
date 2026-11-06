// ---------------------------------------------------------------------------
// autoRepeat.test.ts
// Purpose : "Hold to mash" (access.auto_repeat, #166): a held button repeats after the delay, then on the interval,
//           and releasing starts the delay again.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { AUTO_REPEAT_DELAY_S, AUTO_REPEAT_INTERVAL_S, AutoRepeat } from "../src/core/autoRepeat";

describe("auto repeat", () => {
  it("repeats a held press after the delay, then on the interval", () => {
    const rep = new AutoRepeat();
    const fired: number[] = [];
    let t = 0;
    for (let i = 0; i < 70; i++) {
      t += 0.01;
      if (rep.update(0.01, true)) fired.push(t);
    }
    expect(fired.length).toBe(3);
    expect(fired[0]).toBeCloseTo(AUTO_REPEAT_DELAY_S, 1);
    expect(fired[1] - fired[0]).toBeCloseTo(AUTO_REPEAT_INTERVAL_S, 1);
    expect(rep.update(0.01, false)).toBe(false);
    expect(rep.update(0.2, true)).toBe(false);
  });
});
