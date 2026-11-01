// ---------------------------------------------------------------------------
// userData.ts
// Purpose : The files in the game's user-data folder besides settings and saves: the rotating game log,
//           crash reports and the consent-gated telemetry file.
// Usage   : const log = new GameLog(store, "My Game 0.1.0") ; Log.addSink((l) => log.append(l)) ; log.flush()
//           writeCrash(store, { header, error, stack, seed, tail: log.tail(40) })   // -> "crashes/crash_<ts>.txt"
//           const tel = new Telemetry(store, () => telemetryAllowed(settings)) ; tel.event("screen", "title")
// Notes   : No Phaser import (Vitest runs it). Files: logs/game.log (first line: version and timestamp;
//           LOG_KEEP older logs as logs/game.1.log ...), crashes/crash_<ts>.txt, telemetry.csv.
//           Telemetry never leaves the device: nothing here sends anything anywhere (SOP-19 explains what a
//           game must add, and promise in its privacy policy, before it uploads the file).
//
// Pseudocode:
//   GameLog(start): game.(KEEP-1).log -> game.KEEP.log ... game.log -> game.1.log ; new game.log with a header
//   append(line): memory buffer (tail) + pending text, flushed every FLUSH_MS, before a crash, on page hide
//   Telemetry.event: only when allowed(): telemetry.csv gets a header once, then one escaped CSV row per event
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { TextStore } from "./textStore";

// ---- Tunables ----------------------------------------------------------------
export const LOG_FILE = "logs/game.log";
export const LOG_KEEP = 5; // older logs kept: logs/game.1.log (newest) .. logs/game.5.log
export const LOG_MAX_CHARS = 200_000; // per file; later lines are dropped with one notice (localStorage is small)
export const TAIL_LINES = 200; // kept in memory for crash and bug reports
export const CRASH_DIR = "crashes/";
export const TELEMETRY_FILE = "telemetry.csv";
export const TELEMETRY_HEADER = "time,event,detail";

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

  constructor(private readonly store: TextStore, header: string, now: Date = new Date()) {
    for (let n = LOG_KEEP - 1; n >= 1; n--) {
      const t = store.read(rotated(n));
      if (t !== null) store.write(rotated(n + 1), t);
    }
    const prev = store.read(LOG_FILE);
    if (prev !== null) store.write(rotated(1), prev);
    this.text = `${header} ${now.toISOString()}\n`;
    this.dirty = true;
    this.flush();
  }

  append(line: string): void {
    this.lines.push(line);
    if (this.lines.length > TAIL_LINES) this.lines.shift();
    if (this.full) return;
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
    if (!this.dirty) return;
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

export class Telemetry {
  constructor(private readonly store: TextStore, private readonly allowed: () => boolean) {}

  /** Appends one row when the player said yes; returns whether it did. */
  event(name: string, detail = "", now: Date = new Date()): boolean {
    if (!this.allowed()) return false;
    try {
      const old = this.store.read(TELEMETRY_FILE) ?? TELEMETRY_HEADER + "\n";
      this.store.write(TELEMETRY_FILE, old + [now.toISOString(), name, detail].map(csvField).join(",") + "\n");
      return true;
    } catch {
      return false;
    }
  }
}

// {{FOOTER}}
