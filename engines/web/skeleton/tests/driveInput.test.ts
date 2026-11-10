// ---------------------------------------------------------------------------
// driveInput.test.ts
// Purpose : #276: while a smoke drive runs (input.scripted), a real key, mouse event or gamepad (a stray key, a real
//           or virtual pad: navigator.getGamepads is live in headless Chromium) must not reach the shell, and the
//           menus' own click handlers get nothing either; the drive's injected presses still count; normal play
//           reads all of it.
// Usage   : python tools/dev.py test
// Notes   : No browser: the window is a plain EventTarget (Node has one) and the "real" events are plain Events
//           carrying a KeyboardEvent's code and repeat; the pads are plain objects passed to poll(), as in
//           shellInput.test.ts. A listener added after attach() stands in for a menu item's click handler.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { DEFAULT_BINDINGS, type Bindings } from "../src/core/bindings";
import { ShellInput } from "../src/shell/input";

/** A connected standard-mapping pad holding south (button 0) with the left stick hard right. */
function realPad(): Gamepad {
  const buttons = Array.from({ length: 17 }, (_, i) => ({ pressed: i === 0, touched: i === 0, value: i === 0 ? 1 : 0 }));
  return { id: "Xbox Wireless Controller (STANDARD GAMEPAD)", connected: true, axes: [0.9, 0, 0, 0], buttons } as unknown as Gamepad;
}

function keyEvent(type: string, code: string): Event {
  return Object.assign(new Event(type, { cancelable: true }), { code, repeat: false });
}

/** A shell input on a stand-in window, recording every press it sends on, every raw key and every menu click. */
function rig(scripted: boolean) {
  const bindings = structuredClone(DEFAULT_BINDINGS) as Bindings;
  const input = new ShellInput(() => bindings, () => 0.2, () => false);
  const win = new EventTarget();
  const pressed: string[] = [];
  const raw: string[] = [];
  let clicks = 0;
  input.onPress = (binding) => pressed.push(binding);
  input.onRawKey = (code) => raw.push(code);
  input.attach(win as unknown as Window);
  win.addEventListener("click", () => clicks++); // a menu item's handler, added after the shell's input
  input.scripted = scripted;
  // the real devices: D held (move_right), F8, a mouse move and click, a pad with south held and the stick right
  const real = () => {
    win.dispatchEvent(keyEvent("keydown", "KeyD"));
    win.dispatchEvent(keyEvent("keydown", "F8"));
    win.dispatchEvent(new Event("mousemove"));
    win.dispatchEvent(new Event("click"));
    input.poll([realPad()]);
  };
  return { input, pressed, raw, clicks: () => clicks, real };
}

describe("ShellInput during a drive (#276)", () => {
  it("reads the real keyboard, mouse and pads in normal play", () => {
    const r = rig(false);
    r.real();
    expect(r.pressed).toEqual(["key:d", "key:f8", "pad:south", "pad_axis:leftx+"]);
    expect(r.raw).toEqual(["KeyD", "F8"]);
    expect(r.clicks()).toBe(1);
    expect(r.input.lastDevice).toBe("pad_xbox");
    expect(r.input.isDown("move_right")).toBe(true);
    expect(r.input.isDown("ui_accept")).toBe(true);
    expect(r.input.stick().x).toBeGreaterThan(0.5);
  });

  it("ignores the real keyboard, mouse and pads while a drive runs", () => {
    const r = rig(true);
    r.input.lastDevice = "pad_other"; // where the drive left the prompts
    r.real();
    expect(r.pressed).toEqual([]);
    expect(r.raw).toEqual([]); // no F8 bug report from a stray key
    expect(r.clicks()).toBe(0); // the menus' click handlers never see it
    expect(r.input.lastDevice).toBe("pad_other");
    expect(r.input.isDown("move_right")).toBe(false);
    expect(r.input.isDown("ui_accept")).toBe(false);
    expect(r.input.stick()).toEqual({ x: 0, y: 0 });
    expect(r.input.triggers()).toEqual({ left: 0, right: 0 });
    expect(r.input.heldActions()).toEqual([]);
  });

  it("still takes the drive's own presses", () => {
    const r = rig(true);
    expect(r.input.inject("ui_down")).toBe(true);
    expect(r.input.injectPad("ui_accept")).toBe(true); // the access drive's gamepad-only run
    expect(r.pressed).toEqual(["key:down", "pad:south"]);
    expect(r.input.takePress("ui_down")).toBe(true);
    expect(r.input.lastDevice).toBe("pad_other");
  });
});

// {{FOOTER}}
