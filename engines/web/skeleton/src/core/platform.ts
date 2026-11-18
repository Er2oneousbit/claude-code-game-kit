// ---------------------------------------------------------------------------
// platform.ts
// Purpose : The engine-free platform layer (#84, docs/PLATFORM.md): achievements, stats, rich presence, the
//           overlay's pause hook and cloud saves, kept here and sent to a backend. Every game runs the null
//           backend (records every call); a store adapter replaces it in a store build. Checked against
//           data/golden/platform.json (every case).
// Usage   : const ps = new PlatformService(store, achievementsText)      // the shell builds one at start
//           ps.unlock("first_win") ; ps.addStat("enemies_defeated", 1) ; ps.flush()   // at checkpoints
//           ps.setPresence("status", "In the crypt") ; ps.saved("save_1.json")         // after an atomic save
//           if (ps.overlay(active, topScreenId) === "pause") shell.pauseGame()
//           pure parts: achievementsLoad, cloudPartition, overlayAction, Platform, NullBackend, platformStateLoad
// Notes   : No Phaser import (Vitest runs it). A browser build has no Steam: the web overlay keeps the null
//           backend (PLATFORM.md section 4; steamworks.js or Greenworks belong to an Electron or NW.js wrapper,
//           not this template). With no data/achievements.json every call is "unknown" and nothing is written,
//           so a game without achievements behaves exactly as before. The local state is a cache
//           (<user-data>/platform_state.json, written atomically only when it changed); the store's copy is the
//           truth.
//
// Pseudocode:
//   Platform op -> update local state -> (online) send calls to backend.send, one at a time, in order
//   flush: set_stat per pending stat (definition order), set_achievement per pending unlock, store_stats;
//          a false store_stats keeps everything and goes offline; then cloud_write per pending cloud file
//   PlatformService: defs <- data/achievements.json ; state <- platform_state.json ; backend available ->
//          connect(backend.remote()) ; after every op: write the state file when it changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): Platform.storeFailed and PlatformService.update take a
//           store that failed after it was accepted (a backend's takeStoreFailure) back onto the queue
// ---------------------------------------------------------------------------
import { atomicWrite } from "./atomicFile";
import { isObject, type JsonObject } from "./jsonUtil";
import { Log } from "./log";
import type { TextStore } from "./textStore";

// ---- Tunables (the same in every engine: data/golden/platform.json "names and limits") ------
export const PLATFORM_FORMAT = "platform_state";
export const PLATFORM_STATE_VERSION = 1;
export const PLATFORM_STATE_FILE = "platform_state.json";
export const PLATFORM_ID_MAX = 64;
export const STAT_TYPES = ["int", "float"];
export const PRESENCE_MAX_KEYS = 30; // Steam's rich presence limits (verify)
export const PRESENCE_MAX_VALUE_BYTES = 255;
export const CLOUD_MODES = ["auto", "api"];
export const CLOUD_LOCAL_NAMES = ["settings.json", PLATFORM_STATE_FILE, "telemetry.csv", "log_tail.txt"];
export const CLOUD_LOCAL_SUFFIXES = [".tmp", ".log"];
export const CLOUD_LOCAL_DIRS = ["logs", "crashes", "captures"];
export const OVERLAY_PAUSE_SCREENS = ["play"];
/** The game's cloud mode: "auto" (Steam Auto-Cloud, no code, preferred) or "api" (the adapter writes files). */
export const CLOUD_MODE: CloudMode = "auto";

export type CloudMode = "auto" | "api";
export type StatType = "int" | "float";
export type StatDef = { id: string; type: StatType; min: number; max: number | null; increment_only: boolean };
export type AchievementDef = {
  id: string;
  name: string;
  description: string;
  stat: string | null;
  threshold: number | null;
  progress_every: number | null;
};
export type PlatformDefs = { version: number; stats: StatDef[]; achievements: AchievementDef[] };
export type Call = (string | number | boolean)[];
export type Remote = { unlocked?: unknown; stats?: unknown };
export type PlatformState = {
  format: string;
  version: number;
  unlocked: string[];
  stats: Record<string, number>;
  pending: { stats: string[]; unlocks: string[]; cloud: string[] };
};

const LETTERS = /^[A-Za-z][A-Za-z0-9_]*$/;

