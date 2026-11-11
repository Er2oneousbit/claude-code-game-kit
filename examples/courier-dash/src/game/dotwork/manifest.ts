// ---------------------------------------------------------------------------
// manifest.ts
// Purpose : Reads a Dotwork asset manifest (<pack>.assets.json, spec: tools/art/dotwork/ASSET_MANIFEST.md, version 1)
//           into plain, engine-ready definitions: clips with per-frame seconds and pivots, sprites with collision,
//           tilesets with a tile per [atlas, col, row], maps whose terrain layers are already resolved into tiles,
//           fonts with a glyph map, UI kits with 9-slice margins. No three import: tests run it in Node.
// Usage   : const pack = importManifest(json, "assets/dotwork/town.assets.json", (m) => Log.warn("dotwork", m));
//           pack.animated.get("hero")!.clips.get("walk_s")!.frames[0].seconds
//           (src/game/dotwork/library.ts loads the files and builds Three.js objects from these definitions)
// Notes   : Every path resolves as join(dirname(manifest), base, path) (URLs or file paths, forward slashes). Another
//           major version is refused with a message naming both; unknown fields are ignored; unknown kinds and the
//           extra kinds this importer does not build yet (particles, transition, normal_map, image) are skipped
//           with one warning per kind. `background` is read (layers) but not drawn. A terrain layer resolves with
//           the spec's blob rule (cellMask below, a port of assetspec.cell_mask): each painted cell takes the first
//           tile in atlas order of the layer's terrain whose mask is the cell's. corners4 terrain layers name no
//           tile (spec 1.0 gives the rule for masks only), like the reference loader: place those as tiles layers.
//           Timing is each frame's own `duration` (seconds; holds included), never fps alone.
//
// Pseudocode:
//   check format + major version -> base folder = dirname(manifest) + base
//   per asset in the spec's import order (sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map):
//     read the fields it needs (missing required field -> DotworkError naming manifest and asset)
//     map: tiles layers as placed cells; terrain layers -> cellMask per painted cell -> first tile with that mask
//   other kinds -> background read, the rest skipped with one warning each
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Constants -----------------------------------------------------------------
export const FORMAT = "dotwork-assets";
export const SPEC_MAJOR = 1; // the manifest major version this importer reads
export const CORE_KINDS = ["animated_sprite", "sprite", "icon", "portrait", "tileset", "map", "font", "ui_kit"] as const;
/** Extra kinds the importer skips (with one warning each) until a game needs them. */
export const SKIPPED_KINDS = ["particles", "transition", "normal_map", "image"] as const;
/** The spec's import order: a portrait needs its animation, a map its tileset. */
const IMPORT_ORDER = ["sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset", "map", "background"];

// 8-neighbour masks, bit order N, NE, E, SE, S, SW, W, NW (bit 0 = N = 1), y down (assetspec.NB8)
export const NB8: ReadonlyArray<readonly [number, number]> = [
  [0, -1], [1, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1],
];
const SIDES_ONLY = 1 | 4 | 16 | 64; // N, E, S, W
export const FLIP_H = 1;
export const FLIP_V = 2;
export const TRANSPOSE = 4;

// ---- Types ---------------------------------------------------------------------
export type Rect = [number, number, number, number]; // x, y, w, h (image pixels, y down)
export type Point = [number, number];

export class DotworkError extends Error {}

export interface FrameDef {
  /** The frame's own PNG (always shipped). */
  file: string;
  /** The image `rect` is in: the clip's sheet when it has one, else the frame's own file. */
  texture: string;
  rect: Rect;
  seconds: number;
}

export interface ClipDef {
  name: string;
  fps: number;
  loop: boolean;
  frameSize: Point;
  pivot: Point;
  /** The sheet's manifest path (as written, for comparing with expected.json), or null when frames are files. */
  sheet: string | null;
  frames: FrameDef[];
  /** Seconds: the sum of the frames' durations. */
  length: number;
}

export interface AnimatedSpriteDef {
  name: string;
  role: string;
  blend: "normal" | "add";
  clips: Map<string, ClipDef>; // in the manifest's (Godot's SpriteFrames) order
  directions: Record<string, Record<string, string>>; // action -> dir -> clip
}

