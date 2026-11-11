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
//           Every image goes through pixelTexture (nearest, no mipmaps, sRGB). A manifest or image that fails to
//           load rejects load() with the URL in the message (the loading screen's crash path shows it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { Log } from "../../core/log";
import { DotworkError, importManifest, type PackDef } from "./manifest";
import {
  AnimatedSprite3D, DotworkNineSlice, DotworkPortrait, DotworkSprite, DotworkText, DotworkTileMap, iconQuad, pixelTexture,
  type QuadOptions, type TextOptions,
} from "./threeBuild";

// ---- Tunables ----------------------------------------------------------------
const MANIFEST_SHARE = 0.1; // of the loading bar: the manifests; the images take the rest

type PackMaps = "animated" | "sprites" | "icons" | "portraits" | "tilesets" | "maps" | "fonts" | "uiKits" | "backgrounds";

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
      textures.set(url, pixelTexture(tex));
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

  sprite(name: string, opts: QuadOptions & { pack?: string } = {}): DotworkSprite {
    return new DotworkSprite(this.def("sprites", name, opts.pack), this.lookup, opts);
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

  /** Frees every texture (the objects' own geometry and materials go with their scene: disposeScene). */
  dispose(): void {
    for (const t of this.textures.values()) t.dispose();
    this.textures.clear();
  }
}

// {{FOOTER}}
