// ---------------------------------------------------------------------------
// dotworkPlan.ts
// Purpose : The engine-free half of the Dotwork asset importer (#55): reads an asset manifest
//           (<assets_dir>/dotwork/<pack>.assets.json, spec in tools/art/dotwork/ASSET_MANIFEST.md) and turns it into
//           a plan: every PNG to load, named frames with their origins, animations with per-frame milliseconds,
//           sprites, icons, portraits, tilesets with Phaser tile indexes, maps with terrain layers already resolved,
//           bitmap font data and UI kit parts. src/game/dotwork.ts hands the plan to Phaser.
// Usage   : const plan = planManifest(doc, "assets/dotwork/town.assets.json")   // throws on another major version
//           plan.warnings (skipped kinds, unresolved cells), plan.errors (broken assets: verify fails on them)
//           loadedResult(plan) is the plan in the shape of data/golden/dotwork/expected.json (the importer test).
// Notes   : No Phaser import, so Vitest checks it against the golden fixture in Node. It lives in src/game/, not
//           src/core/, because src/core/ is shared file for file with the web-3d overlay (which has its own planner).
//           Pseudocode:
//             check format and major version -> refuse another major
//             for each asset: known core kind -> plan it; extra kind -> plan what the loaded result needs and warn
//               once that this importer does not draw it; unknown kind -> warn and skip; unknown fields are ignored
//             paths: join(dirname(manifest), base, path), nearest filtering is the Phaser side's job
//             animated_sprite: one frame per manifest frame (named <pack>/<asset>/<clip>/<i>, in the sheet or in the
//               frame's own PNG), origin = pivot / frame size, each frame keeps its own duration in ms
//             tileset: atlases get consecutive Phaser tile indexes (firstgid), each tile keeps collision and anim
//             map: a tiles layer places its cells as they are; a terrain layer gets each cell's mask from the blob
//               rule (cellMask, a port of assetspec.cell_mask) and the first tile, in atlas order, with that mask
//             font: Phaser's BitmapFont data built from `chars` (Phaser parses BMFont XML; Dotwork writes the text
//               format, so the data is built here instead of parsing either file)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export const FORMAT = "dotwork-assets";
export const SPEC_MAJOR = 1; // reads every 1.x manifest, refuses 2.x
export const MANIFEST_SUFFIX = ".assets.json";
export const CORE_KINDS = ["animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font", "ui_kit"];
export const EXTRA_KINDS = ["background", "particles", "transition", "normal_map", "image"];
const TEXTURE_PREFIX = "dotwork:"; // Phaser texture key = this + the resolved URL (shared files load once)

// Masks: one bit per neighbour, N NE E SE S SW W NW (bit 0 is N), y down (ASSET_MANIFEST.md "Conventions")
const NB8: ReadonlyArray<readonly [number, number]> = [[0, -1], [1, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1]];
const SIDES_ONLY = 1 | 4 | 16 | 64;

export type Rect = [number, number, number, number];
export type Pt = [number, number];

export class DotworkError extends Error {}

// ---- autotile (the spec's blob rule, ported) --------------------------------------------------
/** A corner bit counts only when both sides next to it are set: 256 raw masks fold into the 47 blob masks. */
export function canon(m: number): number {
  for (const c of [1, 3, 5, 7]) {
    if (!(((m >> ((c + 7) % 8)) & 1) && ((m >> ((c + 1) % 8)) & 1))) m &= ~(1 << c);
  }
  return m;
}

export const cellKey = (x: number, y: number): string => `${x},${y}`;

/** The mask a painted cell needs, from the set of painted cells of the same terrain (keys from cellKey). */
export function cellMask(painted: ReadonlySet<string>, x: number, y: number, mode = "blob47"): number {
  let m = 0;
  NB8.forEach(([dx, dy], b) => {
    if (painted.has(cellKey(x + dx, y + dy))) m |= 1 << b;
  });
  return mode === "sides4" ? m & SIDES_ONLY : canon(m);
}

// ---- tile flags (map cells: 1 flip h, 2 flip v, 4 transpose; transpose first, then flip) ----------------
/** Phaser's tile model: flips in the tile's own space, then `rotation` quarter turns clockwise (y down). */
export interface TileTransform {
  quarterTurns: 0 | 1 | 3;
  flipX: boolean;
  flipY: boolean;
}

export function tileTransform(flags: number): TileTransform {
  const h = (flags & 1) !== 0;
  const v = (flags & 2) !== 0;
  if (!(flags & 4)) return { quarterTurns: 0, flipX: h, flipY: v };
  // transpose = flip x, then a quarter turn counter-clockwise; a world flip after it folds into the turn
  if (h && v) return { quarterTurns: 1, flipX: true, flipY: false };
  if (h) return { quarterTurns: 1, flipX: false, flipY: false };
  if (v) return { quarterTurns: 3, flipX: false, flipY: false };
  return { quarterTurns: 3, flipX: true, flipY: false };
}

