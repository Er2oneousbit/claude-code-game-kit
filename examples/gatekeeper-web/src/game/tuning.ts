// ---------------------------------------------------------------------------
// tuning.ts
// Purpose : Every number and every model setting in one place.
// Notes   : Trust math lives here, not in the prompt: the model never sees these numbers.
//           MODEL_ID is a WebLLM prebuilt model: Qwen2.5 1.5B Instruct (Apache-2.0, about 880 MB download,
//           about 1.6 GB of GPU memory per WebLLM's own record). Playtest: Qwen3.5 0.8B answered in
//           "thinking" mode (slow, <think> before the JSON) despite enable_thinking: false, so the
//           guard uses a model without a thinking mode. Logged in docs/ASSET_LOG.md.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 with Claude (Opus 5.5, claude-opus-5-5): LOAD_STALL_MS
// ---------------------------------------------------------------------------
import type { Rules } from "../core/gatekeeper";

export const RULES: Rules = {
  startTrust: 20,
  openAt: 70,
  turns: 8,
  maxThreats: 2,
  maxFlattery: 2,
  delta: { greeting: 5, flattery: 10, bribe: -15, threat: -25, mentions_captain: 45, question: 0, other: 0 },
  // other is 0 on purpose: a line the guard did not understand must not cost the player, above all when the
  // keyword fallback is the one judging (playtest: "That armor looks well kept" counted as other and lost the game)
};

export const MODEL_ID = "Qwen2.5-1.5B-Instruct-q4f16_1-MLC";
export const MODEL_NAME = "Qwen2.5 1.5B";
export const MODEL_DOWNLOAD_MB = 880;
export const REPLY_TIMEOUT_MS = 12000; // a model reply slower than this falls back to the scripted line
export const MAX_SLOW_REPLIES = 2;   // this many model timeouts in a row switch the session to the scripted guard
export const LOAD_STALL_MS = 60000; // model load with no progress this long counts as failed (scripted guard takes over)
export const MAX_TOKENS = 120;
export const TEMPERATURE = 0.7;
export const HISTORY_TURNS = 4; // past exchanges sent to the model (small context, fast replies)
export const SEED = 7;
