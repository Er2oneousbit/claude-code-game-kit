// ---------------------------------------------------------------------------
// dotwork.ts (game)
// Purpose : The Phaser half of the Dotwork importer (#55): loads every Dotwork manifest of the game
//           (public/assets/dotwork/*.assets.json) and its PNGs, then turns the plan src/game/dotworkPlan.ts makes into
//           Phaser objects: named frames with their pivots, animations with each frame's own duration, bitmap
//           fonts, sprites with Arcade collision boxes, tilemaps with terrain layers resolved, 9-slices.
// Usage   : preload(): queueDotwork(this)                     // every manifest (or pass a list of URLs)
//           create():  const pack = dotworkPack()            // the first loaded pack (or dotworkPack("town"))
//                      const hero = addAnimatedSprite(this, pack, "hero", 100, 80, "walk_s")
//                      const crate = addSprite(this, pack, "crate", 140, 80)
//                      const yard = addMap(this, pack, "yard", 0, 0)   // .layers, .collision, .objects
//                      addCollisionBodies(this, [...yard.collision, ...crate.collision])   // needs Arcade physics
//                      addText(this, pack, "dialogue", 8, 8, "Hello")
//                      addNineSlice(this, pack, "windows", "ui_window_plain", 8, 8, 120, 40)
// Notes   : Phaser 4.2.1 (checked in its source, not memory):
//           - an animation frame's `duration` REPLACES the clip's base rate for that frame
//             (Animation.getNextTick: nextTick = frame.duration || msPerFrame) as long as play() keeps the clip's
//             frameRate. Phaser 3 added it to the base rate; dotworkVerify.ts checks the 4.x rule in the browser.
//           - a texture frame with customPivot sets the sprite's origin whenever an animation shows it, so a clip
//             with another frame size or pivot (a wider death clip) keeps its feet in place.
//           - tilemap layers play Tiled-style tile animations (tileset.tileData) on their own timer.
//           - BitmapText reads font data in ParseXMLBitmapFont's shape; it is built from `chars` (one page).
//           Textures are game-wide: a second scene reuses them (queueDotwork loads nothing twice).
//           Animation keys: <pack>/<asset>/<clip>; fonts: <pack>/<font> (names are unique per pack only).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import manifestFiles from "virtual:dotwork-manifests";
import { Log } from "../core/log";
import {
  bitmapFontData, directionClip, DotworkError, planManifest, rectToWorld, tileAnimations, tileTransform,
  type DotworkPlan, type PlanClip, type Rect,
} from "./dotworkPlan";

const CHANNEL = "dotwork";
/** Every manifest of the game, as URLs relative to the page ("assets/dotwork/town.assets.json"). */
export const DOTWORK_MANIFESTS: readonly string[] = manifestFiles;

const plans = new Map<string, DotworkPlan>(); // by manifest URL, for the whole game
const reported = new Set<string>();
const built = new Map<string, string[]>(); // manifest URL -> the problems its build found (built once per game)

/** Queues the manifests, then (as each arrives) the PNGs it names, on this scene's loader. Call in preload(). */
export function queueDotwork(scene: Phaser.Scene, urls: readonly string[] = DOTWORK_MANIFESTS): void {
  for (const url of urls) {
    const known = plans.get(url);
    if (known) {
      queueTextures(scene, known);
      continue;
    }
    const key = `dotwork-manifest:${url}`;
    scene.load.once(`filecomplete-json-${key}`, (_k: string, _t: string, data: unknown) => {
      try {
        const plan = planManifest(data, url);
        plans.set(url, plan);
        report(plan);
        queueTextures(scene, plan);
      } catch (err) {
        if (!(err instanceof DotworkError)) throw err;
        Log.error(CHANNEL, err.message);
      }
    });
    scene.load.json(key, url);
  }
}

function queueTextures(scene: Phaser.Scene, plan: DotworkPlan): void {
  for (const t of plan.textures.values()) if (!scene.textures.exists(t.key)) scene.load.image(t.key, t.url);
}

