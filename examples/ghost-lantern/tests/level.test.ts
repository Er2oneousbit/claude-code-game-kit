// ---------------------------------------------------------------------------
// level.test.ts
// Purpose : Design guard for the map: right shape, one start, key and exit, the
//           key and the exit reachable, every pickup and ghost on a reachable cell.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { findPath } from "../src/core/astar";
import { Grid } from "../src/core/grid";
import { LEVEL } from "../src/game/level";

const g = Grid.parse(LEVEL);
const one = (ch: string) => {
  const cells = g.find(ch);
  expect(cells, `exactly one '${ch}'`).toHaveLength(1);
  return cells[0];
};

describe("level", () => {
  it("is closed by walls on every edge", () => {
    for (let x = 0; x < g.width; x++) expect(g.walkable(x, 0) || g.walkable(x, g.height - 1)).toBe(false);
    for (let y = 0; y < g.height; y++) expect(g.walkable(0, y) || g.walkable(g.width - 1, y)).toBe(false);
  });

  it("has one start, one key and one exit, all connected", () => {
    const start = one("P"), key = one("K"), exit = one("X");
    expect(findPath(g, start, key)).not.toBeNull();
    expect(findPath(g, key, exit)).not.toBeNull();
  });

  it("puts every ghost and oil where the player can reach", () => {
    const start = one("P");
    for (const c of [...g.find("G"), ...g.find("o")]) expect(findPath(g, start, c), `${c.x},${c.y}`).not.toBeNull();
  });

  it("keeps ghosts out of the starting room's sense range", () => {
    const start = one("P");
    for (const c of g.find("G")) expect(Math.hypot(c.x - start.x, c.y - start.y)).toBeGreaterThan(8);
  });
});
