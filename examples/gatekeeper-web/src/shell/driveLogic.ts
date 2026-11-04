// ---------------------------------------------------------------------------
// driveLogic.ts
// Purpose : The pure decisions of the scripted smoke runs (drive.ts), apart from the DOM and the shell, so Vitest
//           can load them: what --drive menus sets, and which press moves a slider towards its target.
// Usage   : slideAction(shell.settings.audio.master, MENU_TARGET.master) -> "ui_left" | "ui_right" | ""
// Notes   : The kit's Godot and LÖVE drives make the same choice (slide_action).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const MENU_TARGET = { master: 0.5, reduceMotion: true }; // what --drive menus sets
export const MAX_SLIDER_STEPS = 40; // presses a slider gets to reach its target (0..1 is 20 steps of 0.05)
const SLIDER_EPS = 1e-9; // a slider value this close to its target is there

/** The press that moves a slider from now towards target ("" once it is there). */
export function slideAction(now: number, target: number): "ui_left" | "ui_right" | "" {
  if (Math.abs(now - target) <= SLIDER_EPS) return "";
  return now > target ? "ui_left" : "ui_right";
}
