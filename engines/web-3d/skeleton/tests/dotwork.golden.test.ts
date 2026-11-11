// ---------------------------------------------------------------------------
// dotwork.golden.test.ts
// Purpose : The Dotwork importer (src/game/dotwork/) against the golden fixture data/golden/dotwork/: the imported
//           definitions must reproduce expected.json (the spec's loaded result, tools/art/dotwork/assetspec.py
//           expected()) to 1e-6, and the Three.js objects built from them must put each frame, tile and glyph on
//           the right part of its texture.
// Usage   : python tools/dev.py test
// Notes   : loaded() rebuilds the expected.json shape from the importer's own definitions (frame seconds, the
//           resolved terrain cells, the glyph map), not from the manifest's raw fields, so the comparison tests
//           what the game draws. Three.js builds in Node: textures are stand-ins with the real PNG sizes
//           (tests/helpers/dotwork.ts), nothing is rendered. Expected values come only from the fixture.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import {
  canon, cellMask, DotworkError, FLIP_H, flagSample, frameAt, importManifest, layoutText, normalizePath, TRANSPOSE, uvRect,
  type PackDef,
} from "../src/game/dotwork/manifest";
import { AnimatedSprite3D, DotworkNineSlice, DotworkSprite, DotworkText, DotworkTileMap, pixelTexture } from "../src/game/dotwork/threeBuild";
import { checkPackFiles, pngSize, pngTextures, posix, readPack } from "./helpers/dotwork";
import { expectClose, GOLDEN_DIR } from "./helpers/golden";

const FIXTURE = join(GOLDEN_DIR, "dotwork");
const MANIFEST = join(FIXTURE, "assets", "dotwork", "golden.assets.json");
const EXPECTED = JSON.parse(readFileSync(join(FIXTURE, "expected.json"), "utf-8"));
const TOL = 1e-6; // ASSET_MANIFEST.md: numbers rounded to 6 decimals

const pack = readPack(MANIFEST);
const tex = pngTextures(pack);

/** Python's list ordering (element by element), for the sorted mask lists. */
const cmp = (a: unknown, b: unknown): number => {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const c = cmp(a[i], b[i]);
      if (c) return c;
    }
    return a.length - b.length;
  }
  return (a as number) - (b as number);
};

/** The loaded result, in expected.json's shape, from the importer's definitions. */
function loaded(p: PackDef): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const a of p.animated.values()) {
    const clips: Record<string, unknown> = {};
    for (const c of a.clips.values()) {
      clips[c.name] = {
        frames: c.frames.length, rects: c.frames.map((f) => f.rect), seconds: c.frames.map((f) => f.seconds), length: c.length,
        loop: c.loop, pivot: c.pivot, texture: c.sheet,
      };
    }
    out[`animated_sprite/${a.name}`] = { blend: a.blend, clips, directions: a.directions };
  }
  for (const s of p.sprites.values()) out[`sprite/${s.name}`] = { size: s.size, pivot: s.pivot, collision: s.collision.map((c) => c.rect) };
  for (const i of p.icons.values()) out[`icon/${i.name}`] = { sizes: i.sizes.map((s) => s.size) };
  for (const q of p.portraits.values()) {
    out[`portrait/${q.name}`] = { size: q.size, expressions: q.expressions.map((e) => e.name).sort(), animation: q.animation };
  }
  for (const ts of p.tilesets.values()) {
    const masks: Record<string, unknown[]> = {};
    let n = 0, coll = 0, anim = 0;
    for (const t of ts.tiles.values()) {
      n += 1;
      coll += t.collision.length ? 1 : 0;
      anim += t.anim ? 1 : 0;
      if (t.terrain === null) continue;
      const key = `${t.terrainSet ?? 0}/${t.terrain}`;
      const v = t.mask !== null ? t.mask : Object.keys(t.corners ?? {}).sort().map((k) => t.corners![k]);
      masks[key] ??= [];
      if (!masks[key].some((x) => cmp(x, v) === 0)) masks[key].push(v);
    }
    for (const k of Object.keys(masks)) masks[k].sort(cmp);
    const terrains: Record<string, string> = {};
    for (const s of ts.terrainSets) for (const t of s.terrains) terrains[`${s.id}/${t.id}`] = t.name;
    out[`tileset/${ts.name}`] = {
      tile_size: ts.tileSize, shape: ts.shape, tiles: n, collision_tiles: coll, animated_tiles: anim, terrains, masks,
    };
  }
  for (const m of p.maps.values()) {
    const layers: Record<string, number> = {}, terrain: Record<string, unknown> = {};
    for (const L of m.layers) {
      layers[L.name] = L.given;
      if (L.terrain) terrain[L.name] = L.terrain.map((c) => [c.x, c.y, c.mask, c.tile]);
    }
    out[`map/${m.name}`] = { size: m.size, layers, terrain, objects: m.objects.map((o) => [o.asset, o.x, o.y]) };
  }
  for (const f of p.fonts.values()) {
    const g = f.glyphs.get(65) ?? f.glyphs.values().next().value;
    out[`font/${f.name}`] = {
      line_height: f.lineHeight, base: f.base, chars: f.glyphs.size, pages: f.pages.length,
      sample: g ? [g.id, g.x, g.y, g.w, g.h, g.xoffset, g.yoffset, g.xadvance, g.page] : null,
    };
  }
  for (const k of p.uiKits.values()) {
    const parts: Record<string, unknown> = {};
    for (const q of k.parts.values()) parts[q.name] = { size: q.size, margins: q.margins, hotspot: q.hotspot };
    out[`ui_kit/${k.name}`] = { parts };
  }
  for (const b of p.backgrounds.values()) {
    out[`background/${b.name}`] = { layers: b.layers.map((L) => [L.size[0], L.size[1], L.velocity[0], L.velocity[1], L.repeat]) };
  }
  for (const [key, kind] of p.skipped) out[key] = { kind };
  return { format: "dotwork-assets-expected", version: p.version, pack: p.pack, assets: out };
}

