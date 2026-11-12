// ---------------------------------------------------------------------------
// dotwork.golden.test.ts
// Purpose : The Dotwork importer (src/game/dotworkPlan.ts) against the kit's golden pack: data/golden/dotwork/ holds
//           a manifest with every kind and expected.json, the loaded result every engine's importer must reproduce
//           (to 1e-6). Plus the rules the fixture does not reach: version refusal, unknown kinds and fields,
//           the three terrain modes, the variant pick's hash vectors, cell centres on both shapes, stamps,
//           tile flags, per-frame timing, bitmap font data, the extra kinds.
// Notes   : expected.json is written by tools/art/dotwork/assetspec.py (the reference); never copy its values here.
//           The hash and roll vectors and the cell centres are the spec's own (ASSET_MANIFEST.md 1.1.0).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 cases (#285)
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  bitmapFontData, canon, cellCentre, cellKey, cellMask, cellRoll, DotworkError, frameAt, hash32, loadedResult, pickVariant,
  planManifest, rectToWorld, resolvePath, tileAnimations, tileKey, tileOfGid, tileTransform,
} from "../src/game/dotworkPlan";
import { problems, readPlan } from "./helpers/dotworkFiles";
import { diff, GOLDEN_DIR } from "./helpers/golden";

const DIR = GOLDEN_DIR + "dotwork/";
const MANIFEST = DIR + "assets/dotwork/golden.assets.json";
const TOLERANCE = 1e-6; // ASSET_MANIFEST.md: numbers are rounded to 6 decimals

const golden = () => readPlan(MANIFEST);
const minimal = (assets: unknown[], version = "1.0.0") => ({ format: "dotwork-assets", version, pack: "t", generator: "test", base: "..", assets });

