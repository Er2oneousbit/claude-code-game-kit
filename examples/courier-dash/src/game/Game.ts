// ---------------------------------------------------------------------------
// Game.ts
// Purpose : The Three.js side of Courier Dash: builds the town from src/core/level.ts, steps the
//           engine-free simulation at a fixed rate, and draws it (courier, robot, parcels, camera,
//           HUD, sound, debug view).
// Usage   : const game = await Game.load(host, aspect, readOptions(location.search))
//           each frame: game.update(dt); renderer.render(game.scene, game.camera)
// Notes   : URL flags: ?debug (robot state, paths, collision boxes), &god (cannot be caught), &top (camera above the block),
//           &close or &close=robot (close-up camera),
//           &speed=N (simulation steps per frame), ?autoplay or ?autoplay=reckless (a bot plays),
//           &start=N (robot starts at patrol point N). Markers for `dev.py smoke`: RUN_WON,
//           CAUGHT, TIME_UP.
//           The simulation runs in fixed steps (TUNING.stepSeconds), so an autoplay run in the
//           browser plays out exactly like the same run in tests/scenario.test.ts.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): the ?debug path line draws (preallocated
//           buffer), and a restart clears held keys so a held direction does not start the new run.
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { version } from "../../package.json";
import { Bot, type BotMode } from "../core/bot";
import { Follow3 } from "../core/follow";
import { LEVEL, roadTiles } from "../core/level";
import { Log } from "../core/log";
import { Sim, type SimEvent } from "../core/sim";
import { type ModelLibrary, fitted, fittedLong, loadModels } from "./assets";
import { CourierView } from "./courierView";
import { Hud } from "./hud";
import { Controls } from "./input";
import { RobotView } from "./robotView";
import { Sfx } from "./sound";

const SKY = "#9fd3f0";
const LAWN = "#7cc36b";
const CAMERA_OFFSET = new THREE.Vector3(0, 11, 9); // m above and behind the courier
const CAMERA_LOOK = new THREE.Vector3(0, 0, -1.5); // look a little ahead
const CAMERA_SMOOTH = 0.2; // s
const MAX_STEPS_PER_FRAME = 12; // per unit of speed; beyond this the frame drops time
const TILE = 3; // m, road tile size
const PARCEL_SIZE = 0.7; // m
const STRAIGHT_TURNS = 0; // quarter turns that lay road-straight along x
const TREE_OVERSIZE = 1.4; // the canopy overhangs the trunk's collision box
const TOP_CAMERA = new THREE.Vector3(0, 34, 0.01); // &top: the whole block from above (debug)
const CLOSE_CAMERA = new THREE.Vector3(2.2, 2.4, 3.2); // &close or &close=robot: inspect facing and animation (debug)
const DEPOT_STACK = { x: 1.4, z: 0.4, step: 0.75 }; // delivered parcels pile up beside the flag
const PATH_MAX_POINTS = 64; // ?debug path line capacity (robot + smoothed A* points; real paths use a handful)
const PATH_Y = 0.15; // m, path line height above the ground

export type Options = {
  debug: boolean;
  god: boolean;
  top: boolean;
  close: "courier" | "robot" | null;
  speed: number;
  autoplay: BotMode | null;
  robotStart: number;
};

export function readOptions(search: string): Options {
  const q = new URLSearchParams(search);
  const auto = q.get("autoplay");
  return {
    debug: q.has("debug"),
    god: q.has("god"),
    top: q.has("top"),
    close: !q.has("close") ? null : q.get("close") === "robot" ? "robot" : "courier",
    speed: Math.max(1, Math.min(16, Number(q.get("speed")) || 1)),
    autoplay: auto === null ? null : auto === "reckless" ? "reckless" : "careful",
    robotStart: Number(q.get("start")) || 0,
  };
}

export class Game {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private sim!: Sim;
  private bot: Bot | null = null;
  private readonly courier: CourierView;
  private readonly robot: RobotView;
  private readonly parcels: THREE.Group[] = [];
  private readonly depotRing: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  private readonly controls = new Controls(window);
  private readonly sfx = new Sfx();
  private readonly hud: Hud;
  private readonly cam = new Follow3(CAMERA_SMOOTH);
  private readonly debugLines = new THREE.Group();
  private readonly pathLine = makePathLine();
  private acc = 0;
  private time = 0;
  private best: number | null = null;
  private lastTick = -1;

  static async load(host: HTMLElement, aspect: number, opts: Options): Promise<Game> {
    const lib = await loadModels();
    return new Game(host, aspect, opts, lib);
  }

  private constructor(host: HTMLElement, aspect: number, readonly opts: Options, lib: ModelLibrary) {
    this.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 200);
    this.scene.background = new THREE.Color(SKY);
    this.scene.fog = new THREE.Fog(SKY, 32, 70);
    this.addLights();
    this.buildTown(lib);

