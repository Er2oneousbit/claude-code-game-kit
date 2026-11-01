// ---------------------------------------------------------------------------
// fsStore.ts
// Purpose : A TextStore on the real filesystem (Node), so tests can prove atomicWrite against real files,
//           real flushes and a real rename, not only against localStorage.
// Usage   : const store = new FsStore(mkdtempSync(join(tmpdir(), "kit-"))) ; atomicWrite(store, "save_1.json", t)
// Notes   : Test-only (Node APIs). write() flushes to disk (fsync) before returning, rename() is fs.renameSync,
//           which replaces the target in one step on Windows, macOS and Linux.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readdirSync, readFileSync, renameSync, rmSync, writeSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import type { TextStore } from "../../src/core/textStore";

export class FsStore implements TextStore {
  constructor(readonly root: string) {}

  private path(name: string): string {
    return join(this.root, ...name.split("/"));
  }

  read(name: string): string | null {
    const p = this.path(name);
    return existsSync(p) ? readFileSync(p, "utf-8") : null;
  }

  write(name: string, text: string): void {
    const p = this.path(name);
    mkdirSync(dirname(p), { recursive: true });
    const fd = openSync(p, "w");
    try {
      writeSync(fd, text, null, "utf-8");
      fsyncSync(fd); // on disk before anything is renamed over the old file
    } finally {
      closeSync(fd);
    }
  }

  rename(from: string, to: string): void {
    renameSync(this.path(from), this.path(to));
  }

  remove(name: string): void {
    rmSync(this.path(name), { force: true });
  }

  list(prefix = ""): string[] {
    const out: string[] = [];
    const walk = (dir: string) => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, e.name);
        if (e.isDirectory()) walk(full);
        else out.push(relative(this.root, full).split(/[\\/]/).join("/"));
      }
    };
    if (existsSync(this.root)) walk(this.root);
    return out.filter((n) => n.startsWith(prefix)).sort();
  }
}

// {{FOOTER}}