// ---- paths ------------------------------------------------------------------------------------------
function normalize(path: string): string {
  const out: string[] = [];
  const parts = path.replace(/\\/g, "/").split("/");
  parts.forEach((p, i) => {
    if (p === "." || (p === "" && i > 0)) return;
    if (p === ".." && out.length && out[out.length - 1] !== ".." && out[out.length - 1] !== "") out.pop();
    else out.push(p);
  });
  return out.join("/");
}

/** join(dirname(manifest), base, path): what every path in a manifest is relative to. */
export function resolvePath(manifestUrl: string, base: string, path: string): string {
  const dir = manifestUrl.replace(/\\/g, "/").replace(/\/[^/]*$/, "");
  return normalize(`${dir}/${base}/${path}`);
}

function safePath(p: unknown): p is string {
  return typeof p === "string" && p.length > 0 && !p.startsWith("/") && !/^[A-Za-z]:/.test(p) && !p.split("/").includes("..");
}

// ---- the plan ------------------------------------------------------------------------------------------
export interface PlanTexture {
  key: string; // Phaser texture key
  url: string; // resolved URL (or file path in Node)
  path: string; // as the manifest names it
  repeat?: string; // background layers only: "x", "y", "xy" or "none"
}

export interface PlanFrame {
  texture: string;
  name: string;
  rect: Rect;
  origin: Pt; // pivot / size (y down, no flip)
}

export interface PlanClipFrame {
  texture: string;
  frame: string;
  rect: Rect;
  ms: number; // this frame's own duration
}

export interface PlanClip {
  key: string; // Phaser animation key: <pack>/<asset>/<clip>
  name: string;
  fps: number;
  loop: boolean;
  size: Pt;
  pivot: Pt;
  origin: Pt;
  sheet: string | null; // manifest path of the strip, or null when every frame is its own PNG
  frames: PlanClipFrame[];
}

export interface PlanAnimatedSprite {
  name: string;
  role: string;
  blend: string;
  clips: PlanClip[];
  directions: Record<string, Record<string, string>>;
}

export interface PlanSprite {
  name: string;
  role: string;
  texture: string;
  size: Pt;
  pivot: Pt;
  origin: Pt;
  collision: Rect[]; // in the image's pixels
  shadow: { texture: string; offset: Pt } | null;
}

export interface PlanIcon {
  name: string;
  sizes: { size: number; texture: string }[];
}

export interface PlanPortrait {
  name: string;
  size: Pt;
  expressions: { name: string; texture: string }[];
  animation: string | null; // an animated_sprite name in the same pack
}

export interface PlanAtlas {
  id: number;
  name: string;
  role: string;
  texture: string;
  tileSize: Pt;
  columns: number;
  rows: number;
  firstgid: number; // Phaser tile index of cell (0, 0); index = firstgid + row * columns + col
}

export interface PlanTile {
  atlas: number;
  col: number;
  row: number;
  gid: number;
  terrainSet: number | null;
  terrain: number | null;
  mask: number | null;
  corners: Record<string, number> | null;
  probability: number;
  surface: string | null;
  collision: Rect[];
  oneWay: boolean;
  anim: { frames: number; fps: number } | null;
}

export interface PlanTileset {
  name: string;
  tileSize: Pt;
  shape: string; // square | isometric
  terrainSets: { id: number; mode: string; terrains: { id: number; name: string; color: string }[] }[];
  atlases: PlanAtlas[];
  tiles: PlanTile[];
  stamps: { name: string; size: Pt; solid: boolean; tiles: [number, number, number][] }[];
}

export interface PlanCell {
  x: number;
  y: number;
  gid: number;
  tile: [number, number, number]; // [atlas, col, row]
  flags: number;
  mask: number | null; // terrain cells only
}

export interface PlanLayer {
  name: string;
  kind: string; // tiles | terrain
  count: number; // cells in the manifest
  opacity: number;
  terrain: { set: number; id: number; mode: string } | null;
  cells: PlanCell[]; // what gets placed
  unresolved: { x: number; y: number; mask: number }[]; // terrain cells no tile fits
}

export interface PlanMap {
  name: string;
  tileset: string;
  size: Pt;
  tileSize: Pt;
  layers: PlanLayer[];
  objects: { asset: string; x: number; y: number }[];
}

/** One glyph as Phaser's BitmapText reads it (the shape ParseXMLBitmapFont builds). */
export interface BitmapGlyph {
  x: number;
  y: number;
  width: number;
  height: number;
  centerX: number;
  centerY: number;
  xOffset: number;
  yOffset: number;
  xAdvance: number;
  data: Record<string, never>;
  kerning: Record<number, number>;
  u0: number;
  v0: number;
  u1: number;
  v1: number;
}

export interface BitmapFontData {
  font: string;
  size: number;
  lineHeight: number;
  chars: Record<number, BitmapGlyph>;
}

export interface PlanFont {
  name: string;
  key: string; // Phaser bitmap font key: <pack>/<font>
  file: string;
  texture: string; // page 0
  pages: string[]; // texture keys, page 0 first
  lineHeight: number;
  base: number;
  scale: number;
  tint: boolean;
  chars: number[][]; // [id, x, y, w, h, xoffset, yoffset, xadvance, page]
  kerning: number[][]; // [first, second, amount]
}

