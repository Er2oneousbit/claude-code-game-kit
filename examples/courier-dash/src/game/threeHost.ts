// ---------------------------------------------------------------------------
// threeHost.ts
// Purpose : The shell's GameHost (src/shell/host.ts) on Three.js: the frame loop, the world that runs ("main" =
//           Play, "juice" = the juice demo) or the still backdrop behind the menus, pause, the frame cap, the
//           screenshot for F8, and errors in a world's update routed to the shell's crash screen.
// Usage   : const host = new ThreeHost(renderer, backdrop, { main: (a) => new Game(a), juice: (a) => new JuiceWorld(a) },
//                                      (err) => shell.crash(err));
//           host.onFirstFrame = () => shell.start(host);   host.run();   (src/main.ts)
// Notes   : A world is anything with a scene, a camera, update(dt) and resize(aspect); load(progress) is optional
//           (fetch models there: the loading screen shows its progress) and so is dispose(). Each start builds a
//           fresh world from its factory, so Play always begins from scratch, like a Phaser scene's create().
//           dt is real seconds, clamped to MAX_DT (a background tab does not teleport the world); game_speed and
//           hitstop are the world's business. THREE.Timer, not THREE.Clock (deprecated since r183); connect()
//           pauses time while the tab is hidden. The frame cap skips animation frames and hands their time to the
//           next drawn one. Three.js has no sound of its own: audio() keeps the master volume and mono setting and
//           applies them to a THREE.AudioListener once the game gives one (setListener).
//
// Pseudocode (per animation frame):
//   time += timer delta ; capped and too early -> return
//   world loaded and not paused -> world.update(dt)   (a throw -> onError, the shell shows its crash screen)
//   draw the world, else the backdrop ; first frame -> onFirstFrame ; a world's first frame -> its ready()
//   screenshots asked for -> canvas.toDataURL right after the draw (no preserveDrawingBuffer needed)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { Log } from "../core/log";
import type { GameHost, GameKey } from "../shell/host";

// ---- Tunables ----------------------------------------------------------------
const MAX_DT = 0.1; // s
const CAP_SLACK_S = 0.002; // a capped frame may come this early (rAF timestamps jitter)

export interface World {
  readonly scene: THREE.Scene;
  readonly camera: THREE.Camera;
  /** One step of real time in seconds (clamped). */
  update(dt: number): void;
  resize(aspect: number): void;
  /** Optional: fetch what the world needs; progress(0..1) feeds the loading screen. */
  load?(progress: (v: number) => void): Promise<void>;
  /** Optional: free what the world made beyond its scene's meshes (disposeScene does those). */
  dispose?(): void;
}

export type WorldFactory = (aspect: number) => World;

/** Frees every geometry, material and texture under scene (GPU memory is not garbage collected). */
export function disposeScene(scene: THREE.Object3D): void {
  scene.traverse((o) => {
    const mesh = o as THREE.Mesh;
    mesh.geometry?.dispose();
    const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const m of mats) {
      for (const v of Object.values(m)) if (v instanceof THREE.Texture) v.dispose();
      m.dispose();
    }
  });
}

export class ThreeHost implements GameHost {
  /** Called once, after the first frame is on screen (main.ts starts the shell there: BOOT_OK means it draws). */
  onFirstFrame: (() => void) | null = null;
  /** The player's master volume and mono setting (settings.audio), for the game's own sound code. */
  readonly sound = { master: 1, mono: false };

  private readonly timer = new THREE.Timer();
  private world: World | null = null;
  private key: GameKey | null = null;
  private loaded = false;
  private paused = false;
  private showBackdrop = true;
  private cap = 0;
  private pending = 0;
  private drawn = false;
  private ready: (() => void) | null = null;
  private shots: ((png: string) => void)[] = [];
  private listener: THREE.AudioListener | null = null;

