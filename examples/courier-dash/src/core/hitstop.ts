// ---------------------------------------------------------------------------
// hitstop.ts
// Purpose : Freezes game time for a moment on impact ("hitstop"), the cheapest way to make a hit feel heavy.
// Usage   : const stop = new Hitstop();      // cap from HITSTOP_MAX_S
//           on a hit:   stop.hit(0.06)
//           each frame: const gameDt = stop.scaledDt(realDt) * settings.access.game_speed
//           realDt is wall-clock time (hitstop runs before game_speed); feed gameDt to the world
// Notes   : No Phaser import (Vitest runs it). Overlapping hits keep the longest freeze, capped at maxS,
//           so a flurry of hits cannot lock the game. Checked against data/golden/juice.json "hitstop".
//
// Pseudocode:
//   hit(d)        -> remaining = min(max(remaining, d), maxS)
//   scaledDt(dt)  -> if remaining <= 0: dt ; else used = min(remaining, dt), remaining -= used, return dt - used
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const HITSTOP_MAX_S = 0.25; // longest freeze one hit (or a flurry) can cause

export class Hitstop {
  remaining = 0;

  constructor(readonly maxS = HITSTOP_MAX_S) {}

  hit(duration: number): void {
    this.remaining = Math.min(Math.max(this.remaining, duration), this.maxS);
  }

  /** The game's delta for this frame: the frozen part of realDt is removed. */
  scaledDt(realDt: number): number {
    if (this.remaining <= 0) return realDt;
    const used = Math.min(this.remaining, realDt);
    this.remaining -= used;
    return realDt - used;
  }
}
