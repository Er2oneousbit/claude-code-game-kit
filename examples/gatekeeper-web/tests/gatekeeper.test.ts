// ---------------------------------------------------------------------------
// gatekeeper.test.ts
// Purpose : The rules no model can change: the captain is the way in, bribes and
//           threats hurt, flattery wears off, turns run out.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): trust ceiling case, no single line opens the gate
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { applyIntent, newState, type State } from "../src/core/gatekeeper";
import { type Intent, INTENTS } from "../src/core/intent";
import { RULES } from "../src/game/tuning";

const play = (intents: Intent[]): State =>
  intents.reduce((s, i) => applyIntent(s, i, RULES).state, newState(RULES));

describe("gatekeeper rules", () => {
  it("opens for a greeting plus the captain's name", () => {
    expect(play(["greeting", "mentions_captain"]).outcome).toBe("open");
  });

  it("never opens without the captain, however charming", () => {
    const s = play(["greeting", "flattery", "flattery", "flattery", "question", "question", "flattery", "greeting"]);
    expect(s.outcome).toBe("turned_away");
    expect(s.trust).toBeLessThan(RULES.openAt);
  });

  it("flattery only counts twice", () => {
    const two = play(["flattery", "flattery"]).trust;
    expect(play(["flattery", "flattery", "flattery"]).trust).toBe(two);
  });

  it("two threats end the conversation", () => {
    expect(play(["threat", "threat"]).outcome).toBe("turned_away");
  });

  it("a bribe makes the captain alone not enough", () => {
    expect(play(["bribe", "mentions_captain"]).outcome).toBe("talking");
  });

  it("turns run out", () => {
    expect(play(Array<Intent>(RULES.turns).fill("question")).outcome).toBe("turned_away");
  });

  it("does nothing after the conversation is over", () => {
    const done = play(["greeting", "mentions_captain"]);
    expect(applyIntent(done, "threat", RULES).state).toBe(done);
  });

  it("a line the guard did not understand costs nothing", () => {
    expect(play(["other"]).trust).toBe(RULES.startTrust);
  });

  it("keeps trust between 0 and 100", () => {
    expect(play(["threat"]).trust).toBe(0);
    const big = { ...RULES, openAt: 1000, delta: { ...RULES.delta, greeting: 500 } };   // openAt out of reach: only the clamp matters
    expect(applyIntent(newState(big), "greeting", big).state.trust).toBe(100);
  });

  it("no single line opens the gate, whatever its intent (SOP-15: the game decides, not one model label)", () => {
    for (const i of INTENTS) expect(applyIntent(newState(RULES), i, RULES).state.outcome, i).not.toBe("open");
  });
});
