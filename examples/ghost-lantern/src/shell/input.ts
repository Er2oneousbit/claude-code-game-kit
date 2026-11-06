// ---------------------------------------------------------------------------
// input.ts
// Purpose : One input path for menus and gameplay: keyboard and gamepad events become bindings
//           ("key:space", "pad:south", "pad_axis:leftx-"), bindings become actions through the player's
//           settings.input.bindings. Also tracks the last device (for prompt glyphs) and captures the next
//           press for rebinding.
// Usage   : const input = new ShellInput(() => settings.input.bindings, () => settings.input.deadzone)
//           input.attach(window) ; each frame input.poll()
//           input.onPress = (binding, actions) => ...      // the shell routes presses to the top screen
//           scenes: input.isDown("move_left") ; input.takePress("jump")
//           rebinding: input.capture((binding) => ...)     // null when cancelled (Escape) or timed out
//           smoke driver: input.inject("ui_down")          // presses the action's first binding
// Notes   : Browser only (window, navigator.getGamepads), no Phaser: Phaser's own keyboard and gamepad
//           plugins are off in main.ts so nothing reads keys twice. Gamepads use the browser's "standard"
//           mapping (button 0 = south). keyName / padButtonName / padDevice are pure and unit tested.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { Bindings } from "../core/bindings";

// ---- Tunables ----------------------------------------------------------------
const CAPTURE_TIMEOUT_MS = 6000; // a rebind prompt gives up after this
const CAPTURE_CANCEL = "key:escape";
const PAD_BUTTONS = [
  "south", "east", "west", "north", "l1", "r1", "l2", "r2", "select", "start", "l3", "r3",
  "dpad_up", "dpad_down", "dpad_left", "dpad_right", "home",
];
const PAD_AXES = ["leftx", "lefty", "rightx", "righty"];
const PAD_TRIGGER = 0.5; // analog buttons (triggers) count as pressed above this
const MAX_QUEUED = 3; // gameplay presses remembered per action until a scene takes them

export type Device = "keyboard" | "mouse" | "pad_xbox" | "pad_playstation" | "pad_other";

const KEY_ALIASES: Record<string, string> = {
  Space: "space", Enter: "enter", NumpadEnter: "enter", Escape: "escape", Tab: "tab", Backspace: "backspace",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  ShiftLeft: "shift", ShiftRight: "shift", ControlLeft: "ctrl", ControlRight: "ctrl", AltLeft: "alt", AltRight: "alt",
  MetaLeft: "meta", MetaRight: "meta", Minus: "minus", Equal: "equal", Comma: "comma", Period: "period",
  Slash: "slash", Backslash: "backslash", Semicolon: "semicolon", Quote: "quote", BracketLeft: "bracket_left",
  BracketRight: "bracket_right", Backquote: "backquote", CapsLock: "capslock", Delete: "delete", Insert: "insert",
  Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown",
};

/** KeyboardEvent.code -> binding name: KeyA -> "a", Digit1 -> "1", ArrowUp -> "up", Numpad4 -> "kp_4". */
export function keyName(code: string): string {
  if (Object.prototype.hasOwnProperty.call(KEY_ALIASES, code)) return KEY_ALIASES[code];
  let m = /^Key([A-Z])$/.exec(code);
  if (m) return m[1].toLowerCase();
  m = /^Digit(\d)$/.exec(code);
  if (m) return m[1];
  m = /^Numpad(.+)$/.exec(code);
  if (m) return "kp_" + m[1].toLowerCase();
  return code.toLowerCase();
}

/** Standard-mapping button index -> binding name ("south" ...), or "b<index>" past the standard 17. */
export function padButtonName(index: number): string {
  return PAD_BUTTONS[index] ?? `b${index}`;
}

/** Which family a gamepad belongs to, from its id string (vendor ids: 045e Microsoft, 054c Sony). */
export function padDevice(id: string): Device {
  if (/xbox|xinput|045e/i.test(id)) return "pad_xbox";
  if (/playstation|dualshock|dualsense|054c|wireless controller/i.test(id)) return "pad_playstation";
  return "pad_other";
}

export class ShellInput {
  lastDevice: Device = "keyboard";
  /** Called once per new press with the binding and the actions it maps to (maybe none). */
  onPress: (binding: string, actions: string[]) => void = () => {};
  /** Called for raw key presses before mapping (the shell's F8 bug report key). */
  onRawKey: (code: string) => void = () => {};

  private readonly down = new Set<string>(); // bindings held now
  private readonly presses = new Map<string, number>(); // action -> presses not yet taken
  private padPrev = new Map<string, boolean>();
  private captureCb: ((binding: string | null) => void) | null = null;
  private captureTimer = 0;

