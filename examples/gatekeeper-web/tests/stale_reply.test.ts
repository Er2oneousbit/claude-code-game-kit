// ---------------------------------------------------------------------------
// stale_reply.test.ts
// Purpose : Regression test: a guard reply that lands AFTER "Start over" must not touch the new
//           game (once it did: old intent applied, a turn lost, history polluted, and one greeting
//           then opened the gate). The Controller runs in Node on a fake page (support/fakePage.ts).
// Usage   : python tools/dev.py test
// Notes   : Found by a review with Claude (Fable 5.1, claude-fable-5-1), ported as a regression test.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { afterEach, describe, expect, it, vi } from "vitest";
import { newState, type State } from "../src/core/gatekeeper";
import type { BrainReply, NpcBrain } from "../src/game/brain";
import { Controller } from "../src/game/controller";
import type { Turn } from "../src/game/prompt";
import { RULES } from "../src/game/tuning";
import { fakePage } from "./support/fakePage";

type Inside = { state: State; history: Turn[]; brain: NpcBrain; begin(b: NpcBrain): void };
const inside = (c: Controller) => c as unknown as Inside;

/** A model brain whose reply arrives only when the test says so. */
function slowBrain() {
  let answer!: (r: BrainReply) => void;
  const brain: NpcBrain = { kind: "model", reply: () => new Promise<BrainReply>((res) => { answer = res; }) };
  return { brain, answer: (r: BrainReply) => answer(r) };
}

const greeter: NpcBrain = { kind: "model", reply: async () => ({ intent: "greeting", line: "Evening.", source: "model", ms: 1 }) };

afterEach(() => vi.unstubAllGlobals());

describe("Start over while the guard is still thinking", () => {
  it("the old reply does not change the new game, and one greeting does not open the gate", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();                                   // wires the buttons (no WebGPU in Node: fine)
    const slow = slowBrain();
    inside(c).begin(slow.brain);                       // what "Talk to the AI guard" does once loaded

    const pending = c.say("Captain Wren sent me.");    // the model is thinking
    page.byId("again").onclick!();                     // the player clicks "Start over" while waiting
    slow.answer({ intent: "mentions_captain", line: "Wren? Hm.", source: "model", ms: 5 });
    await pending;

    expect(inside(c).state).toEqual(newState(RULES));
    expect(inside(c).history).toHaveLength(0);
    expect(page.logTexts()).not.toContain("Wren? Hm.");

    // Before the fix the new game started at 65 trust, so this greeting opened the gate (65 + 5 = 70)
    inside(c).brain = greeter;
    await c.say("Good evening.");
    expect(inside(c).state.outcome).toBe("talking");
    expect(inside(c).state.trust).toBe(RULES.startTrust + RULES.delta.greeting);
  });

  it("the new game takes a line at once, before the old reply has landed", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    const slow = slowBrain();
    inside(c).begin(slow.brain);

    const pending = c.say("Captain Wren sent me.");
    page.byId("again").onclick!();
    inside(c).brain = greeter;
    await c.say("Good evening.");                      // was ignored: busy stayed set by the old line
    expect(page.logTexts()).toContain("You: Good evening.");
    expect(inside(c).history).toHaveLength(1);

    slow.answer({ intent: "mentions_captain", line: "Wren? Hm.", source: "model", ms: 5 });
    await pending;
    expect(inside(c).history).toHaveLength(1);         // the late reply is dropped, not appended
    expect(inside(c).state.trust).toBe(RULES.startTrust + RULES.delta.greeting);
  });
});