export interface CollisionDef {
  rect: Rect;
  oneWay: boolean;
}

export interface SpriteDef {
  name: string;
  role: string;
  image: string;
  size: Point;
  pivot: Point;
  contentRect: Rect | null;
  collision: CollisionDef[];
  shadow: { image: string; offset: Point } | null;
}

export interface IconDef {
  name: string;
  sizes: { size: number; image: string }[]; // smallest first
}

export interface PortraitDef {
  name: string;
  size: Point;
  expressions: { name: string; image: string }[]; // neutral first
  animation: string | null;
}

export type TerrainMode = "blob47" | "corners4" | "sides4";

export interface TileDef {
  atlas: number;
  col: number;
  row: number;
  terrainSet: number | null;
  terrain: number | null;
  mask: number | null;
  corners: Record<string, number> | null;
  probability: number;
  surface: string | null;
  collision: CollisionDef[];
  anim: { frames: number; fps: number } | null;
  /** Point of the tile image drawn on the cell's centre, when not the image's own centre. */
  origin: Point | null;
}

export interface AtlasDef {
  id: number;
  name: string;
  role: string;
  image: string;
  tileSize: Point;
  columns: number;
  rows: number;
  tiles: TileDef[];
}

export interface TilesetDef {
  name: string;
  tileSize: Point;
  shape: "square" | "isometric";
  terrainSets: { id: number; mode: TerrainMode; terrains: { id: number; name: string; color: string }[] }[];
  atlases: AtlasDef[];
  stamps: { name: string; size: Point; solid: boolean; tiles: [number, number, number][] }[];
  customData: string | null;
  /** "atlas,col,row" -> tile */
  tiles: Map<string, TileDef>;
}

export interface MapCell {
  x: number;
  y: number;
  atlas: number;
  col: number;
  row: number;
  flags: number; // FLIP_H | FLIP_V | TRANSPOSE
}

export interface TerrainCell {
  x: number;
  y: number;
  mask: number;
  tile: [number, number, number] | null; // [atlas, col, row]
}

export interface MapLayerDef {
  name: string;
  kind: "tiles" | "terrain";
  opacity: number;
  /** The cells as given (tiles: [x, y, atlas, col, row, flags?]; terrain: [x, y]). */
  given: number;
  /** What to draw: placed tiles, and for a terrain layer its resolved cells that have a tile. */
  cells: MapCell[];
  /** Terrain layers: every painted cell with its mask and tile (null: no tile has that mask). */
  terrain: TerrainCell[] | null;
}

export interface MapDef {
  name: string;
  tileset: string;
  size: Point;
  tileSize: Point;
  layers: MapLayerDef[];
  objects: { asset: string; x: number; y: number }[];
}

/** One BMFont char: [id, x, y, w, h, xoffset, yoffset, xadvance, page] as the spec lists it. */
export interface GlyphDef {
  id: number;
  x: number;
  y: number;
  w: number;
  h: number;
  xoffset: number;
  yoffset: number;
  xadvance: number;
  page: number;
}

export interface FontDef {
  name: string;
  file: string;
  pages: string[];
  lineHeight: number;
  base: number;
  scale: number;
  tint: boolean;
  glyphs: Map<number, GlyphDef>;
  kerning: Map<string, number>; // "first,second" -> amount
}

export interface UiPartDef {
  name: string;
  role: string;
  image: string;
  size: Point;
  scale: number;
  state: string | null;
  control: string | null;
  margins: [number, number, number, number] | null; // left, top, right, bottom
  stretchMargin: number[] | null;
  hotspot: Point | null;
  glyph: string | null;
}

export interface UiKitDef {
  name: string;
  role: string;
  parts: Map<string, UiPartDef>;
}

export interface BackgroundDef {
  name: string;
  role: string;
  layers: { name: string | null; image: string; size: Point; velocity: Point; repeat: string; wobblePx: number; scale: number }[];
}

