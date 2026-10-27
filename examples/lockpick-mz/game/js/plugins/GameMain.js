// ---------------------------------------------------------------------------
// GameMain.js
// Purpose : Lockpick MZ's glue: the lockpicking scene (draws the lock, reads the key), the "Open Lock" plugin command
//           for events, a "Pick a lock" title command to try it, ?autoplay for the smoke test, and the boot marker.
//           The rules and the bots live in GameCore.js (LockpickCore), engine-free.
// Usage   : Plugin Manager: GameCore, then GameMain (python tools/dev.py setup registers both).
//           Event: Plugin Command > GameMain > Open Lock (pins, sweet spot %, seed, result switch); then a Conditional
//           Branch on that switch. Browser: ?autoplay (a careful bot) or ?autoplay=masher.
// Notes   : Console markers for dev.py smoke: BOOT_OK, LOCK_START, LOCK_SET, LOCK_STRIKE, LOCK_OPEN, LOCK_JAMMED.
//           Written in MZ's own style (prototype scenes, aliased hooks); MZ itself has not run it yet: the calls into
//           MZ (Scene_Base, Sprite, Bitmap, SceneManager, the title window) are marked (verify) where unsure.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc Lockpick MZ: the lockpicking scene, its plugin command and a title demo (needs GameCore above it).
 * @author Lockpick MZ
 * @base GameCore
 * @orderAfter GameCore
 *
 * @help GameMain.js
 *
 * A timing minigame: a pick sweeps across a bar; press OK (Enter, Z,
 * Space or a tap) while it is inside the green sweet spot to set a pin.
 * A miss is a strike. Too many strikes, or running out of time, jams the
 * lock. Each set pin makes the pick faster.
 *
 * Plugin command "Open Lock": runs the minigame and turns the result switch
 * ON when the lock opens (OFF when it jams). Check that switch with a
 * Conditional Branch right after the command.
 *
 * The title screen gets a "Pick a lock" command to try it (turn it off with
 * the parameter below).
 *
 * @param titleDemo
 * @text Title demo
 * @desc Add "Pick a lock" to the title screen.
 * @type boolean
 * @default true
 *
 * @command OpenLock
 * @text Open Lock
 * @desc Play the lockpicking minigame; the result goes to a switch.
 *
 * @arg pins
 * @text Pins
 * @desc How many pins to set (1 to 6).
 * @type number
 * @min 1
 * @max 6
 * @default 3
 *
 * @arg zone
 * @text Sweet spot (%)
 * @desc Width of each sweet spot, in percent of the bar (5 to 40). Smaller is harder.
 * @type number
 * @min 5
 * @max 40
 * @default 16
 *
 * @arg seed
 * @text Seed
 * @desc 0 for a new lock every time; any other number always makes the same lock.
 * @type number
 * @default 0
 *
 * @arg switchId
 * @text Result switch
 * @desc Turned ON when the lock opens, OFF when it jams.
 * @type switch
 * @default 0
 */

