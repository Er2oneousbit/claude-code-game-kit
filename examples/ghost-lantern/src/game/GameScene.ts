// ---------------------------------------------------------------------------
// GameScene.ts
// Purpose : The slice: three dark rooms, the wizard and the lantern, oil, the key
//           chest, the exit, and ghosts driven by utility AI (SOP-14).
// Usage   : Registered in src/main.ts. URL flags: ?debug (paths, scores, I = infinite
//           oil, G = freeze ghosts), ?autoplay (a bot plays: scenario check and smoke).
// Notes   : Engine side only. Decisions live in src/core/ghostBrain.ts, paths in
//           src/core/astar.ts, lantern rules in src/core/lantern.ts, numbers in tuning.ts.
//           Positions are in tiles (floats); pixels only when drawing. Sounds: ElevenLabs (A-0004 to A-0008),
//           one-shots plus a haunted-house ambience loop.
//
// Pseudocode (update):
//   read input (or the bot) -> move the player with wall collision -> burn oil
//   pickups: oil refills, the chest gives the key, the exit with the key wins
//   each ghost: every thinkEvery s sense (distance, light, memory) -> pick action
//               -> new A* path when the action changes or every repathEvery s
//               -> follow the path at that action's speed -> caught if close
//   redraw the darkness around the lantern, push the HUD numbers
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { findPath } from "../core/astar";
import { pickAction, scoreActions, type GhostAction, type Scores } from "../core/ghostBrain";
import { cellOf, dist, Grid, moveBox, type Cell, type Vec } from "../core/grid";
import { Lantern } from "../core/lantern";
import { Log } from "../core/log";
import { Rng } from "../core/rng";
import { separate } from "../core/separation";
import { LEVEL } from "./level";
import { BRAIN, GHOST, LANTERN, OIL_PICKUP, PLAYER, SEED, TILE_PX, TILES, ZOOM } from "./tuning";

const AMBIENCE_VOLUME = 0.35;   // under the one-shots

type Ghost = {
  id: number;
  sprite: Phaser.GameObjects.Sprite;
  pos: Vec;
  action: GhostAction;
  scores: Scores;
  path: Cell[];
  thinkIn: number;
  repathIn: number;
  memory: number;
};

type Pickup = { cell: Cell; sprite: Phaser.GameObjects.Sprite };

const ACTION_TINT: Record<GhostAction, number> = { chase: 0x7fe6ff, flee: 0xffffff, wander: 0xffffff };
const DARKNESS = "rgba(11, 11, 20, 0.94)";

export type HudState = { oil: number; bright: boolean; hasKey: boolean; message: string; time: number; debug: string[] };

const center = (c: Cell): Vec => ({ x: c.x + 0.5, y: c.y + 0.5 });
const px = (tiles: number): number => tiles * TILE_PX;

export class GameScene extends Phaser.Scene {
  private grid!: Grid;
  private rng!: Rng;
  private lantern!: Lantern;
  private player!: Phaser.GameObjects.Sprite;
  private playerPos!: Vec;
  private ghosts: Ghost[] = [];
  private oils: Pickup[] = [];
  private chest!: Pickup;
  private exit!: Cell;
  private hasKey = false;
  private state: "playing" | "won" | "caught" = "playing";
  private elapsed = 0;
  private dark!: Phaser.Textures.CanvasTexture;
  private debugGfx?: Phaser.GameObjects.Graphics;
  private debugText: Phaser.GameObjects.Text[] = [];
  private keys!: Record<string, Phaser.Input.Keyboard.Key>;
  private flags = { debug: false, autoplay: false, botDark: false, infiniteOil: false, frozen: false };

  constructor() {
    super("game");
  }

  preload(): void {
    this.load.spritesheet("tiles", "assets/art/tilemap_packed.png", { frameWidth: 16, frameHeight: 16 });
    this.load.audio("oil", "assets/audio/oil-refill.mp3");
    this.load.audio("key", "assets/audio/key-found.mp3");
    this.load.audio("win", "assets/audio/door-escape.mp3");
    this.load.audio("caught", "assets/audio/ghost-caught.mp3");
    this.load.audio("ambience", "assets/audio/haunted-ambience.wav");
  }

