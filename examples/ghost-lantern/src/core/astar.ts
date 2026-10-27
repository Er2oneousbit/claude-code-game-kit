// ---------------------------------------------------------------------------
// astar.ts
// Purpose : A* pathfinding on the tile grid (SOP-14: Phaser has no built-in
//           pathfinding, and a small grid needs nothing heavier).
// Usage   : const path = findPath(grid, from, to)   // cells after `from`, ending at `to`; null if unreachable
// Notes   : 4-way moves, cost 1, Manhattan heuristic (admissible, so paths are shortest).
//           Open set is a plain array: fine for this map size (440 cells). Swap in a
//           binary heap if maps grow past a few thousand cells (measure first, SOP-10).
//           maxNodes caps the work per call so a bad request cannot stall a frame.
//
// Pseudocode:
//   open = {from}; g[from] = 0
//   loop: take the open cell with the lowest g + h; if it is `to`, walk cameFrom back
//         else for each walkable neighbor with a better g: record it, push to open
//   open empty or node cap hit -> null
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { Cell, Grid } from "./grid";

const key = (c: Cell): number => c.y * 10000 + c.x;

export function findPath(grid: Grid, from: Cell, to: Cell, maxNodes = 5000): Cell[] | null {
  if (!grid.walkable(to.x, to.y) || !grid.walkable(from.x, from.y)) return null;
  if (from.x === to.x && from.y === to.y) return [];
  const h = (c: Cell): number => Math.abs(c.x - to.x) + Math.abs(c.y - to.y);
  const g = new Map<number, number>([[key(from), 0]]);
  const cameFrom = new Map<number, Cell>();
  const open: Cell[] = [from];
  const closed = new Set<number>();
  let expanded = 0;

  while (open.length > 0) {
    let best = 0;
    for (let i = 1; i < open.length; i++) {
      const fi = g.get(key(open[i]))! + h(open[i]);
      const fb = g.get(key(open[best]))! + h(open[best]);
      if (fi < fb) best = i;
    }
    const cur = open.splice(best, 1)[0];
    if (cur.x === to.x && cur.y === to.y) {
      const path: Cell[] = [cur];
      let k = key(cur);
      while (cameFrom.has(k)) {
        const prev = cameFrom.get(k)!;
        if (prev.x === from.x && prev.y === from.y) break;
        path.unshift(prev);
        k = key(prev);
      }
      return path;
    }
    closed.add(key(cur));
    if (++expanded > maxNodes) return null;
    for (const n of grid.neighbors(cur)) {
      const nk = key(n);
      if (closed.has(nk)) continue;
      const tentative = g.get(key(cur))! + 1;
      if (tentative < (g.get(nk) ?? Infinity)) {
        g.set(nk, tentative);
        cameFrom.set(nk, cur);
        if (!open.some((o) => o.x === n.x && o.y === n.y)) open.push(n);
      }
    }
  }
  return null;
}
