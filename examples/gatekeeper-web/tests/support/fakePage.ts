// ---------------------------------------------------------------------------
// fakePage.ts
// Purpose : Just enough page and scene for the Controller to run in Node: elements by id, a chat
//           log you can read back, and a GateScene stand-in whose "create" event you fire by hand.
// Usage   : const page = fakePage("?autoplay"); const c = new Controller(page.scene as never); await c.start()
//           page.byId("line").value = "Hello"; page.submit(); page.logTexts(); page.fireCreate()
// Notes   : Not a test file (vitest only collects *.test.ts). Call it before constructing a Controller:
//           it stubs the globals `document` and `location`, which the Controller reads at that point.
//           syncCreate: "create" fires inside events.once (Phaser fires it a frame later; same result
//           unless the test is about what happens in between).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { vi } from "vitest";

export type FakeEl = {
  onclick: null | (() => void);
  onsubmit: null | ((e: { preventDefault(): void }) => void);
  style: Record<string, string>;
  textContent: string;
  innerHTML: string;
  value: string;
  disabled: boolean;
  className: string;
  scrollTop: number;
  scrollHeight: number;
  children: unknown[];
  firstElementChild: { style: Record<string, string> };
  focus(): void;
  append(...nodes: unknown[]): void;
};

function el(): FakeEl {
  let html = "";
  return {
    onclick: null, onsubmit: null, style: {}, textContent: "", value: "", disabled: false, className: "",
    scrollTop: 0, scrollHeight: 0, children: [], firstElementChild: { style: {} },
    get innerHTML() { return html; },
    set innerHTML(v: string) { html = v; this.children = []; },   // log.innerHTML = "" clears the chat
    focus() {},
    append(...nodes: unknown[]) { this.children.push(...nodes); },
  };
}

export function fakePage(search = "", { syncCreate = true } = {}) {
  const ids = new Map<string, FakeEl>();
  const byId = (id: string): FakeEl => {
    if (!ids.has(id)) ids.set(id, el());
    return ids.get(id)!;
  };
  vi.stubGlobal("location", { search });
  vi.stubGlobal("document", { getElementById: byId, createElement: () => el() });
  const queued: (() => void)[] = [];
  const scene = {
    show: vi.fn(), finish: vi.fn(),
    scene: { restart: vi.fn() },
    events: { once: (_event: string, fn: () => void) => (syncCreate ? fn() : queued.push(fn)) },
  };
  return {
    byId,
    scene,
    /** The text of every chat line, oldest first ("You: ...", the guard's words, sys notes). */
    logTexts: () => (byId("log").children as FakeEl[]).map((p) => String(p.children[0])),
    /** Presses Enter in the chat box. */
    submit: () => byId("say").onsubmit!({ preventDefault() {} }),
    /** Fires the queued scene "create" events (with syncCreate: false). */
    fireCreate: () => queued.splice(0).forEach((fn) => fn()),
  };
}