export interface PackDef {
  pack: string;
  version: string;
  url: string;
  animated: Map<string, AnimatedSpriteDef>;
  sprites: Map<string, SpriteDef>;
  icons: Map<string, IconDef>;
  portraits: Map<string, PortraitDef>;
  tilesets: Map<string, TilesetDef>;
  maps: Map<string, MapDef>;
  fonts: Map<string, FontDef>;
  uiKits: Map<string, UiKitDef>;
  backgrounds: Map<string, BackgroundDef>;
  /** Assets of kinds this importer does not build: name -> kind. */
  skipped: Map<string, string>;
  /** Every image URL the imported assets draw from (what a loader fetches). */
  images: Set<string>;
  warnings: string[];
}

// ---- Paths ---------------------------------------------------------------------
/** Collapses "." and ".." segments of a URL or a forward-slash path (keeps a scheme or drive prefix). */
export function normalizePath(p: string): string {
  const m = /^([a-z][a-z0-9+.-]*:\/\/[^/]*|[A-Za-z]:|)(.*)$/i.exec(p.replace(/\\/g, "/"))!;
  const head = m[1];
  const lead = m[2].startsWith("/") ? "/" : "";
  const out: string[] = [];
  for (const seg of m[2].split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === ".." && out.length && out[out.length - 1] !== "..") out.pop();
    else out.push(seg);
  }
  return head + lead + out.join("/");
}

/** The folder a manifest's paths are relative to: join(dirname(manifest), base). */
export function baseDir(manifestUrl: string, base: string): string {
  const u = manifestUrl.replace(/\\/g, "/");
  const dir = u.includes("/") ? u.slice(0, u.lastIndexOf("/")) : ".";
  return normalizePath(`${dir}/${base || "."}`);
}

/** A manifest path checked against the spec (forward slashes, no "..", no drive, no leading slash). */
function checkedPath(path: unknown, where: string): string {
  if (typeof path !== "string" || !path) throw new DotworkError(`${where}: a path is missing`);
  if (path.includes("\\") || path.startsWith("/") || /^[A-Za-z]:/.test(path) || path.split("/").includes("..")) {
    throw new DotworkError(`${where}: path "${path}" must be relative, with forward slashes and no ".."`);
  }
  return path;
}

// ---- Autotiling (a port of assetspec.canon / cell_mask) ------------------------------
/** A corner bit only counts when both sides next to it are set: 256 raw masks fold into the 47 blob masks. */
export function canon(m: number): number {
  for (const c of [1, 3, 5, 7]) {
    if (!(((m >> ((c + 7) % 8)) & 1) && ((m >> ((c + 1) % 8)) & 1))) m &= ~(1 << c);
  }
  return m;
}

/** The mask a painted cell at (x, y) needs; painted holds "x,y" keys of the same terrain. */
export function cellMask(painted: Set<string>, x: number, y: number, mode: TerrainMode = "blob47"): number {
  let m = 0;
  NB8.forEach(([dx, dy], b) => {
    if (painted.has(`${x + dx},${y + dy}`)) m |= 1 << b;
  });
  return mode === "sides4" ? m & SIDES_ONLY : canon(m);
}

/** Each painted cell of a terrain layer, in reading order, with its mask and the first tile (atlas order) of the
 *  layer's terrain that has that mask (assetspec.resolve_terrain). */
export function resolveTerrain(ts: TilesetDef, terrainSet: number, terrain: number, cells: Point[]): TerrainCell[] {
  const set = ts.terrainSets.find((s) => s.id === terrainSet);
  if (!set) throw new DotworkError(`tileset ${ts.name}: no terrain set ${terrainSet}`);
  const byMask = new Map<number, [number, number, number]>();
  for (const at of ts.atlases) {
    for (const t of at.tiles) {
      if (t.terrain === terrain && (t.terrainSet ?? 0) === terrainSet && t.mask !== null && !byMask.has(t.mask)) {
        byMask.set(t.mask, [at.id, t.col, t.row]);
      }
    }
  }
  const painted = new Set(cells.map(([x, y]) => `${x},${y}`));
  const order = [...painted].map((k) => k.split(",").map(Number) as Point).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  return order.map(([x, y]) => {
    const mask = cellMask(painted, x, y, set.mode);
    return { x, y, mask, tile: byMask.get(mask) ?? null };
  });
}

