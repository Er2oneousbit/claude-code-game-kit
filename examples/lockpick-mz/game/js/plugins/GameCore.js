// ---------------------------------------------------------------------------
// GameCore.js
// Purpose : Lockpick MZ's rules, engine-free: a lock with pins, a pick that sweeps across a bar, presses that set a
//           pin inside its sweet spot or cost a strike, and two bots (a timer and a masher) for the scenario pair.
//           Plain JavaScript with no RPG Maker objects, so Node runs it in tests; GameMain.js is the MZ glue.
// Usage   : const lock = LockpickCore.create({ seed: 7, pins: 3 });
//           each frame: LockpickCore.step(lock, 1 / 60);  on a key press: LockpickCore.press(lock)
//           lock.state: "picking" | "open" | "jammed";  a bot: LockpickCore.bots.timer(lock) -> press this frame?
// Notes   : Seeded (mulberry32), so a lock replays from its seed. The pick moves on a triangle wave between 0 and 1;
//           each set pin moves the next sweet spot and speeds the pick up. The last lines make the same file a
//           global (LockpickCore) in MZ and a CommonJS module in Node.
//
// Pseudocode:
//   create: seed -> one sweet spot per pin (center, width); pick at 0 moving right; strikes 0; time 0
//   step: time += dt; pick += direction * speed * dt, bouncing at 0 and 1; past the time limit -> jammed
//   press: pick inside the current pin's spot -> set it (all set: open), else a strike (too many: jammed)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc Lockpick MZ: the lock's rules and its bots (engine-free; load before GameMain).
 * @author Lockpick MZ
 *
 * @help GameCore.js
 *
 * The rules of the lockpicking minigame, kept free of RPG Maker objects so
 * they can be tested outside the editor (python tools/dev.py test).
 * GameMain.js draws the lock and reads the keys. No plugin commands and no
 * parameters here.
 */

(() => {
    "use strict";

    // ---- Tunables -------------------------------------------------------------
    const DEFAULTS = {
        pins: 3,             // pins to set
        zone: 0.16,          // width of a sweet spot, as a share of the bar (0..1)
        speed: 0.9,          // bar widths per second for the first pin
        speedUp: 1.25,       // the pick moves this much faster after each set pin
        strikes: 3,          // misses allowed before the lock jams
        timeLimit: 30,       // seconds before the lock jams
        margin: 0.1,         // no sweet spot within this of either end (the pick turns there)
    };
    const BOT = {
        timerLag: 6,         // frames the timer bot reacts late (a person, not a perfect machine)
        timerInner: 0.55,    // the timer presses only in this share of the spot's middle (it allows for its lag)
        mashEvery: 8,        // the masher presses every N frames, wherever the pick is
    };

    // mulberry32: a tiny seeded PRNG, the same numbers in Node and in every browser
    function rng(seed) {
        let a = seed >>> 0;
        return () => {
            a = (a + 0x6d2b79f5) >>> 0;
            let t = a;
            t = Math.imul(t ^ (t >>> 15), t | 1);
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function create(options = {}) {
        const o = { ...DEFAULTS, ...options };
        for (const k of ["pins", "zone", "speed", "speedUp", "strikes", "timeLimit"]) {
            if (!(Number.isFinite(o[k]) && o[k] > 0)) throw new RangeError(`lock option ${k} must be a positive number, got ${o[k]}`);
        }
        if (o.zone >= 1 - 2 * o.margin) throw new RangeError(`zone ${o.zone} does not fit on the bar`);
        const random = rng(Number.isFinite(o.seed) ? o.seed : 1);
        const spots = [];
        for (let i = 0; i < Math.round(o.pins); i++) {
            const half = o.zone / 2;
            const center = o.margin + half + random() * (1 - 2 * o.margin - o.zone);
            spots.push({ center, width: o.zone });
        }
        return {
            options: o, spots, pin: 0, pick: 0, direction: 1, speed: o.speed, strikes: 0, time: 0,
            state: "picking", frames: 0, history: [],
        };
    }

    // The current pin's sweet spot, or null once the lock is done
    function spot(lock) {
        return lock.state === "picking" ? lock.spots[lock.pin] : null;
    }

    function inSpot(lock, at = lock.pick) {
        const s = spot(lock);
        return !!s && Math.abs(at - s.center) <= s.width / 2;
    }

    function step(lock, dt) {
        if (lock.state !== "picking") return lock.state;
        if (!(dt >= 0)) throw new RangeError(`dt must be 0 or more, got ${dt}`);
        lock.time += dt;
        lock.frames += 1;
        let p = lock.pick + lock.direction * lock.speed * dt;
        while (p > 1 || p < 0) {             // bounce off the ends of the bar
            if (p > 1) { p = 2 - p; lock.direction = -1; }
            if (p < 0) { p = -p; lock.direction = 1; }
        }
        lock.pick = p;
        lock.history.push(p);
        if (lock.history.length > 120) lock.history.shift();
        if (lock.time >= lock.options.timeLimit) lock.state = "jammed";
        return lock.state;
    }

    // One press of the pick. Returns what it did: "set", "open", "strike", "jammed", or "done" (nothing to press)
    function press(lock) {
        if (lock.state !== "picking") return "done";
        if (inSpot(lock)) {
            lock.pin += 1;
            if (lock.pin >= lock.spots.length) {
                lock.state = "open";
                return "open";
            }
            lock.speed *= lock.options.speedUp;
            return "set";
        }
        lock.strikes += 1;
        if (lock.strikes >= lock.options.strikes) {
            lock.state = "jammed";
            return "jammed";
        }
        return "strike";
    }

    // A careful player: sees the pick `lag` frames late, so it reads the pick's motion and presses where the pick
    // will be by then (seen position plus its visible speed over the lag), only in the middle `inner` of the spot.
    // A bigger lag or inner makes a sloppier player (the "sloppy copies" a level must survive, SOP-14 step 6).
    function timerBot(lag, inner) {
        return (lock) => {
            const s = spot(lock);
            const h = lock.history;
            if (!s || h.length <= lag + 1) return false;
            const seen = h[h.length - 1 - lag];
            const before = h[h.length - 2 - lag];
            const moving = Math.sign(seen - before) || lock.direction;
            const guess = seen + moving * lock.speed * (lag / 60);
            return guess >= 0 && guess <= 1 && Math.abs(guess - s.center) <= (s.width / 2) * inner;
        };
    }

    // Bots: called once per frame after step(); true means press now. They see what a player sees.
    const bots = {
        timer: timerBot(BOT.timerLag, BOT.timerInner),
        timerWith: timerBot,
        // Presses every few frames, wherever the pick is (a player hammering the key)
        masher(lock) {
            return spot(lock) !== null && lock.frames % BOT.mashEvery === 0;
        },
    };

    // A whole lock played by a bot at a fixed frame rate (tests and autoplay). Returns the finished lock.
    function play(lock, bot, fps = 60) {
        const dt = 1 / fps;
        while (lock.state === "picking") {
            step(lock, dt);
            if (lock.state === "picking" && bot(lock)) press(lock);
        }
        return lock;
    }

    const LockpickCore = { DEFAULTS, BOT, rng, create, spot, inSpot, step, press, bots, play };

    // Both, not either: MZ's desktop test play (NW.js) may define `module` too, and the plugins need the global
    globalThis.LockpickCore = LockpickCore;                                                       // RPG Maker MZ
    if (typeof module === "object" && module && module.exports) module.exports = LockpickCore;    // Node (tests)
})();
