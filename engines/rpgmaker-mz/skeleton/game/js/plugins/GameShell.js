// ---------------------------------------------------------------------------
// GameShell.js
// Purpose : The kit's shell rules, engine-free: the player's settings (defaults, the schema, a loader that repairs a
//           damaged or old file, effectiveShake, telemetryAllowed), bindings and prompt glyph names (rebind with
//           swap, conflicts, narration lines), i18n (fallback chain, placeholders, plurals, the pseudo-locale) and
//           the versioned save envelope (parse, migrate, primary then backup). Plain JavaScript with no RPG Maker
//           objects, so Node tests it (tests/gameShell.test.js) against the kit's golden vectors
//           (data/golden/shell.json) and MZ loads it as an ordinary plugin.
// Usage   : in another plugin:  const { settings, problems } = GameShell.settingsLoad(textOrNull);
//                               GameShell.effectiveShake(settings)  // 0 with reduce motion, else shake_scale
//                               GameShell.tr(tables, "fr", "menu.play")  ;  GameShell.pseudo("Play")
//                               GameShell.saveLoad(primaryText, backupText)   // { envelope, source, problems }
//           in a test:          const GameShell = require("../game/js/plugins/GameShell.js");
// Notes   : Ports of tools/golden_vectors.py (the spec; the web overlay's src/core/settings.ts, bindings.ts, i18n.ts
//           and saveStore.ts are the same rules in TypeScript). MZ keeps its own title, options, save and load
//           screens: GameAccess.js stores these settings in MZ's config file and puts the accessibility ones on
//           MZ's Options screen; the rest are here for your plugins (a rebinding screen, per-locale text, a save
//           version in DataManager.makeSaveContents). Settings are numbers 0..1 here (MZ's own volumes are 0..100).
//           Keep it free of $game*, Scene_*, Window_*, ConfigManager: anything MZ goes in GameAccess.js.
//           The last lines make the same file a global (GameShell) in MZ and a CommonJS module in Node.
//
// Pseudocode (settingsLoad):
//   parse (unreadable or not an object -> defaults + one problem) ; copy every key of the file
//   version = 1 ; language must be a string of 2..12 code points
//   per schema section: a non-object section counts as one problem ; per field: missing -> default,
//   present -> fixField (bool | num clamp | enum | resolution) ; input.bindings: lists of strings only
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc {{GAME_NAME}}: shell rules (engine-free: settings, bindings, i18n, versioned saves).
 * @author {{AUTHOR}}
 *
 * @help GameShell.js
 *
 * The kit's shell rules for {{GAME_NAME}}, kept free of RPG Maker objects
 * so they can be tested outside the editor (python tools/dev.py test)
 * against the kit's golden vectors: settings that repair themselves,
 * rebinding with swap, prompt glyph names, translations with the
 * pseudo-locale, and save files with a version and migrations.
 * GameAccess.js connects the settings to MZ's Options screen.
 * No plugin commands and no parameters.
 */

