// ---------------------------------------------------------------------------
// library.ts
// Purpose : Loads Dotwork asset manifests and their images in the browser and builds Three.js objects by name:
//           the one place a world asks for Dotwork art.
// Usage   : const lib = await DotworkLibrary.load(DOTWORK_MANIFESTS, progress);   // in a World's load()
//           const hero = lib.animated("hero", { ppu: 16 }); hero.playDirection("walk", "s"); scene.add(hero);
//           const yard = lib.map("yard"); const label = lib.text("tiny", "HELLO");
//           hero.update(dt, camera) / yard.update(dt, camera) every frame; lib.dispose() when the world ends.
// Notes   : DOTWORK_MANIFESTS (src/game/dotwork/boot.ts) lists public/assets/dotwork/*.assets.json at build time.
//           Names are unique per pack, not across packs: the first pack that has a name wins; pass `pack` to pick.
//           Every image goes through pixelTexture (nearest, no mipmaps, sRGB); the data images (normal maps,
//           transition rules) are left in no colour space, so a shader reads their bytes as they are. A manifest
//           or image that fails to load rejects load() with the URL in the message (the loading screen's crash
//           path shows it). The extra kinds come out by name with their textures: `background` (a texture per
//           layer wrapping on its `repeat` axes), `particles` (texture + emitter JSON), `transition` (texture +
//           kind), `normalMap` (texture + its target's texture; `sprite(name, { lit: true })` puts it on the
//           sprite's material) and `image` (a quad); the game object that uses them is the game's own.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the extra kinds by name,
//           data images without sRGB, lit sprites with their normal map
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { Log } from "../../core/log";
import { DotworkError, importManifest, type NormalMapDef, type PackDef, type ParticlesDef, type TransitionDef } from "./manifest";
import {
  AnimatedSprite3D, backgroundLayers, DotworkImage, DotworkNineSlice, DotworkPortrait, DotworkSprite, DotworkText, DotworkTileMap,
  iconQuad, imageQuad, pixelTexture, type QuadOptions, type SpriteOptions, type TextOptions,
} from "./threeBuild";

// ---- Tunables ----------------------------------------------------------------
const MANIFEST_SHARE = 0.1; // of the loading bar: the manifests; the images take the rest

type PackMaps = "animated" | "sprites" | "icons" | "portraits" | "tilesets" | "maps" | "fonts" | "uiKits" | "backgrounds"
  | "particles" | "transitions" | "normalMaps" | "pictures";

export class DotworkLibrary {
  constructor(readonly packs: PackDef[], private readonly textures: Map<string, THREE.Texture>) {}

  /** Fetches every manifest, then every image they draw from; progress(0..1) feeds the loading screen. */
  static async load(urls: string[], progress: (v: number) => void = () => {}, warn = (m: string) => Log.warn("dotwork", m)): Promise<DotworkLibrary> {
    const packs: PackDef[] = [];
    for (const [i, url] of urls.entries()) {
      const res = await fetch(url);
      if (!res.ok) throw new DotworkError(`${url}: HTTP ${res.status}`);
      packs.push(importManifest(await res.json(), res.url || url, warn));
      progress((MANIFEST_SHARE * (i + 1)) / urls.length);
    }
    const images = [...new Set(packs.flatMap((p) => [...p.images]))];
    const data = new Set(packs.flatMap((p) => [...p.dataImages]));
    const loader = new THREE.TextureLoader();
    const textures = new Map<string, THREE.Texture>();
    let done = 0;
    await Promise.all(images.map(async (url) => {
      let tex: THREE.Texture;
      try {
        tex = await loader.loadAsync(url);
      } catch {
        throw new DotworkError(`image ${url} did not load (missing file, or not a PNG)`);
      }
      tex.name = url;
      textures.set(url, pixelTexture(tex, data.has(url)));
      done += 1;
      progress(MANIFEST_SHARE + ((1 - MANIFEST_SHARE) * done) / images.length);
    }));
    progress(1);
    return new DotworkLibrary(packs, textures);
  }

  /** The loaded texture of an image URL (as the definitions name it). */
  texture(url: string): THREE.Texture {
    const t = this.textures.get(url);
    if (!t) throw new DotworkError(`image ${url} was not loaded (not in any manifest of this library)`);
    return t;
  }

  /** Every texture this library loaded (the boot check counts them). */
  get textureCount(): number {
    return this.textures.size;
  }

