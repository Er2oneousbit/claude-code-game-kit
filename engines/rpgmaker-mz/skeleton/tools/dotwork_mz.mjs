// ---------------------------------------------------------------------------
// dotwork_mz.mjs
// Purpose : Convert Dotwork's art (the engine-neutral asset manifest, <assets_dir>/dotwork/<pack>.assets.json) into
//           RPG Maker MZ's own image layouts in the game folder: character sheets, object sheets, faces, side-view
//           battlers, enemies, the window skin, IconSet.png and B to E tileset sheets. Records what it wrote and
//           the numbers the database needs (icon indexes, face indexes, tile ids) in <src_dir>/dotwork/mz_export.json.
// Usage   : python tools/dev.py dotwork [options]                 (the usual way; options as below)
//           node tools/dotwork_mz.mjs [--manifest FILE ...] [--game DIR] [--scale N] [--sheet NAME]
//                                     [--only KINDS] [--stand walk|idle] [--side-view] [--replace] [--dry-run]
//                                     [--check] [--debug]
// Exit    : 0 ok (skipped kinds and files it may not overwrite are notes, not failures), 1 an asset failed
//           (a missing or broken PNG, --check found a problem), 2 usage or nothing to convert
// Notes   : A converter, not a loader: MZ reads fixed image layouts from img/<folder>/ by name, and the editor's
//           pickers (character, face, tileset, icon) only see files on disk, so a runtime plugin could not put
//           Dotwork's art in the database or the event editor. Node's standard library only (tools/pngio.mjs).
//           MZ's layouts (verify against a real MZ project; the kit has only run them against stand-ins):
//             characters  img/characters: 3 frames x 4 rows (down, left, right, up) per character; "$" = one
//                         character per file, else 4 x 2 characters; MZ walks columns 1, 2, 1, 0 (1 = standing)
//             objects     "!$" files: a prop or an animated prop, the same frames in all four rows
//             faces       img/faces: 144 x 144 cells, 4 x 2 per file (576 x 288)
//             sv_actors   img/sv_actors: 9 x 6 cells (3 frames per motion, 18 motions); only for side-view games
//             enemies     img/enemies (front view) or img/sv_enemies (side view): one picture each
//             Window.png  img/system: 192 x 192; background, frame (24 px corners), cursor (4 px corners),
//                         arrows, pause sign and 32 text colours (the last three kept from the existing skin);
//                         the ui_kit parts are taken 1:1 (Dotwork already drew them at the kit's `scale`)
//             IconSet.png img/system: 16 columns of 32 x 32 icons; ours are appended below the existing ones
//             tilesets    img/tilesets: B to E sheets of 16 x 16 tiles in two 8-column halves; B's tile 0 is empty
//           Pixel art is never shrunk: every scale is a whole number (System.json tileSize / the art's tile size).
//           Never overwrites a file it did not write (MZ's own Window.png, a sheet you drew) unless --replace,
//           which first keeps the original in build/dotwork_mz/originals/.
//
// Pseudocode:
//   find the manifests (Dotwork's config: <assets_dir>/dotwork, or --manifest) -> read each, refuse another
//   major version -> read MZ's tile size and battle view from data/System.json -> pick the whole-number scale
//   for each asset kind MZ has a place for: plan the cells (numbers only), then compose the image from the
//   frames -> write it when the bytes changed and the file is ours (or --replace) -> every other kind: a note
//   -> write the record (hashes of the files written + the indexes the database needs)
//   --check: the recorded files exist, are unchanged and have MZ's shapes
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { PngError, blank, blit, crop, decodePng, encodePng, fill, pixel, scale, stretch } from "./pngio.mjs";

// ---- Tunables / constants -------------------------------------------------------------------------------
export const SPEC_FORMAT = "dotwork-assets";
export const SPEC_MAJOR = 1;
export const RECORD_FORMAT = "dotwork-mz-export";
export const RECORD_VERSION = 1;
export const KINDS = ["characters", "objects", "faces", "sv", "enemies", "icons", "window", "tilesets"];   // --only
export const MZ = {
  tileSize: 48,                    // System.json "tileSize" when present (MZ's default 48)
  face: 144, faceCols: 4, faceRows: 2,
  icon: 32, iconCols: 16,
  charRows: ["s", "w", "e", "n"],  // MZ's direction rows: down (2), left (4), right (6), up (8)
  sheetChars: [4, 2],              // characters per normal (not "$") sheet
  svCols: 9, svRows: 6, svMin: 64, // side-view battler grid; MZ's default frame is 64 x 64
  skin: 192,                       // Window.png is 192 x 192
  skinCorner: 24, cursorCorner: 4, // the frame's and the cursor's 9-slice corners in Window.png
  tilesetCols: 16, tilesetRows: 16, tilesetHalf: 8, tilesetSheets: ["B", "C", "D", "E"],
};
// MZ's 18 side-view motions in Sprite_Actor's order (index = position): [motion, loops, Dotwork clips to try].
// The battle stills come from Dotwork's character entry "poses": "battle" (ready, weak, ko, victory, hurt, defend,
// cast, item, jump; a still named like an animated clip ships as <pose>_pose_w). A motion with no source shows
// "wait". (verify the motion order in Sprite_Actor.MOTIONS)
export const SV_MOTIONS = [
  ["walk", true, ["walk_w"]], ["wait", true, ["ready_w", "idle_w"]], ["chant", true, ["cast_w", "cast_pose_w"]],
  ["guard", true, ["defend_w", "defend_pose_w"]], ["damage", false, ["hurt_w", "hurt_pose_w"]],
  ["evade", false, ["jump_w", "jump_pose_w", "defend_w"]], ["thrust", false, ["attack_w"]],
  ["swing", false, ["attack_w"]], ["missile", false, ["shoot_w", "attack_w"]], ["skill", false, ["cast_w", "attack_w"]],
  ["spell", false, ["cast_w", "cast_pose_w"]], ["item", false, ["item_w", "item_pose_w"]],
  ["escape", true, ["walk_e"]], ["victory", true, ["victory_w", "victory_pose_w"]],
  ["dying", true, ["weak_w", "weak_pose_w"]], ["abnormal", true, ["hurt_pose_w", "hurt_w", "weak_w"]],
  ["sleep", true, ["ko_w", "ko_pose_w"]], ["dead", true, ["ko_w", "ko_pose_w", "death_w"]],
];
const BATTLE_ONLY = ["ready_w", "weak_w", "ko_w", "victory_w", "defend_w", "item_w", "ready_pose_w", "ko_pose_w"];
// MZ's text colours by ColorManager index, used only when there is no Window.png to keep them from (normal 0,
// system 16, crisis 17, death 18, gauge back 19, hp 20/21, mp 22/23, power up 24, down 25, ct 26/27, tp 28/29).
// The kit's own values, not MZ's: (verify) and prefer keeping the skin MZ's new project ships.
const TEXT_COLOURS = [
  "#ffffff", "#20a0d6", "#ff784c", "#66cc40", "#99ccff", "#ccc0ff", "#ffffa0", "#808080",
  "#c0c0c0", "#2080cc", "#ff3810", "#00a010", "#3e9ade", "#a098ff", "#ffcc20", "#000000",
  "#84aaff", "#ffff40", "#ff2020", "#202040", "#e08040", "#f0c040", "#4080c0", "#40c0f0",
  "#80ff80", "#c08080", "#8080ff", "#ff80ff", "#00a040", "#00e060", "#a060e0", "#c080ff",
];
const MZ_SKIPS = {   // kinds MZ has no place for in this converter, and why (printed once per asset)
  map: "MZ maps are data/MapNNN.json painted with A1 to E tile ids; with no autotiles converted yet, paint the map in MZ's editor",
  font: "MZ draws text with TrueType or WOFF fonts (fonts/, css); a BMFont needs a plugin",
  background: "battle backgrounds and parallaxes (img/battlebacks1, battlebacks2, parallaxes) are a later step",
  particles: "MZ's effects are Effekseer files (effects/); the emitter has no place",
  transition: "MZ fades screens itself; a rule image needs a plugin",
  normal_map: "MZ has no lit sprites",
  image: "no fixed place in MZ (img/pictures takes any picture: copy it there by hand)",
};
const DEBUG_ENV = "DOTWORK_MZ_DEBUG";