/** An achievement, stat or presence key name: 1 to 64 ASCII characters, a letter first. */
export function platformIdOk(v: unknown): v is string {
  return typeof v === "string" && v.length > 0 && v.length <= PLATFORM_ID_MAX && LETTERS.test(v);
}

/** A finite number (JSON true is never 1 here). */
const numOk = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
/** Whole by value, never by type: 5 and 5.0 are the same number. */
const whole = (v: unknown): v is number => numOk(v) && Math.floor(v) === v;
const utf8Len = (s: string): number => new TextEncoder().encode(s).length;
const has = (o: JsonObject, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);
/** o[k] when the key is there (null included), else the default: Python's dict.get(k, default). */
const get = (o: JsonObject, k: string, dflt: unknown): unknown => (has(o, k) ? o[k] : dflt);

function clampStat(s: StatDef, v: number): number {
  const lo = Math.max(v, s.min);
  return s.max === null ? lo : Math.min(lo, s.max);
}

/** A stat's value before anything happened: 0 clamped into [min, max]. */
export function statInitial(s: StatDef): number {
  return clampStat(s, 0);
}

const emptyDefs = (): PlatformDefs => ({ version: PLATFORM_STATE_VERSION, stats: [], achievements: [] });

/** data/achievements.json text (null or "" = no file) -> the definitions and the number of problems. */
export function achievementsLoad(text: string | null): { defs: PlatformDefs; problems: number } {
  if (!text) return { defs: emptyDefs(), problems: 0 };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { defs: emptyDefs(), problems: 1 };
  }
  if (!isObject(raw)) return { defs: emptyDefs(), problems: 1 };
  let problems = 0;
  const stats: StatDef[] = [];
  const achievements: AchievementDef[] = [];
  let rawStats = get(raw, "stats", []);
  if (!Array.isArray(rawStats)) {
    rawStats = [];
    problems++;
  }
  for (const s of rawStats as unknown[]) {
    let ok = isObject(s) && platformIdOk(s.id) && stats.every((t) => t.id !== s.id);
    let kind: unknown, lo: unknown, hi: unknown, inc: unknown;
    if (ok && isObject(s)) {
      kind = get(s, "type", "int");
      lo = get(s, "min", 0);
      hi = get(s, "max", null);
      inc = get(s, "increment_only", false);
      const w = kind === "int" ? whole : numOk;
      ok = STAT_TYPES.includes(kind as string) && w(lo) && (hi === null || (w(hi) && (hi as number) >= (lo as number))) && typeof inc === "boolean";
    }
    if (!ok || !isObject(s)) {
      problems++;
      continue;
    }
    stats.push({ id: s.id as string, type: kind as StatType, min: lo as number, max: hi as number | null, increment_only: inc as boolean });
  }
  const byId = new Map(stats.map((s) => [s.id, s]));
  let rawAch = get(raw, "achievements", []);
  if (!Array.isArray(rawAch)) {
    rawAch = [];
    problems++;
  }
  for (const a of rawAch as unknown[]) {
    let ok =
      isObject(a) &&
      platformIdOk(a.id) &&
      achievements.every((b) => b.id !== a.id) &&
      typeof a.name === "string" &&
      a.name !== "" &&
      typeof get(a, "description", "") === "string";
    let stat: unknown = null, threshold: unknown = null, every: unknown = null;
    if (ok && isObject(a)) {
      stat = get(a, "stat", null);
      threshold = get(a, "threshold", null);
      every = get(a, "progress_every", null);
      if (stat !== null) {
        const sdef = typeof stat === "string" ? byId.get(stat) : undefined;
        const w = sdef && sdef.type === "int" ? whole : numOk;
        ok =
          sdef !== undefined &&
          w(threshold) &&
          threshold > statInitial(sdef) &&
          (sdef.max === null || threshold <= sdef.max) &&
          (every === null || (w(every) && every > 0 && every < threshold));
      } else {
        ok = threshold === null && every === null; // a threshold without a stat is a mistake
      }
    }
    if (!ok || !isObject(a)) {
      problems++;
      continue;
    }
    achievements.push({
      id: a.id as string,
      name: a.name as string,
      description: get(a, "description", "") as string,
      stat: stat as string | null,
      threshold: stat === null ? null : (threshold as number),
      progress_every: every === null ? null : (every as number),
    });
  }
  return { defs: { version: PLATFORM_STATE_VERSION, stats, achievements }, problems };
}