export interface PlanUiPart {
  name: string;
  role: string;
  texture: string;
  size: Pt;
  scale: number;
  state: string | null;
  control: string | null;
  margins: [number, number, number, number] | null; // left, top, right, bottom
  stretchMargin: number[] | null;
  hotspot: Pt | null;
  glyph: string | null;
}

export interface PlanUiKit {
  name: string;
  role: string;
  parts: PlanUiPart[];
}

export interface PlanBackground {
  name: string;
  role: string;
  layers: { name: string; texture: string; size: Pt; velocity: Pt; repeat: string; scale: number; wobble: number }[];
}

export interface DotworkPlan {
  url: string;
  pack: string;
  version: string;
  base: string;
  textures: Map<string, PlanTexture>;
  frames: PlanFrame[];
  files: string[]; // every resolved file the manifest names (PNGs and .fnt files): the verify checks they exist
  animatedSprites: Map<string, PlanAnimatedSprite>;
  sprites: Map<string, PlanSprite>;
  icons: Map<string, PlanIcon>;
  portraits: Map<string, PlanPortrait>;
  tilesets: Map<string, PlanTileset>;
  maps: Map<string, PlanMap>;
  fonts: Map<string, PlanFont>;
  uiKits: Map<string, PlanUiKit>;
  backgrounds: Map<string, PlanBackground>;
  others: { kind: string; name: string }[]; // extra kinds this importer does not draw (particles, transition ...)
  warnings: string[];
  errors: string[];
}

// ---- small readers (a manifest is outside data: check before trusting) -------------------------------------
type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function num(o: Obj, k: string, where: string, fallback?: number): number {
  const v = o[k];
  if (isNum(v)) return v;
  if (v === undefined && fallback !== undefined) return fallback;
  throw new DotworkError(`${where}: "${k}" must be a number`);
}

function str(o: Obj, k: string, where: string, fallback?: string): string {
  const v = o[k];
  if (typeof v === "string") return v;
  if (v === undefined && fallback !== undefined) return fallback;
  throw new DotworkError(`${where}: "${k}" must be a string`);
}

function nums(v: unknown, n: number, where: string): number[] {
  if (!Array.isArray(v) || v.length !== n || !v.every(isNum)) throw new DotworkError(`${where}: expected ${n} numbers`);
  return v as number[];
}

const pt = (v: unknown, where: string): Pt => nums(v, 2, where) as Pt;
const rect = (v: unknown, where: string): Rect => nums(v, 4, where) as Rect;

function list(o: Obj, k: string, where: string, optional = false): Obj[] {
  const v = o[k];
  if (v === undefined && optional) return [];
  if (!Array.isArray(v) || !v.every(isObj)) throw new DotworkError(`${where}: "${k}" must be a list of objects`);
  return v as Obj[];
}

function collisionRects(o: Obj, where: string): Rect[] {
  return list(o, "collision", where, true).map((c, i) => rect(c.rect, `${where} collision ${i}`));
}

// ---- the planner -------------------------------------------------------------------------------------------
class Planner {
  readonly plan: DotworkPlan;
  private warnedKinds = new Set<string>();

  constructor(doc: Obj, url: string) {
    this.plan = {
      url, pack: str(doc, "pack", url), version: str(doc, "version", url), base: str(doc, "base", url, "."),
      textures: new Map(), frames: [], files: [], animatedSprites: new Map(), sprites: new Map(), icons: new Map(),
      portraits: new Map(), tilesets: new Map(), maps: new Map(), fonts: new Map(), uiKits: new Map(),
      backgrounds: new Map(), others: [], warnings: [], errors: [],
    };
  }

  /** A file the manifest names: resolved, remembered for the existence check; returns its URL. */
  file(path: unknown, where: string): string {
    if (!safePath(path)) throw new DotworkError(`${where}: path ${JSON.stringify(path)} must be relative, without ".." or a drive`);
    const url = resolvePath(this.plan.url, this.plan.base, path);
    if (!this.plan.files.includes(url)) this.plan.files.push(url);
    return url;
  }

  /** A PNG to load as a texture; returns its Phaser key. */
  texture(path: unknown, where: string, repeat?: string): string {
    const url = this.file(path, where);
    const key = TEXTURE_PREFIX + url;
    if (!this.plan.textures.has(key)) this.plan.textures.set(key, { key, url, path: path as string, ...(repeat ? { repeat } : {}) });
    return key;
  }

  warnKind(kind: string, why: string): void {
    if (this.warnedKinds.has(kind)) return;
    this.warnedKinds.add(kind);
    this.plan.warnings.push(`kind "${kind}" ${why}`);
  }