// ---- small helpers ------------------------------------------------------------------------------------------
/** A problem with one asset or the input; the caller prints it as one [FAIL] line. */
export class ConvertError extends Error {}

const r6 = (v) => Math.round(v * 1e6) / 1e6;
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const posix = (p) => p.split(sep).join("/");
const hex = (s) => [parseInt(s.slice(1, 3), 16), parseInt(s.slice(3, 5), 16), parseInt(s.slice(5, 7), 16), 255];

// Python's sort order for numbers and lists of numbers (assetspec.expected sorts masks and corner lists with it)
function lexical(x, y) {
  if (typeof x === "number") return x - y;
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

// JSON with one key per line but short arrays (frame picks, cells) and small objects (a tile's slot) on one line
function pretty(v, pad = "") {
  const flat = JSON.stringify(v);
  if (v === null || typeof v !== "object" || flat.length <= 72) return flat;
  const inner = pad + " ";
  if (Array.isArray(v)) return `[\n${v.map((x) => inner + pretty(x, inner)).join(",\n")}\n${pad}]`;
  return `{\n${Object.entries(v).map(([k, x]) => `${inner}${JSON.stringify(k)}: ${pretty(x, inner)}`).join(",\n")}\n${pad}}`;
}

function readJson(file, what) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (err) {
    throw new ConvertError(`${what} ${file}: ${err.code === "ENOENT" ? "not found" : `not valid JSON (${err.message})`}`);
  }
}

// ---- reading the manifest -----------------------------------------------------------------------------------
/**
 * Read one asset manifest. Returns { file, base, doc, pack, path(rel) }: path() resolves an asset path against
 * the manifest's base folder (join(dirname(manifest), base, path)). doc: a document already in memory (tests).
 */
export function loadManifest(file, doc = null) {
  doc = doc ?? readJson(file, "manifest");
  if (doc.format !== SPEC_FORMAT) throw new ConvertError(`${file}: not a Dotwork asset manifest (format ${JSON.stringify(doc.format)})`);
  const major = Number(String(doc.version || "").split(".")[0]);
  if (major !== SPEC_MAJOR) {
    throw new ConvertError(`${file}: manifest version ${doc.version}; this converter reads version ${SPEC_MAJOR}.x (update tools/dotwork_mz.mjs from the kit)`);
  }
  const base = resolve(dirname(file), doc.base || ".");
  const path = (rel) => {
    if (typeof rel !== "string" || rel.startsWith("/") || /^[A-Za-z]:/.test(rel) || rel.split("/").includes("..")) {
      throw new ConvertError(`${file}: unsafe path ${JSON.stringify(rel)}`);
    }
    return join(base, ...rel.split("/"));
  };
  return { file, base, doc, pack: doc.pack || "pack", path };
}

/**
 * The loaded result of the kinds MZ uses, in the shape of assetspec.expected() (data/golden/dotwork/expected.json):
 * animated_sprite, sprite, icon, portrait, tileset, ui_kit. Other kinds are left out (MZ_SKIPS says why).
 */
export function expectedOf(doc) {
  const out = {};
  for (const a of doc.assets) {
    const key = `${a.kind}/${a.name}`;
    if (a.kind === "animated_sprite") {
      const clips = {};
      for (const c of a.clips) {
        clips[c.name] = {
          frames: c.frames.length, rects: c.frames.map((f) => f.rect), seconds: c.frames.map((f) => r6(f.duration)),
          length: r6(c.frames.reduce((s, f) => s + f.duration, 0)), loop: c.loop, pivot: c.pivot.map(r6),
          texture: c.sheet || null,
        };
      }
      out[key] = { blend: a.blend || "normal", clips, directions: a.directions || {} };
    } else if (a.kind === "sprite") {
      out[key] = { size: a.size, pivot: a.pivot.map(r6), collision: (a.collision || []).map((s) => s.rect.map(r6)) };
    } else if (a.kind === "icon") {
      out[key] = { sizes: a.sizes.map((s) => s.size).sort((x, y) => x - y) };
    } else if (a.kind === "portrait") {
      out[key] = { size: a.size, expressions: a.expressions.map((e) => e.name).sort(), animation: a.animation ?? null };
    } else if (a.kind === "tileset") {
      const masks = {};
      let n = 0, coll = 0, anim = 0;
      for (const at of a.atlases) {
        for (const t of at.tiles) {
          n++; coll += t.collision?.length ? 1 : 0; anim += t.anim ? 1 : 0;
          if ("terrain" in t) {
            const tk = `${t.terrain_set ?? 0}/${t.terrain}`;
            const v = "mask" in t ? t.mask : Object.keys(t.corners).sort().map((c) => t.corners[c]);
            masks[tk] ??= [];
            if (!masks[tk].some((m) => JSON.stringify(m) === JSON.stringify(v))) masks[tk].push(v);
          }
        }
      }
      const sorted = {};
      for (const tk of Object.keys(masks).sort()) sorted[tk] = masks[tk].sort(lexical);
      const terrains = {};
      for (const s of a.terrain_sets || []) for (const t of s.terrains) terrains[`${s.id}/${t.id}`] = t.name;
      out[key] = { tile_size: a.tile_size, shape: a.shape, tiles: n, collision_tiles: coll, animated_tiles: anim, terrains, masks: sorted };
    } else if (a.kind === "ui_kit") {
      const parts = {};
      for (const p of a.parts) parts[p.name] = { size: p.size, margins: p.margins ?? null, hotspot: p.hotspot ?? null };
      out[key] = { parts };
    }
  }
  return out;
}

// ---- the MZ project -----------------------------------------------------------------------------------------
/** MZ's tile size and battle view from data/System.json (MZ's defaults when there is no project yet). */
export function mzSettings(game) {
  const file = join(game, "data", "System.json");
  if (!existsSync(file)) return { tileSize: MZ.tileSize, sideView: false, found: false };
  const sys = readJson(file, "MZ system file");
  const tile = Number(sys.tileSize) || MZ.tileSize;   // (verify) MZ 1.x keeps it in System.json; absent = 48
  return { tileSize: tile, sideView: !!sys.optSideView, found: true };
}

/**
 * The whole-number scale from Dotwork pixels to MZ pixels: forced, else MZ's tile size over the art's tile size
 * (the first square tileset whose size divides it), else the largest that keeps a walking character's frame
 * within one MZ tile. Returns { k, why }.
 */
export function chooseScale(docs, tileSize, forced = 0) {
  if (forced) return { k: forced, why: `--scale ${forced}` };
  for (const doc of docs) {
    for (const a of doc.assets) {
      if (a.kind === "tileset" && a.shape === "square" && a.tile_size[0] === a.tile_size[1] && tileSize % a.tile_size[0] === 0) {
        return { k: tileSize / a.tile_size[0], why: `MZ tile ${tileSize} / tileset ${a.name} ${a.tile_size[0]} px` };
      }
    }
  }
  for (const doc of docs) {
    for (const a of doc.assets) {
      const src = a.kind === "animated_sprite" ? characterSource(a) : null;
      if (src) {
        const w = src.clips.s.frame_size[0];
        return { k: Math.max(1, Math.floor(tileSize / w)), why: `MZ tile ${tileSize} / ${a.name}'s frame width ${w}` };
      }
    }
  }
  return { k: 1, why: "no tileset or character to scale from" };
}

