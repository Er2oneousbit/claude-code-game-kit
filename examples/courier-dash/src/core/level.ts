// ---------------------------------------------------------------------------
// level.ts
// Purpose : The town block as data: buildings and trees (each one a collision box), parcel spots,
//           the depot, the robot's patrol loop and the road tiles. One source for the simulation,
//           the renderer and the tests.
// Usage   : import { LEVEL, blockingBoxes, roadTiles } from "./level"
// Notes   : Engine-free. Coordinates in meters on the ground plane, origin in the middle,
//           -z is "up the screen" (away from the camera). Every model is fitted INTO its
//           footprint by the renderer, so what you see is what collides.
//           tests/level.test.ts guards it: spots reachable, nothing inside a building, the patrol
//           loop drivable.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { type Box, type V2, boxAt } from "./geom";

export type Block = { model: string; x: number; z: number; w: number; d: number; turns?: number };
export type RoadTile = { kind: "straight" | "cross" | "end"; x: number; z: number; alongX: boolean };

const RING = 6; // patrol loop and ring road half-size
const TILE = 3; // road tile size

export const LEVEL = {
  bounds: { minX: -15, minZ: -15, maxX: 15, maxZ: 15 } as Box,
  courierStart: { x: 0, z: 11 } as V2,
  depot: { x: 0, z: 12.5 } as V2,
  parcels: [
    { x: 0, z: 4.2 }, // on the doorstep: close, but right next to the patrol road
    { x: -13, z: 0 },
    { x: 13, z: 0 },
    { x: -5, z: -12.5 },
    { x: 5, z: -12.5 },
  ] as V2[],
  /** Patrol loop, driven in this order and back to the start. */
  patrol: [
    { x: -RING, z: -RING },
    { x: RING, z: -RING },
    { x: RING, z: RING },
    { x: -RING, z: RING },
  ] as V2[],
  blocks: [
    { model: "building-type-c", x: 0, z: 0, w: 6, d: 5 },
    { model: "building-type-a", x: -11.5, z: -11, w: 6, d: 5 },
    { model: "building-type-f", x: 11.5, z: -11, w: 6, d: 5 },
    { model: "building-type-k", x: -11.5, z: 11, w: 6, d: 5, turns: 2 },
    { model: "building-type-a", x: 11.5, z: 11, w: 6, d: 5, turns: 2 },
    { model: "building-type-k", x: 0, z: -12.5, w: 5, d: 4 },
    { model: "tree-large", x: -11, z: -4, w: 1.4, d: 1.4 },
    { model: "tree-large", x: -11, z: 4, w: 1.4, d: 1.4 },
    { model: "tree-large", x: 11, z: -4, w: 1.4, d: 1.4 },
    { model: "tree-large", x: 11, z: 4, w: 1.4, d: 1.4 },
    { model: "tree-small", x: -4.5, z: 13.6, w: 1, d: 1 },
    { model: "tree-small", x: 4.5, z: 13.6, w: 1, d: 1 },
  ] as Block[],
};

/** Collision boxes of every block. */
export function blockingBoxes(blocks: readonly Block[] = LEVEL.blocks): Box[] {
  return blocks.map((b) => boxAt(b.x, b.z, b.w, b.d));
}

/** Road tiles: the ring, arms out of each corner, and the street down to the depot. */
export function roadTiles(): RoadTile[] {
  const tiles: RoadTile[] = [];
  for (const sx of [-1, 1])
    for (const sz of [-1, 1]) {
      tiles.push({ kind: "cross", x: sx * RING, z: sz * RING, alongX: true });
      for (const k of [1, 2]) {
        tiles.push({ kind: "straight", x: sx * (RING + k * TILE), z: sz * RING, alongX: true });
        tiles.push({ kind: "straight", x: sx * RING, z: sz * (RING + k * TILE), alongX: false });
      }
    }
  for (let t = -RING + TILE; t < RING; t += TILE) {
    tiles.push({ kind: "straight", x: t, z: -RING, alongX: true });
    tiles.push({ kind: t === 0 ? "cross" : "straight", x: t, z: RING, alongX: true });
    tiles.push({ kind: "straight", x: -RING, z: t, alongX: false });
    tiles.push({ kind: "straight", x: RING, z: t, alongX: false });
  }
  tiles.push({ kind: "straight", x: 0, z: RING + TILE, alongX: false });
  tiles.push({ kind: "end", x: 0, z: RING + 2 * TILE, alongX: false });
  return tiles;
}
