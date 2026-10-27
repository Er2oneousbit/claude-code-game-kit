// ---------------------------------------------------------------------------
// scenario.test.ts
// Purpose : The scenario pair as a unit test (SOP-14 step 6): over every robot start, the careful
//           bot delivers all five parcels in time and the reckless bot gets caught. If the
//           reckless bot ever wins, the robot does not matter and pillar 2 is false.
// Usage   : python tools/dev.py test   (the same runs play in the browser with ?autoplay)
// Notes   : Fixed steps, no randomness: a failing start replays exactly.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { Bot, type BotMode } from "../src/core/bot";
import { LEVEL } from "../src/core/level";
import { Sim } from "../src/core/sim";

const MAX_STEPS = 60 * 120;
const STARTS = LEVEL.patrol.map((_, i) => i);

function play(mode: BotMode, robotStart: number): Sim {
  const sim = new Sim({ robotStart });
  const bot = new Bot(mode);
  for (let i = 0; i < MAX_STEPS && sim.outcome === "playing"; i++) sim.step(bot.think(sim));
  return sim;
}

describe("scenario pair", () => {
  test.each(STARTS)("careful bot delivers everything, robot start %i", (start) => {
    const sim = play("careful", start);
    expect(sim.outcome).toBe("won");
    expect(sim.timeLeft).toBeGreaterThan(5); // a real margin, not a photo finish
  });

  test.each(STARTS)("reckless bot gets caught, robot start %i", (start) => {
    expect(play("reckless", start).outcome).toBe("caught");
  });
});
