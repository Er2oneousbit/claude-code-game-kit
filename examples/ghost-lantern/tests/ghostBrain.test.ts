// ---------------------------------------------------------------------------
// ghostBrain.test.ts
// Purpose : The behaviors players must be able to rely on (SOP-14 step 6), checked
//           against the real tuning: ghosts chase in the dark, flee bright light,
//           wander when far away, and do not flicker between close scores.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { pickAction, scoreActions } from "../src/core/ghostBrain";
import { BRAIN } from "../src/game/tuning";

const decide = (distance: number, light: number, memory = 0, current: "chase" | "flee" | "wander" = "wander") =>
  pickAction(scoreActions({ distance, light, memory }, BRAIN), current, BRAIN.inertia);

describe("ghost brain (utility AI)", () => {
  it("chases a nearby player in the dark", () => {
    expect(decide(2, 0)).toBe("chase");
  });

  it("flees when standing in strong light", () => {
    expect(decide(1, 0.8)).toBe("flee");
  });

  it("never chases into strong light, however close", () => {
    for (const d of [0.5, 1, 2, 3]) expect(decide(d, 0.7, 1, "chase")).not.toBe("chase");
  });

  it("wanders when the player is out of range and forgotten", () => {
    expect(decide(BRAIN.senseRange + 1, 0, 0)).toBe("wander");
  });

  it("keeps chasing for a while from memory after losing the player", () => {
    expect(decide(BRAIN.senseRange + 1, 0, 1, "chase")).toBe("chase");
  });

  it("does not flip actions over a tiny score difference (inertia)", () => {
    // Find a distance where chase only just beats wander, then check a chasing ghost keeps chasing
    // and a wandering ghost keeps wandering.
    const d = BRAIN.senseRange * (1 - (BRAIN.wanderBase + BRAIN.inertia / 2));
    expect(decide(d, 0, 0, "chase")).toBe("chase");
    expect(decide(d, 0, 0, "wander")).toBe("wander");
  });

  it("keeps every score between 0 and 1", () => {
    for (const s of [scoreActions({ distance: 0, light: 1, memory: 1 }, BRAIN), scoreActions({ distance: 99, light: 0, memory: 0 }, BRAIN)]) {
      for (const v of Object.values(s)) expect(v).toBeGreaterThanOrEqual(0), expect(v).toBeLessThanOrEqual(1);
    }
  });
});
