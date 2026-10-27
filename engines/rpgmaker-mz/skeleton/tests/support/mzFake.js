// ---------------------------------------------------------------------------
// mzFake.js
// Purpose : Load an MZ plugin in Node with stand-ins for the few RPG Maker objects it touches, so tests can run
//           its glue (commands, hooks) without the editor. A plugin that throws on load fails here first.
// Usage   : const mz = loadPlugin("GameMain", { GameCore }, { startMinutes: "480" });
//           mz.commands.get("LogPhase")({ minutes: "480" });  new mz.Scene_Title().start();  mz.logs
// Notes   : These are fakes, not RPG Maker: they prove your code runs and calls what you meant, not that MZ's real
//           classes behave the same. Add a fake when a plugin uses a new MZ class; keep each one as small as its use.
//           The smoke test (python tools/dev.py smoke) boots the plugin in a browser on the MZ files that
//           setup --from copied in (not yet run against a real MZ project).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGINS = path.resolve(__dirname, "..", "..", "game", "js", "plugins");

// globals: objects the plugin expects (e.g. { GameCore }); params: what PluginManager.parameters returns (strings)
function loadPlugin(name, globals = {}, params = {}) {
    const logs = [];
    const commands = new Map();
    class Scene_Base {
        start() {}
        update() {}
    }
    class Scene_Title extends Scene_Base {}
    const context = {
        console: { log: (...a) => logs.push(a.join(" ")), warn: (...a) => logs.push(a.join(" ")), error: (...a) => logs.push(a.join(" ")) },
        PluginManager: {
            parameters: (plugin) => (plugin === name ? { ...params } : {}),
            registerCommand: (plugin, command, fn) => {
                if (plugin !== name) throw new Error(`registerCommand under "${plugin}", but the file is ${name}.js`);
                commands.set(command, fn);
            },
        },
        Scene_Base,
        Scene_Title,
        ...globals,
    };
    vm.createContext(context);
    const file = path.join(PLUGINS, `${name}.js`);
    vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });
    return { logs, commands, Scene_Title: context.Scene_Title, context };
}

module.exports = { loadPlugin };

// {{FOOTER}}