  /** The definition `name` of one kind, from `pack` or the first pack that has it. */
  def<K extends PackMaps>(kind: K, name: string, pack?: string): PackDef[K] extends Map<string, infer T> ? T : never {
    for (const p of this.packs) {
      if (pack && p.pack !== pack) continue;
      const d = (p[kind] as Map<string, unknown>).get(name);
      if (d) return d as never;
    }
    throw new DotworkError(`no ${kind} "${name}"${pack ? ` in pack ${pack}` : ""} (packs: ${this.packs.map((p) => p.pack).join(", ") || "none"})`);
  }

  /** The pack that holds a definition (maps need their pack for tilesets and objects). */
  private packOf(kind: PackMaps, name: string, pack?: string): PackDef {
    const p = this.packs.find((q) => (!pack || q.pack === pack) && (q[kind] as Map<string, unknown>).has(name));
    if (!p) throw new DotworkError(`no ${kind} "${name}"${pack ? ` in pack ${pack}` : ""}`);
    return p;
  }

  private readonly lookup = (url: string) => this.texture(url);

  animated(name: string, opts: QuadOptions & { clip?: string; pack?: string } = {}): AnimatedSprite3D {
    return new AnimatedSprite3D(this.def("animated", name, opts.pack), this.lookup, opts);
  }

  /** A prop or enemy on its pivot; `lit: true` gives it a lit material with the pack's normal map for its image. */
  sprite(name: string, opts: SpriteOptions & { pack?: string } = {}): DotworkSprite {
    const p = this.packOf("sprites", name, opts.pack);
    return new DotworkSprite(p.sprites.get(name)!, this.lookup, opts, p);
  }

  icon(name: string, px: number, opts: QuadOptions & { pack?: string } = {}) {
    return iconQuad(this.def("icons", name, opts.pack), this.lookup, px, opts);
  }

  portrait(name: string, expression?: string, opts: QuadOptions & { pack?: string } = {}): DotworkPortrait {
    return new DotworkPortrait(this.def("portraits", name, opts.pack), this.lookup, expression, opts);
  }

  map(name: string, pack?: string): DotworkTileMap {
    const p = this.packOf("maps", name, pack);
    const def = p.maps.get(name)!;
    return new DotworkTileMap(def, p.tilesets.get(def.tileset)!, p, this.lookup);
  }

  text(font: string, text: string, opts: TextOptions & { pack?: string } = {}): DotworkText {
    return new DotworkText(this.def("fonts", font, opts.pack), this.lookup, text, opts);
  }

  nineSlice(kit: string, part: string, width: number, height: number, opts: QuadOptions & { pack?: string } = {}): DotworkNineSlice {
    const def = this.def("uiKits", kit, opts.pack).parts.get(part);
    if (!def) throw new DotworkError(`ui_kit ${kit} has no part "${part}"`);
    return new DotworkNineSlice(def, this.lookup, width, height, opts);
  }

  // ---- The extra kinds: by name, with their textures; the game draws them ----
  /** A `background`'s layers (drawn first to last) each with a texture wrapping on its `repeat` axes: scroll one by
   *  `velocity` px/s through `texture.offset` (an offset of 1 is one image). */
  background(name: string, pack?: string) {
    return backgroundLayers(this.def("backgrounds", name, pack), this.lookup);
  }

  /** A `particles` asset: its white mask texture (tint it by the emitter's colour steps) and the emitter JSON. */
  particles(name: string, pack?: string): { def: ParticlesDef; texture: THREE.Texture } {
    const def = this.def("particles", name, pack);
    return { def, texture: this.texture(def.texture) };
  }

  /** A `transition`: its greyscale rule texture (no colour space: the bytes as drawn) and the transition's kind. */
  transition(name: string, pack?: string): { def: TransitionDef; texture: THREE.Texture } {
    const def = this.def("transitions", name, pack);
    return { def, texture: this.texture(def.image) };
  }

  /** A `normal_map` (OpenGL style, green up, as three expects) with the texture of the image it lights. */
  normalMap(name: string, pack?: string): { def: NormalMapDef; texture: THREE.Texture; target: THREE.Texture } {
    const def = this.def("normalMaps", name, pack);
    return { def, texture: this.texture(def.image), target: this.texture(def.target) };
  }

  /** An `image` asset (a logo, a loose sheet) on its pivot, or centred when it has none. */
  image(name: string, opts: QuadOptions & { pack?: string } = {}): DotworkImage {
    return imageQuad(this.def("pictures", name, opts.pack), this.lookup, opts);
  }

  /** Frees every texture (the objects' own geometry and materials go with their scene: disposeScene). */
  dispose(): void {
    for (const t of this.textures.values()) t.dispose();
    this.textures.clear();
  }
}
