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
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the maps' placed cells and
//           centres, the corners4 and roll vectors, stamps, the extra kinds loaded
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import {
  canon, cellCentre, cellMask, cellRoll, DotworkError, expandStamps, FLIP_H, flagSample, frameAt, hash32, importManifest, layoutText,
  mapCentres, normalizePath, pickVariant, tileKey, TRANSPOSE, uvRect, type PackDef, type TileDef,
} from "../src/game/dotwork/manifest";
import {
  AnimatedSprite3D, backgroundLayers, DotworkNineSlice, DotworkSprite, DotworkText, DotworkTileMap, imageQuad, pixelTexture,
} from "../src/game/dotwork/threeBuild";
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
    const layers: Record<string, number> = {}, terrain: Record<string, unknown> = {}, placed: Record<string, unknown> = {};
    for (const L of m.layers) {
      layers[L.name] = L.cells.length; // cells drawn: a stamps layer its expanded tiles, a terrain layer its resolved cells
      placed[L.name] = L.cells.map((c) => [c.x, c.y, c.atlas, c.col, c.row, c.left, c.top]);
      if (L.terrain) terrain[L.name] = L.terrain.map((c) => [c.x, c.y, c.key, c.tile]);
    }
    out[`map/${m.name}`] = {
      size: m.size, shape: m.shape, tile_size: m.tileSize, layers, terrain, placed, centres: mapCentres(m),
      objects: m.objects.map((o) => [o.asset, o.x, o.y]),
    };
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
  for (const q of p.particles.values()) out[`particles/${q.name}`] = { kind: "particles" };
  for (const t of p.transitions.values()) out[`transition/${t.name}`] = { kind: "transition" };
  for (const n of p.normalMaps.values()) out[`normal_map/${n.name}`] = { kind: "normal_map" };
  for (const i of p.pictures.values()) out[`image/${i.name}`] = { kind: "image" };
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

  it("loads every kind of the spec (nothing skipped, no warning) and draws every file it names", () => {
    expect(pack.skipped.size).toBe(0);
    expect(pack.warnings).toEqual([]);
    expect(checkPackFiles(MANIFEST, pack)).toEqual([]);
  });

  it("exposes the extra kinds by name with their data", () => {
    const bg = pack.backgrounds.get("hills")!;
    expect(bg.layers.map((L) => L.repeat)).toEqual(EXPECTED.assets["background/hills"].layers.map((L: unknown[]) => L[4]));
    const fx = pack.particles.get("vfx_embers_particles")!;
    expect(pack.images.has(fx.texture)).toBe(true);
    expect(Object.keys(fx.emitter).length).toBeGreaterThan(0);
    const tr = pack.transitions.get("transition_wipe")!;
    expect(tr.transition).toBe("wipe");
    expect(pack.dataImages.has(tr.image)).toBe(true);
    const nm = pack.normalMaps.get("spr_crate_n")!;
    expect(nm.convention).toBe("opengl");
    expect(nm.target).toBe(pack.sprites.get("crate")!.image); // it lights the crate
    expect(pack.dataImages.has(nm.image) && !pack.dataImages.has(nm.target)).toBe(true);
    expect(pack.pictures.get("logo_golden")!.size).toEqual(pngSize(pack.pictures.get("logo_golden")!.image));
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

  it("corners4 keys a 3x3 block by the corners where all four cells are painted", () => {
    const block = new Set<string>();
    for (let y = 0; y < 3; y++) for (let x = 0; x < 3; x++) block.add(`${x},${y}`);
    expect(cellMask(block, 1, 1, "corners4")).toBe(170); // the centre: every corner
    expect(cellMask(block, 0, 0, "corners4")).toBe(8); // top-left: SE only
    expect(cellMask(block, 1, 0, "corners4")).toBe(40); // top-middle: SE and SW
    expect(cellMask(block, 2, 2, "corners4")).toBe(128); // bottom-right: NW only
    // a tile's key: the corner bits whose corner holds its terrain, by shape (square names, isometric names)
    const tile = (corners: Record<string, number>) => ({ terrain: 1, corners } as unknown as TileDef);
    expect(tileKey(tile({ top_left: 1, top_right: -1, bottom_right: 1, bottom_left: 1 }), "corners4", "square")).toBe(128 + 8 + 32);
    expect(tileKey(tile({ top: 1, right: 1, bottom: -1, left: -1 }), "corners4", "isometric")).toBe(128 + 2);
    expect(tileKey(tile({ top_left: 1 }), "corners4", "square")).toBeNull(); // not all four corners: no key
  });

  it("hash32 and cellRoll give the spec's vectors (32-bit steps only)", () => {
    expect(hash32(0)).toBe(1800329511);
    expect(hash32(1)).toBe(3028713910);
    expect(hash32(0xFFFFFFFF)).toBe(4268016002);
    expect(cellRoll(0, 0, 0)).toBeCloseTo(0.169182, 6);
    expect(cellRoll(3, 1, 1)).toBeCloseTo(0.765973, 6);
    expect(cellRoll(3, 2, 1)).toBeCloseTo(0.531301, 6);
    expect(cellRoll(-1, -1, 0)).toBeCloseTo(0.992978, 6); // coordinates wrap at 16 bits
    expect(pickVariant([[0.6, "a"], [0.6, "b"]], 0.49)).toBe("a");
    expect(pickVariant([[0.6, "a"], [0.6, "b"]], 0.5)).toBe("b");
    expect(pickVariant([[0, "a"], [0, "b"]], 0.9)).toBe("a"); // all weights 0: the first
  });

  it("picks the variant the roll names (yard Path: two full cells, one rolls the variant tile)", () => {
    const path = pack.maps.get("yard")!.layers.find((L) => L.name === "Path")!;
    const want = EXPECTED.assets["map/yard"].terrain.Path as [number, number, number, number[]][];
    const full = want.filter(([, , key]) => key === 255);
    expect(full.length).toBe(2);
    expect(new Set(full.map(([, , , t]) => t.join(","))).size).toBe(2); // the base tile and the variant
    for (const [x, y, key, tile] of want) {
      const got = path.terrain!.find((c) => c.x === x && c.y === y)!;
      expect([got.key, got.tile], `Path (${x}, ${y})`).toEqual([key, tile]);
    }
  });

  it("cell centres: squares in rows, isometric diamonds in Godot's diamond-down layout", () => {
    expect(cellCentre("square", [8, 8], 3, 2)).toEqual([28, 20]);
    const iso = (x: number, y: number) => cellCentre("isometric", [16, 8], x, y);
    expect([iso(0, 0), iso(1, 0), iso(0, 1), iso(3, 2)]).toEqual([[8, 4], [16, 8], [0, 8], [16, 24]]);
    const isle = pack.maps.get("isle")!;
    expectClose(mapCentres(isle), EXPECTED.assets["map/isle"].centres, TOL, "isle centres");
    // a raised block with its own origin [8, 8] on a 16 x 8 diamond: its bottom edge on the diamond's bottom point
    const blocks = isle.layers.find((L) => L.name === "Blocks")!.cells[0];
    const [cx, cy] = iso(blocks.x, blocks.y);
    expect([blocks.left, blocks.top]).toEqual([cx - 8, cy - 8]);
  });

  it("a stamps layer places every tile of the stamp from its top-left cell", () => {
    const ts = pack.tilesets.get("ground_yard")!;
    const door = ts.stamps[0];
    const cells = expandStamps(ts, [[7, 0, 0]], "test");
    expect(cells.length).toBe(door.size[0] * door.size[1]);
    door.tiles.forEach(([atlas, col, row], j) => {
      expect(cells[j]).toEqual([7 + (j % door.size[0]), Math.floor(j / door.size[0]), atlas, col, row]);
    });
    const fixtures = pack.maps.get("yard")!.layers.find((L) => L.name === "Fixtures")!;
    expect(fixtures.given).toBe(1);
    expect(fixtures.cells.map((c) => [c.x, c.y, c.atlas, c.col, c.row, c.left, c.top])).toEqual(EXPECTED.assets["map/yard"].placed.Fixtures);
    expect(() => expandStamps(ts, [[0, 0, 99]], "test")).toThrow(/stamp 99/);
  });

  it("skips a map layer of an unknown kind with one warning", () => {
    const d = doc();
    const yard = d.assets.find((a: { kind: string; name: string }) => a.kind === "map" && a.name === "yard");
    yard.layers.push({ name: "Fog", kind: "weather", cells: [[0, 0]] });
    const warnings: string[] = [];
    const p = importManifest(d, posix(MANIFEST), (m) => warnings.push(m));
    expect(p.maps.get("yard")!.layers.map((L) => L.name)).not.toContain("Fog");
    expect(warnings.filter((w) => w.includes('"weather"'))).toHaveLength(1);
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

  it("a map is one InstancedMesh per atlas and layer, each placed cell on its tile at its left/top (all three maps)", () => {
    for (const name of ["yard", "meadow_patch", "isle"]) {
      const def = pack.maps.get(name)!;
      const tileset = pack.tilesets.get(def.tileset)!;
      const map = new DotworkTileMap(def, tileset, pack, tex);
      const meshes = map.children.filter((c): c is THREE.InstancedMesh => (c as THREE.InstancedMesh).isInstancedMesh);
      expect(meshes.reduce((n, m) => n + m.count, 0)).toBe(def.layers.reduce((n, L) => n + L.cells.length, 0));
      const want = EXPECTED.assets[`map/${name}`];
      for (const [layer, cells] of Object.entries(want.placed) as [string, number[][]][]) {
        const own = def.layers.find((L) => L.name === layer)!.cells;
        for (const [x, y, atlasId, col, row, left, top] of cells) {
          const atlas = tileset.atlases.find((a) => a.id === atlasId)!;
          const mesh = meshes.find((m) => m.name === `${layer}/${atlas.name}`)!;
          const i = own.filter((c) => c.atlas === atlasId).findIndex((c) => c.x === x && c.y === y && c.col === col && c.row === row);
          expect(i, `${name}.${layer} (${x}, ${y}) is placed`).toBeGreaterThanOrEqual(0);
          const uv = mesh.geometry.getAttribute("tileUv");
          const [W, H] = pngSize(atlas.image);
          const [tw, th] = atlas.tileSize;
          expectClose([uv.getX(i), uv.getY(i), uv.getZ(i), uv.getW(i)], uvRect([col * tw, row * th, tw, th], W, H), TOL, `${name}.${layer} (${x}, ${y}) uv`);
          const m = new THREE.Matrix4();
          mesh.getMatrixAt(i, m);
          const p = new THREE.Vector3().setFromMatrixPosition(m);
          // the quad's centre: the image's top-left in map pixels plus half the atlas tile, one unit per tile width
          expectClose([p.x, p.z], [(left + tw / 2) / map.unit, (top + th / 2) / map.unit], TOL, `${name}.${layer} (${x}, ${y}) position`);
        }
      }
    }
    const yard = pack.maps.get("yard")!;
    const map = new DotworkTileMap(yard, pack.tilesets.get(yard.tileset)!, pack, tex);
    expect(map.objects).toHaveLength(1);
    const [, ox, oy] = EXPECTED.assets["map/yard"].objects[0];
    expectClose([map.objects[0].position.x, map.objects[0].position.z], [ox / 8, oy / 8], TOL, "crate on the map");
  });

  it("the extra kinds build: wrapping background layers, a lit sprite with its normal map, an image quad", () => {
    expect(pixelTexture(new THREE.Texture(), true).colorSpace).toBe(THREE.NoColorSpace);
    const layers = backgroundLayers(pack.backgrounds.get("hills")!, tex);
    expect(layers.length).toBe(EXPECTED.assets["background/hills"].layers.length);
    for (const { layer, texture } of layers) {
      expect(texture.source).toBe(tex(layer.image).source); // a clone: the image is shared
      expect(texture.wrapS).toBe(layer.repeat === "x" || layer.repeat === "xy" ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping);
      expect(texture.wrapT).toBe(layer.repeat === "y" || layer.repeat === "xy" ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping);
    }
    const crate = new DotworkSprite(pack.sprites.get("crate")!, tex, { lit: true }, pack);
    expect(crate.material).toBeInstanceOf(THREE.MeshLambertMaterial);
    expect(crate.normalMap).toBe(tex(pack.normalMaps.get("spr_crate_n")!.image));
    expect((crate.material as THREE.MeshLambertMaterial).normalMap).toBe(crate.normalMap);
    const plain = new DotworkSprite(pack.sprites.get("crate")!, tex, {}, pack);
    expect(plain.material).toBeInstanceOf(THREE.MeshBasicMaterial); // unlit by default, the normal map still known
    expect(plain.normalMap).toBe(crate.normalMap);
    const logo = imageQuad(pack.pictures.get("logo_golden")!, tex, { ppu: 1 });
    logo.geometry.computeBoundingBox();
    const [w, h] = pack.pictures.get("logo_golden")!.size;
    expectClose([logo.geometry.boundingBox!.min.x, logo.geometry.boundingBox!.max.y], [-w / 2, h / 2], TOL, "logo centred");
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
