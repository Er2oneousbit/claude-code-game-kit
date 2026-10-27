// ---------------------------------------------------------------------------
// nav.ts
// Purpose : Grid pathfinding for the robot and the autoplay bot: an occupancy grid built from
//           the building boxes, A* over it, and string pulling so paths are straight lines.
// Usage   : const nav = new NavGrid(bounds, boxes, 0.5, 0.6)  // cell size, clearance (agent radius)
//           const path = nav.findPath(from, to)                 // [..., to] or null
// Notes   : Engine-free. 8-connected, no corner cutting, octile heuristic, binary heap.
//           A goal inside a building snaps to the nearest walkable cell. Smoothing keeps a
//           point only when the straight line to the next one would clip an inflated box.
//
// Pseudocode:
//   blocked[cell] = cell center inside any box inflated by clearance (or outside bounds - clearance)
//   A*: open = heap by f = g + h ; pop best ; for 8 neighbors (diagonals only if both sides free)
//       relax g ; stop at goal ; walk parents back
//   smooth: anchor = start ; keep the farthest next point with a clear line ; repeat
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { type Box, type V2, inBox, inflate, lineOfSight } from "./geom";

const SQRT2 = Math.SQRT2;

export class NavGrid {
  readonly cols: number;
  readonly rows: number;
  readonly blocked: Uint8Array;
  /** Boxes grown by the clearance: a segment that misses all of them is safe for the agent. */
  readonly grown: Box[];

  constructor(readonly bounds: Box, boxes: readonly Box[], readonly cell: number, readonly clearance: number) {
    this.cols = Math.round((bounds.maxX - bounds.minX) / cell);
    this.rows = Math.round((bounds.maxZ - bounds.minZ) / cell);
    this.grown = boxes.map((b) => inflate(b, clearance));
    const inner = inflate(bounds, -clearance);
    this.blocked = new Uint8Array(this.cols * this.rows);
    for (let r = 0; r < this.rows; r++)
      for (let c = 0; c < this.cols; c++) {
        const p = this.center(c, r);
        this.blocked[r * this.cols + c] = !inBox(p, inner) || this.grown.some((b) => inBox(p, b)) ? 1 : 0;
      }
  }

  center(c: number, r: number): V2 {
    return { x: this.bounds.minX + (c + 0.5) * this.cell, z: this.bounds.minZ + (r + 0.5) * this.cell };
  }

  cellOf(p: V2): [number, number] {
    const c = Math.floor((p.x - this.bounds.minX) / this.cell);
    const r = Math.floor((p.z - this.bounds.minZ) / this.cell);
    return [Math.min(Math.max(c, 0), this.cols - 1), Math.min(Math.max(r, 0), this.rows - 1)];
  }

  walkable(c: number, r: number): boolean {
    return c >= 0 && r >= 0 && c < this.cols && r < this.rows && this.blocked[r * this.cols + c] === 0;
  }

  /** Nearest walkable cell to p (breadth-first rings), or null if the grid is solid. */
  nearestWalkable(p: V2): [number, number] | null {
    const [c0, r0] = this.cellOf(p);
    if (this.walkable(c0, r0)) return [c0, r0];
    for (let ring = 1; ring < Math.max(this.cols, this.rows); ring++) {
      let best: [number, number] | null = null;
      let bestD = Infinity;
      for (let dr = -ring; dr <= ring; dr++)
        for (let dc = -ring; dc <= ring; dc++) {
          if (Math.max(Math.abs(dc), Math.abs(dr)) !== ring || !this.walkable(c0 + dc, r0 + dr)) continue;
          const q = this.center(c0 + dc, r0 + dr);
          const d = Math.hypot(q.x - p.x, q.z - p.z);
          if (d < bestD) [best, bestD] = [[c0 + dc, r0 + dr], d];
        }
      if (best) return best;
    }
    return null;
  }

