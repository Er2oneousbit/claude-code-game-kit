// ---------------------------------------------------------------------------
// golden.ts
// Purpose : Test helpers for the golden vectors: load data/golden/<file>.json from disk at test time and
//           compare results with the expected values structurally.
// Usage   : const g = loadGolden("juice.json") ; expectClose(actual, expected, g.tolerance, "case/step 3")
// Notes   : The vectors are written by tools/golden_vectors.py (the reference implementation) and shared by
//           every engine of the kit: never copy expected values into a test. Comparison rules: numbers within
//           the file's absolute tolerance (an int 0 equals 0.0), arrays in order, objects as key sets,
//           everything else exactly.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export type GoldenCase = { type: string; name: string; [k: string]: any };
export type GoldenFile = { version: number; tolerance: number; cases: GoldenCase[]; [k: string]: any };

export const GOLDEN_DIR = fileURLToPath(new URL("../../data/golden/", import.meta.url));

export function loadGolden(file: string): GoldenFile {
  const data = JSON.parse(readFileSync(GOLDEN_DIR + file, "utf-8")) as GoldenFile;
  if (!Array.isArray(data.cases) || typeof data.tolerance !== "number") throw new Error(`${file}: not a golden vector file`);
  return data;
}

/** The first difference between actual and expected as "path: why", or null when they match. */
export function diff(actual: unknown, expected: unknown, tol: number, path = "$"): string | null {
  if (typeof expected === "number") {
    if (typeof actual !== "number") return `${path}: expected number ${expected}, got ${JSON.stringify(actual)}`;
    return Math.abs(actual - expected) <= tol ? null : `${path}: expected ${expected}, got ${actual}`;
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) return `${path}: expected an array, got ${JSON.stringify(actual)}`;
    if (actual.length !== expected.length) return `${path}: expected ${expected.length} items, got ${actual.length}`;
    for (let i = 0; i < expected.length; i++) {
      const d = diff(actual[i], expected[i], tol, `${path}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  if (expected !== null && typeof expected === "object") {
    if (actual === null || typeof actual !== "object" || Array.isArray(actual)) return `${path}: expected an object, got ${JSON.stringify(actual)}`;
    const ek = Object.keys(expected).sort();
    const ak = Object.keys(actual).sort();
    if (ek.join("\u0000") !== ak.join("\u0000")) return `${path}: keys differ: expected [${ek}], got [${ak}]`;
    for (const k of ek) {
      const d = diff((actual as Record<string, unknown>)[k], (expected as Record<string, unknown>)[k], tol, `${path}.${k}`);
      if (d) return d;
    }
    return null;
  }
  return actual === expected ? null : `${path}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
}

/** Throws with the first difference (the test runner prints it). */
export function expectClose(actual: unknown, expected: unknown, tol: number, where: string): void {
  const d = diff(actual, expected, tol);
  if (d) throw new Error(`${where}: ${d}`);
}
