// ---------------------------------------------------------------------------
// MainScene.ts
// Purpose : The play scene: what "Play" on the main menu starts (after the loading screen).
// Usage   : Registered in src/main.ts as "main"; the shell (src/shell/app.ts) starts, pauses and stops it.
// Notes   : PROTOTYPE: a box bouncing around proves the loop and rendering work. Replace it with your game.
//           With Dotwork art (public/assets/dotwork/*.assets.json) it shows the importer instead (#55): the first
//           map, a character walking (it turns at the prop's collision box) and a prop at a whole-number zoom,
//           then a 9-slice window and a label in a Dotwork font on a second camera at 1:1.
//           Read the player's settings through shell.settings (game_speed scales dt here) and input through
//           shell.input (isDown / takePress with action names from settings.input.bindings; stick() and
//           triggers() for analog control, heldActions() for everything held).
//           HUD text drawn here (this.add.text, a bitmap label) follows the player's ui_scale and text_scale only
//           through hudFontPx(base, shell.settings) (src/core/hud.ts), redone in shell.onLook() (#309); the
//           shell's own HUD bar is HTML and follows them already.
//           BOOT_OK is logged by the shell once the title screen is up (dev.py smoke waits for it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the Dotwork showcase (#55)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): where HUD text gets ui_scale and text_scale (#309)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { shell } from "../shell/app";
import type { DotworkPlan } from "./dotworkPlan";
import {
  addAnimatedSprite, addCollisionBodies, addMap, addNineSlice, addSprite, addText, buildDotwork, dotworkPacks, playDirection, queueDotwork,
  type CollisionRect,
} from "./dotwork";

const BOX_SIZE = 32;
const START_VELOCITY = { x: 160, y: 110 }; // px/s
const MAX_DT = 0.1; // s: clamp big gaps (tab in background, debugger pause)
const SHOWCASE_ZOOM = 3; // whole number: pixel art stays crisp
const SHOWCASE_MARGIN = 8; // art pixels around the map
const WALK_SPEED = 24; // art px/s
const LABEL_GLYPHS = 16; // the label shows the font's first glyphs, so it never asks for one the font lacks
const UI_PAD = 8; // screen px around the window and its label
const UI_BOX_W = 320; // screen px: the window's widest

export class MainScene extends Phaser.Scene {
  private box: Phaser.GameObjects.Rectangle | null = null;
  private velocity = { ...START_VELOCITY };
  private walker: { sprite: Phaser.GameObjects.Sprite; pack: DotworkPlan; name: string; dir: number; minX: number; maxX: number } | null = null;

  constructor() {
    super({ key: "main", physics: { arcade: { debug: false } } });
  }

  preload(): void {
    queueDotwork(this); // nothing without Dotwork manifests
  }

  create(): void {
    this.velocity = { ...START_VELOCITY };
    this.walker = null;
    this.box = null;
    if (!this.showcase()) this.box = this.add.rectangle(40, 40, BOX_SIZE, BOX_SIZE, 0xf2c14e).setOrigin(0, 0);
  }

