// ---------------------------------------------------------------------------
// vitest.config.ts
// Purpose : Unit tests for engine-free code (src/core, pure parts of src/game).
// Notes   : Node environment, no browser: tests stay instant. Three.js objects can be built here (the Dotwork
//           importer's tests do, with stand-in textures) but nothing is rendered: anything that needs a canvas
//           belongs in the smoke test (tools/smoke.mjs).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
