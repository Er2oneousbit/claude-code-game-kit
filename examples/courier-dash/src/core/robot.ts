// ---------------------------------------------------------------------------
// robot.ts
// Purpose : The patrol robot: perception (a sight cone blocked by buildings), a finite state
//           machine (patrol, alert, chase, search, return) and tank-style movement.
// Usage   : const robot = new Robot(LEVEL.patrol, TUNING.robot, nav, boxes, bounds, startIndex)
//           each step: const events = robot.step(dt, courierPos, awake)   // "SPOTTED", "CHASE", ...
// Notes   : Engine-free (SOP-14: perception in, decision, movement out). An FSM because the robot
//           has a handful of clear modes; nothing here needs scores or plans (SOP-14 step 2).
//           Fairness rules, on purpose: it perceives nothing until the run starts (awake), it only
//           reacts to what is inside its cone, it always
//           pauses in "alert" before a chase (the "!" tell), and it must turn before it drives.
//
// Pseudocode:
//   sees = in range AND inside the cone AND no building on the line
//   patrol : drive the loop                    ; sees -> alert
//   alert  : stop, face the courier            ; after alertSeconds: sees -> chase, else -> search
//   chase  : drive straight at the courier     ; unseen loseSightSeconds or too far -> search
//            no progress for stuckSeconds -> A* toward it ; still no progress -> search
//   search : A* to the last seen spot (snapped to a cell it fits in), look around searchSeconds
//            (the approach gives up after searchApproachSeconds) ; sees -> alert ; done -> return
//   return : A* to the nearest patrol point    ; sees -> alert ; arrived -> patrol from there
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): search targets a reachable spot and its
//           approach times out; chase detects a robot pinned on a corner and paths around it.
// ---------------------------------------------------------------------------
import { type Box, type V2, dist, lineOfSight, moveCircle, normalize, sub, turnToward, wrapAngle, yawOf } from "./geom";
import type { NavGrid } from "./nav";
import type { Tuning } from "./tuning";

export type RobotState = "patrol" | "alert" | "chase" | "search" | "return";
export type RobotEvent = "SPOTTED" | "CHASE" | "LOST" | "GAVE_UP" | "PATROL";
type RobotTuning = Tuning["robot"];

export class Robot {
  pos: V2;
  yaw: number;
  state: RobotState = "patrol";
  /** Seconds spent in the current state. */
  stateTime = 0;
  sees = false;
  lastSeen: V2 | null = null;
  /** Where the search goes: lastSeen, moved to the nearest cell the robot fits in. */
  searchSpot: V2 | null = null;
  /** Current A* path (search, return, a chase detour), for movement and the debug view. */
  path: V2[] = [];
  private waypoint: number;
  private unseenTime = 0;
  private repathTime = 0;
  private searchArrived = false;
  /** Chase progress check: where the robot was stuckTime seconds ago. */
  private stuckAnchor: V2 = { x: 0, z: 0 };
  private stuckTime = 0;
  /** Chase follows A* instead of driving straight (set once it got stuck). */
  private detour = false;

  constructor(
    readonly patrol: readonly V2[],
    readonly t: RobotTuning,
    readonly nav: NavGrid,
    readonly boxes: readonly Box[],
    readonly bounds: Box,
    startIndex = 0,
  ) {
    const i = ((startIndex % patrol.length) + patrol.length) % patrol.length;
    this.pos = { ...patrol[i] };
    this.waypoint = (i + 1) % patrol.length;
    this.yaw = yawOf(sub(patrol[this.waypoint], this.pos));
  }

  /** Perception: in range, inside the cone, and nothing in the way. */
  canSee(target: V2): boolean {
    const to = sub(target, this.pos);
    const d = Math.hypot(to.x, to.z);
    if (d > this.t.sightRange) return false;
    if (d > 1e-6 && Math.abs(wrapAngle(yawOf(to) - this.yaw)) > this.t.sightHalfAngle) return false;
    return lineOfSight(this.pos, target, this.boxes);
  }

