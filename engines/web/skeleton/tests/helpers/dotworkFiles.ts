// ---------------------------------------------------------------------------
// dotworkFiles.ts
// Purpose : Test helpers for the Dotwork importer: read a manifest from disk into a plan, and list what is wrong
//           with it on disk (missing files, PNGs smaller than the rects cut from them, broken assets, terrain cells
//           no tile fits). The Node half of the stand-in for Dotwork's Godot `verify`; the browser half is
//           src/game/dotworkVerify.ts in `dev.py smoke`.
// Usage   : const { plan, doc } = readPlan(path) ; expect(problems(plan)).toEqual([])
// Notes   : PNG sizes come from the IHDR chunk (no decoder needed).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): a terrain cell without a tile is a problem in
//           every mode (spec 1.1.0 defines the corners4 key); a normal map must be its target's size (#285)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { existsSync, openSync, readFileSync, readSync, closeSync } from "node:fs";
import { planManifest, type DotworkPlan, type Rect } from "../../src/game/dotworkPlan";

export function readPlan(path: string): { plan: DotworkPlan; doc: unknown } {
  const doc = JSON.parse(readFileSync(path, "utf-8")) as unknown;
  return { plan: planManifest(doc, path.replace(/\\/g, "/")), doc };
}

/** [width, height] of a PNG, or null when the file is not a PNG. */
export function pngSize(path: string): [number, number] | null {
  const fd = openSync(path, "r");
  try {
    const head = Buffer.alloc(24);
    if (readSync(fd, head, 0, 24, 0) < 24) return null;
    if (head.readUInt32BE(0) !== 0x89504e47 || head.toString("latin1", 12, 16) !== "IHDR") return null;
    return [head.readUInt32BE(16), head.readUInt32BE(20)];
  } finally {
    closeSync(fd);
  }
}

const fits = (r: Rect, size: [number, number]) => r[0] >= 0 && r[1] >= 0 && r[0] + r[2] <= size[0] && r[1] + r[3] <= size[1];

/** Everything wrong with a plan on disk, one line each (empty: it loads). */
export function problems(plan: DotworkPlan): string[] {
  const out = [...plan.errors];
  const sizes = new Map<string, [number, number] | null>();
  for (const f of plan.files) {
    if (!existsSync(f)) out.push(`missing file ${f}`);
    else if (f.toLowerCase().endsWith(".png")) {
      const s = pngSize(f);
      sizes.set(f, s);
      if (!s) out.push(`${f} is not a PNG`);
    }
  }
  const sizeOf = (key: string) => sizes.get(plan.textures.get(key)?.url ?? "") ?? null;
  for (const fr of plan.frames) {
    const s = sizeOf(fr.texture);
    if (s && !fits(fr.rect, s)) out.push(`frame ${fr.name}: rect ${fr.rect} leaves its ${s[0]}x${s[1]} image`);
  }
  for (const ts of plan.tilesets.values()) {
    for (const at of ts.atlases) {
      const s = sizeOf(at.texture);
      if (s && (s[0] < at.columns * at.tileSize[0] || s[1] < at.rows * at.tileSize[1])) {
        out.push(`tileset ${ts.name} atlas ${at.name}: ${at.columns}x${at.rows} tiles of ${at.tileSize} do not fit its ${s[0]}x${s[1]} image`);
      }
    }
  }
  for (const m of plan.maps.values()) {
    for (const L of m.layers) {
      // spec 1.1.0: every mode's key must have a tile (the validator refuses maps where one does not)
      if (L.unresolved.length) out.push(`map ${m.name} layer ${L.name}: ${L.unresolved.length} terrain cell(s) without a tile`);
    }
    for (const o of m.objects) if (!plan.sprites.has(o.asset) && !plan.animatedSprites.has(o.asset)) out.push(`map ${m.name}: object ${o.asset} is not an asset of this pack`);
  }
  for (const f of plan.fonts.values()) {
    const s = sizeOf(f.texture);
    for (const c of f.chars) if (s && c[8] === 0 && !fits([c[1], c[2], c[3], c[4]], s)) out.push(`font ${f.name}: glyph ${c[0]} leaves page 0`);
  }
  for (const k of plan.uiKits.values()) {
    for (const p of k.parts) {
      const s = sizeOf(p.texture);
      if (s && (s[0] !== p.size[0] || s[1] !== p.size[1])) out.push(`ui_kit ${k.name} part ${p.name}: image is ${s[0]}x${s[1]}, manifest says ${p.size}`);
      if (p.margins && (p.margins[0] + p.margins[2] > p.size[0] || p.margins[1] + p.margins[3] > p.size[1])) out.push(`ui_kit ${k.name} part ${p.name}: margins ${p.margins} exceed the image`);
    }
  }
  for (const pr of plan.portraits.values()) if (pr.animation && !plan.animatedSprites.has(pr.animation)) out.push(`portrait ${pr.name}: animation ${pr.animation} is not in this pack`);
  for (const n of plan.normalMaps.values()) {
    // Phaser samples the normal map with the target's UVs: the two PNGs must be the same size
    const target = sizeOf(n.target);
    const normal = existsSync(n.image) ? pngSize(n.image) : null;
    if (target && normal && (target[0] !== normal[0] || target[1] !== normal[1])) out.push(`normal_map ${n.name}: ${normal[0]}x${normal[1]}, its target is ${target[0]}x${target[1]}`);
  }
  return out;
}

// {{FOOTER}}
