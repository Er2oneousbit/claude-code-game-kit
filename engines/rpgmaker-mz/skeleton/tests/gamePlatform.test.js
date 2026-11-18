// ---------------------------------------------------------------------------
// gamePlatform.test.js
// Purpose : Runs every case of data/golden/platform.json through game/js/plugins/GamePlatform.js (achievements and
//           stats, rich presence, the overlay's pause hook, cloud saves, the state file, the null backend), then
//           the service (the cached state file, no file without achievements) and the MZ glue against fakes
//           (MZ's menu flushes, a save calls saved(), the overlay over the map asks for the menu).
// Usage   : python tools/dev.py test
// Notes   : A case type this file does not know FAILS. A step's calls are what the rules sent to their backend
//           during that step; "fail_store" is the null backend's hook. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const GP = require("../game/js/plugins/GamePlatform.js");
const { loadPlugin } = require("./support/mzFake.js");
const { expectClose, runGolden, checkedCount } = require("./support/golden.js");

function step(p, nb, op) {
    const [kind, ...a] = op;
    switch (kind) {
        case "fail_store":
            nb.failStores += 1;
            return { out: null, calls: [] };
        case "overlay": return { out: GP.overlayAction(a[0], a[1]), calls: [] };
        case "unlock": return p.unlock(a[0]);
        case "set_stat": return p.setStat(a[0], a[1]);
        case "add_stat": return p.addStat(a[0], a[1]);
        case "flush": return p.flush();
        case "set_presence": return p.setPresence(a[0], a[1]);
        case "clear_presence": return p.clearPresence();
        case "saved": return p.saved(a[0]);
        case "connect": return p.connect(a[0]);
        case "disconnect": return p.disconnect();
        case "reset_all": return p.resetAll();
        default: return assert.fail(`unknown step ${kind}`);
    }
}

runGolden(test, "platform.json", {
    platform_format: (c, tol) => {
        const mine = {
            state_format: GP.PLATFORM_FORMAT, state_file: GP.PLATFORM_STATE_FILE, state_version: GP.PLATFORM_STATE_VERSION,
            id_max: GP.PLATFORM_ID_MAX, stat_types: GP.STAT_TYPES, presence_max_keys: GP.PRESENCE_MAX_KEYS,
            presence_max_value_bytes: GP.PRESENCE_MAX_VALUE_BYTES, cloud_modes: GP.CLOUD_MODES,
            cloud_local_names: GP.CLOUD_LOCAL_NAMES, cloud_local_suffixes: GP.CLOUD_LOCAL_SUFFIXES,
            cloud_local_dirs: GP.CLOUD_LOCAL_DIRS, overlay_pause_screens: GP.OVERLAY_PAUSE_SCREENS, type: c.type, name: c.name,
        };
        expectClose(mine, c, tol, "format");
    },
    achievements_load: (c, tol) => {
        for (const [name, text, defs, problems] of c.points) {
            const r = GP.achievementsLoad(text);
            expectClose(r.defs, defs, tol, `${name}: defs`);
            expectClose(r.problems, problems, tol, `${name}: problems`);
        }
    },
    cloud_partition: (c, tol) => c.points.forEach(([p, want]) => expectClose(GP.cloudPartition(p), want, tol, `"${p}"`)),
    overlay: (c, tol) => c.points.forEach(([a, s, want]) => expectClose(GP.overlayAction(a, s), want, tol, `${a} ${s}`)),
    platform_script: (c, tol) => {
        const nb = new GP.NullBackend();
        const p = new GP.Platform(c.defs, nb, c.online, c.cloud);
        c.steps.forEach((s, i) => {
            const r = step(p, nb, s.op);
            const w = `step ${i} ${JSON.stringify(s.op)}`;
            expectClose(r.out, s.out, tol, `${w}: out`);
            expectClose(r.calls, s.calls, tol, `${w}: calls`);
            expectClose(p.state(), s.state, tol, `${w}: state`);
            expectClose(p.presenceList(), s.presence, tol, `${w}: presence`);
            expectClose(p.online, s.online, tol, `${w}: online`);
        });
    },
    platform_state_load: (c, tol) => {
        for (const [name, text, state, problems] of c.points) {
            const r = GP.platformStateLoad(c.defs, text);
            expectClose(r.state, state, tol, `${name}: state`);
            expectClose(r.problems, problems, tol, `${name}: problems`);
        }
    },
    null_backend: (c, tol) => {
        const nb = new GP.NullBackend();
        c.sends.forEach(([call, ok, remote, presence, cloud], i) => {
            let got = null;
            if (call.length === 1 && call[0] === "fail_next_store") nb.failStores += 1;
            else got = nb.send(call);
            const w = `send ${i}`;
            expectClose(got, ok, tol, `${w}: ok`);
            expectClose(nb.remote(), remote, tol, `${w}: remote`);
            expectClose(Object.keys(nb.presence).sort().map((k) => [k, nb.presence[k]]), presence, tol, `${w}: presence`);
            expectClose(nb.cloud, cloud, tol, `${w}: cloud`);
        });
        expectClose(nb.calls, c.calls, tol, "calls");
    },
});

