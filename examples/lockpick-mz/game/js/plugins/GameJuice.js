// ---------------------------------------------------------------------------
// GameJuice.js
// Purpose : The kit's game-feel ("juice") rules, engine-free: trauma screen shake on smooth value noise, hitstop,
//           easing curves, a 2D follow camera (deadzone, look-ahead), an input buffer, coyote time, a spring with
//           squash and stretch, the flash limiter, hold-to-toggle and auto repeat. Plain JavaScript with no RPG Maker
//           objects, so Node tests it (tests/gameJuice.test.js) against the kit's golden vectors
//           (data/golden/juice.json) and MZ loads it as an ordinary plugin.
// Usage   : in another plugin:  const shake = new GameJuice.Shake({ maxOffset: 12 });  shake.addTrauma(0.5);
//                               const o = shake.update(dt, GameShell.effectiveShake(settings));   // {x, y, angle}
//                               const limiter = new GameJuice.FlashLimiter(); if (limiter.request(nowS)) flash();
//           in a test:          const GameJuice = require("../game/js/plugins/GameJuice.js");
// Notes   : Ports of tools/golden_vectors.py (the spec; the web overlay's src/core/*.ts are the same rules in
//           TypeScript). Park-Miller runs in plain JS numbers: every product stays below 2^53, so no bit operations.
//           MZ already shakes and flashes the screen ($gameScreen.startShake, startFlash): GameAccess.js routes those
//           through the player's settings (effectiveShake, this FlashLimiter). The rest is for your own plugins:
//           MZ's frames are 1/60 s, so pass dt = 1 / 60 per update (verify in RPG Maker MZ), and a hitstop is
//           Hitstop.scaledDt(dt) === 0 for the frames your scene should hold still.
//           Keep it free of $game*, Scene_*, Window_*: anything MZ goes in GameAccess.js or GameMain.js.
//           The last lines make the same file a global (GameJuice) in MZ and a CommonJS module in Node.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/*:
 * @target MZ
 * @plugindesc Lockpick MZ: game-feel rules (engine-free: shake, hitstop, easing, follow camera, buffers, flash limit).
 * @author the user
 *
 * @help GameJuice.js
 *
 * The kit's game-feel rules for Lockpick MZ, kept free of RPG Maker
 * objects so they can be tested outside the editor (python tools/dev.py
 * test) against the kit's golden vectors. GameAccess.js uses the flash
 * limiter for MZ's own Flash Screen; your plugins can use the rest.
 * No plugin commands and no parameters.
 */

