// ---------------------------------------------------------------------------
// analog.test.ts
// Purpose : The analog shaping in src/core/analog.ts (#274): the radial, rescaled stick deadzone, invert_y, the
//           trigger deadzone, the move_* actions a leaning stick holds, and broken driver values.
// Usage   : python tools/dev.py test
// Notes   : The same cases as the Bevy shell's logic/analog.rs tests, with up as -y (the browser's convention).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { STICK_HOLD_MIN, TRIGGER_DEADZONE, stick, stickActions, trigger } from "../src/core/analog";

const close = (a: { x: number; y: number }, x: number, y: number) => {
  expect(a.x).toBeCloseTo(x, 5);
  expect(a.y).toBeCloseTo(y, 5);
};

describe("stick", () => {
  it("is still inside the deadzone and rescales from zero past it", () => {
    close(stick(0.15, 0.1, 0.2, false), 0, 0);
    const { x } = stick(0.21, 0, 0.2, false); // just past the deadzone: a small push, never a jump to 0.2
    expect(x).toBeGreaterThan(0);
    expect(x).toBeLessThan(0.02);
    close(stick(0.6, 0, 0.2, false), 0.5, 0);
    close(stick(1, 0, 0.2, false), 1, 0);
    close(stick(-0.3, 0.4, 0, false), -0.3, 0.4); // no deadzone: the raw value
  });

  it("clamps a diagonal past full deflection to length 1 and keeps its direction", () => {
    const d = stick(1, 1, 0.2, false);
    expect(Math.hypot(d.x, d.y)).toBeCloseTo(1, 5);
    expect(d.x).toBeCloseTo(d.y, 6);
  });

  it("invert_y flips only the vertical axis", () => {
    close(stick(0, -1, 0.2, true), 0, 1);
    close(stick(1, 0, 0.2, true), 1, 0);
  });

  it("treats broken driver values as 0", () => {
    close(stick(Number.NaN, -1, 0, false), 0, -1);
    close(stick(Number.POSITIVE_INFINITY, 0, 0.2, false), 0, 0);
  });
});

describe("trigger", () => {
  it("rescales past its deadzone and never goes negative", () => {
    expect(trigger(0.04)).toBe(0);
    expect(trigger(1)).toBe(1);
    expect(trigger(0.525, TRIGGER_DEADZONE)).toBeCloseTo(0.5, 5);
    expect(trigger(-0.5, 0)).toBe(0);
    expect(trigger(Number.NaN, 0)).toBe(0);
  });
});

describe("stickActions", () => {
  it("holds move_* past the deadzone, never below STICK_HOLD_MIN", () => {
    expect(stickActions(-0.5, 0, 0.2, false)).toEqual(["move_left"]);
    expect(stickActions(0.5, -0.5, 0.2, false)).toEqual(["move_right", "move_up"]);
    expect(stickActions(STICK_HOLD_MIN - 0.05, 0, 0, false)).toEqual([]); // a drifting stick with deadzone 0
    expect(stickActions(0.3, 0, 0.4, false)).toEqual([]); // the player's bigger deadzone wins
  });

  it("honours invert_y", () => {
    expect(stickActions(0, -0.8, 0.2, true)).toEqual(["move_down"]);
  });
});

// {{FOOTER}}
