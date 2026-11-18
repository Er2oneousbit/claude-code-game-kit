// ---------------------------------------------------------------------------
// gameAccess.test.js
// Purpose : The MZ glue in game/js/plugins/GameAccess.js, loaded with stand-ins for the MZ classes it hooks
//           (ConfigManager, Window_Options, Scene_Options, Game_Screen, Game_System): the settings round-trip
//           through MZ's config data and are repaired on load, the Options rows step and show their values, Shake
//           Screen follows reduce motion and the shake scale, Flash Screen goes through the limiter and is gentler
//           with flash_limit on, and text size scales the font.
// Usage   : python tools/dev.py test
// Notes   : The stand-ins copy the few MZ 1.x methods the hooks wrap, as the kit knows them; they prove the plugin
//           calls what it means, not that RPG Maker MZ behaves the same (smoke or a test play does that).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Sonnet 5.5, claude-sonnet-5-5): battle animation flashes, window line height, the Line
//           Spacing row and extraRows, and the kit's version in MZ's save contents (#280)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): the Blood and Clean Language rows write content.*
//           and their Show parameters hide them (#171, #207)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const GameJuice = require("../game/js/plugins/GameJuice.js");
const GameShell = require("../game/js/plugins/GameShell.js");
const { loadPlugin } = require("./support/mzFake.js");

const MZ_LINE_HEIGHT = 36;   // Window_Base.lineHeight in MZ 1.x
const MZ_OPTIONS = 7;        // Scene_Options.maxCommands in MZ 1.x
const MZ_FONT_SIZE = 26;     // $dataSystem.advanced.fontSize of a new MZ project

// Stand-ins for the MZ classes GameAccess hooks: the methods it wraps, doing what MZ's do
function mzClasses() {
    const ConfigManager = {
        bgmVolume: 100,
        makeData() {
            return { bgmVolume: this.bgmVolume };
        },
        applyData(config) {
            this.bgmVolume = "bgmVolume" in config ? Number(config.bgmVolume) : 100;
        },
    };
    class Window_Options {
        constructor() {
            this.list = [];
            this._index = 0;
            this.sounds = 0;
            this.makeCommandList();
        }
        makeCommandList() {
            this.addCommand("BGM Volume", "bgmVolume");
        }
        addCommand(name, symbol) {
            this.list.push({ name, symbol });
        }
        commandSymbol(index) {
            return this.list[index].symbol;
        }
        index() {
            return this._index;
        }
        select(symbol) {
            this._index = this.list.findIndex((c) => c.symbol === symbol);
        }
        getConfigValue(symbol) {
            return ConfigManager[symbol];
        }
        setConfigValue(symbol, value) {
            ConfigManager[symbol] = value;
        }
        changeValue(symbol, value) {
            if (this.getConfigValue(symbol) !== value) {
                this.setConfigValue(symbol, value);
                this.sounds++;
            }
        }
        booleanStatusText(value) {
            return value ? "ON" : "OFF";
        }
        statusText(index) {
            return `${this.getConfigValue(this.commandSymbol(index))}%`;
        }
        processOk() {
            this.mzOk = true;
        }
        cursorRight() {
            this.mzRight = true;
        }
        cursorLeft() {
            this.mzLeft = true;
        }
    }
    class Scene_Options {
        maxCommands() {
            return MZ_OPTIONS;
        }
    }
    class Game_Screen {
        startShake(power, speed, duration) {
            this.shake = [power, speed, duration];
        }
        startFlash(color, duration) {
            this.flash = [color, duration];
        }
    }
    class Game_System {
        mainFontSize() {
            return MZ_FONT_SIZE;
        }
    }
    class Window_Base {
        lineHeight() {
            return MZ_LINE_HEIGHT;
        }
    }
    // MZ's Sprite_Animation sets a new _flashColor array and _flashDuration at a flash timing's frame
    class Sprite_Animation {
        constructor(timings) {
            this._timings = timings;
            this._frameIndex = 0;
            this._flashColor = [0, 0, 0, 0];
            this._flashDuration = 0;
        }
        processFlashTimings() {
            for (const t of this._timings) {
                if (t.frame === this._frameIndex) {
                    this._flashColor = t.color.slice();
                    this._flashDuration = t.duration;
                }
            }
        }
    }
    class Sprite_AnimationMV {
        startFlash(color, duration) {
            (this.flashes ||= []).push(["target", color, duration]);
        }
        startScreenFlash(color, duration) {
            (this.flashes ||= []).push(["screen", color, duration]);
        }
    }
    const DataManager = {
        makeSaveContents() {
            return { party: { gold: 5 } };
        },
        extractSaveContents(contents) {
            this.extracted = contents;
        },
    };
    return { ConfigManager, Window_Options, Scene_Options, Game_Screen, Game_System, Window_Base, Sprite_Animation,
             Sprite_AnimationMV, DataManager };
}

