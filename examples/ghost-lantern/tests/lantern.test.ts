// ---------------------------------------------------------------------------
// lantern.test.ts
// Purpose : The lantern rules the GDD depends on: bright burns faster and reaches
//           farther, an empty lantern scares nothing, refills cap at max.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { Lantern } from "../src/core/lantern";
import { LANTERN } from "../src/game/tuning";

describe("Lantern", () => {
  it("burns oil faster when bright", () => {
    const dim = new Lantern(LANTERN), bright = new Lantern(LANTERN);
    dim.update(1, false);
    bright.update(1, true);
    expect(bright.oil).toBeLessThan(dim.oil);
  });

  it("reaches farther when bright (the trade-off is real)", () => {
    const l = new Lantern(LANTERN);
    l.update(0, false);
    const dimRadius = l.radius();
    l.update(0, true);
    expect(l.radius()).toBeGreaterThan(dimRadius);
  });

  it("gives full light at a bright lantern and none at the edge", () => {
    const l = new Lantern(LANTERN);
    l.update(0, true);
    expect(l.lightAt(0)).toBe(LANTERN.brightPower);
    expect(l.lightAt(l.radius())).toBe(0);
  });

  it("scares nothing when empty, but still glows a little", () => {
    const l = new Lantern(LANTERN);
    l.update(1000, true);
    expect(l.empty).toBe(true);
    expect(l.lightAt(0)).toBe(0);
    expect(l.radius()).toBe(LANTERN.emptyRadius);
    expect(l.bright).toBe(false);
  });

  it("scares far less when dim: dim light is for seeing, bright light shields", () => {
    const l = new Lantern(LANTERN);
    l.update(0, false);
    const dim = l.lightAt(0.5);
    l.update(0, true);
    expect(dim).toBeLessThan(0.5 * l.lightAt(0.5));
  });

  it("never refills past the maximum", () => {
    const l = new Lantern(LANTERN);
    l.update(1, false);
    l.refill(1000);
    expect(l.oil).toBe(LANTERN.maxOil);
  });
});