  create(): void {
    const params = new URLSearchParams(location.search);
    // ?autoplay: the bot brightens when a ghost is near. ?autoplay=dark: same route, never brightens
    // (scenario pair: the lantern must be what saves you, VERTICAL_SLICE assumption 2)
    this.flags = { debug: params.has("debug"), autoplay: params.has("autoplay"), botDark: params.get("autoplay") === "dark", infiniteOil: false, frozen: false };
    this.grid = Grid.parse(LEVEL);
    this.rng = new Rng(Number(params.get("seed") ?? SEED)); // ?seed=N replays a run (SOP-14: seeded randomness)
    this.lantern = new Lantern(LANTERN);
    this.hasKey = false;
    this.state = "playing";
    this.elapsed = 0;
    this.ghosts = [];
    this.oils = [];
    this.debugText = [];

    this.buildMap();
    this.buildActors();
    this.buildDarkness();
    this.setupInput();
    this.setupCamera();
    if (this.flags.debug) {
      this.debugGfx = this.add.graphics().setDepth(30);
      Log.enableChannel("ai");
    }
    if (!this.scene.isActive("hud")) this.scene.launch("hud");
    this.startAmbience();
    Log.info("core", `BOOT_OK Ghost Lantern${this.flags.autoplay ? ` (autoplay${this.flags.botDark ? ", dark" : ""})` : ""}${this.flags.debug ? " (debug)" : ""}`);
  }

  // One ambience loop for the whole session: Phaser keeps sounds across scene restarts, and a browser keeps audio
  // locked until the first key press, so the loop starts on unlock (the headless smoke browser never unlocks: fine)
  private startAmbience(): void {
    const start = () => {
      if (!this.sound.get("ambience")) this.sound.add("ambience", { loop: true, volume: AMBIENCE_VOLUME }).play();
    };
    if (this.sound.locked) this.sound.once(Phaser.Sound.Events.UNLOCKED, start);
    else start();
  }

  // ---- building ----------------------------------------------------------------
  private buildMap(): void {
    const data = LEVEL.map((row) => [...row].map((ch) => (ch === "#" ? TILES.wall : ch === "X" ? TILES.exit : TILES.floor)));
    const map = this.make.tilemap({ data, tileWidth: TILE_PX, tileHeight: TILE_PX });
    const tileset = map.addTilesetImage("tiles", "tiles", TILE_PX, TILE_PX, 0, 0);
    if (!tileset) throw new Error("tileset 'tiles' failed to load");
    map.createLayer(0, tileset, 0, 0);
    this.exit = this.grid.find("X")[0];
  }

  private sprite(frame: number, at: Vec, depth: number): Phaser.GameObjects.Sprite {
    return this.add.sprite(px(at.x), px(at.y), "tiles", frame).setDepth(depth);
  }

  private buildActors(): void {
    for (const c of this.grid.find("o")) this.oils.push({ cell: c, sprite: this.sprite(TILES.oil, center(c), 5) });
    const k = this.grid.find("K")[0];
    this.chest = { cell: k, sprite: this.sprite(TILES.key, center(k), 5) };
    this.playerPos = center(this.grid.find("P")[0]);
    this.player = this.sprite(TILES.wizard, this.playerPos, 10);
    this.grid.find("G").forEach((c, id) => {
      this.ghosts.push({
        id, sprite: this.sprite(TILES.ghost, center(c), 25), pos: center(c), action: "wander",
        scores: { chase: 0, flee: 0, wander: BRAIN.wanderBase }, path: [], thinkIn: id * 0.08, repathIn: 0, memory: 0,
      });
    });
  }

  private buildDarkness(): void {
    const w = px(this.grid.width), h = px(this.grid.height);
    if (this.textures.exists("dark")) this.textures.remove("dark");
    const tex = this.textures.createCanvas("dark", w, h);
    if (!tex) throw new Error("could not create the darkness canvas");
    this.dark = tex;
    this.add.image(0, 0, "dark").setOrigin(0, 0).setDepth(20);
  }

