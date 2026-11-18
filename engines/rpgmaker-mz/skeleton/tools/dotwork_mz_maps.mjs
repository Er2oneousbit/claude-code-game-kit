// ---------------------------------------------------------------------------
// dotwork_mz_maps.mjs
// Purpose : The terrain and map half of the Dotwork-to-MZ converter (tools/dotwork_mz.mjs, #286): blob47 terrain
//           tiles become MZ autotiles (A2 floor kinds; an animated terrain an A1 water kind), every Dotwork map of a
//           square tileset becomes data/MapNNN.json with a tileset entry in data/Tilesets.json and a row in
//           data/MapInfos.json, and backgrounds become battle backs (img/battlebacks1, battlebacks2) or parallaxes.
// Usage   : imported by tools/dotwork_mz.mjs (python tools/dev.py dotwork runs it); the tests import it directly.
// Notes   : MZ's tile ids and the floor autotile table are RPG Maker MV's corescript (rpg_core/Tilemap.js, MIT,
//           github.com/rpgtkoolmv/corescript, read 2026-11-17): TILE_ID_A1 2048, A2 2816, A5 1536, 48 ids per kind,
//           FLOOR_AUTOTILE_TABLE as below, A2 kind k drawn from block (k % 8 * 2, (k / 8 - 2) * 3) tiles of the A2
//           sheet, A1 water kinds animated over three blocks (frames 0, 1, 2, 1). MZ keeps MV's layout (verify in
//           MZ's rmmz_core.js).
//           An autotile is 2 x 3 tiles of quarter tiles; MZ draws every cell from four quarters picked by the
//           shape (0 to 47) its neighbours give. A quarter's look depends on the two side neighbours next to it and
//           the corner between them: outer corner, edge along either side, inner corner, inside. This file derives
//           the quarter each of the five cases reads from the table itself (QUARTER_SOURCES, checked against every
//           row by the tests), fills the block from Dotwork tiles of the matching masks, and then rebuilds every
//           one of Dotwork's 47 tiles from the block through the table: a terrain whose tiles do not come back
//           pixel for pixel (art that is not quarter-separable) is not made an autotile, its tiles go on the B to E
//           sheets and the maps place them cell by cell instead. sides4 and corners4 terrain always go that way
//           (MZ's autotiles are blob-shaped). Either way every map shows Dotwork's resolved cells.
//           Pseudocode:
//             autotilePlan: per blob47 terrain -> the tile per mask (the first candidate of the variant pick at
//               weight > 0) -> compose the block (Dotwork pixels) -> rebuild the 47 shapes -> ok or a note
//             mapPlan: resolve each layer (the spec's rules: cell mask, variant roll, stamps) -> per cell the MZ
//               tile id (an autotile: kind base + shape of the cell's mask; else the B to E id) -> stack each
//               cell's tiles into MZ's four tile layers in the manifest's layer order -> objects as events
//             database: a tileset entry, a map file, a MapInfos row per Dotwork map, at ids the record keeps
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { blank, blit, crop, scale, samePixels } from "./pngio.mjs";

