// ---------------------------------------------------------------------------
// golden.js
// Purpose : Test helpers for the kit's golden vectors: load data/golden/<file>.json at test time and compare results
//           with the expected values structurally, counting the values compared.
// Usage   : const { loadGolden, expectClose, checkedCount } = require("./support/golden.js");
//           const g = loadGolden("juice.json"); expectClose(actual, expected, g.tolerance, "case/step 3");
// Notes   : The vectors are written by tools/golden_vectors.py (the reference) and shared by every engine of the kit:
//           never copy expected values into a test. Comparison: numbers within the file's absolute tolerance, arrays
//           in order, objects with the same keys, everything else exactly. The core lands at the game's root, so
//           the vectors sit beside tests/ (not in game/data, MZ's database).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const GOLDEN_DIR = path.resolve(__dirname, "..", "..", "data", "golden");
let checked = 0;   // leaf values compared

function loadGolden(file) {
    const full = path.join(GOLDEN_DIR, file);
    if (!fs.existsSync(full)) throw new Error(`${full} is missing: the kit's core puts data/golden/ in every game`);
    const data = JSON.parse(fs.readFileSync(full, "utf8"));
    if (!Array.isArray(data.cases) || typeof data.tolerance !== "number") throw new Error(`${file}: not a golden vector file`);
    return data;
}

// The first difference between actual and expected as "path: why", or null when they match
function diff(actual, expected, tol, where = "$") {
    if (typeof expected === "number") {
        checked++;
        if (typeof actual !== "number") return `${where}: expected number ${expected}, got ${JSON.stringify(actual)}`;
        return Math.abs(actual - expected) <= tol ? null : `${where}: expected ${expected}, got ${actual}`;
    }
    if (Array.isArray(expected)) {
        if (!Array.isArray(actual)) return `${where}: expected an array, got ${JSON.stringify(actual)}`;
        if (actual.length !== expected.length) return `${where}: expected ${expected.length} items, got ${actual.length}`;
        for (let i = 0; i < expected.length; i++) {
            const d = diff(actual[i], expected[i], tol, `${where}[${i}]`);
            if (d) return d;
        }
        return null;
    }
    if (expected !== null && typeof expected === "object") {
        if (actual === null || typeof actual !== "object" || Array.isArray(actual)) {
            return `${where}: expected an object, got ${JSON.stringify(actual)}`;
        }
        const ek = Object.keys(expected).sort();
        const ak = Object.keys(actual).sort();
        if (ek.join("\u0000") !== ak.join("\u0000")) return `${where}: keys differ: expected [${ek}], got [${ak}]`;
        for (const k of ek) {
            const d = diff(actual[k], expected[k], tol, `${where}.${k}`);
            if (d) return d;
        }
        return null;
    }
    checked++;   // strings, null, booleans: exactly
    return actual === expected ? null : `${where}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
}

function expectClose(actual, expected, tol, where) {
    const d = diff(actual, expected, tol);
    if (d) assert.fail(`${where}: ${d}`);
}

// Runs every case of golden through runners (type -> fn(case, tol)) as one node:test test each; an unknown type FAILS
function runGolden(test, file, runners, spec = "tools/golden_vectors.py") {
    const golden = loadGolden(file);
    const run = (c) => {
        if (!Object.prototype.hasOwnProperty.call(runners, c.type)) {
            assert.fail(`${file}: unknown case type "${c.type}": add a runner for it (${spec} is the spec)`);
        }
        runners[c.type](c, golden.tolerance);
    };
    test(`${file} has cases`, () => assert.ok(golden.cases.length > 0, `${file} has no cases`));
    for (const c of golden.cases) test(`${file} ${c.type}: ${c.name}`, () => run(c));
    return { golden, run };
}

module.exports = { GOLDEN_DIR, loadGolden, diff, expectClose, runGolden, checkedCount: () => checked };
