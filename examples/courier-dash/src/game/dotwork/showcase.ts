// ---------------------------------------------------------------------------
// showcase.ts
// Purpose : The starter scene's view of the game's Dotwork art: the first map laid flat, a character walking
//           across it, a prop beside its path and a label in the first font, in the diorama look (flat tiles,
//           billboards that turn around y).
// Usage   : const show = new DotworkShowcase(lib); scene.add(show); show.update(dt, camera) each frame
//           (src/game/Game.ts). Shows only what the packs have; with no manifests it is an empty group.
// Notes   : PROTOTYPE: replace with your own placement. One world unit is one tile of the map (the character and
//           the prop use the map's pixels per unit, so their sizes match the tiles), else DEFAULT_PPU.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import type { DotworkLibrary } from "./library";
import { AnimatedSprite3D, DEFAULT_PPU, type DotworkObject } from "./threeBuild";

// ---- Tunables ----------------------------------------------------------------
const WALK_SPEED = 1.2; // world units (tiles) per second
const WALK_HALF_WIDTH = 3; // the character walks between -this and +this when there is no map
const LABEL_GAP = 0.5; // world units in front of the map's near edge (nothing stands between it and the camera)
const LABEL = "DOTWORK"; // the label's text, cut to the chars the font has
const LABEL_FALLBACK = 8; // a font with none of them shows its own first chars instead

export class DotworkShowcase extends THREE.Group {
  private readonly parts: DotworkObject[] = [];
  private walker: AnimatedSprite3D | null = null;
  private dir = 1;
  private halfWidth = WALK_HALF_WIDTH;

  constructor(lib: DotworkLibrary) {
    super();
    this.name = "dotwork_showcase";
    const first = <T>(pick: (p: DotworkLibrary["packs"][number]) => Map<string, T>): [string, string, T] | null => {
      for (const p of lib.packs) for (const [name, def] of pick(p)) return [p.pack, name, def];
      return null;
    };
    let ppu = DEFAULT_PPU;
    let depth = 2;

    const m = first((p) => p.maps);
    if (m) {
      const map = lib.map(m[1], m[0]);
      const [w, d] = map.extent;
      map.position.set(-w / 2, 0.01, -d / 2); // centred on the origin
      ppu = map.unit;
      depth = d;
      this.halfWidth = Math.max(1, w / 2 - 1);
      this.add(map);
      this.parts.push(map);
    }

    const walkers = lib.packs.flatMap((p) => [...p.animated.values()].map((def) => ({ pack: p.pack, def })));
    const hero = walkers.find((x) => x.def.directions.walk) ?? walkers.find((x) => x.def.role === "characters");
    if (hero) {
      this.walker = lib.animated(hero.def.name, { ppu, pack: hero.pack });
      this.add(this.walker);
      this.parts.push(this.walker);
    }

    const s = first((p) => p.sprites);
    if (s) {
      const prop = lib.sprite(s[1], { ppu, pack: s[0] });
      prop.position.set(-this.halfWidth / 2, 0.01, depth / 4);
      this.add(prop);
      this.parts.push(prop);
    }

    const f = first((p) => p.fonts);
    if (f) {
      const has = (ch: string) => f[2].glyphs.has(ch.codePointAt(0)!);
      const own = [...f[2].glyphs.values()].filter((g) => g.w > 0).slice(0, LABEL_FALLBACK).map((g) => String.fromCodePoint(g.id));
      const text = [...LABEL].filter(has).join("") || own.join("");
      const label = lib.text(f[1], text, { ppu, anchor: [0.5, 1], pack: f[0] });
      label.position.set(0, 0.01, depth / 2 + LABEL_GAP);
      this.add(label);
      this.parts.push(label);
    }
  }

  update(dt: number, camera: THREE.Camera): void {
    const w = this.walker;
    if (w) {
      w.position.x += this.dir * WALK_SPEED * dt;
      if (Math.abs(w.position.x) > this.halfWidth) {
        w.position.x = Math.sign(w.position.x) * this.halfWidth;
        this.dir = -this.dir;
      }
      if (w.def.directions.walk) w.playDirection("walk", this.dir > 0 ? "e" : "w");
    }
    for (const p of this.parts) p.update(dt, camera);
  }

  /** Frees what disposeScene cannot see: the animated sprites' other clips and texture views. */
  dispose(): void {
    this.traverse((o) => {
      if (o instanceof AnimatedSprite3D) o.dispose();
    });
  }
}
