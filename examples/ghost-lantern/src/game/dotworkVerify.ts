// ---------------------------------------------------------------------------
// dotworkVerify.ts
// Purpose : The browser half of the stand-in for Dotwork's Godot `verify` (#55): before the shell starts, load every
//           Dotwork manifest of the game in Phaser and build every asset: frames, animations, sprites, maps, fonts,
//           9-slices. Anything missing or broken is a console error, so `dev.py smoke` fails on it.
// Usage   : main.ts: postBoot: (g) => void verifyDotwork(g).then(() => shell.start(phaserHost(g)))
// Notes   : Runs only in a dev server, an automated browser (smoke) or with ?dotwork-verify, and only when the game
//           has manifests; a player's build boots straight to the title. Ends with
//           DOTWORK_VERIFY_OK <manifests> manifest(s), <assets> asset(s), or DOTWORK_VERIFY_FAILED <problems>.
//           It also checks the Phaser rule the importer relies on: a playing clip waits each frame's own duration.
//           Pseudocode:
//             no manifests or not asked -> done
//             add a hidden scene; preload: queueDotwork; a load error is a problem
//             create: per pack: plan errors, buildDotwork, then make every asset once and compare with the plan
//             log the result, remove the scene, start the shell
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { Log } from "../core/log";
import type { DotworkPlan } from "./dotworkPlan";
import {
  addAnimatedSprite, addMap, addNineSlice, addSprite, addText, buildDotwork, DOTWORK_MANIFESTS, dotworkPacks, queueDotwork,
} from "./dotwork";

const SCENE_KEY = "dotwork-verify";
const CHANNEL = "dotwork";
const MS_TOLERANCE = 1e-6;

/** True when this run should check the manifests: a dev server, an automated browser or ?dotwork-verify. */
export function verifyWanted(): boolean {
  return DOTWORK_MANIFESTS.length > 0 && (import.meta.env.DEV || navigator.webdriver === true || new URLSearchParams(location.search).has("dotwork-verify"));
}

/** Loads and builds every manifest in a hidden scene; resolves when done (problems are logged, never thrown). */
export function verifyDotwork(game: Phaser.Game): Promise<void> {
  if (!verifyWanted()) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      game.scene.remove(SCENE_KEY);
      resolve();
    };
    game.scene.add(SCENE_KEY, new VerifyScene(done), true);
  });
}

class VerifyScene extends Phaser.Scene {
  private problems: string[] = [];

  constructor(private readonly done: () => void) {
    super(SCENE_KEY);
  }

  preload(): void {
    this.load.on(Phaser.Loader.Events.FILE_LOAD_ERROR, (file: Phaser.Loader.File) => this.problems.push(`could not load ${file.url}`));
    queueDotwork(this);
  }

  create(): void {
    let assets = 0;
    try {
      const packs = dotworkPacks();
      if (packs.length < DOTWORK_MANIFESTS.length) this.problems.push(`${DOTWORK_MANIFESTS.length - packs.length} manifest(s) did not load (see the errors above)`);
      for (const plan of packs) assets += this.checkPack(plan);
    } catch (err) {
      this.problems.push(`verify stopped: ${err instanceof Error ? err.message : String(err)}`);
    }
    for (const p of this.problems) Log.error(CHANNEL, p);
    if (this.problems.length) Log.error(CHANNEL, `DOTWORK_VERIFY_FAILED ${this.problems.length} problem(s)`);
    else Log.info(CHANNEL, `DOTWORK_VERIFY_OK ${DOTWORK_MANIFESTS.length} manifest(s), ${assets} asset(s)`);
    this.children.removeAll(true);
    this.time.delayedCall(0, this.done);
  }

