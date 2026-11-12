// ---------------------------------------------------------------------------
// threeBuild.ts
// Purpose : Three.js objects from Dotwork definitions (src/game/dotwork/manifest.ts): pixel-crisp quads for sprites,
//           icons and portraits, animated sprites that move the texture's offset/repeat over the sheet, tile maps
//           as one InstancedMesh per atlas and layer with per-instance UVs, text from a BMFont's glyph table, and
//           9-slice panels from a UI kit part.
// Usage   : const tex = (url: string) => library.texture(url);       // or DotworkLibrary's create* methods
//           const hero = new AnimatedSprite3D(def, tex, { ppu: 16 }); hero.playDirection("walk", "e");
//           hero.update(dt, camera);                                    // every frame: animation + billboard
// Notes   : Dotwork's diorama look (lane_diorama.py): one world unit is one map tile, tiles lie flat on the ground
//           (map x -> +X, map y -> +Z, so north is -Z), sprites stand up as billboards that turn only around y.
//           `ppu` is image pixels per world unit (a map uses its tile width). Every texture: NearestFilter, no
//           mipmaps, sRGB, clamped (pixelTexture), drawn with alphaTest for hard edges and correct depth; additive
//           clips (blend "add") skip depth writes. UV y is up: a rect is offset (x / W, 1 - (y + h) / H) and
//           repeat (w / W, h / H) (manifest.uvRect). A sprite's quad is moved so its pivot sits on the object's
//           origin (manifest.pivotShift). Materials are unlit (MeshBasicMaterial): the art's own shading shows. A
//           sprite built with `lit: true` gets a MeshLambertMaterial instead, with the pack's normal map for its
//           image (a `normal_map` asset whose target is the sprite's image) as `normalMap`: Dotwork's maps are
//           OpenGL style (green up), which is three's convention, so no channel flip. Background layers come as
//           per-layer texture clones with RepeatWrapping on the layer's `repeat` axes (backgroundLayers). Animated
//           sprites use a clone of the sheet texture per object (clones share the image and its GPU upload in
//           three r186), so two heroes animate independently.
//
// Pseudocode (tile map):
//   per layer, per atlas used: an InstancedMesh of the atlas's tile quad, laid flat
//     per cell: matrix = the cell's image top-left (manifest: centre - origin, map pixels) + half the atlas tile,
//               over the map's unit, lifted a little per layer
//               tileUv = uvRect(tile cell), tileFlags = the map flags (the vertex shader flips/transposes uv)
//   animated tiles: update(dt) moves tileUv to the frame's cell (frames sit in the cells to the right)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): cells placed from their
//           left/top (isometric centres per the spec), lit sprites with a normal map, background layer textures
// ---------------------------------------------------------------------------
import * as THREE from "three";
import {
  frameAt, layoutText, pivotShift, tileAnimCol, uvRect,
  type AnimatedSpriteDef, type BackgroundDef, type BackgroundLayerDef, type ClipDef, type FontDef, type MapDef, type PackDef,
  type Point, type PortraitDef, type SpriteDef, type TileDef, type TilesetDef, type UiPartDef,
} from "./manifest";

// ---- Tunables ----------------------------------------------------------------
export const ALPHA_TEST = 0.5; // pixels below this alpha are cut (hard pixel edges, depth stays right)
export const DEFAULT_PPU = 16; // image pixels per world unit when nothing else says (a map uses its tile width)
const LAYER_LIFT = 0.002; // world units between stacked map layers (no z-fighting)

/** Hands back the loaded texture of an image URL (DotworkLibrary.texture). */
export type TextureLookup = (url: string) => THREE.Texture;

export interface QuadOptions {
  /** Image pixels per world unit (default DEFAULT_PPU). */
  ppu?: number;
  /** Turn to the camera around y in update() (default true). */
  billboard?: boolean;
}

/** Pixel-art texture settings: nearest filtering, no mipmaps, sRGB, clamped. Applied to every texture loaded. A
 *  `data` image (a normal map, a transition rule) gets no colour space, so a shader reads its bytes unconverted. */
export function pixelTexture(tex: THREE.Texture, data = false): THREE.Texture {
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.colorSpace = data ? THREE.NoColorSpace : THREE.SRGBColorSpace;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.needsUpdate = true;
  return tex;
}

