// ---------------------------------------------------------------------------
// flashLimiter.ts
// Purpose : Photosensitivity guard: at most N full-screen flashes in any window (default three per second).
//           Checked against data/golden/juice.json "flash_limiter".
// Usage   : const fl = new FlashLimiter()
//           before a flash: if (fl.request(realSeconds)) flash(settings.access.flash_limit ? GENTLE : FULL)
// Notes   : No Phaser import (Vitest runs it). ALWAYS enforced: no setting turns it off. access.flash_limit
//           (default on) only tones each flash down further (about 30 % opacity or a brief tint). now is REAL
//           wall-clock time, before hitstop and game_speed, so slow motion cannot sneak extra flashes in.
//           A refused flash is simply skipped.
//
// Pseudocode:
//   request(now) -> forget flashes at or before now - window ; allow and remember if fewer than max remain
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const FLASH_MAX = 3;
export const FLASH_WINDOW_S = 1.0;

export class FlashLimiter {
  private times: number[] = [];

  constructor(readonly maxFlashes = FLASH_MAX, readonly windowS = FLASH_WINDOW_S) {}

  request(now: number): boolean {
    this.times = this.times.filter((t) => t > now - this.windowS);
    if (this.times.length < this.maxFlashes) {
      this.times.push(now);
      return true;
    }
    return false;
  }
}
