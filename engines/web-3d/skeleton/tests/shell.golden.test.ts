// ---------------------------------------------------------------------------
// shell.golden.test.ts
// Purpose : Runs every case of data/golden/shell.json through the TypeScript shell modules (settings,
//           bindings and glyphs, save store, i18n with the pseudo-locale).
// Usage   : python tools/dev.py test
// Notes   : One test per case. A case type this file does not know fails, so a new vector type added to
//           tools/golden_vectors.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): display_staging, the Display tab's Apply and its
//           keep-or-revert confirm, step by step (#308)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { DISPLAY_APPLY_ORDER, DISPLAY_CONFIRM_S, DisplayStaging, type DisplayCall } from "../src/core/displayStaging";
import { glyphName, glyphSet, promptBinding, rebind, narrationLine } from "../src/core/bindings";
import { plural, pseudo, tr, trPlural } from "../src/core/i18n";
import { SAVE_VERSION, saveLoad } from "../src/core/saveStore";
import { defaultSettings, effectiveShake, settingsLoad, telemetryAllowed } from "../src/core/settings";
import { expectClose, loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("shell.json");
const TOL = golden.tolerance;

type Runner = (c: GoldenCase) => void;

const RUNNERS: Record<string, Runner> = {
  defaults: (c) => expectClose(defaultSettings(), c.expect, TOL, "defaults"),
  settings_load: (c) => {
    const { settings, problems } = settingsLoad(c.input);
    expectClose(settings, c.expect, TOL, "settings");
    expectClose(problems.length, c.problems, TOL, `problems [${problems.join(", ")}]`);
    expectClose(effectiveShake(settings), c.effective_shake, TOL, "effective_shake");
    expectClose(telemetryAllowed(settings), c.telemetry_allowed, TOL, "telemetry_allowed");
  },
  rebind: (c) => {
    const r = rebind(c.bindings, c.action, c.slot, c.binding);
    expectClose({ bindings: r.bindings, conflicts: r.conflicts }, c.expect, TOL, "rebind");
  },
  glyph_set: (c) => {
    c.points.forEach(([setting, dev, want]: string[], i: number) => expectClose(glyphSet(setting, dev), want, TOL, `point ${i}`));
  },
  narration: (c) => {
    c.points.forEach(([label, role, value, want]: string[], i: number) => expectClose(narrationLine(label, role, value), want, TOL, `point ${i}`));
  },
  glyph_name: (c) => {
    c.points.forEach(([gset, b, want]: string[], i: number) => expectClose(glyphName(gset, b), want, TOL, `point ${i} ${gset} ${b}`));
  },
  prompt_binding: (c) => {
    c.points.forEach(([a, g, want]: string[], i: number) => expectClose(promptBinding(c.bindings, a, g), want, TOL, `point ${i}`));
  },
  save_load: (c) => {
    expect(SAVE_VERSION).toBe(c.current_version);
    const r = saveLoad(c.primary, c.backup);
    expectClose({ envelope: r.envelope, source: r.source, problems: r.problems.length }, c.expect, TOL, `save_load [${r.problems.join(", ")}]`);
  },
  tr: (c) => {
    c.points.forEach(([loc, key, args, want]: [string, string, Record<string, unknown>, string], i: number) =>
      expectClose(tr(c.tables, loc, key, args), want, TOL, `point ${i} ${loc} ${key}`));
  },
  plural: (c) => {
    if (typeof c.key !== "string") throw new Error("plural case without a lookup key");
    c.points.forEach(([loc, n, form, text]: [string, number, string, string], i: number) => {
      expectClose(plural(loc, n), form, TOL, `point ${i} plural(${loc}, ${n})`);
      expectClose(trPlural(c.tables, loc, c.key, n), text, TOL, `point ${i} trPlural(${loc}, ${c.key}, ${n})`);
    });
  },
  display_staging: (c) => {
    expectClose(DISPLAY_CONFIRM_S, c.confirm_s, TOL, "DISPLAY_CONFIRM_S");
    const st = new DisplayStaging(c.applied);
    c.steps.forEach((step: Record<string, any>, i: number) => {
      const [op, ...args] = step.op as [string, ...unknown[]];
      let out: unknown = null;
      let calls: DisplayCall[] = [];
      if (op === "stage") out = st.stage(args[0] as string, args[1]);
      else if (op === "apply") calls = st.apply();
      else if (op === "tick") calls = st.tick(args[0] as number);
      else if (op === "keep") st.keep();
      else if (op === "revert") calls = st.revert();
      else if (op === "back") [out, calls] = st.back();
      else throw new Error(`unknown display_staging op "${op}"`);
      const shown = Object.fromEntries(DISPLAY_APPLY_ORDER.map((f) => [f, st.value(f)]));
      expectClose({ out, calls, pending: st.pending, shown, applied: st.applied, seconds: st.seconds() },
        { out: step.out, calls: step.calls, pending: step.pending, shown: step.shown, applied: step.applied, seconds: step.seconds },
        TOL, `step ${i} ${JSON.stringify(step.op)}`);
    });
  },
  pseudo: (c) => {
    c.points.forEach(([text, want]: string[], i: number) => expectClose(pseudo(text), want, TOL, `point ${i} ${JSON.stringify(text)}`));
  },
};

describe("shell golden vectors (data/golden/shell.json)", () => {
  it("has cases", () => {
    expect(golden.cases.length).toBeGreaterThan(0);
  });

  for (const c of golden.cases) {
    it(`${c.type}: ${c.name}`, () => {
      const run = Object.prototype.hasOwnProperty.call(RUNNERS, c.type) ? RUNNERS[c.type] : undefined;
      if (!run) throw new Error(`unknown case type "${c.type}": add a runner for it (tools/golden_vectors.py is the spec)`);
      run(c);
    });
  }
});

// {{FOOTER}}
