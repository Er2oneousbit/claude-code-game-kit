// ---------------------------------------------------------------------------
// displayStaging.test.ts
// Purpose : What the golden display_staging cases leave open: values compared by value (a staged resolution equal
//           to the applied one is no change), the confirm counting real seconds (RealClock) whatever the frame's
//           game time, and the HUD font size helper (#309).
// Usage   : python tools/dev.py test
// Notes   : No browser: the clock is a stand-in function. Expected values are worked out by hand here.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): new (#308, #309)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { DisplayStaging, RealClock, sameValue } from "../src/core/displayStaging";
import { HUD_MIN_PX, hudFontPx, hudScale } from "../src/core/hud";
import { defaultSettings } from "../src/core/settings";

const fresh = () => new DisplayStaging(defaultSettings().display);

describe("DisplayStaging by value", () => {
  it("drops a staged resolution equal to the applied one (a new array, same numbers)", () => {
    const st = fresh();
    st.stage("resolution", [1280, 720]);
    expect(st.dirty).toBe(true);
    st.stage("resolution", [1920, 1080]);
    expect(st.dirty).toBe(false);
    expect(st.apply()).toEqual([]);
  });

  it("copies what it is given and what it hands out", () => {
    const res: [number, number] = [1600, 900];
    const st = fresh();
    st.stage("resolution", res);
    res[0] = 1;
    const calls = st.apply();
    expect(calls).toEqual([["resolution", [1600, 900]]]);
    (calls[0][1] as number[])[0] = 2;
    expect(st.applied.resolution).toEqual([1600, 900]);
  });

  it("sameValue compares numbers, arrays and objects by value", () => {
    expect(sameValue(1, 1.0)).toBe(true);
    expect(sameValue([1, [2, 3]], [1, [2, 3]])).toBe(true);
    expect(sameValue({ a: [1] }, { a: [1] })).toBe(true);
    expect(sameValue([1, 2], [1, 2, 3])).toBe(false);
    expect(sameValue(true, 1)).toBe(false);
  });
});

describe("the confirm counts real time", () => {
  it("reverts after 15 s on the clock, however few frames ran or how slow the game was", () => {
    let ms = 1000;
    const clock = new RealClock(() => ms);
    const st = fresh();
    st.stage("mode", "fullscreen");
    st.apply();
    clock.reset();
    ms += 14_000; // one frame, 14 s later (the tab was in the background, or the game ran at 10 % speed)
    expect(st.tick(clock.elapsed())).toEqual([]);
    expect(st.seconds()).toBe(1);
    ms += 1_000;
    expect(st.tick(clock.elapsed())).toEqual([["mode", "windowed"]]);
    expect(st.seconds()).toBeNull();
  });

  it("does not move while the clock stands still, however many frames tick", () => {
    const clock = new RealClock(() => 5000);
    const st = fresh();
    st.stage("mode", "borderless");
    st.apply();
    for (let i = 0; i < 10_000; i++) st.tick(clock.elapsed());
    expect(st.seconds()).toBe(15);
  });

  it("never runs backwards", () => {
    let ms = 10_000;
    const clock = new RealClock(() => ms);
    ms -= 500;
    expect(clock.elapsed()).toBe(0);
  });
});

describe("hudFontPx (#309)", () => {
  it("follows ui_scale times text_scale, in whole pixels", () => {
    const s = defaultSettings();
    expect(hudFontPx(16, s)).toBe(16);
    s.display.ui_scale = 1.25;
    s.access.text_scale = 1.5;
    expect(hudScale(s)).toBeCloseTo(1.875);
    expect(hudFontPx(16, s)).toBe(30);
  });

  it("never goes below HUD_MIN_PX", () => {
    const s = defaultSettings();
    s.display.ui_scale = 0.75;
    s.access.text_scale = 0.75;
    expect(hudFontPx(4, s)).toBe(HUD_MIN_PX);
  });
});
