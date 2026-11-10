// ---------------------------------------------------------------------------
// analog.ts
// Purpose : Analog input shaping (#274): the left stick and the triggers as the game reads them, after the player's
//           deadzone and invert_y, so a racer steers by how far the stick leans and brakes by how far a trigger is in.
//           The same rules as the Bevy shell's Intent (#265).
// Usage   : const { x, y } = stick(rawX, rawY, settings.input.deadzone, settings.input.invert_y)
//           const gas = trigger(pad.buttons[7].value)              // 0 at rest to 1 fully in
//           stickActions(rawX, rawY, deadzone, invertY)             // ["move_left"] while the stick leans left
// Notes   : No Phaser, no browser (Vitest runs it). The stick deadzone is radial (the length of the vector, not each
//           axis), and what is left is rescaled to 0..1, so a stick just past the deadzone gives a small value
//           instead of jumping to the deadzone's size; the direction never changes. Up is -y, as the browser's
//           Gamepad API and screen coordinates have it; invert_y flips it. Triggers have their own small fixed
//           deadzone: input.deadzone is the "Stick deadzone" setting, and a trigger that rests at 0.1 would otherwise
//           lose a fifth of its travel. NaN and infinities (a broken driver) count as 0.
//
// Pseudocode:
//   stick(x, y, dz, inv): y = -y if inv -> len = |(x, y)| -> len <= dz: (0, 0)
//   -> scale = min((len - dz) / (1 - dz), 1) / len -> (x * scale, y * scale)
//   trigger(v, dz): v = clamp(v, 0, 1) -> v <= dz: 0 -> (v - dz) / (1 - dz)
//   stickActions: raw lean past max(dz, STICK_HOLD_MIN) per direction (invert_y honoured) -> move_* names
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
/** Trigger travel ignored at rest (0 to 1). */
export const TRIGGER_DEADZONE = 0.05;
/** The largest deadzone accepted (settings clamp input.deadzone to 0.9 too); keeps the rescale finite. */
export const MAX_DEADZONE = 0.95;
/** Raw stick lean that also holds a move_* action; never below the player's deadzone. */
export const STICK_HOLD_MIN = 0.2;

export type Vec2 = { x: number; y: number };

const finite = (v: number): number => (Number.isFinite(v) ? v : 0);
const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), hi);

/** The stick after the radial deadzone and invert_y: each axis -1..1, the vector's length 0..1, up is -y. */
export function stick(x: number, y: number, deadzone: number, invertY: boolean): Vec2 {
  x = finite(x);
  y = finite(y);
  if (invertY) y = -y;
  const dz = clamp(finite(deadzone), 0, MAX_DEADZONE);
  const len = Math.hypot(x, y);
  if (len <= dz || len === 0) return { x: 0, y: 0 };
  const scale = Math.min((len - dz) / (1 - dz), 1) / len;
  return { x: x * scale, y: y * scale };
}

/** A trigger (0 at rest, 1 fully in) after its deadzone, rescaled to 0..1. */
export function trigger(value: number, deadzone = TRIGGER_DEADZONE): number {
  const v = clamp(finite(value), 0, 1);
  const dz = clamp(finite(deadzone), 0, MAX_DEADZONE);
  return v <= dz ? 0 : (v - dz) / (1 - dz);
}

/** The move_* actions a raw stick lean holds: past max(deadzone, STICK_HOLD_MIN), invert_y honoured, up is -y. */
export function stickActions(x: number, y: number, deadzone: number, invertY: boolean): string[] {
  const on = Math.max(finite(deadzone), STICK_HOLD_MIN);
  x = finite(x);
  y = finite(y);
  if (invertY) y = -y;
  const out: string[] = [];
  if (x < -on) out.push("move_left");
  if (x > on) out.push("move_right");
  if (y < -on) out.push("move_up");
  if (y > on) out.push("move_down");
  return out;
}
