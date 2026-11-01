// ---------------------------------------------------------------------------
// atomicFile.ts
// Purpose : Crash-safe writes for settings and saves: the old file stays readable until the new one is
//           complete, and the previous good version is kept as <file>.bak.
// Usage   : atomicWrite(store, "save_1.json", text)                          // keeps save_1.json.bak
//           atomicWrite(store, "save_1.json", text, { isGood: (old) => ... }) // back up only a valid old file
// Notes   : No Phaser import (Vitest runs it, also against the real filesystem in tests/atomicFile.test.ts).
//           A crash (closed tab, power cut) between writing <file>.tmp and the rename leaves the old file intact;
//           the stale .tmp is overwritten by the next save.
//
// Pseudocode:
//   write <file>.tmp ; read it back (a short or failed write throws here, before anything is replaced)
//   if <file> exists and isGood(old): copy it to <file>.bak
//   rename <file>.tmp over <file>
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type { TextStore } from "./textStore";

export const TMP_SUFFIX = ".tmp";
export const BAK_SUFFIX = ".bak";

export type AtomicOptions = {
  /** Keep the replaced file as <file>.bak (default true). */
  backup?: boolean;
  /** Back up the old text only when this says it is good (a valid save), so a corrupt file never replaces a good .bak. */
  isGood?: (oldText: string) => boolean;
};

export function atomicWrite(store: TextStore, name: string, text: string, opts: AtomicOptions = {}): void {
  const tmp = name + TMP_SUFFIX;
  store.write(tmp, text);
  if (store.read(tmp) !== text) throw new Error(`atomic write: ${tmp} did not read back complete`);
  if (opts.backup ?? true) {
    const old = store.read(name);
    if (old !== null && (opts.isGood ?? (() => true))(old)) store.write(name + BAK_SUFFIX, old);
  }
  store.rename(tmp, name);
}

// {{FOOTER}}
