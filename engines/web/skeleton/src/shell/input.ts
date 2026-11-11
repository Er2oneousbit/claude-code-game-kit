// ---------------------------------------------------------------------------
// input.ts
// Purpose : One input path for menus and gameplay: keyboard and gamepad events become bindings
//           ("key:space", "pad:south", "pad_axis:leftx-"), bindings become actions through the player's
//           settings.input.bindings. Also tracks the last device (for prompt glyphs), captures the next
//           press for rebinding, and gives the game the pad's analog values (#274).
// Usage   : const input = new ShellInput(() => settings.input.bindings, () => settings.input.deadzone,
//                                        () => settings.input.invert_y)
//           input.attach(window) ; each frame input.poll()
//           input.onPress = (binding, actions) => ...      // the shell routes presses to the top screen
//           scenes: input.isDown("move_left") ; input.takePress("jump")
//           analog: input.stick() -> {x, y} ; input.triggers() -> {left, right} ; input.heldActions()
//           rebinding: input.capture((binding) => ...)     // null when cancelled (Escape) or timed out
//           smoke driver: input.inject("ui_down")          // presses the action's first binding
//           (app sets input.scripted while a drive runs: then only inject / injectPad press anything)
// Notes   : Browser only (window, navigator.getGamepads), no renderer import: the renderer reads no keys or pads
//           itself (on web, Phaser's keyboard and gamepad plugins are off in main.ts), so nothing reads keys twice.
//           Gamepads use the browser's "standard" mapping (button 0 = south). keyName / padButtonName / padDevice are pure and unit tested.
//           Analog (the Bevy shell's Intent rules, src/core/analog.ts): stick() is the left stick with the
//           player's radial, rescaled deadzone and invert_y (up is -y); triggers() are 0 to 1; the stick leaning
//           past the deadzone also holds move_left/right/up/down (isDown, heldActions), whatever the bindings say.
//           With several pads the stick comes from the one leaning furthest and each trigger from the one pressed
//           furthest. The browser offers no trigger on a pad without the standard mapping (both read 0).
//           scripted (#276; app sets it while a smoke drive runs): no real device is read, only what the drive
//           injects. attach() puts a capture-phase guard on the window first, so every real key, mouse, pointer
//           and touch event stops there (the menus' click and hover handlers, the F8 key, the renderer's pointer too),
//           and poll() reads no pad (navigator.getGamepads is live in headless Chromium: a real or virtual pad on
//           the machine would otherwise reach the tour). inject() and injectPad() still land.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): real devices are not read while a drive runs (#276)
// ---------------------------------------------------------------------------
import { stick, stickActions, trigger, type Vec2 } from "../core/analog";
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
const PAD_TRIGGER_BUTTONS = { left: 6, right: 7 }; // standard mapping: l2, r2
const MAX_QUEUED = 3; // gameplay presses remembered per action until a scene takes them
// The real devices' DOM events: dropped at the window while a drive runs (#276). blur and focus are not input.
const REAL_EVENTS = [
  "keydown", "keyup", "keypress",
  "mousedown", "mouseup", "click", "dblclick", "auxclick", "contextmenu", "mousemove", "mouseover", "mouseenter", "wheel",
  "pointerdown", "pointerup", "pointermove", "pointerover", "pointerenter",
  "touchstart", "touchend", "touchmove",
];

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

function connectedPads(): ArrayLike<Gamepad | null> {
  return typeof navigator !== "undefined" && navigator.getGamepads ? navigator.getGamepads() : [];
}

export class ShellInput {
  lastDevice: Device = "keyboard";
  /** A drive runs: the real keyboard, mouse and pads are not read, only inject() / injectPad() (#276). */
  scripted = false;
  /** Called once per new press with the binding and the actions it maps to (maybe none). */
  onPress: (binding: string, actions: string[]) => void = () => {};
  /** Called for raw key presses before mapping (the shell's F8 bug report key). */
  onRawKey: (code: string) => void = () => {};

  private readonly down = new Set<string>(); // bindings held now
  private readonly presses = new Map<string, number>(); // action -> presses not yet taken
  private padPrev = new Map<string, boolean>();
  private captureCb: ((binding: string | null) => void) | null = null;
  private captureTimer = 0;
  private raw = { x: 0, y: 0, left: 0, right: 0 }; // the pads' analog values as the hardware reports them

  constructor(
    private readonly bindings: () => Bindings,
    private readonly deadzone: () => number,
    private readonly invertY: () => boolean = () => false,
  ) {}

  attach(target: Window): void {
    // First, and in the capture phase: while a drive runs, a real event stops here, before this class's own
    // listeners below and before any element's (the window sees every event first, hover and click included).
    const guard = (e: Event) => {
      if (this.scripted) e.stopImmediatePropagation();
    };
    for (const type of REAL_EVENTS) target.addEventListener(type, guard, { capture: true, passive: true });
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

  /** Held right now: a binding of the action is down, or (move_*) the left stick leans that way. */
  isDown(action: string): boolean {
    const list = this.bindings()[action] ?? [];
    return list.some((b) => b !== "" && this.down.has(b)) || this.stickHolds().includes(action);
  }

  /** The game actions (no ui_*) held right now: a drift button, a charge, "hold to sprint". */
  heldActions(): string[] {
    return Object.keys(this.bindings()).filter((a) => !a.startsWith("ui_") && this.isDown(a));
  }

  /** The left stick for gameplay: input.deadzone (radial, rescaled) and input.invert_y applied, up is -y. */
  stick(): Vec2 {
    return stick(this.raw.x, this.raw.y, this.deadzone(), this.invertY());
  }

  /** The analog triggers, 0 at rest to 1 fully in (TRIGGER_DEADZONE applied): gas and brake. */
  triggers(): { left: number; right: number } {
    return { left: trigger(this.raw.left), right: trigger(this.raw.right) };
  }

  private stickHolds(): string[] {
    return stickActions(this.raw.x, this.raw.y, this.deadzone(), this.invertY());
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

  /** Reads gamepads (call once per frame): new button and stick presses become bindings, and the analog values
   * are kept for stick() and triggers(). Tests pass their own pads. While scripted no pad is read (not even
   * passed ones): any pad binding still held is released and the stick and triggers rest. */
  poll(pads?: ArrayLike<Gamepad | null>): void {
    const now = new Map<string, boolean>();
    const raw = { x: 0, y: 0, left: 0, right: 0 };
    const list = this.scripted ? [] : Array.from(pads ?? connectedPads());
    for (const pad of list) {
      if (!pad || !pad.connected) continue;
      const [x = 0, y = 0] = pad.axes;
      if (Math.hypot(x, y) > Math.hypot(raw.x, raw.y)) Object.assign(raw, { x, y });
      raw.left = Math.max(raw.left, pad.buttons[PAD_TRIGGER_BUTTONS.left]?.value ?? 0);
      raw.right = Math.max(raw.right, pad.buttons[PAD_TRIGGER_BUTTONS.right]?.value ?? 0);
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
    this.raw = raw;
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

// {{FOOTER}}