  private setupInput(): void {
    const kb = this.input.keyboard!;
    this.keys = kb.addKeys("W,A,S,D,UP,DOWN,LEFT,RIGHT,SPACE,SHIFT,R,I,G") as Record<string, Phaser.Input.Keyboard.Key>;
  }

  private setupCamera(): void {
    const cam = this.cameras.main;
    cam.setBounds(0, 0, px(this.grid.width), px(this.grid.height));
    cam.setZoom(ZOOM);
    cam.startFollow(this.player, true, 0.15, 0.15);
    cam.setBackgroundColor("#0b0b14");
  }

  // ---- frame -------------------------------------------------------------------
  update(_time: number, deltaMs: number): void {
    const dt = Math.min(deltaMs / 1000, 0.05);
    if (Phaser.Input.Keyboard.JustDown(this.keys.R)) {
      this.scene.restart();
      return;
    }
    if (this.flags.debug && Phaser.Input.Keyboard.JustDown(this.keys.I)) this.flags.infiniteOil = !this.flags.infiniteOil;
    if (this.flags.debug && Phaser.Input.Keyboard.JustDown(this.keys.G)) this.flags.frozen = !this.flags.frozen;
    if (this.state === "playing") {
      this.elapsed += dt;
      const intent = this.flags.autoplay ? this.botIntent() : this.playerIntent();
      this.movePlayer(intent.move, dt);
      this.lantern.update(dt, intent.bright);
      if (this.flags.infiniteOil) this.lantern.refill(LANTERN.maxOil);
      this.checkPickups();
      if (!this.flags.frozen && this.state === "playing") { // escaping this frame ends the run before any catch
        for (const g of this.ghosts) {
          this.updateGhost(g, dt);
          if (this.state !== "playing") break; // one catch per run: no second sound or log line
        }
        this.separateGhosts();
      }
    }
    this.drawDarkness();
    this.drawDebug();
    this.events.emit("hud", {
      oil: this.lantern.fraction(), bright: this.lantern.bright, hasKey: this.hasKey, time: this.elapsed,
      message: this.state === "won" ? "You escaped!  R to play again" : this.state === "caught" ? "Caught!  R to try again" : "",
      debug: this.flags.debug ? this.debugLines() : [],
    } satisfies HudState);
  }

  private playerIntent(): { move: Vec; bright: boolean } {
    const k = this.keys;
    const x = (k.D.isDown || k.RIGHT.isDown ? 1 : 0) - (k.A.isDown || k.LEFT.isDown ? 1 : 0);
    const y = (k.S.isDown || k.DOWN.isDown ? 1 : 0) - (k.W.isDown || k.UP.isDown ? 1 : 0);
    return { move: { x, y }, bright: k.SPACE.isDown || k.SHIFT.isDown };
  }

  private movePlayer(dir: Vec, dt: number): void {
    const len = Math.hypot(dir.x, dir.y);
    if (len > 0) {
      const step = (PLAYER.speed * dt) / len;
      this.playerPos = moveBox(this.grid, this.playerPos, { x: dir.x * step, y: dir.y * step }, PLAYER.half);
      if (dir.x !== 0) this.player.setFlipX(dir.x < 0);
    }
    this.player.setPosition(px(this.playerPos.x), px(this.playerPos.y));
  }

  private checkPickups(): void {
    for (const o of this.oils) {
      if (o.sprite.visible && dist(this.playerPos, center(o.cell)) < 0.6) {
        o.sprite.setVisible(false);
        this.lantern.refill(OIL_PICKUP);
        this.sound.play("oil");
        Log.info("game", `OIL picked up (${Math.round(this.lantern.oil)})`);
      }
    }
    if (!this.hasKey && dist(this.playerPos, center(this.chest.cell)) < 0.7) {
      this.hasKey = true;
      this.chest.sprite.setAlpha(0.4);
      this.sound.play("key");
      Log.info("game", `GOT_KEY at ${this.elapsed.toFixed(1)} s`);
    }
    if (this.hasKey && dist(this.playerPos, center(this.exit)) < 0.75) {
      this.state = "won";
      this.sound.play("win");
      Log.info("game", `ESCAPED in ${this.elapsed.toFixed(1)} s with ${Math.round(this.lantern.oil)} oil`);
    }
  }