/** Which user-data file syncs: "cloud" or "local". ASCII-only folding (never a locale's lowercase). */
export function cloudPartition(path: string): "cloud" | "local" {
  const folded = path.replace(/[A-Z]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 32));
  const parts = folded.replace(/\\/g, "/").split("/").filter((p) => p !== "" && p !== ".");
  if (parts.length === 0) return "local";
  const name = parts[parts.length - 1];
  if ((parts.length > 1 && CLOUD_LOCAL_DIRS.includes(parts[0])) || CLOUD_LOCAL_NAMES.includes(name) || CLOUD_LOCAL_SUFFIXES.some((s) => name.endsWith(s))) {
    return "local";
  }
  return "cloud";
}

/** The store overlay opened (active) or closed over `screen`: "pause" opens the pause menu; closing never resumes. */
export function overlayAction(active: boolean, screen: string): "pause" | "none" {
  return active && OVERLAY_PAUSE_SCREENS.includes(screen) ? "pause" : "none";
}

/** The backend interface (PLATFORM.md section 4). send returns false only for a store_stats the store refused. */
export interface PlatformBackend {
  readonly name: string;
  available(): boolean;
  remote(): Remote;
  send(call: Call): boolean;
  /** Each frame: run the SDK's callbacks (the null backend does nothing). */
  update?(): void;
  /** A store that failed after send(["store_stats"]) returned true (Steam's UserStatsStored): its set_stat and
   *  set_achievement calls, oldest first; null when none. */
  takeStoreFailure?(): Call[] | null;
}

/** The backend every game runs by default: records every call and keeps what a store would hold. */
export class NullBackend implements PlatformBackend {
  readonly name = "null";
  readonly calls: Call[] = [];
  unlocked: string[] = [];
  stats: Record<string, number> = {};
  presence: Record<string, string> = {};
  cloud: string[] = [];
  /** Test hook: the next N store_stats fail (a failed store lands nothing). */
  failStores = 0;
  private stagedUnlocks: string[] = [];
  private stagedStats: Record<string, number> = {};

  available(): boolean {
    return true;
  }

  remote(): Remote {
    return { unlocked: [...this.unlocked], stats: { ...this.stats } };
  }

  send(call: Call): boolean {
    this.calls.push([...call]);
    const [name, a, b] = call;
    if (name === "set_achievement") {
      if (!this.stagedUnlocks.includes(a as string)) this.stagedUnlocks.push(a as string);
    } else if (name === "set_stat") {
      this.stagedStats[a as string] = b as number;
    } else if (name === "store_stats") {
      if (this.failStores > 0) {
        this.failStores--;
        return false;
      }
      for (const u of this.stagedUnlocks) if (!this.unlocked.includes(u)) this.unlocked.push(u);
      Object.assign(this.stats, this.stagedStats);
      this.stagedUnlocks = [];
      this.stagedStats = {};
    } else if (name === "reset_all_stats") {
      this.unlocked = [];
      this.stats = {};
      this.stagedUnlocks = [];
      this.stagedStats = {};
    } else if (name === "set_presence") {
      if (b === "") delete this.presence[a as string];
      else this.presence[a as string] = b as string;
    } else if (name === "clear_presence") {
      this.presence = {};
    } else if (name === "cloud_write" && !this.cloud.includes(a as string)) {
      this.cloud.push(a as string);
    }
    return true;
  }
}

export type Out = { out: string; calls: Call[] };

/** The rules (PLATFORM.md section 3). Every operation returns its status word and the calls it sent, in order. */
export class Platform {
  readonly statDefs: Map<string, StatDef>;
  readonly achDefs: Map<string, AchievementDef>;
  unlocked: string[] = [];
  stats: Record<string, number> = {};
  pendingStats: string[] = [];
  pendingUnlocks: string[] = [];
  pendingCloud: string[] = [];
  presence: Record<string, string> = {};
  private sent: Call[] = [];

  constructor(
    readonly defs: PlatformDefs,
    readonly backend: PlatformBackend = new NullBackend(),
    public online = false,
    public cloud: CloudMode = "auto",
  ) {
    this.statDefs = new Map(defs.stats.map((s) => [s.id, s]));
    this.achDefs = new Map(defs.achievements.map((a) => [a.id, a]));
    this.resetLocal();
  }

  private resetLocal(): void {
    this.unlocked = [];
    this.stats = {};
    for (const s of this.defs.stats) this.stats[s.id] = statInitial(s);
    this.pendingStats = [];
    this.pendingUnlocks = [];
    this.pendingCloud = [];
  }

