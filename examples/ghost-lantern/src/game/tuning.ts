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
  dimBurn: 3.5, // playtest 1: 2.0 / 7.0 left 72 oil at the exit, so oil never mattered (pillar 2)
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

export const SEED = 1337; // all ghost randomness; change it and the run changes, keep it and bugs replay

// Tile indices in tilemap_packed.png (Kenney Tiny Dungeon, A-0001): row * 12 + column
// The pack has no key sprite: the key sits in a chest (89). Indices checked against Tiles/tile_NNNN.png in the pack.
export const TILES = { floor: 48, wall: 40, exit: 45, oil: 115, key: 89, wizard: 84, ghost: 121 };