  asset(a: Obj, i: number): void {
    const kind = typeof a.kind === "string" ? a.kind : "?";
    const name = typeof a.name === "string" ? a.name : `#${i}`;
    const where = `${this.plan.pack}: ${kind} ${name}`;
    switch (kind) {
      case "animated_sprite": return this.animatedSprite(a, name, where);
      case "sprite": return this.sprite(a, name, where);
      case "icon":
        this.plan.icons.set(name, { name, sizes: list(a, "sizes", where).map((s, k) => ({ size: num(s, "size", where), texture: this.texture(s.image, `${where} size ${k}`) })) });
        return;
      case "portrait":
        this.plan.portraits.set(name, {
          name, size: pt(a.size, `${where} size`),
          expressions: list(a, "expressions", where).map((e) => ({ name: str(e, "name", where), texture: this.texture(e.image, `${where} ${String(e.name)}`) })),
          animation: typeof a.animation === "string" ? a.animation : null,
        });
        return;
      case "tileset": return this.tileset(a, name, where);
      case "map": return this.map(a, name, where);
      case "font": return this.font(a, name, where);
      case "ui_kit": return this.uiKit(a, name, where);
      case "background": return this.background(a, name, where);
      default:
        if (EXTRA_KINDS.includes(kind)) {
          for (const k of ["image", "texture", "target"]) if (safePath(a[k])) this.file(a[k], where);
          this.plan.others.push({ kind, name });
          this.warnKind(kind, "is an extra kind: its files are checked, this importer does not draw it yet");
        } else {
          this.warnKind(kind, "is unknown to this importer (a newer 1.x manifest?): skipped");
        }
    }
  }

  animatedSprite(a: Obj, name: string, where: string): void {
    const clips = list(a, "clips", where).map((c) => {
      const clip = str(c, "name", where);
      const cw = `${where} clip ${clip}`;
      const size = pt(c.frame_size, `${cw} frame_size`);
      const pivot = pt(c.pivot, `${cw} pivot`);
      const origin: Pt = [pivot[0] / size[0], pivot[1] / size[1]];
      const sheet = c.sheet === undefined ? null : (c.sheet as string);
      const sheetKey = sheet === null ? null : this.texture(sheet, `${cw} sheet`);
      const frames = list(c, "frames", cw).map((f, i) => {
        const fw = `${cw} frame ${i}`;
        const own = this.texture(f.file, fw); // every frame's own PNG ships, even with a sheet
        const texture = sheetKey ?? own;
        const r = rect(f.rect, `${fw} rect`);
        const frame = `${this.plan.pack}/${name}/${clip}/${i}`;
        this.plan.frames.push({ texture, name: frame, rect: r, origin });
        const sec = num(f, "duration", fw);
        if (sec <= 0) throw new DotworkError(`${fw}: duration ${sec} must be above 0`);
        return { texture, frame, rect: r, ms: sec * 1000 };
      });
      if (!frames.length) throw new DotworkError(`${cw}: no frames`);
      return {
        key: `${this.plan.pack}/${name}/${clip}`, name: clip, fps: num(c, "fps", cw), loop: c.loop === true,
        size, pivot, origin, sheet, frames,
      };
    });
    const directions = isObj(a.directions) ? (a.directions as Record<string, Record<string, string>>) : {};
    this.plan.animatedSprites.set(name, { name, role: str(a, "role", where, ""), blend: str(a, "blend", where, "normal"), clips, directions });
  }

  sprite(a: Obj, name: string, where: string): void {
    const size = pt(a.size, `${where} size`);
    const pivot = pt(a.pivot, `${where} pivot`);
    const shadow = isObj(a.shadow) ? { texture: this.texture(a.shadow.image, `${where} shadow`), offset: pt(a.shadow.offset, `${where} shadow offset`) } : null;
    this.plan.sprites.set(name, {
      name, role: str(a, "role", where, ""), texture: this.texture(a.image, where), size, pivot,
      origin: [pivot[0] / size[0], pivot[1] / size[1]], collision: collisionRects(a, where), shadow,
    });
  }