  /** What the state file holds (and what the golden steps compare). */
  state(): PlatformState {
    return {
      format: PLATFORM_FORMAT,
      version: PLATFORM_STATE_VERSION,
      unlocked: [...this.unlocked],
      stats: { ...this.stats },
      pending: {
        stats: this.defs.stats.filter((s) => this.pendingStats.includes(s.id)).map((s) => s.id),
        unlocks: [...this.pendingUnlocks],
        cloud: [...this.pendingCloud],
      },
    };
  }

  /** Takes over a loaded state (platformStateLoad's), e.g. at start. */
  restore(st: PlatformState): void {
    this.unlocked = [...st.unlocked];
    this.stats = { ...st.stats };
    this.pendingStats = [...st.pending.stats];
    this.pendingUnlocks = [...st.pending.unlocks];
    this.pendingCloud = [...st.pending.cloud];
  }

  /** The presence map, keys sorted (ordinal). */
  presenceList(): [string, string][] {
    return Object.keys(this.presence).sort().map((k) => [k, this.presence[k]]);
  }

  private send(call: Call): boolean {
    this.sent.push(call);
    return this.backend.send(call);
  }

  private done(out: string): Out {
    const calls = this.sent;
    this.sent = [];
    return { out, calls };
  }

  private unlockLocal(id: string): void {
    this.unlocked.push(id);
    this.pendingUnlocks.push(id);
  }

  unlock(id: string): Out {
    if (!this.achDefs.has(id)) return this.done("unknown");
    if (this.unlocked.includes(id)) return this.done("already");
    this.unlockLocal(id);
    if (this.online) this.flushInner();
    return this.done("unlocked");
  }

  private check(sid: string, old: number, now: number, notify: boolean): boolean {
    let unlocked = false;
    for (const a of this.defs.achievements) {
      if (a.stat !== sid || this.unlocked.includes(a.id)) continue;
      if (now >= (a.threshold as number)) {
        this.unlockLocal(a.id);
        unlocked = true;
      } else if (notify && this.online && a.progress_every !== null && Math.floor(now / a.progress_every) > Math.floor(old / a.progress_every)) {
        this.send(["indicate_progress", a.id, now, a.threshold as number]);
      }
    }
    return unlocked;
  }

  /** v may be anything a caller (or a JSON file) passes: a non-number is refused, never coerced. */
  setStat(id: string, v: unknown): Out {
    const s = this.statDefs.get(id);
    if (!s) return this.done("unknown");
    if (!numOk(v) || (s.type === "int" && !whole(v))) return this.done("refused");
    const c = clampStat(s, v);
    const old = this.stats[id];
    if (s.increment_only && c < old) return this.done("refused");
    if (c === old) return this.done("same");
    this.stats[id] = c;
    if (!this.pendingStats.includes(id)) this.pendingStats.push(id);
    if (this.check(id, old, c, true) && this.online) this.flushInner();
    return this.done(c !== v ? "clamped" : "ok");
  }

  addStat(id: string, d: unknown): Out {
    const s = this.statDefs.get(id);
    if (!s) return this.done("unknown");
    if (!numOk(d) || (s.type === "int" && !whole(d))) return this.done("refused");
    return this.setStat(id, this.stats[id] + d);
  }

  private flushInner(): string {
    if (!this.online) return "offline";
    if (this.pendingStats.length === 0 && this.pendingUnlocks.length === 0 && this.pendingCloud.length === 0) return "nothing";
    if (this.pendingStats.length > 0 || this.pendingUnlocks.length > 0) {
      for (const s of this.defs.stats) if (this.pendingStats.includes(s.id)) this.send(["set_stat", s.id, this.stats[s.id]]);
      for (const id of this.pendingUnlocks) this.send(["set_achievement", id]);
      if (!this.send(["store_stats"])) {
        this.online = false; // the store said no: keep everything, wait for connect()
        return "failed";
      }
      this.pendingStats = [];
      this.pendingUnlocks = [];
    }
    for (const p of this.pendingCloud) this.send(["cloud_write", p]);
    this.pendingCloud = [];
    return "sent";
  }

  flush(): Out {
    return this.done(this.flushInner());
  }