(() => {
    "use strict";

    // ---- Tunables -------------------------------------------------------------
    const SHAKE_DEFAULTS = {
        maxOffset: 8.0,     // pixels at full trauma
        maxAngle: 0.05,     // radians at full trauma
        decay: 1.5,         // trauma lost per second
        frequency: 15.0,    // noise samples per second (higher = jitterier)
        seed: 1,
    };
    const FOLLOW_DEFAULTS = {
        deadzoneW: 64.0,    // pixels the target may move left/right before the camera follows
        deadzoneH: 48.0,
        lookahead: 0.25,    // seconds of velocity to look ahead
        smoothing: 8.0,     // 1/s; 0 = snap
        x: 0.0,
        y: 0.0,
    };
    const HITSTOP_MAX_S = 0.25;            // longest freeze one hit (or a flurry) can cause
    const INPUT_BUFFER_S = 0.12;           // how long a press is remembered
    const COYOTE_S = 0.1;
    const SPRING_FREQUENCY = 4.0;          // Hz
    const SPRING_DAMPING = 0.5;            // 0 = wobbles forever, 1 = critically damped
    const SQUASH_MIN = -0.9;               // a stronger stretch than this would flip the sprite
    const FLASH_MAX = 3;                   // full-screen flashes per window (F34: at most 3 per second)
    const FLASH_WINDOW_S = 1.0;
    const AUTO_REPEAT_DELAY_S = 0.35;      // held this long before the first repeat
    const AUTO_REPEAT_INTERVAL_S = 0.15;   // then one repeat this often
    const PM_M = 2147483647;               // Park-Miller modulus (2^31 - 1)
    const PM_A = 16807;
    const EPSILON = 1e-12;

    // ---- Noise and shake ------------------------------------------------------
    // Python-style modulo (the sign of m), so negative inputs match the reference
    const mod = (x, m) => ((x % m) + m) % m;

    // A value in (-1, 1] for integer lattice point i of channel ch
    function lattice(seed, i, ch) {
        let s = mod(seed * 7919 + i * 104729 + ch * 15485863, PM_M);
        if (s === 0) s = 1;
        s = (s * PM_A) % PM_M;
        s = (s * PM_A) % PM_M;
        return (s / (PM_M - 1)) * 2.0 - 1.0;
    }

    // Smooth 1D value noise: lattice values blended with smoothstep (t >= 0)
    function noise(seed, t, ch) {
        const i = Math.floor(t);
        const f = t - i;
        const a = lattice(seed, i, ch);
        const b = lattice(seed, i + 1, ch);
        const u = f * f * (3.0 - 2.0 * f);
        return a + (b - a) * u;
    }

    class Shake {
        constructor(params = {}) {
            const p = { ...SHAKE_DEFAULTS, ...params };
            this.maxOffset = p.maxOffset;
            this.maxAngle = p.maxAngle;
            this.decay = p.decay;
            this.frequency = p.frequency;
            this.seed = p.seed;
            this.trauma = 0;
            this.time = 0;
        }

        // Adds trauma (0..1 after clamping); a negative amount calms the shake
        addTrauma(amount) {
            this.trauma = Math.min(Math.max(this.trauma + amount, 0), 1);
        }

        // Advances time (game time) and returns this frame's {x, y, angle}; intensity is effectiveShake(settings)
        update(dt, intensity = 1.0) {
            this.time += dt;
            this.trauma = Math.max(this.trauma - this.decay * dt, 0);
            const s = this.trauma * this.trauma * intensity;
            const t = this.time * this.frequency;
            return {
                x: this.maxOffset * s * noise(this.seed, t, 0),
                y: this.maxOffset * s * noise(this.seed, t, 1),
                angle: this.maxAngle * s * noise(this.seed, t, 2),
            };
        }
    }

    // ---- Hitstop --------------------------------------------------------------
    class Hitstop {
        constructor(maxS = HITSTOP_MAX_S) {
            this.maxS = maxS;
            this.remaining = 0;
        }

        hit(duration) {
            this.remaining = Math.min(Math.max(this.remaining, duration), this.maxS);
        }

        // The game's delta for this frame (real time in): the frozen part of realDt is removed
        scaledDt(realDt) {
            if (this.remaining <= 0) return realDt;
            const used = Math.min(this.remaining, realDt);
            this.remaining -= used;
            return realDt - used;
        }
    }

    // ---- Easing ---------------------------------------------------------------
    const C1 = 1.70158;
    const C3 = C1 + 1.0;
    const C4 = (2.0 * Math.PI) / 3.0;

    function bounce(t) {
        const n1 = 7.5625;
        const d1 = 2.75;
        if (t < 1.0 / d1) return n1 * t * t;
        if (t < 2.0 / d1) {
            t -= 1.5 / d1;
            return n1 * t * t + 0.75;
        }
        if (t < 2.5 / d1) {
            t -= 2.25 / d1;
            return n1 * t * t + 0.9375;
        }
        t -= 2.625 / d1;
        return n1 * t * t + 0.984375;
    }

    const EASES = {
        linear: (t) => t,
        in_quad: (t) => t * t,
        out_quad: (t) => 1.0 - (1.0 - t) * (1.0 - t),
        in_out_quad: (t) => (t < 0.5 ? 2.0 * t * t : 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0),
        in_cubic: (t) => t * t * t,
        out_cubic: (t) => 1.0 - (1.0 - t) ** 3,
        in_out_cubic: (t) => (t < 0.5 ? 4.0 * t * t * t : 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0),
        in_sine: (t) => 1.0 - Math.cos((t * Math.PI) / 2.0),
        out_sine: (t) => Math.sin((t * Math.PI) / 2.0),
        in_out_sine: (t) => -(Math.cos(Math.PI * t) - 1.0) / 2.0,
        in_back: (t) => C3 * t * t * t - C1 * t * t,
        out_back: (t) => 1.0 + C3 * (t - 1.0) ** 3 + C1 * (t - 1.0) ** 2,
        out_elastic: (t) => (t <= 0.0 ? 0.0 : t >= 1.0 ? 1.0 : 2.0 ** (-10.0 * t) * Math.sin((t * 10.0 - 0.75) * C4) + 1.0),
        out_bounce: bounce,
    };
    const EASE_NAMES = Object.keys(EASES).sort();

    // The eased value for t (clamped to 0..1); an unknown name is a bug, not a curve
    function ease(name, t) {
        if (!Object.prototype.hasOwnProperty.call(EASES, name)) throw new Error(`unknown easing "${name}"`);
        return EASES[name](Math.min(Math.max(t, 0.0), 1.0));
    }

    // ---- Follow camera --------------------------------------------------------
    function followAxis(cam, target, half) {
        if (target > cam + half) return target - half;
        if (target < cam - half) return target + half;
        return cam;
    }

    class FollowCamera {
        constructor(params = {}) {
            const p = { ...FOLLOW_DEFAULTS, ...params };
            this.deadzoneW = p.deadzoneW;
            this.deadzoneH = p.deadzoneH;
            this.lookahead = p.lookahead;
            this.smoothing = p.smoothing;
            this.x = p.x;
            this.y = p.y;
        }

        // Where the camera centers this frame: deadzone, look-ahead along (vx, vy), frame-rate independent smoothing
        update(dt, tx, ty, vx = 0, vy = 0) {
            const dx = followAxis(this.x, tx, this.deadzoneW / 2.0) + vx * this.lookahead;
            const dy = followAxis(this.y, ty, this.deadzoneH / 2.0) + vy * this.lookahead;
            const k = this.smoothing > 0.0 ? 1.0 - Math.exp(-this.smoothing * dt) : 1.0;
            this.x += (dx - this.x) * k;
            this.y += (dy - this.y) * k;
            return { x: this.x, y: this.y };
        }
    }

    // ---- Input buffer and coyote time ----------------------------------------
    class InputBuffer {
        constructor(window = INPUT_BUFFER_S) {
            this.window = window;
            this.pending = new Map();
        }

        press(action) {
            this.pending.set(action, this.window);
        }

        update(dt) {
            for (const action of [...this.pending.keys()].sort()) {
                const left = (this.pending.get(action) || 0) - dt;
                if (left <= EPSILON) this.pending.delete(action);
                else this.pending.set(action, left);
            }
        }

        consume(action) {
            if ((this.pending.get(action) || 0) > 0) {
                this.pending.delete(action);
                return true;
            }
            return false;
        }
    }

    class CoyoteTimer {
        constructor(windowSeconds = COYOTE_S) {
            this.window = Math.max(windowSeconds, 0);   // bad tuning data never makes a negative window
            this.timeLeft = 0;
            this.grounded = false;
            this.consumed = false;
        }

        update(dt, onFloor) {
            if (onFloor) {
                if (!this.grounded) this.consumed = false;   // landed: the next jump is available again
                this.grounded = true;
                this.timeLeft = this.window;
            } else {
                this.grounded = false;
                this.timeLeft = Math.max(this.timeLeft - dt, 0);
            }
        }

        canJump() {
            return !this.consumed && (this.grounded || this.timeLeft > 0);
        }

        consume() {
            this.consumed = true;
            this.timeLeft = 0;
        }
    }

    // ---- Spring and squash ----------------------------------------------------
    class Spring {
        constructor(frequency = SPRING_FREQUENCY, damping = SPRING_DAMPING) {
            this.frequency = frequency;
            this.damping = damping;
            this.x = 0;
            this.v = 0;
            this.target = 0;
        }

        update(dt) {
            const w = 2.0 * Math.PI * this.frequency;
            const a = -w * w * (this.x - this.target) - 2.0 * this.damping * w * this.v;
            this.v += a * dt;
            this.x += this.v * dt;
            return this.x;
        }
    }

    // Volume-keeping scale [sx, sy]: amount > 0 widens and flattens, < 0 stretches
    function squash(amount) {
        const a = Math.max(amount, SQUASH_MIN);
        return [1.0 + a, 1.0 / (1.0 + a)];
    }

    // ---- Flash limiter, hold toggle, auto repeat ------------------------------
    // At most maxFlashes full-screen flashes in any windowS seconds of REAL time; request(now) says yes or no
    class FlashLimiter {
        constructor(maxFlashes = FLASH_MAX, windowS = FLASH_WINDOW_S) {
            this.maxFlashes = maxFlashes;
            this.windowS = windowS;
            this.times = [];
        }

        request(now) {
            this.times = this.times.filter((t) => t > now - this.windowS);
            if (this.times.length < this.maxFlashes) {
                this.times.push(now);
                return true;
            }
            return false;
        }
    }

    // access.hold_to_toggle: a held action (guard, aim) becomes a press-to-flip one
    class HoldToggle {
        constructor() {
            this.active = false;
            this.wasDown = false;
            this.wasToggle = false;
        }

        update(down, toggleMode) {
            if (toggleMode !== this.wasToggle) this.active = false;   // the setting changed: start released
            if (toggleMode) {
                if (down && !this.wasDown) this.active = !this.active;   // each new press flips it
            } else {
                this.active = down;
            }
            this.wasDown = down;
            this.wasToggle = toggleMode;
            return this.active;
        }
    }

    // access.auto_repeat: true on a frame where a held button repeats its press
    class AutoRepeat {
        constructor() {
            this.held = 0;
            this.next = AUTO_REPEAT_DELAY_S;
        }

        update(dt, isHeld) {
            if (!isHeld) {
                this.held = 0;
                this.next = AUTO_REPEAT_DELAY_S;
                return false;
            }
            this.held += dt;
            if (this.held >= this.next) {
                this.next += AUTO_REPEAT_INTERVAL_S;
                return true;
            }
            return false;
        }
    }

    const GameJuice = {
        lattice, noise, Shake, Hitstop, ease, EASE_NAMES, FollowCamera, InputBuffer, CoyoteTimer, Spring, squash,
        FlashLimiter, HoldToggle, AutoRepeat,
        SHAKE_DEFAULTS, FOLLOW_DEFAULTS, HITSTOP_MAX_S, INPUT_BUFFER_S, COYOTE_S, FLASH_MAX, FLASH_WINDOW_S,
    };

    // Both, not either: MZ's desktop test play (NW.js) may define `module` too, and the plugins need the global
    globalThis.GameJuice = GameJuice;                                                       // RPG Maker MZ
    if (typeof module === "object" && module && module.exports) module.exports = GameJuice; // Node (tests)
})();
