// ---------------------------------------------------------------------------
// ghostBrain.ts
// Purpose : The ghost's decision layer: utility AI (SOP-14, ADR 0001). Every think
//           tick each action gets a 0..1 score from what the ghost senses; the
//           highest wins, with a small bonus for the current action so ghosts do
//           not flicker between two close scores.
// Usage   : const scores = scoreActions(senses, weights); const a = pickAction(scores, current, weights.inertia)
// Notes   : Pure functions, unit tested; the scene gathers Senses (perception) and
//           turns the chosen action into a path (movement).
//
// Pseudocode:
//   near    = clamp(1 - distance / senseRange)            1 next to the player, 0 out of range
//   chase   = near * (1 - light) + memory * memoryWeight  wants the player, unless lit
//   flee    = light ^ fearCurve * fearWeight               the brighter it is here, the stronger
//   wander  = wanderBase                                   the floor every other score must beat
//   pick    = argmax(score + inertia if it is the current action)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type GhostAction = "chase" | "flee" | "wander";
export const ACTIONS: readonly GhostAction[] = ["chase", "flee", "wander"];

/** Perception results, gathered by the scene each think tick. */
export type Senses = {
  distance: number; // tiles to the player
  light: number; // 0..1 lantern light at the ghost
  memory: number; // 0..1, 1 = sensed the player just now, fades to 0
};

export type BrainWeights = {
  senseRange: number; // tiles
  memoryWeight: number;
  fearWeight: number;
  fearCurve: number; // < 1 makes even dim light scary
  wanderBase: number;
  inertia: number;
};

export type Scores = Record<GhostAction, number>;

const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));

export function scoreActions(s: Senses, w: BrainWeights): Scores {
  const near = clamp01(1 - s.distance / w.senseRange);
  return {
    chase: clamp01(near * (1 - s.light) + s.memory * w.memoryWeight * (1 - s.light)),
    flee: clamp01(Math.pow(clamp01(s.light), w.fearCurve) * w.fearWeight),
    wander: w.wanderBase,
  };
}

export function pickAction(scores: Scores, current: GhostAction, inertia: number): GhostAction {
  let best: GhostAction = current;
  let bestScore = scores[current] + inertia;
  for (const a of ACTIONS) {
    if (a !== current && scores[a] > bestScore) {
      best = a;
      bestScore = scores[a];
    }
  }
  return best;
}