  setPresence(key: unknown, value: unknown): Out {
    if (!platformIdOk(key) || typeof value !== "string" || utf8Len(value) > PRESENCE_MAX_VALUE_BYTES) return this.done("refused");
    const known = Object.prototype.hasOwnProperty.call(this.presence, key);
    if (value === "") {
      if (!known) return this.done("same");
      delete this.presence[key];
    } else {
      if (known && this.presence[key] === value) return this.done("same");
      if (!known && Object.keys(this.presence).length >= PRESENCE_MAX_KEYS) return this.done("refused");
      this.presence[key] = value;
    }
    if (this.online) this.send(["set_presence", key, value]);
    return this.done("ok");
  }

  clearPresence(): Out {
    if (Object.keys(this.presence).length === 0) return this.done("same");
    this.presence = {};
    if (this.online) this.send(["clear_presence"]);
    return this.done("ok");
  }

  /** The save code calls this after its atomic write succeeded; path is relative to the user-data folder. */
  saved(path: string): Out {
    const part = cloudPartition(path);
    if (part === "cloud" && this.cloud === "api") {
      if (this.online) this.send(["cloud_write", path]);
      else if (!this.pendingCloud.includes(path)) this.pendingCloud.push(path);
    }
    return this.done(part);
  }

  connect(remote: Remote): Out {
    this.online = true;
    const ru = Array.isArray(remote.unlocked) ? remote.unlocked : [];
    for (const id of ru) {
      if (typeof id !== "string") continue;
      if (this.achDefs.has(id) && !this.unlocked.includes(id)) this.unlocked.push(id);
      const i = this.pendingUnlocks.indexOf(id);
      if (i >= 0) this.pendingUnlocks.splice(i, 1);
    }
    const rs = isObject(remote.stats) ? remote.stats : {};
    for (const s of this.defs.stats) {
      const r0 = has(rs, s.id) ? rs[s.id] : undefined;
      if (!numOk(r0) || (s.type === "int" && !whole(r0))) continue;
      const r = clampStat(s, r0);
      const old = this.stats[s.id];
      const pend = this.pendingStats.includes(s.id);
      let now: number;
      if (s.increment_only) {
        if (r >= old && pend) this.pendingStats.splice(this.pendingStats.indexOf(s.id), 1);
        now = Math.max(old, r);
      } else {
        now = pend ? old : r;
      }
      this.stats[s.id] = now;
      this.check(s.id, old, now, false);
    }
    this.flushInner();
    if (this.online) for (const [k, v] of this.presenceList()) this.send(["set_presence", k, v]);
    return this.done(this.online ? "online" : "failed");
  }

  disconnect(): Out {
    this.online = false;
    return this.done("offline");
  }

  /** A store the backend accepted failed later: the same as a refused store_stats. The batch's stats and unlocks
   *  are pending again and the layer is offline until connect(). */
  storeFailed(batch: Call[]): Out {
    this.online = false;
    for (const [name, id] of batch) {
      if (name === "set_stat" && this.statDefs.has(id as string) && !this.pendingStats.includes(id as string)) this.pendingStats.push(id as string);
      else if (name === "set_achievement" && this.unlocked.includes(id as string) && !this.pendingUnlocks.includes(id as string)) this.pendingUnlocks.push(id as string);
    }
    return this.done("failed");
  }

  /** Testing only: refused offline (a reset is never queued). */
  resetAll(): Out {
    if (!this.online) return this.done("offline");
    this.resetLocal();
    this.send(["reset_all_stats", true]);
    return this.done("reset");
  }
}