describe("golden pack (data/golden/dotwork)", () => {
  it("reproduces expected.json", () => {
    const expected = JSON.parse(readFileSync(DIR + "expected.json", "utf-8"));
    const { plan } = golden();
    expect(plan.errors).toEqual([]);
    const d = diff(loadedResult(plan), expected, TOLERANCE);
    expect(d).toBeNull();
  });

  it("names only files that exist, with rects inside their images", () => {
    expect(problems(golden().plan)).toEqual([]);
  });

  it("gives each frame its own duration (holds), not the clip's fps alone", () => {
    const walk = golden().plan.animatedSprites.get("hero")!.clips.find((c) => c.name === "walk_s")!;
    expect(walk.frames.map((f) => f.ms)).toEqual([125, 125, 250, 125]);
    expect([0, 124, 125, 250, 260, 499, 500, 624, 625].map((t) => frameAt(walk, t))).toEqual([0, 0, 1, 2, 2, 2, 3, 3, 0]);
    const attack = golden().plan.animatedSprites.get("hero")!.clips.find((c) => c.name === "attack_e")!;
    expect(frameAt(attack, 10_000)).toBe(2); // a clip that does not loop holds its last frame
  });

  it("puts the pivot on the origin and names frames per pack, asset and clip", () => {
    const { plan } = golden();
    const idle = plan.animatedSprites.get("hero")!.clips[0];
    expect(idle.origin).toEqual([0.5, 1]);
    expect(idle.frames[1].frame).toBe("golden/hero/idle_s/1");
    expect(idle.key).toBe("golden/hero/idle_s");
    expect(plan.sprites.get("crate")!.origin).toEqual([0.5, 1]);
  });

  it("keeps collision in the sprite's space", () => {
    const crate = golden().plan.sprites.get("crate")!;
    expect(rectToWorld(crate.collision[0], crate.pivot, 100, 50)).toEqual([95, 38, 10, 12]); // 100 - 8 + 3, 50 - 16 + 4
  });

  it("gives atlases consecutive Phaser tile indexes and finds tiles back", () => {
    const ts = golden().plan.tilesets.get("ground_yard")!;
    let next = 0;
    for (const a of ts.atlases) {
      expect(a.firstgid).toBe(next); // each atlas starts where the one before it ends
      next += a.columns * a.rows;
    }
    expect(ts.atlases.length).toBe(5);
    for (const t of ts.tiles) expect(tileOfGid(ts, t.gid)).toEqual([t.atlas, t.col, t.row]);
  });

  it("animates tiles with the frames to the right of them", () => {
    const ts = golden().plan.tilesets.get("ground_yard")!;
    const water = tileAnimations(ts).get(2)!;
    expect(water[0].animation.map((f) => f.tileid)).toEqual([0, 1]);
    expect(water[0].animationDuration).toBe(500);
  });

  it("builds Phaser bitmap font data from chars", () => {
    const f = golden().plan.fonts.get("tiny")!;
    const data = bitmapFontData(f, 16, 8);
    expect(data.lineHeight).toBe(7);
    expect(data.chars[65]).toMatchObject({ x: 1, y: 1, width: 3, height: 5, xAdvance: 4, u0: 1 / 16, v0: 1 - 1 / 8, u1: 4 / 16, v1: 1 - 6 / 8 });
    expect(data.chars[66].kerning[65]).toBe(-1); // Phaser stores kerning on the second glyph
  });

  it("loads the extra kinds by name, without a warning", () => {
    const { plan } = golden();
    for (const k of ["background", "particles", "transition", "normal_map", "image"]) expect(plan.warnings.filter((x) => x.includes(`"${k}"`))).toEqual([]);
    const bg = plan.backgrounds.get("hills")!;
    expect(bg.layers.map((L) => L.repeat)).toEqual(["none", "x"]);
    expect(plan.textures.get(bg.layers[1].texture)!.repeat).toBe("x");
    const fx = plan.particles.get("vfx_embers_particles")!;
    expect(fx.emitter.amount).toBe(12);
    expect(plan.textures.has(fx.texture)).toBe(true);
    expect(plan.transitions.get("transition_wipe")!.transition).toBe("wipe");
    expect(plan.images.get("logo_golden")!.role).toBe("logo");
    // the normal map rides on its target's texture (the crate sprite's), as load.image(key, [url, normal])
    const n = plan.normalMaps.get("spr_crate_n")!;
    expect(n.target).toBe(plan.sprites.get("crate")!.texture);
    expect(plan.textures.get(n.target)!.normal).toBe(n.image);
    expect(plan.files).toContain(n.image);
    expect(n.convention).toBe("opengl");
  });

  it("picks the variant with the cell's roll: two full path cells, one of each tile", () => {
    const path = golden().plan.maps.get("yard")!.layers.find((L) => L.name === "Path")!;
    const full = path.cells.filter((c) => c.mask === 255);
    expect(full.length).toBe(2);
    expect(full[0].tile).not.toEqual(full[1].tile); // the base tile and its 0.6 variant
  });

  it("expands the door stamp into its two cells, one under the other", () => {
    const yard = golden().plan.maps.get("yard")!;
    const fixtures = yard.layers.find((L) => L.name === "Fixtures")!;
    expect(fixtures.kind).toBe("stamps");
    expect(fixtures.count).toBe(2);
    expect(fixtures.cells.map((c) => [c.x, c.y])).toEqual([[7, 0], [7, 1]]);
    expect(fixtures.cells.map((c) => c.top)).toEqual([0, yard.tileSize[1]]);
  });

  it("stands the iso block on its cell: the spec's centre less its own origin", () => {
    const isle = golden().plan.maps.get("isle")!;
    expect(isle.shape).toBe("isometric");
    const block = isle.layers.find((L) => L.name === "Blocks")!.cells[0];
    const ts = golden().plan.tilesets.get(isle.tileset)!;
    const tile = ts.tiles.find((t) => t.gid === block.gid)!;
    const [cx, cy] = cellCentre("isometric", block.x, block.y, isle.tileSize);
    expect([block.left, block.top]).toEqual([cx - tile.origin![0], cy - tile.origin![1]]);
    const floor = isle.layers.find((L) => L.name === "Floor")!.cells.find((c) => c.x === 1 && c.y === 2)!;
    expect([floor.left, floor.top]).toEqual([-isle.tileSize[0] / 2, (isle.tileSize[1] * 3) / 2]); // left of the map's x = 0
  });
});