// ---- Tunables / constants -------------------------------------------------------------------------------
export const TILE_ID = { B: 0, C: 256, D: 512, E: 768, A5: 1536, A1: 2048, A2: 2816, A3: 4352, A4: 5888, MAX: 8192 };
export const KIND_IDS = 48;              // ids per autotile kind (48 shapes)
export const SHEET_TILES = [16, 12];     // A1 and A2 sheets: 16 x 12 tiles (768 x 576 at 48 px)
export const MZ_LAYERS = 4;              // tile layers z 0 to 3; z 4 is shadows, z 5 regions
export const IMPASSABLE = 0x0f;          // a tileset flag: blocked from all four directions
export const STAR = 0x10;                // a tileset flag: drawn above characters (MZ sets it on B's empty tile 0)
export const DEFAULT_SCREEN = [816, 624];   // MZ's default screen (System.json advanced.screenWidth / Height)
export const MAP_FRAME_RATE = 60;        // MZ updates a map's parallax once per frame
export const DOTWORK_NOTE = "<dotwork>";   // in the note of every database entry the converter owns
// RPG Maker MV corescript, rpg_core/Tilemap.js (MIT): the quarters [qx, qy] (half tiles inside a kind's 2 x 3
// tile block) of shapes 0 to 47, each [top-left, top-right, bottom-left, bottom-right]
export const FLOOR_AUTOTILE_TABLE = [
  [[2, 4], [1, 4], [2, 3], [1, 3]], [[2, 0], [1, 4], [2, 3], [1, 3]],
  [[2, 4], [3, 0], [2, 3], [1, 3]], [[2, 0], [3, 0], [2, 3], [1, 3]],
  [[2, 4], [1, 4], [2, 3], [3, 1]], [[2, 0], [1, 4], [2, 3], [3, 1]],
  [[2, 4], [3, 0], [2, 3], [3, 1]], [[2, 0], [3, 0], [2, 3], [3, 1]],
  [[2, 4], [1, 4], [2, 1], [1, 3]], [[2, 0], [1, 4], [2, 1], [1, 3]],
  [[2, 4], [3, 0], [2, 1], [1, 3]], [[2, 0], [3, 0], [2, 1], [1, 3]],
  [[2, 4], [1, 4], [2, 1], [3, 1]], [[2, 0], [1, 4], [2, 1], [3, 1]],
  [[2, 4], [3, 0], [2, 1], [3, 1]], [[2, 0], [3, 0], [2, 1], [3, 1]],
  [[0, 4], [1, 4], [0, 3], [1, 3]], [[0, 4], [3, 0], [0, 3], [1, 3]],
  [[0, 4], [1, 4], [0, 3], [3, 1]], [[0, 4], [3, 0], [0, 3], [3, 1]],
  [[2, 2], [1, 2], [2, 3], [1, 3]], [[2, 2], [1, 2], [2, 3], [3, 1]],
  [[2, 2], [1, 2], [2, 1], [1, 3]], [[2, 2], [1, 2], [2, 1], [3, 1]],
  [[2, 4], [3, 4], [2, 3], [3, 3]], [[2, 4], [3, 4], [2, 1], [3, 3]],
  [[2, 0], [3, 4], [2, 3], [3, 3]], [[2, 0], [3, 4], [2, 1], [3, 3]],
  [[2, 4], [1, 4], [2, 5], [1, 5]], [[2, 0], [1, 4], [2, 5], [1, 5]],
  [[2, 4], [3, 0], [2, 5], [1, 5]], [[2, 0], [3, 0], [2, 5], [1, 5]],
  [[0, 4], [3, 4], [0, 3], [3, 3]], [[2, 2], [1, 2], [2, 5], [1, 5]],
  [[0, 2], [1, 2], [0, 3], [1, 3]], [[0, 2], [1, 2], [0, 3], [3, 1]],
  [[2, 2], [3, 2], [2, 3], [3, 3]], [[2, 2], [3, 2], [2, 1], [3, 3]],
  [[2, 4], [3, 4], [2, 5], [3, 5]], [[2, 0], [3, 4], [2, 5], [3, 5]],
  [[0, 4], [1, 4], [0, 5], [1, 5]], [[0, 4], [3, 0], [0, 5], [1, 5]],
  [[0, 2], [3, 2], [0, 3], [3, 3]], [[0, 2], [1, 2], [0, 5], [1, 5]],
  [[0, 4], [3, 4], [0, 5], [3, 5]], [[2, 2], [3, 2], [2, 5], [3, 5]],
  [[0, 2], [3, 2], [0, 5], [3, 5]], [[0, 0], [1, 0], [0, 1], [1, 1]],
];
// Masks (ASSET_MANIFEST.md "Conventions"): one bit per neighbour, N NE E SE S SW W NW (bit 0 is N), y down
const NB8 = [[0, -1], [1, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1]];
const N = 1, NE = 2, E = 4, SE = 8, S = 16, SW = 32, W = 64, NW = 128;
const SIDES = N | E | S | W, CORNERS = NE | SE | SW | NW;
// Each quarter of a cell (top-left, top-right, bottom-left, bottom-right): its vertical side neighbour, its
// horizontal one and the corner between them
export const QUARTERS = [[N, W, NW], [N, E, NE], [S, W, SW], [S, E, SE]];
// Where in the 2 x 3 block each quarter reads its five cases. The block's bottom 2 x 2 tiles are a painted 2 x 2
// island (outer corners and edges round it, inside in the middle), the top-right tile the four inner corners; the
// table's rows use exactly these (the tests check every row).
export const QUARTER_SOURCES = [
  { outer: [0, 2], across: [2, 2], down: [0, 4], inner: [2, 0], inside: [2, 4] },   // top-left
  { outer: [3, 2], across: [1, 2], down: [3, 4], inner: [3, 0], inside: [1, 4] },   // top-right
  { outer: [0, 5], across: [2, 5], down: [0, 3], inner: [2, 1], inside: [2, 3] },   // bottom-left
  { outer: [3, 5], across: [1, 5], down: [3, 3], inner: [3, 1], inside: [1, 3] },   // bottom-right
];
// The masks whose tiles fill the block, first come first: the lone cell, the full cell, the 2 x 2 island's four
// tiles and the four inner corners give every quarter; the rest only re-check
const BLOCK_MASKS = [0, 255, 28, 112, 7, 193, 127, 253, 223, 247];
// A2's 32 kinds: the left half (ground in MZ's editor) first, then the right half (verify the editor's use)
export const A2_ORDER = [0, 1, 2, 3, 8, 9, 10, 11, 16, 17, 18, 19, 24, 25, 26, 27, 4, 5, 6, 7, 12, 13, 14, 15, 20, 21, 22, 23, 28, 29, 30, 31];
// A1's animated water kinds (0 and 1 the sea and deep sea, then the even kinds; odd kinds from 5 are waterfalls)
export const A1_ORDER = [0, 1, 4, 6, 8, 10, 12, 14];
const A1_FRAMES = 3;                     // MZ draws A1 water frames 0, 1, 2, 1
const ROLL_DIVISOR = 4294967296;
const CORNER_BITS = { top_left: NW, top_right: NE, bottom_right: SE, bottom_left: SW };