// ---- planning (numbers only; the tests check these) -----------------------------------------------------------
/**
 * The 3 walk frames MZ needs, as Dotwork frame indexes for MZ's columns 0, 1, 2. Column 1 stands (MZ shows it
 * when idle) and MZ walks 1, 2, 1, 0. Dotwork's pose-driven walk starts with the feet together (frame 0) and
 * reaches its two strides a quarter and three quarters through, so: [3n/4, 0, n/4] keeps Dotwork's order.
 */
export function walkPicks(n) {
  if (n <= 1) return [0, 0, 0];
  if (n === 2) return [1, 0, 1];
  return [Math.round((3 * n) / 4) % n, 0, Math.round(n / 4) % n];
}

/** Three frames spread over a clip: a loop evenly, a one-shot first / middle / last. */
export function spreadPicks(n, loop) {
  if (n <= 1) return [0, 0, 0];
  if (!loop) return [0, Math.floor((n - 1) / 2), n - 1];
  return [0, Math.round(n / 3) % n, Math.round((2 * n) / 3) % n];
}

const clipOf = (a, name) => a.clips.find((c) => c.name === name) || null;

/** The clips a character sheet comes from: walk (else idle) in s, w, e and n, or null. */
export function characterSource(a) {
  const dirs = a.directions || {};
  for (const action of ["walk", "idle"]) {
    const t = dirs[action];
    if (t && MZ.charRows.every((d) => t[d] && clipOf(a, t[d]))) {
      return { action, clips: Object.fromEntries(MZ.charRows.map((d) => [d, clipOf(a, t[d])])) };
    }
  }
  return null;
}

/** One frame of a clip as a plan entry: where its pixels are and its pivot. */
function frameRef(clip, i) {
  const f = clip.frames[i];
  return { clip: clip.name, index: i, file: f.file, sheet: clip.sheet || null, rect: f.rect, size: clip.frame_size, pivot: clip.pivot };
}

/**
 * The cell that holds every frame at scale k with its pivot on the cell's bottom centre (MZ anchors characters,
 * battlers and enemies at the feet: anchor 0.5, 1), at least minW x minH. cut: frames reach below their pivot
 * (that part is lost). Each frame's offset in the cell: offsetIn().
 */
export function cellFor(frames, k, minW, minH) {
  let half = 0, up = 0, cut = false;
  for (const f of frames) {
    const [w, h] = f.size, [px, py] = f.pivot;
    half = Math.max(half, px * k, (w - px) * k);
    up = Math.max(up, py * k);
    if (h - py > 0) cut = true;
  }
  return { w: Math.max(minW, 2 * Math.ceil(half)), h: Math.max(minH, Math.ceil(up)), cut };
}

/** Where a frame's top-left goes in a cell (pivot on the bottom centre). */
export function offsetIn(cell, f, k) {
  return [Math.round(cell.w / 2 - f.pivot[0] * k), Math.round(cell.h - f.pivot[1] * k)];
}

/** A character sheet plan: per MZ row the three frames, the cell, the sheet size. stand: "walk" or "idle". */
export function characterPlan(a, k, tile, stand = "walk") {
  const src = characterSource(a);
  if (!src) return null;
  const rows = {}, picks = {}, notes = [];
  for (const d of MZ.charRows) {
    const clip = src.clips[d];
    const p = src.action === "walk" ? walkPicks(clip.frames.length) : spreadPicks(clip.frames.length, true);
    picks[d] = p;
    rows[d] = p.map((i) => frameRef(clip, i));
    const idle = stand === "idle" && a.directions?.idle?.[d] ? clipOf(a, a.directions.idle[d]) : null;
    if (idle) rows[d][1] = frameRef(idle, 0);
  }
  if (src.action !== "walk") notes.push(`${a.name}: no walk in four directions, the sheet uses ${src.action}`);
  const all = Object.values(rows).flat();
  const cell = cellFor(all, k, tile, tile);
  if (cell.cut) notes.push(`${a.name}: frames reach below the feet; MZ's cell ends at the feet, that part is cut`);
  return { name: a.name, action: src.action, picks, rows, cell, sheet: [cell.w * 3, cell.h * 4], k, notes };
}

/** An object sheet ("!$"): a prop's picture, or three frames of an animated prop's first clip, in all four rows. */
export function objectPlan(a, k, tile) {
  let frames;
  if (a.kind === "sprite") {
    const f = { clip: null, index: 0, file: a.image, sheet: null, rect: [0, 0, ...a.size], size: a.size, pivot: a.pivot };
    frames = [f, f, f];
  } else {
    const clip = a.clips[0];
    frames = spreadPicks(clip.frames.length, clip.loop).map((i) => frameRef(clip, i));
  }
  const cell = cellFor(frames, k, tile, tile);
  const rows = Object.fromEntries(MZ.charRows.map((d) => [d, frames]));
  return { name: a.name, rows, cell, sheet: [cell.w * 3, cell.h * 4], k, notes: [] };
}

/** A face file plan: expressions in manifest order (neutral first) as face indexes, scaled to fit 144 x 144. */
export function facePlan(p) {
  const [w, h] = p.size;
  if (w > MZ.face || h > MZ.face) return { name: p.name, skip: `${p.name}: ${w}x${h} is larger than MZ's ${MZ.face} px face (pixel art is never shrunk)` };
  const k = Math.max(1, Math.floor(Math.min(MZ.face / w, MZ.face / h)));
  const per = MZ.faceCols * MZ.faceRows;
  const files = [];
  p.expressions.forEach((e, i) => {
    const f = Math.floor(i / per);
    files[f] ??= { file: f ? `${p.name}_${f + 1}` : p.name, faces: [] };
    files[f].faces.push({ name: e.name, image: e.image, index: i % per });
  });
  const offset = [Math.floor((MZ.face - w * k) / 2), MZ.face - h * k];   // centred, the bust on the bottom edge
  return { name: p.name, k, offset, files, sheet: [MZ.face * MZ.faceCols, MZ.face * MZ.faceRows] };
}

/** True when a character has Dotwork's battle stills (character entry "poses": "battle"). */
export function hasBattlePoses(a) {
  return a.clips.some((c) => BATTLE_ONLY.includes(c.name));
}

/** A side-view battler plan: for each of MZ's 18 motions the clip and its three frames (or wait's). */
export function svPlan(a, k) {
  const motions = [], missing = [];
  let wait = null;
  SV_MOTIONS.forEach(([motion, loop, sources], index) => {
    const clip = sources.map((s) => clipOf(a, s)).find(Boolean) || null;
    let picks = null;
    if (clip) {
      const n = clip.frames.length;
      picks = motion === "walk" || motion === "escape" ? walkPicks(n)
        : motion === "dead" && !clip.loop ? [n - 1, n - 1, n - 1] : spreadPicks(n, loop && clip.loop);
    } else missing.push(motion);
    motions.push({ motion, index, clip, picks });
    if (motion === "wait") wait = clip ? { clip, picks } : null;
  });
  if (!wait) return { name: a.name, skip: `${a.name}: no ready_w or idle_w clip for MZ's wait motion` };
  for (const m of motions) if (!m.clip) Object.assign(m, wait);
  const frames = motions.map((m) => m.picks.map((i) => frameRef(m.clip, i)));
  const cell = cellFor(frames.flat(), k, MZ.svMin, MZ.svMin);
  return {
    name: a.name, k, cell, sheet: [cell.w * MZ.svCols, cell.h * MZ.svRows], missing,
    motions: motions.map((m, i) => ({ motion: m.motion, index: m.index, clip: m.clip.name, picks: m.picks,
      col: Math.floor(m.index / MZ.svRows) * 3, row: m.index % MZ.svRows, frames: frames[i] })),
  };
}

