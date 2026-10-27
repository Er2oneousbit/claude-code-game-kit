// ---------------------------------------------------------------------------
// lockpick.test.js
// Purpose : The lock's rules (game/js/plugins/GameCore.js) and the scenario pair (SOP-14 step 6): a careful player
//           opens nearly every lock, sloppier copies of it still do, and a key-masher almost never does.
// Usage   : python tools/dev.py test
// Notes   : 40 seeds and gaps, not one seed and exact counts (SOP-14). Measured 2026-10-23: careful 40/40,
//           sloppy (lag 10, inner 0.9) 40/40, sloppier (14, 1.0) 37/40, masher 1/40.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const C = require("../game/js/plugins/GameCore.js");

const SEEDS = Array.from({ length: 40 }, (_, i) => i + 1);
const opened = (bot) => SEEDS.filter((seed) => C.play(C.create({ seed }), bot).state === "open").length;

test("a press inside the sweet spot sets the pin; outside it is a strike", () => {
    const lock = C.create({ seed: 3, pins: 2 });
    lock.pick = C.spot(lock).center;
    assert.equal(C.press(lock), "set");
    assert.equal(lock.pin, 1);
    lock.pick = C.spot(lock).center > 0.5 ? 0.02 : 0.98;
    assert.equal(C.press(lock), "strike");
    assert.equal(lock.strikes, 1);
});

test("setting the last pin opens the lock; nothing more can be pressed", () => {
    const lock = C.create({ seed: 5, pins: 1 });
    lock.pick = C.spot(lock).center;
    assert.equal(C.press(lock), "open");
    assert.equal(lock.state, "open");
    assert.equal(C.press(lock), "done");
});

test("too many strikes jam the lock", () => {
    const lock = C.create({ seed: 5, strikes: 2 });
    lock.pick = C.spot(lock).center > 0.5 ? 0.02 : 0.98;
    assert.equal(C.press(lock), "strike");
    assert.equal(C.press(lock), "jammed");
    assert.equal(lock.state, "jammed");
});

test("waiting out the clock jams the lock", () => {
    const lock = C.create({ seed: 1, timeLimit: 2 });
    for (let i = 0; i < 200 && lock.state === "picking"; i++) C.step(lock, 1 / 60);
    assert.equal(lock.state, "jammed");
    assert.ok(lock.time >= 2);
});

test("the pick bounces between the ends of the bar and speeds up after each pin", () => {
    const lock = C.create({ seed: 2 });
    for (let i = 0; i < 600; i++) {
        C.step(lock, 1 / 60);
        assert.ok(lock.pick >= 0 && lock.pick <= 1, `pick ${lock.pick}`);
    }
    const fresh = C.create({ seed: 2 });
    const before = fresh.speed;
    fresh.pick = C.spot(fresh).center;
    C.press(fresh);
    assert.ok(fresh.speed > before);
});

test("one seed, one lock; every sweet spot fits on the bar", () => {
    assert.deepEqual(C.create({ seed: 9 }).spots, C.create({ seed: 9 }).spots);
    for (const seed of SEEDS) {
        for (const s of C.create({ seed }).spots) {
            assert.ok(s.center - s.width / 2 >= C.DEFAULTS.margin - 1e-9 && s.center + s.width / 2 <= 1 - C.DEFAULTS.margin + 1e-9);
        }
    }
});

test("bad options are an error, not a strange lock", () => {
    assert.throws(() => C.create({ pins: 0 }), RangeError);
    assert.throws(() => C.create({ zone: 0.95 }), RangeError);
    assert.throws(() => C.step(C.create(), -1), RangeError);
});

test("the pair: careful players open locks, sloppy ones mostly do, mashing does not", () => {
    const careful = opened(C.bots.timer);
    const sloppy = opened(C.bots.timerWith(10, 0.9));
    const masher = opened(C.bots.masher);
    console.log(`[pair] careful ${careful}/40, sloppy ${sloppy}/40, masher ${masher}/40`);
    assert.ok(careful >= 36, `careful opened only ${careful} of 40`);
    assert.ok(sloppy >= 34, `a slightly sloppy player opened only ${sloppy} of 40: the sweet spots are too tight`);
    assert.ok(masher <= 4, `mashing opened ${masher} of 40: the lock rewards spamming the key`);
});