  step(dt: number, courier: V2, awake = true): RobotEvent[] {
    const events: RobotEvent[] = [];
    this.sees = awake && this.canSee(courier);
    if (this.sees) this.lastSeen = { ...courier };
    this.stateTime += dt;
    const go = (next: RobotState, ev?: RobotEvent) => {
      this.state = next;
      this.stateTime = 0;
      this.path = [];
      this.repathTime = 0;
      this.unseenTime = 0;
      this.searchArrived = false;
      this.stuckAnchor = { ...this.pos };
      this.stuckTime = 0;
      this.detour = false;
      // The courier fits where the robot does not (a gap behind a tree): search the nearest spot it can reach.
      if (next === "search") this.searchSpot = this.reachable(this.lastSeen ?? this.pos);
      if (ev) events.push(ev);
    };

    switch (this.state) {
      case "patrol": {
        if (this.sees) {
          go("alert", "SPOTTED");
          break;
        }
        const wp = this.patrol[this.waypoint];
        if (dist(this.pos, wp) < this.t.arriveDistance) this.waypoint = (this.waypoint + 1) % this.patrol.length;
        this.drive(this.patrol[this.waypoint], this.t.patrolSpeed, dt);
        break;
      }
      case "alert": {
        if (this.lastSeen) this.yaw = turnToward(this.yaw, yawOf(sub(this.lastSeen, this.pos)), this.t.turnRate * dt);
        if (this.stateTime >= this.t.alertSeconds) {
          if (this.sees) go("chase", "CHASE");
          else go("search", "LOST");
        }
        break;
      }
      case "chase": {
        this.unseenTime = this.sees ? 0 : this.unseenTime + dt;
        const tooFar = dist(this.pos, courier) > this.t.giveUpRange;
        if (this.unseenTime > this.t.loseSightSeconds || tooFar) {
          go("search", "LOST");
          break;
        }
        const goal = this.sees ? courier : this.lastSeen!;
        this.stuckTime += dt;
        if (this.stuckTime >= this.t.stuckSeconds) {
          const moved = dist(this.pos, this.stuckAnchor);
          this.stuckAnchor = { ...this.pos };
          this.stuckTime = 0;
          if (moved < this.t.stuckDistance) {
            // Pinned on a corner: try A* around it once; if that does not move it either, give up.
            if (this.detour) {
              go("search", "LOST");
              break;
            }
            this.detour = true;
            this.path = [];
          }
        }
        if (this.detour) this.followPath(goal, this.t.chaseSpeed, dt);
        else this.drive(goal, this.t.chaseSpeed, dt);
        break;
      }
      case "search": {
        if (this.sees) {
          go("alert", "SPOTTED");
          break;
        }
        if (!this.searchArrived) {
          const target = this.searchSpot ?? this.pos;
          const late = this.stateTime >= this.t.searchApproachSeconds; // blocked on the way: look around here
          if (late || dist(this.pos, target) < this.t.arriveDistance * 2 || this.followPath(target, this.t.searchSpeed, dt)) {
            this.searchArrived = true;
            this.stateTime = 0;
          }
        } else {
          this.yaw = wrapAngle(this.yaw + this.t.turnRate * 0.6 * dt); // look around
          if (this.stateTime >= this.t.searchSeconds) go("return", "GAVE_UP");
        }
        break;
      }
      case "return": {
        if (this.sees) {
          go("alert", "SPOTTED");
          break;
        }
        const nearest = this.nearestPatrolIndex();
        if (this.followPath(this.patrol[nearest], this.t.patrolSpeed, dt)) {
          this.waypoint = (nearest + 1) % this.patrol.length;
          go("patrol", "PATROL");
        }
        break;
      }
    }
    return events;
  }

  /** Index of the patrol point closest to the robot. */
  nearestPatrolIndex(): number {
    let best = 0;
    for (let i = 1; i < this.patrol.length; i++)
      if (dist(this.pos, this.patrol[i]) < dist(this.pos, this.patrol[best])) best = i;
    return best;
  }

  /** p itself if the robot fits there, else the center of the nearest cell it fits in. */
  private reachable(p: V2): V2 {
    if (this.nav.walkable(...this.nav.cellOf(p))) return { ...p };
    const cell = this.nav.nearestWalkable(p);
    return cell ? this.nav.center(...cell) : { ...p };
  }

  /** Follow an A* path to target (re-planned every repathSeconds). True once arrived. */
  private followPath(target: V2, speed: number, dt: number): boolean {
    if (dist(this.pos, target) < this.t.arriveDistance) return true;
    this.repathTime -= dt;
    if (this.repathTime <= 0 || this.path.length === 0) {
      this.path = this.nav.findPath(this.pos, target) ?? [target];
      this.repathTime = this.t.repathSeconds;
    }
    while (this.path.length > 1 && dist(this.pos, this.path[0]) < this.t.arriveDistance) this.path.shift();
    this.drive(this.path[0], speed, dt);
    return false;
  }

  /** Tank movement: turn toward the target, drive forward only as much as it faces it. */
  private drive(target: V2, speed: number, dt: number): void {
    const to = sub(target, this.pos);
    if (Math.hypot(to.x, to.z) < 1e-6) return;
    this.yaw = turnToward(this.yaw, yawOf(to), this.t.turnRate * dt);
    const facing = Math.cos(wrapAngle(yawOf(to) - this.yaw));
    if (facing <= 0) return;
    const fwd = normalize({ x: Math.sin(this.yaw), z: Math.cos(this.yaw) });
    const step = Math.min(speed * facing * dt, Math.hypot(to.x, to.z));
    this.pos = moveCircle(this.pos, { x: fwd.x * step, z: fwd.z * step }, this.t.radius, this.boxes, this.bounds);
  }
}
