// ---------------------------------------------------------------------------
// gameJuice.test.js
// Purpose : Runs every case of data/golden/juice.json through game/js/plugins/GameJuice.js (noise, shake, hitstop,
//           ease, follow camera, input buffer, coyote time, spring, squash, flash limiter), plus the two juice
//           helpers the vectors do not cover (hold toggle, auto repeat). Also loads the plugin the way MZ does.
// Usage   : python tools/dev.py test
// Notes   : One test per case. A case type this file does not know FAILS, so a new vector type added to
//           tools/golden_vectors.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const GameJuice = require("../game/js/plugins/GameJuice.js");
const { loadPlugin } = require("./support/mzFake.js");
const { expectClose, runGolden, checkedCount } = require("./support/golden.js");

function steps(c, handlers) {
    c.steps.forEach((step, i) => {
        if (!Object.prototype.hasOwnProperty.call(handlers, step.call)) assert.fail(`step ${i}: unknown call ${step.call}`);
        handlers[step.call](step, `step ${i}`);
    });
}

const RUNNERS = {
    noise: (c, tol) => {
        c.points.forEach(([seed, t, ch, want], i) => expectClose(GameJuice.noise(seed, t, ch), want, tol, `point ${i}`));
    },
    shake: (c, tol) => {
        const p = c.params;
        const s = new GameJuice.Shake({ maxOffset: p.max_offset, maxAngle: p.max_angle, decay: p.decay, frequency: p.frequency, seed: p.seed });
        steps(c, {
            add_trauma: (step) => s.addTrauma(step.a),
            update: (step, w) => {
                const o = s.update(step.dt, step.intensity);
                expectClose({ x: o.x, y: o.y, angle: o.angle, trauma: s.trauma }, step.expect, tol, w);
            },
        });
    },
    hitstop: (c, tol) => {
        const h = new GameJuice.Hitstop(c.params.max_s);
        steps(c, {
            hit: (step) => h.hit(step.duration),
            scaled_dt: (step, w) => expectClose({ dt: h.scaledDt(step.dt), remaining: h.remaining }, step.expect, tol, w),
        });
    },
    ease: (c, tol) => {
        c.points.forEach(([name, t, want], i) => expectClose(GameJuice.ease(name, t), want, tol, `point ${i} ${name}(${t})`));
    },
    follow: (c, tol) => {
        const p = c.params;
        const f = new GameJuice.FollowCamera({ deadzoneW: p.deadzone_w, deadzoneH: p.deadzone_h, lookahead: p.lookahead,
                                               smoothing: p.smoothing, x: p.x, y: p.y });
        steps(c, { update: (step, w) => expectClose(f.update(step.dt, step.tx, step.ty, step.vx, step.vy), step.expect, tol, w) });
    },
    input_buffer: (c, tol) => {
        const b = new GameJuice.InputBuffer(c.params.window_s);
        steps(c, {
            press: (step) => b.press(step.action),
            update: (step) => b.update(step.dt),
            consume: (step, w) => expectClose({ result: b.consume(step.action) }, step.expect, tol, w),
        });
    },
    coyote: (c, tol) => {
        const t = new GameJuice.CoyoteTimer(c.params.window_s);
        steps(c, {
            update: (step) => t.update(step.dt, step.on_floor),
            consume: () => t.consume(),
            can_jump: (step, w) => expectClose({ result: t.canJump() }, step.expect, tol, w),
        });
    },
    spring: (c, tol) => {
        const s = new GameJuice.Spring(c.params.frequency, c.params.damping);
        s.x = c.params.x;
        s.v = c.params.v;
        s.target = c.params.target;
        steps(c, { update: (step, w) => expectClose({ x: s.update(step.dt), v: s.v }, step.expect, tol, w) });
    },
    squash: (c, tol) => {
        c.points.forEach(([a, sx, sy], i) => expectClose(GameJuice.squash(a), [sx, sy], tol, `point ${i}`));
    },
    flash_limiter: (c, tol) => {
        const fl = new GameJuice.FlashLimiter(c.params.max_flashes, c.params.window_s);
        steps(c, { request: (step, w) => expectClose({ result: fl.request(step.now) }, step.expect, tol, w) });
    },
};

const { run } = runGolden(test, "juice.json", RUNNERS);

test("a case type with no runner fails instead of passing silently", () => {
    assert.throws(() => run({ type: "juice_made_up", name: "x", steps: [] }), /unknown case type/);
});

test("an unknown easing is an error, not a curve", () => {
    assert.throws(() => GameJuice.ease("in_wobble", 0.5), /unknown easing/);
    assert.throws(() => GameJuice.ease("constructor", 0.5), /unknown easing/);
});

test("hold to toggle: held in hold mode, flips on each press in toggle mode, starts released on a mode change", () => {
    const h = new GameJuice.HoldToggle();
    assert.deepEqual([h.update(true, false), h.update(false, false)], [true, false]);
    assert.deepEqual([h.update(true, true), h.update(false, true), h.update(true, true), h.update(false, true)],
                     [true, true, false, false]);
    h.update(true, true);
    assert.equal(h.update(true, false), true);    // back to hold mode while held: follows the button
    assert.equal(h.update(false, false), false);
});

test("auto repeat: the first repeat after the delay, then one per interval, none once released", () => {
    const r = new GameJuice.AutoRepeat();
    const dt = 0.05;
    const repeats = [];
    for (let i = 1; i <= 14; i++) if (r.update(dt, true)) repeats.push(i * dt);
    // within one frame of 0.35, 0.5, 0.65 s (sums of 0.05 are not exact in binary)
    assert.equal(repeats.length, 3, String(repeats));
    [0.35, 0.5, 0.65].forEach((want, i) => assert.ok(repeats[i] >= want - 1e-9 && repeats[i] <= want + dt + 1e-9, String(repeats)));
    assert.equal(r.update(dt, false), false);
    assert.equal(r.update(0.3, true), false);   // the delay starts again
});

test("GameJuice loads as an MZ plugin (no module, no require): it sets the global and logs nothing", () => {
    const mz = loadPlugin("GameJuice");
    assert.equal(typeof mz.context.GameJuice.Shake, "function");
    assert.equal(typeof mz.context.GameJuice.FlashLimiter, "function");
    assert.deepEqual(mz.logs, []);
});

// Runs last (node:test runs a file's tests in order): zero values means the vectors never reached the rules
test("golden values were checked", (t) => {
    assert.ok(checkedCount() > 0, "no golden values were compared");
    t.diagnostic(`checked ${checkedCount()} golden values from juice.json`);
});

// {{FOOTER}}
