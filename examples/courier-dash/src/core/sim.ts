// ---------------------------------------------------------------------------
// sim.ts
// Purpose : One run of Courier Dash, engine-free: the courier (walk, sprint, stamina), the
//           parcels, the depot, the clock, the robot and the outcome. The renderer only draws
//           what this holds, which is why the whole game can be played in a unit test.
// Usage   : const sim = new Sim({ robotStart: 0 })
//           each fixed step: const events = sim.step({ x, z, sprint })   // input in world axes
//           sim.outcome: "playing" | "won" | "caught" | "timeup"
// Notes   : Fixed step (TUNING.stepSeconds): the same inputs give the same run on any machine.
//           The clock starts on the first move, and the robot perceives nothing before that, so
//           watching its patrol before moving is free.
//           One parcel at a time (pillar 2). Touching the robot ends the run.
//           The clock counts whole steps, so a 90 s run is exactly 5400 steps; the step that
//           reaches 0.0 s ends the run as time up before anything else moves (no last-step win).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): clock from an integer step count, time up
//           checked first, so a delivery in the step the clock hits zero no longer wins.
// ---------------------------------------------------------------------------
import { type Box, type V2, dist, len, moveCircle, turnToward, yawOf } from "./geom";
import { LEVEL, blockingBoxes } from "./level";
import { NavGrid } from "./nav";
import { Robot, type RobotEvent } from "./robot";
import { TUNING, type Tuning } from "./tuning";

export type Input = { x: number; z: number; sprint: boolean };
export type Outcome = "playing" | "won" | "caught" | "timeup";
export type SimEvent =
  | { type: "START" | "LOW_TIME" | "CAUGHT" | "TIME_UP" | "RUN_WON" }
  | { type: "PICKUP" | "DELIVERED"; parcel: number }
  | { type: RobotEvent };
export type ParcelState = "waiting" | "carried" | "delivered";
export type SimOptions = { tuning?: Tuning; robotStart?: number; god?: boolean };

export const NO_INPUT: Input = { x: 0, z: 0, sprint: false };

export class Sim {
  readonly t: Tuning;
  readonly level = LEVEL;
  readonly boxes: Box[];
  /** Grid for the courier's size (the autoplay bot plans on it). */
  readonly courierNav: NavGrid;
  readonly robot: Robot;
  readonly god: boolean;

  outcome: Outcome = "playing";
  started = false;
  elapsed = 0;
  timeLeft: number;
  courier = { pos: { ...LEVEL.courierStart }, vel: { x: 0, z: 0 }, yaw: Math.PI, stamina: 0, sprinting: false, exhausted: false, pause: 0 };
  carrying: number | null = null;
  parcels: ParcelState[];
  delivered = 0;
  private lowTimeSent = false;
  /** Steps since the run started; elapsed and timeLeft derive from it (no float drift). */
  private ticks = 0;

  constructor(opts: SimOptions = {}) {
    this.t = opts.tuning ?? TUNING;
    this.god = opts.god ?? false;
    this.boxes = blockingBoxes();
    this.timeLeft = this.t.run.seconds;
    this.courier.stamina = this.t.courier.staminaMax;
    this.parcels = LEVEL.parcels.map(() => "waiting");
    this.courierNav = new NavGrid(LEVEL.bounds, this.boxes, this.t.nav.cellSize, this.t.courier.radius + 0.1);
    const robotNav = new NavGrid(LEVEL.bounds, this.boxes, this.t.nav.cellSize, this.t.robot.radius + 0.1);
    this.robot = new Robot(LEVEL.patrol, this.t.robot, robotNav, this.boxes, LEVEL.bounds, opts.robotStart ?? 0);
  }

  get speed(): number {
    return len(this.courier.vel);
  }