/** platform_state.json text (null or "" = no file) -> the state and the number of problems. */
export function platformStateLoad(defs: PlatformDefs, text: string | null): { state: PlatformState; problems: number } {
  const p = new Platform(defs);
  if (!text) return { state: p.state(), problems: 0 };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { state: p.state(), problems: 1 };
  }
  if (!isObject(raw) || raw.format !== PLATFORM_FORMAT || raw.version !== PLATFORM_STATE_VERSION) return { state: p.state(), problems: 1 };
  let problems = 0;
  const list = (v: unknown): unknown[] => {
    if (Array.isArray(v)) return v;
    if (v !== undefined && v !== null) problems++;
    return [];
  };
  const dict = (v: unknown): JsonObject => {
    if (isObject(v)) return v;
    if (v !== undefined && v !== null) problems++;
    return {};
  };
  for (const id of list(raw.unlocked)) {
    if (typeof id === "string" && p.achDefs.has(id) && !p.unlocked.includes(id)) p.unlocked.push(id);
    else problems++;
  }
  const st = dict(raw.stats);
  for (const sid of Object.keys(st)) {
    const s = p.statDefs.get(sid);
    const v = st[sid];
    if (!s || !numOk(v) || (s.type === "int" && !whole(v))) {
      problems++;
      continue;
    }
    p.stats[sid] = clampStat(s, v);
  }
  const pending = dict(raw.pending);
  for (const sid of list(pending.stats)) {
    if (typeof sid === "string" && p.statDefs.has(sid) && !p.pendingStats.includes(sid)) p.pendingStats.push(sid);
    else problems++;
  }
  for (const id of list(pending.unlocks)) {
    if (typeof id === "string" && p.unlocked.includes(id) && !p.pendingUnlocks.includes(id)) p.pendingUnlocks.push(id);
    else problems++;
  }
  for (const path of list(pending.cloud)) {
    if (typeof path === "string" && cloudPartition(path) === "cloud" && !p.pendingCloud.includes(path)) p.pendingCloud.push(path);
    else problems++;
  }
  return { state: p.state(), problems };
}

/** The game-facing service the shell owns: the rules, the backend, and the cached local state file. */
export class PlatformService {
  readonly platform: Platform;
  /** False without data/achievements.json (or with an empty one): nothing is ever written. */
  readonly active: boolean;
  private lastWritten: string;

  constructor(
    private readonly store: TextStore,
    achievementsText: string | null,
    readonly backend: PlatformBackend = new NullBackend(),
    cloud: CloudMode = CLOUD_MODE,
  ) {
    const { defs, problems } = achievementsLoad(achievementsText);
    if (problems > 0) Log.warn("platform", `data/achievements.json: ${problems} problem(s), those entries were dropped`);
    this.active = defs.stats.length > 0 || defs.achievements.length > 0;
    this.platform = new Platform(defs, backend, false, cloud);
    let stored: string | null = null;
    if (this.active) {
      try {
        stored = store.read(PLATFORM_STATE_FILE);
      } catch {
        stored = null;
      }
      const loaded = platformStateLoad(defs, stored);
      if (loaded.problems > 0) Log.warn("platform", `${PLATFORM_STATE_FILE}: ${loaded.problems} problem(s), the store's copy wins`);
      this.platform.restore(loaded.state);
    }
    this.lastWritten = stored ?? "";
    if (backend.available()) this.platform.connect(backend.remote());
    this.persist();
  }

  /** Writes the state file when it changed (never throws: a full store must not stop the game). */
  private persist(): void {
    if (!this.active) return;
    const text = JSON.stringify(this.platform.state(), null, 1) + "\n";
    if (text === this.lastWritten) return;
    try {
      atomicWrite(this.store, PLATFORM_STATE_FILE, text, { backup: false });
      this.lastWritten = text;
    } catch (err) {
      Log.warn("platform", `${PLATFORM_STATE_FILE} not written: ${String(err)}`);
    }
  }

  private after(r: Out): string {
    this.persist();
    return r.out;
  }

  unlock(id: string): string {
    return this.after(this.platform.unlock(id));
  }
  setStat(id: string, v: number): string {
    return this.after(this.platform.setStat(id, v));
  }
  addStat(id: string, d: number): string {
    return this.after(this.platform.addStat(id, d));
  }
  /** At checkpoints: level end, pause, quit. */
  flush(): string {
    return this.after(this.platform.flush());
  }
  setPresence(key: string, value: string): string {
    return this.after(this.platform.setPresence(key, value));
  }
  clearPresence(): string {
    return this.after(this.platform.clearPresence());
  }
  /** After an atomic save: its cloud partition (and, in api mode, the cloud write or its queue). */
  saved(path: string): string {
    return this.after(this.platform.saved(path));
  }
  /** The store overlay opened or closed over `screen`: "pause" means open the pause menu. */
  overlay(active: boolean, screen: string): "pause" | "none" {
    return overlayAction(active, screen);
  }
  /** Each frame (the null backend does nothing); a store that failed late goes back on the queue, offline. */
  update(): void {
    this.backend.update?.();
    for (let batch = this.backend.takeStoreFailure?.(); batch; batch = this.backend.takeStoreFailure?.()) {
      Log.warn("platform", "a store the backend accepted failed later: kept for the next connect");
      this.after(this.platform.storeFailed(batch));
    }
  }
}

// {{FOOTER}}
