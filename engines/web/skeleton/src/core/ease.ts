// ---------------------------------------------------------------------------
// ease.ts
// Purpose : The standard easing curves (Penner set, as on easings.net) by name, for tweens, UI pops and
//           camera moves. Same numbers in every engine of the kit (data/golden/juice.json "ease").
// Usage   : const k = ease("out_back", t)     // t in 0..1 (clamped), k mostly 0..1 (back/elastic overshoot)
//           EASE_NAMES lists every name.
// Notes   : No Phaser import (Vitest runs it). An unknown name throws, in every port, so a typo is loud.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

const C1 = 1.70158;
const C3 = C1 + 1.0;
const C4 = (2.0 * Math.PI) / 3.0;

function bounce(t: number): number {
  const n1 = 7.5625;
  const d1 = 2.75;
  if (t < 1.0 / d1) return n1 * t * t;
  if (t < 2.0 / d1) {
    t -= 1.5 / d1;
    return n1 * t * t + 0.75;
  }
  if (t < 2.5 / d1) {
    t -= 2.25 / d1;
    return n1 * t * t + 0.9375;
  }
  t -= 2.625 / d1;
  return n1 * t * t + 0.984375;
}

const EASES: Record<string, (t: number) => number> = {
  linear: (t) => t,
  in_quad: (t) => t * t,
  out_quad: (t) => 1.0 - (1.0 - t) * (1.0 - t),
  in_out_quad: (t) => (t < 0.5 ? 2.0 * t * t : 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0),
  in_cubic: (t) => t * t * t,
  out_cubic: (t) => 1.0 - (1.0 - t) ** 3,
  in_out_cubic: (t) => (t < 0.5 ? 4.0 * t * t * t : 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0),
  in_sine: (t) => 1.0 - Math.cos((t * Math.PI) / 2.0),
  out_sine: (t) => Math.sin((t * Math.PI) / 2.0),
  in_out_sine: (t) => -(Math.cos(Math.PI * t) - 1.0) / 2.0,
  in_back: (t) => C3 * t * t * t - C1 * t * t,
  out_back: (t) => 1.0 + C3 * (t - 1.0) ** 3 + C1 * (t - 1.0) ** 2,
  out_elastic: (t) => (t <= 0.0 ? 0.0 : t >= 1.0 ? 1.0 : 2.0 ** (-10.0 * t) * Math.sin((t * 10.0 - 0.75) * C4) + 1.0),
  out_bounce: bounce,
};

export const EASE_NAMES: readonly string[] = Object.keys(EASES).sort();

/** The eased value for t (clamped to 0..1). Throws on an unknown name. */
export function ease(name: string, t: number): number {
  const fn = Object.prototype.hasOwnProperty.call(EASES, name) ? EASES[name] : undefined;
  if (!fn) throw new Error(`unknown easing "${name}"`);
  return fn(Math.min(Math.max(t, 0.0), 1.0));
}

// {{FOOTER}}
