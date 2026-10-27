// ---------------------------------------------------------------------------
// brain.ts
// Purpose : Where the guard's words come from. Two brains behind one interface:
//           FallbackBrain (keywords + scripted lines, always works) and WebLlmBrain
//           (webllmBrain.ts: a small local model in the browser, WebGPU, loaded only when asked for).
//           Every model reply is checked;
//           anything late or invalid becomes the scripted reply (SOP-15 steps 3 to 5).
// Usage   : const brain = gpuOk ? await (await import("./webllmBrain")).WebLlmBrain.load(...) : new FallbackBrain(pick)
//           const r = await brain.reply(history, playerText, mood)   // {intent, line, source, ms, why?, fatal?}
// Notes   : The model runs in llm.worker.ts. Its download is cached by the browser, so the
//           second visit starts in seconds. Nothing leaves the player's machine: no server, no key.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): BrainReply.fatal (the model engine broke)
// ---------------------------------------------------------------------------
import { keywordIntent, type Reply } from "../core/intent";
import { fallbackLine } from "../core/lines";
import type { Turn } from "./prompt";

// fatal: the model engine itself failed (not just slow or off-script); the controller stops asking it
export type BrainReply = Reply & { source: "model" | "fallback"; ms: number; why?: string; fatal?: boolean };
export type Pick = (n: number) => number;

export interface NpcBrain {
  readonly kind: "model" | "fallback";
  reply(history: Turn[], player: string, mood: string): Promise<BrainReply>;
}

export class FallbackBrain implements NpcBrain {
  readonly kind = "fallback" as const;
  constructor(private readonly pick: Pick) {}

  async reply(_history: Turn[], player: string): Promise<BrainReply> {
    const intent = keywordIntent(player);
    return { intent, line: fallbackLine(intent, this.pick), source: "fallback", ms: 0 };
  }
}

/** True when the browser offers a WebGPU adapter (needed by WebLLM). */
export async function webGpuAvailable(): Promise<boolean> {
  const gpu = (navigator as unknown as { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  if (!gpu) return false;
  try {
    return (await gpu.requestAdapter()) != null;
  } catch {
    return false;
  }
}