/** The icon size to use and its scale to MZ's 32 px cell (a size that divides 32, the largest), or null. */
export function iconPick(icon) {
  const fits = icon.sizes.filter((s) => s.size <= MZ.icon && MZ.icon % s.size === 0).sort((x, y) => y.size - x.size);
  return fits.length ? { size: fits[0].size, image: fits[0].image, k: MZ.icon / fits[0].size } : null;
}

/** The B to E sheet position of a tile id within one sheet (0..255): pixel cell (col, row). */
export function tileSlot(id) {
  return { col: (Math.floor(id / 128) % 2) * MZ.tilesetHalf + (id % MZ.tilesetHalf), row: Math.floor((id % 256) / MZ.tilesetHalf) % MZ.tilesetRows };
}

/**
 * Plain tiles (no terrain) of a square tileset placed on B to E sheets: stamps first as blocks (in the editor's
 * palette, 8 tiles wide, the left half above the right one), then every other plain tile in atlas order. B's
 * tile 0 is MZ's empty tile and stays free. Returns { tiles: {"atlas,col,row": {sheet, id, tile_id, passable}},
 * sheets, skipped } or { skip }.
 */
export function tilesetPlan(ts, k, tile) {
  const [tw, th] = ts.tile_size;
  if (ts.shape !== "square" || tw !== th) return { name: ts.name, skip: `${ts.name}: ${ts.shape} tiles; MZ maps are square` };
  if (tw * k !== tile) return { name: ts.name, skip: `${ts.name}: ${tw} px tiles at scale ${k} are ${tw * k} px, MZ's tiles are ${tile} px (set MZ's tile size or --scale)` };
  const atlases = new Map(ts.atlases.map((at) => [at.id, at]));
  const plain = new Map(), terrain = [], odd = [];
  for (const at of ts.atlases) {
    for (const t of at.tiles) {
      const key = `${at.id},${t.col},${t.row}`;
      if ("terrain" in t) terrain.push(key);
      else if (at.tile_size[0] !== tw || at.tile_size[1] !== th || t.origin) odd.push(key);
      else plain.set(key, { atlas: at, tile: t });
    }
  }
  const sheets = MZ.tilesetSheets.map(() => Array(256).fill(null));
  sheets[0][0] = "empty";
  const place = (keys, w, h) => {   // the first free block of w x h in palette order (8 wide, 32 tall per sheet)
    for (let s = 0; s < sheets.length; s++) {
      for (let pr = 0; pr + h <= 32; pr++) {
        for (let pc = 0; pc + w <= MZ.tilesetHalf; pc++) {
          const ids = [];
          for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) ids.push((pr + y) * MZ.tilesetHalf + pc + x);
          if (ids.every((id) => sheets[s][id] === null)) {
            ids.forEach((id, i) => { sheets[s][id] = keys[i]; });
            return ids.map((id) => [s, id]);
          }
        }
      }
    }
    return null;
  };
  const tiles = {}, notes = [];
  const put = (key, at) => {
    const t = plain.get(key);
    tiles[key] = { sheet: MZ.tilesetSheets[at[0]], id: at[1], tile_id: at[0] * 256 + at[1], passable: !t.tile.collision?.length,
      ...(t.tile.anim ? { animated: true } : {}) };
  };
  for (const st of ts.stamps || []) {
    const keys = st.tiles.map((t) => t.join(","));
    const [w, h] = st.size;
    if (w > MZ.tilesetHalf || !keys.every((key) => plain.has(key) && !tiles[key])) continue;
    const at = place(keys, w, h);
    if (at) keys.forEach((key, i) => put(key, at[i]));
  }
  for (const key of plain.keys()) {
    if (tiles[key]) continue;
    const at = place([key], 1, 1);
    if (!at) { notes.push(`${ts.name}: more than ${4 * 256 - 1} plain tiles; the rest did not fit on B to E`); break; }
    put(key, at[0]);
  }
  if (terrain.length) notes.push(`${ts.name}: ${terrain.length} terrain tile(s) skipped: MZ autotiles (A1 to A4) are built from quarter tiles, not blob or corner tiles (a later step)`);
  if (odd.length) notes.push(`${ts.name}: ${odd.length} tile(s) larger than a cell or off-centre skipped`);
  const anim = Object.values(tiles).filter((t) => t.animated).length;
  if (anim) notes.push(`${ts.name}: ${anim} animated tile(s) keep their first frame (B to E tiles do not animate)`);
  const used = sheets.map((s, i) => [MZ.tilesetSheets[i], s]).filter(([letter, s]) => s.some((v, id) => v && !(letter === "B" && id === 0)));
  return { name: ts.name, k, tile, atlases, plain, tiles, sheets: Object.fromEntries(used), notes };
}

// ---- composing (pixels) ---------------------------------------------------------------------------------------
/** An image cache over one manifest's paths. */
function imageLoader(m) {
  const cache = new Map();
  return (rel) => {
    const file = m.path(rel);
    if (!cache.has(file)) {
      if (!existsSync(file)) throw new ConvertError(`${rel}: missing (${file})`);
      try {
        cache.set(file, decodePng(readFileSync(file), rel));
      } catch (err) {
        throw new ConvertError(err instanceof PngError ? err.message : `${rel}: ${err.message}`);
      }
    }
    return cache.get(file);
  };
}

/** A frame's pixels at Dotwork scale: from the sheet's rect when there is a sheet, else the frame's own file. */
function frameImage(load, f) {
  if (f.sheet) return crop(load(f.sheet), ...f.rect);
  const img = load(f.file);
  return f.rect && (f.rect[2] !== img.width || f.rect[3] !== img.height) ? crop(img, ...f.rect) : img;
}

/** Draw rows {dir: [3 frames]} of one character into sheet at block (bx, by) (in cells). */
function drawCharacter(sheet, load, plan, bx = 0, by = 0, cell = plan.cell) {
  MZ.charRows.forEach((d, row) => {
    plan.rows[d].forEach((f, col) => {
      const [ox, oy] = offsetIn(cell, f, plan.k);
      blit(sheet, scale(frameImage(load, f), plan.k), (bx * 3 + col) * cell.w + ox, (by * 4 + row) * cell.h + oy);
    });
  });
}

export function composeCharacter(load, plan) {
  const sheet = blank(...plan.sheet);
  drawCharacter(sheet, load, plan);
  return sheet;
}

/** A normal (not "$") sheet of up to 8 characters in MZ's 4 x 2 blocks, one shared cell size. */
export function composeCharacterSheet(loads, plans) {
  const cell = { w: Math.max(...plans.map((p) => p.cell.w)), h: Math.max(...plans.map((p) => p.cell.h)) };
  const [cols, rows] = MZ.sheetChars;
  const sheet = blank(cell.w * 3 * cols, cell.h * 4 * rows);
  plans.forEach((p, i) => drawCharacter(sheet, loads[i], p, i % cols, Math.floor(i / cols), cell));
  return { sheet, cell };
}