// ---- Geometry helpers (shared by the Three.js builders and the tests) -------------------
/** A rect of an image as Three.js texture offset/repeat: [u0, v0, du, dv]; UV y is up, so v0 = 1 - (y + h) / H. */
export function uvRect(rect: Rect, imageW: number, imageH: number): [number, number, number, number] {
  const [x, y, w, h] = rect;
  return [x / imageW, 1 - (y + h) / imageH, w / imageW, h / imageH];
}

/** How far a quad centred on its image must move (pixels, y up) so that its pivot lands on the origin. */
export function pivotShift(size: Point, pivot: Point): Point {
  return [size[0] / 2 - pivot[0], pivot[1] - size[1] / 2];
}

/** The image point (s, t in 0..1, y down) a cell shows at (s, t) under the map flags: flips first, then the
 *  transpose (the image was transposed first, then flipped). The tile shader does the same per pixel. */
export function flagSample(s: number, t: number, flags: number): Point {
  if (flags & FLIP_H) s = 1 - s;
  if (flags & FLIP_V) t = 1 - t;
  return flags & TRANSPOSE ? [t, s] : [s, t];
}

/** The tile drawn at time `t` (seconds) for an animated tile: its frames sit in the next cells to the right. */
export function tileAnimCol(tile: TileDef, t: number): number {
  if (!tile.anim || tile.anim.frames <= 1 || tile.anim.fps <= 0) return tile.col;
  return tile.col + (Math.floor(t * tile.anim.fps) % tile.anim.frames);
}

/** Centre of map cell (x, y) in map pixels (y down): squares in rows, isometric diamond-down (Godot's layout). */
export function cellCentre(shape: TilesetDef["shape"], tileSize: Point, x: number, y: number): Point {
  const [w, h] = tileSize;
  if (shape === "isometric") return [((x - y) * w) / 2, ((x + y + 1) * h) / 2];
  return [x * w + w / 2, y * h + h / 2];
}

/** Where a clip's time lands: the frame index and whether a one-shot clip has finished. */
export function frameAt(clip: ClipDef, t: number): { index: number; done: boolean } {
  const n = clip.frames.length;
  if (n === 0) return { index: 0, done: true };
  if (clip.length <= 0) return { index: 0, done: !clip.loop };
  let time = t;
  if (clip.loop) time = ((t % clip.length) + clip.length) % clip.length;
  else if (t >= clip.length) return { index: n - 1, done: true };
  for (let i = 0; i < n; i++) {
    time -= clip.frames[i].seconds;
    if (time < -1e-9) return { index: i, done: false };
  }
  return { index: n - 1, done: !clip.loop };
}

/** One glyph quad of a laid-out text: where it goes (pixels from the text's top-left, y down) and its source. */
export interface GlyphQuad {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  src: Rect;
}

/** Lays a string out with a font's glyph map: xadvance plus kerning per char, line_height per "\n". Chars the font
 *  lacks fall back to "?" (or are skipped) and are counted in `missing`. */
export function layoutText(font: FontDef, text: string): { quads: GlyphQuad[]; width: number; height: number; missing: number } {
  const quads: GlyphQuad[] = [];
  let pen = 0, line = 0, width = 0, missing = 0, prev = -1;
  for (const ch of text) {
    if (ch === "\n") {
      width = Math.max(width, pen);
      pen = 0;
      line += 1;
      prev = -1;
      continue;
    }
    let id = ch.codePointAt(0)!;
    let g = font.glyphs.get(id);
    if (!g) {
      missing += 1;
      id = 63; // "?"
      g = font.glyphs.get(id);
      if (!g) continue;
    }
    if (prev >= 0) pen += font.kerning.get(`${prev},${id}`) ?? 0;
    if (g.w > 0 && g.h > 0) {
      quads.push({ page: g.page, x: pen + g.xoffset, y: line * font.lineHeight + g.yoffset, w: g.w, h: g.h, src: [g.x, g.y, g.w, g.h] });
    }
    pen += g.xadvance;
    prev = id;
  }
  width = Math.max(width, pen);
  return { quads, width, height: (line + 1) * font.lineHeight, missing };
}

