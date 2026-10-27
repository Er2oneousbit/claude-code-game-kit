// ---------------------------------------------------------------------------
// separation.test.ts
// Purpose : Ghosts must not stack into one sprite (found in the first screenshot).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { separate } from "../src/core/separation";

const apply = (ps: { x: number; y: number }[], min: number) =>
  separate(ps, min).map((p, i) => ({ x: ps[i].x + p.x, y: ps[i].y + p.y }));

describe("separate", () => {
  it("leaves agents that are far enough apart alone", () => {
    expect(separate([{ x: 0, y: 0 }, { x: 2, y: 0 }], 0.8)).toEqual([{ x: 0, y: 0 }, { x: 0, y: 0 }]);
  });

  it("pushes two close agents to exactly the minimum distance", () => {
    const [a, b] = apply([{ x: 0, y: 0 }, { x: 0.2, y: 0 }], 0.8);
    expect(Math.hypot(b.x - a.x, b.y - a.y)).toBeCloseTo(0.8, 6);
  });

  it("splits agents on the exact same spot deterministically", () => {
    const [a, b] = apply([{ x: 1, y: 1 }, { x: 1, y: 1 }], 0.8);
    expect(a.x).toBeLessThan(b.x);
    expect(a.y).toBe(b.y);
  });

  it("spreads a stack of three", () => {
    const out = apply([{ x: 1, y: 1 }, { x: 1.05, y: 1 }, { x: 1, y: 1.05 }], 0.8);
    const spread = Math.max(...out.map((p) => p.x)) - Math.min(...out.map((p) => p.x));
    expect(spread).toBeGreaterThan(0.5);
  });
});
