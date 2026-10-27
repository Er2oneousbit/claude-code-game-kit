// ---------------------------------------------------------------------------
// astar.test.ts
// Purpose : Pathfinding on tiny hand-made grids (SOP-14 step 6): straight line,
//           around a wall, no path, start equals goal, node cap.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { findPath } from "../src/core/astar";
import { Grid } from "../src/core/grid";

const open = Grid.parse(["#####", "#...#", "#...#", "#...#", "#####"]);
const walled = Grid.parse(["#######", "#..#..#", "#..#..#", "#.....#", "#######"]);
const sealed = Grid.parse(["#######", "#..#..#", "#######"]);

describe("findPath", () => {
  it("walks a straight line, excluding the start and ending at the goal", () => {
    expect(findPath(open, { x: 1, y: 1 }, { x: 3, y: 1 })).toEqual([{ x: 2, y: 1 }, { x: 3, y: 1 }]);
  });

  it("goes around a wall with a shortest path", () => {
    const path = findPath(walled, { x: 1, y: 1 }, { x: 5, y: 1 })!;
    expect(path).not.toBeNull();
    expect(path.length).toBe(8); // down 2, across 4, up 2
    expect(path.every((c) => walled.walkable(c.x, c.y))).toBe(true);
    expect(path[path.length - 1]).toEqual({ x: 5, y: 1 });
  });

  it("returns null when the goal cannot be reached", () => {
    expect(findPath(sealed, { x: 1, y: 1 }, { x: 4, y: 1 })).toBeNull();
  });

  it("returns null for a goal inside a wall", () => {
    expect(findPath(open, { x: 1, y: 1 }, { x: 0, y: 0 })).toBeNull();
  });

  it("returns an empty path when already there", () => {
    expect(findPath(open, { x: 2, y: 2 }, { x: 2, y: 2 })).toEqual([]);
  });

  it("gives up past the node cap instead of stalling a frame", () => {
    expect(findPath(walled, { x: 1, y: 1 }, { x: 5, y: 1 }, 2)).toBeNull();
  });
});
