// ---------------------------------------------------------------------------
// robot.test.ts
// Purpose : The robot's perception and every FSM transition, one test per rule (SOP-14 step 6).
// Usage   : python tools/dev.py test
// Notes   : A tiny world: a two-point patrol along the x axis, the robot starts at (-5, 0)
//           facing +x. `run` steps it with a fixed courier position.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { type Box, type V2, boxAt, dist } from "../src/core/geom";
import { NavGrid } from "../src/core/nav";
import { Robot, type RobotEvent } from "../src/core/robot";
import { TUNING } from "../src/core/tuning";

const DT = TUNING.stepSeconds;
const world = boxAt(0, 0, 30, 30);
const patrol: V2[] = [{ x: -5, z: 0 }, { x: 5, z: 0 }];
const FAR_AWAY = { x: 0, z: 14 };

function robot(boxes: Box[] = []): Robot {
  return new Robot(patrol, TUNING.robot, new NavGrid(world, boxes, 0.5, 0.7), boxes, world, 0);
}

function run(r: Robot, courier: V2, seconds: number): RobotEvent[] {
  const events: RobotEvent[] = [];
  for (let t = 0; t < seconds; t += DT) events.push(...r.step(DT, courier));
  return events;
}

describe("perception", () => {
  test("sees in front, inside range and cone", () => {
    expect(robot().canSee({ x: -1, z: 0.5 })).toBe(true);
  });
  test("blind behind, beside, and beyond range", () => {
    const r = robot();
    expect(r.canSee({ x: -7, z: 0 })).toBe(false);
    expect(r.canSee({ x: -5, z: 3 })).toBe(false);
    expect(r.canSee({ x: -5 + TUNING.robot.sightRange + 0.5, z: 0 })).toBe(false);
  });
  test("asleep until the run starts: sees nothing", () => {
    const r = robot();
    expect(r.step(DT, { x: -1, z: 0 }, false)).toEqual([]);
    expect(r.state).toBe("patrol");
  });
  test("a building blocks the view", () => {
    expect(robot([boxAt(-2, 0, 1, 2)]).canSee({ x: 0, z: 0 })).toBe(false);
  });
});

describe("state machine", () => {
  test("patrol drives the loop when it sees nothing", () => {
    const r = robot();
    run(r, FAR_AWAY, 2);
    expect(r.state).toBe("patrol");
    expect(r.pos.x).toBeGreaterThan(-5 + TUNING.robot.patrolSpeed * 1.5);
  });

  test("patrol -> alert when it sees the courier, and alert stands still", () => {
    const r = robot();
    expect(r.step(DT, { x: -1, z: 0 })).toContain("SPOTTED");
    expect(r.state).toBe("alert");
    const at = { ...r.pos };
    run(r, { x: -1, z: 0 }, TUNING.robot.alertSeconds * 0.9);
    expect(r.state).toBe("alert");
    expect(dist(r.pos, at)).toBe(0);
  });

  test("alert -> chase when still seen after the alert time", () => {
    const r = robot();
    const events = run(r, { x: -1, z: 0 }, TUNING.robot.alertSeconds + 0.05);
    expect(events).toEqual(["SPOTTED", "CHASE"]);
    expect(r.state).toBe("chase");
  });

  test("alert -> search when the courier slipped away during the alert", () => {
    const r = robot();
    r.step(DT, { x: -1, z: 0 });
    run(r, { x: -5, z: -6 }, TUNING.robot.alertSeconds + 0.05);
    expect(r.state).toBe("search");
    expect(r.lastSeen).toEqual({ x: -1, z: 0 });
  });

  test("chase closes in faster than the courier walks, slower than a sprint", () => {
    const r = robot();
    const target = { x: 2, z: 0 };
    run(r, target, TUNING.robot.alertSeconds + 0.05);
    const before = dist(r.pos, target);
    run(r, target, 0.5);
    expect(before - dist(r.pos, target)).toBeGreaterThan(TUNING.courier.walkSpeed * 0.5);
    expect(TUNING.robot.chaseSpeed).toBeGreaterThan(TUNING.courier.walkSpeed);
    expect(TUNING.robot.chaseSpeed).toBeLessThan(TUNING.courier.sprintSpeed);
  });

  test("chase -> search after losing sight for loseSightSeconds", () => {
    const r = robot([boxAt(0, 4, 4, 1)]);
    run(r, { x: -1, z: 0 }, TUNING.robot.alertSeconds + 0.05);
    expect(r.state).toBe("chase");
    const events = run(r, { x: 0, z: 8 }, TUNING.robot.loseSightSeconds + 0.1); // behind the wall
    expect(events).toContain("LOST");
    expect(r.state).toBe("search");
  });

  test("search -> return after looking around, return -> patrol on arrival", () => {
    const r = robot();
    r.step(DT, { x: -1, z: 0 });
    run(r, { x: -5, z: -6 }, TUNING.robot.alertSeconds + 0.05); // slipped away: search
    const events = run(r, FAR_AWAY, 12);
    expect(events).toContain("GAVE_UP");
    expect(events).toContain("PATROL");
    expect(r.state).toBe("patrol");
  });

  test("search -> alert when it sees the courier again", () => {
    const r = robot();
    r.step(DT, { x: -1, z: 0 });
    run(r, { x: -5, z: -6 }, TUNING.robot.alertSeconds + 0.05);
    expect(r.state).toBe("search");
    const inFront = { x: r.pos.x + Math.sin(r.yaw) * 2, z: r.pos.z + Math.cos(r.yaw) * 2 };
    expect(r.step(DT, inFront)).toContain("SPOTTED");
    expect(r.state).toBe("alert");
  });
});
