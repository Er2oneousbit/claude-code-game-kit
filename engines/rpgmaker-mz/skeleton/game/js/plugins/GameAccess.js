// ---------------------------------------------------------------------------
// GameAccess.js
// Purpose : The MZ glue for the kit's shell and juice rules: the player's settings (GameShell) live in MZ's own
//           config file next to MZ's options, the accessibility options that fit MZ's Options screen appear there
//           (reduce motion, screen shake, gentle flashes, text size), and MZ's own Shake Screen and Flash Screen go
//           through them: shake scaled by effectiveShake (0 with reduce motion), every full-screen flash through
//           the FlashLimiter (at most 3 per real second, always) and toned down while gentle flashes is on, and so are
//           the flashes of battle animations (#280). Window line height follows Text Size and Line Spacing, the kit's
//           save version rides in MZ's save contents (migrated on load), and a game can switch on more Options rows.
// Usage   : Plugin Manager: GameCore, GameAudio, GameJuice, GameShell, then GameAccess, then GameMain
//           (python tools/dev.py setup registers them). In another plugin: GameAccess.settings() is the player's
//           settings object (read access.difficulty, input.bindings, language ...); after changing it, call
//           ConfigManager.save() as MZ's own options do.
// Notes   : Written against MZ 1.x's ConfigManager, Window_Options, Scene_Options, Game_Screen and Game_System as the
//           kit knows them, not yet run in RPG Maker MZ (verify each hook in a test play). Hooks call the original
//           method (alias). The settings sit under one key, "kit", in config.rpgsave and are repaired on load
//           (GameShell.settingsLoad): unknown keys stay, so a newer game's file survives. Option labels are plugin
//           parameters, so a translated game changes them in the Plugin Manager. Text size scales MZ's main font
//           size, and Window_Base.lineHeight grows with it (and with Line Spacing), which MZ's windows size from
//           (verify at 150 %: a window that sets its own height still needs a look). Battle animations: MZ's
//           Sprite_Animation (Effekseer) flashes its target through processFlashTimings, the older Sprite_AnimationMV
//           through startFlash and startScreenFlash; both are routed through the same limiter (verify against the
//           method names in your MZ version). Saves: DataManager.makeSaveContents adds `kitSave` (the version of the
//           kit's save rules) and extractSaveContents runs GameShell.saveMigrate over contents that carry an older
//           one; contents without it (a game made before this plugin) count as the current version unless the
//           plugin parameter unmarkedSaveVersion says otherwise. What MZ leaves to you: docs/ENGINE_FLOW.md "The
//           shell, juice and accessibility in MZ".
//
// Pseudocode:
//   ConfigManager: makeData adds config.kit ; applyData reads it through settingsLoad ; one property per option
//   Window_Options: kit rows after MZ's, status as on/off or a percent, OK and right step forward, left back
//   Game_Screen.startShake(power, ...) -> power * effectiveShake ; 0 -> no shake
//   Game_Screen.startFlash(color, d)  -> limiter says no -> no flash ; gentle -> alpha * GENTLE_FLASH
//   Sprite_Animation.processFlashTimings / Sprite_AnimationMV.startFlash, startScreenFlash -> the same decision
//   Window_Base.lineHeight -> ceil(MZ's * max(1, text size) * line spacing)
//   DataManager.makeSaveContents adds kitSave ; extractSaveContents migrates older contents, refuses newer ones
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Sonnet 5.5, claude-sonnet-5-5): battle animation flashes through the limiter, window
//           line height with Text Size and a Line Spacing row, more Options rows a game can switch on (extraRows),
//           the kit's save version in MZ's save contents (#280)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc {{GAME_NAME}}: accessibility settings on MZ's Options screen; shake and flash follow them.
 * @author {{AUTHOR}}
 * @base GameJuice
 * @base GameShell
 * @orderAfter GameShell
 *
 * @help GameAccess.js
 *
 * Keeps the kit's player settings in MZ's config file and adds five
 * options to the Options screen: Reduce Motion, Screen Shake (0 to 100 %),
 * Gentle Flashes, Text Size and Line Spacing (more on/off rows through the
 * More Options rows parameter). MZ's Shake Screen follows Reduce Motion
 * and Screen Shake; every Flash Screen, and the flashes of battle
 * animations, goes through a limit of three flashes per second, and is
 * softer while Gentle Flashes is on. Windows grow their line height with
 * Text Size and Line Spacing. The kit's save version is kept in save files.
 * Needs GameJuice and GameShell above it. No plugin commands.
 *
 * @param reduceMotionText
 * @text Reduce Motion label
 * @type string
 * @default Reduce Motion
 *
 * @param shakeText
 * @text Screen Shake label
 * @type string
 * @default Screen Shake
 *
 * @param flashText
 * @text Gentle Flashes label
 * @type string
 * @default Gentle Flashes
 *
 * @param textSizeText
 * @text Text Size label
 * @type string
 * @default Text Size
 *
 * @param lineSpacingText
 * @text Line Spacing label
 * @type string
 * @default Line Spacing
 *
 * @param extraRows
 * @text More Options rows
 * @type string
 * @default
 * @desc Comma-separated on/off settings to add as rows: subtitles, speaker_names, subtitle_barks, subtitle_hold, captions_sfx, hold_to_toggle, auto_repeat, narration, readable_font. Your game reads them with GameAccess.settings().access.
 *
 * @param unmarkedSaveVersion
 * @text Version of saves without a mark
 * @type string
 * @default
 * @desc Saves made before this plugin carry no version. Empty: they count as the current one (nothing is migrated). Set the version your older saves were, and GameShell's MIGRATIONS bring them forward.
 */

