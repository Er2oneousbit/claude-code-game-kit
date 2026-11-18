// ---------------------------------------------------------------------------
// drives.test.js
// Purpose : The scripted runs of tools/mz_drives.js (smoke --drive menus | access | crash), executed in Node against
//           stand-ins for the MZ scene classes and the Options window, to prove each one does what its header says:
//           walks every screen, turns every kit row and checks it was saved, fails when something is wrong, and
//           plants its error. NOT proof that they work in a real MZ project (smoke --drive does that, verify).
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { DRIVES, FAILS_ON_PURPOSE } = require("../tools/mz_drives.js");

// A page: requestAnimationFrame runs at once, SceneManager.goto swaps the scene on the next frame (as MZ's loop does)
function page({ failOpening = null, kitRows = 5, brokenRow = null } = {}) {
    const logs = [];
    const scenes = {};
    for (const name of ["Scene_Title", "Scene_Menu", "Scene_Item", "Scene_Skill", "Scene_Equip", "Scene_Status",
        "Scene_Options", "Scene_Save", "Scene_Load", "Scene_GameEnd"]) {
        scenes[name] = { [name]: class { constructor() { this.updated = 0; } update() { this.updated++; } } }[name];
    }
    const ConfigManager = { bgmVolume: 100, makeData: () => ({ kit: { ok: true } }) };
    const rows = ["bgmVolume"];
    for (let i = 0; i < kitRows; i++) {
        const symbol = `kitRow${i}`;
        rows.push(symbol);
        ConfigManager[symbol] = false;
    }
    const win = {
        maxItems: () => rows.length,
        commandSymbol: (i) => rows[i],
        select(i) { this.i = i; },
        processOk() {
            const symbol = rows[this.i];
            if (symbol !== brokenRow) ConfigManager[symbol] = !ConfigManager[symbol];
        },
    };
    let pending = null;
    const SceneManager = {
        _scene: null,
        goto(C) { pending = C; },
    };
    const raf = (fn) => {
        queueMicrotask(() => {
            if (pending) {
                const C = pending;
                pending = null;
                if (C.name !== failOpening) SceneManager._scene = new C();
                if (SceneManager._scene instanceof scenes.Scene_Options) SceneManager._scene._optionsWindow = win;
            }
            try {
                SceneManager._scene?.update();
            } catch (e) {
                logs.push(`pageerror ${e.message}`);   // MZ's loop reports a scene's error and carries on
            }
            fn();
        });
    };
    const context = {
        console: { log: (...a) => logs.push(a.join(" ")), error: (...a) => logs.push(a.join(" ")) },
        requestAnimationFrame: raf,
        SceneManager,
        ConfigManager,
        DataManager: { setupNewGame() {} },
        ...scenes,
    };
    vm.createContext(context);
    const run = (name) => vm.runInContext(`(${DRIVES[name].toString()})()`, context);
    return { logs, run };
}

test("menus opens every screen of MZ and says so", async () => {
    const p = page();
    await p.run("menus");
    assert.equal(p.logs.filter((l) => l.startsWith("DRIVE_SCREEN ")).length, 10);
    assert.equal(p.logs[0], "DRIVE_START menus");
    assert.equal(p.logs.at(-1), "DRIVE_DONE menus");
});

test("menus fails, naming the screen, when one does not open", async () => {
    const p = page({ failOpening: "Scene_Save" });
    await assert.rejects(p.run("menus"), /DRIVE_FAIL Scene_Save did not open/);
    assert.ok(!p.logs.includes("DRIVE_DONE menus"));
});

test("access turns every kit row once and reports each", async () => {
    const p = page();
    await p.run("access");
    const rows = p.logs.filter((l) => l.startsWith("DRIVE_ROW "));
    assert.equal(rows.length, 5, "MZ's own row is left alone");
    assert.equal(rows[0], "DRIVE_ROW kitRow0 false true");
    assert.equal(p.logs.at(-1), "DRIVE_DONE access");
});

test("access fails when a row does not change, or the kit rows are not there", async () => {
    await assert.rejects(page({ brokenRow: "kitRow2" }).run("access"), /DRIVE_FAIL kitRow2 did not change/);
    await assert.rejects(page({ kitRows: 2 }).run("access"), /only 2 kit row/);
});

test("crash plants its error in the scene's update, and names the marker dev.py looks for", async () => {
    const p = page();
    await p.run("crash");
    assert.ok(p.logs.some((l) => l.includes("pageerror") && l.includes("DRIVE_CRASH")), p.logs.join(" | "));
    assert.equal(FAILS_ON_PURPOSE.crash, "DRIVE_CRASH");
});

// {{FOOTER}}
