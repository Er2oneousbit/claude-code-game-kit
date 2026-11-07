// ---------------------------------------------------------------------------
// bindings.ts
// Purpose : Input bindings as data: the default action map, rebinding with a swap inside the action's
//           group, which prompt-glyph set to show, and the glyph art name for a binding.
//           Checked against data/golden/shell.json "rebind", "glyph_set", "glyph_name", "prompt_binding".
// Usage   : const { bindings, conflicts } = rebind(settings.input.bindings, "jump", 0, "key:k")
//           const set = glyphSet(settings.input.glyphs, input.lastDevice)       // "keyboard" | "xbox" | ...
//           const art = glyphName(set, promptBinding(bindings, "jump", set))     // "key_space", "xbox_a"
// Notes   : No Phaser import (Vitest runs it). A binding is "kind:name": key:space, mouse:left, pad:south,
//           pad_axis:leftx-. Slot 0 is the keyboard binding, slot 1 the gamepad binding, more slots are extras.
//           Actions named ui_* form the "ui" group, everything else the "game" group: a key may mean one thing
//           in menus and another in play, but never two things inside one group.
//
// Pseudocode (rebind):
//   old = action's slot ; every other (action, slot) of the same group holding the new binding is a conflict
//   put the binding in the slot ; each conflict gets old (a swap), or "" (unbound) when the slot was empty
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { deepCopy } from "./jsonUtil";

export type Bindings = Record<string, string[]>;
export type Conflict = [action: string, slot: number];

// ---- Tunables ----------------------------------------------------------------
export const DEFAULT_BINDINGS: Readonly<Bindings> = {
  ui_up: ["key:up", "pad:dpad_up"],
  ui_down: ["key:down", "pad:dpad_down"],
  ui_left: ["key:left", "pad:dpad_left"],
  ui_right: ["key:right", "pad:dpad_right"],
  ui_accept: ["key:enter", "pad:south"],
  ui_cancel: ["key:escape", "pad:east"],
  move_left: ["key:a", "pad:dpad_left"],
  move_right: ["key:d", "pad:dpad_right"],
  move_up: ["key:w", "pad:dpad_up"],
  move_down: ["key:s", "pad:dpad_down"],
  jump: ["key:space", "pad:south"],
  attack: ["key:j", "pad:west"],
  interact: ["key:e", "pad:north"],
  pause: ["key:escape", "pad:start"],
};

export const GLYPH_SETS = ["auto", "keyboard", "xbox", "playstation", "generic"] as const;

const XBOX: Record<string, string> = {
  south: "a", east: "b", west: "x", north: "y", l1: "lb", r1: "rb", l2: "lt", r2: "rt", start: "menu", select: "view",
};
const PLAYSTATION: Record<string, string> = {
  south: "cross", east: "circle", west: "square", north: "triangle", start: "options", select: "share",
};
const AUTO_DEVICE: Record<string, string> = {
  keyboard: "keyboard", mouse: "keyboard", pad_xbox: "xbox", pad_playstation: "playstation",
};

const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);

export function groupOf(action: string): "ui" | "game" {
  return action.startsWith("ui_") ? "ui" : "game";
}

/** A fresh copy of the default bindings. */
export function defaultBindings(): Bindings {
  return deepCopy(DEFAULT_BINDINGS) as Bindings;
}

/** Puts binding in action's slot and swaps it out of any same-group action that had it. Pure: returns a copy. */
export function rebind(bindings: Bindings, action: string, slot: number, binding: string): { bindings: Bindings; conflicts: Conflict[] } {
  const b = deepCopy(bindings);
  if (!own(b, action)) b[action] = [];
  const lst = b[action];
  if (slot > lst.length) throw new Error("slot past the end");
  const old = slot < lst.length ? lst[slot] : "";
  const conflicts: Conflict[] = [];
  for (const other of Object.keys(b).sort()) {
    if (groupOf(other) !== groupOf(action)) continue;
    b[other].forEach((name, s) => {
      if (!(other === action && s === slot) && name === binding && binding !== "") conflicts.push([other, s]);
    });
  }
  if (slot === lst.length) lst.push(binding);
  else lst[slot] = binding;
  for (const [other, s] of conflicts) b[other][s] = old;
  return { bindings: b, conflicts };
}

/** Which prompt art to show: the player's choice, or (auto) the last device used. */
export function glyphSet(setting: string, lastDevice: string): string {
  if (setting !== "auto") return setting;
  return own(AUTO_DEVICE, lastDevice) ? AUTO_DEVICE[lastDevice] : "generic";
}

/** The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick ... */
export function glyphName(gset: string, binding: string): string {
  const colon = binding.indexOf(":");
  const kind = colon >= 0 ? binding.slice(0, colon) : binding;
  let name = colon >= 0 ? binding.slice(colon + 1) : "";
  if (kind === "key") return "key_" + name;
  if (kind === "mouse") return "mouse_" + name;
  if (kind === "pad_axis") name = name.startsWith("left") ? "lstick" : "rstick";
  else if (kind !== "pad") return "unknown";
  if (gset === "xbox") return "xbox_" + (own(XBOX, name) ? XBOX[name] : name);
  if (gset === "playstation") return "ps_" + (own(PLAYSTATION, name) ? PLAYSTATION[name] : name);
  return "pad_" + name;
}

/** The binding to show for an action: slot 0 (keyboard) for the keyboard set, slot 1 (pad) otherwise. */
export function promptBinding(bindings: Bindings, action: string, gset: string): string {
  const lst = own(bindings, action) ? bindings[action] : [];
  const slot = gset === "keyboard" ? 0 : 1;
  return slot < lst.length ? lst[slot] : "";
}

/** Actions (same group) that share a non-empty binding with another action: [action, slot] pairs, sorted. */
export function findConflicts(bindings: Bindings): Conflict[] {
  const seen = new Map<string, Conflict[]>();
  for (const action of Object.keys(bindings).sort()) {
    bindings[action].forEach((name, slot) => {
      if (name === "") return;
      const key = groupOf(action) + "|" + name;
      seen.set(key, [...(seen.get(key) ?? []), [action, slot]]);
    });
  }
  return [...seen.values()].filter((list) => list.length > 1).flat();
}

const oneLine = (text: string) => String(text ?? "").split(/\s+/).filter(Boolean).join(" ");

/** What the narration says for one control (#165): "Music volume, slider, 70 percent"; no label says "unlabelled". */
export function narrationLine(label: string, role: string, value = ""): string {
  const parts = [oneLine(label) || "unlabelled"];
  if (oneLine(role)) parts.push(oneLine(role));
  if (oneLine(value)) parts.push(oneLine(value));
  return parts.join(", ");
}

// {{FOOTER}}
