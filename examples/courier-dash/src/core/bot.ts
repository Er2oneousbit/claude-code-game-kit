// ---------------------------------------------------------------------------
// bot.ts
// Purpose : Autoplay drivers for scenario checks (SOP-14 step 6). "careful" reads the robot like
//           a player should (waits when it would be seen, sprints past, runs when spotted);
//           "reckless" walks the shortest path and ignores the robot.
// Usage   : const bot = new Bot("careful"); each step: sim.step(bot.think(sim))
// Notes   : Engine-free, so the scenario pair also runs in Vitest (tests/scenario.test.ts).
//           The pair tests pillar 2: if the reckless bot also wins, the robot does not matter.
//           The bot may read the robot's state directly; a player reads it from the light and "!".
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { type V2, dist, inBox, inflate, lineOfSight, normalize, sub, wrapAngle, yawOf } from "./geom";
import type { Input, Sim } from "./sim";

export type BotMode = "careful" | "reckless";

const REPATH_SECONDS = 0.3;
const ARRIVE = 0.3; // m, next path point reached
const LOOK_AHEAD = 1.6; // m, where the careful bot checks before stepping
const WARY_RANGE = 1.5; // m added to the robot's sight range when judging danger
const WARY_ANGLE = 0.3; // rad added to the robot's half angle
const BUMP_RANGE = 3.0; // m, never walk this close to the robot
const SPRINT_NEAR = 9; // m, sprint when the robot is closer than this
const HIDE_SAMPLES = 24; // directions tried when looking for cover
const HIDE_RADIUS = 3; // m, how far ahead each try looks
const HIDDEN_BONUS = 20; // score for a spot the robot cannot see

export class Bot {
  path: V2[] = [];
  private target: V2 | null = null;
  private repath = 0;

  constructor(readonly mode: BotMode) {}

  think(sim: Sim): Input {
    if (sim.outcome !== "playing") return { x: 0, z: 0, sprint: false };
    const pos = sim.courier.pos;
    const target = this.pickTarget(sim);
    this.repath -= sim.t.stepSeconds;
    if (target !== this.target || this.repath <= 0 || this.path.length === 0) {
      this.target = target;
      this.path = sim.courierNav.findPath(pos, target) ?? [target];
      this.repath = REPATH_SECONDS;
    }
    while (this.path.length > 1 && dist(pos, this.path[0]) < ARRIVE) this.path.shift();
    const dir = normalize(sub(this.path[0], pos));
    if (this.mode === "reckless") return { x: dir.x, z: dir.z, sprint: false };
    return this.careful(sim, pos, dir);
  }

  /** Carrying: the depot. Otherwise the nearest waiting parcel. */
  private pickTarget(sim: Sim): V2 {
    if (sim.carrying !== null) return sim.level.depot;
    let best: V2 | null = null;
    sim.parcels.forEach((s, i) => {
      const p = sim.level.parcels[i];
      if (s === "waiting" && (!best || dist(p, sim.courier.pos) < dist(best, sim.courier.pos))) best = p;
    });
    return best ?? sim.level.depot;
  }

  private careful(sim: Sim, pos: V2, dir: V2): Input {
    const r = sim.robot;
    const near = dist(r.pos, pos) < SPRINT_NEAR;
    // Spotted (or about to be): run for the best hiding spot nearby.
    if (r.state === "alert" || r.state === "chase" || r.canSee(pos)) return { ...this.hideDir(sim, pos), sprint: true };
    // Inside the cone but not seen yet: step sideways out of it.
    if (this.wary(sim, pos)) return { ...this.sidestep(sim, pos), sprint: near };
    // Clear here, but the next step would be seen or bump it: wait for the gap.
    const ahead = { x: pos.x + dir.x * LOOK_AHEAD, z: pos.z + dir.z * LOOK_AHEAD };
    if (this.wary(sim, ahead) || dist(r.pos, ahead) < BUMP_RANGE) return { x: 0, z: 0, sprint: false };
    return { x: dir.x, z: dir.z, sprint: near };
  }

  /** Direction to the reachable point nearby that is hidden from the robot and far from it. */
  private hideDir(sim: Sim, pos: V2): V2 {
    const r = sim.robot;
    let best = normalize(sub(pos, r.pos));
    let bestScore = -Infinity;
    for (let i = 0; i < HIDE_SAMPLES; i++) {
      const a = (i / HIDE_SAMPLES) * Math.PI * 2;
      const d = { x: Math.sin(a), z: Math.cos(a) };
      const p = { x: pos.x + d.x * HIDE_RADIUS, z: pos.z + d.z * HIDE_RADIUS };
      if (!lineOfSight(pos, p, sim.courierNav.grown) || !inBox(p, inflate(sim.level.bounds, -1))) continue;
      const score = (lineOfSight(r.pos, p, sim.boxes) ? 0 : HIDDEN_BONUS) + dist(r.pos, p);
      if (score > bestScore) [best, bestScore] = [d, score];
    }
    return best;
  }

  /** Leave the robot's cone sideways: perpendicular to its facing, away from its center line. */
  private sidestep(sim: Sim, pos: V2): V2 {
    const r = sim.robot;
    const fwd = { x: Math.sin(r.yaw), z: Math.cos(r.yaw) };
    const side = { x: fwd.z, z: -fwd.x };
    const away = normalize(sub(pos, r.pos));
    const s = away.x * side.x + away.z * side.z >= 0 ? 1 : -1;
    const want = normalize({ x: side.x * s + away.x * 0.5, z: side.z * s + away.z * 0.5 });
    const p = { x: pos.x + want.x, z: pos.z + want.z };
    return lineOfSight(pos, p, sim.courierNav.grown) ? want : this.hideDir(sim, pos);
  }

  /** Could the robot see p soon? Its own sight check with a safety margin. */
  private wary(sim: Sim, p: V2): boolean {
    const r = sim.robot;
    const to = sub(p, r.pos);
    if (Math.hypot(to.x, to.z) > sim.t.robot.sightRange + WARY_RANGE) return false;
    if (Math.abs(wrapAngle(yawOf(to) - r.yaw)) > sim.t.robot.sightHalfAngle + WARY_ANGLE) return false;
    return lineOfSight(r.pos, p, sim.boxes);
  }
}
