// ---------------------------------------------------------------------------
// userData.ts
// Purpose : The files in the game's user-data folder besides settings and saves: the rotating game log,
//           crash reports and the consent-gated telemetry file.
// Usage   : const log = new GameLog(store, "My Game 0.1.0") ; Log.addSink((l) => log.append(l)) ; log.flush()
//           writeCrash(store, { header, error, stack, seed, tail: log.tail(40) })   // -> "crashes/crash_<ts>.txt"
//           const tel = new Telemetry(store, () => telemetryAllowed(settings)) ; tel.event("screen", "title")
// Notes   : No Phaser import (Vitest runs it). Files: logs/game.log (first line: version and timestamp;
//           LOG_KEEP older logs as logs/game.1.log ...), crashes/crash_<ts>.txt, telemetry.csv (the last
//           TELEMETRY_MAX_ROWS rows; columns time,session,event,detail as in every engine, tested against
//           data/golden/telemetry.json). Nothing here throws on a full or blocked store: `new Shell()` builds the
//           log before the crash hook exists, so a full localStorage degrades to console-only logging.
//           Telemetry never leaves the device: nothing here sends anything anywhere (SOP-19 explains what a
//           game must add, and promise in its privacy policy, before it uploads the file).
//
// Pseudocode:
//   GameLog(start): game.(KEEP-1).log -> game.KEEP.log ... game.log -> game.1.log ; new game.log with a header
//                   (a write fails -> console only for this run: the older logs stay as they are)
//   append(line): memory buffer (tail) + pending text, flushed every FLUSH_MS, before a crash, on page hide
//   Telemetry.event: only when allowed(): header + the last TELEMETRY_MAX_ROWS - 1 rows + this one, escaped CSV
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { Log } from "./log";
import type { TextStore } from "./textStore";

// ---- Tunables ----------------------------------------------------------------
export const LOG_FILE = "logs/game.log";
export const LOG_KEEP = 5; // older logs kept: logs/game.1.log (newest) .. logs/game.5.log
export const LOG_MAX_CHARS = 200_000; // per file; later lines are dropped with one notice (localStorage is small)
export const TAIL_LINES = 200; // kept in memory for crash and bug reports
export const CRASH_DIR = "crashes/";
export const TELEMETRY_FILE = "telemetry.csv";
export const TELEMETRY_HEADER = "time,session,event,detail";
export const SESSION_LENGTH = 8; // hex digits in a session id (random per launch)
export const TELEMETRY_MAX_ROWS = 2000; // older rows are dropped: the whole file is rewritten on every event

/** 2026-11-01T09:05:03.042Z -> 20261101_090503_042 (sorts by time, safe in file names). */
export function stamp(d: Date = new Date()): string {
  return d.toISOString().replace(/[-:]/g, "").replace("T", "_").replace(".", "_").replace("Z", "");
}

const rotated = (n: number) => LOG_FILE.replace(/\.log$/, `.${n}.log`);

export class GameLog {
  private text: string;
  private readonly lines: string[] = [];
  private dirty = false;
  private full = false;
  /** The rotation failed (store full or blocked): this run writes nothing, so the older logs survive. */
  readonly consoleOnly: boolean = false;

  constructor(private readonly store: TextStore, header: string, now: Date = new Date()) {
    try {
      for (let n = LOG_KEEP - 1; n >= 1; n--) {
        const t = store.read(rotated(n));
        if (t !== null) store.write(rotated(n + 1), t);
      }
      const prev = store.read(LOG_FILE);
      if (prev !== null) store.write(rotated(1), prev);
    } catch (err) {
      // Writing the new log now would overwrite the previous run's (the one a bug report needs) and could
      // throw again: leave the files as they are and log to the console only.
      this.consoleOnly = true;
      Log.warn("core", `${LOG_FILE} not written this run (storage full or blocked: ${String(err)}): console only`);
    }
    this.text = `${header} ${now.toISOString()}\n`;
    this.dirty = true;
    this.flush();
  }