/** Warnings once per pack (info: skipped extra kinds are expected), broken assets as errors (smoke fails). */
function report(plan: DotworkPlan): void {
  if (reported.has(plan.url)) return;
  reported.add(plan.url);
  for (const w of plan.warnings) Log.warn(CHANNEL, `${plan.pack}: ${w}`);
  for (const e of plan.errors) Log.error(CHANNEL, e);
}

/** A loaded pack by name, or the first one; built into Phaser objects on first use. Null when there is none. */
export function dotworkPack(pack?: string, scene?: Phaser.Scene): DotworkPlan | null {
  for (const p of plans.values()) {
    if (pack !== undefined && p.pack !== pack) continue;
    if (scene) buildDotwork(scene, p);
    return p;
  }
  return null;
}

/** Every pack loaded so far. */
export const dotworkPacks = (): DotworkPlan[] => [...plans.values()];

/** Frames, pivots, nearest filtering, animations and bitmap fonts of one pack (game-wide: built once, later calls
 *  return the first result). Returns the problems found (a texture that did not load), each logged once as an error. */
export function buildDotwork(scene: Phaser.Scene, plan: DotworkPlan): string[] {
  const done = built.get(plan.url);
  if (done) return done;
  const out: string[] = [];
  built.set(plan.url, out);
  const fail = (msg: string) => {
    out.push(msg);
    Log.error(CHANNEL, `${plan.pack}: ${msg}`);
  };
  for (const t of plan.textures.values()) {
    if (scene.textures.exists(t.key)) scene.textures.get(t.key).setFilter(Phaser.Textures.FilterMode.NEAREST);
    else fail(`${t.path} did not load`);
  }
  for (const f of plan.frames) {
    if (!scene.textures.exists(f.texture)) continue;
    const tex = scene.textures.get(f.texture);
    const frame = tex.has(f.name) ? tex.get(f.name) : tex.add(f.name, 0, f.rect[0], f.rect[1], f.rect[2], f.rect[3]);
    if (!frame) {
      fail(`frame ${f.name} could not be cut from ${f.texture}`);
      continue;
    }
    frame.customPivot = true;
    frame.pivotX = f.origin[0];
    frame.pivotY = f.origin[1];
  }
  for (const a of plan.animatedSprites.values()) {
    for (const c of a.clips) {
      if (scene.anims.exists(c.key) || !c.frames.every((f) => scene.textures.exists(f.texture))) continue;
      scene.anims.create({
        key: c.key,
        frames: c.frames.map((f) => ({ key: f.texture, frame: f.frame, duration: f.ms })),
        frameRate: c.fps, // the base rate; each frame's duration replaces it (see the header)
        repeat: c.loop ? -1 : 0,
      });
    }
  }
  for (const f of plan.fonts.values()) {
    if (scene.cache.bitmapFont.exists(f.key) || !scene.textures.exists(f.texture)) continue;
    const img = scene.textures.get(f.texture).getSourceImage() as { width: number; height: number };
    scene.cache.bitmapFont.add(f.key, { data: bitmapFontData(f, img.width, img.height), texture: f.texture, frame: null });
  }
  return out;
}

// ---- game objects --------------------------------------------------------------------------------------------
function need<T>(v: T | undefined, what: string, plan: DotworkPlan): T {
  if (v === undefined) throw new DotworkError(`${plan.pack}: no ${what} in this pack`);
  return v;
}

/** A sprite playing one clip (default: the first), its pivot on (x, y). Blend "add" draws additively. */
export function addAnimatedSprite(scene: Phaser.Scene, plan: DotworkPlan, name: string, x: number, y: number, clip?: string): Phaser.GameObjects.Sprite {
  buildDotwork(scene, plan);
  const a = need(plan.animatedSprites.get(name), `animated_sprite ${name}`, plan);
  const c = need(clip === undefined ? a.clips[0] : a.clips.find((k) => k.name === clip), `clip ${clip} of ${name}`, plan);
  const s = scene.add.sprite(x, y, c.frames[0].texture, c.frames[0].frame).setOrigin(c.origin[0], c.origin[1]);
  if (a.blend === "add") s.setBlendMode(Phaser.BlendModes.ADD);
  s.play(c.key);
  return s;
}