(() => {
    "use strict";

    // ---- Tunables -------------------------------------------------------------
    const SETTINGS_VERSION = 1;
    const DIFFICULTIES = ["story", "easy", "normal", "hard"];
    const COLORBLIND = ["none", "protanopia", "deuteranopia", "tritanopia"];
    const SUB_SIZES = ["small", "medium", "large", "xl"];
    const DISPLAY_MODES = ["windowed", "fullscreen", "borderless"];
    const FRAME_CAPS = [0, 30, 60, 120, 144, 240];
    const CONSENT = ["unset", "yes", "no"];
    const GLYPH_SETS = ["auto", "keyboard", "xbox", "playstation", "generic"];
    const FALLBACK_LOCALE = "en";
    const PSEUDO_LOCALE = "pseudo";
    const PSEUDO_GROWTH = 0.40;            // translated text runs about 40 % longer than English (SOP-19)
    const NO_PLURAL = ["ja", "zh", "ko"];  // one form for every count
    const ZERO_IS_ONE = ["fr"];            // 0 and 1 take the singular
    const SAVE_VERSION = 3;
    const SAVE_FORMAT = "save";

    const DEFAULT_BINDINGS = {
        ui_up: ["key:up", "pad:dpad_up"],
        ui_down: ["key:down", "pad:dpad_down"],
        ui_left: ["key:left", "pad:dpad_left"],
        ui_right: ["key:right", "pad:dpad_right"],
        ui_accept: ["key:enter", "pad:south"],
        ui_cancel: ["key:escape", "pad:east"],
        move_left: ["key:a", "pad:dpad_left"],
        move_right: ["key:d", "pad:dpad_right"],
        move_up: ["key:w", "pad:dpad_up"],
        move_down: ["key:s", "pad:dpad_down"],
        jump: ["key:space", "pad:south"],
        attack: ["key:j", "pad:west"],
        interact: ["key:e", "pad:north"],
        pause: ["key:escape", "pad:start"],
    };

    // ---- Small helpers --------------------------------------------------------
    const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
    const isObject = (v) => typeof v === "object" && v !== null && !Array.isArray(v);
    const isNum = (v) => typeof v === "number" && !Number.isNaN(v);
    const deepCopy = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

    // ---- Settings -------------------------------------------------------------
    const DEFAULTS = {
        version: SETTINGS_VERSION,
        display: { mode: "windowed", vsync: true, frame_cap: 0, resolution: [1920, 1080], ui_scale: 1.0 },
        audio: { master: 1.0, music: 0.8, sfx: 1.0, ui: 1.0, voice: 1.0, mono: false },
        language: "en",
        access: {
            text_scale: 1.0, subtitles: true, subtitle_size: "medium", subtitle_background: 0.6, speaker_names: true,
            subtitle_barks: false, captions_sfx: false, colorblind: "none", reduce_motion: false, shake_scale: 1.0,
            flash_limit: true, hold_to_toggle: false, difficulty: "normal", game_speed: 1.0,
            readable_font: false, line_spacing: 1.0, subtitle_hold: false, timing_scale: 1.0, auto_repeat: false,
            narration: false,
        },
        input: { bindings: deepCopy(DEFAULT_BINDINGS), deadzone: 0.2, invert_y: false, glyphs: "auto" },
        telemetry: { consent: "unset" },
    };

    const num = (lo, hi) => ({ kind: "num", lo, hi });
    const bool = { kind: "bool" };
    const choice = (values) => ({ kind: "enum", values });

    // Section -> field -> rule; each field's default comes from DEFAULTS
    const SCHEMA = {
        display: { mode: choice(DISPLAY_MODES), vsync: bool, frame_cap: choice(FRAME_CAPS), resolution: { kind: "res" },
                   ui_scale: num(0.75, 2.0) },
        audio: { master: num(0, 1), music: num(0, 1), sfx: num(0, 1), ui: num(0, 1), voice: num(0, 1), mono: bool },
        access: {
            text_scale: num(0.75, 2.0), subtitles: bool, subtitle_size: choice(SUB_SIZES), subtitle_background: num(0, 1),
            speaker_names: bool, subtitle_barks: bool, captions_sfx: bool, colorblind: choice(COLORBLIND),
            reduce_motion: bool, shake_scale: num(0, 1), flash_limit: bool, hold_to_toggle: bool,
            difficulty: choice(DIFFICULTIES), game_speed: num(0.5, 1.0), readable_font: bool, line_spacing: num(1, 2),
            subtitle_hold: bool, timing_scale: num(1, 3), auto_repeat: bool, narration: bool,
        },
        input: { deadzone: num(0, 0.9), invert_y: bool, glyphs: choice(GLYPH_SETS) },
        telemetry: { consent: choice(CONSENT) },
    };

    const defaultSettings = () => deepCopy(DEFAULTS);

    // [value, problem] for one field
    function fixField(rule, value, def) {
        switch (rule.kind) {
            case "bool":
                return typeof value === "boolean" ? [value, false] : [def, true];
            case "num": {
                if (!isNum(value)) return [def, true];
                const clamped = Math.min(Math.max(value, rule.lo), rule.hi);
                return [clamped, clamped !== value];
            }
            case "enum":
                for (const allowed of rule.values) if (typeof allowed === typeof value && value === allowed) return [allowed, false];
                return [def, true];
            case "res":
                if (Array.isArray(value) && value.length === 2 && value.every((n) => isNum(n) && n >= 1 && Number.isInteger(n))) {
                    return [[value[0], value[1]], false];
                }
                return [[...def], true];
            default:
                throw new Error(`unknown rule ${rule.kind}`);
        }
    }

    function fixBindings(value, problems) {
        const out = deepCopy(DEFAULT_BINDINGS);
        if (!isObject(value)) {
            problems.push("input.bindings");
            return out;
        }
        for (const [action, lst] of Object.entries(value)) {
            if (!Array.isArray(lst)) {
                problems.push(`input.bindings.${action}`);
                continue;
            }
            const clean = lst.filter((b) => typeof b === "string");
            if (clean.length !== lst.length) problems.push(`input.bindings.${action}`);
            out[action] = clean;
        }
        return out;
    }

    // Settings from the file's text (null = no file yet): every field valid, plus the list of what was fixed
    function settingsLoad(text) {
        const problems = [];
        let raw;
        try {
            raw = text === null || text === undefined ? {} : JSON.parse(text);
        } catch (e) {
            return { settings: defaultSettings(), problems: ["unreadable"] };
        }
        if (!isObject(raw)) return { settings: defaultSettings(), problems: ["not an object"] };
        const out = deepCopy(raw);
        out.version = SETTINGS_VERSION;
        const lang = own(raw, "language") ? raw.language : "en";
        const langLength = typeof lang === "string" ? [...lang].length : 0;   // code points, as the reference counts
        if (typeof lang === "string" && langLength >= 2 && langLength <= 12) {
            out.language = lang;
        } else {
            out.language = "en";
            if (own(raw, "language")) problems.push("language");
        }
        for (const [section, fields] of Object.entries(SCHEMA)) {
            let src = own(raw, section) ? raw[section] : {};
            if (!isObject(src)) {
                problems.push(section);
                src = {};
            }
            const sec = deepCopy(src);
            for (const [name, rule] of Object.entries(fields)) {
                const def = DEFAULTS[section][name];
                if (own(src, name)) {
                    const [value, bad] = fixField(rule, src[name], def);
                    if (bad) problems.push(`${section}.${name}`);
                    sec[name] = deepCopy(value);
                } else {
                    sec[name] = deepCopy(def);
                }
            }
            if (section === "input") {
                sec.bindings = own(src, "bindings") ? fixBindings(src.bindings, problems) : deepCopy(DEFAULT_BINDINGS);
            }
            out[section] = sec;
        }
        return { settings: out, problems };
    }

    // The shake intensity the juice should use: 0 with reduce motion, else the player's shake scale
    const effectiveShake = (settings) => (settings.access.reduce_motion ? 0.0 : settings.access.shake_scale);
    // Telemetry is recorded only after an explicit yes
    const telemetryAllowed = (settings) => settings.telemetry.consent === "yes";
    // The settings as file text (one-space indent, like the kit's other JSON files)
    const settingsText = (settings) => JSON.stringify(settings, null, 1) + "\n";

    // ---- Bindings and glyphs --------------------------------------------------
    const XBOX = { south: "a", east: "b", west: "x", north: "y", l1: "lb", r1: "rb", l2: "lt", r2: "rt", start: "menu",
                   select: "view" };
    const PLAYSTATION = { south: "cross", east: "circle", west: "square", north: "triangle", start: "options",
                          select: "share" };
    const AUTO_DEVICE = { keyboard: "keyboard", mouse: "keyboard", pad_xbox: "xbox", pad_playstation: "playstation" };

    const groupOf = (action) => (action.startsWith("ui_") ? "ui" : "game");

    // Puts binding in action's slot and swaps it out of any same-group action that had it. Pure: returns a copy
    function rebind(bindings, action, slot, binding) {
        const b = deepCopy(bindings);
        if (!own(b, action)) b[action] = [];
        const lst = b[action];
        if (slot > lst.length) throw new Error("slot past the end");
        const old = slot < lst.length ? lst[slot] : "";
        const conflicts = [];
        for (const other of Object.keys(b).sort()) {
            if (groupOf(other) !== groupOf(action)) continue;
            b[other].forEach((name, s) => {
                if (!(other === action && s === slot) && name === binding && binding !== "") conflicts.push([other, s]);
            });
        }
        if (slot === lst.length) lst.push(binding);
        else lst[slot] = binding;
        for (const [other, s] of conflicts) b[other][s] = old;
        return { bindings: b, conflicts };
    }

    // Which prompt art to show: the player's choice, or (auto) the last device used
    function glyphSet(setting, lastDevice) {
        if (setting !== "auto") return setting;
        return own(AUTO_DEVICE, lastDevice) ? AUTO_DEVICE[lastDevice] : "generic";
    }

    // The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick ...
    function glyphName(gset, binding) {
        const colon = binding.indexOf(":");
        const kind = colon >= 0 ? binding.slice(0, colon) : binding;
        let name = colon >= 0 ? binding.slice(colon + 1) : "";
        if (kind === "key") return "key_" + name;
        if (kind === "mouse") return "mouse_" + name;
        if (kind === "pad_axis") name = name.startsWith("left") ? "lstick" : "rstick";
        else if (kind !== "pad") return "unknown";
        if (gset === "xbox") return "xbox_" + (own(XBOX, name) ? XBOX[name] : name);
        if (gset === "playstation") return "ps_" + (own(PLAYSTATION, name) ? PLAYSTATION[name] : name);
        return "pad_" + name;
    }

    // The binding to show for an action: slot 0 (keyboard) for the keyboard set, slot 1 (pad) otherwise
    function promptBinding(bindings, action, gset) {
        const lst = own(bindings, action) ? bindings[action] : [];
        const slot = gset === "keyboard" ? 0 : 1;
        return slot < lst.length ? lst[slot] : "";
    }

    // Actions (same group) that share a non-empty binding with another: [action, slot] pairs
    function findConflicts(bindings) {
        const seen = new Map();
        for (const action of Object.keys(bindings).sort()) {
            bindings[action].forEach((name, slot) => {
                if (name === "") return;
                const key = groupOf(action) + "|" + name;
                seen.set(key, [...(seen.get(key) || []), [action, slot]]);
            });
        }
        return [...seen.values()].filter((list) => list.length > 1).flat();
    }

    const oneLine = (text) => String(text === undefined || text === null ? "" : text).split(/\s+/).filter(Boolean).join(" ");

    // What narration says for one control: "Music volume, slider, 70 percent"; no label says "unlabelled"
    function narrationLine(label, role, value = "") {
        const parts = [oneLine(label) || "unlabelled"];
        if (oneLine(role)) parts.push(oneLine(role));
        if (oneLine(value)) parts.push(oneLine(value));
        return parts.join(", ");
    }

    // ---- i18n -----------------------------------------------------------------
    const PSEUDO = {
        a: "á", e: "é", i: "í", o: "ó", u: "ú", c: "ç", n: "ñ", y: "ý",
        A: "Á", E: "É", I: "Í", O: "Ó", U: "Ú", C: "Ç", N: "Ñ", Y: "Ý",
    };
    const language = (locale) => locale.split("-")[0].split("_")[0];

    function localeChain(locale, fallback = FALLBACK_LOCALE) {
        const chain = [];
        for (const loc of [locale, language(locale), fallback]) if (loc && !chain.includes(loc)) chain.push(loc);
        return chain;
    }

    // Replaces {name} with args[name]; unknown names stay as written
    function fill(text, args) {
        let out = "";
        let i = 0;
        while (i < text.length) {
            if (text[i] === "{") {
                const j = text.indexOf("}", i);
                if (j > i) {
                    const name = text.slice(i + 1, j);
                    if (own(args, name)) {
                        out += String(args[name]);
                        i = j + 1;
                        continue;
                    }
                }
            }
            out += text[i];
            i += 1;
        }
        return out;
    }

    // The raw template for key through the fallback chain, or null
    function lookup(tables, locale, key) {
        for (const loc of localeChain(locale)) {
            const table = own(tables, loc) ? tables[loc] : undefined;
            if (table && own(table, key)) return table[key];
        }
        return null;
    }

    // A string through the fallback chain; a missing key returns the key itself, so it shows
    function tr(tables, locale, key, args = {}) {
        const text = lookup(tables, locale, key);
        return text === null ? key : fill(text, args);
    }

    function plural(locale, n) {
        const base = language(locale);
        if (NO_PLURAL.includes(base)) return "other";
        if (ZERO_IS_ONE.includes(base)) return n === 0 || n === 1 ? "one" : "other";
        return n === 1 ? "one" : "other";
    }

    const trPlural = (tables, locale, key, n, args = {}) => tr(tables, locale, `${key}.${plural(locale, n)}`, { ...args, n });

    // The pseudo-locale version of text: accented, 40 % longer, in brackets; placeholders untouched
    function pseudo(text) {
        const cs = Array.from(text);   // code points, so an emoji counts once (as in the reference)
        const out = [];
        let visible = 0;
        let i = 0;
        while (i < cs.length) {
            const c = cs[i];
            if (c === "{") {
                const j = cs.indexOf("}", i);
                if (j > i) {
                    out.push(cs.slice(i, j + 1).join(""));
                    i = j + 1;
                    continue;
                }
            }
            if (c === "%" && i + 1 < cs.length && "sdif%".includes(cs[i + 1])) {
                out.push(c + cs[i + 1]);
                i += 2;
                continue;
            }
            out.push(own(PSEUDO, c) ? PSEUDO[c] : c);
            visible += 1;
            i += 1;
        }
        return "[" + out.join("") + "~".repeat(Math.ceil(visible * PSEUDO_GROWTH)) + "]";
    }

    // ---- Versioned saves ------------------------------------------------------
    // MIGRATIONS[n] turns version-n data into version-n+1 data (the kit's template history; yours replaces it)
    const MIGRATIONS = {
        1: (data) => {
            if (own(data, "hp")) {
                data.health = data.hp;   // v2 renamed hp to health
                delete data.hp;
            }
            return data;
        },
        2: (data) => {
            if (!own(data, "difficulty")) data.difficulty = "normal";   // v3 added the difficulty the game started on
            return data;
        },
    };

    // [envelope, problem]: problem is "" when the envelope is usable
    function parseSave(text) {
        if (text === null || text === undefined) return [null, "missing"];
        let env;
        try {
            env = JSON.parse(text);
        } catch (e) {
            return [null, "unreadable"];
        }
        if (!isObject(env) || env.format !== SAVE_FORMAT || !isObject(env.data)) return [null, "not a save"];
        const v = env.version;
        if (typeof v !== "number" || !Number.isInteger(v) || v < 1) return [null, "bad version"];
        if (v > SAVE_VERSION) return [null, "newer"];
        return [env, ""];
    }

    function saveMigrate(env) {
        const out = deepCopy(env);
        while (out.version < SAVE_VERSION) {
            if (!own(MIGRATIONS, out.version)) throw new Error(`no save migration from version ${out.version}`);
            out.data = MIGRATIONS[out.version](out.data);
            out.version += 1;
        }
        return out;
    }

    // The newest usable save from the two files' text (null = file missing)
    function saveLoad(primary, backup) {
        const problems = [];
        for (const [source, text] of [["primary", primary], ["backup", backup]]) {
            const [env, problem] = parseSave(text);
            if (env !== null) return { envelope: saveMigrate(env), source, problems };
            problems.push(`${source}: ${problem}`);
        }
        return { envelope: null, source: "none", problems };
    }

    // The text of a save file for data (what saveLoad reads back)
    const saveText = (data) => JSON.stringify({ format: SAVE_FORMAT, version: SAVE_VERSION, data }, null, 1) + "\n";

    const GameShell = {
        SETTINGS_VERSION, DIFFICULTIES, COLORBLIND, SUB_SIZES, DISPLAY_MODES, FRAME_CAPS, CONSENT, GLYPH_SETS, SCHEMA,
        DEFAULT_BINDINGS, defaultSettings, fixField, settingsLoad, effectiveShake, telemetryAllowed, settingsText,
        groupOf, rebind, glyphSet, glyphName, promptBinding, findConflicts, narrationLine,
        FALLBACK_LOCALE, PSEUDO_LOCALE, localeChain, fill, lookup, tr, plural, trPlural, pseudo,
        SAVE_VERSION, SAVE_FORMAT, MIGRATIONS, parseSave, saveMigrate, saveLoad, saveText,
    };

    // Both, not either: MZ's desktop test play (NW.js) may define `module` too, and the plugins need the global
    globalThis.GameShell = GameShell;                                                       // RPG Maker MZ
    if (typeof module === "object" && module && module.exports) module.exports = GameShell; // Node (tests)
})();

// {{FOOTER}}
