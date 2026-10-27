// ---------------------------------------------------------------------------
// intent.ts
// Purpose : What the player meant, as one value from a fixed list. The model's only
//           power over the game is choosing one of these (SOP-15: the game decides,
//           the model only words it). Also the strict checks for the model's two
//           outputs (a label, a spoken line) and the keyword classifier used when
//           there is no model.
// Usage   : parseLabel(raw) -> Intent | null ; parseLine(raw) -> string | null
//           keywordIntent(playerText) -> Intent
// Notes   : Engine-free and unit tested against recorded model outputs
//           (tests/fixtures/recorded.json, shared with the Godot version of this example).
//           Same rules as scripts/core/gate_intent.gd there.
//
// Pseudocode (parseLine):
//   first line only -> drop a "Bram:" prefix and wrapping quotes -> collapse spaces -> cut to MAX_LINE
//   reject: empty, braces or brackets (leaked JSON or markup), breaking character ("as an AI ...")
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export const INTENTS = ["greeting", "flattery", "bribe", "threat", "mentions_captain", "question", "other"] as const;
export type Intent = (typeof INTENTS)[number];
export type Reply = { intent: Intent; line: string };

export const MAX_LINE = 220; // characters shown from the model; longer replies are cut, not trusted
export const MAX_INPUT = 200; // characters the player may type per message

/** EBNF grammar for the classifier call: the output can only be one exact label (WebLLM response_format). */
export const INTENT_GRAMMAR = `root ::= ${INTENTS.map((i) => `"${i}"`).join(" | ")}`;

/** EBNF grammar for the speaker call: one sentence, capital first, no brackets, braces or line breaks
 *  (same shape as the Godot twin's LINE_REGEX). Length is bounded by max_tokens. */
export const LINE_GRAMMAR = `root ::= [A-Z] [^\\n\\[\\]{}<>]* [.!?]`;

const BREAKS_CHARACTER = /\b(as an ai|language model|i am an ai|i'm an ai|assistant)\b/i;

export function isIntent(v: unknown): v is Intent {
  return typeof v === "string" && (INTENTS as readonly string[]).includes(v);
}

export function cleanLine(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim().replace(/^["']|["']$/g, "");
  return flat.length > MAX_LINE ? `${flat.slice(0, MAX_LINE - 3).trimEnd()}...` : flat;
}

/** The classifier's output: exactly one label (case and surrounding space forgiven), else null. */
export function parseLabel(raw: string): Intent | null {
  const label = raw.trim().toLowerCase();
  return isIntent(label) ? label : null;
}

/** The speaker's output: one clean in-character line, else null (the caller uses the scripted line). */
export function parseLine(raw: string): string | null {
  const first = raw.trim().split(/\r?\n/)[0] ?? "";
  // Small models copy the "[intent: ...]" notes from their input into their answer: cut them out
  const line = cleanLine(first.replace(/^\s*bram\s*:\s*/i, "").replace(/\s*\[[^\]]*\]\s*/g, " "));
  if (!line || /[{}[\]<>]/.test(line) || BREAKS_CHARACTER.test(line)) return null;
  return line;
}

const KEYWORDS: [Intent, RegExp][] = [
  ["threat", /\b(kill|hurt|attack|stab|burn|or else|break (the|your)|smash|threat)\b/i],
  ["mentions_captain", /\b(captain|wren)\b/i],
  ["bribe", /\b(gold|coins?|pay|money|bribe|silver|reward)\b/i],
  ["flattery", /\b(strong|brave|handsome|impressive|great|fine|nice|best|honou?rable|wise|sharp|tough|admire|well[- ]kept|looks? (good|great|sharp))\b/i],
  ["greeting", /^\s*(hi|hello|hey|greetings|good (morning|day|evening)|well met)\b/i],
  ["question", /\?\s*$|^\s*(who|what|why|where|when|how|can|could|is|are)\b/i],
];

/** Fallback classifier: first matching rule wins, in priority order (threats before anything else). */
export function keywordIntent(text: string): Intent {
  for (const [intent, re] of KEYWORDS) if (re.test(text)) return intent;
  return "other";
}