/** An image's pixel size (the loaded HTMLImageElement / ImageBitmap, or a stand-in with width and height). */
export function imageSize(tex: THREE.Texture): Point {
  const img = tex.image as { width?: number; height?: number } | null;
  if (!img?.width || !img?.height) throw new Error(`texture ${tex.name || "(unnamed)"} has no image size yet (not loaded)`);
  return [img.width, img.height];
}

function spriteMaterial(map: THREE.Texture, blend: "normal" | "add" = "normal"): THREE.MeshBasicMaterial {
  const add = blend === "add";
  return new THREE.MeshBasicMaterial({
    map, alphaTest: ALPHA_TEST, side: THREE.DoubleSide, transparent: add, depthWrite: !add,
    blending: add ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
}

/** A lit sprite material (needs lights in the scene): the same pixel settings on a MeshLambertMaterial, with the
 *  normal map when the pack has one for the image (OpenGL style, green up: three's own convention). */
export function litSpriteMaterial(map: THREE.Texture, normalMap: THREE.Texture | null): THREE.MeshLambertMaterial {
  return new THREE.MeshLambertMaterial({ map, normalMap, alphaTest: ALPHA_TEST, side: THREE.DoubleSide });
}

/** A quad of size w x h image pixels whose pivot sits on the origin (y up). */
export function pivotQuad(size: Point, pivot: Point, ppu: number): THREE.PlaneGeometry {
  const [dx, dy] = pivotShift(size, pivot);
  return new THREE.PlaneGeometry(size[0] / ppu, size[1] / ppu).translate(dx / ppu, dy / ppu, 0);
}

/** Turns obj around y so its front faces the camera (a y-only billboard; obj's parent is not rotated). */
export function faceCamera(obj: THREE.Object3D, camera: THREE.Camera): void {
  const c = camera.getWorldPosition(new THREE.Vector3());
  const o = obj.getWorldPosition(new THREE.Vector3());
  obj.rotation.y = Math.atan2(c.x - o.x, c.z - o.z);
}

/** Anything the builders make that moves: update(dt) every frame, with the camera for billboards. */
export interface DotworkObject extends THREE.Object3D {
  update(dt: number, camera?: THREE.Camera): void;
}

// ---- Still images: sprites, icons, portraits ---------------------------------------
/** One image on a pivot quad (a prop, an icon, a portrait expression, an `image` asset). */
export class DotworkImage extends THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial | THREE.MeshLambertMaterial> implements DotworkObject {
  billboard: boolean;

  constructor(texture: THREE.Texture, size: Point, pivot: Point, opts: QuadOptions = {}, blend: "normal" | "add" = "normal", lit: THREE.MeshLambertMaterial | null = null) {
    super(pivotQuad(size, pivot, opts.ppu ?? DEFAULT_PPU), lit ?? spriteMaterial(texture, blend));
    this.billboard = opts.billboard ?? true;
  }

  update(_dt: number, camera?: THREE.Camera): void {
    if (this.billboard && camera) faceCamera(this, camera);
  }
}

export interface SpriteOptions extends QuadOptions {
  /** A lit material (MeshLambertMaterial) with `normalMap` when a normal_map asset targets the sprite's image. */
  lit?: boolean;
}

/** A `sprite` asset (a prop, an enemy): the image on its pivot, collision rects and contact shadow in def. With
 *  `lit`, the pack's normal map for the image (a `normal_map` asset whose target is the sprite's image, if any)
 *  goes on the material; `normalMap` is that texture or null either way. */
export class DotworkSprite extends DotworkImage {
  readonly normalMap: THREE.Texture | null;

  constructor(readonly def: SpriteDef, tex: TextureLookup, opts: SpriteOptions = {}, pack?: PackDef) {
    const nm = pack ? [...pack.normalMaps.values()].find((n) => n.target === def.image) : undefined;
    const normalMap = nm ? tex(nm.image) : null;
    const image = tex(def.image);
    super(image, def.size, def.pivot, opts, "normal", opts.lit ? litSpriteMaterial(image, normalMap) : null);
    this.normalMap = normalMap;
    this.name = def.name;
  }
}

/** An `image` asset on its pivot (the image centre when it has none): a logo, a loose sheet. */
export function imageQuad(def: { name: string; image: string; size: Point; pivot: Point | null }, tex: TextureLookup, opts: QuadOptions = {}): DotworkImage {
  const q = new DotworkImage(tex(def.image), def.size, def.pivot ?? [def.size[0] / 2, def.size[1] / 2], { billboard: false, ...opts });
  q.name = def.name;
  return q;
}

/** A `background`'s layers with their textures: a clone per layer (the image is shared) wrapping on the layer's
 *  `repeat` axes, so a scrolling layer can move `texture.offset` instead of being redrawn. The game draws them. */
export function backgroundLayers(def: BackgroundDef, tex: TextureLookup): { layer: BackgroundLayerDef; texture: THREE.Texture }[] {
  return def.layers.map((layer) => {
    const texture = tex(layer.image).clone();
    texture.wrapS = layer.repeat === "x" || layer.repeat === "xy" ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
    texture.wrapT = layer.repeat === "y" || layer.repeat === "xy" ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
    texture.needsUpdate = true;
    return { layer, texture };
  });
}

/** An `icon` at the smallest shipped size that is at least `px` (else the largest), centred. */
export function iconQuad(def: { name: string; sizes: { size: number; image: string }[] }, tex: TextureLookup, px: number, opts: QuadOptions = {}): DotworkImage {
  if (!def.sizes.length) throw new Error(`icon ${def.name} has no sizes`);
  const pick = def.sizes.find((s) => s.size >= px) ?? def.sizes[def.sizes.length - 1];
  const q = new DotworkImage(tex(pick.image), [pick.size, pick.size], [pick.size / 2, pick.size / 2], { billboard: false, ...opts });
  q.name = `${def.name}_${pick.size}`;
  return q;
}

/** A `portrait`: one expression at a time, centred (its talking clips are the animated sprite def.animation). */
export class DotworkPortrait extends DotworkImage {
  constructor(readonly def: PortraitDef, private readonly tex: TextureLookup, expression?: string, opts: QuadOptions = {}) {
    const e = def.expressions.find((x) => x.name === expression) ?? def.expressions[0];
    if (!e) throw new Error(`portrait ${def.name} has no expressions`);
    super(tex(e.image), def.size, [def.size[0] / 2, def.size[1] / 2], { billboard: false, ...opts });
    this.name = def.name;
  }

  setExpression(name: string): void {
    const e = this.def.expressions.find((x) => x.name === name);
    if (!e) throw new Error(`portrait ${this.def.name} has no expression "${name}"`);
    this.material.map = this.tex(e.image);
  }
}

// ---- Animated sprites ----------------------------------------------------------------
export class AnimatedSprite3D extends THREE.Mesh<THREE.BufferGeometry, THREE.MeshBasicMaterial> implements DotworkObject {
  billboard: boolean;
  /** Playback rate (1 = as authored). */
  speed = 1;
  clip: ClipDef;
  /** Seconds into the clip. */
  time = 0;
  frame = 0;
  /** A one-shot clip (loop false) reached its end and holds the last frame. */
  finished = false;
  private readonly ppu: number;
  private readonly geoms = new Map<string, THREE.BufferGeometry>();
  private readonly views = new Map<string, THREE.Texture>();

  constructor(readonly def: AnimatedSpriteDef, private readonly tex: TextureLookup, opts: QuadOptions & { clip?: string } = {}) {
    const first = def.clips.get(opts.clip ?? "") ?? def.clips.values().next().value!;
    super(new THREE.BufferGeometry(), spriteMaterial(tex(first.frames[0].texture), def.blend));
    this.name = def.name;
    this.ppu = opts.ppu ?? DEFAULT_PPU;
    this.billboard = opts.billboard ?? true;
    this.clip = first;
    this.play(first.name, true);
  }

  /** Starts a clip (a running clip of the same name keeps going unless restart). */
  play(name: string, restart = false): void {
    const clip = this.def.clips.get(name);
    if (!clip) throw new Error(`${this.def.name} has no clip "${name}" (${[...this.def.clips.keys()].join(", ")})`);
    if (clip === this.clip && !restart && this.geometry.attributes.position) return;
    this.clip = clip;
    this.time = 0;
    this.finished = false;
    let g = this.geoms.get(name);
    if (!g) {
      g = pivotQuad(clip.frameSize, clip.pivot, this.ppu);
      this.geoms.set(name, g);
    }
    this.geometry = g;
    this.showFrame(0);
  }

  /** Plays <action>_<dir> through the manifest's directions table; a missing direction falls back to s, then any. */
  playDirection(action: string, dir: string, restart = false): void {
    const dirs = this.def.directions[action];
    if (!dirs) throw new Error(`${this.def.name} has no action "${action}" (${Object.keys(this.def.directions).join(", ")})`);
    this.play(dirs[dir] ?? dirs.s ?? Object.values(dirs)[0], restart);
  }

  update(dt: number, camera?: THREE.Camera): void {
    if (!this.finished) {
      this.time += dt * this.speed;
      const at = frameAt(this.clip, this.time);
      this.finished = at.done;
      if (at.index !== this.frame) this.showFrame(at.index);
    }
    if (this.billboard && camera) faceCamera(this, camera);
  }

  /** The texture offset/repeat of frame i (exposed for tests and debugging). */
  showFrame(i: number): void {
    const f = this.clip.frames[i];
    let view = this.views.get(f.texture);
    if (!view) {
      view = this.tex(f.texture).clone(); // shares the image: one upload, its own offset/repeat
      this.views.set(f.texture, view);
    }
    const [w, h] = imageSize(view);
    const [u0, v0, du, dv] = uvRect(f.rect, w, h);
    view.offset.set(u0, v0);
    view.repeat.set(du, dv);
    this.material.map = view;
    this.frame = i;
  }

  dispose(): void {
    for (const g of this.geoms.values()) g.dispose();
    for (const v of this.views.values()) v.dispose();
    this.material.dispose();
  }
}

// ---- Tile maps -----------------------------------------------------------------------
const TILE_VERTEX_HEAD = "#include <common>\nattribute vec4 tileUv;\nattribute float tileFlags;";
// tileUv = (u0, v0, du, dv) of the tile's cell; tileFlags = flip h (1), flip v (2), transpose (4): flips first, then
// the transpose, in image space (t down), as manifest.flagSample does
const TILE_VERTEX_UV = `#include <uv_vertex>
#ifdef USE_MAP
  vec2 st = vec2(uv.x, 1.0 - uv.y);
  if (mod(tileFlags, 2.0) >= 1.0) st.x = 1.0 - st.x;
  if (mod(floor(tileFlags / 2.0), 2.0) >= 1.0) st.y = 1.0 - st.y;
  if (tileFlags >= 4.0) st = st.yx;
  vMapUv = tileUv.xy + vec2(st.x, 1.0 - st.y) * tileUv.zw;
#endif`;

function tileMaterial(map: THREE.Texture, opacity: number): THREE.MeshBasicMaterial {
  const m = new THREE.MeshBasicMaterial({ map, alphaTest: ALPHA_TEST, transparent: opacity < 1, opacity, depthWrite: opacity >= 1 });
  m.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader.replace("#include <common>", TILE_VERTEX_HEAD).replace("#include <uv_vertex>", TILE_VERTEX_UV);
  };
  m.customProgramCacheKey = () => "dotwork-tiles";
  return m;
}

interface AnimatedTile {
  mesh: THREE.InstancedMesh;
  index: number;
  tile: TileDef;
  col: number;
}

/** A `map`: its layers as instanced flat tiles (top-left corner of the map at the group's origin, one unit per
 *  tile width) and its objects as billboards standing on it. */
export class DotworkTileMap extends THREE.Group implements DotworkObject {
  readonly unit: number;
  readonly objects: DotworkObject[] = [];
  private readonly animated: AnimatedTile[] = [];
  private time = 0;

  constructor(readonly def: MapDef, readonly tileset: TilesetDef, pack: PackDef, tex: TextureLookup) {
    super();
    this.name = def.name;
    this.unit = tileset.tileSize[0];
    const flat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);
    def.layers.forEach((layer, li) => {
      const byAtlas = new Map<number, typeof layer.cells>();
      for (const c of layer.cells) {
        if (!byAtlas.has(c.atlas)) byAtlas.set(c.atlas, []);
        byAtlas.get(c.atlas)!.push(c);
      }
      for (const [atlasId, cells] of byAtlas) {
        const atlas = tileset.atlases.find((a) => a.id === atlasId)!;
        const map = tex(atlas.image);
        const geom = new THREE.PlaneGeometry(atlas.tileSize[0] / this.unit, atlas.tileSize[1] / this.unit);
        const uvs = new THREE.InstancedBufferAttribute(new Float32Array(cells.length * 4), 4);
        const flags = new THREE.InstancedBufferAttribute(new Float32Array(cells.length), 1);
        geom.setAttribute("tileUv", uvs);
        geom.setAttribute("tileFlags", flags);
        const mesh = new THREE.InstancedMesh(geom, tileMaterial(map, layer.opacity), cells.length);
        mesh.name = `${layer.name}/${atlas.name}`;
        mesh.frustumCulled = false; // the instances spread far beyond the one quad's bounds
        const m = new THREE.Matrix4();
        cells.forEach((c, i) => {
          const tile = tileset.tiles.get(`${c.atlas},${c.col},${c.row}`)!;
          // the quad's centre: the image's top-left (map pixels, from the importer) plus half the atlas tile
          const qx = (c.left + atlas.tileSize[0] / 2) / this.unit, qz = (c.top + atlas.tileSize[1] / 2) / this.unit;
          m.compose(new THREE.Vector3(qx, li * LAYER_LIFT, qz), flat, new THREE.Vector3(1, 1, 1));
          mesh.setMatrixAt(i, m);
          this.setTileUv(mesh, i, atlas.tileSize, c.col, c.row);
          flags.setX(i, c.flags);
          if (tile.anim && tile.anim.frames > 1) this.animated.push({ mesh, index: i, tile, col: c.col });
        });
        this.add(mesh);
      }
    });
    // objects: their pivot on map pixel (x, y), standing on the top layer
    const lift = def.layers.length * LAYER_LIFT;
    for (const o of def.objects) {
      const sprite = pack.sprites.get(o.asset);
      const anim = pack.animated.get(o.asset);
      const obj: DotworkObject = sprite ? new DotworkSprite(sprite, tex, { ppu: this.unit }) : new AnimatedSprite3D(anim!, tex, { ppu: this.unit });
      obj.position.set(o.x / this.unit, lift, o.y / this.unit);
      this.objects.push(obj);
      this.add(obj);
    }
  }

  /** The map's size in world units (x along +X, y along +Z). */
  get extent(): Point {
    return [(this.def.size[0] * this.def.tileSize[0]) / this.unit, (this.def.size[1] * this.def.tileSize[1]) / this.unit];
  }

  private setTileUv(mesh: THREE.InstancedMesh, i: number, size: Point, col: number, row: number): void {
    const [w, h] = imageSize((mesh.material as THREE.MeshBasicMaterial).map!);
    const r = uvRect([col * size[0], row * size[1], size[0], size[1]], w, h);
    (mesh.geometry.getAttribute("tileUv") as THREE.InstancedBufferAttribute).setXYZW(i, r[0], r[1], r[2], r[3]);
  }

  update(dt: number, camera?: THREE.Camera): void {
    this.time += dt;
    for (const a of this.animated) {
      const col = tileAnimCol(a.tile, this.time);
      if (col === a.col) continue;
      a.col = col;
      const atlas = this.tileset.atlases.find((x) => x.id === a.tile.atlas)!;
      this.setTileUv(a.mesh, a.index, atlas.tileSize, col, a.tile.row);
      a.mesh.geometry.getAttribute("tileUv").needsUpdate = true;
    }
    for (const o of this.objects) o.update(dt, camera);
  }
}

