// ---------------------------------------------------------------------------
// saveStore.ts
// Purpose : Save slots that survive crashes, corruption and game updates: a versioned envelope, a migration
//           chain from every old version, a fallback to the .bak copy, and a refusal to load (or overwrite)
//           a save made by a newer build. Checked against data/golden/shell.json "save_load".
// Usage   : const saves = new SaveStore(store)
//           const r = saves.load(1)            // r.envelope?.data, r.source "primary" | "backup" | "none", r.problems
//           saves.save(1, { level: 3, health: 9 })   // atomic, keeps save_1.json.bak; throws after a "newer" load
//           pure parts: saveLoad(primaryText, backupText), saveMigrate(envelope)
// Notes   : No Phaser import (Vitest runs it). The file is {"format": "save", "version": N, "data": {...}}.
//           MIGRATIONS is the TEMPLATE chain the kit's vectors test (v2 renamed hp to health, v3 added
//           difficulty): when your save data changes shape, bump SAVE_VERSION and add one function
//           (SOP-19). Never edit an old migration; old saves in the wild still need it.
//
// Pseudocode (saveLoad):
//   for primary, then backup: parse -> missing | unreadable | not a save | bad version | newer -> next
//   the first good one is migrated step by step up to SAVE_VERSION and returned with its source
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { atomicWrite } from "./atomicFile";
import { deepCopy, hasKey, isObject, type JsonObject } from "./jsonUtil";
import type { TextStore } from "./textStore";

// ---- Tunables ----------------------------------------------------------------
export const SAVE_VERSION = 3;
export const SAVE_FORMAT = "save";

export type SaveEnvelope = { format: string; version: number; data: JsonObject; [k: string]: unknown };
export type SaveSource = "primary" | "backup" | "none";
export type SaveLoadResult = { envelope: SaveEnvelope | null; source: SaveSource; problems: string[] };

/** MIGRATIONS[n] turns version-n data into version n+1 data. */
export const MIGRATIONS: Record<number, (data: JsonObject) => JsonObject> = {
  1: (data) => {
    if (hasKey(data, "hp")) {
      data.health = data.hp; // v2 renamed hp to health
      delete data.hp;
    }
    return data;
  },
  2: (data) => {
    if (!hasKey(data, "difficulty")) data.difficulty = "normal"; // v3 added the difficulty the game was started on
    return data;
  },
};

/** [envelope, problem]: problem is "" when the envelope is usable. */
export function parseSave(text: string | null): [SaveEnvelope | null, string] {
  if (text === null) return [null, "missing"];
  let env: unknown;
  try {
    env = JSON.parse(text);
  } catch {
    return [null, "unreadable"];
  }
  if (!isObject(env) || env.format !== SAVE_FORMAT || !isObject(env.data)) return [null, "not a save"];
  const v = env.version;
  if (typeof v !== "number" || !Number.isInteger(v) || v < 1) return [null, "bad version"];
  if (v > SAVE_VERSION) return [null, "newer"];
  return [env as SaveEnvelope, ""];
}

export function saveMigrate(env: SaveEnvelope): SaveEnvelope {
  const out = deepCopy(env);
  while (out.version < SAVE_VERSION) {
    const step = MIGRATIONS[out.version];
    if (!step) throw new Error(`no save migration from version ${out.version}`);
    out.data = step(out.data);
    out.version += 1;
  }
  return out;
}

/** The newest usable save from the two files' text (null = file missing). */
export function saveLoad(primary: string | null, backup: string | null): SaveLoadResult {
  const problems: string[] = [];
  for (const [source, text] of [["primary", primary], ["backup", backup]] as const) {
    const [env, problem] = parseSave(text);
    if (env !== null) return { envelope: saveMigrate(env), source, problems };
    problems.push(`${source}: ${problem}`);
  }
  return { envelope: null, source: "none", problems };
}

export const saveName = (slot: number | string) => `save_${slot}.json`;

/** Save slots on a TextStore (localStorage in the browser). */
export class SaveStore {
  private readonly newer = new Set<string>();

  constructor(private readonly store: TextStore) {}

  load(slot: number | string): SaveLoadResult {
    const name = saveName(slot);
    const r = saveLoad(this.store.read(name), this.store.read(name + ".bak"));
    if (r.problems.some((p) => p.endsWith(": newer"))) this.newer.add(name);
    else this.newer.delete(name);
    return r;
  }

  /** Writes the slot atomically. Refuses to replace a save from a newer build of the game. */
  save(slot: number | string, data: JsonObject): void {
    const name = saveName(slot);
    if (this.newer.has(name) || parseSave(this.store.read(name))[1] === "newer") {
      throw new Error(`${name} was written by a newer version of the game: not overwriting it`);
    }
    const text = JSON.stringify({ format: SAVE_FORMAT, version: SAVE_VERSION, data }, null, 1) + "\n";
    atomicWrite(this.store, name, text, { isGood: (old) => parseSave(old)[1] === "" });
  }
}

// {{FOOTER}}