describe("Dotwork golden fixture (data/golden/dotwork/)", () => {
  it("imports to expected.json, asset by asset", () => {
    const got = loaded(pack) as { assets: Record<string, unknown> };
    expect(Object.keys(got.assets).sort()).toEqual(Object.keys(EXPECTED.assets).sort());
    for (const [key, want] of Object.entries(EXPECTED.assets)) expectClose(got.assets[key], want, TOL, key);
    expectClose(got, EXPECTED, TOL, "whole result");
  });

  it("warns once per skipped kind and draws every file it names", () => {
    for (const kind of ["particles", "transition", "normal_map", "image"]) {
      expect(pack.warnings.filter((w) => w.includes(` ${kind} asset`))).toHaveLength(1);
    }
    expect(checkPackFiles(MANIFEST, pack)).toEqual([]);
  });

  it("resolves paths as join(dirname(manifest), base, path)", () => {
    const hero = pack.animated.get("hero")!.clips.get("walk_s")!;
    expect(hero.frames[0].texture).toBe(normalizePath(posix(join(FIXTURE, "assets", hero.sheet!))));
    expect(normalizePath("http://h:1/a/dotwork/../art/x.png")).toBe("http://h:1/a/art/x.png");
  });
});

// A sheet render_sprites.py made from the golden rigged character (#290): rows are directions, columns frames, so
// a clip's rects sit on its own row of a shared sheet. The importer must load it as it loads Dotwork's packs.
describe("rendered character (data/golden/character/sprites/)", () => {
  const CHAR = join(GOLDEN_DIR, "character", "sprites");
  const CHAR_MANIFEST = join(CHAR, "dotwork", "character.assets.json");
  const charPack = readPack(CHAR_MANIFEST);

  it("imports to its expected.json", () => {
    const want = JSON.parse(readFileSync(join(CHAR, "expected.json"), "utf-8"));
    expectClose(loaded(charPack), want, TOL, "rendered character");
    expect(checkPackFiles(CHAR_MANIFEST, charPack)).toEqual([]);
  });

  it("maps each direction's row to its own UV band (y up)", () => {
    const clip = charPack.animated.get("character")!.clips.get("walk_w")!;
    const [w, h] = pngSize(clip.frames[0].texture);
    const size = clip.frames[0].rect[3];
    expect(uvRect(clip.frames[0].rect, w, h)[1]).toBeCloseTo(1 - (2 * size) / h, 9); // row 1 from the top
    expect(frameAt(clip, clip.length + 1e-3).index).toBe(0); // loops
  });
});

