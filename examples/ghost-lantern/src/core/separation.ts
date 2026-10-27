// ---------------------------------------------------------------------------
// separation.ts
// Purpose : Steering "separation" (SOP-14 movement layer): push agents apart when
//           they get closer than a minimum distance, so a pack of ghosts reads as
//           several ghosts instead of one stacked sprite.
// Usage   : const pushes = separate(positions, minDist)   // one {x, y} offset per agent
// Notes   : Pure function; the caller applies each push through wall collision.
//           Two agents on the exact same point are split along x by index, so the
//           result is deterministic.
//
// Pseudocode:
//   for every pair closer than minDist: overlap = minDist - d
//   push each half the overlap away from the other (along the line between them)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { Vec } from "./grid";

export function separate(positions: readonly Vec[], minDist: number): Vec[] {
  const push = positions.map(() => ({ x: 0, y: 0 }));
  for (let i = 0; i < positions.length; i++) {
    for (let j = i + 1; j < positions.length; j++) {
      const dx = positions[j].x - positions[i].x, dy = positions[j].y - positions[i].y;
      const d = Math.hypot(dx, dy);
      if (d >= minDist) continue;
      const [ux, uy] = d > 1e-6 ? [dx / d, dy / d] : [1, 0];
      const half = (minDist - d) / 2;
      push[i].x -= ux * half;
      push[i].y -= uy * half;
      push[j].x += ux * half;
      push[j].y += uy * half;
    }
  }
  return push;
}
