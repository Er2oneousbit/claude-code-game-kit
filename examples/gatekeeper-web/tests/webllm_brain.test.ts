// ---------------------------------------------------------------------------
// webllm_brain.test.ts
// Purpose : Regression tests for WebLlmBrain against a fake engine and a fake worker: a slow reply
//           and an engine error are told apart (only the error is fatal), and load() gives up when
//           the worker errors or the download stalls, stopping the worker, instead of never settling.
// Usage   : python tools/dev.py test
// Notes   : WebLLM is mocked: no model, no download, no GPU. Fake timers stand in for the 12 s reply
//           timeout and the 60 s stall window. The reply cases were found by a review with Claude
//           (Fable 5.1, claude-fable-5-1).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { CreateWebWorkerMLCEngine } from "@mlc-ai/web-llm";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FallbackBrain } from "../src/game/brain";
import { LOAD_STALL_MS, REPLY_TIMEOUT_MS } from "../src/game/tuning";
import { WebLlmBrain } from "../src/game/webllmBrain";

vi.mock("@mlc-ai/web-llm", () => ({
  CreateWebWorkerMLCEngine: vi.fn(),
  hasModelInCache: vi.fn(async () => false),
}));

const pick = () => 0;
const answer = (content: string) => Promise.resolve({ choices: [{ message: { content } }] });

function fakeEngine(create: () => Promise<unknown>) {
  return { chat: { completions: { create: vi.fn(create) } }, interruptGenerate: vi.fn() };
}

/** A brain around a fake engine (the constructor is private: load() needs a real worker). */
function make(create: () => Promise<unknown>) {
  const engine = fakeEngine(create);
  const Ctor = WebLlmBrain as unknown as new (e: unknown, f: FallbackBrain, p: () => number) => WebLlmBrain;
  return { brain: new Ctor(engine, new FallbackBrain(pick), pick), engine };
}

class FakeWorker {
  static last: FakeWorker;
  readonly listeners = new Map<string, Set<(e: Event) => void>>();
  readonly terminate = vi.fn();
  constructor() { FakeWorker.last = this; }
  addEventListener(type: string, fn: (e: Event) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(fn);
  }
  removeEventListener(type: string, fn: (e: Event) => void) { this.listeners.get(type)?.delete(fn); }
  emit(type: string, e: unknown) { for (const fn of this.listeners.get(type) ?? []) fn(e as Event); }
}

type Progress = (r: { progress: number; text: string; timeElapsed: number }) => void;
/** Makes CreateWebWorkerMLCEngine hang forever, handing the test its progress callback. */
function hangingCreate(): { progress: () => Progress } {
  let cb!: Progress;
  vi.mocked(CreateWebWorkerMLCEngine).mockImplementation((_w, _id, cfg) => {
    cb = cfg!.initProgressCallback as Progress;
    return new Promise(() => {});
  });
  return { progress: () => cb };
}

/** Settles a promise into a readable outcome without an unhandled rejection. */
function watch<T>(p: Promise<T>) {
  const out: { done: boolean; error?: Error } = { done: false };
  p.then(() => { out.done = true; }, (e: Error) => { out.done = true; out.error = e; });
  return out;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.mocked(CreateWebWorkerMLCEngine).mockReset();
});

describe("WebLlmBrain.reply", () => {
  it("a slow engine falls back with 'model too slow' and is not fatal", async () => {
    vi.useFakeTimers();
    const { brain, engine } = make(() => new Promise(() => {}));
    const p = brain.reply([], "Hello there.", "wary");
    await vi.advanceTimersByTimeAsync(REPLY_TIMEOUT_MS);
    const r = await p;
    expect(r.source).toBe("fallback");
    expect(r.why).toBe("model too slow");
    expect(r.fatal).toBeFalsy();
    expect(engine.interruptGenerate).toHaveBeenCalledTimes(1);
  });

  it("an engine error is called a model error, not 'model too slow', and is fatal", async () => {
    const { brain } = make(() => Promise.reject(new Error("WebGPU device lost")));
    const r = await brain.reply([], "Hello there.", "wary");
    expect(r.source).toBe("fallback");
    expect(r.why).toBe("model error: WebGPU device lost");   // was "model too slow"
    expect(r.fatal).toBe(true);
  });

  it("an engine error in the speaking call keeps the label, scripts the line, and is fatal", async () => {
    let n = 0;
    const { brain } = make(() => (++n === 1 ? answer("greeting") : Promise.reject(new Error("worker gone"))));
    const r = await brain.reply([], "Hello there.", "wary");
    expect(r.intent).toBe("greeting");
    expect(r.why).toBe("model error: worker gone");
    expect(r.fatal).toBe(true);
  });

  it("a good answer is not fatal and has no why", async () => {
    let n = 0;
    const { brain } = make(() => answer(++n === 1 ? "greeting" : "Evening, traveler."));
    const r = await brain.reply([], "Hello there.", "wary");
    expect(r).toMatchObject({ intent: "greeting", line: "Evening, traveler.", source: "model" });
    expect(r.why).toBeUndefined();
    expect(r.fatal).toBeUndefined();
  });
});

describe("WebLlmBrain.load", () => {
  it("rejects and stops the worker when the worker errors", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    hangingCreate();
    const out = watch(WebLlmBrain.load(() => {}, pick));
    await Promise.resolve();
    FakeWorker.last.emit("error", { message: "Failed to fetch module" });
    await vi.waitFor(() => expect(out.done).toBe(true));
    expect(out.error?.message).toContain("Failed to fetch module");
    expect(FakeWorker.last.terminate).toHaveBeenCalledTimes(1);
  });

  it("rejects after LOAD_STALL_MS with no progress, and each progress report restarts the wait", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("Worker", FakeWorker);
    const hang = hangingCreate();
    const out = watch(WebLlmBrain.load(() => {}, pick));
    await vi.advanceTimersByTimeAsync(LOAD_STALL_MS - 1000);
    hang.progress()({ progress: 0.1, text: "Fetching...", timeElapsed: 1 });
    await vi.advanceTimersByTimeAsync(LOAD_STALL_MS - 1000);
    expect(out.done).toBe(false);                      // still downloading: progress came in time
    await vi.advanceTimersByTimeAsync(1000);
    expect(out.done).toBe(true);
    expect(out.error?.message).toContain("no progress");
    expect(FakeWorker.last.terminate).toHaveBeenCalledTimes(1);
  });

  it("resolves with a warmed-up brain and keeps the worker running", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const engine = fakeEngine(() => answer("hi"));
    vi.mocked(CreateWebWorkerMLCEngine).mockResolvedValue(engine as never);
    const brain = await WebLlmBrain.load(() => {}, pick);
    expect(brain.kind).toBe("model");
    expect(engine.chat.completions.create).toHaveBeenCalledTimes(1);   // the warm-up
    expect(FakeWorker.last.terminate).not.toHaveBeenCalled();
  });
});
