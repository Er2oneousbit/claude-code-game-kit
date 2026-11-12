// ---------------------------------------------------------------------------
// dotwork.manifests.test.ts
// Purpose : Every real Dotwork manifest of this game (public/assets/dotwork/*.assets.json) imports, names only files
//           that exist with the sizes it gives, and builds into Three.js objects: the stand-in for Dotwork's Godot
//           `verify` on this engine.
// Usage   : python tools/dev.py test     (`dev.py smoke` loads them again in the browser: src/game/dotwork/boot.ts)
// Notes   : No manifests yet (a game that does not use Dotwork): one empty test says so. Warnings (an unknown kind
//           of a newer manifest) are printed, not failures. Rebuild a stale pack with `python tools/art/dotwork/dotwork.py manifest`.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the extra kinds build too (#285)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  AnimatedSprite3D, backgroundLayers, DotworkNineSlice, DotworkPortrait, DotworkSprite, DotworkText, DotworkTileMap, iconQuad, imageQuad,
} from "../src/game/dotwork/threeBuild";
import { checkPackFiles, pngTextures, readPack } from "./helpers/dotwork";

const DIR = fileURLToPath(new URL("../public/assets/dotwork/", import.meta.url));
const FILES = existsSync(DIR) ? readdirSync(DIR).filter((f) => f.endsWith(".assets.json")).sort() : [];

describe("the game's Dotwork manifests (public/assets/dotwork/)", () => {
  it.runIf(FILES.length === 0)("has none yet (nothing to check)", () => {});

  for (const file of FILES) {
    it(`${file} loads`, () => {
      const path = join(DIR, file);
      const pack = readPack(path);
      for (const w of pack.warnings) console.warn(`[warn] ${w}`);
      expect(checkPackFiles(path, pack)).toEqual([]);
      const tex = pngTextures(pack);
      for (const def of pack.animated.values()) {
        const a = new AnimatedSprite3D(def, tex);
        for (const [name, clip] of def.clips) {
          a.play(name, true);
          a.update(clip.length * 1.5);
        }
        a.dispose();
      }
      for (const def of pack.sprites.values()) new DotworkSprite(def, tex);
      for (const def of pack.icons.values()) for (const s of def.sizes) iconQuad(def, tex, s.size);
      for (const def of pack.portraits.values()) {
        const p = new DotworkPortrait(def, tex);
        for (const e of def.expressions) p.setExpression(e.name);
      }
      for (const def of pack.maps.values()) new DotworkTileMap(def, pack.tilesets.get(def.tileset)!, pack, tex).update(1);
      for (const def of pack.fonts.values()) new DotworkText(def, tex, String.fromCodePoint(...[...def.glyphs.keys()].slice(0, 512)));
      for (const kit of pack.uiKits.values()) for (const part of kit.parts.values()) new DotworkNineSlice(part, tex, part.size[0] * 2, part.size[1] * 2);
      // the extra kinds: their textures are in the pack's images; a sprite with a normal map builds lit
      for (const def of pack.backgrounds.values()) backgroundLayers(def, tex);
      for (const def of pack.particles.values()) tex(def.texture);
      for (const def of pack.transitions.values()) tex(def.image);
      for (const def of pack.normalMaps.values()) {
        tex(def.image);
        tex(def.target);
        const lit = [...pack.sprites.values()].find((s) => s.image === def.target);
        if (lit) expect(new DotworkSprite(lit, tex, { lit: true }, pack).normalMap, `${def.name} lights ${lit.name}`).toBe(tex(def.image));
      }
      for (const def of pack.pictures.values()) imageQuad(def, tex);
    });
  }
});

// {{FOOTER}}
