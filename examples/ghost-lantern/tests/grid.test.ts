// ---------------------------------------------------------------------------
// grid.test.ts
// Purpose : Grid parsing and box movement against walls (the player's collision).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { Grid, moveBox } from "../src/core/grid";

const g = Grid.parse(["#####", "#...#", "#.#.#", "#...#", "#####"]);

describe("Grid", () => {
  it("rejects ragged rows", () => {
    expect(() => Grid.parse(["###", "##"])).toThrow(/row 1/);
  });

  it("treats outside the map as wall", () => {
    expect(g.walkable(-1, 2)).toBe(false);
    expect(g.walkable(1, 1)).toBe(true);
  });

  it("lists 4-way walkable neighbors only", () => {
    expect(g.neighbors({ x: 1, y: 1 })).toEqual([{ x: 2, y: 1 }, { x: 1, y: 2 }]);
  });
});

describe("moveBox", () => {
  it("moves freely in open space", () => {
    expect(moveBox(g, { x: 1.5, y: 1.5 }, { x: 0.2, y: 0 }, 0.3)).toEqual({ x: 1.7, y: 1.5 });
  });

  it("stops flush against a wall", () => {
    const p = moveBox(g, { x: 3.5, y: 1.5 }, { x: 0.5, y: 0 }, 0.3);
    expect(p.x).toBeCloseTo(4 - 0.3, 6);
  });

  it("slides along a wall when moving diagonally into it", () => {
    const p = moveBox(g, { x: 3.5, y: 1.5 }, { x: 0.5, y: 0.2 }, 0.3);
    expect(p.x).toBeCloseTo(3.7, 6);
    expect(p.y).toBeCloseTo(1.7, 6);
  });

  it("never ends inside the pillar", () => {
    const p = moveBox(g, { x: 1.5, y: 2.5 }, { x: 0.6, y: 0 }, 0.3);
    expect(p.x).toBeLessThanOrEqual(2 - 0.3 + 1e-9);
  });
});
