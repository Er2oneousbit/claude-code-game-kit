// ---------------------------------------------------------------------------
// coyoteTimer.ts
// Purpose : Example of ENGINE-FREE logic that is unit testable. Grants a short
//           grace window to still jump after leaving a ledge ("coyote time").
// Usage   : const t = new CoyoteTimer(0.1)
//           each update: t.update(dtSeconds, body.blocked.down)
//           on jump pressed: if (t.canJump()) { ...; t.consume() }
// Notes   : No Phaser import, so Vitest runs it instantly (see tests/).
//           A window of 0 means "no coyote time", not "no jumping": grounded
//           jumps always work. This file is a TEMPLATE example. Delete it if
//           the game has no jump.
//
// Pseudocode:
//   on floor   -> grounded, timeLeft = window; a landing re-arms a consumed jump
//   off floor  -> not grounded, timeLeft = max(0, timeLeft - dt)
//   canJump()  -> not consumed and (grounded or timeLeft > 0)
//   consume()  -> consumed until the next landing
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export class CoyoteTimer {
  readonly window: number;
  timeLeft = 0;
  private grounded = false;
  private consumed = false;

  constructor(windowSeconds = 0.1) {
    // Guard against negative windows from bad tuning data.
    this.window = Math.max(windowSeconds, 0);
  }

  update(dt: number, onFloor: boolean): void {
    if (onFloor) {
      if (!this.grounded) this.consumed = false; // landed: the next jump is available again
      this.grounded = true;
      this.timeLeft = this.window;
    } else {
      this.grounded = false;
      this.timeLeft = Math.max(this.timeLeft - dt, 0);
    }
  }

  canJump(): boolean {
    return !this.consumed && (this.grounded || this.timeLeft > 0);
  }

  consume(): void {
    this.consumed = true;
    this.timeLeft = 0;
  }
}

// {{FOOTER}}