  constructor(
    private readonly renderer: THREE.WebGLRenderer,
    private readonly backdropWorld: World,
    private readonly factories: Record<GameKey, WorldFactory>,
    private readonly onError: (err: unknown) => void,
  ) {
    this.timer.connect(document);
  }

  /** Starts the frame loop. */
  run(): void {
    this.renderer.setAnimationLoop((t) => this.frame(t));
  }

  /** The canvas width / height. */
  get aspect(): number {
    const size = this.renderer.getSize(new THREE.Vector2());
    return size.x / Math.max(size.y, 1);
  }

  resize(width: number, height: number): void {
    this.renderer.setSize(width, height);
    this.backdropWorld.resize(this.aspect);
    this.world?.resize(this.aspect);
  }

  // ---- GameHost ----------------------------------------------------------------
  start(key: GameKey, progress: (v: number) => void, ready: () => void): void {
    if (this.key) this.stop(this.key);
    const world = this.factories[key](this.aspect);
    this.world = world;
    this.key = key;
    this.loaded = false;
    this.paused = false;
    const go = () => {
      if (this.world !== world) return; // stopped while it loaded
      progress(1);
      this.loaded = true;
      this.ready = ready;
    };
    if (!world.load) go();
    else world.load(progress).then(go, (err: unknown) => this.onError(err));
  }

  pause(key: GameKey): void {
    if (this.key === key) this.paused = true;
  }

  resume(key: GameKey): void {
    if (this.key === key) this.paused = false;
  }

  stop(key: GameKey): void {
    if (this.key !== key || !this.world) return;
    const world = this.world;
    this.world = null;
    this.key = null;
    this.ready = null;
    try {
      world.dispose?.();
      disposeScene(world.scene);
    } catch (err) {
      Log.debug("core", `world ${key} not fully disposed: ${String(err)}`);
    }
  }

  backdrop(show: boolean): void {
    this.showBackdrop = show;
  }

  frameCap(fps: number): void {
    this.cap = fps > 0 ? fps : 0;
  }

  audio(master: number, mono: boolean): void {
    this.sound.master = master;
    this.sound.mono = mono;
    const l = this.listener;
    if (!l) return;
    l.setMasterVolume(master);
    try {
      const out = l.context.destination;
      out.channelCountMode = "explicit";
      out.channelInterpretation = "speakers";
      out.channelCount = mono ? 1 : Math.max(1, Math.min(2, out.maxChannelCount));
    } catch (err) {
      Log.debug("core", `mono audio not applied: ${String(err)}`);
    }
  }

  /** Hands the host the game's THREE.AudioListener, so the player's volume and mono setting reach it. */
  setListener(listener: THREE.AudioListener | null): void {
    this.listener = listener;
    this.audio(this.sound.master, this.sound.mono);
  }

  snapshot(done: (png: string) => void): void {
    this.shots.push(done);
  }

  // ---- the frame loop --------------------------------------------------------------
  private frame(timestamp: number): void {
    this.timer.update(timestamp);
    this.pending += this.timer.getDelta();
    if (this.cap > 0 && this.drawn && this.pending < 1 / this.cap - CAP_SLACK_S) return;
    const dt = Math.min(this.pending, MAX_DT);
    this.pending = 0;

    const world = this.world && this.loaded ? this.world : null;
    if (world && !this.paused) {
      try {
        world.update(dt);
      } catch (err) {
        this.onError(err); // the shell's crash screen; it stops this world
      }
    }
    const view = this.world && this.loaded ? this.world : this.showBackdrop ? this.backdropWorld : null;
    if (view) this.renderer.render(view.scene, view.camera);
    else this.renderer.clear();

    if (this.shots.length) {
      const png = this.renderer.domElement.toDataURL("image/png");
      for (const done of this.shots.splice(0)) done(png);
    }
    if (!this.drawn) {
      this.drawn = true;
      this.onFirstFrame?.();
    }
    if (view && view === this.world && this.ready) {
      const ready = this.ready;
      this.ready = null;
      ready();
    }
  }
}