// ---- Reading fields ------------------------------------------------------------------
type Obj = Record<string, any>;

function num(v: unknown, where: string): number {
  if (typeof v !== "number" || !Number.isFinite(v)) throw new DotworkError(`${where}: expected a number, got ${JSON.stringify(v)}`);
  return v;
}

function pair(v: unknown, where: string): Point {
  if (!Array.isArray(v) || v.length !== 2) throw new DotworkError(`${where}: expected [a, b], got ${JSON.stringify(v)}`);
  return [num(v[0], where), num(v[1], where)];
}

function rect(v: unknown, where: string): Rect {
  if (!Array.isArray(v) || v.length !== 4) throw new DotworkError(`${where}: expected [x, y, w, h], got ${JSON.stringify(v)}`);
  return [num(v[0], where), num(v[1], where), num(v[2], where), num(v[3], where)];
}

function list(v: unknown, where: string): any[] {
  if (v === undefined || v === null) return [];
  if (!Array.isArray(v)) throw new DotworkError(`${where}: expected a list`);
  return v;
}

function collisions(v: unknown, where: string): CollisionDef[] {
  return list(v, where).map((c: Obj, i) => ({ rect: rect(c?.rect, `${where}[${i}]`), oneWay: c?.one_way === true }));
}

// ---- The importer ------------------------------------------------------------------
/**
 * Turns a parsed manifest into definitions. manifestUrl is where the manifest was loaded from (a URL or a file path):
 * every image path in the result is resolved against it. warn() gets one line per skipped kind or unresolved cell.
 */