  /** Makes every asset of one pack once; returns how many were checked. */
  private checkPack(plan: DotworkPlan): number {
    const bad = (msg: string) => this.problems.push(`${plan.pack}: ${msg}`);
    plan.errors.forEach(bad);
    buildDotwork(this, plan).forEach(bad);
    let n = 0;
    const guard = (what: string, fn: () => void) => {
      n++;
      try {
        fn();
      } catch (err) {
        bad(`${what}: ${err instanceof Error ? err.message : String(err)}`);
      }
    };
    for (const a of plan.animatedSprites.values()) {
      guard(`animated_sprite ${a.name}`, () => {
        for (const c of a.clips) {
          const anim = this.anims.get(c.key);
          if (!anim) throw new Error(`clip ${c.name} has no animation`);
          if (anim.frames.length !== c.frames.length) throw new Error(`clip ${c.name}: ${anim.frames.length} frames, plan has ${c.frames.length}`);
          anim.frames.forEach((f, i) => {
            const want = c.frames[i];
            if (Math.abs(f.duration - want.ms) > MS_TOLERANCE) throw new Error(`clip ${c.name} frame ${i}: ${f.duration} ms, plan has ${want.ms}`);
            const cut = f.frame;
            if (cut.cutX !== want.rect[0] || cut.cutY !== want.rect[1] || cut.cutWidth !== want.rect[2] || cut.cutHeight !== want.rect[3]) {
              throw new Error(`clip ${c.name} frame ${i}: cut ${cut.cutX},${cut.cutY},${cut.cutWidth},${cut.cutHeight}, plan has ${want.rect}`);
            }
          });
          // Phaser's timing: the first frame waits its own duration (Phaser 3 added the base rate to it)
          const s = addAnimatedSprite(this, plan, a.name, 0, 0, c.name);
          if (Math.abs(s.anims.nextTick - c.frames[0].ms) > MS_TOLERANCE) throw new Error(`clip ${c.name}: Phaser waits ${s.anims.nextTick} ms on frame 0, the manifest says ${c.frames[0].ms}`);
          if (Math.abs(s.originX - c.origin[0]) > MS_TOLERANCE || Math.abs(s.originY - c.origin[1]) > MS_TOLERANCE) throw new Error(`clip ${c.name}: origin ${s.originX},${s.originY}, plan has ${c.origin}`);
          s.destroy();
        }
      });
    }
    for (const s of plan.sprites.values()) guard(`sprite ${s.name}`, () => addSprite(this, plan, s.name, 0, 0));
    for (const i of plan.icons.values()) guard(`icon ${i.name}`, () => i.sizes.forEach((z) => this.add.image(0, 0, z.texture)));
    for (const p of plan.portraits.values()) guard(`portrait ${p.name}`, () => p.expressions.forEach((e) => this.add.image(0, 0, e.texture)));
    for (const t of plan.tilesets.values()) guard(`tileset ${t.name}`, () => t.atlases.forEach((at) => this.textures.get(at.texture).getSourceImage()));
    for (const m of plan.maps.values()) {
      guard(`map ${m.name}`, () => {
        const want = m.layers.reduce((s, L) => s + L.cells.length, 0);
        const built = addMap(this, plan, m.name);
        if (built.placed !== want) throw new Error(`${built.placed} tiles placed, plan has ${want}`);
        built.map.destroy();
      });
    }
    for (const f of plan.fonts.values()) {
      guard(`font ${f.name}`, () => {
        const glyph = f.chars.find((c) => c[3] > 0 && c[8] === 0);
        if (!glyph) return;
        const t = addText(this, plan, f.name, 0, 0, String.fromCodePoint(glyph[0]), 1);
        if (Math.round(t.getTextBounds().local.width) <= 0) throw new Error(`glyph ${glyph[0]} draws nothing`);
      });
    }
    for (const k of plan.uiKits.values()) guard(`ui_kit ${k.name}`, () => k.parts.forEach((p) => addNineSlice(this, plan, k.name, p.name, 0, 0, p.size[0] * 3, p.size[1] * 3)));
    n += plan.backgrounds.size + plan.others.length; // extra kinds: their files were loaded with the rest
    return n;
  }
}
