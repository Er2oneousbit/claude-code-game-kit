// ---------------------------------------------------------------------------
// dotwork.golden.test.ts
// Purpose : The Dotwork importer (src/game/dotworkPlan.ts) against the kit's golden pack: data/golden/dotwork/ holds
//           a manifest with every kind and expected.json, the loaded result every engine's importer must reproduce
//           (to 1e-6). Plus the rules the fixture does not reach: version refusal, unknown kinds and fields,
//           the blob rule, tile flags, per-frame timing, bitmap font data.
// Notes   : expected.json is written by tools/art/dotwork/assetspec.py (the reference); never copy its values here.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  bitmapFontData, canon, cellKey, cellMask, DotworkError, frameAt, loadedResult, planManifest, rectToWorld, resolvePath,
  tileAnimations, tileOfGid, tileTransform,
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
    expect(ts.atlases.map((a) => a.firstgid)).toEqual([0, 2, 50, 146, 148]);
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

  it("warns once about the extra kinds it does not draw", () => {
    const w = golden().plan.warnings;
    for (const k of ["background", "particles", "transition", "normal_map", "image"]) expect(w.filter((x) => x.includes(`"${k}"`)).length).toBe(1);
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

describe("blob rule (assetspec.cell_mask, ported)", () => {
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

// {{FOOTER}}
