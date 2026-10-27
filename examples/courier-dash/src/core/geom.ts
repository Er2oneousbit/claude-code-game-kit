// ---------------------------------------------------------------------------
// geom.ts
// Purpose : Flat 2D geometry on the ground plane (x, z): boxes for buildings, circles for the
//           courier and the robot, line of sight, and "move and slide" collision.
// Usage   : const p = moveCircle(pos, {x: vx * dt, z: vz * dt}, radius, boxes, bounds)
//           if (lineOfSight(robot, courier, boxes)) ...
// Notes   : Engine-free (no three import) so Vitest runs it instantly. The game is flat, so
//           everything that collides is an axis-aligned box seen from above.
//           Yaw convention matches Three.js rotation.y for a model facing +Z:
//           direction = (sin(yaw), cos(yaw)).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type V2 = { x: number; z: number };
export type Box = { minX: number; minZ: number; maxX: number; maxZ: number };

const EPS = 1e-9;

export const v2 = (x: number, z: number): V2 => ({ x, z });
export const sub = (a: V2, b: V2): V2 => ({ x: a.x - b.x, z: a.z - b.z });
export const len = (a: V2): number => Math.hypot(a.x, a.z);
export const dist = (a: V2, b: V2): number => Math.hypot(a.x - b.x, a.z - b.z);

export function normalize(a: V2): V2 {
  const l = len(a);
  return l < EPS ? { x: 0, z: 0 } : { x: a.x / l, z: a.z / l };
}

/** Box from a center and a size (width along x, depth along z). */
export function boxAt(cx: number, cz: number, w: number, d: number): Box {
  return { minX: cx - w / 2, minZ: cz - d / 2, maxX: cx + w / 2, maxZ: cz + d / 2 };
}

export function inflate(b: Box, r: number): Box {
  return { minX: b.minX - r, minZ: b.minZ - r, maxX: b.maxX + r, maxZ: b.maxZ + r };
}

export function inBox(p: V2, b: Box): boolean {
  return p.x >= b.minX && p.x <= b.maxX && p.z >= b.minZ && p.z <= b.maxZ;
}

/** Does the segment a-b touch the box? Slab method. */
export function segmentHitsBox(a: V2, b: V2, box: Box): boolean {
  let t0 = 0;
  let t1 = 1;
  const d = sub(b, a);
  for (const [p, dd, lo, hi] of [
    [a.x, d.x, box.minX, box.maxX],
    [a.z, d.z, box.minZ, box.maxZ],
  ] as const) {
    if (Math.abs(dd) < EPS) {
      if (p < lo || p > hi) return false;
      continue;
    }
    let ta = (lo - p) / dd;
    let tb = (hi - p) / dd;
    if (ta > tb) [ta, tb] = [tb, ta];
    t0 = Math.max(t0, ta);
    t1 = Math.min(t1, tb);
    if (t0 > t1) return false;
  }
  return true;
}

/** True when nothing in `boxes` blocks the straight line from a to b. */
export function lineOfSight(a: V2, b: V2, boxes: readonly Box[]): boolean {
  return !boxes.some((box) => segmentHitsBox(a, b, box));
}

/** How far a ray from `from` along unit `dir` travels before a box stops it (at most maxDist).
 *  Used to draw the robot's sight cone exactly as far as it really sees. */
export function rayDistance(from: V2, dir: V2, maxDist: number, boxes: readonly Box[]): number {
  let best = maxDist;
  for (const box of boxes) {
    let t0 = 0;
    let t1 = best;
    let hit = true;
    for (const [p, dd, lo, hi] of [
      [from.x, dir.x, box.minX, box.maxX],
      [from.z, dir.z, box.minZ, box.maxZ],
    ] as const) {
      if (Math.abs(dd) < EPS) {
        if (p < lo || p > hi) hit = false;
        continue;
      }
      let ta = (lo - p) / dd;
      let tb = (hi - p) / dd;
      if (ta > tb) [ta, tb] = [tb, ta];
      t0 = Math.max(t0, ta);
      t1 = Math.min(t1, tb);
    }
    if (hit && t0 <= t1) best = Math.min(best, t0);
  }
  return best;
}

/** Push a circle out of one box. Returns the corrected center (unchanged if not touching). */
export function pushOut(p: V2, r: number, box: Box): V2 {
  const qx = Math.min(Math.max(p.x, box.minX), box.maxX);
  const qz = Math.min(Math.max(p.z, box.minZ), box.maxZ);
  const dx = p.x - qx;
  const dz = p.z - qz;
  const d = Math.hypot(dx, dz);
  if (d >= r) return p;
  if (d > EPS) return { x: qx + (dx / d) * r, z: qz + (dz / d) * r };
  // Center inside the box: leave by the shortest way out.
  const exits = [
    { x: box.minX - r, z: p.z, cost: p.x - box.minX },
    { x: box.maxX + r, z: p.z, cost: box.maxX - p.x },
    { x: p.x, z: box.minZ - r, cost: p.z - box.minZ },
    { x: p.x, z: box.maxZ + r, cost: box.maxZ - p.z },
  ];
  exits.sort((m, n) => m.cost - n.cost);
  return { x: exits[0].x, z: exits[0].z };
}

/** Move a circle by delta, sliding along boxes and staying inside bounds. */
export function moveCircle(pos: V2, delta: V2, r: number, boxes: readonly Box[], bounds: Box): V2 {
  let p = { x: pos.x + delta.x, z: pos.z + delta.z };
  for (let pass = 0; pass < 2; pass++) for (const box of boxes) p = pushOut(p, r, box);
  return {
    x: Math.min(Math.max(p.x, bounds.minX + r), bounds.maxX - r),
    z: Math.min(Math.max(p.z, bounds.minZ + r), bounds.maxZ - r),
  };
}

export function yawOf(dir: V2): number {
  return Math.atan2(dir.x, dir.z);
}

export function wrapAngle(a: number): number {
  while (a > Math.PI) a -= 2 * Math.PI;
  while (a < -Math.PI) a += 2 * Math.PI;
  return a;
}

/** Turn `from` toward `to` by at most maxStep radians. */
export function turnToward(from: number, to: number, maxStep: number): number {
  const diff = wrapAngle(to - from);
  return Math.abs(diff) <= maxStep ? to : wrapAngle(from + Math.sign(diff) * maxStep);
}