/** Plays an action facing a direction ("walk", "e") on a sprite from addAnimatedSprite; keeps playing when unchanged. */
export function playDirection(sprite: Phaser.GameObjects.Sprite, plan: DotworkPlan, name: string, action: string, dir: string): PlanClip | null {
  const a = plan.animatedSprites.get(name);
  const c = a ? directionClip(a, action, dir) : null;
  if (c) sprite.play(c.key, true);
  return c;
}

/** A still sprite (a prop, an enemy) with its pivot on (x, y), its contact shadow behind it, and its collision
 *  rects in world pixels (for addCollisionBodies). */
export function addSprite(scene: Phaser.Scene, plan: DotworkPlan, name: string, x: number, y: number): { image: Phaser.GameObjects.Image; shadow: Phaser.GameObjects.Image | null; collision: CollisionRect[] } {
  buildDotwork(scene, plan);
  const s = need(plan.sprites.get(name), `sprite ${name}`, plan);
  const shadow = s.shadow ? scene.add.image(x + s.shadow.offset[0], y + s.shadow.offset[1], s.shadow.texture) : null;
  const image = scene.add.image(x, y, s.texture).setOrigin(s.origin[0], s.origin[1]);
  return { image, shadow, collision: s.collision.map((r) => ({ rect: rectToWorld(r, s.pivot, x, y), oneWay: false })) };
}

export interface CollisionRect {
  rect: Rect; // world pixels
  oneWay: boolean; // collides from above only
}

export interface BuiltMap {
  map: Phaser.Tilemaps.Tilemap;
  layers: Phaser.Tilemaps.TilemapLayer[];
  collision: CollisionRect[];
  objects: Phaser.GameObjects.GameObject[];
  placed: number; // tiles put on the layers
}

/** A Dotwork map at (x, y): a blank tilemap per the plan, a layer per manifest layer (terrain layers already
 *  resolved by the blob rule), tile flags as flips and quarter turns, animated tiles, collision rects of every
 *  placed tile, and the map's objects (y-sorted by their feet). */
export function addMap(scene: Phaser.Scene, plan: DotworkPlan, name: string, x = 0, y = 0): BuiltMap {
  buildDotwork(scene, plan);
  const m = need(plan.maps.get(name), `map ${name}`, plan);
  const ts = need(plan.tilesets.get(m.tileset), `tileset ${m.tileset}`, plan);
  const orientation = ts.shape === "isometric" ? Phaser.Tilemaps.Orientation.ISOMETRIC : Phaser.Tilemaps.Orientation.ORTHOGONAL;
  const data = new Phaser.Tilemaps.MapData({ width: m.size[0], height: m.size[1], tileWidth: m.tileSize[0], tileHeight: m.tileSize[1], orientation });
  const map = new Phaser.Tilemaps.Tilemap(scene, data);
  const anims = tileAnimations(ts);
  const tilesets: Phaser.Tilemaps.Tileset[] = [];
  for (const at of ts.atlases) {
    const set = map.addTilesetImage(`${ts.name}/${at.name}`, at.texture, at.tileSize[0], at.tileSize[1], 0, 0, at.firstgid);
    if (!set) throw new DotworkError(`${plan.pack}: atlas ${at.name} of ${ts.name} could not become a tileset`);
    const a = anims.get(at.id);
    if (a) set.tileData = a;
    tilesets.push(set);
  }
  const tileByGid = new Map(ts.tiles.map((t) => [t.gid, t]));
  const out: BuiltMap = { map, layers: [], collision: [], objects: [], placed: 0 };
  for (const L of m.layers) {
    const layer = map.createBlankLayer(`${m.name}/${L.name}`, tilesets, x, y);
    if (!layer) throw new DotworkError(`${plan.pack}: layer ${L.name} of ${m.name} could not be created`);
    layer.setAlpha(L.opacity);
    for (const c of L.cells) {
      const tile = layer.putTileAt(c.gid, c.x, c.y);
      if (!tile) continue;
      out.placed++;
      if (c.flags) {
        const t = tileTransform(c.flags);
        tile.flipX = t.flipX;
        tile.flipY = t.flipY;
        tile.rotation = (t.quarterTurns * Math.PI) / 2;
      }
      const info = tileByGid.get(c.gid);
      if (info && info.collision.length && ts.shape === "square") {
        // collision rects are in tile pixels from the tile's top-left (flags are not applied: Dotwork's flipped
        // tiles come from Pixelorama tilemaps, which carry no collision)
        for (const r of info.collision) {
          out.collision.push({ rect: [x + c.x * m.tileSize[0] + r[0], y + c.y * m.tileSize[1] + r[1], r[2], r[3]], oneWay: info.oneWay });
        }
      }
    }
    out.layers.push(layer);
  }
  for (const o of m.objects) {
    if (plan.sprites.has(o.asset)) {
      const s = addSprite(scene, plan, o.asset, x + o.x, y + o.y);
      s.image.setDepth(y + o.y);
      out.objects.push(s.image);
      out.collision.push(...s.collision);
    } else if (plan.animatedSprites.has(o.asset)) {
      out.objects.push(addAnimatedSprite(scene, plan, o.asset, x + o.x, y + o.y).setDepth(y + o.y));
    } else {
      Log.warn(CHANNEL, `${plan.pack}: map ${m.name} places ${o.asset}, which is not a sprite of this pack`);
    }
  }
  return out;
}