// A sheet render_sprites.py made from the golden rigged character (#290): rows are directions, columns frames,
// so a clip's rects sit on its own row of a shared sheet. The importer must load it as it loads Dotwork's packs.
describe("rendered character (data/golden/character/sprites)", () => {
  const CHAR = GOLDEN_DIR + "character/sprites/";
  const rendered = () => readPlan(CHAR + "dotwork/character.assets.json");

  it("reproduces its expected.json", () => {
    const expected = JSON.parse(readFileSync(CHAR + "expected.json", "utf-8"));
    const { plan } = rendered();
    expect(plan.errors).toEqual([]);
    expect(diff(loadedResult(plan), expected, TOLERANCE)).toBeNull();
  });

  it("names only files that exist, with rects inside their sheets", () => {
    expect(problems(rendered().plan)).toEqual([]);
  });

  it("cuts each direction from its own row and keeps the feet on the origin", () => {
    const sprite = rendered().plan.animatedSprites.get("character")!;
    const walkW = sprite.clips.find((c) => c.name === "walk_w")!;
    const size = walkW.frames[0].rect[3];
    expect(walkW.frames.map((f) => f.rect[1])).toEqual(walkW.frames.map(() => size)); // row 1 of the sheet
    expect(walkW.origin[1]).toBeGreaterThan(0.5); // the feet are below the cell's centre
    expect(frameAt(walkW, walkW.frames[0].ms * walkW.frames.length + 1)).toBe(0); // loops
  });
});

describe("manifest rules", () => {
  it("refuses another major version, naming both", () => {
    expect(() => planManifest(minimal([], "2.0.0"), "x.assets.json")).toThrow(/2\.0\.0.*1\.x/);
    expect(() => planManifest({ format: "other" }, "x.assets.json")).toThrow(DotworkError);
    expect(planManifest(minimal([], "1.7.3"), "x.assets.json").errors).toEqual([]); // a newer minor reads fine
  });

  it("skips an unknown kind with one warning and ignores unknown fields", () => {
    const sprite = { kind: "sprite", name: "s", image: "a.png", size: [4, 4], pivot: [2, 4], content_rect: [0, 0, 4, 4], sparkle: 9 };
    const plan = planManifest(minimal([{ kind: "hologram", name: "h1" }, { kind: "hologram", name: "h2" }, sprite]), "g/dotwork/t.assets.json");
    expect(plan.warnings.filter((w) => w.includes("hologram")).length).toBe(1);
    expect(plan.sprites.get("s")!.texture).toBe("dotwork:g/a.png");
    expect(plan.errors).toEqual([]);
  });

  it("reports a broken asset and still loads the rest", () => {
    const bad = { kind: "sprite", name: "bad", image: "../escape.png", size: [4, 4], pivot: [2, 4] };
    const good = { kind: "icon", name: "ok", sizes: [{ size: 16, image: "i.png" }] };
    const plan = planManifest(minimal([bad, good]), "t.assets.json");
    expect(plan.errors.length).toBe(1);
    expect(plan.icons.has("ok")).toBe(true);
  });

  it("resolves paths against the manifest's folder and base", () => {
    expect(resolvePath("assets/dotwork/town.assets.json", "..", "art/a.png")).toBe("assets/art/a.png");
    expect(resolvePath("D:/g/public/assets/dotwork/t.assets.json", "..", "art/x/y.png")).toBe("D:/g/public/assets/art/x/y.png");
  });
});

