// ---------------------------------------------------------------------------
// coyoteTimer.test.ts
// Purpose : Vitest unit tests for CoyoteTimer. Doubles as the example of how to
//           write engine-free tests in this project.
// Usage   : python tools/dev.py test
// Notes   : Test names describe behavior. No browser, no Phaser.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { CoyoteTimer } from "../src/core/coyoteTimer";

describe("CoyoteTimer", () => {
  it("allows a jump while grounded", () => {
    const t = new CoyoteTimer(0.1);
    t.update(0.016, true);
    expect(t.canJump()).toBe(true);
  });

  it("allows a jump shortly after leaving the floor", () => {
    const t = new CoyoteTimer(0.1);
    t.update(0.016, true);
    t.update(0.05, false);
    expect(t.canJump()).toBe(true);
  });

  it("closes the window after it expires", () => {
    const t = new CoyoteTimer(0.1);
    t.update(0.016, true);
    t.update(0.2, false);
    expect(t.canJump()).toBe(false);
  });

  it("does not reuse a consumed jump while still grounded", () => {
    const t = new CoyoteTimer(0.1);
    t.update(0.016, true);
    t.consume();
    t.update(0.016, true);
    expect(t.canJump()).toBe(false);
  });

  it("re-arms the jump on landing", () => {
    const t = new CoyoteTimer(0.1);
    t.update(0.016, true);
    t.consume();
    t.update(0.3, false);
    t.update(0.016, true);
    expect(t.canJump()).toBe(true);
  });

  it("treats a zero window as no grace, not no jumping", () => {
    const t = new CoyoteTimer(0);
    t.update(0.016, true);
    expect(t.canJump()).toBe(true);
    t.update(0.016, false);
    expect(t.canJump()).toBe(false);
  });
});

// {{FOOTER}}
