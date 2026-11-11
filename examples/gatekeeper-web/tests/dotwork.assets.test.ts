// ---------------------------------------------------------------------------
// dotwork.assets.test.ts
// Purpose : Every real Dotwork manifest of this game (public/assets/dotwork/*.assets.json) loads: the version is
//           one this importer reads, every file it names exists, every rect fits its PNG, every terrain cell has a
//           tile, every map object and portrait animation is in the pack. The Node half of the stand-in for
//           Dotwork's Godot `verify`; `dev.py smoke` loads the same manifests in Phaser (src/game/dotworkVerify.ts).
// Notes   : A game without Dotwork art has no manifests: the test says so and passes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MANIFEST_SUFFIX } from "../src/game/dotworkPlan";
import { problems, readPlan } from "./helpers/dotworkFiles";

const DIR = fileURLToPath(new URL("../public/assets/dotwork/", import.meta.url));
const manifests = existsSync(DIR) ? readdirSync(DIR).filter((f) => f.endsWith(MANIFEST_SUFFIX)).sort() : [];

describe("the game's Dotwork manifests (public/assets/dotwork)", () => {
  it.skipIf(manifests.length > 0)("none yet (Dotwork writes them with --engine none)", () => {
    expect(manifests).toEqual([]);
  });

  for (const name of manifests) {
    it(`${name} loads`, () => {
      const { plan } = readPlan(DIR + name);
      expect(problems(plan)).toEqual([]);
    });
  }
});