function load(params = {}) {
    const mz = loadPlugin("GameAccess", { GameJuice, GameShell, ...mzClasses() }, params);
    return { ...mz, c: mz.context };
}

test("the settings ride in MZ's config data and are repaired on load", () => {
    const { c, logs } = load();
    c.ConfigManager.applyData({ bgmVolume: 40, kit: { access: { reduce_motion: true, shake_scale: 7 }, mine: 1 } });
    assert.equal(c.ConfigManager.bgmVolume, 40, "MZ's own options still load");
    const s = c.GameAccess.settings();
    assert.equal(s.access.reduce_motion, true);
    assert.equal(s.access.shake_scale, 1, "an out-of-range value is clamped");
    assert.equal(s.mine, 1, "unknown keys stay");
    assert.ok(logs.some((l) => l.includes("settings repaired")), logs.join("\n"));
    const saved = c.ConfigManager.makeData();
    assert.equal(saved.bgmVolume, 40);
    assert.equal(saved.kit.access.reduce_motion, true);
    c.ConfigManager.applyData({});                      // a first run: no kit key, defaults, nothing logged
    assert.deepEqual(c.GameAccess.settings(), GameShell.defaultSettings());
});

test("the Options screen gets the seven rows after MZ's, and room for them", () => {
    const { c } = load({ shakeText: "Tremblement" });
    const w = new c.Window_Options();
    assert.deepEqual(w.list.map((x) => x.symbol), ["bgmVolume", "kitReduceMotion", "kitShakeScale", "kitFlashLimit",
        "kitTextScale", "kitLineSpacing", "kitBlood", "kitCleanLanguage"]);
    assert.equal(w.list[2].name, "Tremblement", "labels are plugin parameters");
    assert.equal(new c.Scene_Options().maxCommands(), MZ_OPTIONS + 7);
});

test("Blood and Clean Language write content.*, and a game can hide either (#171, #207)", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const w = new c.Window_Options();
    w.select("kitBlood");
    assert.equal(w.statusText(w.index()), "ON");
    w.processOk();
    assert.equal(c.GameAccess.settings().content.blood, false);
    assert.equal(GameShell.bloodEnabled(c.GameAccess.settings()), false);
    w.select("kitCleanLanguage");
    w.cursorRight();
    assert.equal(GameShell.cleanLanguage(c.GameAccess.settings()), true);
    assert.equal(c.ConfigManager.makeData().kit.content.clean_language, true, "saved with the rest");
    const hidden = new (load({ showBlood: "false", showCleanLanguage: "false" }).c.Window_Options)();
    assert.ok(!hidden.list.some((x) => x.symbol === "kitBlood" || x.symbol === "kitCleanLanguage"));
});

test("extraRows adds on/off rows a game asked for, reports unknown names", () => {
    const { c, logs } = load({ extraRows: '["subtitles", "hold_to_toggle", "nonsense"]' });
    const w = new c.Window_Options();
    assert.deepEqual(w.list.slice(-2).map((x) => [x.symbol, x.name]), [["kitSubtitles", "Subtitles"], ["kitHoldToToggle", "Hold To Toggle"]]);
    assert.equal(new c.Scene_Options().maxCommands(), MZ_OPTIONS + 9);
    assert.ok(logs.some((l) => l.includes('"nonsense" is not one of')), logs.join("\n"));
    const was = c.GameAccess.settings().access.subtitles;
    w.select("kitSubtitles");
    w.processOk();
    assert.equal(c.GameAccess.settings().access.subtitles, !was, "the row writes the setting the game reads");
    assert.deepEqual(load({ extraRows: "narration, narration" }).c.GameAccess.OPTIONS.filter((o) => o.field === "narration").length, 1);
});

