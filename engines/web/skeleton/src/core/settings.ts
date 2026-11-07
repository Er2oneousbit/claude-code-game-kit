// ---------------------------------------------------------------------------
// settings.ts
// Purpose : The player's settings: built-in defaults, the schema every field is checked against, and a
//           loader that repairs a damaged or old settings.json instead of crashing or resetting it.
//           Checked against data/golden/shell.json "defaults" and "settings_load".
// Usage   : const { settings, problems } = settingsLoad(textOrNull)   // null = no file yet
//           settings.audio.master ... ; effectiveShake(settings) ; telemetryAllowed(settings)
//           save: atomicWrite(store, "settings.json", JSON.stringify(settings, null, 1))
// Notes   : No Phaser import (Vitest runs it). Missing fields take defaults, bad ones are fixed (one problem
//           each: a number is clamped, a wrong type or unknown choice falls back to the default), and unknown
//           keys are kept as they are, so a newer game's file survives an older build.
//
// Pseudocode:
//   parse (unreadable or not an object -> defaults + one problem) ; copy every key of the file
//   version = 1 ; language must be a string of 2..12 code points (as the reference counts: [...s].length)
//   per schema section: a non-object section counts as one problem ; per field: missing -> default,
//   present -> fixField (bool | num clamp | enum | resolution) ; input.bindings: lists of strings only
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { DEFAULT_BINDINGS, GLYPH_SETS, type Bindings } from "./bindings";
import { deepCopy, hasKey, isNum, isObject, type JsonObject } from "./jsonUtil";

// ---- Tunables ----------------------------------------------------------------
export const SETTINGS_VERSION = 1;
export const DIFFICULTIES = ["story", "easy", "normal", "hard"] as const;
export const COLORBLIND = ["none", "protanopia", "deuteranopia", "tritanopia"] as const;
export const SUB_SIZES = ["small", "medium", "large", "xl"] as const;
export const DISPLAY_MODES = ["windowed", "fullscreen", "borderless"] as const;
export const FRAME_CAPS = [0, 30, 60, 120, 144, 240] as const;
export const CONSENT = ["unset", "yes", "no"] as const;

export interface Settings {
  version: number;
  display: { mode: string; vsync: boolean; frame_cap: number; resolution: [number, number]; ui_scale: number; [k: string]: unknown };
  audio: { master: number; music: number; sfx: number; ui: number; voice: number; mono: boolean; [k: string]: unknown };
  language: string;
  access: {
    text_scale: number; subtitles: boolean; subtitle_size: string; subtitle_background: number;
    speaker_names: boolean; subtitle_barks: boolean; captions_sfx: boolean; colorblind: string;
    reduce_motion: boolean; shake_scale: number; flash_limit: boolean; hold_to_toggle: boolean;
    difficulty: string; game_speed: number; readable_font: boolean; line_spacing: number;
    subtitle_hold: boolean; timing_scale: number; auto_repeat: boolean; narration: boolean; [k: string]: unknown;
  };
  input: { bindings: Bindings; deadzone: number; invert_y: boolean; glyphs: string; [k: string]: unknown };
  telemetry: { consent: string; [k: string]: unknown };
  [k: string]: unknown;
}

const DEFAULTS: Settings = {
  version: SETTINGS_VERSION,
  display: { mode: "windowed", vsync: true, frame_cap: 0, resolution: [1920, 1080], ui_scale: 1.0 },
  audio: { master: 1.0, music: 0.8, sfx: 1.0, ui: 1.0, voice: 1.0, mono: false },
  language: "en",
  access: {
    text_scale: 1.0, subtitles: true, subtitle_size: "medium", subtitle_background: 0.6, speaker_names: true,
    subtitle_barks: false, captions_sfx: false, colorblind: "none", reduce_motion: false, shake_scale: 1.0,
    flash_limit: true, hold_to_toggle: false, difficulty: "normal", game_speed: 1.0,
    readable_font: false, line_spacing: 1.0, subtitle_hold: false, timing_scale: 1.0, auto_repeat: false, narration: false,
  },
  input: { bindings: deepCopy(DEFAULT_BINDINGS) as Bindings, deadzone: 0.2, invert_y: false, glyphs: "auto" },
  telemetry: { consent: "unset" },
};

export type Rule =
  | { kind: "num"; lo: number; hi: number }
  | { kind: "bool" }
  | { kind: "enum"; values: readonly (string | number)[] }
  | { kind: "res" };

const num = (lo: number, hi: number): Rule => ({ kind: "num", lo, hi });
const bool: Rule = { kind: "bool" };
const choice = (values: readonly (string | number)[]): Rule => ({ kind: "enum", values });