export function composeFaces(load, plan, file) {
  const sheet = blank(...plan.sheet);
  for (const f of file.faces) {
    const img = scale(load(f.image), plan.k);
    blit(sheet, img, (f.index % MZ.faceCols) * MZ.face + plan.offset[0], Math.floor(f.index / MZ.faceCols) * MZ.face + plan.offset[1]);
  }
  return sheet;
}

export function composeSv(load, plan) {
  const sheet = blank(...plan.sheet);
  for (const m of plan.motions) {
    m.frames.forEach((f, i) => {
      const [ox, oy] = offsetIn(plan.cell, f, plan.k);
      blit(sheet, scale(frameImage(load, f), plan.k), (m.col + i) * plan.cell.w + ox, m.row * plan.cell.h + oy);
    });
  }
  return sheet;
}

/** A 9-slice image rendered at w x h: corners scaled by k, edges and centre stretched. */
export function nineSlice(img, margins, k, w, h) {
  const [l, t, r, b] = margins, out = blank(w, h);
  const xs = [[0, l, 0, l * k], [l, img.width - l - r, l * k, w - (l + r) * k], [img.width - r, r, w - r * k, r * k]];
  const ys = [[0, t, 0, t * k], [t, img.height - t - b, t * k, h - (t + b) * k], [img.height - b, b, h - b * k, b * k]];
  for (const [sy, sh, dy, dh] of ys) {
    for (const [sx, sw, dx, dw] of xs) {
      if (sw > 0 && sh > 0 && dw > 0 && dh > 0) blit(out, stretch(crop(img, sx, sy, sw, sh), dw, dh), dx, dy);
    }
  }
  return out;
}

/** The first opaque colour on the window part's top edge (arrows and the pause sign use it), else white. */
function inkOf(part) {
  for (let x = 0; x < part.width; x++) {
    const p = pixel(part, x, 0);
    if (p[3] === 255) return p;
  }
  return [255, 255, 255, 255];
}

function triangle(img, x, y, w, down, rgba) {   // a w-wide, w/2-tall triangle pointing down (or up)
  const h = Math.floor(w / 2);
  for (let i = 0; i < h; i++) {
    const row = down ? i : h - 1 - i;
    fill(img, x + i, y + row, w - 2 * i, 1, rgba);
  }
}

/**
 * Window.png from a ui_kit window part (and a hover / focus button as the cursor). Keeps the existing skin's
 * arrows, pause sign and text colours when there is one (MZ's new project ships its own); draws simple ones
 * otherwise. Layout (verify): background 0,0,96,96; pattern 0,96,96,96 (cleared); frame 96,0,96,96 with 24 px
 * corners and its middle left free for the arrows (132,24 and 132,60, 24 x 12); cursor 96,96,48,48 with 4 px
 * corners; pause sign 144,96, four 24 x 24 frames; text colours 96,144, 8 x 4 squares of 12 px.
 * The parts are used 1:1: a ui_kit's images and margins are already drawn at the kit's `scale` (Dotwork's
 * windows lane upscales them), so they are never scaled again. Returns { skin, notes }.
 */
export function composeWindow(window, cursor, existing) {
  const S = MZ.skin, C = MZ.skinCorner, notes = [];
  const keep = existing && existing.width === S && existing.height === S;
  const skin = keep ? crop(existing, 0, 0, S, S) : blank(S, S);
  const m = window.margins || [0, 0, 0, 0];
  if (Math.max(...m) > C) notes.push(`the window part's margins (${m}) are wider than MZ's ${C} px frame corner: MZ cuts the corners there`);
  fill(skin, 0, 0, 96, 192, [0, 0, 0, 0]);                       // background and pattern
  const centre = crop(window.img, m[0], m[1], window.img.width - m[0] - m[2], window.img.height - m[1] - m[3]);
  blit(skin, stretch(centre.width && centre.height ? centre : window.img, 96, 96), 0, 0);
  const arrows = keep ? crop(skin, 120, 24, 48, 48) : null;      // the frame's free middle (arrows live there)
  fill(skin, 96, 0, 96, 96, [0, 0, 0, 0]);
  blit(skin, nineSlice(window.img, m, 1, 96, 96), 96, 0);
  fill(skin, 96 + C, C, 96 - 2 * C, 96 - 2 * C, [0, 0, 0, 0]);
  const ink = inkOf(window.img);
  if (arrows) blit(skin, arrows, 120, 24);
  else {
    triangle(skin, 132, 24, 24, false, ink);
    triangle(skin, 132, 60, 24, true, ink);
  }
  if (cursor) {
    const cm = cursor.margins || [0, 0, 0, 0];
    if (Math.max(...cm) > MZ.cursorCorner) notes.push(`the cursor part's margins (${cm}) are wider than MZ's ${MZ.cursorCorner} px cursor corner: MZ stretches the rest`);
    fill(skin, 96, 96, 48, 48, [0, 0, 0, 0]);
    blit(skin, nineSlice(cursor.img, cm, 1, 48, 48), 96, 96);
  } else if (!keep) {
    fill(skin, 96, 96, 48, 48, [255, 255, 255, 64]);
  }
  if (!keep) {
    [0, 2, 4, 2].forEach((dy, i) => triangle(skin, 144 + (i % 2) * 24 + 6, 96 + Math.floor(i / 2) * 24 + 8 + dy, 12, true, ink));
    TEXT_COLOURS.forEach((c, n) => fill(skin, 96 + (n % 8) * 12, 144 + Math.floor(n / 8) * 12, 12, 12, hex(c)));
  }
  return { skin, notes };
}

/** IconSet.png: the base rows kept, our icons appended in 16 columns from index baseRows * 16. */
export function composeIconSet(base, baseRows, icons) {
  const rows = baseRows + Math.ceil(icons.length / MZ.iconCols);
  const out = blank(MZ.icon * MZ.iconCols, Math.max(1, rows) * MZ.icon);
  if (base) blit(out, crop(base, 0, 0, MZ.icon * MZ.iconCols, baseRows * MZ.icon), 0, 0);
  icons.forEach((img, i) => {
    const index = baseRows * MZ.iconCols + i;
    blit(out, img, (index % MZ.iconCols) * MZ.icon, Math.floor(index / MZ.iconCols) * MZ.icon);
  });
  return out;
}

/** One B to E sheet image from a tileset plan's slots. */
export function composeTileSheet(load, plan, slots) {
  const T = plan.tile, out = blank(MZ.tilesetCols * T, MZ.tilesetRows * T);
  slots.forEach((key, id) => {
    if (!key || key === "empty") return;
    const { atlas, tile } = plan.plain.get(key);
    const [tw, th] = atlas.tile_size;
    const img = scale(crop(load(atlas.image), tile.col * tw, tile.row * th, tw, th), plan.k);
    const { col, row } = tileSlot(id);
    blit(out, img, col * T, row * T);
  });
  return out;
}

// ---- writing with the record ----------------------------------------------------------------------------------
/** Paths and settings for one project: root (the kit project), game (the MZ project), record, manifests. */
export function projectPaths(root, game = null) {
  const conf = join(root, "art_src", "dotwork", "dotwork.config.json");   // Dotwork's per-game config
  let assets = "assets", src = "assets_src";
  if (existsSync(conf)) {
    const c = readJson(conf, "Dotwork config");
    assets = c.project?.assets_dir || assets;
    src = c.project?.src_dir || src;
  }
  if (!game) {
    const g = join(root, "game");
    game = existsSync(join(g, "index.html")) || readdirSafe(g).some((n) => n.endsWith(".rmmzproject")) ? g
      : readdirSafe(root).some((n) => n.endsWith(".rmmzproject")) && existsSync(join(root, "js", "rmmz_core.js")) ? root : g;
  }
  const dirs = [...new Set([join(root, assets, "dotwork"), join(game, "img", "dotwork")])];
  return { root, game, record: join(root, src, "dotwork", "mz_export.json"), manifestDirs: dirs };
}