    this.courier = new CourierView(lib);
    this.robot = new RobotView(lib);
    this.scene.add(this.courier.root, this.robot.root, this.robot.cone);
    // the ambience loop needs a key press before the browser lets it play (gamepad-only players get it on a click)
    window.addEventListener("keydown", () => this.sfx.ambience());
    window.addEventListener("pointerdown", () => this.sfx.ambience());

    for (let i = 0; i < LEVEL.parcels.length; i++) {
      const g = fitted(lib.get("crate"), PARCEL_SIZE, PARCEL_SIZE);
      this.parcels.push(g);
      this.scene.add(g);
    }
    this.depotRing = new THREE.Mesh(
      new THREE.RingGeometry(1.5, 1.8, 48),
      new THREE.MeshBasicMaterial({ color: "#fbf7ee", transparent: true, opacity: 0.5, depthWrite: false }),
    );
    this.depotRing.rotation.x = -Math.PI / 2;
    this.depotRing.position.set(LEVEL.depot.x, 0.1, LEVEL.depot.z);
    const flag = fitted(lib.get("flag"), 1.2, 0.4);
    flag.position.set(LEVEL.depot.x, 0, LEVEL.depot.z);
    this.scene.add(this.depotRing, flag);

    if (opts.debug) {
      Log.enableChannel("ai");
      this.scene.add(this.debugLines, this.pathLine);
    }
    this.hud = new Hud(host, version);
    this.reset();
    Log.info("game", `ready v${version}${opts.autoplay ? ` AUTOPLAY ${opts.autoplay} start=${opts.robotStart}` : ""}`);
  }

  private addLights(): void {
    this.scene.add(new THREE.HemisphereLight("#d7ecff", "#5e7f4f", 1.5));
    const sun = new THREE.DirectionalLight("#fff6e5", 2.2);
    sun.position.set(8, 18, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -18, right: 18, top: 18, bottom: -18, near: 1, far: 50 });
    sun.shadow.bias = -0.0005;
    this.scene.add(sun);
  }

  /** Ground, roads, buildings and trees (each fitted into its level box), fences on the edge. */
  private buildTown(lib: ModelLibrary): void {
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(90, 90), new THREE.MeshStandardMaterial({ color: LAWN }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    const kinds = { straight: "road-straight", cross: "road-crossroad", end: "road-end" } as const;
    for (const t of roadTiles()) {
      const turns = t.kind === "end" ? 2 : STRAIGHT_TURNS + (t.alongX ? 0 : 1);
      const tile = fitted(lib.get(kinds[t.kind]), TILE, TILE, turns);
      tile.position.set(t.x, 0, t.z);
      this.scene.add(tile);
    }

    for (const b of LEVEL.blocks) {
      const oversize = b.model.startsWith("tree") ? TREE_OVERSIZE : 1;
      const obj = fitted(lib.get(b.model), b.w, b.d, b.turns ?? 0, oversize);
      obj.position.set(b.x, 0, b.z);
      this.scene.add(obj);
      if (this.opts.debug) this.debugLines.add(boxOutline(b.x, b.z, b.w, b.d));
    }

    const { minX, maxX, minZ, maxZ } = LEVEL.bounds;
    for (let s = minX + TILE / 2; s < maxX; s += TILE)
      for (const [x, z, turn] of [
        [s, minZ, 0],
        [s, maxZ, 0],
        [minX, s, 1],
        [maxX, s, 1],
      ] as const) {
        const fence = fittedLong(lib.get("fence"), TILE);
        fence.position.set(x, 0, z);
        fence.rotation.y = (turn * Math.PI) / 2;
        this.scene.add(fence);
      }
  }

  /** New run: fresh simulation, views back to the start. */
  private reset(): void {
    this.controls.clear();
    this.sim = new Sim({ god: this.opts.god, robotStart: this.opts.robotStart });
    this.bot = this.opts.autoplay ? new Bot(this.opts.autoplay) : null;
    this.acc = 0;
    this.lastTick = -1;
    this.courier.reset();
    const target = this.courierTarget();
    this.cam.snap(target.clone().add(CAMERA_OFFSET));
    this.camera.position.copy(target).add(CAMERA_OFFSET);
    this.camera.lookAt(target.add(CAMERA_LOOK));
  }

  resize(aspect: number): void {
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
  }

  update(dt: number): void {
    if (this.controls.consumeRestart()) this.reset();
    this.time += dt;
    const step = this.sim.t.stepSeconds;
    this.acc += dt * this.opts.speed;
    let n = 0;
    while (this.acc >= step && n < MAX_STEPS_PER_FRAME * this.opts.speed) {
      const input = this.bot ? this.bot.think(this.sim) : this.controls.read();
      for (const ev of this.sim.step(input)) this.onEvent(ev);
      this.acc -= step;
      n++;
    }
    if (n >= MAX_STEPS_PER_FRAME * this.opts.speed) this.acc = 0; // too slow: drop time, never spiral
    this.draw(dt);
  }

  private onEvent(ev: SimEvent): void {
    const s = this.sim;
    const tally = `${s.delivered}/${s.parcels.length}`;
    switch (ev.type) {
      case "START":
        Log.info("game", "RUN_START");
        break;
      case "PICKUP":
        this.sfx.play("pickup");
        Log.info("game", `PICKUP parcel ${ev.parcel}`);
        break;
      case "DELIVERED":
        this.sfx.play("delivered");
        Log.info("game", `DELIVERED ${tally}`);
        break;
      case "CAUGHT":
        this.sfx.play("caught");
        Log.info("game", `CAUGHT after ${s.elapsed.toFixed(1)} s, delivered ${tally}`);
        break;
      case "TIME_UP":
        Log.info("game", `TIME_UP delivered ${tally}`);
        break;
      case "RUN_WON":
        this.best = Math.max(this.best ?? 0, s.timeLeft);
        Log.info("game", `RUN_WON with ${s.timeLeft.toFixed(1)} s left`);
        break;
      case "LOW_TIME":
        break;
      default:
        Log.debug("ai", `robot ${ev.type} (now ${s.robot.state})`);
    }
  }

  private courierTarget(): THREE.Vector3 {
    return new THREE.Vector3(this.sim.courier.pos.x, 0, this.sim.courier.pos.z);
  }

  private draw(dt: number): void {
    const s = this.sim;
    this.courier.sync(s, dt);
    this.robot.sync(s, this.time);

    s.parcels.forEach((state, i) => {
      const g = this.parcels[i];
      g.visible = state !== "carried";
      if (state === "waiting") {
        const p = LEVEL.parcels[i];
        g.position.set(p.x, 0.1 + Math.abs(Math.sin(this.time * 2 + i)) * 0.25, p.z);
        g.rotation.y = this.time * 0.8 + i;
      } else if (state === "delivered") {
        const k = s.parcels.slice(0, i).filter((x) => x === "delivered").length;
        g.position.set(LEVEL.depot.x + DEPOT_STACK.x + (k % 3) * DEPOT_STACK.step, Math.floor(k / 3) * PARCEL_SIZE, LEVEL.depot.z + DEPOT_STACK.z);
        g.rotation.y = 0;
      }
    });
    this.depotRing.material.opacity = s.carrying !== null ? 0.55 + Math.sin(this.time * 6) * 0.3 : 0.25;

    // Ticks in the last seconds (pillar 2: every second counts).
    const whole = Math.ceil(s.timeLeft);
    if (s.outcome === "playing" && s.started && s.timeLeft <= s.t.run.lowTimeSeconds && whole !== this.lastTick) {
      this.lastTick = whole;
      this.sfx.play("tick");
    }

    const target = this.courierTarget();
    const p = this.cam.step(target.clone().add(CAMERA_OFFSET), dt);
    this.camera.position.set(p.x, p.y, p.z);
    this.camera.lookAt(target.add(CAMERA_LOOK));
    if (this.opts.top) {
      this.camera.position.copy(TOP_CAMERA);
      this.camera.lookAt(0, 0, 0);
    } else if (this.opts.close) {
      const at = this.opts.close === "robot" ? s.robot.pos : s.courier.pos;
      this.camera.position.set(at.x + CLOSE_CAMERA.x, CLOSE_CAMERA.y, at.z + CLOSE_CAMERA.z);
      this.camera.lookAt(at.x, 0.6, at.z);
    }

    let debug = "";
    if (this.opts.debug) {
      const r = s.robot;
      const path = r.path.length ? [r.pos, ...r.path] : [];
      const attr = this.pathLine.geometry.getAttribute("position") as THREE.BufferAttribute;
      const n = Math.min(path.length, PATH_MAX_POINTS);
      for (let i = 0; i < n; i++) attr.setXYZ(i, path[i].x, PATH_Y, path[i].z);
      attr.needsUpdate = true;
      this.pathLine.geometry.setDrawRange(0, n);
      debug = `robot ${r.state} ${r.stateTime.toFixed(1)}s sees=${r.sees} | courier stamina ${s.courier.stamina.toFixed(2)}${this.opts.god ? " | GOD" : ""}${this.bot ? ` | bot ${this.bot.mode}` : ""}`;
    }
    this.hud.update(s, this.best, debug);
  }
}

/**
 * The ?debug robot path. setFromPoints cannot grow an attribute created empty (Three r186 warns
 * and draws nothing), so the buffer is allocated once at full size and only the draw range moves.
 */
function makePathLine(): THREE.Line {
  const geometry = new THREE.BufferGeometry();
  const attr = new THREE.BufferAttribute(new Float32Array(PATH_MAX_POINTS * 3), 3);
  attr.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute("position", attr);
  geometry.setDrawRange(0, 0);
  const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: "#ff3bd4" }));
  line.frustumCulled = false; // the bounding sphere is computed once from the empty buffer
  return line;
}

function boxOutline(x: number, z: number, w: number, d: number): THREE.LineSegments {
  const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(w, 0.5, d));
  const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: "#ff3bd4" }));
  line.position.set(x, 0.25, z);
  return line;
}