describe("Dotwork manifest rules", () => {
  const doc = () => JSON.parse(readFileSync(MANIFEST, "utf-8"));

  it("refuses another major version, naming both", () => {
    const d = { ...doc(), version: "2.0.0" };
    expect(() => importManifest(d, "x/dotwork/a.assets.json")).toThrow(/2\.0\.0.*1\.x/);
    expect(() => importManifest({ ...doc(), format: "other" }, "x.json")).toThrow(DotworkError);
  });

  it("reads a newer minor: unknown fields ignored, unknown kinds skipped with a warning", () => {
    const d = doc();
    d.version = "1.4.0";
    d.assets.push({ kind: "hologram", name: "h1", future: true });
    d.assets[0].future_field = { anything: 1 };
    const warnings: string[] = [];
    const p = importManifest(d, posix(MANIFEST), (m) => warnings.push(m));
    expect(p.skipped.get("hologram/h1")).toBe("hologram");
    expect(warnings.some((w) => w.includes("hologram") && w.includes("does not know"))).toBe(true);
  });

  it("refuses paths that climb out or are absolute", () => {
    for (const bad of ["../x.png", "/x.png", "C:/x.png", "a\\b.png"]) {
      const d = doc();
      d.assets.find((a: { kind: string }) => a.kind === "sprite").image = bad;
      expect(() => importManifest(d, posix(MANIFEST)), bad).toThrow(/path/);
    }
  });

  it("finds a missing file", () => {
    const d = doc();
    d.assets.find((a: { kind: string }) => a.kind === "sprite").image = "art/props/nope.png";
    const p = importManifest(d, posix(MANIFEST));
    expect(p.images.has(normalizePath(posix(join(FIXTURE, "assets", "art/props/nope.png"))))).toBe(true);
    expect(checkPackFiles(MANIFEST, p, d)).toEqual(["sprite/crate.image: art/props/nope.png is missing"]);
  });

  it("canon folds the 256 neighbour sets into the 47 blob masks; sides4 keeps N E S W", () => {
    expect(new Set(Array.from({ length: 256 }, (_, m) => canon(m))).size).toBe(47);
    const painted = new Set(["0,0", "1,0", "0,1", "1,1"]);
    expect(cellMask(painted, 0, 0)).toBe(4 | 8 | 16); // E, SE, S
    expect(cellMask(painted, 0, 0, "sides4")).toBe(4 | 16);
    expect(cellMask(new Set(["0,0", "1,1"]), 0, 0)).toBe(0); // a lone corner does not count
  });

  it("flips first, then transposes (transpose + flip h is a quarter turn clockwise)", () => {
    expect(flagSample(0, 0, TRANSPOSE | FLIP_H)).toEqual([0, 1]);
    expect(flagSample(1, 0, TRANSPOSE | FLIP_H)).toEqual([0, 0]);
    expect(flagSample(0.25, 0, FLIP_H)).toEqual([0.75, 0]);
  });
});