// ---- the spec's terrain rules (ASSET_MANIFEST.md "Autotiling and maps", ported from assetspec.py) ---------
export function canon(m) {
  for (const c of [1, 3, 5, 7]) if (!(((m >> ((c + 7) % 8)) & 1) && ((m >> ((c + 1) % 8)) & 1))) m &= ~(1 << c);
  return m;
}

export function cellMask(painted, x, y, mode = "blob47") {
  let m = 0;
  NB8.forEach(([dx, dy], b) => { if (painted.has(`${x + dx},${y + dy}`)) m |= 1 << b; });
  if (mode === "sides4") return m & SIDES;
  if (mode === "corners4") return canon(m) & CORNERS;
  return canon(m);
}

/** A tile's key: its mask, or (corners4, square) the corner bits whose corner holds its own terrain. */
export function tileKey(t, mode) {
  if (mode !== "corners4") return t.mask ?? null;
  if (!t.corners) return null;
  let key = 0;
  for (const [name, bit] of Object.entries(CORNER_BITS)) if (t.corners[name] === t.terrain) key += bit;
  return key;
}

export function hash32(k) {
  k = k >>> 0;
  k = (k + 0x7ed55d16 + ((k << 12) >>> 0)) >>> 0;
  k = (k ^ 0xc761c23c ^ (k >>> 19)) >>> 0;
  k = (k + 0x165667b1 + ((k << 5) >>> 0)) >>> 0;
  k = (((k + 0xd3a2646c) >>> 0) ^ ((k << 9) >>> 0)) >>> 0;
  k = (k + 0xfd7046c5 + ((k << 3) >>> 0)) >>> 0;
  return (k ^ 0xb55a4f09 ^ (k >>> 16)) >>> 0;
}

export const cellRoll = (x, y, layer) => hash32(hash32((((x & 0xffff) << 16) | (y & 0xffff)) >>> 0) + layer) / ROLL_DIVISOR;

export function pickVariant(candidates, roll) {
  const total = candidates.reduce((s, [w]) => s + w, 0);
  if (total <= 0) return candidates[0][1];
  let u = roll * total;
  for (const [w, v] of candidates) {
    u -= w;
    if (u < 0) return v;
  }
  return candidates[candidates.length - 1][1];
}

/** The tiles of one terrain with each key, in atlas order (atlases as listed): Map key -> [[weight, [a, c, r]]]. */
export function terrainCandidates(ts, setId, terrain) {
  const mode = (ts.terrain_sets || []).find((s) => s.id === setId)?.mode ?? "blob47";
  const out = new Map();
  for (const at of ts.atlases) {
    for (const t of at.tiles) {
      if (t.terrain !== terrain || (t.terrain_set ?? 0) !== setId) continue;
      const key = tileKey(t, mode);
      if (key === null) continue;
      if (!out.has(key)) out.set(key, []);
      out.get(key).push([t.probability ?? 1, [at.id, t.col, t.row]]);
    }
  }
  return { mode, byKey: out };
}

