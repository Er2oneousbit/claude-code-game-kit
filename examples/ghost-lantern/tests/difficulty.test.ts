// ---------------------------------------------------------------------------
// difficulty.test.ts
// Purpose : The difficulty table (one row per kit difficulty, ordered from Story to Hard, Normal = the base
//           tuning, the speed pillar on Normal and Hard) and which difficulty a run uses (the URL flag, else the
//           player's saved setting from the kit's settings file, else Normal).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { Lantern } from "../src/core/lantern";
import { DIFFICULTIES, defaultSettings, settingsLoad, settingsText } from "../src/core/settings";
import { difficultyFor, lanternFor } from "../src/game/difficulty";
import { DIFFICULTY, GHOST, LANTERN, PLAYER } from "../src/game/tuning";

const ORDER = ["story", "easy", "normal", "hard"] as const;

describe("difficulty table", () => {
  it("has exactly the kit's difficulties", () => {
    expect(Object.keys(DIFFICULTY).sort()).toEqual([...DIFFICULTIES].sort());
  });

  it("Normal is the base tuning, with the dim burn from the first human playtest", () => {
    expect(LANTERN.dimBurn).toBe(3.0);
    expect(DIFFICULTY.normal.dimBurn).toBe(LANTERN.dimBurn);
    expect(DIFFICULTY.normal.brightBurn).toBe(LANTERN.brightBurn);
    expect(DIFFICULTY.normal.ghostSpeed).toEqual(GHOST.speed);
  });

  it("gets harder step by step: more oil burned, chasers never slower", () => {
    for (let i = 1; i < ORDER.length; i++) {
      const easier = DIFFICULTY[ORDER[i - 1]], harder = DIFFICULTY[ORDER[i]];
      expect(harder.dimBurn, ORDER[i]).toBeGreaterThan(easier.dimBurn);
      expect(harder.brightBurn, ORDER[i]).toBeGreaterThan(easier.brightBurn);
      expect(harder.ghostSpeed.chase, ORDER[i]).toBeGreaterThanOrEqual(easier.ghostSpeed.chase);
    }
    // Story and Easy also slow the chasers; Hard keeps Normal's speed (faster ghosts beat the lantern bot: tuning.ts)
    expect(DIFFICULTY.story.ghostSpeed.chase).toBeLessThan(DIFFICULTY.easy.ghostSpeed.chase);
    expect(DIFFICULTY.easy.ghostSpeed.chase).toBeLessThan(DIFFICULTY.normal.ghostSpeed.chase);
  });

  it("keeps bright light costly on every difficulty (the trade-off is the game)", () => {
    for (const d of ORDER) expect(DIFFICULTY[d].brightBurn / DIFFICULTY[d].dimBurn, d).toBeGreaterThanOrEqual(3);
  });

  it("keeps the pillar on Normal and Hard: you cannot outrun a chasing ghost in the dark", () => {
    expect(DIFFICULTY.normal.ghostSpeed.chase).toBeGreaterThan(PLAYER.speed);
    expect(DIFFICULTY.hard.ghostSpeed.chase).toBeGreaterThan(PLAYER.speed);
  });

  it("answers the playtest on Easy: ghosts near the player's speed, the oil lasting longer", () => {
    expect(Math.abs(DIFFICULTY.easy.ghostSpeed.chase - PLAYER.speed)).toBeLessThanOrEqual(0.15);
    const easy = new Lantern(lanternFor("easy")), normal = new Lantern(lanternFor("normal"));
    easy.update(10, false);
    normal.update(10, false);
    expect(easy.oil).toBeGreaterThan(normal.oil);
  });

  it("changes only the burn rates of the lantern", () => {
    for (const d of ORDER) {
      expect(lanternFor(d)).toEqual({ ...LANTERN, dimBurn: DIFFICULTY[d].dimBurn, brightBurn: DIFFICULTY[d].brightBurn });
    }
  });
});

describe("difficultyFor", () => {
  const withSetting = (difficulty: unknown) => {
    const s = defaultSettings();
    s.access.difficulty = difficulty as string;
    return s;
  };

  it("reads the player's setting (settings.access.difficulty)", () => {
    for (const d of ORDER) expect(difficultyFor("", withSetting(d))).toBe(d);
  });

  it("reads it through the kit's settings file, as saved by the menu", () => {
    const text = settingsText(withSetting("easy"));
    expect(difficultyFor("", settingsLoad(text).settings)).toBe("easy");
  });

  it("is Normal for a fresh settings file", () => {
    expect(difficultyFor("", defaultSettings())).toBe("normal");
  });

  it("lets ?difficulty= override the setting for one page load", () => {
    expect(difficultyFor("?autoplay&difficulty=hard", withSetting("story"))).toBe("hard");
    expect(difficultyFor("?difficulty=story", withSetting("hard"))).toBe("story");
  });

  it("ignores an unknown ?difficulty= and an unknown setting", () => {
    expect(difficultyFor("?difficulty=nightmare", withSetting("easy"))).toBe("easy");
    expect(difficultyFor("?difficulty=", withSetting("hard"))).toBe("hard");
    expect(difficultyFor("", withSetting("nightmare"))).toBe("normal");
    expect(difficultyFor("", withSetting(7))).toBe("normal");
  });
});