function readdirSafe(d) {
  try { return readdirSync(d); } catch { return []; }
}

/** Every *.assets.json in the manifest folders, sorted. */
export function findManifests(dirs) {
  const out = [];
  for (const d of dirs) for (const n of readdirSafe(d).sort()) if (n.endsWith(".assets.json")) out.push(join(d, n));
  return out;
}

class Writer {
  constructor(paths, record, opts, log) {
    this.paths = paths; this.old = record?.files || {}; this.files = {}; this.opts = opts; this.log = log;
    this.wrote = 0; this.same = 0; this.held = 0;
  }

  /** Write img to game/<rel> (posix) if the policy allows; returns true when the file now holds it. */
  put(rel, img) {
    const bytes = encodePng(img), hash = sha256(bytes);
    const file = join(this.paths.game, ...rel.split("/"));
    if (existsSync(file)) {
      const now = sha256(readFileSync(file));
      if (now === hash) { this.files[rel] = hash; this.same++; return true; }
      if (this.old[rel] !== now) {
        if (!this.opts.replace) {
          this.held++;
          this.log("skip", `${rel} is not one Dotwork wrote (MZ's own, or edited since): --replace overwrites it (the original is kept in build/dotwork_mz/originals/)`);
          if (this.old[rel]) this.files[rel] = this.old[rel];   // still ours on record: --check reports the edit
          return false;
        }
        const keep = join(this.paths.root, "build", "dotwork_mz", "originals", ...rel.split("/"));
        if (!this.opts.dryRun && !existsSync(keep)) {
          mkdirSync(dirname(keep), { recursive: true });
          copyFileSync(file, keep);
        }
        this.log("info", `${rel}: replaced; the earlier file is in ${posix(relative(this.paths.root, keep))}`);
      }
    }
    this.files[rel] = hash;
    this.wrote++;
    if (this.opts.dryRun) { this.log("dry", `would write ${rel} (${img.width}x${img.height})`); return true; }
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, bytes);
    this.log("OK", `${rel} (${img.width}x${img.height})`);
    return true;
  }

  /** The current file's image when it exists and decodes (for Window.png and IconSet.png), else null. */
  current(rel) {
    const file = join(this.paths.game, ...rel.split("/"));
    try {
      return existsSync(file) ? decodePng(readFileSync(file), rel) : null;
    } catch (err) {
      this.log("WARN", `${rel}: ${err.message}; starting from an empty one`);
      return null;
    }
  }

  /** True when the file on disk is the one this converter wrote last time. */
  ours(rel) {
    const file = join(this.paths.game, ...rel.split("/"));
    return !!this.old[rel] && existsSync(file) && sha256(readFileSync(file)) === this.old[rel];
  }
}

/**
 * Convert every manifest. opts: { scale, sheet, only (kinds), stand, sideView (force), replace, dryRun }.
 * manifests: loaded manifests (loadManifest). Returns { record, failures, notes, written }.
 */
