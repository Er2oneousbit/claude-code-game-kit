// ---------------------------------------------------------------------------
// level.test.ts
// Purpose : Guards the level data: no spot inside a building, every parcel reachable from the
//           depot, the patrol loop drivable in straight lines, the robot starts away from the courier.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { dist, inBox, lineOfSight } from "../src/core/geom";
import { LEVEL, blockingBoxes, roadTiles } from "../src/core/level";
import { NavGrid } from "../src/core/nav";
import { TUNING } from "../src/core/tuning";

const boxes = blockingBoxes();
const courierNav = new NavGrid(LEVEL.bounds, boxes, TUNING.nav.cellSize, TUNING.courier.radius + 0.1);
const robotNav = new NavGrid(LEVEL.bounds, boxes, TUNING.nav.cellSize, TUNING.robot.radius + 0.1);

describe("level data", () => {
  test("start, depot and parcels are on open ground", () => {
    for (const p of [LEVEL.courierStart, LEVEL.depot, ...LEVEL.parcels])
      expect(courierNav.grown.some((b) => inBox(p, b))).toBe(false);
  });

  test("every parcel can be reached from the depot and carried back", () => {
    for (const p of LEVEL.parcels) {
      const there = courierNav.findPath(LEVEL.depot, p);
      expect(there).not.toBeNull();
      expect(dist(there!.at(-1)!, p)).toBeLessThan(TUNING.courier.pickupRadius);
      expect(courierNav.findPath(p, LEVEL.depot)).not.toBeNull();
    }
  });

  test("the patrol loop is drivable in straight lines", () => {
    LEVEL.patrol.forEach((a, i) => {
      const b = LEVEL.patrol[(i + 1) % LEVEL.patrol.length];
      expect(lineOfSight(a, b, robotNav.grown)).toBe(true);
    });
  });

  test("no robot start is within sight range of the courier's start", () => {
    for (const p of LEVEL.patrol) expect(dist(p, LEVEL.courierStart)).toBeGreaterThan(TUNING.robot.sightRange);
  });

  test("road tiles sit on the 3 m grid and never under a building", () => {
    const buildings = LEVEL.blocks.filter((b) => b.model.startsWith("building"));
    for (const t of roadTiles()) {
      expect(Math.abs(t.x % 3)).toBe(0);
      expect(Math.abs(t.z % 3)).toBe(0);
      expect(buildings.some((b) => Math.abs(t.x - b.x) < b.w / 2 + 1.5 && Math.abs(t.z - b.z) < b.d / 2 + 1.5)).toBe(false);
    }
  });
});