  // ---- ghosts (perception -> decision -> movement, SOP-14) -----------------------
  private updateGhost(g: Ghost, dt: number): void {
    const d = dist(g.pos, this.playerPos);
    const light = this.lantern.lightAt(d);
    g.memory = d < BRAIN.senseRange && light < 0.3 ? 1 : Math.max(0, g.memory - dt / GHOST.memorySeconds);

    g.thinkIn -= dt;
    g.repathIn -= dt;
    if (g.thinkIn <= 0) {
      g.thinkIn = Math.max(g.thinkIn + GHOST.thinkEvery, 0); // keep the leftover: same rhythm at any frame rate
      g.scores = scoreActions({ distance: d, light, memory: g.memory }, BRAIN);
      const next = pickAction(g.scores, g.action, BRAIN.inertia);
      if (next !== g.action) {
        Log.debug("ai", `ghost ${g.id}: ${g.action} -> ${next}`);
        g.action = next;
        g.repathIn = 0;
      }
    }
    if (g.repathIn <= 0 || g.path.length === 0) {
      g.repathIn = Math.max(g.repathIn + GHOST.repathEvery, 0);
      g.path = findPath(this.grid, cellOf(g.pos), this.targetFor(g)) ?? [];
    }
    this.followPath(g, GHOST.speed[g.action] * dt);

    const lit = light > 0.05;
    g.sprite.setPosition(px(g.pos.x), px(g.pos.y)).setTint(ACTION_TINT[g.action]);
    g.sprite.setAlpha(g.action === "flee" ? 0.55 : lit ? 1 : 0.35);
    if (g.action !== "flee" && light < GHOST.shieldLight && d < GHOST.catchDistance) this.caught(g);
  }

  private targetFor(g: Ghost): Cell {
    const here = cellOf(g.pos);
    if (g.action === "chase") return cellOf(this.playerPos);
    if (g.action === "flee") {
      const options = this.grid.cellsNear(here, GHOST.fleeRadius);
      let best = here, bestD = -1;
      const taken = this.ghosts.filter((o) => o !== g && o.path.length > 0).map((o) => o.path[o.path.length - 1]);
      for (const c of options) {
        const crowd = taken.filter((t) => Math.abs(t.x - c.x) + Math.abs(t.y - c.y) <= 2).length;
        const dc = dist(center(c), this.playerPos) - crowd * GHOST.crowdPenalty + this.rng.next() * 0.3;
        if (dc > bestD) [best, bestD] = [c, dc];
      }
      return best;
    }
    return this.rng.pick(this.grid.cellsNear(here, GHOST.wanderRadius));
  }

  private followPath(g: Ghost, step: number): void {
    while (step > 0 && g.path.length > 0) {
      const target = center(g.path[0]);
      const d = dist(g.pos, target);
      if (d <= step) {
        g.pos = target;
        step -= d;
        g.path.shift();
      } else {
        g.pos = { x: g.pos.x + ((target.x - g.pos.x) / d) * step, y: g.pos.y + ((target.y - g.pos.y) / d) * step };
        step = 0;
      }
    }
  }

  /** Steering separation after the moves: ghosts push apart, never into walls. */
  private separateGhosts(): void {
    const pushes = separate(this.ghosts.map((g) => g.pos), GHOST.separation);
    this.ghosts.forEach((g, i) => {
      g.pos = moveBox(this.grid, g.pos, pushes[i], 0.3);
      // A fleeing ghost never overlaps the lantern bearer: it would read as "why did it not catch me?" (pillar 1)
      const d = dist(g.pos, this.playerPos);
      if (g.action === "flee" && d < GHOST.separation) {
        const ux = d > 1e-6 ? (g.pos.x - this.playerPos.x) / d : 1, uy = d > 1e-6 ? (g.pos.y - this.playerPos.y) / d : 0;
        g.pos = moveBox(this.grid, g.pos, { x: ux * (GHOST.separation - d), y: uy * (GHOST.separation - d) }, 0.3);
      }
      g.sprite.setPosition(px(g.pos.x), px(g.pos.y));
    });
  }