/**
 * Every layer of a map as placed cells, as the spec resolves them: [{name, kind, cells: [{x, y, tile: [a, c, r],
 * flags, mask?, terrain?}], unresolved}] (terrain cells in y then x order, the variant picked with the cell roll;
 * stamps expanded; a terrain cell keeps its mask and its terrain key for the autotile id).
 */
export function resolveLayers(map, ts) {
  return map.layers.map((L, li) => {
    const out = { name: L.name, kind: L.kind, cells: [], unresolved: 0 };
    if (L.kind === "tiles") {
      for (const c of L.cells) out.cells.push({ x: c[0], y: c[1], tile: [c[2], c[3], c[4]], flags: c[5] || 0 });
    } else if (L.kind === "stamps") {
      for (const [x, y, s] of L.cells) {
        const st = (ts.stamps || [])[s];
        if (!st) { out.unresolved++; continue; }
        st.tiles.forEach((t, j) => out.cells.push({ x: x + (j % st.size[0]), y: y + Math.floor(j / st.size[0]), tile: [...t], flags: 0 }));
      }
    } else if (L.kind === "terrain") {
      const { mode, byKey } = terrainCandidates(ts, L.terrain_set ?? 0, L.terrain);
      const painted = new Set(L.cells.map(([x, y]) => `${x},${y}`));
      const cells = [...painted].map((k) => k.split(",").map(Number)).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
      out.rows = [];   // assetspec.resolve_terrain's rows: [x, y, key, [a, c, r] or null]
      for (const [x, y] of cells) {
        const mask = cellMask(painted, x, y, mode);
        const cands = byKey.get(mask);
        out.rows.push([x, y, mask, cands ? pickVariant(cands, cellRoll(x, y, li)) : null]);
        if (!cands) { out.unresolved++; continue; }
        out.cells.push({ x, y, tile: out.rows[out.rows.length - 1][3], flags: 0, mask, terrain: `${L.terrain_set ?? 0}/${L.terrain}`, mode });
      }
    }
    return out;
  });
}

// ---- the autotile shapes ------------------------------------------------------------------------------------
/** The 47 blob masks (every 8-bit mask folded by canon), ascending. */
export const BLOB = [...new Set(Array.from({ length: 256 }, (_, m) => canon(m)))].sort((a, b) => a - b);

/** The quarter sources [qx, qy] a cell with this blob mask needs, top-left, top-right, bottom-left, bottom-right. */
export function quarterSources(mask) {
  return QUARTERS.map(([v, h, d], i) => {
    const src = QUARTER_SOURCES[i];
    const hv = !!(mask & v), hh = !!(mask & h);
    if (!hv && !hh) return src.outer;
    if (!hv) return src.across;   // the row of the quarter's horizontal neighbour continues: a top or bottom edge
    if (!hh) return src.down;     // the column continues: a left or right edge
    return mask & d ? src.inside : src.inner;
  });
}

const ROWS = new Map(FLOOR_AUTOTILE_TABLE.map((row, s) => [JSON.stringify(row), s]));

/** MZ's autotile shape (0 to 46) for a blob mask: the table row with this mask's quarters; null if none. */
export function shapeOf(mask) {
  const s = ROWS.get(JSON.stringify(quarterSources(canon(mask))));
  return s === undefined ? null : s;
}

/** The block positions (in tiles) of an autotile kind's frames on its sheet: A2 one, A1 water three. */
export function kindBlocks(sheet, kind) {
  const tx = kind % 8, ty = Math.floor(kind / 8);
  if (sheet === "A2") return [[tx * 2, ty * 3]];
  if (kind === 0 || kind === 1) return [0, 1, 2].map((f) => [f * 2, kind * 3]);
  if (kind % 2 === 1 || kind < 4) return null;   // waterfalls (odd from 5) and the static kinds 2 and 3
  const bx = Math.floor(tx / 4) * 8, by = ty * 6 + (Math.floor(tx / 2) % 2) * 3;
  return [0, 1, 2].map((f) => [bx + f * 2, by]);
}