  tileset(a: Obj, name: string, where: string): void {
    const atlases: PlanAtlas[] = [];
    const tiles: PlanTile[] = [];
    let gid = 0;
    for (const at of list(a, "atlases", where)) {
      const aw = `${where} atlas ${String(at.name ?? at.id)}`;
      const atlas: PlanAtlas = {
        id: num(at, "id", aw), name: str(at, "name", aw, ""), role: str(at, "role", aw, ""), texture: this.texture(at.image, aw),
        tileSize: pt(at.tile_size, `${aw} tile_size`), columns: num(at, "columns", aw), rows: num(at, "rows", aw), firstgid: gid,
      };
      gid += atlas.columns * atlas.rows;
      atlases.push(atlas);
      for (const t of list(at, "tiles", aw)) {
        const col = num(t, "col", aw);
        const row = num(t, "row", aw);
        const tw = `${aw} tile ${col},${row}`;
        if (col < 0 || row < 0 || col >= atlas.columns || row >= atlas.rows) throw new DotworkError(`${tw}: outside the ${atlas.columns}x${atlas.rows} atlas`);
        const coll = list(t, "collision", tw, true);
        const anim = isObj(t.anim) ? { frames: num(t.anim, "frames", tw), fps: num(t.anim, "fps", tw) } : null;
        if (anim && col + anim.frames > atlas.columns) throw new DotworkError(`${tw}: ${anim.frames} animation frames run past the atlas`);
        tiles.push({
          atlas: atlas.id, col, row, gid: atlas.firstgid + row * atlas.columns + col,
          terrainSet: t.terrain === undefined ? null : num(t, "terrain_set", tw, 0),
          terrain: t.terrain === undefined ? null : num(t, "terrain", tw),
          mask: t.mask === undefined ? null : num(t, "mask", tw),
          corners: isObj(t.corners) ? (t.corners as Record<string, number>) : null,
          probability: num(t, "probability", tw, 1), surface: typeof t.surface === "string" ? t.surface : null,
          collision: coll.map((c, i) => rect(c.rect, `${tw} collision ${i}`)), oneWay: coll.some((c) => c.one_way === true), anim,
        });
      }
    }
    const terrainSets = list(a, "terrain_sets", where, true).map((s) => ({
      id: num(s, "id", where), mode: str(s, "mode", where),
      terrains: list(s, "terrains", where).map((t) => ({ id: num(t, "id", where), name: str(t, "name", where), color: str(t, "color", where, "") })),
    }));
    const stamps = list(a, "stamps", where, true).map((s) => ({
      name: str(s, "name", where), size: pt(s.size, `${where} stamp`), solid: s.solid === true,
      tiles: (Array.isArray(s.tiles) ? s.tiles : []).map((t) => nums(t, 3, `${where} stamp ${String(s.name)}`) as [number, number, number]),
    }));
    this.plan.tilesets.set(name, { name, tileSize: pt(a.tile_size, `${where} tile_size`), shape: str(a, "shape", where, "square"), terrainSets, atlases, tiles, stamps });
  }

  map(a: Obj, name: string, where: string): void {
    const tsName = str(a, "tileset", where);
    const ts = this.plan.tilesets.get(tsName); // tilesets come before maps in a manifest (sorted by kind)
    if (!ts) throw new DotworkError(`${where}: tileset "${tsName}" is not in this manifest`);
    const byTile = new Map<string, PlanTile>(ts.tiles.map((t) => [`${t.atlas},${t.col},${t.row}`, t]));
    const atlasById = new Map(ts.atlases.map((at) => [at.id, at]));
    const size = pt(a.size, `${where} size`);
    const layers = list(a, "layers", where).map((L) => this.layer(L, ts, byTile, atlasById, size, `${where} layer ${String(L.name)}`));
    const objects = list(a, "objects", where, true).map((o) => ({ asset: str(o, "asset", where), x: num(o, "x", where), y: num(o, "y", where) }));
    this.plan.maps.set(name, { name, tileset: tsName, size, tileSize: pt(a.tile_size ?? ts.tileSize, `${where} tile_size`), layers, objects });
  }

  layer(L: Obj, ts: PlanTileset, byTile: Map<string, PlanTile>, atlasById: Map<number, PlanAtlas>, size: Pt, where: string): PlanLayer {
    const kind = str(L, "kind", where);
    const raw = Array.isArray(L.cells) ? (L.cells as unknown[]) : [];
    const out: PlanLayer = { name: str(L, "name", where), kind, count: raw.length, opacity: num(L, "opacity", where, 1), terrain: null, cells: [], unresolved: [] };
    const inside = (x: number, y: number) => x >= 0 && y >= 0 && x < size[0] && y < size[1];
    if (kind === "tiles") {
      for (const c of raw) {
        if (!Array.isArray(c) || c.length < 5 || !c.every(isNum)) throw new DotworkError(`${where}: a tiles cell is [x, y, atlas, col, row(, flags)]`);
        const [x, y, at, col, row] = c as number[];
        const atlas = atlasById.get(at);
        if (!inside(x, y)) throw new DotworkError(`${where}: cell ${x},${y} is outside the map`);
        if (!atlas || !byTile.has(`${at},${col},${row}`)) throw new DotworkError(`${where}: cell ${x},${y} names tile [${at}, ${col}, ${row}], which tileset ${ts.name} does not have`);
        out.cells.push({ x, y, gid: atlas.firstgid + row * atlas.columns + col, tile: [at, col, row], flags: (c as number[])[5] ?? 0, mask: null });
      }
    } else if (kind === "terrain") {
      const set = num(L, "terrain_set", where, 0);
      const id = num(L, "terrain", where);
      const mode = ts.terrainSets.find((s) => s.id === set)?.mode;
      if (!mode || !ts.terrainSets.find((s) => s.id === set)?.terrains.some((t) => t.id === id)) throw new DotworkError(`${where}: terrain ${set}/${id} is not in tileset ${ts.name}`);
      out.terrain = { set, id, mode };
      // the first tile of this terrain with each mask, in atlas order (what the loaded result names)
      const byMask = new Map<number, PlanTile>();
      for (const t of ts.tiles) if (t.terrain === id && (t.terrainSet ?? 0) === set && t.mask !== null && !byMask.has(t.mask)) byMask.set(t.mask, t);
      const painted = new Set<string>();
      for (const c of raw) {
        if (!Array.isArray(c) || c.length < 2 || !isNum(c[0]) || !isNum(c[1])) throw new DotworkError(`${where}: a terrain cell is [x, y]`);
        if (!inside(c[0], c[1])) throw new DotworkError(`${where}: cell ${c[0]},${c[1]} is outside the map`);
        painted.add(cellKey(c[0], c[1]));
      }
      const cells = [...painted].map((k) => k.split(",").map(Number) as Pt).sort((p, q) => p[1] - q[1] || p[0] - q[0]);
      for (const [x, y] of cells) {
        const mask = cellMask(painted, x, y, mode);
        const t = byMask.get(mask);
        if (t) out.cells.push({ x, y, gid: t.gid, tile: [t.atlas, t.col, t.row], flags: 0, mask });
        else out.unresolved.push({ x, y, mask });
      }
      if (out.unresolved.length) {
        this.plan.warnings.push(`${where}: ${out.unresolved.length} cell(s) have no ${mode} tile with their mask (${mode === "corners4" ? "corner terrains are not painted from terrain layers" : "the tileset lacks it"}): left empty`);
      }
    } else {
      this.plan.warnings.push(`${where}: layer kind "${kind}" is unknown: skipped`);
    }
    return out;
  }

