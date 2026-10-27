// ---------------------------------------------------------------------------
// webllmBrain.ts
// Purpose : The model brain: MODEL_ID in tuning.ts (Qwen2.5 1.5B) through WebLLM in a Web Worker. Kept in its own
//           module so the ~6 MB WebLLM library is downloaded only when a player asks for the AI
//           guard (dynamic import in controller.ts); the scripted guard never pays for it.
// Usage   : const { WebLlmBrain } = await import("./webllmBrain"); await WebLlmBrain.load(onProgress, pick)
// Notes   : load() rejects (and stops the worker) when the worker errors or the download stalls for
//           LOAD_STALL_MS, so the controller can switch to the scripted guard instead of waiting forever.
//           A reply is fatal when the engine itself errors: the controller then stops asking the model.
//
// Pseudocode (load):
//   start worker; fail on worker "error" or LOAD_STALL_MS without a progress callback (rearmed by each one)
//   race engine creation, then the warm-up generation, against that failure
//   on failure: terminate the worker, rethrow
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): load() fails on worker error or a stalled
//           download; an engine error is reported as such and marks the reply fatal
// ---------------------------------------------------------------------------
import { type ChatCompletionRequestNonStreaming, CreateWebWorkerMLCEngine, hasModelInCache, type WebWorkerMLCEngine } from "@mlc-ai/web-llm";
import { INTENT_GRAMMAR, LINE_GRAMMAR, parseLabel, parseLine } from "../core/intent";
import { fallbackLine } from "../core/lines";
import { type BrainReply, FallbackBrain, type NpcBrain, type Pick } from "./brain";
import { classifyMessages, speakMessages, type Turn } from "./prompt";
import { HISTORY_TURNS, LOAD_STALL_MS, MAX_TOKENS, MODEL_ID, REPLY_TIMEOUT_MS, TEMPERATURE } from "./tuning";

export async function modelIsCached(): Promise<boolean> {
  try {
    return await hasModelInCache(MODEL_ID);
  } catch {
    return false;
  }
}

const TIMEOUT = Symbol("timeout");
const timeout = (ms: number) => new Promise<typeof TIMEOUT>((res) => setTimeout(() => res(TIMEOUT), ms));

/** What one completion came to: the text, too slow, or an engine error (message). */
type Asked = { text: string } | { slow: true } | { error: string };

export class WebLlmBrain implements NpcBrain {
  readonly kind = "model" as const;
  private constructor(private readonly engine: WebWorkerMLCEngine, private readonly fallback: FallbackBrain, private readonly pick: Pick) {}

  static async load(onProgress: (fraction: number, text: string) => void, pick: Pick): Promise<WebLlmBrain> {
    const worker = new Worker(new URL("./llm.worker.ts", import.meta.url), { type: "module" });
    let fail!: (err: Error) => void;
    const failed = new Promise<never>((_, reject) => { fail = reject; });
    let stall: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      clearTimeout(stall);
      stall = setTimeout(() => fail(new Error(`no progress for ${LOAD_STALL_MS / 1000} s`)), LOAD_STALL_MS);
    };
    const onError = (e: Event) => fail(new Error(`model worker failed: ${(e as ErrorEvent).message || "it could not start"}`));
    worker.addEventListener("error", onError);
    arm();
    try {
      const engine = await Promise.race([CreateWebWorkerMLCEngine(worker, MODEL_ID, {
        initProgressCallback: (r) => { arm(); onProgress(r.progress, r.text); },
      }), failed]);
      onProgress(1, "Warming up the model...");
      arm();   // the warm-up reports no progress: it gets one stall window of its own
      // The first generation compiles GPU shaders and is slow: do it now, not on the player's first line
      await Promise.race([engine.chat.completions.create({ messages: [{ role: "user", content: "Hello" }], max_tokens: 1 }), failed]);
      return new WebLlmBrain(engine, new FallbackBrain(pick), pick);
    } catch (err) {
      worker.terminate();
      throw err;
    } finally {
      clearTimeout(stall);
      worker.removeEventListener("error", onError);
    }
  }

  async reply(history: Turn[], player: string, mood: string): Promise<BrainReply> {
    const t0 = performance.now();
    const elapsed = () => Math.round(performance.now() - t0);
    // Job 1: classify. The grammar allows nothing but one exact label.
    const label = await this.ask({
      messages: classifyMessages(player),
      response_format: { type: "grammar", grammar: INTENT_GRAMMAR },
      max_tokens: 8,
      temperature: 0,
    });
    if ("slow" in label) return { ...(await this.fallback.reply(history, player)), ms: elapsed(), why: "model too slow" };
    if ("error" in label) return { ...(await this.fallback.reply(history, player)), ms: elapsed(), why: `model error: ${label.error}`, fatal: true };
    const intent = parseLabel(label.text);
    if (!intent) return { ...(await this.fallback.reply(history, player)), ms: elapsed(), why: `invalid label: ${label.text.slice(0, 40)}` };
    // Job 2: speak, knowing the label and the mood the game computed.
    const spoken = await this.ask({
      messages: speakMessages(history, player, intent, mood, HISTORY_TURNS),
      max_tokens: MAX_TOKENS,
      temperature: TEMPERATURE,
      response_format: { type: "grammar", grammar: LINE_GRAMMAR }, // one sentence, no brackets or braces
    });
    const scripted = () => fallbackLine(intent, this.pick);
    if ("error" in spoken) return { intent, line: scripted(), source: "model", ms: elapsed(), why: `model error: ${spoken.error}`, fatal: true };
    const line = "text" in spoken ? parseLine(spoken.text) : null;
    if (!line) return { intent, line: scripted(), source: "model", ms: elapsed(), why: `line rejected, scripted instead: ${JSON.stringify(("text" in spoken ? spoken.text : "(timeout)").slice(0, 80))}` };
    return { intent, line, source: "model", ms: elapsed() };
  }

  /** One completion with a timeout. Keeps "too slow" apart from "the engine failed": only the second is fatal. */
  private async ask(request: ChatCompletionRequestNonStreaming): Promise<Asked> {
    const call = this.engine.chat.completions.create(request).then((r) => r.choices[0]?.message?.content ?? "");
    try {
      const raw = await Promise.race([call, timeout(REPLY_TIMEOUT_MS)]);
      if (raw !== TIMEOUT) return { text: raw };
      this.engine.interruptGenerate();
      return { slow: true };
    } catch (err) {
      return { error: (err instanceof Error ? err.message : String(err)).slice(0, 80) };
    }
  }
}
