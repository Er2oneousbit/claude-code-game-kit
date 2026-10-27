// ---------------------------------------------------------------------------
// gatekeeper.ts
// Purpose : The rules: how much each intent moves the guard's trust, when the gate
//           opens, when the guard sends you away. Pure functions, unit tested.
//           This is the part a language model can never change (SOP-15).
// Usage   : let s = newState(RULES); const step = applyIntent(s, "greeting", RULES); s = step.state
// Notes   : The puzzle: a notice says the gate is closed by order of Captain Wren.
//           Mentioning the captain is the big trust jump; greeting and flattery help a
//           little (flattery only twice); bribes and threats hurt; two threats and you are out.
//
// Pseudocode:
//   delta = rules.delta[intent], with "first time only" and "max twice" limits
//   trust = clamp(trust + delta, 0, 100); turns -= 1
//   trust >= openAt -> open | threats >= maxThreats or turns == 0 -> turned_away | else talking
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { Intent } from "./intent";

export type Outcome = "talking" | "open" | "turned_away";

export type Rules = {
  startTrust: number;
  openAt: number;
  turns: number;
  maxThreats: number;
  maxFlattery: number;
  delta: Record<Intent, number>;
};

export type State = {
  trust: number;
  turnsLeft: number;
  threats: number;
  flattery: number;
  greeted: boolean;
  captainMentioned: boolean;
  outcome: Outcome;
};

export type Step = { state: State; delta: number; note: string };

export function newState(r: Rules): State {
  return { trust: r.startTrust, turnsLeft: r.turns, threats: 0, flattery: 0, greeted: false, captainMentioned: false, outcome: "talking" };
}

export function applyIntent(s: State, intent: Intent, r: Rules): Step {
  if (s.outcome !== "talking") return { state: s, delta: 0, note: "the conversation is over" };
  const next = { ...s };
  let delta = r.delta[intent];
  let note: string = intent;
  if (intent === "greeting") {
    if (s.greeted) [delta, note] = [0, "already greeted"];
    next.greeted = true;
  } else if (intent === "flattery") {
    if (s.flattery >= r.maxFlattery) [delta, note] = [0, "flattery wore off"];
    next.flattery += 1;
  } else if (intent === "mentions_captain") {
    if (s.captainMentioned) [delta, note] = [0, "captain already mentioned"];
    next.captainMentioned = true;
  } else if (intent === "threat") {
    next.threats += 1;
  }
  next.trust = Math.min(100, Math.max(0, s.trust + delta));
  next.turnsLeft = s.turnsLeft - 1;
  if (next.trust >= r.openAt) next.outcome = "open";
  else if (next.threats >= r.maxThreats || next.turnsLeft <= 0) next.outcome = "turned_away";
  return { state: next, delta: next.trust - s.trust, note };
}

/** A word for the prompt, so the model's tone follows the game's state (state in, words out). */
export function mood(s: State, r: Rules): "suspicious" | "wary" | "warming up" {
  if (s.trust >= r.openAt * 0.6) return "warming up";
  return s.trust >= r.startTrust ? "wary" : "suspicious";
}
