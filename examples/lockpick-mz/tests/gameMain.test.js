// ---------------------------------------------------------------------------
// gameMain.test.js
// Purpose : The MZ glue in game/js/plugins/GameMain.js, run with stand-ins for RPG Maker (tests/support/mzFake.js):
//           the Open Lock command, the scene played by both bots to the end (markers, the result switch, the pop),
//           the title demo command, ?autoplay, and the boot marker.
// Usage   : python tools/dev.py test
// Notes   : Fakes, not MZ: this proves the glue does what it means to. `smoke` is what runs it in the real engine.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const LockpickCore = require("../game/js/plugins/GameCore.js");
const { loadPlugin } = require("./support/mzFake.js");

const load = (params = { titleDemo: "true" }, location = { search: "" }) => loadPlugin("GameMain", { LockpickCore }, params, location);

test("Open Lock is registered, clamps its arguments and opens the scene", () => {
    const mz = load();
    assert.ok(mz.commands.has("OpenLock"));
    mz.commands.get("OpenLock")({ pins: "9", zone: "2", seed: "11", switchId: "5" });   // MZ passes strings
    assert.equal(mz.scenes.stack.length, 1);
    const [config] = mz.scenes.prepared;
    assert.equal(config.pins, 6, "at most 6 pins");
    assert.equal(config.zone, 0.05, "at least a 5% sweet spot");
    assert.equal(config.seed, 11);
    assert.equal(config.switchId, 5);
});

test("a careful bot opens the lock: LOCK_OPEN, the switch ON, the scene closes", () => {
    const mz = load();
    mz.commands.get("OpenLock")({ pins: "3", zone: "16", seed: "8", switchId: "5" });
    mz.scenes.prepared[0].bot = "timer";
    const scene = mz.runScene();
    assert.equal(scene._lock.state, "open");
    assert.ok(mz.logs.some((l) => l.startsWith("LOCK_OPEN seed=8")), mz.logs.join("\n"));
    assert.equal(mz.switches.get(5), true);
    assert.equal(mz.scenes.pops, 1, "the scene closed itself");
    assert.ok(!mz.logs.some((l) => l.startsWith("ERROR")), mz.logs.join("\n"));
});

test("a masher jams the lock: LOCK_JAMMED and the switch OFF", () => {
    const mz = load();
    mz.commands.get("OpenLock")({ pins: "3", zone: "16", seed: "8", switchId: "5" });
    mz.scenes.prepared[0].bot = "masher";
    mz.runScene();
    assert.ok(mz.logs.some((l) => l.startsWith("LOCK_JAMMED")), mz.logs.join("\n"));
    assert.equal(mz.switches.get(5), false);
});

test("a player's OK press sets a pin when the pick is in the spot", () => {
    const mz = load();
    mz.commands.get("OpenLock")({ pins: "2", zone: "16", seed: "3", switchId: "0" });
    const Cls = mz.scenes.stack[0];
    const scene = new Cls();
    scene.prepare(...mz.scenes.prepared);
    scene.create();
    scene._lock.pick = LockpickCore.spot(scene._lock).center - scene._lock.speed / 60;   // one frame short of the middle
    mz.input.ok = true;
    scene.update();
    assert.equal(scene._lock.pin, 1, mz.logs.join("\n"));
    assert.ok(mz.logs.includes("LOCK_SET 1"));
});

test("the title gets a Pick a lock command that opens the scene", () => {
    const mz = load();
    const win = new mz.context.Window_TitleCommand();
    win.makeCommandList();
    assert.deepEqual(win.list.map((c) => c.symbol), ["newGame", "continue", "options", "lockpick"]);
    const title = new mz.context.Scene_Title();
    title.createCommandWindow();
    title._commandWindow.handlers.lockpick();
    assert.equal(mz.scenes.stack.length, 1);
});

test("the title demo can be turned off", () => {
    const mz = load({ titleDemo: "false" });
    const win = new mz.context.Window_TitleCommand();
    win.makeCommandList();
    assert.ok(!win.list.some((c) => c.symbol === "lockpick"));
});

test("BOOT_OK once; ?autoplay starts a careful bot on the demo lock", () => {
    const mz = load({ titleDemo: "true" }, { search: "?autoplay" });
    new mz.context.Scene_Title().start();
    new mz.context.Scene_Title().start();
    assert.equal(mz.logs.filter((l) => l.startsWith("BOOT_OK")).length, 1);
    assert.equal(mz.scenes.stack.length, 1, "autoplay pushed the scene once");
    assert.equal(mz.scenes.prepared[0].bot, "timer");
    mz.runScene();
    assert.ok(mz.logs.some((l) => l.startsWith("LOCK_OPEN")), mz.logs.join("\n"));
});

test("?autoplay=masher picks the masher", () => {
    const mz = load({ titleDemo: "true" }, { search: "?autoplay=masher" });
    new mz.context.Scene_Title().start();
    assert.equal(mz.scenes.prepared[0].bot, "masher");
});
