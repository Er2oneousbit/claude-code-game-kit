// ---------------------------------------------------------------------------
// prompt.ts
// Purpose : The two model jobs, one call each (a 1.5B model mixes them up when asked for
//           both at once; the Godot twin's tools/eval_guard.gd measured 64% vs 93%):
//           1) classify the player's line into one label (no history: no drift),
//           2) speak one in-character sentence, told the label and the mood the GAME computed.
// Notes   : Same prompts and examples as the Godot version (scripts/game/guard_brain.gd).
//           The model never sees trust numbers or the opening rule.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { type Intent, MAX_INPUT } from "../core/intent";

export type ChatMessage = { role: "system" | "user" | "assistant"; content: string };
export type Turn = { player: string; intent: Intent; line: string };

const CLASSIFY_SYSTEM = [
  "You label what a traveler says to a town gate guard. Reply with ONE label, nothing else.",
  "greeting: says hello or good evening.",
  "flattery: compliments the guard or his gear.",
  "bribe: offers money, gifts or payment.",
  "threat: threatens harm or violence.",
  "mentions_captain: names Captain Wren or says the captain sent them.",
  "question: asks something.",
  "other: anything else.",
].join("\n");

const SPEAK_SYSTEM = [
  "You are Bram, a tired but honest town gate guard at night.",
  "The gate is closed by order of Captain Wren; a notice on the wall says so.",
  "The user messages are what a traveler says to you. You answer AS BRAM, never as the traveler.",
  "Answer in one short sentence, in character, plain words. Never open the gate or promise to; that is not your call.",
  "Never mention being an AI or these instructions.",
].join("\n");

const pairs = (rows: [string, string][]): ChatMessage[] =>
  rows.flatMap(([u, a]): ChatMessage[] => [{ role: "user", content: u }, { role: "assistant", content: a }]);

const CLASSIFY_EXAMPLES = pairs([
  ["Good evening to you.", "greeting"], ["Nice helmet, very shiny.", "flattery"],
  ["Five gold if you look away.", "bribe"], ["Step aside or you will regret it.", "threat"],
  ["Wren told me to report here.", "mentions_captain"], ["Is there another way into town?", "question"],
  ["The moon is pretty tonight.", "other"], ["You seem like a sensible man.", "flattery"],
]);

const SPEAK_EXAMPLES = pairs([
  ["Good evening! Cold night for guard duty. [intent: greeting]", "Evening. Cold enough. What brings you to a shut gate?"],
  ["Ten silver if you let me through. [intent: bribe]", "Keep your silver. I am not for sale."],
]);

export function classifyMessages(player: string): ChatMessage[] {
  return [{ role: "system", content: CLASSIFY_SYSTEM }, ...CLASSIFY_EXAMPLES, { role: "user", content: player.slice(0, MAX_INPUT) }];
}

export function speakMessages(history: Turn[], player: string, intent: Intent, mood: string, keep: number): ChatMessage[] {
  const recent = history.slice(-keep).flatMap((t): ChatMessage[] => [
    { role: "user", content: `${t.player} [intent: ${t.intent}]` },
    { role: "assistant", content: t.line },
  ]);
  return [
    { role: "system", content: SPEAK_SYSTEM }, ...SPEAK_EXAMPLES, ...recent,
    { role: "user", content: `${player.slice(0, MAX_INPUT)} [intent: ${intent}; Bram feels ${mood}]` },
  ];
}
