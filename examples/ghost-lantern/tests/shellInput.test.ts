// ---------------------------------------------------------------------------
// shellInput.test.ts
// Purpose : The shell input's analog side (#274): poll() keeps the pads' stick and triggers, stick() applies the
//           player's deadzone and invert_y, triggers() go 0 to 1, a leaning stick holds move_* (isDown,
//           heldActions) without a stick binding, and held game actions leave out ui_*.
// Usage   : python tools/dev.py test
// Notes   : No browser: the pads are plain objects passed to poll(), so navigator.getGamepads is never read.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { DEFAULT_BINDINGS, type Bindings } from "../src/core/bindings";
import { ShellInput } from "../src/shell/input";

type PadState = { axes?: number[]; pressed?: number[]; values?: Record<number, number> };

/** A standard-mapping pad: 17 buttons, axes [lx, ly, rx, ry]. */
function pad({ axes = [0, 0, 0, 0], pressed = [], values = {} }: PadState): Gamepad {
  const buttons = Array.from({ length: 17 }, (_, i) => {
    const value = values[i] ?? (pressed.includes(i) ? 1 : 0);
    return { pressed: pressed.includes(i) || value > 0.5, touched: value > 0, value };
  });
  return { id: "Xbox Wireless Controller (STANDARD GAMEPAD)", connected: true, axes, buttons } as unknown as Gamepad;
}

function input(opts: { deadzone?: number; invertY?: boolean; bindings?: Bindings } = {}) {
  const bindings = opts.bindings ?? (structuredClone(DEFAULT_BINDINGS) as Bindings);
  return new ShellInput(() => bindings, () => opts.deadzone ?? 0.2, () => opts.invertY ?? false);
}

describe("ShellInput analog", () => {
  it("is zero without a pad", () => {
    const i = input();
    i.poll([]);
    expect(i.stick()).toEqual({ x: 0, y: 0 });
    expect(i.triggers()).toEqual({ left: 0, right: 0 });
    expect(i.heldActions()).toEqual([]);
  });

  it("shapes the stick with the deadzone and invert_y", () => {
    const i = input();
    i.poll([pad({ axes: [0.6, 0, 0, 0] })]);
    expect(i.stick().x).toBeCloseTo(0.5, 5);
    i.poll([pad({ axes: [0.1, 0.1, 0, 0] })]);
    expect(i.stick()).toEqual({ x: 0, y: 0 });
    const inv = input({ invertY: true });
    inv.poll([pad({ axes: [0, -1, 0, 0] })]);
    expect(inv.stick().y).toBeCloseTo(1, 5);
  });

  it("reads the triggers 0 to 1", () => {
    const i = input();
    i.poll([pad({ values: { 6: 0.525, 7: 1 } })]);
    expect(i.triggers().left).toBeCloseTo(0.5, 5);
    expect(i.triggers().right).toBe(1);
  });

  it("takes the stick from the pad leaning furthest and each trigger from the one pressed furthest", () => {
    const i = input();
    i.poll([pad({ axes: [0.3, 0, 0, 0], values: { 7: 0.9 } }), pad({ axes: [0, 1, 0, 0], values: { 6: 0.4 } })]);
    expect(i.stick().y).toBeCloseTo(1, 5);
    expect(i.triggers().right).toBeGreaterThan(0.8);
    expect(i.triggers().left).toBeGreaterThan(0.3);
  });

  it("holds move_* with a leaning stick, though no move_* binding names the stick", () => {
    const i = input();
    i.poll([pad({ axes: [-0.7, -0.7, 0, 0] })]);
    expect(i.isDown("move_left")).toBe(true);
    expect(i.isDown("move_up")).toBe(true);
    expect(i.isDown("move_right")).toBe(false);
    expect(i.heldActions().sort()).toEqual(["move_left", "move_up"]);
    i.poll([pad({})]);
    expect(i.isDown("move_left")).toBe(false);
  });

  it("lists held game actions, never ui_* ones", () => {
    const i = input();
    i.poll([pad({ pressed: [0, 12] })]); // south (ui_accept and jump), d-pad up (ui_up and move_up)
    expect(i.heldActions().sort()).toEqual(["jump", "move_up"]);
  });
});
