// ---------------------------------------------------------------------------
// GameAccess.js
// Purpose : The MZ glue for the kit's shell and juice rules: the player's settings (GameShell) live in MZ's own
//           config file next to MZ's options, the accessibility options that fit MZ's Options screen appear there
//           (reduce motion, screen shake, gentle flashes, text size), and MZ's own Shake Screen and Flash Screen go
//           through them: shake scaled by effectiveShake (0 with reduce motion), every full-screen flash through
//           the FlashLimiter (at most 3 per real second, always) and toned down while gentle flashes is on.
// Usage   : Plugin Manager: GameCore, GameAudio, GameJuice, GameShell, then GameAccess, then GameMain
//           (python tools/dev.py setup registers them). In another plugin: GameAccess.settings() is the player's
//           settings object (read access.difficulty, input.bindings, language ...); after changing it, call
//           ConfigManager.save() as MZ's own options do.
// Notes   : Written against MZ 1.x's ConfigManager, Window_Options, Scene_Options, Game_Screen and Game_System as the
//           kit knows them, not yet run in RPG Maker MZ (verify each hook in a test play). Hooks call the original
//           method (alias). The settings sit under one key, "kit", in config.rpgsave and are repaired on load
//           (GameShell.settingsLoad): unknown keys stay, so a newer game's file survives. Option labels are plugin
//           parameters, so a translated game changes them in the Plugin Manager. Text size scales MZ's main font
//           size; windows keep their line height, so check long messages at the largest size (verify).
//           Battle animations' own flashes (Sprite_Animation) are not routed through the limiter (verify what your
//           animations flash, SOP-20). What MZ leaves to you: docs/ENGINE_FLOW.md "The shell, juice and
//           accessibility in MZ".
//
// Pseudocode:
//   ConfigManager: makeData adds config.kit ; applyData reads it through settingsLoad ; one property per option
//   Window_Options: kit rows after MZ's, status as on/off or a percent, OK and right step forward, left back
//   Game_Screen.startShake(power, ...) -> power * effectiveShake ; 0 -> no shake
//   Game_Screen.startFlash(color, d)  -> limiter says no -> no flash ; gentle -> alpha * GENTLE_FLASH
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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
 * Keeps the kit's player settings in MZ's config file and adds four
 * options to the Options screen: Reduce Motion, Screen Shake (0 to 100 %),
 * Gentle Flashes and Text Size. MZ's Shake Screen follows Reduce Motion
 * and Screen Shake; every Flash Screen goes through a limit of three
 * flashes per second, and is softer while Gentle Flashes is on.
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
 */

(() => {
    "use strict";

    const PLUGIN = "GameAccess";          // must match this file's name (MZ looks plugins up by it)
    const CONFIG_KEY = "kit";             // where the settings sit in config.rpgsave
    const GENTLE_FLASH = 0.4;             // alpha factor while gentle flashes (access.flash_limit) is on
    const SHAKE_STEPS = [0, 0.25, 0.5, 0.75, 1];
    const TEXT_STEPS = [0.75, 1, 1.25, 1.5];

    const params = PluginManager.parameters(PLUGIN);
    const label = (name, fallback) => String(params[name] || fallback);
    // symbol (the ConfigManager property Window_Options reads), label, settings field under access, steps or bool
    const OPTIONS = [
        { symbol: "kitReduceMotion", text: label("reduceMotionText", "Reduce Motion"), field: "reduce_motion" },
        { symbol: "kitShakeScale", text: label("shakeText", "Screen Shake"), field: "shake_scale", steps: SHAKE_STEPS },
        { symbol: "kitFlashLimit", text: label("flashText", "Gentle Flashes"), field: "flash_limit" },
        { symbol: "kitTextScale", text: label("textSizeText", "Text Size"), field: "text_scale", steps: TEXT_STEPS },
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

    // ---- Game_System: text size ---------------------------------------------------
    const mainFontSize = Game_System.prototype.mainFontSize;
    Game_System.prototype.mainFontSize = function () {
        return Math.round(mainFontSize.call(this) * settings.access.text_scale);
    };

    const GameAccess = { settings: () => settings, OPTIONS, shakePower, flashColor, stepValue, GENTLE_FLASH };
    globalThis.GameAccess = GameAccess;
})();

// {{FOOTER}}
