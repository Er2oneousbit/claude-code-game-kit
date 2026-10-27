// ---------------------------------------------------------------------------
// controller_extras.test.ts
// Purpose : Regression tests for smaller Controller defects: typed text dropped while the guard
//           is thinking, a doubled intro when ?autoplay&llm=1 meets a failed model load, two
//           restarts from a double click, a broken model engine asked forever, and player text
//           longer than MAX_INPUT stored and sent whole.
// Usage   : python tools/dev.py test
// Notes   : Runs the Controller in Node on a fake page (support/fakePage.ts). WebLLM is mocked: no
//           model, no download. The first two cases were found by a review with Claude
//           (Fable 5.1, claude-fable-5-1).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_INPUT } from "../src/core/intent";
import type { BrainReply, NpcBrain } from "../src/game/brain";
import { Controller } from "../src/game/controller";
import type { Turn } from "../src/game/prompt";
import { fakePage } from "./support/fakePage";

vi.mock("@mlc-ai/web-llm", () => ({
  CreateWebWorkerMLCEngine: vi.fn(async () => { throw new Error("mocked: never reached"); }),
  hasModelInCache: vi.fn(async () => false),
}));

type Inside = { history: Turn[]; brain: NpcBrain; begin(b: NpcBrain): void };
const inside = (c: Controller) => c as unknown as Inside;
const HALT = "Halt. The gate is closed.";

afterEach(() => vi.unstubAllGlobals());

describe("controller", () => {
  it("keeps a line typed while the guard is thinking, and sends it on the next Enter", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    let answer!: (r: BrainReply) => void;
    let calls = 0;
    inside(c).begin({
      kind: "model",
      reply: () => {
        calls += 1;
        if (calls === 1) return new Promise<BrainReply>((res) => { answer = res; });
        return Promise.resolve({ intent: "mentions_captain", line: "Wren? Then come in.", source: "model", ms: 1 });
      },
    });

    const pending = c.say("Good evening.");            // first line, model thinking
    page.byId("line").value = "Captain Wren sent me."; // the player types the winning line and presses Enter
    page.submit();
    expect(page.byId("line").value).toBe("Captain Wren sent me.");   // was cleared and lost
    expect(page.logTexts()).not.toContain("You: Captain Wren sent me.");

    answer({ intent: "greeting", line: "Evening.", source: "model", ms: 1 });
    await pending;
    page.submit();                                     // Enter again once Bram has answered
    expect(page.byId("line").value).toBe("");
    expect(page.logTexts()).toContain("You: Captain Wren sent me.");
  });

  it("?autoplay&llm=1 with a failed model load shows the intro once", async () => {
    const page = fakePage("?autoplay&llm=1");
    vi.stubGlobal("navigator", { gpu: { requestAdapter: async () => ({}) } });   // WebGPU "present"
    vi.stubGlobal("Worker", class { constructor() { throw new Error("worker cannot start"); } });
    const c = new Controller(page.scene as never);
    await c.start();                                   // loadModel fails and begins with the scripted guard
    expect(page.logTexts().filter((t) => t === HALT)).toHaveLength(1);   // was 2
    expect(page.byId("status").textContent).toContain("could not load");
  });

  it("a double click on Start over restarts once", async () => {
    const page = fakePage("", { syncCreate: false });
    const c = new Controller(page.scene as never);
    await c.start();
    page.byId("useScript").onclick!();
    page.byId("again").onclick!();
    page.byId("again").onclick!();                     // second click before the scene came back
    page.fireCreate();
    expect(page.scene.scene.restart).toHaveBeenCalledTimes(1);
    expect(page.logTexts().filter((t) => t === HALT)).toHaveLength(1);

    page.byId("again").onclick!();                     // a later click works again
    page.fireCreate();
    expect(page.scene.scene.restart).toHaveBeenCalledTimes(2);
  });

  it("a fatal reply hands the rest of the game to the scripted guard", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    const broken: NpcBrain = {
      kind: "model",
      reply: async () => ({ intent: "greeting", line: "Evening.", source: "fallback", ms: 3, why: "model error: device lost", fatal: true }),
    };
    inside(c).begin(broken);
    await c.say("Good evening.");
    expect(inside(c).brain.kind).toBe("fallback");
    expect(page.logTexts()).toContain("The AI guard stopped working; the scripted guard takes over.");
    expect(inside(c).history).toHaveLength(1);         // the fatal turn itself still counts (it has a scripted reply)
  });

  it("two model timeouts in a row hand the game to the scripted guard; one does not", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    const slow: NpcBrain = {
      kind: "model",
      reply: async () => ({ intent: "greeting", line: "Evening.", source: "fallback", ms: 12000, why: "model too slow" }),
    };
    inside(c).begin(slow);
    await c.say("Good evening.");
    expect(inside(c).brain.kind).toBe("model");          // one slow reply can be a hiccup
    await c.say("Nice armor.");
    expect(inside(c).brain.kind).toBe("fallback");       // two in a row: stop costing 12 s per line
  });

  it("cuts the player's line to MAX_INPUT before it is stored or sent", async () => {
    const page = fakePage();
    const c = new Controller(page.scene as never);
    await c.start();
    const seen: string[] = [];
    inside(c).begin({
      kind: "model",
      reply: async (_h, player) => { seen.push(player); return { intent: "other", line: "What?", source: "model", ms: 1 }; },
    });
    await c.say("A".repeat(MAX_INPUT * 3));
    expect(seen[0]).toHaveLength(MAX_INPUT);
    expect(inside(c).history[0].player).toHaveLength(MAX_INPUT);
    expect(page.logTexts()).toContain(`You: ${"A".repeat(MAX_INPUT)}`);
  });
});
