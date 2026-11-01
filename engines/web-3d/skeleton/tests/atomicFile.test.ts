// ---------------------------------------------------------------------------
// atomicFile.test.ts
// Purpose : Proves the crash-safe write on the REAL filesystem (a temp folder) and on the localStorage store,
//           plus the save store's .bak fallback and its refusal to overwrite a newer game's save.
// Usage   : python tools/dev.py test
// Notes   : A "crash" is simulated by writing <file>.tmp and never renaming it, which is exactly what a closed
//           tab or a power cut between the two steps leaves behind.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { atomicWrite } from "../src/core/atomicFile";
import { SaveStore, SAVE_VERSION } from "../src/core/saveStore";
import { MemoryStore, WebStorageStore, dataPrefix, type KeyValueStorage, type TextStore } from "../src/core/textStore";
import { FsStore } from "./helpers/fsStore";

/** A localStorage stand-in (Map-backed) with the Web Storage API shape. */
class FakeStorage implements KeyValueStorage {
  private readonly m = new Map<string, string>();
  get length() { return this.m.size; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  getItem(k: string) { return this.m.get(k) ?? null; }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
  removeItem(k: string) { this.m.delete(k); }
}

let dir = "";
beforeEach(() => { dir = mkdtempSync(join(tmpdir(), "kit-atomic-")); });
afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

const stores: [string, () => TextStore][] = [
  ["real filesystem", () => new FsStore(dir)],
  ["localStorage", () => new WebStorageStore(new FakeStorage(), "test/")],
  ["memory", () => new MemoryStore()],
];

describe.each(stores)("atomicWrite on %s", (_label, make) => {
  it("writes the file and leaves no .tmp behind", () => {
    const s = make();
    atomicWrite(s, "settings.json", "{\"a\": 1}");
    expect(s.read("settings.json")).toBe("{\"a\": 1}");
    expect(s.read("settings.json.tmp")).toBeNull();
  });

  it("keeps the previous version as .bak", () => {
    const s = make();
    atomicWrite(s, "save_1.json", "one");
    atomicWrite(s, "save_1.json", "two");
    expect(s.read("save_1.json")).toBe("two");
    expect(s.read("save_1.json.bak")).toBe("one");
  });

  it("leaves the old file intact after a crash between write and rename", () => {
    const s = make();
    atomicWrite(s, "save_1.json", "good");
    s.write("save_1.json.tmp", "half-writ"); // the crash: tmp written, rename never happened
    expect(s.read("save_1.json")).toBe("good");
    atomicWrite(s, "save_1.json", "next"); // the next save overwrites the stale tmp
    expect(s.read("save_1.json")).toBe("next");
    expect(s.read("save_1.json.tmp")).toBeNull();
  });

  it("does not back up a file that isGood rejects", () => {
    const s = make();
    atomicWrite(s, "save_1.json", "good");
    atomicWrite(s, "save_1.json", "corrupt");
    atomicWrite(s, "save_1.json", "new", { isGood: (old) => old !== "corrupt" });
    expect(s.read("save_1.json.bak")).toBe("good");
  });
});

describe("SaveStore", () => {
  it("falls back to the .bak when the primary is corrupt", () => {
    const store = new FsStore(dir);
    const saves = new SaveStore(store);
    saves.save(1, { level: 1 });
    saves.save(1, { level: 2 });
    store.write("save_1.json", "{\"format\": \"save\", \"vers"); // torn file
    const r = saves.load(1);
    expect(r.source).toBe("backup");
    expect(r.envelope?.data.level).toBe(1);
    expect(r.envelope?.version).toBe(SAVE_VERSION);
  });

  it("never backs up a corrupt primary over a good .bak", () => {
    const store = new MemoryStore();
    const saves = new SaveStore(store);
    saves.save(1, { level: 1 });
    saves.save(1, { level: 2 });
    store.write("save_1.json", "garbage");
    saves.save(1, { level: 3 });
    expect(JSON.parse(store.read("save_1.json.bak")!).data.level).toBe(1);
  });

  it("refuses to overwrite a save from a newer game version", () => {
    const store = new MemoryStore();
    const newer = JSON.stringify({ format: "save", version: SAVE_VERSION + 1, data: { x: 1 } });
    store.write("save_2.json", newer);
    const saves = new SaveStore(store);
    expect(saves.load(2).source).toBe("none");
    expect(() => saves.save(2, { x: 0 })).toThrow(/newer/);
    expect(store.read("save_2.json")).toBe(newer);
  });
});

describe("dataPrefix", () => {
  it("uses ?data-dir= when given, with a trailing slash", () => {
    expect(dataPrefix("?data-dir=build/smoke-data")).toBe("build/smoke-data/");
    expect(dataPrefix("?data-dir=C:\\tmp\\d\\")).toBe("C:/tmp/d/");
  });

  it("falls back to the game's prefix", () => {
    expect(dataPrefix("", "game/")).toBe("game/");
    expect(dataPrefix("?data-dir=", "game/")).toBe("game/");
  });
});

// {{FOOTER}}