  step(input: Input, dt = this.t.stepSeconds): SimEvent[] {
    if (this.outcome !== "playing") return [];
    const events: SimEvent[] = [];
    const moving = Math.hypot(input.x, input.z) > 0.05;
    if (!this.started && moving) {
      this.started = true;
      events.push({ type: "START" });
    }

    if (this.started) {
      this.ticks++;
      const total = Math.round(this.t.run.seconds / this.t.stepSeconds);
      this.elapsed = this.ticks * this.t.stepSeconds;
      this.timeLeft = Math.max(0, total - this.ticks) * this.t.stepSeconds;
      if (!this.lowTimeSent && this.timeLeft <= this.t.run.lowTimeSeconds) {
        this.lowTimeSent = true;
        events.push({ type: "LOW_TIME" });
      }
      if (this.timeLeft <= 0) {
        this.outcome = "timeup";
        events.push({ type: "TIME_UP" });
        return events;
      }
    }

    this.moveCourier(input, dt);
    this.handleParcels(events);
    for (const ev of this.robot.step(dt, this.courier.pos, this.started)) events.push({ type: ev });

    if (this.outcome === "playing") {
      const touch = this.t.courier.radius + this.t.robot.radius + this.t.robot.catchMargin;
      if (!this.god && dist(this.robot.pos, this.courier.pos) < touch) {
        this.outcome = "caught";
        events.push({ type: "CAUGHT" });
      }
    }
    return events;
  }

  private moveCourier(input: Input, dt: number): void {
    const c = this.courier;
    const k = this.t.courier;
    let dir = { x: input.x, z: input.z };
    const mag = Math.hypot(dir.x, dir.z);
    if (mag > 1) dir = { x: dir.x / mag, z: dir.z / mag };
    if (c.pause > 0) {
      c.pause -= dt;
      dir = { x: 0, z: 0 };
    }
    const moving = Math.hypot(dir.x, dir.z) > 0.05;

    // Stamina: an emptied bar must refill to staminaToStart before sprint works again.
    if (c.exhausted && c.stamina >= k.staminaToStart) c.exhausted = false;
    c.sprinting = input.sprint && moving && !c.exhausted && c.stamina > 0;
    if (c.sprinting) {
      c.stamina = Math.max(0, c.stamina - dt);
      if (c.stamina === 0) c.exhausted = true;
    } else {
      c.stamina = Math.min(k.staminaMax, c.stamina + k.staminaRegen * dt);
    }

    const top = c.sprinting ? k.sprintSpeed : k.walkSpeed;
    const want = { x: dir.x * top, z: dir.z * top };
    const dv = { x: want.x - c.vel.x, z: want.z - c.vel.z };
    const dvLen = Math.hypot(dv.x, dv.z);
    const maxDv = k.accel * dt;
    c.vel = dvLen <= maxDv ? want : { x: c.vel.x + (dv.x / dvLen) * maxDv, z: c.vel.z + (dv.z / dvLen) * maxDv };

    const before = c.pos;
    c.pos = moveCircle(c.pos, { x: c.vel.x * dt, z: c.vel.z * dt }, k.radius, this.boxes, this.level.bounds);
    // Walls eat velocity, so pushing into a house does not keep a full-speed run "stored".
    c.vel = { x: (c.pos.x - before.x) / dt, z: (c.pos.z - before.z) / dt };
    if (moving) c.yaw = turnToward(c.yaw, yawOf(dir), k.turnRate * dt);
  }

  private handleParcels(events: SimEvent[]): void {
    const k = this.t.courier;
    if (this.carrying === null) {
      const i = this.parcels.findIndex((s, n) => s === "waiting" && dist(this.level.parcels[n], this.courier.pos) < k.pickupRadius);
      if (i >= 0) {
        this.parcels[i] = "carried";
        this.carrying = i;
        this.courier.pause = k.pickupPause;
        events.push({ type: "PICKUP", parcel: i });
      }
    } else if (dist(this.level.depot, this.courier.pos) < k.deliverRadius) {
      const i = this.carrying;
      this.parcels[i] = "delivered";
      this.carrying = null;
      this.delivered++;
      events.push({ type: "DELIVERED", parcel: i });
      if (this.delivered === this.parcels.length) {
        this.outcome = "won";
        events.push({ type: "RUN_WON" });
      }
    }
  }

  /** Where the parcel is drawn: its spot, or with the courier. */
  parcelPos(i: number): V2 {
    return this.parcels[i] === "carried" ? this.courier.pos : this.level.parcels[i];
  }
}