  constructor(private readonly bindings: () => Bindings, private readonly deadzone: () => number) {}

  attach(target: Window): void {
    target.addEventListener("keydown", (e) => {
      if (e.repeat) return;
      this.lastDevice = "keyboard";
      this.onRawKey(e.code);
      const binding = "key:" + keyName(e.code);
      if (this.captureCb || this.actionsFor(binding).length) e.preventDefault(); // no page scroll on arrows/space
      this.press(binding);
    });
    target.addEventListener("keyup", (e) => this.release("key:" + keyName(e.code)));
    target.addEventListener("mousemove", () => (this.lastDevice = "mouse"));
    target.addEventListener("mousedown", () => (this.lastDevice = "mouse"));
    target.addEventListener("blur", () => this.down.clear()); // keys released while away never send keyup
  }

  /** Actions that a binding triggers, in binding-table order. */
  actionsFor(binding: string): string[] {
    const b = this.bindings();
    return Object.keys(b).filter((a) => b[a].includes(binding));
  }

  isDown(action: string): boolean {
    const list = this.bindings()[action] ?? [];
    return list.some((b) => b !== "" && this.down.has(b));
  }

  /** True once per press of action since the last take (for gameplay polling). */
  takePress(action: string): boolean {
    const n = this.presses.get(action) ?? 0;
    if (n <= 0) return false;
    this.presses.set(action, n - 1);
    return true;
  }

  /** Forget queued gameplay presses (on scene start, after a menu closes). */
  clearPresses(): void {
    this.presses.clear();
  }

  /** The next press of any key or button goes to cb instead of the game; Escape or a timeout cancel (null). */
  capture(cb: (binding: string | null) => void): void {
    this.captureCb = cb;
    clearTimeout(this.captureTimer);
    this.captureTimer = window.setTimeout(() => this.finishCapture(null), CAPTURE_TIMEOUT_MS);
  }

  get capturing(): boolean {
    return this.captureCb !== null;
  }

  /** Presses and releases the action's first binding, as if the player had (smoke driver). */
  inject(action: string): boolean {
    const binding = (this.bindings()[action] ?? []).find((b) => b !== "");
    if (!binding) return false;
    this.press(binding);
    this.release(binding);
    return true;
  }

  /** Presses and releases the action's gamepad binding, as a gamepad-only player would (the access drive, #85).
   * False when the action has none. */
  injectPad(action: string): boolean {
    const binding = (this.bindings()[action] ?? []).find((b) => b.startsWith("pad:") || b.startsWith("pad_axis:"));
    if (!binding) return false;
    this.lastDevice = padDevice("");
    this.press(binding);
    this.release(binding);
    return true;
  }

  /** Reads gamepads (call once per frame): new button and stick presses become bindings. */
  poll(): void {
    const pads = typeof navigator !== "undefined" && navigator.getGamepads ? navigator.getGamepads() : [];
    const now = new Map<string, boolean>();
    for (const pad of pads) {
      if (!pad || !pad.connected) continue;
      pad.buttons.forEach((btn, i) => {
        if (btn.pressed || btn.value > PAD_TRIGGER) now.set("pad:" + padButtonName(i), true);
      });
      const dz = this.deadzone();
      pad.axes.forEach((v, i) => {
        const axis = PAD_AXES[i];
        if (!axis) return;
        if (v < -dz) now.set(`pad_axis:${axis}-`, true);
        if (v > dz) now.set(`pad_axis:${axis}+`, true);
      });
      if ([...now.keys()].some((k) => !this.padPrev.get(k))) this.lastDevice = padDevice(pad.id);
    }
    for (const b of now.keys()) if (!this.padPrev.get(b)) this.press(b);
    for (const b of this.padPrev.keys()) if (!now.has(b)) this.release(b);
    this.padPrev = now;
  }

  private press(binding: string): void {
    if (this.captureCb) {
      this.finishCapture(binding === CAPTURE_CANCEL ? null : binding);
      return;
    }
    this.down.add(binding);
    const actions = this.actionsFor(binding);
    for (const a of actions) this.presses.set(a, Math.min((this.presses.get(a) ?? 0) + 1, MAX_QUEUED)); // nobody polls menus' actions
    this.onPress(binding, actions);
  }

  private release(binding: string): void {
    this.down.delete(binding);
  }

  private finishCapture(binding: string | null): void {
    const cb = this.captureCb;
    this.captureCb = null;
    clearTimeout(this.captureTimer);
    cb?.(binding);
  }
}
