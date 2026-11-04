// ---------------------------------------------------------------------------
// tuning.ts
// Purpose : Every gameplay number in one place (SOP-01, SOP-14 step 3).
// Usage   : import { TUNING } from "./tuning"
// Notes   : Distances in tiles, speeds in tiles per second, time in seconds.
//           Tests read these too, so a retune that breaks a rule fails `test`.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { LanternConfig } from "../core/lantern";
import type { BrainWeights } from "../core/ghostBrain";

export const TILE_PX = 16;
export const ZOOM = 2; // 640x360 canvas shows 320x180 px = 20 x 11.25 tiles

export const PLAYER = {
  speed: 3.6,
  half: 0.3, // collision half-size in tiles (box of 0.6)
};

export const LANTERN: LanternConfig = {
  maxOil: 100,
  // playtest 1: 2.0 / 7.0 left 72 oil at the exit, so oil never mattered (pillar 2), so 3.5.
  // First human playtest (2026-11-04): "I run out of oil and they catch up to me", so 3.0 (Normal; see DIFFICULTY)
  dimBurn: 3.0,
  brightBurn: 10.0,
  dimRadius: 2.6,
  brightRadius: 4.6,
  emptyRadius: 1.2,
  // playtest 1: at full power even the dim lantern repelled ghosts at point-blank range, so brightening
  // never mattered. Dim light is for seeing; only bright light shields (pillar 2).
  dimPower: 0.35,
  brightPower: 1.0,
};
export const OIL_PICKUP = 40;

export const GHOST = {
  // chase > PLAYER.speed on purpose: in the dark you cannot outrun them, only the light saves you
  // (playtest 1 at 2.5: the dark bot escaped and the lantern did not matter)
  speed: { chase: 3.9, flee: 3.2, wander: 1.1 },
  catchDistance: 0.55,
  shieldLight: 0.5, // a ghost standing in at least this much light cannot touch you
  thinkEvery: 0.12, // s between decisions (SOP-14: not every frame; playtest 1 at 0.25 let a ghost cover a tile between thinks)
  repathEvery: 0.4,
  memorySeconds: 2.0, // how long a ghost keeps chasing after losing the player
  wanderRadius: 4,
  fleeRadius: 5,
  separation: 0.8, // tiles between ghosts (steering), so a pack never stacks into one sprite
  crowdPenalty: 2.0, // flee target score lost per other ghost already heading near that cell
};

export const BRAIN: BrainWeights = {
  senseRange: 6,
  memoryWeight: 0.6,
  fearWeight: 1.0,
  fearCurve: 0.6,
  wanderBase: 0.2,
  inertia: 0.08,
};

// ---- Difficulty (settings.access.difficulty, or ?difficulty=<name>; src/game/difficulty.ts picks one) ----------
// Only the oil burn and the ghost speeds change: the level, the light and the ghosts' minds stay the same, so every
// difficulty is the same game. Normal is LANTERN and GHOST above. The pillar "only the light saves you" (chase faster
// than PLAYER.speed) holds on Normal and Hard; Easy brings the ghosts down to about your speed and Story below it.
// A full lantern lasts 100 / dimBurn seconds dim: Story 67, Easy 45, Normal 33, Hard 25 (before the playtest: 29).
// Measured 2026-11-04 with the bot pair, seeds 1 to 8 each (?autoplay&seed=N&difficulty=D; HOW_IT_WAS_MADE):
//   story : lantern bot escapes 8/8 (19 to 22 s, 35 to 70 oil left) | dark bot caught 8/8 (11 s)
//   easy  : lantern bot escapes 8/8 (20 to 24 s, 46 to 55 oil)      | dark bot caught 7/8 (seed 8 escapes, fine here)
//   normal: lantern bot escapes 8/8 (21 to 25 s, 37 to 59 oil)      | dark bot caught 8/8 (6 to 13 s)
//   hard  : lantern bot escapes 8/8 (21 to 22 s, 45 to 55 oil)      | dark bot caught 8/8 (6 to 13 s)
// Hard is harder on oil only. Tried and dropped (the lantern bot must escape every seed): chase 4.3 (escaped 3/6),
// 4.1 (5/6, 7/8), 4.0 (7/8); burn 4.5 / 13.5 (2/8): above 4.0 the bot detours for oil past the ghosts and is caught.
// Oil left is a noisy number: the bot fetches oil only below 35 %, so a cheap lantern can mean fewer pickups.
export type DifficultyTuning = {
  dimBurn: number; // oil per second, dim
  brightBurn: number; // oil per second, bright
  ghostSpeed: { chase: number; flee: number; wander: number };
};

export const DIFFICULTY: Record<"story" | "easy" | "normal" | "hard", DifficultyTuning> = {
  story: { dimBurn: 1.5, brightBurn: 5.0, ghostSpeed: { chase: 3.0, flee: 3.2, wander: 0.9 } },
  easy: { dimBurn: 2.2, brightBurn: 7.5, ghostSpeed: { chase: 3.5, flee: 3.2, wander: 1.0 } },
  normal: { dimBurn: LANTERN.dimBurn, brightBurn: LANTERN.brightBurn, ghostSpeed: GHOST.speed },
  hard: { dimBurn: 4.0, brightBurn: 12.0, ghostSpeed: { chase: 3.9, flee: 3.2, wander: 1.1 } },
};

export const SEED = 1337; // all ghost randomness; change it and the run changes, keep it and bugs replay

// Tile indices in tilemap_packed.png (Kenney Tiny Dungeon, A-0001): row * 12 + column
// The pack has no key sprite: the key sits in a chest (89). Indices checked against Tiles/tile_NNNN.png in the pack.
// The keeper and the ghosts were tiles 84 and 121 until they got PixelLab art (src/game/sprites.ts).
export const TILES = { floor: 48, wall: 40, exit: 45, oil: 115, key: 89 };
