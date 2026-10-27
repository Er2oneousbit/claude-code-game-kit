// ---------------------------------------------------------------------------
// geom.test.ts
// Purpose : Ground-plane geometry: segment vs box, line of sight, push-out, move and slide, angles.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { boxAt, lineOfSight, moveCircle, pushOut, rayDistance, segmentHitsBox, turnToward, wrapAngle, yawOf } from "../src/core/geom";

const house = boxAt(0, 0, 2, 2);
const world = boxAt(0, 0, 20, 20);

describe("segmentHitsBox and lineOfSight", () => {
  test("a line through the box is blocked, one beside it is not", () => {
    expect(segmentHitsBox({ x: -5, z: 0 }, { x: 5, z: 0 }, house)).toBe(true);
    expect(segmentHitsBox({ x: -5, z: 2 }, { x: 5, z: 2 }, house)).toBe(false);
    expect(lineOfSight({ x: -5, z: 0 }, { x: 5, z: 0 }, [house])).toBe(false);
    expect(lineOfSight({ x: -5, z: 3 }, { x: 5, z: 3 }, [house])).toBe(true);
  });
  test("a segment that stops short of the box is clear", () => {
    expect(segmentHitsBox({ x: -5, z: 0 }, { x: -2, z: 0 }, house)).toBe(false);
  });
  test("axis-parallel segments work (zero direction on one axis)", () => {
    expect(segmentHitsBox({ x: 0, z: -5 }, { x: 0, z: 5 }, house)).toBe(true);
    expect(segmentHitsBox({ x: 3, z: -5 }, { x: 3, z: 5 }, house)).toBe(false);
  });
});

describe("pushOut and moveCircle", () => {
  test("a circle touching a side is pushed out to exactly its radius", () => {
    const p = pushOut({ x: 1.2, z: 0 }, 0.5, house);
    expect(p.x).toBeCloseTo(1.5);
    expect(p.z).toBeCloseTo(0);
  });
  test("a center inside the box leaves by the nearest side", () => {
    const p = pushOut({ x: 0.9, z: 0.1 }, 0.5, house);
    expect(p.x).toBeCloseTo(1.5);
  });
  test("moving into a wall slides along it", () => {
    const p = moveCircle({ x: -1.6, z: -0.5 }, { x: 0.5, z: 0.4 }, 0.5, [house], world);
    expect(p.x).toBeCloseTo(-1.5);
    expect(p.z).toBeCloseTo(-0.1);
  });
  test("bounds keep the circle inside the world", () => {
    const p = moveCircle({ x: 9, z: 0 }, { x: 5, z: 0 }, 0.5, [], world);
    expect(p.x).toBeCloseTo(9.5);
  });
});

describe("rayDistance", () => {
  test("stops at the first box face, or runs to max distance", () => {
    expect(rayDistance({ x: -5, z: 0 }, { x: 1, z: 0 }, 10, [house])).toBeCloseTo(4);
    expect(rayDistance({ x: -5, z: 0 }, { x: -1, z: 0 }, 10, [house])).toBeCloseTo(10);
    expect(rayDistance({ x: -5, z: 3 }, { x: 1, z: 0 }, 10, [house])).toBeCloseTo(10);
    expect(rayDistance({ x: -5, z: 0 }, { x: 1, z: 0 }, 2, [house])).toBeCloseTo(2);
  });
});

describe("angles", () => {
  test("yawOf matches Three.js rotation.y for a model facing +z", () => {
    expect(yawOf({ x: 0, z: 1 })).toBeCloseTo(0);
    expect(yawOf({ x: 1, z: 0 })).toBeCloseTo(Math.PI / 2);
  });
  test("wrapAngle and turnToward take the short way round", () => {
    expect(wrapAngle(3 * Math.PI)).toBeCloseTo(Math.PI);
    expect(turnToward(3, -3, 0.1)).toBeCloseTo(3.1);
    expect(turnToward(0, 0.05, 0.1)).toBeCloseTo(0.05);
  });
});