/** Static Arcade bodies for collision rects (needs Arcade physics in this scene: `physics: { arcade: {} }` in
 *  the scene config, or a default in the game config). Null, with a warning, without it. */
export function addCollisionBodies(scene: Phaser.Scene, rects: readonly CollisionRect[]): Phaser.Physics.Arcade.StaticGroup | null {
  if (!scene.physics) {
    Log.warn(CHANNEL, "collision rects need Arcade physics in this scene: no bodies made");
    return null;
  }
  const group = scene.physics.add.staticGroup();
  for (const c of rects) {
    const [rx, ry, rw, rh] = c.rect;
    const zone = scene.add.zone(rx + rw / 2, ry + rh / 2, rw, rh);
    group.add(zone);
    const body = zone.body as Phaser.Physics.Arcade.StaticBody;
    body.setSize(rw, rh);
    if (c.oneWay) {
      body.checkCollision.down = false;
      body.checkCollision.left = false;
      body.checkCollision.right = false;
    }
  }
  group.refresh();
  return group;
}

/** A label in a Dotwork bitmap font. The pages are already drawn at the font's `scale` (2: every glyph pixel is
 *  2x2), so 1 draws them as they are; a larger whole number draws them bigger still. */
export function addText(scene: Phaser.Scene, plan: DotworkPlan, font: string, x: number, y: number, text: string, scale = 1): Phaser.GameObjects.BitmapText {
  buildDotwork(scene, plan);
  const f = need(plan.fonts.get(font), `font ${font}`, plan);
  return scene.add.bitmapText(x, y, f.key, text, f.lineHeight * Math.max(1, Math.round(scale)));
}

/** A 9-slice of a UI kit part, w x h pixels before `scale`; parts without margins are plain images. The images and
 *  their margins ([left, top, right, bottom]) are already at the part's own `scale`, so 1 draws them as they are. */
export function addNineSlice(scene: Phaser.Scene, plan: DotworkPlan, kit: string, part: string, x: number, y: number, w: number, h: number, scale = 1): Phaser.GameObjects.NineSlice | Phaser.GameObjects.Image {
  buildDotwork(scene, plan);
  const k = need(plan.uiKits.get(kit), `ui_kit ${kit}`, plan);
  const p = need(k.parts.find((q) => q.name === part), `part ${part} of ${kit}`, plan);
  const s = Math.max(1, Math.round(scale));
  if (!p.margins) return scene.add.image(x, y, p.texture).setOrigin(0, 0).setScale(s);
  const [l, t, r, b] = p.margins;
  return scene.add.nineslice(x, y, p.texture, undefined, Math.max(l + r, Math.round(w)), Math.max(t + b, Math.round(h)), l, r, t, b).setOrigin(0, 0).setScale(s);
}
