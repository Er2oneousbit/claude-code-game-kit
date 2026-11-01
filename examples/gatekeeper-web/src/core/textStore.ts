// ---------------------------------------------------------------------------
// textStore.ts
// Purpose : The game's user-data folder as a small interface, so settings, saves, logs, crash files and
//           telemetry code never touch localStorage directly and can be unit tested.
// Usage   : const store = new WebStorageStore(localStorage, dataPrefix(location.search))   // in the browser
//           const store = new MemoryStore()                                                 // in tests
//           store.read("settings.json") ; store.write("logs/game.log", text) ; store.list("crashes/")
// Notes   : No Phaser import (Vitest runs it). Names are folder-style paths ("logs/game.log"). In the browser
//           every name is a localStorage key under one prefix: "<slug>/" by default, or the ?data-dir=
//           URL parameter (what `dev.py smoke --data-dir` sets), so a test run never touches real player data.
//           rename() is the store's atomic step: atomicFile.ts builds safe saves on top of it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const DEFAULT_DATA_PREFIX = "gatekeeper/";
export const DATA_DIR_PARAM = "data-dir";

export interface TextStore {
  read(name: string): string | null;
  /** Throws when the store is full or unavailable. */
  write(name: string, text: string): void;
  /** Replaces `to` with `from` and removes `from`. */
  rename(from: string, to: string): void;
  remove(name: string): void;
  /** Names that start with prefix, sorted. */
  list(prefix?: string): string[];
}

/** The key prefix for this run: ?data-dir=<dir> wins, else the game's default. Always ends in "/". */
export function dataPrefix(search: string, fallback = DEFAULT_DATA_PREFIX): string {
  const dir = new URLSearchParams(search).get(DATA_DIR_PARAM);
  const p = (dir ?? "").trim().replace(/\\/g, "/");
  if (!p) return fallback;
  return p.endsWith("/") ? p : p + "/";
}

/** In-memory store for tests and for browsers that block storage (private mode, disabled cookies). */
export class MemoryStore implements TextStore {
  readonly files = new Map<string, string>();

  read(name: string): string | null {
    return this.files.get(name) ?? null;
  }

  write(name: string, text: string): void {
    this.files.set(name, text);
  }

  rename(from: string, to: string): void {
    const text = this.files.get(from);
    if (text === undefined) throw new Error(`rename: ${from} does not exist`);
    this.files.set(to, text);
    this.files.delete(from);
  }

  remove(name: string): void {
    this.files.delete(name);
  }

  list(prefix = ""): string[] {
    return [...this.files.keys()].filter((k) => k.startsWith(prefix)).sort();
  }
}

/** The Web Storage API subset we use (localStorage, or a test double). */
export interface KeyValueStorage {
  readonly length: number;
  key(index: number): string | null;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** localStorage under one key prefix. */
export class WebStorageStore implements TextStore {
  constructor(private readonly storage: KeyValueStorage, readonly prefix = DEFAULT_DATA_PREFIX) {}

  read(name: string): string | null {
    return this.storage.getItem(this.prefix + name);
  }

  write(name: string, text: string): void {
    this.storage.setItem(this.prefix + name, text); // throws QuotaExceededError when full
  }

  rename(from: string, to: string): void {
    const text = this.read(from);
    if (text === null) throw new Error(`rename: ${from} does not exist`);
    this.write(to, text); // one setItem: the target is either the old text or the new text, never half
    this.remove(from);
  }

  remove(name: string): void {
    this.storage.removeItem(this.prefix + name);
  }

  list(prefix = ""): string[] {
    const out: string[] = [];
    for (let i = 0; i < this.storage.length; i++) {
      const key = this.storage.key(i);
      if (key !== null && key.startsWith(this.prefix + prefix)) out.push(key.slice(this.prefix.length));
    }
    return out.sort();
  }
}