test("rows step and show their values; MZ's own rows keep MZ's behavior", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const w = new c.Window_Options();
    w.select("kitReduceMotion");
    assert.equal(w.statusText(w.index()), "OFF");
    w.processOk();
    assert.equal(c.ConfigManager.kitReduceMotion, true);
    assert.equal(w.statusText(w.index()), "ON");
    w.cursorLeft();
    assert.equal(c.GameAccess.settings().access.reduce_motion, false);
    w.select("kitShakeScale");
    assert.equal(w.statusText(w.index()), "100%");
    w.cursorRight();                                    // already at the top: stays
    assert.equal(c.ConfigManager.kitShakeScale, 1);
    w.processOk();                                      // OK wraps around
    assert.equal(c.ConfigManager.kitShakeScale, 0);
    w.cursorRight();
    assert.equal(w.statusText(w.index()), "25%");
    w.select("bgmVolume");
    w.processOk();
    w.cursorRight();
    w.cursorLeft();
    assert.ok(w.mzOk && w.mzRight && w.mzLeft, "MZ's rows go to MZ's methods");
    assert.equal(w.statusText(w.index()), "100%");
});

test("a stepped value from the file that sits between or past the steps moves to the step on that side", () => {
    const { c } = load();
    const step = c.GameAccess.stepValue;
    assert.equal(step([0.75, 1, 1.25, 1.5], 1.1, 1, false), 1.25);
    assert.equal(step([0.75, 1, 1.25, 1.5], 1.1, -1, false), 1);
    assert.equal(step([0.75, 1, 1.25, 1.5], 2, -1, false), 1.5);
    assert.equal(step([0.75, 1, 1.25, 1.5], 2, 1, true), 0.75);
    assert.equal(step([0.75, 1, 1.25, 1.5], 0.5, -1, false), 0.75);
});

test("Shake Screen follows reduce motion and the shake scale", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const screen = new c.Game_Screen();
    screen.startShake(5, 5, 60);
    assert.deepEqual(screen.shake, [5, 5, 60]);
    c.ConfigManager.kitShakeScale = 0.5;
    screen.startShake(6, 5, 60);
    assert.deepEqual(screen.shake, [3, 5, 60]);
    c.ConfigManager.kitReduceMotion = true;
    screen.startShake(9, 5, 60);
    assert.deepEqual(screen.shake, [0, 5, 0], "reduce motion: no shake at all");
});

test("Flash Screen: three per second at most, always, and gentler with gentle flashes", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const s = c.GameAccess.settings();
    const limiter = new GameJuice.FlashLimiter();
    const color = [255, 255, 255, 200];
    const shown = [0, 0.1, 0.2, 0.3, 1.05].map((t) => c.GameAccess.flashColor(color, s, limiter, t));
    assert.equal(shown[3], null, "the fourth flash inside one second is dropped");
    assert.deepEqual([...shown[0]], [255, 255, 255, Math.round(200 * c.GameAccess.GENTLE_FLASH)], "flash_limit is on by default");
    assert.notEqual(shown[4], null, "a second later flashes are allowed again");
    s.access.flash_limit = false;
    assert.deepEqual([...c.GameAccess.flashColor(color, s, new GameJuice.FlashLimiter(), 0)], color);   // [...]: the plugin's realm
    assert.deepEqual(color, [255, 255, 255, 200], "the caller's color is not changed");
    const screen = new c.Game_Screen();
    for (let i = 0; i < 5; i++) screen.startFlash([255, 0, 0, 128], 8);   // one frame apart: the hook's own limiter
    assert.ok(screen.flash, "the first flash reaches MZ");
});

test("battle animation flashes go through the limiter and are gentler (Sprite_Animation)", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const spr = new c.Sprite_Animation([{ frame: 0, color: [255, 255, 255, 200], duration: 6 }]);
    spr.processFlashTimings();
    assert.deepEqual([...spr._flashColor], [255, 255, 255, Math.round(200 * c.GameAccess.GENTLE_FLASH)]);
    assert.equal(spr._flashDuration, 6);
});

