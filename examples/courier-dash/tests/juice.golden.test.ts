// ---------------------------------------------------------------------------
// juice.golden.test.ts
// Purpose : Runs every case of data/golden/juice.json through the TypeScript juice modules (shake, hitstop,
//           ease, follow camera, input buffer, coyote time, spring, squash, flash limiter).
// Usage   : python tools/dev.py test
// Notes   : One test per case. A case type this file does not know fails, so a new vector type added to
//           tools/golden_vectors.py cannot be skipped silently. Expected values come only from the JSON.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { CoyoteTimer } from "../src/core/coyoteTimer";
import { ease } from "../src/core/ease";
import { FlashLimiter } from "../src/core/flashLimiter";
import { FollowCamera } from "../src/core/followCamera";
import { Hitstop } from "../src/core/hitstop";
import { InputBuffer } from "../src/core/inputBuffer";
import { noise, Shake } from "../src/core/shake";
import { Spring, squash } from "../src/core/spring";
import { expectClose, loadGolden, type GoldenCase } from "./helpers/golden";

const golden = loadGolden("juice.json");
const TOL = golden.tolerance;

type Runner = (c: GoldenCase) => void;

const RUNNERS: Record<string, Runner> = {
  noise: (c) => {
    c.points.forEach(([seed, t, ch, want]: number[], i: number) => expectClose(noise(seed, t, ch), want, TOL, `point ${i}`));
  },
  shake: (c) => {
    const p = c.params;
    const s = new Shake({ maxOffset: p.max_offset, maxAngle: p.max_angle, decay: p.decay, frequency: p.frequency, seed: p.seed });
    c.steps.forEach((step: any, i: number) => {
      if (step.call === "add_trauma") return s.addTrauma(step.a);
      if (step.call !== "update") throw new Error(`step ${i}: unknown call ${step.call}`);
      const o = s.update(step.dt, step.intensity);
      expectClose({ x: o.x, y: o.y, angle: o.angle, trauma: s.trauma }, step.expect, TOL, `step ${i}`);
    });
  },
  hitstop: (c) => {
    const h = new Hitstop(c.params.max_s);
    c.steps.forEach((step: any, i: number) => {
      if (step.call === "hit") return h.hit(step.duration);
      if (step.call !== "scaled_dt") throw new Error(`step ${i}: unknown call ${step.call}`);
      expectClose({ dt: h.scaledDt(step.dt), remaining: h.remaining }, step.expect, TOL, `step ${i}`);
    });
  },
  ease: (c) => {
    c.points.forEach(([name, t, want]: [string, number, number], i: number) => expectClose(ease(name, t), want, TOL, `point ${i} ${name}(${t})`));
  },
  follow: (c) => {
    const p = c.params;
    const f = new FollowCamera({ deadzoneW: p.deadzone_w, deadzoneH: p.deadzone_h, lookahead: p.lookahead, smoothing: p.smoothing, x: p.x, y: p.y });
    c.steps.forEach((step: any, i: number) => {
      if (step.call !== "update") throw new Error(`step ${i}: unknown call ${step.call}`);
      expectClose(f.update(step.dt, step.tx, step.ty, step.vx, step.vy), step.expect, TOL, `step ${i}`);
    });
  },
  input_buffer: (c) => {
    const b = new InputBuffer(c.params.window_s);
    c.steps.forEach((step: any, i: number) => {
      if (step.call === "press") return b.press(step.action);
      if (step.call === "update") return b.update(step.dt);
      if (step.call !== "consume") throw new Error(`step ${i}: unknown call ${step.call}`);
      expectClose({ result: b.consume(step.action) }, step.expect, TOL, `step ${i}`);
    });
  },
  coyote: (c) => {
    const t = new CoyoteTimer(c.params.window_s);
    c.steps.forEach((step: any, i: number) => {
      if (step.call === "update") return t.update(step.dt, step.on_floor);
      if (step.call === "consume") return t.consume();
      if (step.call !== "can_jump") throw new Error(`step ${i}: unknown call ${step.call}`);
      expectClose({ result: t.canJump() }, step.expect, TOL, `step ${i}`);
    });
  },
  spring: (c) => {
    const s = new Spring(c.params.frequency, c.params.damping);
    s.x = c.params.x;
    s.v = c.params.v;
    s.target = c.params.target;
    c.steps.forEach((step: any, i: number) => {
      if (step.call !== "update") throw new Error(`step ${i}: unknown call ${step.call}`);
      expectClose({ x: s.update(step.dt), v: s.v }, step.expect, TOL, `step ${i}`);
    });
  },
  squash: (c) => {
    c.points.forEach(([a, sx, sy]: number[], i: number) => expectClose(squash(a), [sx, sy], TOL, `point ${i}`));
  },
  flash_limiter: (c) => {
    const fl = new FlashLimiter(c.params.max_flashes, c.params.window_s);
    c.steps.forEach((step: any, i: number) => {
      if (step.call !== "request") throw new Error(`step ${i}: unknown call ${step.call}`);
      expectClose({ result: fl.request(step.now) }, step.expect, TOL, `step ${i}`);
    });
  },
};

describe("juice golden vectors (data/golden/juice.json)", () => {
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