  font(a: Obj, name: string, where: string): void {
    const pages = (Array.isArray(a.pages) ? a.pages : []).map((p, i) => this.texture(p, `${where} page ${i}`));
    if (!pages.length) throw new DotworkError(`${where}: no pages`);
    const chars = (Array.isArray(a.chars) ? a.chars : []).map((c) => nums(c, 9, `${where} chars`));
    const kerning = (Array.isArray(a.kerning) ? a.kerning : []).map((k) => nums(k, 3, `${where} kerning`));
    const off = chars.filter((c) => c[8] !== 0).length;
    if (off) this.plan.warnings.push(`${where}: ${off} glyph(s) on page 1 or later are left out (Phaser's BitmapText draws from one texture)`);
    this.plan.fonts.set(name, {
      name, key: `${this.plan.pack}/${name}`, file: this.file(a.file, where), texture: pages[0], pages,
      lineHeight: num(a, "line_height", where), base: num(a, "base", where), scale: num(a, "scale", where, 1), tint: a.tint !== false, chars, kerning,
    });
  }

  uiKit(a: Obj, name: string, where: string): void {
    const parts = list(a, "parts", where).map((p) => {
      const pn = str(p, "name", where);
      const pw = `${where} part ${pn}`;
      return {
        name: pn, role: str(p, "role", pw, ""), texture: this.texture(p.image, pw), size: pt(p.size, `${pw} size`), scale: num(p, "scale", pw, 1),
        state: typeof p.state === "string" ? p.state : null, control: typeof p.control === "string" ? p.control : null,
        margins: p.margins === undefined || p.margins === null ? null : (nums(p.margins, 4, `${pw} margins`) as [number, number, number, number]),
        stretchMargin: Array.isArray(p.stretch_margin) ? (p.stretch_margin as number[]) : null,
        hotspot: p.hotspot === undefined || p.hotspot === null ? null : pt(p.hotspot, `${pw} hotspot`),
        glyph: typeof p.glyph === "string" ? p.glyph : null,
      };
    });
    this.plan.uiKits.set(name, { name, role: str(a, "role", where, ""), parts });
  }

  background(a: Obj, name: string, where: string): void {
    const layers = list(a, "layers", where).map((L, i) => {
      const repeat = str(L, "repeat", where, "none");
      return {
        name: str(L, "name", where, `layer${i}`), texture: this.texture(L.image, `${where} layer ${i}`, repeat), size: pt(L.size, `${where} layer ${i} size`),
        velocity: pt(L.velocity ?? [0, 0], `${where} layer ${i} velocity`), repeat, scale: num(L, "scale", where, 1), wobble: num(L, "wobble_px", where, 0),
      };
    });
    this.plan.backgrounds.set(name, { name, role: str(a, "role", where, ""), layers });
    this.warnKind("background", "is an extra kind: planned and checked, this importer does not draw it yet");
  }
}

/** Reads one manifest (already parsed JSON). Throws DotworkError on a wrong format or another major version;
 *  a broken asset becomes a line in plan.errors and the rest still loads. */