test("a battle animation flash the limiter drops leaves the previous flash alone", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const make = () => new c.Sprite_Animation([{ frame: 0, color: [255, 255, 255, 200], duration: 6 }]);
    const shown = [make(), make(), make()];
    for (const s of shown) s.processFlashTimings();
    const dropped = make();
    dropped._flashColor = [9, 9, 9, 9];
    dropped._flashDuration = 2;
    dropped.processFlashTimings();
    assert.deepEqual([...dropped._flashColor], [9, 9, 9, 9], "dropped: the old color stays");
    assert.equal(dropped._flashDuration, 2, "dropped: the old duration stays");
});

test("MV-format animation flashes (target and screen) go through the limiter", () => {
    const { c } = load();
    c.ConfigManager.applyData({});
    const mv = new c.Sprite_AnimationMV();
    mv.startFlash([255, 255, 255, 200], 5);
    mv.startScreenFlash([255, 255, 255, 200], 5);
    mv.startFlash([255, 255, 255, 200], 5);
    mv.startScreenFlash([255, 255, 255, 200], 5);
    assert.equal(mv.flashes.length, 3, "the fourth in a second is dropped");
    assert.equal(mv.flashes[0][1][3], Math.round(200 * c.GameAccess.GENTLE_FLASH));
});

test("windows grow their line height with the text size and the line spacing, never shrink", () => {
    const { c } = load();
    const win = new c.Window_Base();
    c.ConfigManager.applyData({});
    assert.equal(win.lineHeight(), MZ_LINE_HEIGHT);
    c.ConfigManager.kitTextScale = 1.5;
    assert.equal(win.lineHeight(), MZ_LINE_HEIGHT * 1.5, "150 % text: 54 pixel lines");
    c.ConfigManager.kitLineSpacing = 1.25;
    assert.equal(win.lineHeight(), Math.ceil(MZ_LINE_HEIGHT * 1.5 * 1.25));
    c.ConfigManager.kitTextScale = 0.75;
    c.ConfigManager.kitLineSpacing = 1;
    assert.equal(win.lineHeight(), MZ_LINE_HEIGHT, "small text keeps MZ's line");
});

test("MZ's save contents carry the kit's version, older ones are migrated, newer ones refused", () => {
    const { c } = load();
    const contents = c.DataManager.makeSaveContents();
    assert.deepEqual(JSON.parse(JSON.stringify(contents.kitSave)), { format: GameShell.SAVE_FORMAT, version: GameShell.SAVE_VERSION });
    assert.equal(contents.party.gold, 5, "MZ's own contents stay");
    c.DataManager.extractSaveContents(contents);
    assert.equal(c.DataManager.extracted.kitSave, undefined, "MZ never sees the mark");
    assert.equal(c.DataManager.extracted.party.gold, 5);
    const old = { kitSave: { version: 1 }, hp: 4 };          // the kit's template migrations: v1 renamed hp to health
    c.DataManager.extractSaveContents(old);
    assert.equal(c.DataManager.extracted.health, 4);
    assert.equal(c.DataManager.extracted.difficulty, "normal");
    assert.throws(() => c.DataManager.extractSaveContents({ kitSave: { version: 99 } }), /cannot be loaded \(newer\)/);
    c.DataManager.extractSaveContents({ party: {} });         // a save from before the plugin: the current version, untouched
    assert.deepEqual(c.DataManager.extracted, { party: {} });
    const older = load({ unmarkedSaveVersion: "1" });
    older.c.DataManager.extractSaveContents({ hp: 7 });
    assert.equal(older.c.DataManager.extracted.health, 7, "unmarkedSaveVersion says what version unmarked saves were");
});

test("text size scales MZ's main font size", () => {
    const { c } = load();
    c.ConfigManager.applyData({ kit: { access: { text_scale: 1.5 } } });
    assert.equal(new c.Game_System().mainFontSize(), Math.round(MZ_FONT_SIZE * 1.5));
});

// {{FOOTER}}
