// ---------------------------------------------------------------------------
// grid.ts
// Purpose : The level as a tile grid parsed from ASCII rows, plus the queries the
//           AI and movement need: walkable cells, neighbors, finding markers, and
//           moving a box through the grid without entering walls.
// Usage   : const g = Grid.parse(LEVEL_ROWS); g.walkable(x, y); g.find("P")
//           moveBox(g, pos, delta, half) -> new position after wall collision
// Notes   : Engine-free (no Phaser), unit tested. Coordinates: cells are integers,
//           positions are floats in tile units (cell centre = x + 0.5).
//
// Pseudocode (moveBox):
//   move along x, if the box overlaps a wall cell, push it back to the wall edge
//   then the same along y (axis-separated, so sliding along walls works)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type Cell = { x: number; y: number };
export type Vec = { x: number; y: number };

export const WALL = "#";

export class Grid {
  constructor(readonly width: number, readonly height: number, private readonly rows: readonly string[]) {}

  static parse(rows: readonly string[]): Grid {
    if (rows.length === 0) throw new Error("level has no rows");
    const width = rows[0].length;
    rows.forEach((r, i) => {
      if (r.length !== width) throw new Error(`level row ${i} is ${r.length} wide, expected ${width}`);
    });
    return new Grid(width, rows.length, rows);
  }

  charAt(x: number, y: number): string {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return WALL;
    return this.rows[y][x];
  }

  walkable(x: number, y: number): boolean {
    return this.charAt(x, y) !== WALL;
  }

  /** Every cell holding `ch`, row by row. */
  find(ch: string): Cell[] {
    const out: Cell[] = [];
    for (let y = 0; y < this.height; y++) {
      for (let x = 0; x < this.width; x++) if (this.rows[y][x] === ch) out.push({ x, y });
    }
    return out;
  }

  /** 4-way walkable neighbors. */
  neighbors(c: Cell): Cell[] {
    return [
      { x: c.x + 1, y: c.y },
      { x: c.x - 1, y: c.y },
      { x: c.x, y: c.y + 1 },
      { x: c.x, y: c.y - 1 },
    ].filter((n) => this.walkable(n.x, n.y));
  }

  /** Walkable cells within a Chebyshev radius of `c` (for wander and flee targets). */
  cellsNear(c: Cell, radius: number): Cell[] {
    const out: Cell[] = [];
    for (let y = c.y - radius; y <= c.y + radius; y++) {
      for (let x = c.x - radius; x <= c.x + radius; x++) if (this.walkable(x, y)) out.push({ x, y });
    }
    return out;
  }
}

export function cellOf(p: Vec): Cell {
  return { x: Math.floor(p.x), y: Math.floor(p.y) };
}

export function dist(a: Vec, b: Vec): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function overlapsWall(g: Grid, p: Vec, half: number): boolean {
  const x0 = Math.floor(p.x - half), x1 = Math.floor(p.x + half - 1e-6);
  const y0 = Math.floor(p.y - half), y1 = Math.floor(p.y + half - 1e-6);
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (!g.walkable(x, y)) return true;
  return false;
}

/** Move a square box of half-size `half` by `delta`, stopping at walls, sliding along them. */
export function moveBox(g: Grid, pos: Vec, delta: Vec, half: number): Vec {
  let p = { x: pos.x + delta.x, y: pos.y };
  if (overlapsWall(g, p, half)) {
    p.x = delta.x > 0 ? Math.floor(p.x + half) - half : Math.floor(p.x - half) + 1 + half;
    if (overlapsWall(g, p, half)) p.x = pos.x; // still stuck (corner case): do not move on x
  }
  p = { x: p.x, y: p.y + delta.y };
  if (overlapsWall(g, p, half)) {
    p.y = delta.y > 0 ? Math.floor(p.y + half) - half : Math.floor(p.y - half) + 1 + half;
    if (overlapsWall(g, p, half)) p.y = pos.y;
  }
  return p;
}
