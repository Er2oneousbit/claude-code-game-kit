// ---------------------------------------------------------------------------
// spring.ts
// Purpose : A damped spring for squash and stretch recovery, UI pops and wobble, plus the volume-keeping
//           squash scale. Same numbers in every engine (data/golden/juice.json "spring" and "squash").
// Usage   : const s = new Spring(4, 0.5)        // frequency (Hz), damping ratio (1 = no overshoot)
//           on landing: s.x = 0.4              // kick it
//           each frame: const [sx, sy] = squash(s.update(dt)); sprite.setScale(sx, sy)
// Notes   : No Phaser import (Vitest runs it). Semi-implicit Euler: stable at game frame rates; very
//           large dt (a stalled tab) should be clamped by the caller, as the scenes already do.
//
// Pseudocode:
//   w = 2*pi*frequency ; a = -w^2 (x - target) - 2*damping*w*v ; v += a*dt ; x += v*dt
//   squash(a) = (1 + a, 1 / (1 + a)) with a clamped above -0.9
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const SPRING_FREQUENCY = 4.0; // Hz
export const SPRING_DAMPING = 0.5; // 0 = wobbles forever, 1 = critically damped
const SQUASH_MIN = -0.9; // a stronger stretch than this would flip the sprite

export class Spring {
  x = 0;
  v = 0;
  target = 0;

  constructor(readonly frequency = SPRING_FREQUENCY, readonly damping = SPRING_DAMPING) {}

  update(dt: number): number {
    const w = 2.0 * Math.PI * this.frequency;
    const a = -w * w * (this.x - this.target) - 2.0 * this.damping * w * this.v;
    this.v += a * dt;
    this.x += this.v * dt;
    return this.x;
  }
}

/** Volume-keeping scale [sx, sy]: amount > 0 widens and flattens, < 0 stretches. */
export function squash(amount: number): [number, number] {
  const a = Math.max(amount, SQUASH_MIN);
  return [1.0 + a, 1.0 / (1.0 + a)];
}