describe("terrain rule (assetspec.cell_mask, ported)", () => {
  it("folds 256 raw masks into the 47 blob masks", () => {
    expect(new Set(Array.from({ length: 256 }, (_, m) => canon(m))).size).toBe(47);
  });

  it("drops a corner unless both sides next to it are set", () => {
    const painted = new Set([cellKey(1, 1), cellKey(2, 1), cellKey(2, 0), cellKey(1, 0)]);
    expect(cellMask(painted, 1, 1)).toBe(1 | 2 | 4); // N, NE, E: the NE corner counts
    painted.delete(cellKey(1, 0));
    expect(cellMask(painted, 1, 1)).toBe(4); // NE without N does not
    expect(cellMask(new Set([cellKey(0, 1), cellKey(1, 0)]), 1, 1, "sides4")).toBe(1 | 64);
  });

  it("corners4: a 3x3 block keys its centre 170, its top-left 8 and its top-middle 40", () => {
    const painted = new Set<string>();
    for (let y = 0; y < 3; y++) for (let x = 0; x < 3; x++) painted.add(cellKey(x, y));
    expect(cellMask(painted, 1, 1, "corners4")).toBe(170);
    expect(cellMask(painted, 0, 0, "corners4")).toBe(8);
    expect(cellMask(painted, 1, 0, "corners4")).toBe(40);
  });

  it("keys a corners4 tile by the corners that hold its own terrain, named per shape", () => {
    const square = { mask: null, terrain: 1, corners: { top_left: 1, top_right: 0, bottom_right: 1, bottom_left: 0 } };
    expect(tileKey(square, "corners4", "square")).toBe(128 + 8);
    const iso = { mask: null, terrain: 1, corners: { top: 1, right: 1, bottom: 0, left: 0 } };
    expect(tileKey(iso, "corners4", "isometric")).toBe(128 + 2);
    expect(tileKey({ mask: null, terrain: 1, corners: { top: 1 } }, "corners4", "isometric")).toBeNull(); // not all four
    expect(tileKey({ mask: 7, terrain: 1, corners: null }, "blob47", "square")).toBe(7);
  });
});

describe("the variant pick (ASSET_MANIFEST.md test vectors)", () => {
  const r6 = (v: number) => Math.round(v * 1e6) / 1e6;

  it("hash32 and cell_roll give the spec's vectors", () => {
    expect(hash32(0)).toBe(1800329511);
    expect(hash32(1)).toBe(3028713910);
    expect(hash32(0xffffffff)).toBe(4268016002);
    expect(r6(cellRoll(0, 0, 0))).toBe(0.169182);
    expect(r6(cellRoll(3, 1, 1))).toBe(0.765973);
    expect(r6(cellRoll(3, 2, 1))).toBe(0.531301);
    expect(r6(cellRoll(-1, -1, 0))).toBe(0.992978);
  });

  it("walks the weights in atlas order, the first when every weight is 0", () => {
    const c: [number, string][] = [[0.6, "a"], [0.6, "b"]];
    expect(pickVariant(c, 0.49)).toBe("a");
    expect(pickVariant(c, 0.5)).toBe("b"); // 0.5 * 1.2 = 0.6 is past a's span
    expect(pickVariant([[0, "x"], [0, "y"]], 0.9)).toBe("x");
    expect(pickVariant([[0, "x"], [1, "y"]], 0)).toBe("y"); // weight 0 is never picked
  });
});