/** The first tile id of an autotile kind (sheet "A1" kind 0 to 15, "A2" kind 0 to 31). */
export const kindBase = (sheet, kind) => TILE_ID[sheet] + kind * KIND_IDS;

/** The tile id MZ draws a terrain cell with: its kind's base plus the shape of the cell's mask. */
export function autotileId(sheet, kind, mask) {
  const shape = shapeOf(mask);
  return shape === null ? null : kindBase(sheet, kind) + shape;
}

// ---- composing (Dotwork pixels; the caller scales the sheet to MZ's tile size) -----------------------------
function tileImage(load, ts, ref, frame = 0) {
  const at = ts.atlases.find((a) => a.id === ref[0]);
  const [tw, th] = at.tile_size;
  return crop(load(at.image), (ref[1] + frame) * tw, ref[2] * th, tw, th);
}

/** One kind's 2 x 3 tile block from the tile per mask (refs: Map mask -> [a, c, r]), at Dotwork size. */
export function composeBlock(load, ts, refs, frame, T) {
  const h = T / 2, out = blank(2 * T, 3 * T), done = new Set();
  blit(out, tileImage(load, ts, refs.get(0), frame), 0, 0);   // the palette's picture: the lone cell (shape 47)
  for (let q = 0; q < 4; q++) done.add(`${q % 2},${Math.floor(q / 2)}`);
  const order = [...BLOCK_MASKS, ...BLOB.filter((m) => !BLOCK_MASKS.includes(m))];
  for (const mask of order) {
    if (!refs.has(mask)) continue;
    const img = tileImage(load, ts, refs.get(mask), frame);
    quarterSources(mask).forEach(([qx, qy], i) => {
      if (done.has(`${qx},${qy}`)) return;
      done.add(`${qx},${qy}`);
      blit(out, crop(img, (i % 2) * h, Math.floor(i / 2) * h, h, h), qx * h, qy * h);
    });
  }
  return { block: out, filled: done.size };
}

/** A cell drawn as MZ draws shape s from a block (FLOOR_AUTOTILE_TABLE), at the block's size. */
export function drawShape(block, shape, T) {
  const h = T / 2, out = blank(T, T);
  FLOOR_AUTOTILE_TABLE[shape].forEach(([qx, qy], i) => blit(out, crop(block, qx * h, qy * h, h, h), (i % 2) * h, Math.floor(i / 2) * h));
  return out;
}

/**
 * Which terrains of a square tileset become MZ autotiles. Returns { terrains: {"set/terrain": {sheet, kind, base,
 * frames, refs, blocks, impassable, variants}}, notes }. A blob47 terrain qualifies when its tiles have an even
 * size, every one of the 47 masks has a tile, and every tile comes back pixel for pixel from the block; an
 * animated terrain (its tiles' anim) goes on A1, the rest on A2.
 */
