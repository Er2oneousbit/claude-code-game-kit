// ---------------------------------------------------------------------------
// follow.test.ts
// Purpose : Vitest unit tests for the spring follow. Doubles as the example of how to
//           write engine-free tests in this project.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { Follow3, smoothDamp } from "../src/core/follow";

const run = (smoothTime: number, dt: number, seconds: number) => {
  const f = new Follow3(smoothTime);
  const path: number[] = [];
  for (let t = 0; t < seconds; t += dt) path.push(f.step({ x: 10, y: 0, z: 0 }, dt).x);
  return path;
};

describe("smoothDamp / Follow3", () => {
  it("gets close to the target within a few smooth times", () => {
    const path = run(0.2, 1 / 60, 1.5);
    expect(path[path.length - 1]).toBeCloseTo(10, 1);
  });

  it("never overshoots (critically damped)", () => {
    expect(Math.max(...run(0.2, 1 / 60, 3))).toBeLessThanOrEqual(10 + 1e-6);
  });

  it("does not depend much on frame rate", () => {
    const at60 = run(0.3, 1 / 60, 0.5).at(-1)!;
    const at20 = run(0.3, 1 / 20, 0.5).at(-1)!;
    expect(Math.abs(at60 - at20)).toBeLessThan(0.3);
  });

  it("stays put when already on target", () => {
    expect(smoothDamp(5, 5, 0, 0.2, 1 / 60)).toEqual([5, 0]);
  });

  it("snap() jumps without carrying old speed", () => {
    const f = new Follow3(0.2);
    f.step({ x: 10, y: 0, z: 0 }, 0.1);
    f.snap({ x: 0, y: 0, z: 0 });
    expect(f.step({ x: 0, y: 0, z: 0 }, 0.1)).toEqual({ x: 0, y: 0, z: 0 });
  });
});