(() => {
    "use strict";

    const PLUGIN = "GameAccess";          // must match this file's name (MZ looks plugins up by it)
    const CONFIG_KEY = "kit";             // where the settings sit in config.rpgsave
    const GENTLE_FLASH = 0.4;             // alpha factor while gentle flashes (access.flash_limit) is on
    const SHAKE_STEPS = [0, 0.25, 0.5, 0.75, 1];
    const TEXT_STEPS = [0.75, 1, 1.25, 1.5];
    const SPACING_STEPS = [1, 1.25, 1.5, 2];
    // on/off settings a game can put on the Options screen (plugin parameter extraRows); the game reads them
    const EXTRA_BOOL = ["subtitles", "speaker_names", "subtitle_barks", "subtitle_hold", "captions_sfx",
                        "hold_to_toggle", "auto_repeat", "narration", "readable_font"];

    const params = PluginManager.parameters(PLUGIN);
    const label = (name, fallback) => String(params[name] || fallback);
    // symbol (the ConfigManager property Window_Options reads), label, settings field under access, steps or bool
    const titleCase = (field) => field.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
    const camel = (field) => field.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join("");

    // The extra rows a game asked for: names from a JSON list or a comma list; unknown names are reported, not used
    function extraRows(text, warn) {
        const names = String(text || "").replace(/^\s*\[|\]\s*$/g, "").split(",")
            .map((n) => n.trim().replace(/^"|"$/g, "")).filter(Boolean);
        const rows = [];
        for (const n of names) {
            if (!EXTRA_BOOL.includes(n)) {
                warn(`[${PLUGIN}] extraRows: "${n}" is not one of ${EXTRA_BOOL.join(", ")}`);
            } else if (!rows.some((r) => r.field === n)) {
                rows.push({ symbol: "kit" + camel(n), text: titleCase(n), field: n });
            }
        }
        return rows;
    }

    const OPTIONS = [
        { symbol: "kitReduceMotion", text: label("reduceMotionText", "Reduce Motion"), field: "reduce_motion" },
        { symbol: "kitShakeScale", text: label("shakeText", "Screen Shake"), field: "shake_scale", steps: SHAKE_STEPS },
        { symbol: "kitFlashLimit", text: label("flashText", "Gentle Flashes"), field: "flash_limit" },
        { symbol: "kitTextScale", text: label("textSizeText", "Text Size"), field: "text_scale", steps: TEXT_STEPS },
        { symbol: "kitLineSpacing", text: label("lineSpacingText", "Line Spacing"), field: "line_spacing", steps: SPACING_STEPS },
        ...extraRows(params.extraRows, (m) => console.warn(m)),
    ];
    const bySymbol = new Map(OPTIONS.map((o) => [o.symbol, o]));

    let settings = GameShell.defaultSettings();
    const limiter = new GameJuice.FlashLimiter();
    const nowS = () => (typeof performance === "object" ? performance.now() : Date.now()) / 1000;   // real time

    // ---- Decisions (pure, tested in Node) ----------------------------------------
    // MZ's shake power for the player's settings (0 = no shake at all)
    const shakePower = (power, s) => Number(power) * GameShell.effectiveShake(s);

    // MZ's flash color for the player's settings, or null when the flash must not happen (the limiter said no)
    function flashColor(color, s, flashes, now) {
        if (!flashes.request(now)) return null;
        const out = Array.from(color);
        if (s.access.flash_limit) out[3] = Math.round(Number(out[3] || 0) * GENTLE_FLASH);
        return out;
    }

    // A window's line height: MZ's own, grown by the text size (never shrunk: smaller text fits a line already) and by
    // the line spacing the player chose
    const lineHeight = (base, s) => Math.ceil(Number(base) * Math.max(1, s.access.text_scale) * s.access.line_spacing);

    // The save contents with the kit's version, and the contents ready for MZ to extract: [contents, problem].
    // unmarked: the version of contents without a mark ("" or null: the current one, nothing to migrate)
    function saveContents(contents) {
        return Object.assign({}, contents, { kitSave: { format: GameShell.SAVE_FORMAT, version: GameShell.SAVE_VERSION } });
    }
    function extractContents(contents, unmarked) {
        const mark = contents && contents.kitSave;
        const marked = mark && Number.isInteger(mark.version);
        const version = marked ? mark.version : (unmarked === "" || unmarked == null ? GameShell.SAVE_VERSION : Number(unmarked));
        if (!Number.isInteger(version) || version < 1) return [null, "bad version"];
        if (version > GameShell.SAVE_VERSION) return [null, "newer"];
        const data = Object.assign({}, contents);
        delete data.kitSave;
        const env = GameShell.saveMigrate({ format: GameShell.SAVE_FORMAT, version, data });
        return [env.data, ""];
    }

    // The next (dir 1) or previous (dir -1) step of a stepped option; wrap goes from the last back to the first
    function stepValue(steps, value, dir, wrap) {
        let i = steps.findIndex((v) => Math.abs(v - value) < 1e-9);
        if (i < 0) {   // a value between (or past) the steps, from the settings file: move to the step on that side
            const g = steps.findIndex((v) => v > value);
            const above = g < 0 ? steps.length : g;
            i = dir > 0 ? above - 1 : above;
        }
        const next = i + dir;
        if (next >= steps.length) return wrap ? steps[0] : steps[steps.length - 1];
        return steps[Math.max(next, 0)];
    }

    // ---- ConfigManager: the settings in config.rpgsave ---------------------------
    for (const o of OPTIONS) {
        Object.defineProperty(ConfigManager, o.symbol, {
            get: () => settings.access[o.field],
            set: (v) => { settings.access[o.field] = o.steps ? Number(v) : !!v; },
            configurable: true,
        });
    }

    const makeData = ConfigManager.makeData;
    ConfigManager.makeData = function () {
        const config = makeData.call(this);
        config[CONFIG_KEY] = JSON.parse(JSON.stringify(settings));
        return config;
    };

    const applyData = ConfigManager.applyData;
    ConfigManager.applyData = function (config) {
        applyData.call(this, config);
        const raw = config && Object.prototype.hasOwnProperty.call(config, CONFIG_KEY) ? JSON.stringify(config[CONFIG_KEY]) : null;
        const r = GameShell.settingsLoad(raw);
        settings = r.settings;
        if (raw !== null && r.problems.length) console.warn(`[${PLUGIN}] settings repaired (${r.problems.join(", ")})`);
    };

    // ---- Window_Options and Scene_Options: the rows ------------------------------
    const makeCommandList = Window_Options.prototype.makeCommandList;
    Window_Options.prototype.makeCommandList = function () {
        makeCommandList.call(this);
        for (const o of OPTIONS) this.addCommand(o.text, o.symbol);
    };

    const statusText = Window_Options.prototype.statusText;
    Window_Options.prototype.statusText = function (index) {
        const o = bySymbol.get(this.commandSymbol(index));
        if (!o) return statusText.call(this, index);
        const value = this.getConfigValue(o.symbol);
        return o.steps ? `${Math.round(value * 100)}%` : this.booleanStatusText(value);
    };

    // OK and right step forward (OK wraps around, as MZ's volumes do), left steps back; on/off rows flip
    function kitChange(win, symbol, dir, wrap) {
        const o = bySymbol.get(symbol);
        if (!o) return false;
        const value = win.getConfigValue(symbol);
        win.changeValue(symbol, o.steps ? stepValue(o.steps, value, dir, wrap) : (dir === 0 ? !value : dir > 0));
        return true;
    }

    for (const [method, dir, wrap] of [["processOk", 0, true], ["cursorRight", 1, false], ["cursorLeft", -1, false]]) {
        const original = Window_Options.prototype[method];
        Window_Options.prototype[method] = function (...args) {
            const symbol = this.commandSymbol(this.index());
            const o = bySymbol.get(symbol);
            if (!o) return original.apply(this, args);
            return kitChange(this, symbol, o.steps && dir === 0 ? 1 : dir, wrap);
        };
    }

    const maxCommands = Scene_Options.prototype.maxCommands;
    Scene_Options.prototype.maxCommands = function () {
        return maxCommands.call(this) + OPTIONS.length;   // MZ sizes the options window by this count (verify)
    };

    // ---- Game_Screen: MZ's own shake and flash -----------------------------------
    const startShake = Game_Screen.prototype.startShake;
    Game_Screen.prototype.startShake = function (power, speed, duration) {
        const p = shakePower(power, settings);
        return startShake.call(this, p, speed, p > 0 ? duration : 0);
    };

    const startFlash = Game_Screen.prototype.startFlash;
    Game_Screen.prototype.startFlash = function (color, duration) {
        const c = flashColor(color, settings, limiter, nowS());
        if (c) startFlash.call(this, c, duration);
    };

    // ---- Battle animations: their flashes go through the same limiter (#280) ------------------
    // Sprite_Animation (MZ's Effekseer animations) starts a flash in processFlashTimings by setting _flashColor (a new
    // array) and _flashDuration; if the limiter says no, the previous values come back, if gentle the alpha is lowered
    if (typeof Sprite_Animation !== "undefined") {
        const processFlashTimings = Sprite_Animation.prototype.processFlashTimings;
        Sprite_Animation.prototype.processFlashTimings = function () {
            const before = [this._flashColor, this._flashDuration];
            processFlashTimings.call(this);
            if (this._flashColor === before[0]) return;
            const c = flashColor(this._flashColor, settings, limiter, nowS());
            if (c) {
                this._flashColor = c;
            } else {
                this._flashColor = before[0];
                this._flashDuration = before[1];
            }
        };
    }
    // Sprite_AnimationMV (animations made in MV's format) flashes through startFlash (the target) and
    // startScreenFlash (the screen), each with a color array and a duration
    if (typeof Sprite_AnimationMV !== "undefined") {
        for (const method of ["startFlash", "startScreenFlash"]) {
            const original = Sprite_AnimationMV.prototype[method];
            if (typeof original !== "function") continue;
            Sprite_AnimationMV.prototype[method] = function (color, duration) {
                const c = flashColor(color, settings, limiter, nowS());
                if (c) original.call(this, c, duration);
            };
        }
    }

    // ---- Windows: line height grows with the text ----------------------------------------------
    const baseLineHeight = Window_Base.prototype.lineHeight;
    Window_Base.prototype.lineHeight = function () {
        return lineHeight(baseLineHeight.call(this), settings);
    };

    // ---- Saves: the kit's version in MZ's save contents -----------------------------------------
    if (typeof DataManager !== "undefined") {
        const makeSaveContents = DataManager.makeSaveContents;
        DataManager.makeSaveContents = function () {
            return saveContents(makeSaveContents.call(this));
        };
        const extractSaveContents = DataManager.extractSaveContents;
        DataManager.extractSaveContents = function (contents) {
            const [data, problem] = extractContents(contents, params.unmarkedSaveVersion);
            if (data === null) throw new Error(`[${PLUGIN}] this save cannot be loaded (${problem})`);
            return extractSaveContents.call(this, data);
        };
    }

    // ---- Game_System: text size ---------------------------------------------------
    const mainFontSize = Game_System.prototype.mainFontSize;
    Game_System.prototype.mainFontSize = function () {
        return Math.round(mainFontSize.call(this) * settings.access.text_scale);
    };

    const GameAccess = { settings: () => settings, OPTIONS, shakePower, flashColor, stepValue, GENTLE_FLASH,
                         lineHeight, extraRows, saveContents, extractContents };
    globalThis.GameAccess = GameAccess;
})();

// {{FOOTER}}