export function autotilePlan(ts, load) {
  const notes = [], terrains = {};
  if (ts.shape !== "square") return { terrains, notes };
  let a1 = 0, a2 = 0;
  for (const set of ts.terrain_sets || []) {
    for (const ter of set.terrains) {
      const key = `${set.id}/${ter.id}`;
      const tiles = ts.atlases.flatMap((at) => at.tiles.map((t) => ({ at, t }))).filter(({ t }) => t.terrain === ter.id && (t.terrain_set ?? 0) === set.id);
      if (!tiles.length) continue;
      const label = `${ts.name} terrain ${ter.name}`;
      if (set.mode !== "blob47") { notes.push(`${label}: ${set.mode} terrain is not blob-shaped like MZ's autotiles; its tiles go on the B to E sheets and maps place them cell by cell`); continue; }
      const T = tiles[0].at.tile_size[0];
      if (tiles.some(({ at }) => at.tile_size[0] !== T || at.tile_size[1] !== T) || T % 2) { notes.push(`${label}: tiles are not square with an even size, so they do not split into quarters; placed as B to E tiles`); continue; }
      const { byKey } = terrainCandidates(ts, set.id, ter.id);
      const missing = BLOB.filter((m) => !byKey.has(m));
      if (missing.length) { notes.push(`${label}: no tile for ${missing.length} of the 47 masks; placed as B to E tiles`); continue; }
      const refs = new Map();
      let variants = 0;
      for (const [m, cands] of byKey) {
        refs.set(m, (cands.find(([w]) => w > 0) ?? cands[0])[1]);
        variants += cands.length - 1;
      }
      const frameCounts = new Set(tiles.map(({ t }) => t.anim?.frames ?? 1));
      const frames = Math.max(...frameCounts);
      const animated = frames > 1;
      if (animated && (frameCounts.size > 1 || a1 >= A1_ORDER.length)) {
        notes.push(`${label}: ${frameCounts.size > 1 ? "its tiles animate with different frame counts" : "A1 holds no more water kinds"}; placed as B to E tiles (first frame)`);
        continue;
      }
      if (!animated && a2 >= A2_ORDER.length) { notes.push(`${label}: A2 holds no more kinds; placed as B to E tiles`); continue; }
      const blocks = [];
      let bad = null;
      for (let f = 0; f < (animated ? A1_FRAMES : 1) && !bad; f++) {
        const frame = f % frames;
        const { block } = composeBlock(load, ts, refs, frame, T);
        for (const m of BLOB) {
          if (!samePixels(drawShape(block, shapeOf(m), T), tileImage(load, ts, refs.get(m), frame))) { bad = m; break; }
        }
        blocks.push(block);
      }
      if (bad !== null) { notes.push(`${label}: the tile for mask ${bad} does not split into MZ's quarter tiles (its art crosses quarter lines); placed as B to E tiles`); continue; }
      const sheet = animated ? "A1" : "A2";
      const kind = animated ? A1_ORDER[a1++] : A2_ORDER[a2++];
      if (variants) notes.push(`${label}: ${variants} variant tile(s) go on the B to E sheets (an MZ autotile has one look per shape); a map cell that picked one places it as is`);
      if (animated) notes.push(`${label}: MZ animates A1 water itself (frames 0, 1, 2, 1 at its own rate), not at ${tiles[0].t.anim.fps} fps`);
      terrains[key] = {
        name: ter.name, sheet, kind, base: kindBase(sheet, kind), frames: animated ? A1_FRAMES : 1, refs, blocks,
        impassable: tiles.some(({ t }) => t.collision?.length), variants,
      };
    }
  }
  return { terrains, notes };
}

/** "set/terrain" -> the set of "atlas,col,row" keys an autotile of the plan draws (the tile per mask). */
export function autotiledTiles(auto) {
  return new Map(Object.entries(auto.terrains).map(([key, t]) => [key, new Set([...t.refs.values()].map((r) => r.join(",")))]));
}

/** The A1 or A2 sheet image (MZ size) of a tileset's autotiles on it, or null when none. k: Dotwork to MZ scale. */
export function composeAutotileSheet(plan, sheet, k, tile) {
  const mine = Object.values(plan.terrains).filter((t) => t.sheet === sheet);
  if (!mine.length) return null;
  const out = blank(SHEET_TILES[0] * tile, SHEET_TILES[1] * tile);
  for (const t of mine) {
    kindBlocks(sheet, t.kind).forEach(([bx, by], f) => blit(out, scale(t.blocks[f % t.blocks.length], k), bx * tile, by * tile));
  }
  return out;
}

// ---- maps ---------------------------------------------------------------------------------------------------
/**
 * One Dotwork map as MZ map data. tilePlan: the B to E plan (tilesetPlan: tiles "a,c,r" -> {tile_id}); auto: the
 * autotilePlan; objects: Dotwork asset name -> MZ character file ("!$crate"). Returns { width, height, data (MZ's
 * flat layers: index (z * height + y) * width + x), events, notes, placed (cells written), dropped }.
 */
