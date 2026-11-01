// ---------------------------------------------------------------------------
// jsonUtil.ts
// Purpose : Small helpers for JSON-shaped data shared by the settings, save and i18n modules.
// Usage   : isObject(v) narrows to a plain object (not null, not an array); deepCopy(v) clones it;
//           hasKey(obj, k) is an own-property check (JSON.parse objects inherit "toString" and friends,
//           so `k in obj` would lie).
// Notes   : No Phaser import. structuredClone exists in every supported browser and in Node 17+.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type JsonObject = Record<string, unknown>;

/** A plain JSON object: not null, not an array. */
export function isObject(v: unknown): v is JsonObject {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** A number in the JSON sense: NaN is not one (booleans never are in JS). */
export function isNum(v: unknown): v is number {
  return typeof v === "number" && !Number.isNaN(v);
}

/** Own-property test that ignores the prototype chain. */
export function hasKey(obj: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/** A deep copy of JSON-shaped data. */
export function deepCopy<T>(v: T): T {
  return structuredClone(v);
}

// {{FOOTER}}