// ---- Text ------------------------------------------------------------------------------
export interface TextOptions extends QuadOptions {
  /** Ink colour for a tint font (white ink); a coloured font (tint false) ignores it. */
  color?: THREE.ColorRepresentation;
  /** Where the origin sits on the text block, 0..1 (0, 0 top-left; 0.5, 1 bottom centre). */
  anchor?: Point;
}

/** A `font` drawn as glyph quads from its chars table (no BMFont loader needed); one material per page. */
export class DotworkText extends THREE.Mesh<THREE.BufferGeometry, THREE.MeshBasicMaterial[]> implements DotworkObject {
  billboard: boolean;
  text = "";
  /** Size of the laid-out block in world units. */
  readonly size = new THREE.Vector2();
  private readonly ppu: number;
  private readonly anchor: Point;

  constructor(readonly font: FontDef, private readonly tex: TextureLookup, text: string, opts: TextOptions = {}) {
    const ink = new THREE.Color(font.tint ? (opts.color ?? "#ffffff") : "#ffffff");
    super(new THREE.BufferGeometry(), font.pages.map((p) => {
      const m = spriteMaterial(tex(p));
      m.color = ink;
      return m;
    }));
    this.name = `${font.name}_text`;
    this.ppu = (opts.ppu ?? DEFAULT_PPU) / (font.scale || 1);
    this.billboard = opts.billboard ?? true;
    this.anchor = opts.anchor ?? [0, 0];
    this.setText(text);
  }

