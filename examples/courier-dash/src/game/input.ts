// ---------------------------------------------------------------------------
// input.ts
// Purpose : Keyboard and gamepad into the simulation's Input (world axes: -z is up the screen).
// Usage   : const input = new Controls(window); each step: sim.step(input.read())
//           input.consumeRestart() is true once after R or the gamepad Start button.
//           input.clear() on every new run: forgets held keys and a queued restart.
// Notes   : The camera never rotates, so screen directions map straight to world axes.
//           Gamepad: left stick or D-pad to move, A or right trigger to sprint, Start to restart
//           (standard mapping). Diagonals are normalized in the simulation.
//           After clear(), a key or stick still held from the last run is ignored until it is
//           released (key repeat would otherwise re-add it), so a new run starts on a fresh press.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix (Claude Opus 5.5): clear() so held input does not leak into a restart.
// ---------------------------------------------------------------------------
import type { Input } from "../core/sim";

const STICK_DEADZONE = 0.2;
const KEYS = {
  up: ["KeyW", "ArrowUp"],
  down: ["KeyS", "ArrowDown"],
  left: ["KeyA", "ArrowLeft"],
  right: ["KeyD", "ArrowRight"],
  sprint: ["ShiftLeft", "ShiftRight"],
  restart: ["KeyR"],
};
const PAD = { sprint: [0, 7], restart: 9, up: 12, down: 13, left: 14, right: 15 };

export class Controls {
  private held = new Set<string>();
  /** Keys held through a clear(): their repeat keydowns are ignored until keyup. */
  private stale = new Set<string>();
  private restartQueued = false;
  private padRestartHeld = false;
  /** After clear(), pad movement is ignored until the stick and D-pad are back at rest. */
  private padStale = false;

  constructor(target: Window) {
    target.addEventListener("keydown", (e) => {
      if (e.code.startsWith("Arrow")) e.preventDefault(); // no page scroll
      if (e.repeat && this.stale.has(e.code)) return;
      if (KEYS.restart.includes(e.code) && !e.repeat) this.restartQueued = true;
      this.held.add(e.code);
    });
    target.addEventListener("keyup", (e) => {
      this.held.delete(e.code);
      this.stale.delete(e.code);
    });
    target.addEventListener("blur", () => this.held.clear());
  }

  /** New run: drop held keys and any queued restart, so only a fresh press moves the courier. */
  clear(): void {
    for (const k of this.held) this.stale.add(k);
    this.held.clear();
    this.restartQueued = false;
    this.padStale = true;
  }

  private key(names: string[]): boolean {
    return names.some((k) => this.held.has(k));
  }

  read(): Input {
    let x = (this.key(KEYS.right) ? 1 : 0) - (this.key(KEYS.left) ? 1 : 0);
    let z = (this.key(KEYS.down) ? 1 : 0) - (this.key(KEYS.up) ? 1 : 0);
    let sprint = this.key(KEYS.sprint);
    const pad = navigator.getGamepads?.().find((p) => p && p.connected);
    if (pad) {
      const [ax, az] = [pad.axes[0] ?? 0, pad.axes[1] ?? 0];
      const b = (i: number) => pad.buttons[i]?.pressed ?? false;
      const stick = Math.hypot(ax, az) > STICK_DEADZONE;
      const dpad = b(PAD.left) || b(PAD.right) || b(PAD.up) || b(PAD.down);
      if (!stick && !dpad) this.padStale = false;
      if (!this.padStale) {
        if (stick) [x, z] = [ax, az];
        if (dpad) {
          x = (b(PAD.right) ? 1 : 0) - (b(PAD.left) ? 1 : 0);
          z = (b(PAD.down) ? 1 : 0) - (b(PAD.up) ? 1 : 0);
        }
      }
      sprint ||= PAD.sprint.some(b);
      if (b(PAD.restart) && !this.padRestartHeld) this.restartQueued = true;
      this.padRestartHeld = b(PAD.restart);
    }
    return { x, z, sprint };
  }

  consumeRestart(): boolean {
    const r = this.restartQueued;
    this.restartQueued = false;
    return r;
  }
}