export function exportAll(paths, manifests, opts = {}, log = () => {}) {
  const only = new Set(opts.only?.length ? opts.only : KINDS);
  const mz = mzSettings(paths.game);
  if (!mz.found) log("info", `no data/System.json in ${posix(relative(paths.root, paths.game)) || "."}: MZ's defaults (${mz.tileSize} px tiles, front-view battles)`);
  const sideView = opts.sideView || mz.sideView;
  const { k, why } = chooseScale(manifests.map((m) => m.doc), mz.tileSize, opts.scale);
  log("info", `scale ${k} (${why})`);
  const old = existsSync(paths.record) ? readJson(paths.record, "export record") : null;
  const w = new Writer(paths, old, opts, log);
  const report = {}, failures = [], notes = [];
  const used = new Set();
  // A file name in an img folder. Names are unique per pack only: a second pack's twin gets its pack prefix.
  const named = (folder, pack, name, prefix = "") => {
    const n = used.has(`${folder}/${prefix}${name}`) ? `${prefix}${pack}_${name}` : `${prefix}${name}`;
    used.add(`${folder}/${n}`);
    return n;
  };
  const sheetChars = [];
  const iconImgs = [], iconNames = [];
  let windowDone = false;
  const tryAsset = (m, what, fn) => {
    try {
      fn();
    } catch (err) {
      if (!(err instanceof ConvertError || err instanceof PngError)) throw err;
      failures.push(`${m.pack}: ${what}: ${err.message}`);
    }
  };
  for (const m of manifests) {
    const load = imageLoader(m);
    const r = report[m.pack] = { characters: {}, objects: {}, faces: {}, sv_actors: {}, enemies: {}, icons: {}, tilesets: {}, skipped: [] };
    const note = (text) => { r.skipped.push(text); notes.push(`${m.pack}: ${text}`); };
    for (const a of m.doc.assets) {
      if (MZ_SKIPS[a.kind]) { note(`${a.kind} ${a.name}: ${MZ_SKIPS[a.kind]}`); continue; }
      if (a.kind === "animated_sprite") {
        if (characterSource(a)) {
          tryAsset(m, a.name, () => {
            if (only.has("characters")) {
              const plan = characterPlan(a, k, mz.tileSize, opts.stand);
              plan.notes.forEach(note);
              if (opts.sheet) sheetChars.push({ m, load, plan });
              else {
                const file = named("characters", m.pack, a.name, "$");
                if (w.put(`img/characters/${file}.png`, composeCharacter(load, plan))) {
                  r.characters[a.name] = { file, index: 0, from: plan.action, frames: plan.picks, cell: [plan.cell.w, plan.cell.h] };
                }
              }
            }
            if (only.has("sv")) {
              if (!sideView) { if (hasBattlePoses(a)) note(`${a.name}: battle poses not converted: this is a front-view game (System.json optSideView; --side-view converts them anyway)`); return; }
              if (!hasBattlePoses(a)) { note(`${a.name}: no side-view battler: no battle poses (Dotwork character entry "poses": "battle")`); return; }
              const plan = svPlan(a, k);
              if (plan.skip) { note(plan.skip); return; }
              const file = named("sv_actors", m.pack, a.name);
              if (w.put(`img/sv_actors/${file}.png`, composeSv(load, plan))) {
                r.sv_actors[a.name] = { file, cell: [plan.cell.w, plan.cell.h], motions: Object.fromEntries(plan.motions.map((x) => [x.motion, x.clip])), missing: plan.missing };
              }
            }
          });
        } else if (a.role === "props") {
          if (!only.has("objects")) continue;
          tryAsset(m, a.name, () => objectOut(m, a, load));
        } else if (a.role !== "portraits") {
          note(`animated_sprite ${a.name} (${a.role}): no walk or idle in four directions; MZ's battle animations are Effekseer files`);
        }
      } else if (a.kind === "sprite") {
        const enemy = a.role === "enemies" || a.shadow;
        if (enemy ? !only.has("enemies") : !only.has("objects")) continue;
        tryAsset(m, a.name, () => (enemy ? enemyOut(m, a, load) : objectOut(m, a, load)));
      } else if (a.kind === "portrait") {
        if (!only.has("faces")) continue;
        tryAsset(m, a.name, () => {
          const plan = facePlan(a);
          if (plan.skip) { note(plan.skip); return; }
          for (const f of plan.files) {
            const file = named("faces", m.pack, f.file);
            if (w.put(`img/faces/${file}.png`, composeFaces(load, plan, f))) {
              for (const x of f.faces) (r.faces[a.name] ??= {})[x.name] = { file, index: x.index };
            }
          }
        });
      } else if (a.kind === "icon") {
        if (!only.has("icons")) continue;
        tryAsset(m, a.name, () => {
          const pick = iconPick(a);
          if (!pick) { note(`icon ${a.name}: no size that divides MZ's ${MZ.icon} px icon (sizes ${a.sizes.map((s) => s.size)})`); return; }
          iconImgs.push(scale(load(pick.image), pick.k));
          iconNames.push([r, a.name]);
        });
      } else if (a.kind === "ui_kit") {
        if (!only.has("window")) continue;
        const win = a.parts.find((p) => p.role === "window");
        if (!win) { note(`ui_kit ${a.name}: no window part for Window.png`); continue; }
        if (windowDone) { note(`ui_kit ${a.name}: Window.png already made from an earlier kit`); continue; }
        tryAsset(m, a.name, () => {
          const cur = a.parts.find((p) => p.role === "button" && (p.state === "hover" || p.state === "focus"));
          const rel = "img/system/Window.png";
          const { skin, notes: wn } = composeWindow({ img: load(win.image), margins: win.margins }, cur ? { img: load(cur.image), margins: cur.margins } : null, w.current(rel));
          wn.forEach((x) => note(`ui_kit ${a.name}: ${x}`));
          windowDone = true;
          if (w.put(rel, skin)) r.window = { from: win.name, cursor: cur?.name ?? null };
          if (!cur) note(`ui_kit ${a.name}: no hover or focus button: the cursor stays as it was`);
        });
      } else if (a.kind === "tileset") {
        if (!only.has("tilesets")) continue;
        tryAsset(m, a.name, () => {
          const plan = tilesetPlan(a, k, mz.tileSize);
          if (plan.skip) { note(plan.skip); return; }
          plan.notes.forEach(note);
          const files = {};
          for (const [letter, slots] of Object.entries(plan.sheets)) {
            const file = named("tilesets", m.pack, `${m.pack}_${a.name}_${letter}`);
            if (w.put(`img/tilesets/${file}.png`, composeTileSheet(load, plan, slots))) files[letter] = file;
          }
          if (Object.keys(files).length) r.tilesets[a.name] = { sheets: files, tiles: plan.tiles };
        });
      } else {
        note(`${a.kind} ${a.name}: unknown kind, skipped`);
      }
    }

    function objectOut(mf, a, ld) {
      const plan = objectPlan(a, k, mz.tileSize);
      const file = named("characters", mf.pack, a.name, "!$");
      if (w.put(`img/characters/${file}.png`, composeCharacter(ld, plan))) r.objects[a.name] = { file, index: 0, cell: [plan.cell.w, plan.cell.h] };
    }

    function enemyOut(mf, a, ld) {
      const f = { file: a.image, sheet: null, rect: [0, 0, ...a.size], size: a.size, pivot: a.pivot };
      const cell = cellFor([f], k, 0, 0);
      const img = blank(cell.w, cell.h);
      blit(img, scale(ld(a.image), k), ...offsetIn(cell, f, k));
      const folder = sideView ? "sv_enemies" : "enemies";
      const file = named(folder, mf.pack, a.name);
      if (w.put(`img/${folder}/${file}.png`, img)) r.enemies[a.name] = { file, folder };
      if (a.shadow) note(`${a.name}: the contact shadow is not drawn (MZ battlers have none of their own)`);
    }
  }
  // a normal (not "$") sheet: up to 8 characters per file, NAME, NAME_2 ...
  for (let i = 0; i < sheetChars.length; i += 8) {
    const group = sheetChars.slice(i, i + 8);
    const file = i ? `${opts.sheet}_${i / 8 + 1}` : opts.sheet;
    try {
      const { sheet, cell } = composeCharacterSheet(group.map((g) => g.load), group.map((g) => g.plan));
      if (w.put(`img/characters/${file}.png`, sheet)) {
        group.forEach((g, j) => { report[g.m.pack].characters[g.plan.name] = { file, index: j, from: g.plan.action, frames: g.plan.picks, cell: [cell.w, cell.h] }; });
      }
    } catch (err) {
      if (!(err instanceof ConvertError || err instanceof PngError)) throw err;
      failures.push(`sheet ${file}: ${err.message}`);
    }
  }
  // IconSet.png: MZ's (or your) icons first, then ours; the base is remembered so a re-run replaces only ours
  let baseRows = old?.iconset_base_rows ?? null;
  if (iconImgs.length) {
    const rel = "img/system/IconSet.png";
    const cur = w.current(rel);
    if (!(baseRows !== null && w.ours(rel))) baseRows = cur ? Math.ceil(cur.height / MZ.icon) : 1;   // 1: row 0 stays empty
    if (cur && cur.width !== MZ.icon * MZ.iconCols) log("WARN", `${rel} is ${cur.width} px wide; MZ reads ${MZ.iconCols} columns of ${MZ.icon} px`);
    if (w.put(rel, composeIconSet(cur, baseRows, iconImgs))) {
      iconNames.forEach(([r, name], i) => { r.icons[name] = baseRows * MZ.iconCols + i; });
    }
  }
  for (const rel of Object.keys(old?.files || {})) {
    if (!(rel in w.files)) log("info", `${rel}: an earlier export wrote it, this one did not (left in place; delete it if unused)`);
  }
  const record = {
    format: RECORD_FORMAT, version: RECORD_VERSION, tile_size: mz.tileSize, scale: k, side_view: sideView,
    iconset_base_rows: baseRows, files: Object.fromEntries(Object.entries({ ...w.files }).sort()), packs: report,
  };
  if (!opts.dryRun) {
    const text = pretty(record) + "\n";
    if (!existsSync(paths.record) || readFileSync(paths.record, "utf8") !== text) {
      mkdirSync(dirname(paths.record), { recursive: true });
      writeFileSync(paths.record, text);
    }
  }
  return { record, failures, notes, written: w.wrote, unchanged: w.same, held: w.held };
}

// ---- --check ------------------------------------------------------------------------------------------------
/** MZ's shape rule for an image by its folder and name, or null when it fits. */
export function shapeProblem(rel, w, h) {
  const name = rel.split("/").pop();
  if (rel.startsWith("img/characters/")) {
    const big = /^[!$]*\$/.test(name);
    const [c, r] = big ? [3, 4] : [12, 8];
    return w % c || h % r ? `${w}x${h} does not split into ${c} x ${r} frames` : null;
  }
  if (rel.startsWith("img/faces/")) return w % MZ.face || h % MZ.face ? `${w}x${h} is not made of ${MZ.face} px faces` : null;
  if (rel.startsWith("img/sv_actors/")) return w % MZ.svCols || h % MZ.svRows ? `${w}x${h} does not split into ${MZ.svCols} x ${MZ.svRows} frames` : null;
  if (rel === "img/system/Window.png") return w !== MZ.skin || h !== MZ.skin ? `${w}x${h}, MZ's window skin is ${MZ.skin} x ${MZ.skin}` : null;
  if (rel === "img/system/IconSet.png") return w !== MZ.icon * MZ.iconCols || h % MZ.icon ? `${w}x${h}, MZ reads ${MZ.iconCols} columns of ${MZ.icon} px icons` : null;
  if (rel.startsWith("img/tilesets/")) return w % MZ.tilesetCols || h % MZ.tilesetRows || w !== h ? `${w}x${h} is not ${MZ.tilesetCols} x ${MZ.tilesetRows} square tiles` : null;
  return null;
}

