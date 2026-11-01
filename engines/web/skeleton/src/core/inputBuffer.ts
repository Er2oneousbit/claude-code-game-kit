// ---------------------------------------------------------------------------
// inputBuffer.ts
// Purpose : Remembers a press for a short window, so a jump pressed just before landing still happens.
// Usage   : const buf = new InputBuffer(0.12)
//           on key down: buf.press("jump")
//           each frame:  buf.update(dt); if (grounded && buf.consume("jump")) jump()
// Notes   : No Phaser import (Vitest runs it). A press older than the window is forgotten. Checked against
//           data/golden/juice.json "input_buffer". Pairs with CoyoteTimer (late jumps) for forgiving controls.
//
// Pseudocode:
//   press(a)   -> pending[a] = window
//   update(dt) -> every pending entry ages by dt; at <= 0 (1e-12 for float dust) it is dropped
//   consume(a) -> true once if a is pending (and drops it), else false
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const INPUT_BUFFER_S = 0.12; // how long a press is remembered
const EPSILON = 1e-12;

export class InputBuffer {
  private readonly pending = new Map<string, number>();

  constructor(readonly window = INPUT_BUFFER_S) {}

  press(action: string): void {
    this.pending.set(action, this.window);
  }

  update(dt: number): void {
    for (const action of [...this.pending.keys()].sort()) {
      const left = (this.pending.get(action) ?? 0) - dt;
      if (left <= EPSILON) this.pending.delete(action);
      else this.pending.set(action, left);
    }
  }

  consume(action: string): boolean {
    if ((this.pending.get(action) ?? 0) > 0) {
      this.pending.delete(action);
      return true;
    }
    return false;
  }
}

// {{FOOTER}}
