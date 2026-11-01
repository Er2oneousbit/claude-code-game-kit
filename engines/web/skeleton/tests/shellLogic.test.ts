// ---------------------------------------------------------------------------
// shellLogic.test.ts
// Purpose : Unit tests for the shell's engine-free helpers that the golden vectors do not cover: the rotating
//           game log, crash files, consent-gated telemetry, the dialogue reader, hold-to-toggle, binding
//           conflicts and the key / gamepad names the input layer produces.
// Usage   : python tools/dev.py test
// Notes   : No browser, no Phaser: everything runs on MemoryStore.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { DEFAULT_BINDINGS, findConflicts, type Bindings } from "../src/core/bindings";
import { cueAt, dialogueFrom, revealCount, shouldShow } from "../src/core/dialogue";
import { HoldToggle } from "../src/core/holdToggle";
import { defaultSettings, telemetryAllowed } from "../src/core/settings";
import { MemoryStore } from "../src/core/textStore";
import { GameLog, LOG_FILE, LOG_KEEP, TELEMETRY_FILE, Telemetry, crashText, csvField, stamp, writeCrash } from "../src/core/userData";
import { keyName, padButtonName, padDevice } from "../src/shell/input";

describe("GameLog", () => {
  it("starts each log with the version and a timestamp", () => {
    const store = new MemoryStore();
    new GameLog(store, "Game 1.2.3", new Date("2026-11-01T10:00:00Z"));
    expect(store.read(LOG_FILE)!.split("\n")[0]).toBe("Game 1.2.3 2026-11-01T10:00:00.000Z");
  });

  it("keeps LOG_KEEP older logs and drops the oldest", () => {
    const store = new MemoryStore();
    for (let run = 1; run <= LOG_KEEP + 3; run++) {
      const log = new GameLog(store, `run ${run}`);
      log.append(`line of run ${run}`);
      log.flush();
    }
    const logs = store.list("logs/");
    expect(logs.length).toBe(LOG_KEEP + 1);
    expect(store.read(LOG_FILE)).toContain(`line of run ${LOG_KEEP + 3}`);
    expect(store.read(`logs/game.${LOG_KEEP}.log`)).toContain("line of run 3");
  });

  it("keeps a tail in memory for crash and bug reports", () => {
    const log = new GameLog(new MemoryStore(), "g");
    for (let i = 0; i < 50; i++) log.append(`l${i}`);
    expect(log.tail(3)).toEqual(["l47", "l48", "l49"]);
  });
});

describe("crash files", () => {
  it("hold the version, seed, error, stack and log tail", () => {
    const text = crashText({ header: "Game 0.1.0", error: "boom", stack: "at x", seed: 42, tail: ["a", "b"] });
    for (const part of ["Game 0.1.0", "seed: 42", "error: boom", "at x", "a\nb"]) expect(text).toContain(part);
  });

  it("are named crashes/crash_<timestamp>.txt", () => {
    const store = new MemoryStore();
    const name = writeCrash(store, { header: "g", error: "e", tail: [] }, new Date("2026-11-01T09:05:03.042Z"));
    expect(name).toBe("crashes/crash_20261101_090503_042.txt");
    expect(stamp(new Date("2026-11-01T09:05:03.042Z"))).toBe("20261101_090503_042");
  });
});

describe("Telemetry", () => {
  it("writes nothing until the player says yes", () => {
    const store = new MemoryStore();
    const s = defaultSettings();
    const tel = new Telemetry(store, () => telemetryAllowed(s));
    expect(tel.event("screen", "title")).toBe(false);
    s.telemetry.consent = "no";
    expect(tel.event("screen", "title")).toBe(false);
    expect(store.read(TELEMETRY_FILE)).toBeNull();
    s.telemetry.consent = "yes";
    expect(tel.event("screen", "title, then menu")).toBe(true);
    const lines = store.read(TELEMETRY_FILE)!.trim().split("\n");
    expect(lines[0]).toBe("time,event,detail");
    expect(lines[1]).toMatch(/^\d{4}-.*Z,screen,"title, then menu"$/);
  });

  it("escapes CSV fields", () => {
    expect(csvField("plain")).toBe("plain");
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
  });
});

