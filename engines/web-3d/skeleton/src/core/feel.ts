// ---------------------------------------------------------------------------
// feel.ts
// Purpose : The small helpers SOP-18's recipe table builds on (#170, #164): impact (a hit confirm scaled by
//           damage), floatText (a damage number's rise, pop and fade) and the tracer's point history by distance
//           (trailPush, trailShrink, trailLength). Same numbers in every engine (data/golden/juice.json "impact",
//           "float_text", "trail").
// Usage   : const hit = impact(damage, enemy.maxHp);  hitstop.hit(hit.hitstop); shake.addTrauma(hit.trauma);
//           if (hit.flash && flashLimiter.request(realNow)) flashScreen();
//           const f = floatText(label.age); label.y = label.y0 + f.dy; label.setScale(f.scale); label.alpha = f.alpha;
//           tracer.points = trailPush(tracer.points, bullet.x, bullet.y, spacing, length)   // every frame
//           after the hit: tracer.points = trailShrink(tracer.points, speed * dt)            // until < 2 points
// Notes   : No Phaser import (Vitest runs it). Pure functions: no settings, no clock, no random numbers. A game
//           passes its own tunables; the defaults below are SOP-18's starting points. Points are [x, y], tail first,
//           head last; every function returns a new array and leaves the input alone.
//
// Pseudocode:
//   impact: f = clamp(damage / full, 0, 1) (full <= 0: 1); none for damage <= 0; lerp hitstop and trauma; flash f >= at
//   floatText: u = t / life; dy = -rise * outCubic(u); scale = outBack(t / pop); alpha = 1 - inCubic(u)
//   trailPush: < 2 points: append; head spacing past the point before it: append; else move the head; cut to length
//   trailShrink: cut the trail to (length - amount) from the tail
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): impact is the same with blood on or off; what a
//           hit leaves is the game's: blood, or (blood_enabled off) a neutral spark or dust (SOP-18 step 4, #171)
// ---------------------------------------------------------------------------
import { ease } from "./ease";

// ---- Tunables (SOP-18 step 4 starting points) ------------------------------------
export const IMPACT_HITSTOP_MIN = 0.03; // s, the smallest hit
export const IMPACT_HITSTOP_MAX = 0.1; // s, a full hit (under Hitstop's 0.25 s cap)
export const IMPACT_TRAUMA_MIN = 0.15;
export const IMPACT_TRAUMA_MAX = 0.6;
export const IMPACT_FLASH_AT = 0.5; // a hit of at least half of `full` asks for a flash
export const FLOAT_LIFE = 0.8; // s
export const FLOAT_RISE = 24.0; // px
export const FLOAT_POP = 0.12; // s
export const TRAIL_SPACING = 6.0; // px between kept points
export const TRAIL_LENGTH = 48.0; // px, the longest trail
const EPS = 1e-12; // a cut this close to a point removes the point

export type Point = [number, number];
export interface Impact { hitstop: number; trauma: number; flash: boolean }
export interface FloatText { dy: number; scale: number; alpha: number; done: boolean }

export function impact(
  damage: number, full: number, hitstopMin = IMPACT_HITSTOP_MIN, hitstopMax = IMPACT_HITSTOP_MAX,
  traumaMin = IMPACT_TRAUMA_MIN, traumaMax = IMPACT_TRAUMA_MAX, flashAt = IMPACT_FLASH_AT,
): Impact {
  if (damage <= 0) return { hitstop: 0, trauma: 0, flash: false };
  const f = full <= 0 ? 1 : Math.min(Math.max(damage / full, 0), 1);
  return { hitstop: hitstopMin + (hitstopMax - hitstopMin) * f, trauma: traumaMin + (traumaMax - traumaMin) * f, flash: f >= flashAt };
}

export function floatText(t: number, life = FLOAT_LIFE, rise = FLOAT_RISE, popS = FLOAT_POP): FloatText {
  const u = life > 0 ? Math.min(Math.max(t / life, 0), 1) : 1;
  const scale = popS > 0 ? ease("out_back", t / popS) : 1;
  return { dy: -rise * ease("out_cubic", u), scale, alpha: 1 - ease("in_cubic", u), done: t >= life };
}

function seg(a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  return Math.sqrt(dx * dx + dy * dy);
}

/** Total length of the trail, tail to head (summed in order, as the reference does). */
export function trailLength(points: readonly Point[]): number {
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) total += seg(points[i], points[i + 1]);
  return total;
}

function trimTo(points: readonly Point[], keep: number): Point[] {
  const pts: Point[] = points.map((p) => [p[0], p[1]]);
  let excess = trailLength(pts) - Math.max(keep, 0);
  while (excess > EPS && pts.length > 1) {
    const s = seg(pts[0], pts[1]);
    if (s <= excess + EPS) {
      pts.shift();
      excess -= s;
    } else {
      const k = excess / s;
      pts[0] = [pts[0][0] + (pts[1][0] - pts[0][0]) * k, pts[0][1] + (pts[1][1] - pts[0][1]) * k];
      excess = 0;
    }
  }
  return pts;
}

export function trailPush(points: readonly Point[], x: number, y: number, spacing = TRAIL_SPACING, maxLen = TRAIL_LENGTH): Point[] {
  const pts: Point[] = points.map((p) => [p[0], p[1]]);
  if (pts.length < 2 || seg(pts[pts.length - 2], pts[pts.length - 1]) >= spacing) pts.push([x, y]);
  else pts[pts.length - 1] = [x, y];
  return trimTo(pts, maxLen);
}

export function trailShrink(points: readonly Point[], amount: number): Point[] {
  return trimTo(points, trailLength(points) - amount);
}

// {{FOOTER}}
