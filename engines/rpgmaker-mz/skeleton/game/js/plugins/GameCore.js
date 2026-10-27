// ---------------------------------------------------------------------------
// GameCore.js
// Purpose : The game's rules, engine-free: plain JavaScript with no RPG Maker objects in it, so Node runs it in
//           tests (tests/gameCore.test.js) and MZ loads it as an ordinary plugin. GameMain.js is the MZ glue.
// Usage   : in another plugin:  const phase = GameCore.dayPhase(minutes);
//           in a test:          const GameCore = require("../game/js/plugins/GameCore.js");
// Notes   : Keep it free of $game*, Scene_*, Window_*, Input, Graphics: anything MZ goes in GameMain.js.
//           The last lines make the same file a global (GameCore) in MZ and a CommonJS module in Node.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc {{GAME_NAME}}: the game's rules (engine-free; load before GameMain).
 * @author {{AUTHOR}}
 *
 * @help GameCore.js
 *
 * The rules of {{GAME_NAME}}, kept free of RPG Maker objects so they can be
 * tested outside the editor (python tools/dev.py test). GameMain.js uses them.
 * No plugin commands and no parameters.
 */

(() => {
    "use strict";

    // ---- Tunables -------------------------------------------------------------
    const PHASES = [            // [first minute of the day, name]; a day is 1440 minutes
        [0, "night"],
        [300, "dawn"],
        [420, "day"],
        [1080, "dusk"],
        [1200, "night"],
    ];
    const MINUTES_PER_DAY = 1440;

    // The time of day for a clock in minutes (any whole number; it wraps around midnight)
    function dayPhase(minutes) {
        if (!Number.isFinite(minutes)) throw new TypeError(`minutes must be a number, got ${minutes}`);
        const m = ((Math.floor(minutes) % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
        let name = PHASES[0][1];
        for (const [start, phase] of PHASES) if (m >= start) name = phase;
        return name;
    }

    const GameCore = { dayPhase, MINUTES_PER_DAY };

    // Both, not either: MZ's desktop test play (NW.js) may define `module` too, and the plugins need the global
    globalThis.GameCore = GameCore;                                                       // RPG Maker MZ
    if (typeof module === "object" && module && module.exports) module.exports = GameCore; // Node (tests)
})();

// {{FOOTER}}
