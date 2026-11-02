// ---------------------------------------------------------------------------
// gameAudio.test.js
// Purpose : Runs every case of the kit's audio golden vectors through game/js/plugins/GameAudio.js:
//           data/golden/audio.json (audio director), music.json (music director), access.json (slider gains per
//           bus, caption arrows). Also loads the plugin the way MZ does (no `module`) to prove the global is set.
// Usage   : python tools/dev.py test              (the count of values checked: python tools/dev.py --debug test)
// Notes   : One test per case and one runner per case type. A case type this file does not know FAILS, so a new
//           vector type added to tools/audio/wavesmith/ cannot be skipped silently. Expected values and tolerances
//           come only from the JSON (written by tools/audio/wavesmith/audio_events.py, music.py, access.py): never
//           copy them in here. Comparison: numbers within the file's tolerance, arrays in order, objects with the
//           same keys, everything else exactly. These tests prove the rules, not RPG Maker MZ's playback.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const GameAudio = require("../game/js/plugins/GameAudio.js");
const { loadPlugin } = require("./support/mzFake.js");

// The kit's core lands at the game's root, so the vectors sit beside tests/ (not in game/data, MZ's database)
const GOLDEN_DIR = path.resolve(__dirname, "..", "data", "golden");
const SPEC = "tools/audio/wavesmith/";
let checked = 0;                        // leaf values compared, reported by the last test

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
    checked++;                          // strings, null, booleans: exactly
    return actual === expected ? null : `${where}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
}

function expectClose(actual, expected, tol, where) {
    const d = diff(actual, expected, tol);
    if (d) assert.fail(`${where}: ${d}`);
}

// ---- One runner per case type, per golden file --------------------------------------------------------------
const RUNNERS = {
    "audio.json": {
        audio_director: (c, tol) => {
            const d = new GameAudio.AudioDirector(c.params);
            c.steps.forEach((step, i) => {
                if (step.call === "play") return expectClose(d.play(step.event, step.t_ms), step.expect, tol, `step ${i}`);
                if (step.call === "duck") return expectClose(d.duck(step.t_ms), step.expect, tol, `step ${i}`);
                return assert.fail(`step ${i}: unknown call "${step.call}"`);
            });
        },
    },
    "music.json": {
        music_grid: (c, tol) => {
            c.steps.forEach((s, i) => expectClose(GameAudio.beatSample(s.k, s.bpm, s.rate), s.sample, tol, `step ${i}`));
        },
        music_plan: (c, tol) => {
            c.steps.forEach((s, i) => {
                const plan = GameAudio.planTransition(c.params, s.from, s.since, s.entry, s.to, s.now);
                expectClose(plan, s.expect, tol, `step ${i} (${s.from} -> ${s.to} at ${s.now})`);
            });
        },
    },
    "access.json": {
        access_gains: (c, tol) => {
            c.steps.forEach((s, i) => expectClose(GameAudio.userBusGains(s.buses, s.sliders), s.expect, tol, `step ${i}`));
        },
        access_arrow: (c, tol) => {
            c.steps.forEach((s, i) => {
                const where = `step ${i} (${s.dx}, ${s.dy})`;
                expectClose(GameAudio.captionDirection(s.dx, s.dy, s.half_w, s.half_h), s.dir, tol, where);
                expectClose(GameAudio.captionArrow(s.dx, s.dy, s.half_w, s.half_h), s.arrow, tol, where);
            });
        },
    },
};

// Own keys only, so a case type such as "constructor" is unknown too
function runCase(file, c, tol) {
    const runners = RUNNERS[file];
    if (!Object.prototype.hasOwnProperty.call(runners, c.type)) {
        assert.fail(`${file}: unknown case type "${c.type}": add a runner for it (${SPEC} is the spec)`);
    }
    runners[c.type](c, tol);
}

for (const file of Object.keys(RUNNERS)) {
    const golden = loadGolden(file);
    test(`${file} has cases`, () => assert.ok(golden.cases.length > 0, `${file} has no cases`));
    for (const c of golden.cases) {
        test(`${file} ${c.type}: ${c.name}`, () => runCase(file, c, golden.tolerance));
    }
}

test("access.json: the arrows are the same eight, in the same order", () => {
    const golden = loadGolden("access.json");
    expectClose(GameAudio.ARROWS, golden.arrows, 0, "arrows");
});

test("a case type with no runner fails instead of passing silently", () => {
    assert.throws(() => runCase("music.json", { type: "music_made_up", name: "x", steps: [] }, 0), /unknown case type/);
});

test("GameAudio loads as an MZ plugin (no module, no require): it sets the global and logs nothing", () => {
    const mz = loadPlugin("GameAudio");
    assert.equal(typeof mz.context.GameAudio, "object");
    assert.equal(typeof mz.context.GameAudio.AudioDirector, "function");
    assert.deepEqual(mz.logs, []);
});

// Runs last (node:test runs a file's tests in order): zero values means the vectors never reached the rules
test("golden values were checked", (t) => {
    assert.ok(checked > 0, "no golden values were compared");
    t.diagnostic(`checked ${checked} golden values from audio.json, music.json and access.json`);
});

// {{FOOTER}}