(() => {
    "use strict";

    const PLUGIN = "GameMain";            // must match this file's name
    const BOOT_MARKER = "BOOT_OK";        // tools/dev.py smoke waits for this console line
    const DONE_FRAMES = 60;               // frames the result stays on screen before the scene closes
    const DEMO = { pins: 3, zone: 0.16, seed: 0, switchId: 0 };
    const COLORS = {
        backdrop: "rgba(10, 8, 16, 0.92)", bar: "#2b2738", spot: "#3fae5a", pick: "#f4e9c8",
        pinSet: "#e8c35a", pinOpen: "#4a4560", text: "#f4e9c8", bad: "#e0605a",
    };

    const params = PluginManager.parameters(PLUGIN);
    const titleDemo = params.titleDemo !== "false";

    function log(...parts) {
        console.log(parts.join(" "));
    }

    function randomSeed() {
        return 1 + Math.floor(Math.random() * 1e9);
    }

    // ?autoplay (careful bot) or ?autoplay=masher, from the page address; none in a normal game
    function autoplay() {
        if (typeof location === "undefined" || !location.search) return null;
        const q = new URLSearchParams(location.search);
        if (!q.has("autoplay")) return null;
        return q.get("autoplay") === "masher" ? "masher" : "timer";
    }

    // ---- The lockpicking scene --------------------------------------------------
    function Scene_Lockpick() {
        this.initialize(...arguments);
    }

    Scene_Lockpick.prototype = Object.create(Scene_Base.prototype);
    Scene_Lockpick.prototype.constructor = Scene_Lockpick;

    // SceneManager.prepareNextScene(config) calls this before create (as Scene_Shop's goods do) (verify)
    Scene_Lockpick.prototype.prepare = function (config) {
        this._config = config;
    };

    Scene_Lockpick.prototype.create = function () {
        Scene_Base.prototype.create.call(this);
        const c = { ...DEMO, ...(this._config || {}) };
        this._seed = c.seed > 0 ? c.seed : randomSeed();
        this._lock = LockpickCore.create({ seed: this._seed, pins: c.pins, zone: c.zone });
        this._bot = c.bot ? (LockpickCore.bots[c.bot] || null) : null;
        this._switchId = c.switchId || 0;
        this._doneFrames = 0;
        this._lastStrikes = 0;
        this._sprite = new Sprite(new Bitmap(Graphics.width, Graphics.height));
        this.addChild(this._sprite);
        log("LOCK_START", `seed=${this._seed}`, `pins=${this._lock.spots.length}`, this._bot ? `bot=${c.bot}` : "");
        this.redraw();
    };

    Scene_Lockpick.prototype.update = function () {
        Scene_Base.prototype.update.call(this);
        const lock = this._lock;
        if (lock.state === "picking") {
            LockpickCore.step(lock, 1 / 60);
            if (lock.state === "picking" && this.wantsPress()) this.pressPick();
            if (lock.state !== "picking") this.finish();
        } else if (++this._doneFrames >= DONE_FRAMES) {
            SceneManager.pop();
        }
        this.redraw();
    };

    Scene_Lockpick.prototype.wantsPress = function () {
        if (this._bot) return this._bot(this._lock);
        return Input.isTriggered("ok") || TouchInput.isTriggered();
    };

    Scene_Lockpick.prototype.pressPick = function () {
        const result = LockpickCore.press(this._lock);
        if (result === "set") {
            SoundManager.playOk();
            log("LOCK_SET", this._lock.pin);
        } else if (result === "strike") {
            SoundManager.playBuzzer();
            log("LOCK_STRIKE", this._lock.strikes);
        }
    };

    Scene_Lockpick.prototype.finish = function () {
        const lock = this._lock;
        const opened = lock.state === "open";
        if (opened) SoundManager.playOk();
        else SoundManager.playBuzzer();
        if (this._switchId > 0 && typeof $gameSwitches !== "undefined" && $gameSwitches) {
            $gameSwitches.setValue(this._switchId, opened);
        }
        log(opened ? "LOCK_OPEN" : "LOCK_JAMMED", `seed=${this._seed}`, `time=${lock.time.toFixed(1)}`,
            `strikes=${lock.strikes}`);
    };

    Scene_Lockpick.prototype.redraw = function () {
        const lock = this._lock;
        const b = this._sprite.bitmap;
        const w = Graphics.width, h = Graphics.height;
        const barX = Math.round(w * 0.12), barW = Math.round(w * 0.76), barY = Math.round(h * 0.45), barH = 36;
        b.clear();
        b.fillRect(0, 0, w, h, COLORS.backdrop);
        b.fontSize = 28;
        b.textColor = COLORS.text;
        b.drawText("Pick the lock", 0, Math.round(h * 0.16), w, 40, "center");
        b.fontSize = 20;
        b.drawText("Press OK when the pick is in the green", 0, Math.round(h * 0.16) + 44, w, 32, "center");
        b.fillRect(barX, barY, barW, barH, COLORS.bar);
        const spot = LockpickCore.spot(lock);
        if (spot) {
            b.fillRect(barX + Math.round((spot.center - spot.width / 2) * barW), barY, Math.round(spot.width * barW), barH, COLORS.spot);
        }
        b.fillRect(barX + Math.round(lock.pick * barW) - 2, barY - 10, 4, barH + 20, COLORS.pick);
        const pins = lock.spots.length;
        for (let i = 0; i < pins; i++) {
            const x = Math.round(w / 2 + (i - (pins - 1) / 2) * 44) - 14;
            b.fillRect(x, barY + barH + 34, 28, 28, i < lock.pin ? COLORS.pinSet : COLORS.pinOpen);
        }
        b.fontSize = 20;
        const left = Math.max(0, lock.options.timeLimit - lock.time);
        b.drawText(`Strikes ${lock.strikes} / ${lock.options.strikes}     Time ${left.toFixed(1)} s`, 0, barY + barH + 80, w, 32, "center");
        if (lock.state !== "picking") {
            b.fontSize = 32;
            b.textColor = lock.state === "open" ? COLORS.pinSet : COLORS.bad;
            b.drawText(lock.state === "open" ? "Click! The lock opens." : "The lock jams.", 0, Math.round(h * 0.76), w, 44, "center");
        }
    };

    globalThis.Scene_Lockpick = Scene_Lockpick;   // other plugins and events can push it too

    // ---- The plugin command -----------------------------------------------------
    PluginManager.registerCommand(PLUGIN, "OpenLock", (args) => {
        const config = {
            pins: Math.min(6, Math.max(1, Number(args.pins) || DEMO.pins)),
            zone: Math.min(40, Math.max(5, Number(args.zone) || DEMO.zone * 100)) / 100,
            seed: Number(args.seed) || 0,
            switchId: Number(args.switchId) || 0,
        };
        SceneManager.push(Scene_Lockpick);
        SceneManager.prepareNextScene(config);
    });

    // ---- The title screen: a demo command, autoplay and the boot marker -------------
    if (titleDemo) {
        const makeCommandList = Window_TitleCommand.prototype.makeCommandList;
        Window_TitleCommand.prototype.makeCommandList = function () {
            makeCommandList.call(this);
            this.addCommand("Pick a lock", "lockpick");   // the window shows 3 rows: a 4th scrolls (verify)
        };
        const createCommandWindow = Scene_Title.prototype.createCommandWindow;
        Scene_Title.prototype.createCommandWindow = function () {
            createCommandWindow.call(this);
            this._commandWindow.setHandler("lockpick", () => {
                this._commandWindow.close();
                SceneManager.push(Scene_Lockpick);
                SceneManager.prepareNextScene({ ...DEMO });
            });
        };
    }

    let booted = false;
    const titleStart = Scene_Title.prototype.start;
    Scene_Title.prototype.start = function () {
        titleStart.call(this);
        if (booted) return;
        booted = true;
        log(BOOT_MARKER, "Lockpick MZ");
        const bot = autoplay();
        if (bot) {
            SceneManager.push(Scene_Lockpick);
            SceneManager.prepareNextScene({ ...DEMO, seed: 8, bot });   // seed 8: the careful bot opens it, the masher jams
        }
    };
})();
