// ---------------------------------------------------------------------------
// dialogue.ts
// Purpose : Reads dialogue.built.json (the kit's dialogue format v0, written by Wavesmith's dialogue subcommand,
//           tools/audio/wavesmith, or by hand) and answers what a subtitle bar or typewriter shows at a given time.
// Usage   : const d = parseDialogue(jsonText)                  // throws on a file that is not v0-shaped
//           const d = dialogueFrom(parsedObject)               // the same for JSON a bundler already parsed
//           const line = d.lines["baker.greet"]
//           if (shouldShow(line, settings)) { revealCount(line, t) characters ; cueAt(line, t)?.lines }
//           const cap = d.captions["hit"]                       // SFX captions, when access.captions_sfx is on
// Notes   : No Phaser import (Vitest runs it). Unknown fields are ignored (the format only ever ADDS optional
//           fields). kind "bark" lines are shown only with access.subtitle_barks; "line" kind always (when
//           subtitles are on). Without reveal data that fits the shown text (none built, or a translation or the
//           pseudo locale changed its length) the typewriter runs at DEFAULT_CPS, faster when that would not finish
//           within the line's duration, so a line is always fully shown before its hold and removal.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { isNum, isObject } from "./jsonUtil";

// ---- Tunables ----------------------------------------------------------------
export const DIALOGUE_VERSION = 1;
export const DEFAULT_CPS = 30; // typewriter characters per second without reveal data
export const HOLD_AFTER_S = 1.5; // a finished line stays this long
const REVEAL_EPS = 1e-9; // t * cps lands on a whole character count despite rounding

export type Cue = { start: number; end: number; lines: string[] };
export type DialogueLine = {
  id: string; speaker: string; name: string; color: string; text: string; kind: "line" | "bark";
  priority: number; durationS: number; reveal: { i: number; t: number }[]; cues: Cue[]; audio?: string;
};
export type Caption = { text: string; priority: number; minS: number; directional: boolean };
export type Dialogue = { locale: string; lines: Record<string, DialogueLine>; captions: Record<string, Caption> };

const str = (v: unknown, d = "") => (typeof v === "string" ? v : d);
const num = (v: unknown, d = 0) => (isNum(v) ? v : d);

export function parseDialogue(text: string): Dialogue {
  return dialogueFrom(JSON.parse(text));
}

export function dialogueFrom(raw: unknown): Dialogue {
  if (!isObject(raw) || raw.version !== DIALOGUE_VERSION || !isObject(raw.lines)) throw new Error("not a dialogue.built.json v0 file");
  const lines: Record<string, DialogueLine> = {};
  for (const [id, l] of Object.entries(raw.lines)) {
    if (!isObject(l) || typeof l.text !== "string") continue;
    const reveal = Array.isArray(l.reveal) ? l.reveal.filter(isObject).map((r) => ({ i: num(r.i), t: num(r.t) })) : [];
    const cues = Array.isArray(l.cues)
      ? l.cues.filter(isObject).map((c) => ({ start: num(c.start), end: num(c.end), lines: Array.isArray(c.lines) ? c.lines.map((x) => str(x)) : [] }))
      : [];
    lines[id] = {
      id, speaker: str(l.speaker), name: str(l.name, str(l.speaker)), color: str(l.color, "#ffffff"), text: l.text,
      kind: l.kind === "bark" ? "bark" : "line", priority: num(l.priority, 50),
      durationS: num(l.duration_s, l.text.length / DEFAULT_CPS), reveal, cues, audio: typeof l.audio === "string" ? l.audio : undefined,
    };
  }
  const captions: Record<string, Caption> = {};
  if (isObject(raw.captions)) {
    for (const [id, c] of Object.entries(raw.captions)) {
      if (isObject(c) && typeof c.text === "string") captions[id] = { text: c.text, priority: num(c.priority, 30), minS: num(c.min_s, 1), directional: c.directional === true };
    }
  }
  return { locale: str(raw.locale, "en"), lines, captions };
}

/** Whether the player's settings show this line at all. */
export function shouldShow(line: DialogueLine, access: { subtitles: boolean; subtitle_barks: boolean }): boolean {
  if (!access.subtitles) return false;
  return line.kind === "line" || access.subtitle_barks;
}

/** Characters of the text visible t seconds into the line (typewriter). length overrides the text length. */
export function revealCount(line: DialogueLine, t: number, length = Array.from(line.text).length): number {
  if (line.reveal.length === length) {
    let n = 0;
    for (const r of line.reveal) if (r.t <= t) n++;
    return n;
  }
  if (line.durationS <= 0) return length;
  const cps = Math.max(DEFAULT_CPS, length / line.durationS); // all of it by durationS, never slower than DEFAULT_CPS
  return Math.min(length, Math.max(0, Math.floor(t * cps + REVEAL_EPS)));
}

/** The subtitle chunk shown at time t, or null between and after cues. */
export function cueAt(line: DialogueLine, t: number): Cue | null {
  return line.cues.find((c) => t >= c.start && t < c.end) ?? null;
}

/** Seconds the line stays on screen, hold included. */
export function lineLife(line: DialogueLine): number {
  return line.durationS + HOLD_AFTER_S;
}

// {{FOOTER}}