export function mapPlan(map, ts, tilePlan, auto, objects = {}) {
  const [w, h] = map.size, notes = [];
  const stacks = Array.from({ length: w * h }, () => []);
  let placed = 0, dropped = 0, flipped = 0, missing = 0;
  for (const L of resolveLayers(map, ts)) {
    if (L.unresolved) notes.push(`${map.name} layer ${L.name}: ${L.unresolved} cell(s) without a tile`);
    for (const c of L.cells) {
      if (c.x < 0 || c.y < 0 || c.x >= w || c.y >= h) { dropped++; continue; }
      let id = null;
      const at = c.terrain ? auto.terrains[c.terrain] : null;
      // the autotile when the cell's pick is the tile the autotile draws; a variant the roll picked: its B to E tile
      if (at && c.mode === "blob47" && at.refs.get(c.mask)?.join(",") === c.tile.join(",")) id = autotileId(at.sheet, at.kind, c.mask);
      else id = tilePlan.tiles[c.tile.join(",")]?.tile_id ?? null;
      if (id === null) { missing++; continue; }
      if (c.flags) flipped++;
      stacks[c.y * w + c.x].push(id);
      placed++;
    }
  }
  const data = new Array(w * h * 6).fill(0);
  let deep = 0;
  stacks.forEach((ids, i) => {
    // MZ draws z 0 to 3 in order: the manifest's order kept, the topmost four kept when a cell has more
    const keep = ids.slice(-MZ_LAYERS);
    if (ids.length > MZ_LAYERS) deep++;
    keep.forEach((id, z) => { data[z * w * h + i] = id; });
  });
  if (deep) notes.push(`${map.name}: ${deep} cell(s) stack more than MZ's ${MZ_LAYERS} tile layers; the lowest are left out`);
  if (flipped) notes.push(`${map.name}: ${flipped} flipped or turned cell(s) drawn unflipped (MZ tiles do not flip)`);
  if (missing) notes.push(`${map.name}: ${missing} cell(s) whose tile is not on the MZ sheets were left empty`);
  if (dropped) notes.push(`${map.name}: ${dropped} cell(s) outside the map left out`);
  const events = [null];
  const [tw, th] = map.tile_size;
  for (const o of map.objects || []) {
    const file = objects[o.asset];
    if (!file) { notes.push(`${map.name}: object ${o.asset} has no MZ character sheet (convert objects first); left out`); continue; }
    // the pivot is the bottom centre of a cell for props mapbuild places: the cell the feet stand in
    const x = Math.floor(o.x / tw), y = Math.floor((o.y - 1) / th);
    events.push(objectEvent(events.length, o.asset, file, x, y));
  }
  return { width: w, height: h, data, events, notes, placed };
}

/** An event that shows an object sheet, does nothing and blocks like a character (MZ's event shape, verify). */
export function objectEvent(id, name, file, x, y) {
  return {
    id, name, note: DOTWORK_NOTE, x, y,
    pages: [{
      conditions: { actorId: 1, actorValid: false, itemId: 1, itemValid: false, selfSwitchCh: "A", selfSwitchValid: false,
        switch1Id: 1, switch1Valid: false, switch2Id: 1, switch2Valid: false, variableId: 1, variableValid: false, variableValue: 0 },
      directionFix: false, image: { characterIndex: 0, characterName: file, direction: 2, pattern: 1, tileId: 0 },
      list: [{ code: 0, indent: 0, parameters: [] }], moveFrequency: 3,
      moveRoute: { list: [{ code: 0, parameters: [] }], repeat: true, skippable: false, wait: false },
      moveSpeed: 3, moveType: 0, priorityType: 1, stepAnime: false, through: false, trigger: 0, walkAnime: true,
    }],
  };
}

/** MZ's map file for a map plan (data/MapNNN.json), the fields a new map in MZ's editor has (verify). */
export function mapFile(mp, tilesetId, displayName) {
  return {
    autoplayBgm: false, autoplayBgs: false, battleback1Name: "", battleback2Name: "",
    bgm: { name: "", pan: 0, pitch: 100, volume: 90 }, bgs: { name: "", pan: 0, pitch: 100, volume: 90 },
    disableDashing: false, displayName, encounterList: [], encounterStep: 30, height: mp.height, note: DOTWORK_NOTE,
    parallaxLoopX: false, parallaxLoopY: false, parallaxName: "", parallaxShow: true, parallaxSx: 0, parallaxSy: 0,
    scrollType: 0, specifyBattleback: false, tilesetId, width: mp.width, data: mp.data, events: mp.events,
  };
}

/** A Tilesets.json entry: sheet names (A1 to E) and passage flags (collision -> blocked; B's tile 0 a star). */
export function tilesetEntry(id, name, sheets, tilePlan, auto) {
  const flags = new Array(TILE_ID.MAX).fill(0);
  flags[0] = STAR;
  for (const t of Object.values(tilePlan.tiles || {})) if (!t.passable) flags[t.tile_id] = IMPASSABLE;
  for (const t of Object.values(auto.terrains)) {
    if (t.impassable) for (let s = 0; s < KIND_IDS; s++) flags[t.base + s] = IMPASSABLE;
  }
  const order = ["A1", "A2", "A3", "A4", "A5", "B", "C", "D", "E"];
  return { id, flags, mode: 1, name, note: DOTWORK_NOTE, tilesetNames: order.map((s) => sheets[s] || "") };
}