/** The export record against the game folder: [problems, warnings]. */
export function checkExport(paths, manifests) {
  const problems = [], warnings = [];
  if (!existsSync(paths.record)) return [problems, ["no export record yet (python tools/dev.py dotwork writes one)"]];
  const rec = readJson(paths.record, "export record");
  if (rec.format !== RECORD_FORMAT) return [[`${paths.record}: not a Dotwork MZ export record`], warnings];
  const made = statSync(paths.record).mtimeMs;
  for (const [rel, hash] of Object.entries(rec.files || {})) {
    const file = join(paths.game, ...rel.split("/"));
    if (!existsSync(file)) { problems.push(`${rel} is missing (python tools/dev.py dotwork writes it again)`); continue; }
    const bytes = readFileSync(file);
    if (sha256(bytes) !== hash) warnings.push(`${rel} changed since the export (kept; dotwork leaves it alone without --replace)`);
    try {
      const img = decodePng(bytes, rel);
      const bad = shapeProblem(rel, img.width, img.height);
      if (bad) problems.push(`${rel}: ${bad}`);
    } catch (err) {
      problems.push(err.message);
    }
  }
  for (const m of manifests) if (statSync(m.file).mtimeMs > made) warnings.push(`${posix(relative(paths.root, m.file))} is newer than the export: python tools/dev.py dotwork`);
  return [problems, warnings];
}

// ---- command line ---------------------------------------------------------------------------------------------
const HELP = `Convert Dotwork's art (asset manifests) into RPG Maker MZ's image layouts in the game folder.

Usage: node tools/dotwork_mz.mjs [options]        (python tools/dev.py dotwork [options] runs this)

  --manifest FILE   a manifest to convert (repeatable); default: every *.assets.json in Dotwork's
                    <assets_dir>/dotwork/ (art_src/dotwork/dotwork.config.json, default assets/) and game/img/dotwork/
  --game DIR        the MZ project folder (default: game/, or the root for a project kept there)
  --scale N         whole-number scale from Dotwork pixels to MZ pixels (default: MZ's tile size / the art's tile
                    size, from data/System.json tileSize, 48 when absent)
  --sheet NAME      put the characters on normal sheets NAME, NAME_2 ... (8 per file) instead of one "$" file each
  --only KINDS      comma list of ${KINDS.join(", ")} (default: all)
  --stand walk|idle the standing frame (MZ's middle column): walk's first frame (default) or idle's
  --side-view       make side-view battlers even when System.json says front view
  --replace         overwrite files Dotwork did not write (MZ's Window.png and IconSet.png the first time); the
                    originals go to build/dotwork_mz/originals/
  --dry-run         say what would be written, write nothing
  --check           check the last export: files present, unchanged, in MZ's shapes; manifests not newer
  --debug           a stack trace on unexpected errors
  -h, --help        this help

Writes img/characters ($<name>.png, !$<prop>.png), img/faces, img/sv_actors (side-view games), img/enemies or
img/sv_enemies, img/system/Window.png and IconSet.png, img/tilesets (<pack>_<tileset>_B.png ...), and the record
<src_dir>/dotwork/mz_export.json: the icon, face and tile ids to use in MZ's database.
Exit: 0 ok, 1 an asset failed or --check found a problem, 2 usage or nothing to convert.`;

export function parseArgs(argv) {
  const o = { manifests: [], only: [], replace: false, dryRun: false, check: false, sideView: false, stand: "walk", scale: 0, sheet: "", game: "", debug: !!process.env[DEBUG_ENV] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], next = () => {
      if (i + 1 >= argv.length) throw new ConvertError(`${a} needs a value`);
      return argv[++i];
    };
    if (a === "-h" || a === "--help") o.help = true;
    else if (a === "--manifest") o.manifests.push(next());
    else if (a === "--game") o.game = next();
    else if (a === "--scale") {
      o.scale = Number(next());
      if (!Number.isInteger(o.scale) || o.scale < 1 || o.scale > 16) throw new ConvertError("--scale takes a whole number from 1 to 16");
    } else if (a === "--sheet") {
      o.sheet = next();
      if (!/^[A-Za-z0-9_-]+$/.test(o.sheet)) throw new ConvertError("--sheet takes a plain file name (letters, digits, _ and -)");
    } else if (a === "--only") {
      o.only = next().split(",").map((s) => s.trim()).filter(Boolean);
      const bad = o.only.filter((s) => !KINDS.includes(s));
      if (bad.length) throw new ConvertError(`--only: unknown ${bad.join(", ")} (one of ${KINDS.join(", ")})`);
    } else if (a === "--stand") {
      o.stand = next();
      if (!["walk", "idle"].includes(o.stand)) throw new ConvertError("--stand takes walk or idle");
    } else if (a === "--side-view") o.sideView = true;
    else if (a === "--replace") o.replace = true;
    else if (a === "--dry-run") o.dryRun = true;
    else if (a === "--check") o.check = true;
    else if (a === "--debug") o.debug = true;
    else throw new ConvertError(`unknown option ${a} (-h lists them)`);
  }
  return o;
}

const TAGS = { OK: "[ OK ]", skip: "[skip]", info: "[info]", WARN: "[WARN]", dry: "[dry ]" };

export function main(argv, root = resolve(dirname(fileURLToPath(import.meta.url)), "..")) {
  let o;
  try {
    o = parseArgs(argv);
  } catch (err) {
    console.error(`[error] ${err.message}`);
    return 2;
  }
  if (o.help) { console.log(HELP); return 0; }
  try {
    const paths = projectPaths(root, o.game ? resolve(root, o.game) : null);
    const files = o.manifests.length ? o.manifests.map((f) => resolve(root, f)) : findManifests(paths.manifestDirs);
    if (!files.length) {
      console.error(`[error] no Dotwork asset manifests in ${paths.manifestDirs.map((d) => posix(relative(root, d))).join(" or ")}: ` +
        "make art with tools/art/dotwork/dotwork.py (pack, character), then `dotwork.py manifest`");
      return 2;
    }
    const manifests = files.map((f) => loadManifest(f));
    if (o.check) {
      const [problems, warnings] = checkExport(paths, manifests);
      warnings.forEach((x) => console.log(`[WARN] ${x}`));
      problems.forEach((x) => console.log(`[FAIL] ${x}`));
      if (!problems.length) console.log("[ OK ] the Dotwork export matches MZ's layouts");
      return problems.length ? 1 : 0;
    }
    const res = exportAll(paths, manifests, o, (tag, text) => console.log(`${TAGS[tag] || `[${tag}]`} ${text}`));
    for (const n of res.notes) console.log(`[note] ${n}`);
    for (const f of res.failures) console.log(`[FAIL] ${f}`);
    const what = o.dryRun ? "would write" : "wrote";
    console.log(`${res.failures.length ? "[FAIL]" : "[ OK ]"} ${what} ${res.written} image(s), ${res.unchanged} unchanged, ` +
      `${res.held} not ours (kept), ${res.notes.length} note(s)` + (o.dryRun ? "" : `; record: ${posix(relative(root, paths.record))}`));
    return res.failures.length ? 1 : 0;
  } catch (err) {
    if (err instanceof ConvertError || err instanceof PngError) {
      console.error(`[error] ${err.message}`);
      return 2;
    }
    console.error(`[error] unexpected failure: ${err.message}. Re-run with --debug.`);
    if (o.debug) console.error(err.stack);
    return 2;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}