export function planManifest(doc: unknown, url: string): DotworkPlan {
  if (!isObj(doc) || doc.format !== FORMAT) throw new DotworkError(`${url}: not a Dotwork asset manifest (format must be "${FORMAT}")`);
  const version = typeof doc.version === "string" ? doc.version : "";
  const major = Number(version.split(".")[0]);
  if (!/^\d+\.\d+\.\d+$/.test(version) || major !== SPEC_MAJOR) {
    throw new DotworkError(`${url}: manifest version ${version || "(none)"} is not ${SPEC_MAJOR}.x: this importer reads spec ${SPEC_MAJOR}.x only (update the importer or re-run Dotwork)`);
  }
  if (!Array.isArray(doc.assets)) throw new DotworkError(`${url}: "assets" must be a list`);
  const p = new Planner(doc, url);
  // tilesets before maps whatever the order on disk (a map needs its tileset)
  const assets = (doc.assets as unknown[]).map((a, i) => [a, i] as const);
  const rank = (a: unknown) => (isObj(a) && a.kind === "map" ? 1 : 0);
  assets.sort((x, y) => rank(x[0]) - rank(y[0]) || x[1] - y[1]);
  for (const [a, i] of assets) {
    try {
      if (!isObj(a)) throw new DotworkError(`${url}: asset ${i} is not an object`);
      p.asset(a, i);
    } catch (err) {
      if (!(err instanceof DotworkError)) throw err;
      p.plan.errors.push(err.message);
    }
  }
  return p.plan;
}

// ---- Phaser data built from the plan (still engine-free: plain objects) -----------------------------------
/** Phaser's BitmapText data from the manifest's `chars`, the same shape ParseXMLBitmapFont makes from BMFont XML
 *  (Phaser 4: v runs bottom-up, so v0 = 1 - y / height). pageW/pageH: page 0's size in pixels. */
export function bitmapFontData(f: PlanFont, pageW: number, pageH: number): BitmapFontData {
  const chars: Record<number, BitmapGlyph> = {};
  for (const [id, x, y, w, h, xo, yo, xa, page] of f.chars) {
    if (page !== 0) continue;
    chars[id] = {
      x, y, width: w, height: h, centerX: Math.floor(w / 2), centerY: Math.floor(h / 2), xOffset: xo, yOffset: yo, xAdvance: xa,
      data: {}, kerning: {}, u0: x / pageW, v0: 1 - y / pageH, u1: (x + w) / pageW, v1: 1 - (y + h) / pageH,
    };
  }
  for (const [first, second, amount] of f.kerning) if (chars[second]) chars[second].kerning[first] = amount;
  return { font: f.name, size: f.lineHeight, lineHeight: f.lineHeight, chars };
}

/** Phaser tileset animation data (Tiled's shape, which Phaser 4's tilemap renderer plays): the frames sit in the
 *  next cells to the right, each held 1000 / fps ms. Keyed by the tile's id inside its atlas. */
export function tileAnimations(ts: PlanTileset): Map<number, Record<number, { animation: { tileid: number; duration: number; startTime: number }[]; animationDuration: number }>> {
  const out = new Map<number, Record<number, { animation: { tileid: number; duration: number; startTime: number }[]; animationDuration: number }>>();
  for (const t of ts.tiles) {
    if (!t.anim || t.anim.frames < 2 || t.anim.fps <= 0) continue;
    const at = ts.atlases.find((a) => a.id === t.atlas)!;
    const ms = 1000 / t.anim.fps;
    const local = t.row * at.columns + t.col;
    const animation = Array.from({ length: t.anim.frames }, (_, k) => ({ tileid: local + k, duration: ms, startTime: k * ms }));
    const rec = out.get(at.id) ?? {};
    rec[local] = { animation, animationDuration: ms * t.anim.frames };
    out.set(at.id, rec);
  }
  return out;
}

/** A collision rect in image pixels -> world pixels, for an object whose pivot sits at (x, y). */
export function rectToWorld(r: Rect, pivot: Pt, x: number, y: number): Rect {
  return [x - pivot[0] + r[0], y - pivot[1] + r[1], r[2], r[3]];
}

/** Which frame of a clip shows `ms` after it started (the frames' own durations; a clip that does not loop holds
 *  its last frame). The same timing Phaser's animation player gives the clip (checked in the browser verify). */
export function frameAt(clip: Pick<PlanClip, "frames" | "loop">, ms: number): number {
  const total = clip.frames.reduce((s, f) => s + f.ms, 0);
  if (ms >= total && !clip.loop) return clip.frames.length - 1;
  let t = ms % total;
  for (let i = 0; i < clip.frames.length; i++) {
    if (t < clip.frames[i].ms) return i;
    t -= clip.frames[i].ms;
  }
  return clip.frames.length - 1;
}

/** The clip for an action facing a direction ("walk", "e"), falling back to any direction the action has. */
export function directionClip(a: PlanAnimatedSprite, action: string, dir: string): PlanClip | null {
  const dirs = a.directions[action];
  const name = dirs?.[dir] ?? (dirs ? Object.values(dirs)[0] : undefined) ?? action;
  return a.clips.find((c) => c.name === name) ?? null;
}

// ---- the loaded result (data/golden/dotwork/expected.json's shape, made from the plan) ----------------------
const sortNums = (v: number[]) => [...v].sort((a, b) => a - b);
function cmpList(a: number | number[], b: number | number[]): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  const x = a as number[];
  const y = b as number[];
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

/** What the importer made of a manifest, as plain numbers: every value comes from the plan Phaser gets
 *  (frame durations in ms back to seconds, origins back to pivots, tile indexes back to [atlas, col, row]). */