export function importManifest(doc: unknown, manifestUrl: string, warn: (msg: string) => void = () => {}): PackDef {
  const where = manifestUrl.split("/").pop() || manifestUrl;
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new DotworkError(`${where}: not a JSON object`);
  const d = doc as Obj;
  if (d.format !== FORMAT) throw new DotworkError(`${where}: format is ${JSON.stringify(d.format)}, expected "${FORMAT}"`);
  const version = String(d.version ?? "");
  const major = Number(version.split(".")[0]);
  if (major !== SPEC_MAJOR) {
    throw new DotworkError(`${where}: manifest version ${version} is not readable by this importer (reads ${SPEC_MAJOR}.x): update the importer or rebuild the pack`);
  }
  const root = baseDir(manifestUrl, typeof d.base === "string" ? d.base : ".");
  const pack: PackDef = {
    pack: String(d.pack ?? where), version, url: manifestUrl,
    animated: new Map(), sprites: new Map(), icons: new Map(), portraits: new Map(), tilesets: new Map(), maps: new Map(),
    fonts: new Map(), uiKits: new Map(), backgrounds: new Map(), skipped: new Map(), images: new Set(), warnings: [],
  };
  const say = (msg: string) => {
    pack.warnings.push(msg);
    warn(msg);
  };
  const url = (p: unknown, at: string) => {
    const u = normalizePath(`${root}/${checkedPath(p, at)}`);
    return u;
  };
  const image = (p: unknown, at: string) => {
    const u = url(p, at);
    pack.images.add(u);
    return u;
  };

  const assets = list(d.assets, `${where}: assets`) as Obj[];
  const rank = (k: string) => (IMPORT_ORDER.includes(k) ? IMPORT_ORDER.indexOf(k) : IMPORT_ORDER.length);
  const ordered = assets.map((a, i) => ({ a, i })).sort((p, q) => rank(String(p.a?.kind)) - rank(String(q.a?.kind)) || p.i - q.i);
  const skippedKinds = new Map<string, number>();

  for (const { a } of ordered) {
    const kind = String(a?.kind ?? "");
    const name = String(a?.name ?? "");
    const at = `${where}: ${kind}/${name}`;
    if (!name) throw new DotworkError(`${where}: an asset of kind "${kind}" has no name`);
    switch (kind) {
      case "sprite":
        pack.sprites.set(name, {
          name, role: String(a.role ?? ""), image: image(a.image, at), size: pair(a.size, `${at}.size`),
          pivot: pair(a.pivot, `${at}.pivot`), contentRect: a.content_rect ? rect(a.content_rect, `${at}.content_rect`) : null,
          collision: collisions(a.collision, `${at}.collision`),
          shadow: a.shadow ? { image: image(a.shadow.image, `${at}.shadow`), offset: pair(a.shadow.offset, `${at}.shadow.offset`) } : null,
        });
        break;
      case "animated_sprite": {
        const clips = new Map<string, ClipDef>();
        for (const c of list(a.clips, `${at}.clips`) as Obj[]) {
          const cw = `${at}.${c?.name}`;
          const sheet = c.sheet ? checkedPath(c.sheet, cw) : null;
          const sheetUrl = sheet ? image(sheet, cw) : null;
          const frames = (list(c.frames, `${cw}.frames`) as Obj[]).map((f, i) => {
            const file = url(f.file, `${cw}.frames[${i}]`);
            return { file, texture: sheetUrl ?? image(f.file, cw), rect: rect(f.rect, `${cw}.frames[${i}].rect`), seconds: num(f.duration, `${cw}.frames[${i}].duration`) };
          });
          clips.set(String(c.name), {
            name: String(c.name), fps: num(c.fps, `${cw}.fps`), loop: c.loop !== false, frameSize: pair(c.frame_size, `${cw}.frame_size`),
            pivot: pair(c.pivot, `${cw}.pivot`), sheet, frames, length: frames.reduce((s, f) => s + f.seconds, 0),
          });
        }
        if (!clips.size) throw new DotworkError(`${at}: no clips`);
        const directions: Record<string, Record<string, string>> = {};
        for (const [action, dirs] of Object.entries((a.directions ?? {}) as Obj)) {
          directions[action] = {};
          for (const [dir, clip] of Object.entries(dirs as Obj)) {
            if (!clips.has(String(clip))) throw new DotworkError(`${at}.directions: ${action}/${dir} names no clip "${clip}"`);
            directions[action][dir] = String(clip);
          }
        }
        pack.animated.set(name, { name, role: String(a.role ?? ""), blend: a.blend === "add" ? "add" : "normal", clips, directions });
        break;
      }
      case "icon":
        pack.icons.set(name, {
          name, sizes: (list(a.sizes, `${at}.sizes`) as Obj[]).map((s) => ({ size: num(s.size, `${at}.sizes`), image: image(s.image, at) }))
            .sort((p, q) => p.size - q.size),
        });
        break;
      case "portrait": {
        const animation = a.animation ? String(a.animation) : null;
        if (animation && !pack.animated.has(animation)) throw new DotworkError(`${at}: animation "${animation}" is not in this manifest`);
        pack.portraits.set(name, {
          name, size: pair(a.size, `${at}.size`), animation,
          expressions: (list(a.expressions, `${at}.expressions`) as Obj[]).map((e) => ({ name: String(e.name), image: image(e.image, at) })),
        });
        break;
      }
      case "font": {
        const glyphs = new Map<number, GlyphDef>();
        for (const c of list(a.chars, `${at}.chars`)) {
          if (!Array.isArray(c) || c.length < 9) throw new DotworkError(`${at}.chars: expected [id, x, y, w, h, xoffset, yoffset, xadvance, page]`);
          const [id, x, y, w, h, xoffset, yoffset, xadvance, page] = c.map((v: unknown) => num(v, `${at}.chars`));
          glyphs.set(id, { id, x, y, w, h, xoffset, yoffset, xadvance, page });
        }
        const kerning = new Map<string, number>();
        for (const k of list(a.kerning, `${at}.kerning`)) kerning.set(`${k[0]},${k[1]}`, num(k[2], `${at}.kerning`));
        pack.fonts.set(name, {
          name, file: url(a.file, at), pages: list(a.pages, `${at}.pages`).map((p) => image(p, at)),
          lineHeight: num(a.line_height, `${at}.line_height`), base: num(a.base, `${at}.base`), scale: typeof a.scale === "number" ? a.scale : 1,
          tint: a.tint !== false, glyphs, kerning,
        });
        break;
      }
      case "ui_kit": {
        const parts = new Map<string, UiPartDef>();
        for (const p of list(a.parts, `${at}.parts`) as Obj[]) {
          const pw = `${at}.${p?.name}`;
          parts.set(String(p.name), {
            name: String(p.name), role: String(p.role ?? ""), image: image(p.image, pw), size: pair(p.size, `${pw}.size`),
            scale: typeof p.scale === "number" ? p.scale : 1, state: p.state ?? null, control: p.control ?? null,
            margins: p.margins ? (rect(p.margins, `${pw}.margins`) as [number, number, number, number]) : null,
            stretchMargin: Array.isArray(p.stretch_margin) ? p.stretch_margin.map((v: unknown) => num(v, pw)) : null,
            hotspot: p.hotspot ? pair(p.hotspot, `${pw}.hotspot`) : null, glyph: p.glyph ?? null,
          });
        }
        pack.uiKits.set(name, { name, role: String(a.role ?? ""), parts });
        break;
      }
      case "tileset":
        pack.tilesets.set(name, readTileset(a, at, image));
        break;
      case "map":
        pack.maps.set(name, readMap(a, at, pack, say));
        break;
      case "background":
        pack.backgrounds.set(name, {
          name, role: String(a.role ?? ""),
          layers: (list(a.layers, `${at}.layers`) as Obj[]).map((L, i) => ({
            name: L.name ?? null, image: image(L.image, `${at}.layers[${i}]`), size: pair(L.size, `${at}.layers[${i}].size`),
            velocity: pair(L.velocity ?? [0, 0], `${at}.layers[${i}].velocity`), repeat: String(L.repeat ?? "none"),
            wobblePx: typeof L.wobble_px === "number" ? L.wobble_px : 0, scale: typeof L.scale === "number" ? L.scale : 1,
          })),
        });
        break;
      default:
        pack.skipped.set(`${kind}/${name}`, kind);
        skippedKinds.set(kind, (skippedKinds.get(kind) ?? 0) + 1);
    }
  }
  for (const [kind, n] of skippedKinds) {
    const why = (SKIPPED_KINDS as readonly string[]).includes(kind) ? "an extra kind this importer does not build yet" : "a kind this importer does not know (a newer minor version?)";
    say(`${where}: skipped ${n} ${kind} asset(s): ${why}`);
  }
  if (pack.backgrounds.size) say(`${where}: ${pack.backgrounds.size} background(s) read but not drawn (an extra kind: draw the layers in your game)`);
  return pack;
}