  private caught(g: Ghost): void {
    if (this.state !== "playing") return;
    this.state = "caught";
    this.sound.play("caught");
    this.cameras.main.shake(250, 0.01);
    Log.info("game", `CAUGHT by ghost ${g.id} at ${this.elapsed.toFixed(1)} s`);
  }

  // ---- drawing -----------------------------------------------------------------
  private drawDarkness(): void {
    const ctx = this.dark.context;
    const w = this.dark.width, h = this.dark.height;
    const x = px(this.playerPos.x), y = px(this.playerPos.y), r = px(this.lantern.radius());
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = DARKNESS;
    ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = "destination-out";
    const hole = ctx.createRadialGradient(x, y, r * 0.25, x, y, r);
    hole.addColorStop(0, "rgba(0,0,0,1)");
    hole.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = hole;
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
    ctx.globalCompositeOperation = "source-over";
    const glow = ctx.createRadialGradient(x, y, 0, x, y, r);
    glow.addColorStop(0, "rgba(255, 210, 122, 0.18)");
    glow.addColorStop(1, "rgba(255, 210, 122, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
    this.dark.refresh();
  }

  private drawDebug(): void {
    if (!this.debugGfx) return;
    const gfx = this.debugGfx.clear();
    this.debugText.forEach((t) => t.destroy());
    this.debugText = [];
    gfx.lineStyle(1, 0xffd27a, 0.6).strokeCircle(px(this.playerPos.x), px(this.playerPos.y), px(BRAIN.senseRange));
    for (const g of this.ghosts) {
      gfx.lineStyle(1, ACTION_TINT[g.action], 0.9).beginPath().moveTo(px(g.pos.x), px(g.pos.y));
      for (const c of g.path) gfx.lineTo(px(c.x + 0.5), px(c.y + 0.5));
      gfx.strokePath();
      this.debugText.push(this.add.text(px(g.pos.x) - 2, px(g.pos.y) - 14, String(g.id),
        { fontFamily: "monospace", fontSize: "6px", color: "#ffd27a", resolution: 4 }).setDepth(31));
    }
  }

  /** One line per ghost for the HUD: id, action and the three utility scores. */
  private debugLines(): string[] {
    const flags = `${this.flags.infiniteOil ? "  [I] infinite oil" : ""}${this.flags.frozen ? "  [G] frozen" : ""}`;
    return [
      `ghost  action  chase  flee  wander${flags}`,
      ...this.ghosts.map((g) => {
        const s = g.scores;
        return `G${g.id}     ${g.action.padEnd(6)}  ${s.chase.toFixed(2)}   ${s.flee.toFixed(2)}  ${s.wander.toFixed(2)}`;
      }),
    ];
  }

  // ---- autoplay bot (SOP-14 step 6: scenario check) -----------------------------
  private botIntent(): { move: Vec; bright: boolean } {
    const here = cellOf(this.playerPos);
    const oilLeft = this.oils.filter((o) => o.sprite.visible);
    let goal: Cell;
    if (this.lantern.fraction() < 0.35 && oilLeft.length > 0) {
      goal = oilLeft.reduce((a, b) => (dist(center(a.cell), this.playerPos) < dist(center(b.cell), this.playerPos) ? a : b)).cell;
    } else {
      goal = this.hasKey ? this.exit : this.chest.cell;
    }
    const path = findPath(this.grid, here, goal) ?? [];
    const next = path.length > 0 ? center(path[0]) : center(goal);
    // Burst the light only when a ghost is really close: ghosts hover at the edge of the light, and
    // holding it bright drains the oil (playtest 1: the bot ran dry at 14 s and was caught)
    const ghostNear = this.ghosts.some((g) => dist(g.pos, this.playerPos) < 2.2);
    return { move: { x: next.x - this.playerPos.x, y: next.y - this.playerPos.y }, bright: ghostNear && !this.flags.botDark };
  }
}