export function loadedResult(plan: DotworkPlan): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const a of plan.animatedSprites.values()) {
    const clips: Record<string, unknown> = {};
    for (const c of a.clips) {
      clips[c.name] = {
        frames: c.frames.length, rects: c.frames.map((f) => f.rect), seconds: c.frames.map((f) => f.ms / 1000),
        length: c.frames.reduce((s, f) => s + f.ms, 0) / 1000, loop: c.loop, pivot: [c.origin[0] * c.size[0], c.origin[1] * c.size[1]], texture: c.sheet,
      };
    }
    out[`animated_sprite/${a.name}`] = { blend: a.blend, clips, directions: a.directions };
  }
  for (const s of plan.sprites.values()) out[`sprite/${s.name}`] = { size: s.size, pivot: [s.origin[0] * s.size[0], s.origin[1] * s.size[1]], collision: s.collision };
  for (const i of plan.icons.values()) out[`icon/${i.name}`] = { sizes: sortNums(i.sizes.map((s) => s.size)) };
  for (const p of plan.portraits.values()) out[`portrait/${p.name}`] = { size: p.size, expressions: p.expressions.map((e) => e.name).sort(), animation: p.animation };
  for (const ts of plan.tilesets.values()) {
    const masks: Record<string, (number | number[])[]> = {};
    for (const t of ts.tiles) {
      if (t.terrain === null) continue;
      const k = `${t.terrainSet ?? 0}/${t.terrain}`;
      const v: number | number[] = t.mask !== null ? t.mask : Object.keys(t.corners ?? {}).sort().map((c) => t.corners![c]);
      const have = (masks[k] ??= []);
      if (!have.some((h) => JSON.stringify(h) === JSON.stringify(v))) have.push(v);
    }
    const sorted: Record<string, unknown> = {};
    for (const k of Object.keys(masks).sort()) sorted[k] = masks[k].sort(cmpList);
    const terrains: Record<string, string> = {};
    for (const s of ts.terrainSets) for (const t of s.terrains) terrains[`${s.id}/${t.id}`] = t.name;
    out[`tileset/${ts.name}`] = {
      tile_size: ts.tileSize, shape: ts.shape, tiles: ts.tiles.length, collision_tiles: ts.tiles.filter((t) => t.collision.length).length,
      animated_tiles: ts.tiles.filter((t) => t.anim).length, terrains, masks: sorted,
    };
  }
  for (const m of plan.maps.values()) {
    const ts = plan.tilesets.get(m.tileset)!;
    const layers: Record<string, number> = {};
    const terrain: Record<string, unknown[]> = {};
    for (const L of m.layers) {
      layers[L.name] = L.count;
      if (L.kind !== "terrain") continue;
      const rows = [
        ...L.cells.map((c) => ({ x: c.x, y: c.y, mask: c.mask, tile: tileOfGid(ts, c.gid) as unknown })),
        ...L.unresolved.map((u) => ({ x: u.x, y: u.y, mask: u.mask, tile: null as unknown })),
      ].sort((p, q) => p.y - q.y || p.x - q.x);
      terrain[L.name] = rows.map((r) => [r.x, r.y, r.mask, r.tile]);
    }
    out[`map/${m.name}`] = { size: m.size, layers, terrain, objects: m.objects.map((o) => [o.asset, o.x, o.y]) };
  }
  for (const f of plan.fonts.values()) {
    // read the glyph back out of the data Phaser gets (a page-0 glyph), the manifest row otherwise
    const data = bitmapFontData(f, 1, 1);
    const row = f.chars.find((c) => c[0] === 65) ?? f.chars[0] ?? null;
    const g = row ? data.chars[row[0]] : undefined;
    const sample = row && g ? [row[0], g.x, g.y, g.width, g.height, g.xOffset, g.yOffset, g.xAdvance, row[8]] : row;
    out[`font/${f.name}`] = { line_height: data.lineHeight, base: f.base, chars: f.chars.length, pages: f.pages.length, sample };
  }
  for (const k of plan.uiKits.values()) {
    const parts: Record<string, unknown> = {};
    for (const p of k.parts) parts[p.name] = { size: p.size, margins: p.margins, hotspot: p.hotspot };
    out[`ui_kit/${k.name}`] = { parts };
  }
  for (const b of plan.backgrounds.values()) out[`background/${b.name}`] = { layers: b.layers.map((L) => [L.size[0], L.size[1], L.velocity[0], L.velocity[1], L.repeat]) };
  for (const o of plan.others) out[`${o.kind}/${o.name}`] = { kind: o.kind };
  return { format: `${FORMAT}-expected`, version: plan.version, pack: plan.pack, assets: out };
}

/** [atlas, col, row] of a Phaser tile index in a planned tileset. */
export function tileOfGid(ts: PlanTileset, gid: number): [number, number, number] | null {
  for (const at of ts.atlases) {
    const local = gid - at.firstgid;
    if (local >= 0 && local < at.columns * at.rows) return [at.id, local % at.columns, Math.floor(local / at.columns)];
  }
  return null;
}