/** Section -> field -> rule. The default of each field comes from DEFAULTS. */
export const SCHEMA: Record<string, Record<string, Rule>> = {
  display: { mode: choice(DISPLAY_MODES), vsync: bool, frame_cap: choice(FRAME_CAPS), resolution: { kind: "res" }, ui_scale: num(0.75, 2.0) },
  audio: { master: num(0, 1), music: num(0, 1), sfx: num(0, 1), ui: num(0, 1), voice: num(0, 1), mono: bool },
  access: {
    text_scale: num(0.75, 2.0), subtitles: bool, subtitle_size: choice(SUB_SIZES), subtitle_background: num(0, 1),
    speaker_names: bool, subtitle_barks: bool, captions_sfx: bool, colorblind: choice(COLORBLIND), reduce_motion: bool,
    shake_scale: num(0, 1), flash_limit: bool, hold_to_toggle: bool, difficulty: choice(DIFFICULTIES), game_speed: num(0.5, 1.0),
    readable_font: bool, line_spacing: num(1, 2), subtitle_hold: bool, timing_scale: num(1, 3), auto_repeat: bool, narration: bool,
  },
  input: { deadzone: num(0, 0.9), invert_y: bool, glyphs: choice(GLYPH_SETS) },
  telemetry: { consent: choice(CONSENT) },
};

/** A fresh copy of the built-in defaults. */
export function defaultSettings(): Settings {
  return deepCopy(DEFAULTS);
}

/** [value, problem] for one field. */
export function fixField(rule: Rule, value: unknown, def: unknown): [unknown, boolean] {
  switch (rule.kind) {
    case "bool":
      return typeof value === "boolean" ? [value, false] : [def, true];
    case "num": {
      if (!isNum(value)) return [def, true];
      const clamped = Math.min(Math.max(value, rule.lo), rule.hi);
      return [clamped, clamped !== value];
    }
    case "enum":
      for (const allowed of rule.values) if (typeof allowed === typeof value && value === allowed) return [allowed, false];
      return [def, true];
    case "res":
      if (Array.isArray(value) && value.length === 2 && value.every((n) => isNum(n) && n >= 1 && Number.isInteger(n))) {
        return [[value[0], value[1]], false];
      }
      return [[...(def as number[])], true];
  }
}

function fixBindings(value: unknown, problems: string[]): Bindings {
  const out = deepCopy(DEFAULT_BINDINGS) as Bindings;
  if (!isObject(value)) {
    problems.push("input.bindings");
    return out;
  }
  for (const [action, lst] of Object.entries(value)) {
    if (!Array.isArray(lst)) {
      problems.push(`input.bindings.${action}`);
      continue;
    }
    const clean = lst.filter((b): b is string => typeof b === "string");
    if (clean.length !== lst.length) problems.push(`input.bindings.${action}`);
    out[action] = clean;
  }
  return out;
}

/** Settings from the file's text (null = no file): every field valid, plus the list of what was fixed. */
export function settingsLoad(text: string | null): { settings: Settings; problems: string[] } {
  const problems: string[] = [];
  let raw: unknown;
  try {
    raw = text === null ? {} : JSON.parse(text);
  } catch {
    return { settings: defaultSettings(), problems: ["unreadable"] };
  }
  if (!isObject(raw)) return { settings: defaultSettings(), problems: ["not an object"] };
  const out: JsonObject = deepCopy(raw);
  out.version = SETTINGS_VERSION;
  const lang = hasKey(raw, "language") ? raw.language : "en";
  const langLength = typeof lang === "string" ? [...lang].length : 0; // code points, not UTF-16 units
  if (typeof lang === "string" && langLength >= 2 && langLength <= 12) {
    out.language = lang;
  } else {
    out.language = "en";
    if (hasKey(raw, "language")) problems.push("language");
  }
  const defaults = DEFAULTS as unknown as Record<string, JsonObject>;
  for (const [section, fields] of Object.entries(SCHEMA)) {
    let src = hasKey(raw, section) ? raw[section] : {};
    if (!isObject(src)) {
      problems.push(section);
      src = {};
    }
    const srcObj = src as JsonObject;
    const sec: JsonObject = deepCopy(srcObj);
    for (const [name, rule] of Object.entries(fields)) {
      const def = defaults[section][name];
      if (hasKey(srcObj, name)) {
        const [value, bad] = fixField(rule, srcObj[name], def);
        if (bad) problems.push(`${section}.${name}`);
        sec[name] = deepCopy(value);
      } else {
        sec[name] = deepCopy(def);
      }
    }
    if (section === "input") {
      sec.bindings = hasKey(srcObj, "bindings") ? fixBindings(srcObj.bindings, problems) : (deepCopy(DEFAULT_BINDINGS) as Bindings);
    }
    out[section] = sec;
  }
  return { settings: out as Settings, problems };
}

/** The shake intensity the juice should use: 0 with reduce motion, else the player's shake scale. */
export function effectiveShake(settings: Settings): number {
  return settings.access.reduce_motion ? 0.0 : settings.access.shake_scale;
}

/** Telemetry is recorded only after an explicit yes. */
export function telemetryAllowed(settings: Settings): boolean {
  return settings.telemetry.consent === "yes";
}

/** The settings as file text (one-space indent, like the kit's other JSON files). */
export function settingsText(settings: Settings): string {
  return JSON.stringify(settings, null, 1) + "\n";
}

// {{FOOTER}}