  /** Path from `from` to `to` (excluding from, ending at to or the nearest walkable spot), or null. */
  findPath(from: V2, to: V2): V2[] | null {
    const start = this.nearestWalkable(from);
    const goal = this.nearestWalkable(to);
    if (!start || !goal) return null;
    const goalPoint = this.walkable(...this.cellOf(to)) ? to : this.center(...goal);
    const idx = (c: number, r: number) => r * this.cols + c;
    const s = idx(...start);
    const g = idx(...goal);
    if (s === g) return [goalPoint];

    const cost = new Float64Array(this.cols * this.rows).fill(Infinity);
    const parent = new Int32Array(this.cols * this.rows).fill(-1);
    const closed = new Uint8Array(this.cols * this.rows);
    const heap = new MinHeap();
    const h = (i: number) => {
      const dc = Math.abs((i % this.cols) - goal[0]);
      const dr = Math.abs(Math.floor(i / this.cols) - goal[1]);
      return (dc + dr + (SQRT2 - 2) * Math.min(dc, dr)) * this.cell;
    };
    cost[s] = 0;
    heap.push(s, h(s));
    while (heap.size > 0) {
      const cur = heap.pop();
      if (cur === g) break;
      if (closed[cur]) continue;
      closed[cur] = 1;
      const c = cur % this.cols;
      const r = Math.floor(cur / this.cols);
      for (let dr = -1; dr <= 1; dr++)
        for (let dc = -1; dc <= 1; dc++) {
          if ((dc === 0 && dr === 0) || !this.walkable(c + dc, r + dr)) continue;
          if (dc !== 0 && dr !== 0 && (!this.walkable(c + dc, r) || !this.walkable(c, r + dr))) continue;
          const n = idx(c + dc, r + dr);
          const ng = cost[cur] + (dc !== 0 && dr !== 0 ? SQRT2 : 1) * this.cell;
          if (ng < cost[n]) {
            cost[n] = ng;
            parent[n] = cur;
            heap.push(n, ng + h(n));
          }
        }
    }
    if (parent[g] === -1) return null;

    const cells: V2[] = [];
    for (let i = g; i !== s; i = parent[i]) cells.push(this.center(i % this.cols, Math.floor(i / this.cols)));
    cells.reverse();
    cells[cells.length - 1] = goalPoint;
    return this.smooth(from, cells);
  }

  /** String pulling: drop every point the agent can skip with a clear straight line. */
  smooth(from: V2, points: V2[]): V2[] {
    const out: V2[] = [];
    let anchor = from;
    let i = 0;
    while (i < points.length) {
      let far = i;
      for (let j = points.length - 1; j > i; j--)
        if (lineOfSight(anchor, points[j], this.grown)) {
          far = j;
          break;
        }
      out.push(points[far]);
      anchor = points[far];
      i = far + 1;
    }
    return out;
  }
}

/** Binary min-heap of (index, priority). Duplicates allowed; stale pops are skipped by `closed`. */
class MinHeap {
  private ids: number[] = [];
  private keys: number[] = [];
  get size(): number {
    return this.ids.length;
  }
  push(id: number, key: number): void {
    this.ids.push(id);
    this.keys.push(key);
    let i = this.ids.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this.swap(i, p);
      i = p;
    }
  }
  pop(): number {
    const top = this.ids[0];
    const lastId = this.ids.pop()!;
    const lastKey = this.keys.pop()!;
    if (this.ids.length > 0) {
      this.ids[0] = lastId;
      this.keys[0] = lastKey;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < this.ids.length && this.keys[l] < this.keys[m]) m = l;
        if (r < this.ids.length && this.keys[r] < this.keys[m]) m = r;
        if (m === i) break;
        this.swap(i, m);
        i = m;
      }
    }
    return top;
  }
  private swap(a: number, b: number): void {
    [this.ids[a], this.ids[b]] = [this.ids[b], this.ids[a]];
    [this.keys[a], this.keys[b]] = [this.keys[b], this.keys[a]];
  }
}
