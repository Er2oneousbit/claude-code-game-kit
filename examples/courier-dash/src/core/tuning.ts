// ---------------------------------------------------------------------------
// tuning.ts
// Purpose : Every number that defines how Courier Dash feels, in one place (GDD "Tunables").
// Usage   : import { TUNING } from "./tuning"; tests pass a modified copy to new Sim(...).
// Notes   : Units: meters, seconds, radians. Change a value, then run `python tools/dev.py test`:
//           the scenario tests tell you if the careful bot can still win and the careless one
//           still gets caught (pillar 2).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): robot search approach timeout, chase stuck check.
// ---------------------------------------------------------------------------

const DEG = Math.PI / 180;

export const TUNING = {
  /** Fixed simulation step: the same run plays out the same at any frame rate. */
  stepSeconds: 1 / 60,
  run: {
    seconds: 90, // clock per run, starts on the first move
    lowTimeSeconds: 10, // ticking starts here
  },
  courier: {
    radius: 0.35,
    walkSpeed: 3.6, // slower than a chasing robot
    sprintSpeed: 6.2, // faster than a chasing robot
    accel: 28, // m/s^2 toward the wanted velocity
    turnRate: 14, // rad/s, visual facing only
    staminaMax: 2.4, // seconds of sprint
    staminaRegen: 0.6, // seconds of sprint regained per second
    staminaToStart: 0.6, // an empty bar must refill this much before sprinting again
    pickupRadius: 1.0,
    deliverRadius: 1.8,
    pickupPause: 0.3, // frozen while bending down (the pick-up animation)
  },
  robot: {
    radius: 0.6,
    patrolSpeed: 2.3,
    chaseSpeed: 5.0,
    searchSpeed: 3.0,
    turnRate: 3.2, // rad/s: it must turn before it drives, which makes it readable
    sightRange: 7.5,
    sightHalfAngle: 42 * DEG,
    alertSeconds: 0.7, // the "!" pause before a chase: the player's chance to react
    loseSightSeconds: 0.5, // out of sight this long during a chase = search
    searchSeconds: 2.6, // looking around at the last seen spot
    searchApproachSeconds: 8, // driving to that spot longer than this = look around where it is
    stuckSeconds: 0.5, // chase progress check interval
    stuckDistance: 0.1, // moved less than this in stuckSeconds during a chase = stuck on something
    giveUpRange: 12, // a chase farther than this turns into a search
    catchMargin: 0.1, // caught when centers are closer than both radii plus this
    repathSeconds: 0.25,
    arriveDistance: 0.35,
  },
  nav: {
    cellSize: 0.5,
  },
};

export type Tuning = typeof TUNING;