function readTileset(a: Obj, at: string, image: (p: unknown, at: string) => string): TilesetDef {
  const ts: TilesetDef = {
    name: String(a.name), tileSize: pair(a.tile_size, `${at}.tile_size`), shape: a.shape === "isometric" ? "isometric" : "square",
    terrainSets: (list(a.terrain_sets, `${at}.terrain_sets`) as Obj[]).map((s) => ({
      id: num(s.id, `${at}.terrain_sets`), mode: (["blob47", "corners4", "sides4"].includes(s.mode) ? s.mode : "blob47") as TerrainMode,
      terrains: (list(s.terrains, `${at}.terrain_sets`) as Obj[]).map((t) => ({ id: num(t.id, at), name: String(t.name), color: String(t.color ?? "") })),
    })),
    atlases: [], stamps: [], customData: a.custom_data ?? null, tiles: new Map(),
  };
  for (const A of list(a.atlases, `${at}.atlases`) as Obj[]) {
    const aw = `${at}.atlases[${A?.id}]`;
    const atlas: AtlasDef = {
      id: num(A.id, aw), name: String(A.name ?? ""), role: String(A.role ?? ""), image: image(A.image, aw),
      tileSize: pair(A.tile_size ?? a.tile_size, `${aw}.tile_size`), columns: num(A.columns, `${aw}.columns`), rows: num(A.rows, `${aw}.rows`), tiles: [],
    };
    for (const t of list(A.tiles, `${aw}.tiles`) as Obj[]) {
      const tile: TileDef = {
        atlas: atlas.id, col: num(t.col, `${aw}.tiles`), row: num(t.row, `${aw}.tiles`),
        terrainSet: "terrain" in t ? (t.terrain_set ?? 0) : null, terrain: "terrain" in t ? num(t.terrain, aw) : null,
        mask: typeof t.mask === "number" ? t.mask : null, corners: t.corners ?? null,
        probability: typeof t.probability === "number" ? t.probability : 1, surface: t.surface ?? null,
        collision: collisions(t.collision, `${aw}.tiles`), anim: t.anim ? { frames: num(t.anim.frames, aw), fps: num(t.anim.fps, aw) } : null,
        origin: t.origin ? pair(t.origin, `${aw}.tiles.origin`) : null,
      };
      atlas.tiles.push(tile);
      ts.tiles.set(`${atlas.id},${tile.col},${tile.row}`, tile);
    }
    ts.atlases.push(atlas);
  }
  ts.stamps = (list(a.stamps, `${at}.stamps`) as Obj[]).map((s) => ({
    name: String(s.name), size: pair(s.size, `${at}.stamps`), solid: s.solid === true,
    tiles: list(s.tiles, `${at}.stamps`).map((r: number[]) => [r[0], r[1], r[2]] as [number, number, number]),
  }));
  return ts;
}