  /** Dotwork art from the game's packs: the first map, a character, a prop (in the world, zoomed), a 9-slice
   *  window and a font label (on a second camera at 1:1: UI kits and fonts are drawn at their own scale already).
   *  False when the game has no Dotwork art. */
  private showcase(): boolean {
    const packs = dotworkPacks();
    if (!packs.length) return false;
    for (const p of packs) buildDotwork(this, p);
    const first = <T>(pick: (p: DotworkPlan) => T | undefined | null): [DotworkPlan, T] | null => {
      for (const p of packs) {
        const v = pick(p);
        if (v !== undefined && v !== null) return [p, v];
      }
      return null;
    };
    const cam = this.cameras.main.setZoom(SHOWCASE_ZOOM);
    cam.setScroll(-(cam.width - cam.width / SHOWCASE_ZOOM) / 2, -(cam.height - cam.height / SHOWCASE_ZOOM) / 2); // world (0, 0) at the top-left
    const viewW = cam.width / SHOWCASE_ZOOM;
    const m = SHOWCASE_MARGIN;
    const rects: CollisionRect[] = [];
    let groundY = m * 4;
    const map = first((p) => p.maps.keys().next().value);
    if (map) {
      rects.push(...addMap(this, map[0], map[1], m, m).collision);
      const md = map[0].maps.get(map[1])!;
      groundY = m * 3 + md.size[1] * md.tileSize[1];
    }
    const prop = first((p) => p.sprites.keys().next().value);
    if (prop) {
      const s = addSprite(this, prop[0], prop[1], viewW * 0.6, groundY);
      s.image.setDepth(groundY);
      rects.push(...s.collision);
    }
    const bodies = addCollisionBodies(this, rects);
    const walker = first((p) => [...p.animatedSprites.values()].find((a) => a.directions.walk)?.name) ?? first((p) => p.animatedSprites.keys().next().value);
    if (walker) {
      const [pack, name] = walker;
      const sprite = addAnimatedSprite(this, pack, name, m * 2, groundY).setDepth(groundY);
      this.physics.add.existing(sprite);
      const body = sprite.body as Phaser.Physics.Arcade.Body;
      body.setSize(Math.max(1, sprite.width / 2), Math.max(1, sprite.height / 4)).setOffset(sprite.width / 4, (sprite.height * 3) / 4); // the feet
      if (bodies) this.physics.add.collider(sprite, bodies);
      this.walker = { sprite, pack, name, dir: 1, minX: m * 2, maxX: viewW - m * 2 };
      playDirection(sprite, pack, name, "walk", "e");
    }
    // the UI on its own camera at 1:1, along the bottom of the screen
    const world = [...this.children.list];
    const kit = first((p) => [...p.uiKits.values()].find((k) => k.parts.some((q) => q.margins && q.role === "window")) ?? [...p.uiKits.values()].find((k) => k.parts.some((q) => q.margins)));
    const font = first((p) => p.fonts.values().next().value);
    const { width, height } = this.scale;
    const part = kit ? (kit[1].parts.find((q) => q.margins && q.role === "window") ?? kit[1].parts.find((q) => q.margins)!) : null;
    const [l, t, , b] = part?.margins ?? [UI_PAD, UI_PAD, UI_PAD, UI_PAD]; // the text sits inside the window's border
    const boxH = (font ? font[1].lineHeight : UI_PAD * 2) + t + b;
    const boxY = height - UI_PAD * 2 - boxH;
    if (kit && part) addNineSlice(this, kit[0], kit[1].name, part.name, UI_PAD * 2, boxY, Math.min(width - UI_PAD * 4, UI_BOX_W), boxH);
    if (font) {
      const glyphs = font[1].chars.filter((c) => c[0] > 32 && c[3] > 0 && c[8] === 0).slice(0, LABEL_GLYPHS);
      addText(this, font[0], font[1].name, UI_PAD * 2 + l, boxY + t, glyphs.map((c) => String.fromCodePoint(c[0])).join(""));
    }
    const ui = this.children.list.filter((o) => !world.includes(o));
    if (ui.length) {
      cam.ignore(ui);
      this.cameras.add(0, 0, width, height).ignore(world);
    }
    return true;
  }

  update(_time: number, deltaMs: number): void {
    if (shell.plantedCrash) {
      shell.plantedCrash = false;
      throw new Error("planted crash (dev.py smoke --drive crash)"); // proves the crash hook end to end
    }
    const speed = shell.settings.access.game_speed;
    const dt = Math.min(deltaMs / 1000, MAX_DT) * speed;
    if (this.walker) this.walk(speed);
    if (!this.box) return;
    const { width, height } = this.scale;
    this.box.x += this.velocity.x * dt;
    this.box.y += this.velocity.y * dt;
    if (this.box.x < 0 || this.box.x + BOX_SIZE > width) this.velocity.x *= -1;
    if (this.box.y < 0 || this.box.y + BOX_SIZE > height) this.velocity.y *= -1;
    this.box.x = Phaser.Math.Clamp(this.box.x, 0, width - BOX_SIZE);
    this.box.y = Phaser.Math.Clamp(this.box.y, 0, height - BOX_SIZE);
  }

  /** Back and forth: turns at the ends and when its feet bump a collision box. */
  private walk(speed: number): void {
    const w = this.walker!;
    const body = w.sprite.body as Phaser.Physics.Arcade.Body;
    const blocked = w.dir > 0 ? body.blocked.right : body.blocked.left;
    if (blocked || (w.dir > 0 && w.sprite.x >= w.maxX) || (w.dir < 0 && w.sprite.x <= w.minX)) {
      w.dir = -w.dir;
      playDirection(w.sprite, w.pack, w.name, "walk", w.dir > 0 ? "e" : "w");
    }
    body.setVelocityX(w.dir * WALK_SPEED * speed);
    w.sprite.anims.timeScale = speed;
  }
}