/** MZ's data arrays as its editor writes them: null first, then one entry per line. */
export function dataText(arr) {
  return `[\n${arr.map((x) => JSON.stringify(x ?? null)).join(",\n")}\n]`;
}

/**
 * Place an owned entry in a database array: the recorded id when that slot is still ours (null, or an entry with
 * the converter's note and this name), else the first free id after the last one. Returns the id.
 */
export function claimId(arr, recorded, name, owned = (e) => e && e.note === DOTWORK_NOTE && e.name === name) {
  if (recorded && recorded < arr.length && (arr[recorded] === null || owned(arr[recorded]))) return recorded;
  if (recorded && recorded >= arr.length) return recorded;
  const free = arr.findIndex((e, i) => i > 0 && e === null);
  return free > 0 ? free : Math.max(arr.length, 1);
}

// ---- backgrounds --------------------------------------------------------------------------------------------
/** The whole-number factor that makes w x h cover the screen, at least the layer's own scale. */
export function coverScale(w, h, screen, min = 1) {
  return Math.max(min, Math.ceil(screen[0] / w), Math.ceil(screen[1] / h));
}

/** A layer drawn at factor f, repeated along its repeat axes to cover the screen (pixel art is never shrunk). */
export function coverLayer(img, layer, f, screen) {
  const s = scale(img, f);
  const rx = layer.repeat === "x" || layer.repeat === "xy", ry = layer.repeat === "y" || layer.repeat === "xy";
  const W = rx ? Math.max(s.width, screen[0]) : s.width, H = ry ? Math.max(s.height, screen[1]) : s.height;
  const out = blank(W, H);
  for (let y = 0; y < H; y += s.height) {
    for (let x = 0; x < W; x += s.width) {
      blit(out, s, x, y, true);
      if (!rx) break;
    }
    if (!ry) break;
  }
  return out;
}

/**
 * A battle background as MZ's two battle backs: the first layer is battlebacks1 (the floor), the others drawn
 * over each other (bottom-aligned, as the art lines them up) are battlebacks2. One factor for all layers: the
 * one that makes the first layer cover the screen. Returns { back1, back2 (or null), factor, notes }.
 */
export function composeBattleback(load, bg, screen) {
  const notes = [];
  const first = bg.layers[0];
  const factor = coverScale(first.size[0], first.size[1], screen, first.scale || 1);
  const back1 = coverLayer(load(first.image), first, factor, screen);
  let back2 = null;
  if (bg.layers.length > 1) {
    const imgs = bg.layers.slice(1).map((L) => coverLayer(load(L.image), L, factor, screen));
    back2 = blank(Math.max(back1.width, ...imgs.map((i) => i.width)), Math.max(back1.height, ...imgs.map((i) => i.height)));
    for (const i of imgs) blit(back2, i, 0, 0, true);
  }
  if (bg.layers.some((L) => L.velocity && (L.velocity[0] || L.velocity[1]))) notes.push(`background ${bg.name}: MZ's battle backs stand still; the layers' velocity is not kept`);
  return { back1, back2, factor, notes };
}

/**
 * A parallax per layer at the layer's scale times k (the converter's scale), with MZ's scroll numbers: a map's
 * parallax moves sx / 4 px per frame when it loops (Game_Map.updateParallax and parallaxOx: x += sx / tileWidth
 * / 2 tiles, drawn at x * tileWidth / 2), so sx = velocity * scale / (frame rate / 4) (verify the sign in MZ).
 */
export function parallaxPlan(bg, k) {
  return bg.layers.map((L, i) => {
    const f = (L.scale || 1) * k, [vx, vy] = L.velocity || [0, 0];
    const rx = L.repeat === "x" || L.repeat === "xy", ry = L.repeat === "y" || L.repeat === "xy";
    return {
      layer: L.name || String(i), image: L.image, factor: f, loop_x: rx, loop_y: ry,
      sx: rx ? Math.round((vx * f) / (MAP_FRAME_RATE / 4)) : 0, sy: ry ? Math.round((vy * f) / (MAP_FRAME_RATE / 4)) : 0,
    };
  });
}