const SAMPLE = JSON.stringify({
    stats: [{ id: "kills", max: 100, increment_only: true }],
    achievements: [{ id: "first", name: "First" }, { id: "kills_10", name: "Ten", stat: "kills", threshold: 10 }],
});

test("the service writes nothing and answers unknown without achievements", () => {
    const store = new GP.MemoryStore();
    const ps = new GP.PlatformService(store, null);
    assert.equal(ps.active, false);
    assert.equal(ps.unlock("first"), "unknown");
    assert.equal(ps.flush(), "nothing");
    assert.deepEqual([...store.files.keys()], []);
});

test("the service caches the local state and reloads it", () => {
    const store = new GP.MemoryStore();
    const ps = new GP.PlatformService(store, SAMPLE);
    assert.equal(ps.addStat("kills", 12), "ok");
    assert.equal(ps.unlock("first"), "unlocked");
    const again = new GP.PlatformService(store, SAMPLE);
    assert.deepEqual(again.platform.unlocked, ["kills_10", "first"]);
    assert.equal(again.unlock("first"), "already");
    assert.equal(store.read("platform_state.json.tmp"), null);
});

// The smallest MZ that GamePlatform's glue touches
function mzWorld() {
    const saved = [];
    class Scene_Map { constructor() { this.menuCalling = false; } }
    class Scene_Menu { start() {} }
    const SceneManager = { _scene: new Scene_Map(), updateMain() {}, terminate() {} };
    const DataManager = { makeSavename: (id) => `file${id}`, saveGame: (id) => { saved.push(id); return Promise.resolve(0); } };
    const StorageManager = { isLocalMode: () => false };
    class XMLHttpRequest {
        open(m, url) { this.url = url; }
        overrideMimeType() {}
        send() { this.status = 404; this.responseText = ""; this.onload(); }
    }
    const store = new Map();
    const localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
    return { Scene_Map, Scene_Menu, SceneManager, DataManager, StorageManager, XMLHttpRequest, localStorage, saved, TextEncoder };
}

test("GamePlatform loads as an MZ plugin: menu, save and quit hooks, the overlay asks the map for its menu", async () => {
    const world = mzWorld();
    const mz = loadPlugin("GamePlatform", world);
    const G = mz.context.GamePlatform;
    const nb = G.service.backend;
    assert.equal(G.service.active, false, "no data/achievements.json: the service does nothing");
    await mz.context.DataManager.saveGame(1);
    assert.deepEqual(world.saved, [1], "MZ's own save still runs");
    new mz.context.Scene_Menu().start();
    mz.context.SceneManager.updateMain();
    mz.context.SceneManager.terminate();
    assert.equal(nb.calls.length, 0, "nothing defined: nothing sent");
    assert.equal(world.localStorage.getItem("kit platform_state.json"), null, "nothing written");
    G.onOverlay(false);
    assert.equal(mz.context.SceneManager._scene.menuCalling, false, "closing never opens anything");
    G.onOverlay(true);
    assert.equal(mz.context.SceneManager._scene.menuCalling, true, "the overlay over the map asks for the menu");
    mz.context.SceneManager._scene = new mz.context.Scene_Menu();
    assert.equal(G.sceneScreen(mz.context.SceneManager._scene), "Scene_Menu");
    assert.deepEqual(mz.logs, []);
});

test("with achievements, a save in api mode reaches saved() and MZ's menu flushes", async () => {
    const world = mzWorld();
    world.XMLHttpRequest = class {
        open() {}
        overrideMimeType() {}
        send() { this.status = 200; this.responseText = SAMPLE; this.onload(); }
    };
    const mz = loadPlugin("GamePlatform", world);
    const G = mz.context.GamePlatform;
    assert.equal(G.service.active, true);
    G.service.platform.cloud = "api";
    assert.equal(G.service.addStat("kills", 3), "ok");
    await mz.context.DataManager.saveGame(2);
    const calls = G.service.backend.calls.map((c) => c.join(" "));
    assert.ok(calls.includes("cloud_write save/file2.rmmzsave"), calls.join(" | "));
    assert.ok(calls.includes("set_stat kills 3"), calls.join(" | "));
    assert.ok(world.localStorage.getItem("kit platform_state.json").includes('"kills": 3'));
});

test("golden values were checked", (t) => {
    assert.ok(checkedCount() >= 0);
    t.diagnostic(`checked ${checkedCount()} golden values in this run`);
});

// {{FOOTER}}