describe("dialogue reader", () => {
  const raw = {
    version: 1, locale: "en", future_field: { anything: true },
    lines: {
      a: { speaker: "s", name: "S", text: "Hey", kind: "line", duration_s: 0.3, reveal: [{ i: 0, t: 0 }, { i: 1, t: 0.1 }, { i: 2, t: 0.2 }],
        cues: [{ start: 0, end: 0.3, lines: ["Hey"] }], new_field: 1 },
      b: { speaker: "s", text: "Bark", kind: "bark" },
    },
    captions: { hit: { text: "[thud]", min_s: 0.5 } },
  };

  it("ignores unknown fields and fills defaults", () => {
    const d = dialogueFrom(raw);
    expect(Object.keys(d.lines).sort()).toEqual(["a", "b"]);
    expect(d.lines.b.durationS).toBeCloseTo(4 / 30);
    expect(d.captions.hit).toEqual({ text: "[thud]", priority: 30, minS: 0.5 });
  });

  it("refuses a file that is not format v0", () => {
    expect(() => dialogueFrom({ version: 2, lines: {} })).toThrow();
  });

  it("reveals characters by their times and finds cues", () => {
    const line = dialogueFrom(raw).lines.a;
    expect([0, 0.05, 0.15, 1].map((t) => revealCount(line, t))).toEqual([1, 1, 2, 3]);
    expect(cueAt(line, 0.1)?.lines).toEqual(["Hey"]);
    expect(cueAt(line, 0.5)).toBeNull();
  });

  it("shows barks only with subtitle barks on", () => {
    const d = dialogueFrom(raw);
    expect(shouldShow(d.lines.b, { subtitles: true, subtitle_barks: false })).toBe(false);
    expect(shouldShow(d.lines.b, { subtitles: true, subtitle_barks: true })).toBe(true);
    expect(shouldShow(d.lines.a, { subtitles: false, subtitle_barks: true })).toBe(false);
  });
});

describe("HoldToggle", () => {
  it("follows the button when holding", () => {
    const h = new HoldToggle();
    expect([true, true, false].map((d) => h.update(d, false))).toEqual([true, true, false]);
  });

  it("flips on each new press in toggle mode", () => {
    const h = new HoldToggle();
    expect([true, false, false, true, true, false].map((d) => h.update(d, true))).toEqual([true, true, true, false, false, false]);
  });
});

describe("findConflicts", () => {
  it("finds none in the defaults", () => {
    expect(findConflicts(DEFAULT_BINDINGS as Bindings)).toEqual([]);
  });

  it("finds two game actions on one key, not a ui and a game action", () => {
    const b: Bindings = { jump: ["key:k"], attack: ["key:k"], ui_accept: ["key:k"] };
    expect(findConflicts(b)).toEqual([["attack", 0], ["jump", 0]]);
  });
});

describe("input names", () => {
  it("turns KeyboardEvent.code into binding names", () => {
    expect(["KeyA", "Digit7", "ArrowUp", "Space", "Escape", "Numpad4", "ShiftRight", "F8"].map(keyName))
      .toEqual(["a", "7", "up", "space", "escape", "kp_4", "shift", "f8"]);
  });

  it("names standard-mapping buttons and pad families", () => {
    expect([0, 1, 9, 12, 20].map(padButtonName)).toEqual(["south", "east", "start", "dpad_up", "b20"]);
    expect(padDevice("Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e)")).toBe("pad_xbox");
    expect(padDevice("DualSense Wireless Controller (STANDARD GAMEPAD Vendor: 054c)")).toBe("pad_playstation");
    expect(padDevice("8BitDo Pro 2")).toBe("pad_other");
  });
});

// {{FOOTER}}