  setText(text: string): void {
    this.text = text;
    const lay = layoutText(this.font, text);
    const quads = [...lay.quads].sort((a, b) => a.page - b.page);
    const pos: number[] = [], uv: number[] = [], index: number[] = [];
    const ax = this.anchor[0] * lay.width, ay = this.anchor[1] * lay.height;
    const g = new THREE.BufferGeometry();
    let start = 0;
    quads.forEach((q, i) => {
      const [W, H] = imageSize(this.tex(this.font.pages[q.page]));
      const x0 = (q.x - ax) / this.ppu, x1 = (q.x + q.w - ax) / this.ppu;
      const y0 = -(q.y - ay) / this.ppu, y1 = -(q.y + q.h - ay) / this.ppu; // y down -> up
      const [u0, v0, du, dv] = uvRect(q.src, W, H);
      pos.push(x0, y0, 0, x1, y0, 0, x0, y1, 0, x1, y1, 0);
      uv.push(u0, v0 + dv, u0 + du, v0 + dv, u0, v0, u0 + du, v0);
      const b = i * 4;
      index.push(b, b + 2, b + 1, b + 2, b + 3, b + 1);
      if (i === quads.length - 1 || quads[i + 1].page !== q.page) {
        g.addGroup(start * 6, (i + 1 - start) * 6, q.page);
        start = i + 1;
      }
    });
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(index);
    this.geometry.dispose();
    this.geometry = g;
    this.size.set(lay.width / this.ppu, lay.height / this.ppu);
  }

