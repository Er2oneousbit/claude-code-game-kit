// ---------------------------------------------------------------------------
// displayStaging.ts
// Purpose : The Display tab's Apply (#308; SOP-19 section 2): Display changes wait for Apply, every other tab
//           applies at once, and a change that can black out the screen (mode, resolution) asks "Keep these
//           display settings?" for DISPLAY_CONFIRM_S seconds of real time, then puts back what that Apply replaced.
//           Checked against data/golden/shell.json "display_staging".
// Usage   : const st = new DisplayStaging(shell.settings.display)
//           st.stage("mode", "fullscreen")      // the control shows st.value("mode"); nothing is applied yet
//           const calls = st.apply()            // [[field, value], ...] in DISPLAY_APPLY_ORDER: set each one
//           const clock = new RealClock() ; each frame: calls = st.tick(clock.elapsed())  // [] or the revert
//           st.keep() ; st.revert() ; const [out, calls] = st.back()   // "revert" | "warn" | "leave"
// Notes   : No renderer import (Vitest runs it). Engine-free: it never touches the window, it returns the
//           (field, value) calls the shell makes. A port of tools/golden_vectors.py DisplayStaging: values are
//           compared by value (arrays element by element, numbers by value) and copied deep, so a staged
//           [1280, 720] equals the applied one. The countdown takes real seconds (RealClock), never the frame's
//           game time: game speed, a hitstop or a paused world must not stretch it.
//
// Pseudocode:
//   stage(f, v): confirm open -> "busy" ; v equals applied -> drop the pending f ; else pending f = v
//   apply(): changed = pending fields unlike applied ; remember what they replace ; set them in order ;
//            mode or resolution changed -> countdown = DISPLAY_CONFIRM_S
//   tick(dt): countdown -= dt ; at 0 -> revert()
//   back(): confirm open -> revert ; pending and not warned -> warn ; else discard pending -> leave
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): new, the Display tab's Apply and its confirm (#308)
// ---------------------------------------------------------------------------
import { deepCopy, hasKey, isObject } from "./jsonUtil";

// ---- Tunables ----------------------------------------------------------------
export const DISPLAY_APPLY_ORDER = ["mode", "resolution", "vsync", "frame_cap", "ui_scale"]; // mode before resolution
export const DISPLAY_CONFIRM_FIELDS = ["mode", "resolution"]; // can black out the screen: Apply asks "keep these?"
export const DISPLAY_CONFIRM_S = 15; // real seconds before an unanswered confirm reverts

export type DisplayCall = [string, unknown];
export type BackResult = ["revert" | "warn" | "leave", DisplayCall[]];

/** JSON values compared by value: numbers by value, arrays element by element, objects key by key. */
export function sameValue(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") return a === b;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameValue(v, b[i]));
  if (isObject(a) && isObject(b)) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => hasKey(b, k) && sameValue(a[k], b[k]));
  }
  return a === b;
}

export class DisplayStaging {
  applied: Record<string, unknown>;
  pending: Record<string, unknown> = {};
  /** field -> the value the last apply replaced */
  replaced: Record<string, unknown> = {};
  /** confirm countdown in seconds, null when closed */
  left: number | null = null;
  warned = false;

  constructor(applied: Record<string, unknown>) {
    this.applied = deepCopy(applied);
  }

  value(field: string): unknown {
    return hasKey(this.pending, field) ? this.pending[field] : this.applied[field];
  }

  /** Something waits for Apply. */
  get dirty(): boolean {
    return Object.keys(this.pending).length > 0;
  }

  stage(field: string, v: unknown): "busy" | "staged" {
    if (this.left !== null) return "busy";
    if (sameValue(v, this.applied[field])) delete this.pending[field];
    else this.pending[field] = deepCopy(v);
    this.warned = false;
    return "staged";
  }

  private set(values: Record<string, unknown>): DisplayCall[] {
    const calls: DisplayCall[] = [];
    for (const field of DISPLAY_APPLY_ORDER) {
      if (hasKey(values, field)) {
        this.applied[field] = deepCopy(values[field]);
        calls.push([field, deepCopy(values[field])]);
      }
    }
    return calls;
  }

  apply(): DisplayCall[] {
    const changed: Record<string, unknown> = {};
    for (const [f, v] of Object.entries(this.pending)) if (!sameValue(v, this.applied[f])) changed[f] = v;
    this.replaced = {};
    for (const f of Object.keys(changed)) this.replaced[f] = deepCopy(this.applied[f]);
    this.pending = {};
    this.warned = false;
    const calls = this.set(changed);
    if (DISPLAY_CONFIRM_FIELDS.some((f) => hasKey(changed, f))) this.left = DISPLAY_CONFIRM_S;
    return calls;
  }

  /** "Reverting in N s": the whole seconds left, rounded up; null when no confirm is open. */
  seconds(): number | null {
    return this.left === null ? null : Math.ceil(this.left);
  }

  tick(dt: number): DisplayCall[] {
    if (this.left === null) return [];
    this.left -= dt;
    return this.left <= 0 ? this.revert() : [];
  }

  keep(): void {
    this.left = null;
    this.replaced = {};
  }

  revert(): DisplayCall[] {
    const calls = this.set(this.replaced);
    this.left = null;
    this.replaced = {};
    return calls;
  }

  back(): BackResult {
    if (this.left !== null) return ["revert", this.revert()];
    if (this.dirty && !this.warned) {
      this.warned = true;
      return ["warn", []];
    }
    this.pending = {};
    this.warned = false;
    return ["leave", []];
  }
}

/** Real seconds between calls (performance.now by default): the confirm counts these, not game time. */
export class RealClock {
  private last: number;

  constructor(private readonly now: () => number = () => performance.now()) {
    this.last = now();
  }

  /** Starts counting from now. */
  reset(): void {
    this.last = this.now();
  }

  /** Seconds since the last call (or reset). */
  elapsed(): number {
    const t = this.now();
    const dt = Math.max(0, (t - this.last) / 1000);
    this.last = t;
    return dt;
  }
}