describe("Dotwork Three.js objects", () => {
  it("every texture is pixel art: nearest, no mipmaps, sRGB, clamped", () => {
    const t = pixelTexture(new THREE.Texture());
    expect([t.magFilter, t.minFilter, t.generateMipmaps, t.colorSpace, t.wrapS, t.wrapT]).toEqual([
      THREE.NearestFilter, THREE.NearestFilter, false, THREE.SRGBColorSpace, THREE.ClampToEdgeWrapping, THREE.ClampToEdgeWrapping,
    ]);
  });

  it("animated sprites move offset/repeat over the sheet rect, frame by frame, with each frame's seconds", () => {
    for (const [key, want] of Object.entries(EXPECTED.assets) as [string, any][]) {
      if (!key.startsWith("animated_sprite/")) continue;
      const def = pack.animated.get(key.split("/")[1])!;
      for (const [name, clip] of Object.entries(want.clips) as [string, any][]) {
        const a = new AnimatedSprite3D(def, tex, { clip: name, ppu: 8 });
        let start = 0;
        clip.seconds.forEach((s: number, i: number) => {
          a.play(name, true);
          a.update(start + s / 2); // the middle of frame i
          expect(a.frame, `${key}.${name} at ${start + s / 2} s`).toBe(i);
          const map = a.material.map!;
          const [W, H] = pngSize(def.clips.get(name)!.frames[i].texture);
          const [u0, v0, du, dv] = uvRect(clip.rects[i], W, H);
          expectClose([map.offset.x, map.offset.y, map.repeat.x, map.repeat.y], [u0, v0, du, dv], TOL, `${key}.${name}[${i}] uv`);
          expect(map.source).toBe(tex(def.clips.get(name)!.frames[i].texture).source); // a clone: same image
          start += s;
        });
        a.play(name, true);
        a.update(clip.length + 0.01);
        expect(a.frame).toBe(clip.loop ? 0 : clip.frames - 1);
        expect(a.finished).toBe(!clip.loop);
        a.dispose();
      }
    }
  });

  it("the quad is moved so the pivot sits on the origin (y up)", () => {
    const hero = new AnimatedSprite3D(pack.animated.get("hero")!, tex, { clip: "walk_s", ppu: 8 });
    hero.geometry.computeBoundingBox();
    const b = hero.geometry.boundingBox!; // 16 x 24 px, feet [8, 24] -> x -1..1, y 0..3
    expectClose([b.min.x, b.max.x, b.min.y, b.max.y], [-1, 1, 0, 3], TOL, "hero box");
    const crate = new DotworkSprite(pack.sprites.get("crate")!, tex, { ppu: 16 });
    crate.geometry.computeBoundingBox();
    expectClose([crate.geometry.boundingBox!.min.y, crate.geometry.boundingBox!.max.y], [0, 1], TOL, "crate box");
    expect(new AnimatedSprite3D(pack.animated.get("fx_spark")!, tex).material.blending).toBe(THREE.AdditiveBlending);
  });

  it("frameAt holds the last frame of a one-shot clip", () => {
    const clip = pack.animated.get("hero")!.clips.get("attack_e")!;
    expect(frameAt(clip, clip.length * 3)).toEqual({ index: clip.frames.length - 1, done: true });
  });

  it("a map is one InstancedMesh per atlas and layer, each cell on the expected tile", () => {
    const def = pack.maps.get("yard")!;
    const map = new DotworkTileMap(def, pack.tilesets.get(def.tileset)!, pack, tex);
    const meshes = map.children.filter((c): c is THREE.InstancedMesh => (c as THREE.InstancedMesh).isInstancedMesh);
    expect(meshes.reduce((n, m) => n + m.count, 0)).toBe(def.layers.reduce((n, L) => n + L.cells.length, 0));
    const want = EXPECTED.assets["map/yard"];
    for (const [layer, cells] of Object.entries(want.terrain) as [string, [number, number, number, number[]][]][]) {
      for (const [x, y, , tile] of cells) {
        const [atlasId, col, row] = tile;
        const atlas = pack.tilesets.get(def.tileset)!.atlases.find((a) => a.id === atlasId)!;
        const mesh = meshes.find((m) => m.name === `${layer}/${atlas.name}`)!;
        const i = def.layers.find((L) => L.name === layer)!.cells.filter((c) => c.atlas === atlasId).findIndex((c) => c.x === x && c.y === y);
        const uv = mesh.geometry.getAttribute("tileUv");
        const [W, H] = pngSize(atlas.image);
        const r = uvRect([col * 8, row * 8, 8, 8], W, H);
        expectClose([uv.getX(i), uv.getY(i), uv.getZ(i), uv.getW(i)], r, TOL, `${layer} (${x}, ${y})`);
        const m = new THREE.Matrix4();
        mesh.getMatrixAt(i, m);
        const p = new THREE.Vector3().setFromMatrixPosition(m);
        expectClose([p.x, p.z], [x + 0.5, y + 0.5], TOL, `${layer} (${x}, ${y}) position`); // one unit per tile
      }
    }
    expect(map.objects).toHaveLength(1);
    expectClose([map.objects[0].position.x, map.objects[0].position.z], [12 / 8, 40 / 8], TOL, "crate on the map");
  });

  it("animated tiles step to the next cell to the right at their fps", () => {
    const def = pack.maps.get("yard")!;
    const map = new DotworkTileMap(def, pack.tilesets.get(def.tileset)!, pack, tex);
    const water = map.children.find((c) => c.name === "Water/water") as THREE.InstancedMesh;
    const uv = water.geometry.getAttribute("tileUv");
    const u0 = uv.getX(0), du = uv.getZ(0);
    map.update(0.26); // fps 4: frame 1 from 0.25 s
    expectClose(uv.getX(0), u0 + du, TOL, "water frame 1");
    map.update(0.25);
    expectClose(uv.getX(0), u0, TOL, "water frame 0 again");
  });

  it("text is glyph quads from chars, with xadvance and kerning", () => {
    const font = pack.fonts.get("tiny")!;
    const lay = layoutText(font, "A AB");
    // A at 0 (advance 4), space (advance 3, no quad), A at 7, then kerning A->B -1: B at 7 + 4 - 1 = 10
    expect(lay.quads.map((q) => q.x)).toEqual([0, 7, 10]);
    expect(lay.width).toBe(14);
    const text = new DotworkText(font, tex, "AB", { ppu: 1 });
    expect(text.geometry.getAttribute("position").count).toBe(8);
    const [W, H] = pngSize(font.pages[0]);
    const uv = text.geometry.getAttribute("uv");
    expectClose([uv.getX(0), uv.getY(0)], [1 / W, 1 - 1 / H], TOL, "A's top-left uv");
    expect(layoutText(font, "Z").missing).toBe(1);
  });

  it("a 9-slice keeps its corners and stretches the rest", () => {
    const part = pack.uiKits.get("windows")!.parts.get("ui_window_plain")!;
    const ns = new DotworkNineSlice(part, tex, 30, 20, { ppu: 1 });
    const pos = ns.geometry.getAttribute("position");
    expect(pos.count).toBe(36); // 9 quads
    const xs = new Set(Array.from({ length: pos.count }, (_, i) => pos.getX(i)));
    expect([...xs].sort((a, b) => a - b)).toEqual([0, 3, 27, 30]);
  });
});

// {{FOOTER}}
