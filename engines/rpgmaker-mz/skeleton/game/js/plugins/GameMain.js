// ---------------------------------------------------------------------------
// GameMain.js
// Purpose : The MZ glue for {{GAME_NAME}}: plugin commands, scene hooks and the boot marker. The rules live in
//           GameCore.js (engine-free); this file only connects them to RPG Maker.
// Usage   : Plugin Manager: GameCore first, then GameMain (python tools/dev.py setup registers both).
//           Event command "Plugin Command" > GameMain > Log Phase.
// Notes   : Logs BOOT_OK when the title screen starts: `dev.py smoke` waits for it. Plugin parameters arrive as
//           strings: parse them here. Hooks call the original method (alias) so other plugins keep working.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc {{GAME_NAME}}: plugin commands and hooks (needs GameCore above it).
 * @author {{AUTHOR}}
 * @base GameCore
 * @orderAfter GameCore
 *
 * @help GameMain.js
 *
 * Connects the rules in GameCore.js to RPG Maker MZ.
 *
 * Plugin command "Log Phase": writes the time of day for a clock value to
 * the console (F8 in a test play), a starting point for your own commands.
 *
 * @param startMinutes
 * @text Start time (minutes)
 * @desc The clock at the start of the game, in minutes after midnight.
 * @type number
 * @min 0
 * @max 1439
 * @default 480
 *
 * @command LogPhase
 * @text Log Phase
 * @desc Write the time of day for a clock value to the console.
 *
 * @arg minutes
 * @text Minutes
 * @desc Minutes after midnight.
 * @type number
 * @min 0
 * @default 480
 */

(() => {
    "use strict";

    const PLUGIN = "GameMain";            // must match this file's name (MZ looks plugins up by it)
    const BOOT_MARKER = "BOOT_OK";        // tools/dev.py smoke waits for this console line

    const params = PluginManager.parameters(PLUGIN);
    const startMinutes = Number(params.startMinutes || 480);

    PluginManager.registerCommand(PLUGIN, "LogPhase", (args) => {
        const minutes = Number(args.minutes);
        console.log(`[game] ${minutes} min: ${GameCore.dayPhase(minutes)}`);
    });

    // The title screen is the first scene with the database loaded: say so once, for the smoke test
    let booted = false;
    const titleStart = Scene_Title.prototype.start;
    Scene_Title.prototype.start = function () {
        titleStart.call(this);
        if (!booted) {
            booted = true;
            console.log(`${BOOT_MARKER} {{GAME_NAME}} (start ${GameCore.dayPhase(startMinutes)})`);
        }
    };
})();

// {{FOOTER}}
