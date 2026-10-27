// ---------------------------------------------------------------------------
// courierView.ts
// Purpose : Draws the courier from the simulation: position, facing, the carried parcel, and
//           which animation plays (idle, walk, sprint, pick-up, die, emote-yes, emote-no).
// Usage   : const view = new CourierView(lib); scene.add(view.root); each frame view.sync(sim, dt)
// Notes   : The model is skinned, so it is used once (no clone). AnimationMixer crossfades between
//           clips by name; clip names come from the Kenney file (`--list-actions` in
//           tools/blender/render_sprites.py, or validate_asset.py's report).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import type { Sim } from "../core/sim";
import { type ModelLibrary, fitted, fittedHeight } from "./assets";

const HEIGHT = 1.3; // m, the courier on screen
const CRATE_SIZE = 0.6; // m, the carried parcel
const FADE = 0.15; // s, animation crossfade
const IDLE_BELOW = 0.4; // m/s
const MODEL_YAW = 0; // the Kenney character faces +z

type Clip = "idle" | "walk" | "sprint" | "pick-up" | "die" | "emote-yes" | "emote-no";
const ONE_SHOTS: Clip[] = ["pick-up", "die"];

export class CourierView {
  readonly root = new THREE.Group();
  private readonly body: THREE.Group;
  private readonly mixer: THREE.AnimationMixer;
  private readonly actions = new Map<Clip, THREE.AnimationAction>();
  private readonly crate: THREE.Group;
  private current: Clip | null = null;

  constructor(lib: ModelLibrary) {
    const gltf = lib.gltf("courier");
    this.body = fittedHeight(gltf.scene, HEIGHT, false);
    this.root.add(this.body);
    this.mixer = new THREE.AnimationMixer(gltf.scene);
    for (const name of ["idle", "walk", "sprint", "pick-up", "die", "emote-yes", "emote-no"] as Clip[]) {
      const clip = THREE.AnimationClip.findByName(gltf.animations, name);
      if (!clip) throw new Error(`courier.glb has no animation "${name}"`);
      const action = this.mixer.clipAction(clip);
      if (ONE_SHOTS.includes(name)) {
        action.setLoop(THREE.LoopOnce, 1);
        action.clampWhenFinished = true;
      }
      this.actions.set(name, action);
    }
    this.crate = fitted(lib.get("crate"), CRATE_SIZE, CRATE_SIZE);
    this.crate.position.y = HEIGHT + 0.05;
    this.root.add(this.crate);
    this.reset();
  }

  reset(): void {
    this.mixer.stopAllAction();
    this.current = null;
    this.play("idle");
  }

  sync(sim: Sim, dt: number): void {
    const c = sim.courier;
    this.root.position.set(c.pos.x, 0, c.pos.z);
    this.root.rotation.y = c.yaw + MODEL_YAW;
    this.crate.visible = sim.carrying !== null;

    let clip: Clip;
    if (sim.outcome === "caught") clip = "die";
    else if (sim.outcome === "won") clip = "emote-yes";
    else if (sim.outcome === "timeup") clip = "emote-no";
    else if (c.pause > 0) clip = "pick-up";
    else if (sim.speed < IDLE_BELOW) clip = "idle";
    else clip = c.sprinting ? "sprint" : "walk";
    this.play(clip);
    if (clip === "walk") this.actions.get("walk")!.timeScale = Math.max(0.6, sim.speed / sim.t.courier.walkSpeed);
    this.mixer.update(dt);
  }

  private play(clip: Clip): void {
    if (clip === this.current) return;
    const next = this.actions.get(clip)!;
    next.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(FADE).play();
    if (this.current) this.actions.get(this.current)!.fadeOut(FADE);
    this.current = clip;
  }
}
