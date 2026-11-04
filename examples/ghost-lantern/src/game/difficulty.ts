// ---------------------------------------------------------------------------
// difficulty.ts
// Purpose : Which difficulty a run uses, and the lantern and ghost numbers that go with it.
// Usage   : const d = difficultyFor(location.search, shell.settings)   // "story" | "easy" | "normal" | "hard"
//           new Lantern(lanternFor(d)) ; DIFFICULTY[d].ghostSpeed.chase
// Notes   : Engine-free (Vitest runs it). The player picks the difficulty on the main menu or in Settings >
//           Accessibility; it lives in the kit's settings file (settings.access.difficulty). ?difficulty=<name>
//           overrides it for one page load (tests and the bot pair), and an unknown name is ignored.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { LanternConfig } from "../core/lantern";
import { DIFFICULTIES, type Settings } from "../core/settings";
import { DIFFICULTY, LANTERN } from "./tuning";

export type Difficulty = (typeof DIFFICULTIES)[number];
export const DIFFICULTY_PARAM = "difficulty";
const FALLBACK: Difficulty = "normal";

const known = (v: unknown): v is Difficulty => typeof v === "string" && (DIFFICULTIES as readonly string[]).includes(v);

/** The URL flag if it names a difficulty, else the player's setting, else Normal. */
export function difficultyFor(search: string, settings: Pick<Settings, "access">): Difficulty {
  const asked = new URLSearchParams(search).get(DIFFICULTY_PARAM);
  if (known(asked)) return asked;
  const saved = settings.access.difficulty;
  return known(saved) ? saved : FALLBACK;
}

/** The lantern for a difficulty: the burn rates change, everything else is LANTERN. */
export function lanternFor(d: Difficulty): LanternConfig {
  return { ...LANTERN, dimBurn: DIFFICULTY[d].dimBurn, brightBurn: DIFFICULTY[d].brightBurn };
}