describe("placing tiles (ASSET_MANIFEST.md cell centres)", () => {
  it("centres square cells in rows and iso cells on the diamond-down layout", () => {
    expect(cellCentre("square", 2, 1, [8, 8])).toEqual([20, 12]);
    expect(cellCentre("isometric", 0, 0, [16, 8])).toEqual([8, 4]);
    expect(cellCentre("isometric", 1, 0, [16, 8])).toEqual([16, 8]);
    expect(cellCentre("isometric", 0, 1, [16, 8])).toEqual([0, 8]);
    expect(cellCentre("isometric", 3, 2, [16, 8])).toEqual([16, 24]);
  });

  const tileset = {
    kind: "tileset", name: "ts", tile_size: [8, 8], shape: "square", terrain_sets: [],
    atlases: [{ id: 0, name: "a", image: "a.png", tile_size: [8, 8], columns: 2, rows: 2, tiles: [{ col: 0, row: 0 }, { col: 1, row: 0 }, { col: 0, row: 1 }, { col: 1, row: 1 }] }],
    stamps: [{ name: "door", size: [1, 2], solid: true, tiles: [[0, 0, 0], [0, 0, 1]] }, { name: "well", size: [2, 2], solid: true, tiles: [[0, 0, 0], [0, 1, 0], [0, 0, 1], [0, 1, 1]] }],
  };

  it("expands a stamps layer: tile j at (x + j % w, y + j // w), in cell order", () => {
    const map = { kind: "map", name: "m", tileset: "ts", size: [4, 4], tile_size: [8, 8], layers: [{ name: "F", kind: "stamps", cells: [[3, 0, 0], [0, 1, 1]] }] };
    const plan = planManifest(minimal([tileset, map]), "t.assets.json");
    expect(plan.errors).toEqual([]);
    const L = plan.maps.get("m")!.layers[0];
    expect(L.count).toBe(6);
    expect(L.cells.map((c) => [c.x, c.y, ...c.tile])).toEqual([[3, 0, 0, 0, 0], [3, 1, 0, 0, 1], [0, 1, 0, 0, 0], [1, 1, 0, 1, 0], [0, 2, 0, 0, 1], [1, 2, 0, 1, 1]]);
    expect(L.cells.map((c) => [c.left, c.top])).toEqual([[24, 0], [24, 8], [0, 8], [8, 8], [0, 16], [8, 16]]);
    expect(loadedResult(plan).assets).toMatchObject({ "map/m": { layers: { F: 6 } } });
  });

  it("refuses a stamp the tileset lacks and a stamp that leaves the map", () => {
    const bad = (cells: number[][]) => planManifest(minimal([tileset, { kind: "map", name: "m", tileset: "ts", size: [4, 4], tile_size: [8, 8], layers: [{ name: "F", kind: "stamps", cells }] }]), "t.assets.json").errors;
    expect(bad([[0, 0, 2]]).length).toBe(1);
    expect(bad([[3, 3, 1]]).length).toBe(1);
  });

  it("skips an unknown layer kind with one warning", () => {
    const map = { kind: "map", name: "m", tileset: "ts", size: [2, 2], tile_size: [8, 8], layers: [{ name: "A", kind: "fog", cells: [] }, { name: "B", kind: "fog", cells: [] }] };
    const plan = planManifest(minimal([tileset, map]), "t.assets.json");
    expect(plan.errors).toEqual([]);
    expect(plan.warnings.filter((w) => w.includes("fog")).length).toBe(1);
    expect(plan.maps.get("m")!.layers.map((L) => L.count)).toEqual([0, 0]);
  });
});

describe("tile flags (transpose first, then flip)", () => {
  // the reference: transpose, then flip h, then flip v, on a point relative to the tile's centre
  const reference = (flags: number, [x, y]: [number, number]): [number, number] => {
    let p: [number, number] = flags & 4 ? [y, x] : [x, y];
    if (flags & 1) p = [-p[0], p[1]];
    if (flags & 2) p = [p[0], -p[1]];
    return p;
  };
  // Phaser's model: flips in the tile's own space, then quarter turns clockwise (y down)
  const phaser = (flags: number, [x, y]: [number, number]): [number, number] => {
    const t = tileTransform(flags);
    let p: [number, number] = [t.flipX ? -x : x, t.flipY ? -y : y];
    for (let i = 0; i < t.quarterTurns; i++) p = [-p[1], p[0]];
    return p;
  };
  it("gives the same picture for every combination", () => {
    for (let flags = 0; flags < 8; flags++) {
      for (const p of [[1, 2], [-3, 1]] as [number, number][]) expect(phaser(flags, p).map((v) => v + 0)).toEqual(reference(flags, p).map((v) => v + 0));
    }
  });
});
