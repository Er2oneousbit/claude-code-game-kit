// ---------------------------------------------------------------------------
// shell_flow.test.ts
// Purpose : The game inside the kit's shell (#182): "Quit to title" ends the conversation (a reply still on its
//           way is dropped), and "Play" again starts a new one with the guard the player already picked, one
//           intro, no old lines. "Start over" keeps working as before while main.ts listens for both.
// Usage   : python tools/dev.py test
// Notes   : The Controller runs in Node on a fake page (support/fakePage.ts). main.ts calls closed() when the
//           scene shuts down and reopened() when it is created again; a restart fires both, which must not
//           start a second game on top of the one reset() begins.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { afterEach, describe, expect, it, vi } from "vitest";
import { newState, type State } from "../src/core/gatekeeper";
import type { BrainReply, NpcBrain } from "../src/game/brain";
import { Controller } from "../src/game/controller";
import type { Turn } from "../src/game/prompt";
import { RULES } from "../src/game/tuning";
import { fakePage } from "./support/fakePage";

type Inside = { state: State; history: Turn[]; brain: NpcBrain; begun: boolean; begin(b: NpcBrain): void };
const inside = (c: Controller) => c as unknown as Inside;
const INTRO = "Halt. The gate is closed.";

afterEach(() => vi.unstubAllGlobals());

describe("quit to title and Play again", () => {
  it("drops the reply on its way and starts a new conversation with the same guard, one intro", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    let answer!: (r: BrainReply) => void;
    const slow: NpcBrain = { kind: "model", reply: () => new Promise<BrainReply>((res) => { answer = res; }) };
    inside(c).begin(slow);

    const pending = c.say("Captain Wren sent me.");
    c.closed();                                         // the shell stopped the scene: quit to title
    answer({ intent: "mentions_captain", line: "Wren? Hm.", source: "model", ms: 5 });
    await pending;
    expect(inside(c).history).toHaveLength(0);

    c.reopened();                                       // "Play" from the main menu
    expect(inside(c).brain).toBe(slow);                 // the loaded model stays: no second 880 MB load
    expect(inside(c).state).toEqual(newState(RULES));
    expect(page.logTexts().filter((t) => t === INTRO)).toHaveLength(1);
    expect(page.logTexts()).not.toContain("You: Captain Wren sent me.");
    expect(page.scene.show).toHaveBeenLastCalledWith(newState(RULES), false);
  });

  it("before a guard was picked, Play again shows the start panel and begins nothing", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    c.closed();
    c.reopened();
    expect(inside(c).begun).toBe(false);
    expect(page.logTexts()).toHaveLength(0);
  });

  it("Start over still gives one new game when closed() and reopened() fire for its restart", async () => {
    const page = fakePage("", { syncCreate: false });
    const c = new Controller(page.scene as never);
    await c.start();
    page.byId("useScript").onclick!();
    page.byId("again").onclick!();                      // restart: Phaser shuts the scene down, then creates it
    c.closed();
    c.reopened();
    page.fireCreate();                                  // the "create" reset() waits for
    expect(page.logTexts().filter((t) => t === INTRO)).toHaveLength(1);
  });
});
