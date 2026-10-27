// ---------------------------------------------------------------------------
// regressions.test.ts
// Purpose : Regression tests for the bugs a Fable code review proved on 2026-10-26 (its probe
//           tests, ported here): a search that never ended, a chase pinned on a tree corner,
//           and the clock's last step.
// Usage   : python tools/dev.py test
// Notes   : The pocket is the 0.9 m gap between tree-small and the north fence: the courier
//           (r 0.35) fits, the robot (r 0.6) does not, so A* can only reach the nearest cell.
//           Each test failed on the code before the fix.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5), from the Fable review's probes
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { type V2, dist, normalize, sub } from "../src/core/geom";
import { LEVEL } from "../src/core/level";
import { NO_INPUT, Sim } from "../src/core/sim";
import { TUNING } from "../src/core/tuning";

const DT = TUNING.stepSeconds;
const OUT_OF_SIGHT = { x: 12, z: -12 };

describe("search always ends (lastSeen in a spot the robot cannot reach)", () => {
  test("seen in the pocket, then gone: the robot gives up and returns to patrol", () => {
    const sim = new Sim();
    const r = sim.robot;
    r.pos = { x: 2.5, z: 14.3 };
    r.yaw = -Math.PI / 2; // facing -x along the fence
    expect(r.step(DT, { x: -4.9, z: 14.45 }, true)).toContain("SPOTTED");
    const seen = new Set<string>();
    for (let t = 0; t < 60; t += DT) {
      r.step(DT, OUT_OF_SIGHT, true);
      seen.add(r.state);
    }
    expect(seen.has("search")).toBe(true);
    expect(seen.has("patrol")).toBe(true);
  });

  test("the search spot is a cell the robot fits in, next to what it saw", () => {
    const sim = new Sim();
    const r = sim.robot;
    r.pos = { x: 2.5, z: 14.3 };
    r.yaw = -Math.PI / 2;
    const seenAt = { x: -4.9, z: 14.45 };
    r.step(DT, seenAt, true);
    for (let t = 0; t < TUNING.robot.alertSeconds + 0.05; t += DT) r.step(DT, OUT_OF_SIGHT, true);
    expect(r.state).toBe("search");
    expect(r.nav.walkable(...r.nav.cellOf(r.searchSpot!))).toBe(true);
    expect(dist(r.searchSpot!, seenAt)).toBeLessThan(1.5);
  });

  test("courier seen at the pocket slips out south-west: the robot returns to patrol", () => {
    const sim = new Sim();
    sim.started = true;
    const r = sim.robot;
    r.pos = { x: 3.5, z: 14.3 }; // east on the fence line, 7.1 m from the courier
    r.yaw = -Math.PI / 2;
    sim.courier.pos = { x: -3.6, z: 14.5 };
    const route: { to: V2; sprint: boolean }[] = [
      { to: { x: -4.6, z: 14.55 }, sprint: false }, // into the pocket
      { to: { x: -5.5, z: 13.4 }, sprint: true }, // out the west side, around the tree
      { to: { x: -7.5, z: 12.0 }, sprint: true },
      { to: { x: -12, z: 7.5 }, sprint: true },
      { to: { x: -12, z: 4 }, sprint: true },
    ];
    let leg = 0;
    const states = new Set<string>();
    for (let t = 0; t < 45 && sim.outcome === "playing"; t += DT) {
      let input = NO_INPUT;
      if (leg < route.length) {
        if (dist(route[leg].to, sim.courier.pos) < 0.3) leg++;
        else {
          const n = normalize(sub(route[leg].to, sim.courier.pos));
          input = { x: n.x, z: n.z, sprint: route[leg].sprint };
        }
      }
      sim.step(input);
      states.add(r.state);
    }
    expect(sim.outcome).toBe("playing");
    expect(states.has("search")).toBe(true);
    expect(states.has("patrol")).toBe(true);
  });
});

describe("chase stuck detection", () => {
  test("pinned on the tree-small corner with the courier in the pocket: it does not stay frozen in chase", () => {
    const sim = new Sim();
    sim.started = true;
    const r = sim.robot;
    r.pos = { x: -6.6, z: 13.9 };
    r.yaw = Math.PI / 2; // facing +x
    sim.courier.pos = { x: -4.3, z: 14.6 };
    let posAt5: V2 = { x: 0, z: 0 };
    const states = new Set<string>();
    for (let t = 0; t < 20 && sim.outcome === "playing"; t += DT) {
      sim.step(NO_INPUT);
      states.add(r.state);
      if (Math.abs(t - 5) < DT / 2) posAt5 = { ...r.pos };
    }
    const moved = dist(posAt5, r.pos) > 0.05;
    expect(states.has("chase")).toBe(true);
    expect(sim.outcome === "caught" || r.state !== "chase" || moved).toBe(true);
  });
});

describe("clock", () => {
  test("a 90 s run is exactly 90 s of steps", () => {
    const sim = new Sim({ god: true });
    let n = 0;
    sim.step({ x: 1, z: 0, sprint: false }); // START, the first counted step
    n++;
    while (sim.outcome === "playing") {
      sim.step(NO_INPUT);
      n++;
    }
    expect(sim.outcome).toBe("timeup");
    expect(n).toBe(Math.round(TUNING.run.seconds / DT));
    expect(sim.timeLeft).toBe(0);
    expect(sim.elapsed).toBeCloseTo(TUNING.run.seconds, 9);
  });

  test("the fifth delivery in the step the clock reaches zero is time up, not a win", () => {
    const sim = new Sim({ god: true });
    sim.step({ x: 1, z: 0, sprint: false }); // start the clock
    for (let i = 0; i < 4; i++) {
      sim.courier.pos = { ...LEVEL.parcels[i] };
      sim.step(NO_INPUT);
      sim.courier.pos = { ...LEVEL.depot };
      sim.step(NO_INPUT);
    }
    sim.courier.pos = { ...LEVEL.parcels[4] };
    sim.step(NO_INPUT); // carrying the fifth
    sim.courier.pos = { x: 0, z: 5 }; // away from the depot while the clock runs down
    while (sim.timeLeft > DT * 1.5) sim.step(NO_INPUT); // one step left
    expect(sim.outcome).toBe("playing");
    sim.courier.pos = { ...LEVEL.depot };
    const evs = sim.step(NO_INPUT).map((e) => e.type);
    expect(evs).toContain("TIME_UP");
    expect(evs).not.toContain("DELIVERED");
    expect(sim.outcome).toBe("timeup");
    expect(sim.delivered).toBe(4);
  });

  test("a delivery one step before zero still wins", () => {
    const sim = new Sim({ god: true });
    sim.step({ x: 1, z: 0, sprint: false });
    for (let i = 0; i < 4; i++) {
      sim.courier.pos = { ...LEVEL.parcels[i] };
      sim.step(NO_INPUT);
      sim.courier.pos = { ...LEVEL.depot };
      sim.step(NO_INPUT);
    }
    sim.courier.pos = { ...LEVEL.parcels[4] };
    sim.step(NO_INPUT);
    sim.courier.pos = { x: 0, z: 5 };
    while (sim.timeLeft > DT * 2.5) sim.step(NO_INPUT); // two steps left
    sim.courier.pos = { ...LEVEL.depot };
    expect(sim.step(NO_INPUT).map((e) => e.type)).toContain("RUN_WON");
    expect(sim.timeLeft).toBeCloseTo(DT, 9);
  });
});
