// ---------------------------------------------------------------------------
// gameCore.test.js
// Purpose : Unit tests for the engine-free rules in game/js/plugins/GameCore.js (Node's built-in test runner).
// Usage   : python tools/dev.py test        (runs every tests/**/*.test.js)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
const { test } = require("node:test");
const assert = require("node:assert/strict");
const GameCore = require("../game/js/plugins/GameCore.js");

test("each part of the day has its phase", () => {
    assert.equal(GameCore.dayPhase(0), "night");
    assert.equal(GameCore.dayPhase(300), "dawn");
    assert.equal(GameCore.dayPhase(480), "day");
    assert.equal(GameCore.dayPhase(1080), "dusk");
    assert.equal(GameCore.dayPhase(1439), "night");
});

test("the clock wraps around midnight, both ways", () => {
    assert.equal(GameCore.dayPhase(GameCore.MINUTES_PER_DAY + 480), "day");
    assert.equal(GameCore.dayPhase(-60), "night");
});

test("a clock that is not a number is a bug, not a phase", () => {
    assert.throws(() => GameCore.dayPhase(undefined), TypeError);
    assert.throws(() => GameCore.dayPhase("480"), TypeError);
});

// {{FOOTER}}
