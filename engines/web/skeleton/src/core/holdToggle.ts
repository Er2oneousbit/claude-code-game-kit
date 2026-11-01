// ---------------------------------------------------------------------------
// holdToggle.ts
// Purpose : A held action (guard, aim, sprint) that also works as a toggle when the player turns on the
//           hold_to_toggle accessibility setting, so nobody has to keep a button pressed.
// Usage   : const guard = new HoldToggle()
//           each frame: const active = guard.update(input.isDown("interact"), settings.access.hold_to_toggle)
// Notes   : No Phaser import (Vitest runs it). Switching the setting mid-hold releases the action.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export class HoldToggle {
  active = false;
  private wasDown = false;
  private wasToggle = false;

  update(down: boolean, toggleMode: boolean): boolean {
    if (toggleMode !== this.wasToggle) this.active = false; // the setting changed: start released
    if (toggleMode) {
      if (down && !this.wasDown) this.active = !this.active; // each new press flips it
    } else {
      this.active = down;
    }
    this.wasDown = down;
    this.wasToggle = toggleMode;
    return this.active;
  }
}

// {{FOOTER}}
