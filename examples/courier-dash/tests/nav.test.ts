// ---------------------------------------------------------------------------
// nav.test.ts
// Purpose : Grid A* on tiny hand-made worlds (SOP-14 step 6): straight line, around a wall,
//           no path, start equals goal, goal inside a wall.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { boxAt, dist, inBox, lineOfSight } from "../src/core/geom";
import { NavGrid } from "../src/core/nav";

const world = boxAt(0, 0, 10, 10);

describe("NavGrid.findPath", () => {
  test("open ground: one straight segment to the goal", () => {
    const nav = new NavGrid(world, [], 0.5, 0.3);
    expect(nav.findPath({ x: -3, z: 0 }, { x: 3, z: 1 })).toEqual([{ x: 3, z: 1 }]);
  });

  test("a wall in the way: the path goes around and every leg is clear", () => {
    const wall = boxAt(0, 0, 1, 6);
    const nav = new NavGrid(world, [wall], 0.5, 0.3);
    const from = { x: -3, z: 0 };
    const path = nav.findPath(from, { x: 3, z: 0 })!;
    expect(path.length).toBeGreaterThan(1);
    expect(path.at(-1)).toEqual({ x: 3, z: 0 });
    let a = from;
    for (const p of path) {
      expect(lineOfSight(a, p, nav.grown)).toBe(true);
      a = p;
    }
  });

  test("a sealed goal has no path", () => {
    const ring = [boxAt(3, -2, 4, 1), boxAt(3, 2, 4, 1), boxAt(1, 0, 1, 5), boxAt(5, 0, 1, 5)];
    const nav = new NavGrid(world, ring, 0.5, 0.3);
    expect(nav.findPath({ x: -3, z: 0 }, { x: 3, z: 0 })).toBeNull();
  });

  test("start equals goal: just the goal", () => {
    const nav = new NavGrid(world, [], 0.5, 0.3);
    expect(nav.findPath({ x: 1, z: 1 }, { x: 1.1, z: 1.1 })).toEqual([{ x: 1.1, z: 1.1 }]);
  });

  test("a goal inside a building snaps to the nearest walkable spot", () => {
    const house = boxAt(2, 0, 2, 2);
    const nav = new NavGrid(world, [house], 0.5, 0.3);
    const end = nav.findPath({ x: -3, z: 0 }, { x: 2, z: 0 })!.at(-1)!;
    expect(inBox(end, nav.grown[0])).toBe(false);
    expect(dist(end, { x: 2, z: 0 })).toBeLessThan(2);
  });
});
