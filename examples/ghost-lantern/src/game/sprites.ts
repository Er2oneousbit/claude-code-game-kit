// ---------------------------------------------------------------------------
// sprites.ts
// Purpose : The keeper's and the ghosts' animation data (PixelLab frames, A-0009 to A-0013) and
//           the pure rule for which way the keeper faces. No Phaser here, so tests can read it.
// Usage   : GameScene loads every frame in frameFiles() and builds one Phaser animation per entry.
// Notes   : Frames are PNGs exactly as PixelLab made them, one file per frame under public/assets/art/:
//           keeper 48x48 (its animation canvas has room around the 32 px character), ghosts 32x32. The keeper has south, west and north; east is west mirrored
//           (PixelLab's east view hid the lantern behind the body). Ghosts face the camera in
//           every state; each state of the AI has its own loop so a player can read it (pillar 1).
//           Frame counts per kind are held steady (SOP-16): keeper walk 6, idle 4; ghost loops 5 to 9.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { GhostAction } from "../core/ghostBrain";
import type { Vec } from "../core/grid";

export const ART = "assets/art";

export type Facing = "south" | "west" | "north" | "east";
/** The directions drawn as files; east plays west with flipX. */
export const DRAWN: readonly Exclude<Facing, "east">[] = ["south", "west", "north"];

type Clip = { frames: number; fps: number; pad: number };
export const KEEPER = {
  px: 48,
  walk: { frames: 6, fps: 10, pad: 3 } satisfies Clip, // frame_000.png .. frame_005.png
  idle: { frames: 4, fps: 5, pad: 3 } satisfies Clip,
  // The feet are on row 36 of the 48 px cell: origin y 0.65 (row 31) puts them 5 px below the position,
  // the bottom of the collision box, so the keeper stands on the tile he occupies instead of hanging below it
  origin: { x: 0.5, y: 0.65 },
};

// Each ghost clip is a range of the 9 frames PixelLab made (frame_00 is the anchor sprite). Chase holds
// the wail (mouth open, frames 3 to 7), flee holds the cower (hands over the face, frames 3 to 7);
// wander plays the whole gentle bob.
export const GHOST_ART: Record<GhostAction, { folder: string; from: number; to: number; fps: number }> = {
  wander: { folder: "float", from: 0, to: 8, fps: 8 },
  chase: { folder: "chase", from: 3, to: 7, fps: 10 },
  flee: { folder: "flee", from: 3, to: 7, fps: 10 },
};
export const GHOST_FRAMES = 9; // frame_00.png .. frame_08.png in every ghost folder
export const GHOST_PX = 32;
export const GHOST_PAD = 2;

const num = (i: number, pad: number) => String(i).padStart(pad, "0");

export const keeperFrameKey = (clip: "walk" | "idle", dir: Exclude<Facing, "east">, i: number) => `keeper-${clip}-${dir}-${i}`;
export const keeperAnimKey = (clip: "walk" | "idle", dir: Exclude<Facing, "east">) => `keeper-${clip}-${dir}`;
export const ghostFrameKey = (folder: string, i: number) => `ghost-${folder}-${i}`;
export const ghostAnimKey = (action: GhostAction) => `ghost-${action}`;

/** Every texture key, its file and its square size, for the loader (and for the test that the files exist). */
export function frameFiles(): { key: string; file: string; px: number }[] {
  const out: { key: string; file: string; px: number }[] = [];
  for (const clip of ["walk", "idle"] as const) {
    for (const dir of DRAWN) {
      for (let i = 0; i < KEEPER[clip].frames; i++) {
        out.push({ key: keeperFrameKey(clip, dir, i), file: `${ART}/keeper/${clip}/${dir}/frame_${num(i, KEEPER[clip].pad)}.png`, px: KEEPER.px });
      }
    }
  }
  const folders = [...new Set(Object.values(GHOST_ART).map((g) => g.folder))];
  for (const folder of folders) {
    for (let i = 0; i < GHOST_FRAMES; i++) {
      out.push({ key: ghostFrameKey(folder, i), file: `${ART}/ghost/${folder}/frame_${num(i, GHOST_PAD)}.png`, px: GHOST_PX });
    }
  }
  return out;
}

/**
 * Which way the keeper faces after a move: the larger axis wins, a tie keeps a horizontal facing
 * (diagonals read as side views), and no movement keeps the last facing so idle looks the same way.
 */
export function facingFor(move: Vec, last: Facing): Facing {
  if (move.x === 0 && move.y === 0) return last;
  if (Math.abs(move.x) >= Math.abs(move.y)) return move.x < 0 ? "west" : "east";
  return move.y < 0 ? "north" : "south";
}
