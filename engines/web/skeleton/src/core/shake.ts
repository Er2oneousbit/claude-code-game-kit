// ---------------------------------------------------------------------------
// shake.ts
// Purpose : Trauma-based screen shake, driven by smooth 1D value noise that gives the same numbers in
//           every engine of the kit (data/golden/juice.json "noise" and "shake" cases).
// Usage   : const shake = new Shake();               // tunables below, or new Shake({ maxOffset: 12 })
//           on a hit:   shake.addTrauma(0.5)
//           each frame: const { x, y, angle } = shake.update(gameDt, effectiveShake(settings))   // game time
//                       camera offset = (x, y) pixels, camera rotation = angle radians
// Notes   : No Phaser import, so Vitest runs it. The shake is trauma squared, so small hits stay small.
//           intensity is the player's setting: 0 with reduce motion, otherwise access.shake_scale.
//           Noise uses Park-Miller arithmetic that stays exact in doubles, so JS, Lua and C# agree.
//
// Pseudocode:
//   lattice(seed, i, ch) = Park-Miller twice on a mixed integer, scaled to (-1, 1]
//   noise(seed, t, ch)   = lattice at floor(t) and floor(t)+1, blended with smoothstep
//   update: time += dt ; trauma -= decay*dt (>= 0) ; s = trauma^2 * intensity
//           x, y, angle = max * s * noise(seed, time*frequency, channel 0 / 1 / 2)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const SHAKE_DEFAULTS = {
  maxOffset: 8.0, // pixels at full trauma
  maxAngle: 0.05, // radians at full trauma
  decay: 1.5, // trauma lost per second
  frequency: 15.0, // noise samples per second (higher = jitterier)
  seed: 1,
};

const PM_M = 2147483647; // Park-Miller modulus (2^31 - 1)
const PM_A = 16807;

/** Python-style modulo (the result has the sign of m), so negative inputs match the reference. */
function mod(x: number, m: number): number {
  return ((x % m) + m) % m;
}

/** A value in (-1, 1] for integer lattice point i of channel ch. Products stay below 2^53, so doubles are exact. */
export function lattice(seed: number, i: number, ch: number): number {
  let s = mod(seed * 7919 + i * 104729 + ch * 15485863, PM_M);
  if (s === 0) s = 1;
  s = (s * PM_A) % PM_M;
  s = (s * PM_A) % PM_M;
  return (s / (PM_M - 1)) * 2.0 - 1.0;
}

/** Smooth 1D value noise: lattice values blended with smoothstep. t >= 0. */
export function noise(seed: number, t: number, ch: number): number {
  const i = Math.floor(t);
  const f = t - i;
  const a = lattice(seed, i, ch);
  const b = lattice(seed, i + 1, ch);
  const u = f * f * (3.0 - 2.0 * f);
  return a + (b - a) * u;
}

export type ShakeParams = typeof SHAKE_DEFAULTS;
export type ShakeOffset = { x: number; y: number; angle: number };

export class Shake {
  readonly maxOffset: number;
  readonly maxAngle: number;
  readonly decay: number;
  readonly frequency: number;
  readonly seed: number;
  trauma = 0;
  time = 0;

  constructor(params: Partial<ShakeParams> = {}) {
    const p = { ...SHAKE_DEFAULTS, ...params };
    this.maxOffset = p.maxOffset;
    this.maxAngle = p.maxAngle;
    this.decay = p.decay;
    this.frequency = p.frequency;
    this.seed = p.seed;
  }

  /** Adds trauma (0..1 after clamping). A negative amount calms the shake. */
  addTrauma(amount: number): void {
    this.trauma = Math.min(Math.max(this.trauma + amount, 0), 1);
  }

  /** Advances time and returns this frame's offset. intensity is the player's shake setting. */
  update(dt: number, intensity = 1.0): ShakeOffset {
    this.time += dt;
    this.trauma = Math.max(this.trauma - this.decay * dt, 0);
    const s = this.trauma * this.trauma * intensity;
    const t = this.time * this.frequency;
    return {
      x: this.maxOffset * s * noise(this.seed, t, 0),
      y: this.maxOffset * s * noise(this.seed, t, 1),
      angle: this.maxAngle * s * noise(this.seed, t, 2),
    };
  }
}

// {{FOOTER}}