  append(line: string): void {
    this.lines.push(line);
    if (this.lines.length > TAIL_LINES) this.lines.shift();
    if (this.full || this.consoleOnly) return;
    if (this.text.length + line.length > LOG_MAX_CHARS) {
      this.text += "[log full: later lines are only in the browser console]\n";
      this.full = true;
    } else {
      this.text += line + "\n";
    }
    this.dirty = true;
  }

  /** The last n lines (for crash and bug reports). */
  tail(n = 40): string[] {
    return this.lines.slice(-n);
  }

  /** Writes the log if it changed. Never throws (a full store must not crash the game). */
  flush(): void {
    if (!this.dirty || this.consoleOnly) return;
    try {
      this.store.write(LOG_FILE, this.text);
      this.dirty = false;
    } catch {
      /* storage full or blocked: the console still has everything */
    }
  }
}

export type CrashInfo = { header: string; error: string; stack?: string; seed?: string | number | null; tail: string[] };

/** The crash report text. */
export function crashText(info: CrashInfo, now: Date = new Date()): string {
  return [
    info.header,
    `time: ${now.toISOString()}`,
    `seed: ${info.seed ?? "none"}`,
    `error: ${info.error}`,
    "",
    "stack:",
    info.stack || "(none)",
    "",
    `log tail (last ${info.tail.length} lines):`,
    ...info.tail,
    "",
  ].join("\n");
}

/** Writes crashes/crash_<stamp>.txt and returns its name. */
export function writeCrash(store: TextStore, info: CrashInfo, now: Date = new Date()): string {
  const name = `${CRASH_DIR}crash_${stamp(now)}.txt`;
  store.write(name, crashText(info, now));
  return name;
}

/** One CSV field, quoted when it holds a comma, quote or line break. */
export function csvField(v: string): string {
  return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

/** CSV text -> its records without the line breaks between them (a quoted field may hold a line break). */
export function csvRows(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '"') quoted = !quoted; // an escaped "" flips twice: still inside the field
    else if (text[i] === "\n" && !quoted) {
      out.push(text.slice(start, i));
      start = i + 1;
    }
  }
  if (start < text.length) out.push(text.slice(start));
  return out;
}

/** A random id per launch, so rows of one run can be grouped: 8 lowercase hex digits. */
export function newSession(rand: () => number = Math.random): string {
  return Array.from({ length: SESSION_LENGTH }, () => Math.floor(rand() * 16).toString(16)).join("");
}

/** UTC, ISO 8601, whole seconds (a fraction is dropped, not rounded): 2026-11-02T14:05:03Z. */
export function telemetryTime(unixS: number): string {
  return new Date(Math.floor(unixS) * 1000).toISOString().slice(0, 19) + "Z";
}

/** One escaped CSV row of telemetry.csv (no line break). */
export function telemetryRow(unixS: number, session: string, name: string, detail = ""): string {
  return [telemetryTime(unixS), session, name, detail].map(csvField).join(",");
}

export class Telemetry {
  constructor(
    private readonly store: TextStore,
    private readonly allowed: () => boolean,
    readonly session: string = newSession(),
  ) {}

  /** Appends one row when the player said yes (the oldest go past TELEMETRY_MAX_ROWS); returns whether it did. */
  event(name: string, detail = "", now: Date = new Date()): boolean {
    if (!this.allowed()) return false;
    try {
      const rows = csvRows(this.store.read(TELEMETRY_FILE) ?? "");
      if (rows[0] === TELEMETRY_HEADER) rows.shift();
      rows.push(telemetryRow(now.getTime() / 1000, this.session, name, detail));
      this.store.write(TELEMETRY_FILE, [TELEMETRY_HEADER, ...rows.slice(-TELEMETRY_MAX_ROWS)].join("\n") + "\n");
      return true;
    } catch {
      return false;
    }
  }
}

// {{FOOTER}}
