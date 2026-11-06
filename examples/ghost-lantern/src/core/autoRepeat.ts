// ---------------------------------------------------------------------------
// autoRepeat.ts
// Purpose : "Hold to mash" (access.auto_repeat, #166): a held button repeats its press, so a player who cannot tap
//           fast (one hand, a switch, tremor) can still mash.
// Usage   : const rep = new AutoRepeat();
//           if (settings.access.auto_repeat && rep.update(dt, input.isDown("attack"))) attack();
// Notes   : No Phaser import (Vitest runs it). The first repeat comes after DELAY_S, then one every INTERVAL_S
//           while held; releasing resets it. The times are the kit's starting point (a tip: tune them per game).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
export const AUTO_REPEAT_DELAY_S = 0.35; // held this long before the first repeat
export const AUTO_REPEAT_INTERVAL_S = 0.15; // then one repeat this often

export class AutoRepeat {
  private held = 0;
  private next = AUTO_REPEAT_DELAY_S;

  /** Call every frame with whether the button is held; true on a frame that repeats the press. */
  update(dt: number, isHeld: boolean): boolean {
    if (!isHeld) {
      this.held = 0;
      this.next = AUTO_REPEAT_DELAY_S;
      return false;
    }
    this.held += dt;
    if (this.held >= this.next) {
      this.next += AUTO_REPEAT_INTERVAL_S;
      return true;
    }
    return false;
  }
}
