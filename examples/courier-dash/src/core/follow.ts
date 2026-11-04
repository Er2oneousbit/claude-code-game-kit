// ---------------------------------------------------------------------------
// follow.ts
// Purpose : Example of ENGINE-FREE logic that is unit testable: a critically damped
//           spring that eases a value (a camera position, a health bar) toward a target
//           without overshoot, independent of frame rate. The classic "smooth damp".
// Usage   : const s = new Follow3(0.25)              // smooth time in seconds
//           each frame: const p = s.step(target, dt)  // {x, y, z}
// Notes   : No Three.js import, so Vitest runs it instantly (see tests/). Plain {x, y, z} in and
//           out; copy into a THREE.Vector3 at the call site. TEMPLATE example: delete it if unused.
//
// Pseudocode (per axis):
//   omega = 2 / smoothTime ; x = omega * dt ; decay = 1 / (1 + x + 0.48x^2 + 0.235x^3)
//   change = value - target ; temp = (velocity + omega * change) * dt
//   velocity = (velocity - omega * temp) * decay ; value = target + (change + temp) * decay
//   value reached or crossed target (incoming velocity) -> value = target, velocity = 0
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a step that would cross the target lands on it
//           (a fast incoming velocity overshot: smoothDamp(9, 10, 100, 0.2, 1/60) gave 10.42)
// ---------------------------------------------------------------------------

export type Vec3 = { x: number; y: number; z: number };

/** One axis of a critically damped spring. Returns [new value, new velocity]. */
export function smoothDamp(value: number, target: number, velocity: number, smoothTime: number, dt: number): [number, number] {
  const st = Math.max(smoothTime, 1e-4);
  const omega = 2 / st;
  const x = omega * dt;
  const decay = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const change = value - target;
  const temp = (velocity + omega * change) * dt;
  const next = target + (change + temp) * decay;
  // From rest the spring never passes the target, but incoming speed toward it can carry it across in one
  // step (9 -> 10.42 for a target of 10 at 100 units/s): land on the target and stop instead. Reaching it exactly
  // counts too, or the speed left over would carry the next step away from the target.
  if (change !== 0 && (next - target) * change <= 0) return [target, 0];
  return [next, (velocity - omega * temp) * decay];
}

export class Follow3 {
  value: Vec3;
  private velocity: Vec3 = { x: 0, y: 0, z: 0 };

  constructor(readonly smoothTime: number, start: Vec3 = { x: 0, y: 0, z: 0 }) {
    this.value = { ...start };
  }

  step(target: Vec3, dt: number): Vec3 {
    for (const axis of ["x", "y", "z"] as const) {
      [this.value[axis], this.velocity[axis]] = smoothDamp(this.value[axis], target[axis], this.velocity[axis], this.smoothTime, dt);
    }
    return { ...this.value };
  }

  /** Jump straight to a position (respawn, camera cut). */
  snap(to: Vec3): void {
    this.value = { ...to };
    this.velocity = { x: 0, y: 0, z: 0 };
  }
}
