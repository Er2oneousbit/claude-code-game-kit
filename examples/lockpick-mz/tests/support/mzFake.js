// ---------------------------------------------------------------------------
// mzFake.js
// Purpose : Load an MZ plugin in Node with stand-ins for the few RPG Maker objects it touches, so tests can run
//           its glue (commands, hooks, a scene's update loop) without the editor. A plugin that throws on load fails
//           here first.
// Usage   : const mz = loadPlugin("GameMain", { LockpickCore }, { titleDemo: "true" }, { search: "?autoplay" });
//           mz.commands.get("OpenLock")({ pins: "3" });  mz.runScene(200);  mz.logs  mz.switches
// Notes   : These are fakes, not RPG Maker: they prove the code runs and calls what it means to, not that MZ's real
//           classes behave the same. Each fake is as small as this game's use of it, in MZ's prototype style.
//           The smoke test (python tools/dev.py smoke) boots the plugin in a browser on the MZ files that
//           setup --from copied in (not yet run against a real MZ project).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGINS = path.resolve(__dirname, "..", "..", "game", "js", "plugins");

function loadPlugin(name, globals = {}, params = {}, location = { search: "" }) {
    const logs = [];
    const commands = new Map();
    const scenes = { stack: [], prepared: null, pops: 0 };
    const switches = new Map();
    const input = { ok: false };

    function Scene_Base() { this.initialize(...arguments); }
    Scene_Base.prototype.initialize = function () { this.children = []; };
    Scene_Base.prototype.create = function () {};
    Scene_Base.prototype.start = function () {};
    Scene_Base.prototype.update = function () {};
    Scene_Base.prototype.addChild = function (c) { this.children.push(c); return c; };

    function Scene_Title() { this.initialize(...arguments); }
    Scene_Title.prototype = Object.create(Scene_Base.prototype);
    Scene_Title.prototype.constructor = Scene_Title;
    Scene_Title.prototype.createCommandWindow = function () {
        const handlers = {};
        this._commandWindow = { handlers, setHandler: (s, fn) => { handlers[s] = fn; }, close: () => {} };
    };

    function Window_TitleCommand() { this.list = []; }
    Window_TitleCommand.prototype.makeCommandList = function () {
        this.addCommand("New Game", "newGame");
        this.addCommand("Continue", "continue");
        this.addCommand("Options", "options");
    };
    Window_TitleCommand.prototype.addCommand = function (text, symbol) { this.list.push({ text, symbol }); };

    function Bitmap(width, height) { this.width = width; this.height = height; this.calls = 0; }
    Bitmap.prototype.clear = function () { this.calls++; };
    Bitmap.prototype.fillRect = function (x, y, w, h, color) {
        if (![x, y, w, h].every(Number.isFinite)) throw new Error(`fillRect with ${[x, y, w, h]}`);
        this.calls++;
    };
    Bitmap.prototype.drawText = function (text) {
        if (typeof text !== "string") throw new Error(`drawText with ${text}`);
        this.calls++;
    };
    function Sprite(bitmap) { this.bitmap = bitmap; }

    const context = {
        console: { log: (...a) => logs.push(a.join(" ")), warn: (...a) => logs.push(a.join(" ")), error: (...a) => logs.push("ERROR " + a.join(" ")) },
        location,
        URLSearchParams,
        Math, Number, JSON, Object, Array, String, Error, RangeError, TypeError,
        PluginManager: {
            parameters: (plugin) => (plugin === name ? { ...params } : {}),
            registerCommand: (plugin, command, fn) => {
                if (plugin !== name) throw new Error(`registerCommand under "${plugin}", but the file is ${name}.js`);
                commands.set(command, fn);
            },
        },
        SceneManager: {
            push: (cls) => scenes.stack.push(cls),
            prepareNextScene: (...a) => { scenes.prepared = a; },
            pop: () => { scenes.pops++; },
        },
        Scene_Base, Scene_Title, Window_TitleCommand, Bitmap, Sprite,
        Graphics: { width: 816, height: 624 },
        Input: { isTriggered: (k) => k === "ok" && input.ok },
        TouchInput: { isTriggered: () => false },
        SoundManager: { playOk() {}, playBuzzer() {} },
        $gameSwitches: { setValue: (id, v) => switches.set(id, v) },
        ...globals,
    };
    vm.createContext(context);
    const file = path.join(PLUGINS, `${name}.js`);
    vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });

    // Make the scene last pushed, prepare it the way SceneManager does, and update it until it pops (or `frames` pass)
    function runScene(frames = 3600) {
        const Cls = scenes.stack[scenes.stack.length - 1];
        const scene = new Cls();
        if (scenes.prepared && scene.prepare) scene.prepare(...scenes.prepared);
        scene.create();
        scene.start();
        const popsBefore = scenes.pops;
        let n = 0;
        while (scenes.pops === popsBefore && n++ < frames) scene.update();
        return scene;
    }

    return { logs, commands, scenes, switches, input, runScene, context };
}

module.exports = { loadPlugin };
