// ---------------------------------------------------------------------------
// gameMain.test.js
// Purpose : The MZ glue in game/js/plugins/GameMain.js, loaded with stand-ins for RPG Maker (tests/support/mzFake.js):
//           it registers its command, the command uses the rules, and the title screen logs the boot marker once.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const GameCore = require("../game/js/plugins/GameCore.js");
const { loadPlugin } = require("./support/mzFake.js");

test("Log Phase is registered and uses the rules", () => {
    const mz = loadPlugin("GameMain", { GameCore }, { startMinutes: "480" });
    assert.ok(mz.commands.has("LogPhase"));
    mz.commands.get("LogPhase")({ minutes: "1100" });      // MZ passes arguments as strings
    assert.ok(mz.logs.some((l) => l.includes("dusk")), mz.logs.join("\n"));
});

test("the title screen logs BOOT_OK once", () => {
    const mz = loadPlugin("GameMain", { GameCore }, { startMinutes: "480" });
    new mz.Scene_Title().start();
    new mz.Scene_Title().start();
    assert.equal(mz.logs.filter((l) => l.startsWith("BOOT_OK")).length, 1, mz.logs.join("\n"));
});

// {{FOOTER}}
