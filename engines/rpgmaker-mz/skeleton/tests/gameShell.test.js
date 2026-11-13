// ---------------------------------------------------------------------------
// gameShell.test.js
// Purpose : Runs every case of data/golden/shell.json through game/js/plugins/GameShell.js (settings defaults and
//           repair, effective shake, telemetry consent, rebinding, glyph sets and names, prompt bindings, narration,
//           versioned saves, translations, plurals, the pseudo-locale). Also loads the plugin the way MZ does.
// Usage   : python tools/dev.py test
// Notes   : One test per case. A case type this file does not know FAILS, so a new vector type added to
//           tools/golden_vectors.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the display_staging cases (#308)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const GameShell = require("../game/js/plugins/GameShell.js");
const { loadPlugin } = require("./support/mzFake.js");
const { expectClose, runGolden, checkedCount } = require("./support/golden.js");

const RUNNERS = {
    defaults: (c, tol) => expectClose(GameShell.defaultSettings(), c.expect, tol, "defaults"),
    settings_load: (c, tol) => {
        const { settings, problems } = GameShell.settingsLoad(c.input);
        expectClose(settings, c.expect, tol, "settings");
        expectClose(problems.length, c.problems, tol, `problems [${problems.join(", ")}]`);
        expectClose(GameShell.effectiveShake(settings), c.effective_shake, tol, "effective_shake");
        expectClose(GameShell.telemetryAllowed(settings), c.telemetry_allowed, tol, "telemetry_allowed");
    },
    rebind: (c, tol) => {
        const r = GameShell.rebind(c.bindings, c.action, c.slot, c.binding);
        expectClose({ bindings: r.bindings, conflicts: r.conflicts }, c.expect, tol, "rebind");
    },
    glyph_set: (c, tol) => {
        c.points.forEach(([setting, dev, want], i) => expectClose(GameShell.glyphSet(setting, dev), want, tol, `point ${i}`));
    },
    narration: (c, tol) => {
        c.points.forEach(([label, role, value, want], i) => expectClose(GameShell.narrationLine(label, role, value), want, tol, `point ${i}`));
    },
    glyph_name: (c, tol) => {
        c.points.forEach(([gset, b, want], i) => expectClose(GameShell.glyphName(gset, b), want, tol, `point ${i} ${gset} ${b}`));
    },
    prompt_binding: (c, tol) => {
        c.points.forEach(([a, g, want], i) => expectClose(GameShell.promptBinding(c.bindings, a, g), want, tol, `point ${i}`));
    },
    save_load: (c, tol) => {
        assert.equal(GameShell.SAVE_VERSION, c.current_version);
        const r = GameShell.saveLoad(c.primary, c.backup);
        expectClose({ envelope: r.envelope, source: r.source, problems: r.problems.length }, c.expect, tol,
                    `save_load [${r.problems.join(", ")}]`);
    },
    tr: (c, tol) => {
        c.points.forEach(([loc, key, args, want], i) => expectClose(GameShell.tr(c.tables, loc, key, args), want, tol, `point ${i} ${loc} ${key}`));
    },
    plural: (c, tol) => {
        if (typeof c.key !== "string") assert.fail("plural case without a lookup key");
        c.points.forEach(([loc, n, form, text], i) => {
            expectClose(GameShell.plural(loc, n), form, tol, `point ${i} plural(${loc}, ${n})`);
            expectClose(GameShell.trPlural(c.tables, loc, c.key, n), text, tol, `point ${i} trPlural(${loc}, ${c.key}, ${n})`);
        });
    },
    pseudo: (c, tol) => {
        c.points.forEach(([text, want], i) => expectClose(GameShell.pseudo(text), want, tol, `point ${i} ${JSON.stringify(text)}`));
    },
    display_staging: (c, tol) => {
        const st = new GameShell.DisplayStaging(c.applied);
        expectClose(GameShell.DISPLAY_CONFIRM_S, c.confirm_s, tol, "confirm_s");
        c.steps.forEach((s, i) => {
            const [kind, ...args] = s.op;
            let out = null, calls = [];
            if (kind === "stage") out = st.stage(...args);
            else if (kind === "apply") calls = st.apply();
            else if (kind === "tick") calls = st.tick(...args);
            else if (kind === "keep") st.keep();
            else if (kind === "revert") calls = st.revert();
            else if (kind === "back") [out, calls] = st.back();
            else assert.fail(`step ${i}: unknown op ${kind}`);
            const shown = {};
            for (const f of GameShell.DISPLAY_APPLY_ORDER) shown[f] = st.value(f);
            expectClose({ out, calls, pending: st.pending, shown, applied: st.applied, seconds: st.seconds() },
                        { out: s.out, calls: s.calls, pending: s.pending, shown: s.shown, applied: s.applied, seconds: s.seconds },
                        tol, `step ${i} ${JSON.stringify(s.op)}`);
        });
    },
};

const { golden, run } = runGolden(test, "shell.json", RUNNERS);

test("shell.json: the save version the vectors were written for is this file's", () => {
    assert.equal(GameShell.SAVE_VERSION, golden.save_version);
});

test("a case type with no runner fails instead of passing silently", () => {
    assert.throws(() => run({ type: "shell_made_up", name: "x" }), /unknown case type/);
});

test("a save written by saveText loads back as the newest version from the primary file", () => {
    const r = GameShell.saveLoad(GameShell.saveText({ health: 3 }), null);
    assert.equal(r.source, "primary");
    assert.deepEqual(r.envelope.data, { health: 3 });
    assert.equal(r.envelope.version, GameShell.SAVE_VERSION);
});

test("settings text round-trips through settingsLoad with nothing to repair", () => {
    const s = GameShell.defaultSettings();
    s.access.reduce_motion = true;
    const back = GameShell.settingsLoad(GameShell.settingsText(s));
    assert.deepEqual(back.problems, []);
    assert.equal(GameShell.effectiveShake(back.settings), 0);
});

test("GameShell loads as an MZ plugin (no module, no require): it sets the global and logs nothing", () => {
    const mz = loadPlugin("GameShell");
    assert.equal(typeof mz.context.GameShell.settingsLoad, "function");
    assert.deepEqual(mz.logs, []);
});

// Runs last (node:test runs a file's tests in order): zero values means the vectors never reached the rules
test("golden values were checked", (t) => {
    assert.ok(checkedCount() > 0, "no golden values were compared");
    t.diagnostic(`checked ${checkedCount()} golden values from shell.json`);
});

// {{FOOTER}}
