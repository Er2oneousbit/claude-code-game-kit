// ---------------------------------------------------------------------------
// audioAccess.test.ts
// Purpose : The volume sliders reach the right buses exactly once (ambience under sfx is not turned down twice), bad
//           slider values are clamped, a bus cycle cannot hang, and directional captions get the arrow for the side
//           the sound comes from and none while it is on screen.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { captionArrow, userBusGains } from "../src/core/audioAccess";

const SLIDERS = { master: 0.9, music: 0.5, sfx: 0.25, ui: 0.75, voice: 0.6 };

describe("userBusGains", () => {
  it("maps each slider to its bus", () => {
    const buses = { master: {}, music: { parent: "master" }, sfx: { parent: "master" }, ui: { parent: "master" },
                    dialogue: { parent: "master" }, ambience: { parent: "master" } };
    expect(userBusGains(buses, SLIDERS)).toEqual({ master: 0.9, music: 0.5, sfx: 0.25, ui: 0.75, dialogue: 0.6,
                                                   ambience: 0.25 });
  });

  it("never applies a slider twice down one branch", () => {
    const buses = { master: {}, sfx: { parent: "master" }, ambience: { parent: "sfx" }, foley: { parent: "sfx" },
                    stingers: { parent: "music" }, music: {} };
    expect(userBusGains(buses, SLIDERS)).toEqual({ master: 0.9, sfx: 0.25, ambience: 1, foley: 1, stingers: 1,
                                                   music: 0.5 });
  });

  it("clamps bad slider values and survives a cycle", () => {
    const bad = { master: 2, music: -1, sfx: Number.NaN, ui: 0.5, voice: 0.5 } as typeof SLIDERS;
    expect(userBusGains({ master: {}, music: {}, sfx: {} }, bad)).toEqual({ master: 1, music: 0, sfx: 1 });
    expect(userBusGains({ a: { parent: "b" }, b: { parent: "a" } }, SLIDERS)).toEqual({ a: 1, b: 1 });
  });
});

describe("captionArrow", () => {
  const W = 320, H = 180; // half of a 640 x 360 view
  it("shows nothing while the source is on screen, edges included", () => {
    expect(captionArrow(0, 0, W, H)).toBe("");
    expect(captionArrow(W, -H, W, H)).toBe("");
  });

  it("points at the side the sound comes from (y grows downwards)", () => {
    const cases: [number, number, string][] = [
      [500, 0, "→"], [-500, 0, "←"], [0, -400, "↑"], [0, 400, "↓"],
      [500, 500, "↘"], [-500, 500, "↙"], [-500, -500, "↖"], [500, -500, "↗"],
      [900, 120, "→"], // mostly right, slightly down: still right
    ];
    for (const [dx, dy, arrow] of cases) expect(captionArrow(dx, dy, W, H), `${dx},${dy}`).toBe(arrow);
  });

  it("ignores positions that are not numbers", () => {
    expect(captionArrow(Number.NaN, 0, W, H)).toBe("");
  });
});

// {{FOOTER}}