function readMap(a: Obj, at: string, pack: PackDef, say: (msg: string) => void): MapDef {
  const tsName = String(a.tileset ?? "");
  const ts = pack.tilesets.get(tsName);
  if (!ts) throw new DotworkError(`${at}: tileset "${tsName}" is not in this manifest`);
  const layers: MapLayerDef[] = [];
  for (const L of list(a.layers, `${at}.layers`) as Obj[]) {
    const lw = `${at}.${L?.name}`;
    const cells = list(L.cells, `${lw}.cells`) as number[][];
    const layer: MapLayerDef = {
      name: String(L.name), kind: L.kind === "terrain" ? "terrain" : "tiles", opacity: typeof L.opacity === "number" ? L.opacity : 1,
      given: cells.length, cells: [], terrain: null,
    };
    if (layer.kind === "tiles") {
      for (const c of cells) {
        if (!ts.tiles.has(`${c[2]},${c[3]},${c[4]}`)) throw new DotworkError(`${lw}: cell [${c.slice(0, 2)}] names tile [${c.slice(2, 5)}], which ${tsName} does not have`);
        layer.cells.push({ x: c[0], y: c[1], atlas: c[2], col: c[3], row: c[4], flags: c[5] ?? 0 });
      }
    } else {
      const set = num(L.terrain_set ?? 0, lw), terrain = num(L.terrain, `${lw}.terrain`);
      const mode = ts.terrainSets.find((s) => s.id === set)?.mode;
      layer.terrain = resolveTerrain(ts, set, terrain, cells.map((c) => [c[0], c[1]] as Point));
      const none = layer.terrain.filter((c) => !c.tile).length;
      if (mode === "corners4") say(`${lw}: a corners4 terrain layer is not resolved (spec 1.0 has the rule for masks only): place it as a tiles layer`);
      else if (none) say(`${lw}: ${none} cell(s) have a mask no tile of terrain ${terrain} carries (left empty)`);
      for (const c of layer.terrain) if (c.tile) layer.cells.push({ x: c.x, y: c.y, atlas: c.tile[0], col: c.tile[1], row: c.tile[2], flags: 0 });
    }
    layers.push(layer);
  }
  const objects: MapDef["objects"] = [];
  for (const o of list(a.objects, `${at}.objects`) as Obj[]) {
    const asset = String(o.asset);
    if (!pack.sprites.has(asset) && !pack.animated.has(asset)) {
      say(`${at}.objects: "${asset}" is not a sprite or animated sprite of this manifest (not placed)`);
      continue;
    }
    objects.push({ asset, x: num(o.x, `${at}.objects`), y: num(o.y, `${at}.objects`) });
  }
  return { name: String(a.name), tileset: tsName, size: pair(a.size, `${at}.size`), tileSize: pair(a.tile_size ?? ts.tileSize, `${at}.tile_size`), layers, objects };
}
