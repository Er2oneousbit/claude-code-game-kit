// ---------------------------------------------------------------------------
// rng.ts
// Purpose : Seeded random numbers, so every AI choice can be replayed (SOP-14 step 3).
// Usage   : const rng = new Rng(42); rng.next() in [0, 1); rng.int(0, 9); rng.pick(list)
// Notes   : mulberry32: tiny, fast, good enough for games. Not for security.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export class Rng {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  /** Float in [0, 1). */
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  /** Integer in [min, max], both inclusive. */
  int(min: number, max: number): number {
    return min + Math.floor(this.next() * (max - min + 1));
  }

  pick<T>(items: readonly T[]): T {
    if (items.length === 0) throw new Error("Rng.pick on an empty list");
    return items[this.int(0, items.length - 1)];
  }
}
