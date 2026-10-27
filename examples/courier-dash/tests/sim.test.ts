// ---------------------------------------------------------------------------
// sim.test.ts
// Purpose : The run rules: clock, stamina, pickup and delivery, win, caught, god mode, time up.
// Usage   : python tools/dev.py test
// Notes   : Tests move the courier by setting sim.courier.pos directly where the route itself is
//           not what is being tested.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, test } from "vitest";
import { type Input, NO_INPUT, Sim, type SimEvent } from "../src/core/sim";
import { TUNING } from "../src/core/tuning";

const types = (evs: SimEvent[]) => evs.map((e) => e.type);
function steps(sim: Sim, n: number, input: Input = NO_INPUT): SimEvent[] {
  const out: SimEvent[] = [];
  for (let i = 0; i < n; i++) out.push(...sim.step(input));
  return out;
}
const perSecond = (s: number) => Math.ceil(s / TUNING.stepSeconds);

describe("clock", () => {
  test("does not run until the first move", () => {
    const sim = new Sim();
    steps(sim, 120);
    expect(sim.started).toBe(false);
    expect(sim.timeLeft).toBe(TUNING.run.seconds);
    expect(types(sim.step({ x: 1, z: 0, sprint: false }))).toContain("START");
  });

  test("time up ends the run, with a low-time warning first", () => {
    const sim = new Sim({ god: true });
    sim.step({ x: 1, z: 0, sprint: false });
    const evs = types(steps(sim, perSecond(TUNING.run.seconds) + 2));
    expect(evs.indexOf("LOW_TIME")).toBeGreaterThanOrEqual(0);
    expect(evs.indexOf("LOW_TIME")).toBeLessThan(evs.indexOf("TIME_UP"));
    expect(sim.outcome).toBe("timeup");
  });
});

describe("stamina", () => {
  test("sprint is faster, drains the bar, and an empty bar locks sprint until it refills", () => {
    const sim = new Sim({ god: true });
    steps(sim, 30, { x: -1, z: 0, sprint: true });
    expect(sim.courier.sprinting).toBe(true);
    expect(sim.speed).toBeGreaterThan(TUNING.courier.walkSpeed);
    steps(sim, perSecond(TUNING.courier.staminaMax), { x: 0, z: -1, sprint: true });
    expect(sim.courier.exhausted).toBe(true);
    expect(sim.courier.sprinting).toBe(false);
    steps(sim, perSecond(TUNING.courier.staminaToStart / TUNING.courier.staminaRegen) + 5);
    sim.step({ x: 0, z: 1, sprint: true });
    expect(sim.courier.sprinting).toBe(true);
  });
});

describe("parcels", () => {
  test("pick up one at a time, deliver at the depot", () => {
    const sim = new Sim({ god: true });
    sim.courier.pos = { ...sim.level.parcels[1] };
    expect(sim.step(NO_INPUT)).toContainEqual({ type: "PICKUP", parcel: 1 });
    sim.courier.pos = { ...sim.level.parcels[2] };
    expect(types(sim.step(NO_INPUT))).not.toContain("PICKUP"); // hands full
    expect(sim.parcels[2]).toBe("waiting");
    sim.courier.pos = { ...sim.level.depot };
    expect(sim.step(NO_INPUT)).toContainEqual({ type: "DELIVERED", parcel: 1 });
    expect(sim.delivered).toBe(1);
    expect(sim.carrying).toBeNull();
  });

  test("picking up freezes the courier for the pick-up animation", () => {
    const sim = new Sim({ god: true });
    sim.courier.pos = { ...sim.level.parcels[1] };
    sim.step(NO_INPUT);
    const at = { ...sim.courier.pos };
    steps(sim, Math.floor(TUNING.courier.pickupPause / TUNING.stepSeconds) - 1, { x: 1, z: 0, sprint: false });
    expect(sim.courier.pos).toEqual(at);
  });

  test("the fifth delivery wins the run, and nothing happens after the end", () => {
    const sim = new Sim({ god: true });
    let last: SimEvent[] = [];
    sim.level.parcels.forEach((p) => {
      sim.courier.pos = { ...p };
      sim.step(NO_INPUT);
      sim.courier.pos = { ...sim.level.depot };
      last = sim.step(NO_INPUT);
    });
    expect(types(last)).toContain("RUN_WON");
    expect(sim.outcome).toBe("won");
    expect(sim.step({ x: 1, z: 0, sprint: false })).toEqual([]);
  });
});

describe("the robot", () => {
  test("touching it ends the run", () => {
    const sim = new Sim();
    sim.courier.pos = { ...sim.robot.pos };
    expect(types(sim.step(NO_INPUT))).toContain("CAUGHT");
    expect(sim.outcome).toBe("caught");
  });

  test("god mode cannot be caught", () => {
    const sim = new Sim({ god: true });
    sim.courier.pos = { x: sim.robot.pos.x + 0.2, z: sim.robot.pos.z };
    steps(sim, 10);
    expect(sim.outcome).toBe("playing");
  });
});
