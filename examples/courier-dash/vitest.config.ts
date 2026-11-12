// ---------------------------------------------------------------------------
// vitest.config.ts
// Purpose : Unit tests for engine-free code (src/core, pure parts of src/game).
// Notes   : Node environment, no browser: tests stay instant. Three.js objects can be built here (the Dotwork
//           importer's tests do, with stand-in textures) but nothing is rendered: anything that needs a canvas
//           belongs in the smoke test (tools/smoke.mjs).
//           testTimeout: the golden Dotwork tests take about 100 ms alone, but Vitest starts one worker per test
//           file at once (23 here, each loading Three.js), so on a busy machine (an engine build or another test
//           run next door) one test took 7 s and failed Vitest's 5 s default (0.15.0 verification, twice, a
//           different test each time). 30 s still fails a hung test.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-12 with Claude (Fable 5.1, claude-fable-5-1): testTimeout
// ---------------------------------------------------------------------------
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    testTimeout: 30_000,
  },
});