  update(_dt: number, camera?: THREE.Camera): void {
    if (this.billboard && camera) faceCamera(this, camera);
  }
}

// ---- 9-slice -----------------------------------------------------------------------------
/** A `ui_kit` part stretched to width x height image pixels: corners stay, edges stretch one way, the centre both.
 *  A part without margins stretches whole. The origin is the top-left corner. */
export class DotworkNineSlice extends THREE.Mesh<THREE.BufferGeometry, THREE.MeshBasicMaterial> {
  constructor(readonly part: UiPartDef, tex: TextureLookup, width: number, height: number, opts: QuadOptions = {}) {
    const map = tex(part.image);
    super(nineSliceGeometry(part, imageSize(map), width, height, opts.ppu ?? DEFAULT_PPU), spriteMaterial(map));
    this.name = part.name;
  }
}

export function nineSliceGeometry(part: UiPartDef, image: Point, width: number, height: number, ppu: number): THREE.BufferGeometry {
  const [w, h] = part.size;
  const [l, t, r, b] = part.margins ?? [0, 0, 0, 0];
  const srcX = [0, l, w - r, w], dstX = [0, l, width - r, width];
  const srcY = [0, t, h - b, h], dstY = [0, t, height - b, height];
  const pos: number[] = [], uv: number[] = [], index: number[] = [];
  for (let j = 0; j < 3; j++) {
    for (let i = 0; i < 3; i++) {
      if (srcX[i + 1] <= srcX[i] || srcY[j + 1] <= srcY[j] || dstX[i + 1] <= dstX[i] || dstY[j + 1] <= dstY[j]) continue;
      const [u0, v0, du, dv] = uvRect([srcX[i], srcY[j], srcX[i + 1] - srcX[i], srcY[j + 1] - srcY[j]], image[0], image[1]);
      const x0 = dstX[i] / ppu, x1 = dstX[i + 1] / ppu, y0 = -dstY[j] / ppu, y1 = -dstY[j + 1] / ppu;
      const base = pos.length / 3;
      pos.push(x0, y0, 0, x1, y0, 0, x0, y1, 0, x1, y1, 0);
      uv.push(u0, v0 + dv, u0 + du, v0 + dv, u0, v0, u0 + du, v0);
      index.push(base, base + 2, base + 1, base + 2, base + 3, base + 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(index);
  return g;
}
