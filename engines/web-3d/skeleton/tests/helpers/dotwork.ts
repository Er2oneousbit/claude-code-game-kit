// ---------------------------------------------------------------------------
// dotwork.ts
// Purpose : Test helpers for the Dotwork importer (src/game/dotwork/): read a manifest from disk, stand-in
//           textures with the real PNG sizes (Three.js objects build in Node without a GPU), and the file check
//           every real manifest of the game must pass (the stand-in for Dotwork's Godot `verify`).
// Usage   : const pack = readPack(path) ; const tex = pngTextures(pack) ; checkPackFiles(path, pack) -> problems[]
// Notes   : Test-only (Node APIs). PNG sizes come from the IHDR chunk, nothing is decoded. checkPackFiles names
//           every problem it finds: a file the manifest names that is missing, a frame / tile / glyph rect outside
//           its image, an image whose size is not the size the manifest gives.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { existsSync, readFileSync } from "node:fs";
import * as THREE from "three";
import { baseDir, importManifest, normalizePath, type PackDef, type Point, type Rect } from "../../src/game/dotwork/manifest";

const PNG_MAGIC = "89504e470d0a1a0a";
const FILE_EXT = /\.(png|fnt)$/i; // strings in a manifest that name a shipped file

/** A path with forward slashes (the importer resolves paths that way on every OS). */
export const posix = (p: string) => p.replace(/\\/g, "/");

/** (width, height) of a PNG from its IHDR chunk. */
export function pngSize(path: string): Point {
  const head = readFileSync(path).subarray(0, 24);
  if (head.length < 24 || head.subarray(0, 8).toString("hex") !== PNG_MAGIC || head.subarray(12, 16).toString("latin1") !== "IHDR") {
    throw new Error(`${path}: not a PNG`);
  }
  return [head.readUInt32BE(16), head.readUInt32BE(20)];
}

/** Imports a manifest file; warnings are collected in the pack (pack.warnings). */
export function readPack(path: string): PackDef {
  return importManifest(JSON.parse(readFileSync(path, "utf-8")), posix(path));
}

/** A texture lookup for the builders: each image a THREE.Texture whose image is a stand-in with the PNG's size. */
export function pngTextures(pack: PackDef): (url: string) => THREE.Texture {
  const cache = new Map<string, THREE.Texture>();
  return (url: string) => {
    let t = cache.get(url);
    if (!t) {
      if (!pack.images.has(url)) throw new Error(`${url} is not an image of pack ${pack.pack}`);
      const [width, height] = pngSize(url);
      t = new THREE.Texture({ width, height } as unknown as HTMLImageElement);
      t.name = url;
      cache.set(url, t);
    }
    return t;
  };
}

const inside = (r: Rect, [w, h]: Point) => r[0] >= 0 && r[1] >= 0 && r[0] + r[2] <= w && r[1] + r[3] <= h;

/** Every problem with the files a manifest names (empty: it loads). */
export function checkPackFiles(manifestPath: string, pack: PackDef, doc = JSON.parse(readFileSync(manifestPath, "utf-8"))): string[] {
  const bad: string[] = [];
  const root = baseDir(posix(manifestPath), doc.base ?? ".");
  const walk = (v: unknown, where: string): void => {
    if (typeof v === "string" && FILE_EXT.test(v)) {
      if (!existsSync(normalizePath(`${root}/${v}`))) bad.push(`${where}: ${v} is missing`);
    } else if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${where}[${i}]`));
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, `${where}.${k}`);
  };
  for (const a of doc.assets ?? []) walk(a, `${a.kind}/${a.name}`);
  if (bad.length) return bad; // the size checks below would only repeat them
  const size = (url: string) => pngSize(url);
  for (const s of pack.sprites.values()) {
    const [w, h] = size(s.image);
    if (w !== s.size[0] || h !== s.size[1]) bad.push(`sprite/${s.name}: image is ${w}x${h}, manifest says ${s.size}`);
  }
  for (const a of pack.animated.values()) {
    for (const c of a.clips.values()) {
      c.frames.forEach((f, i) => {
        if (!inside(f.rect, size(f.texture))) bad.push(`animated_sprite/${a.name}.${c.name}: frame ${i} rect ${f.rect} is outside its image`);
        if (!(f.seconds > 0)) bad.push(`animated_sprite/${a.name}.${c.name}: frame ${i} lasts ${f.seconds} s`);
      });
    }
  }
  for (const ts of pack.tilesets.values()) {
    for (const at of ts.atlases) {
      const img = size(at.image);
      for (const t of at.tiles) {
        const frames = t.anim?.frames ?? 1;
        const r: Rect = [t.col * at.tileSize[0], t.row * at.tileSize[1], at.tileSize[0] * frames, at.tileSize[1]];
        if (!inside(r, img)) bad.push(`tileset/${ts.name}.${at.name}: tile [${t.col}, ${t.row}] (${frames} frame(s)) is outside its image`);
      }
    }
  }
  for (const f of pack.fonts.values()) {
    for (const g of f.glyphs.values()) {
      if (g.page >= f.pages.length) bad.push(`font/${f.name}: char ${g.id} names page ${g.page}`);
      else if (g.w > 0 && !inside([g.x, g.y, g.w, g.h], size(f.pages[g.page]))) bad.push(`font/${f.name}: char ${g.id} is outside its page`);
    }
  }
  for (const k of pack.uiKits.values()) {
    for (const p of k.parts.values()) {
      const [w, h] = size(p.image);
      if (w !== p.size[0] || h !== p.size[1]) bad.push(`ui_kit/${k.name}.${p.name}: image is ${w}x${h}, manifest says ${p.size}`);
    }
  }
  return bad;
}

// {{FOOTER}}
