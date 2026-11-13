// ---------------------------------------------------------------------------
// Game.ts
// Purpose : The play world: what "Play" on the main menu starts (after the loading screen). Scene, camera, lights,
//           and what moves each frame. The frame loop and the menus live elsewhere (src/game/threeHost.ts,
//           src/shell/).
// Usage   : Registered in src/main.ts as world "main"; the shell starts, pauses and stops it through the host.
// Notes   : PROTOTYPE: a box circles a ground plane and the camera follows it with the engine-free spring in
//           src/core/follow.ts. Replace with your real world. Read the player's settings through shell.settings
//           (game_speed scales dt here) and input through shell.input (isDown / takePress with action names from
//           settings.input.bindings; stick() and triggers() for analog control, heldActions() for everything held).
//           HUD text drawn in the 3D view (a DotworkText, a canvas label) follows the player's ui_scale and
//           text_scale only through hudFontPx(base, shell.settings) (src/core/hud.ts), redone in shell.onLook()
//           (#309); the shell's own HUD bar is HTML and follows them already.
//           Units are meters, +Y is up (Three.js default), which is what Blender's glTF export gives.
//           BOOT_OK is logged by the shell once the title screen is up (dev.py smoke waits for it).
//           Dotwork art: load() reads every public/assets/dotwork/*.assets.json (src/game/dotwork/) and the
//           showcase puts the first map, a walking character, a prop and a font label at the centre (#56).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): a world the shell runs (game_speed, the crash drive)
//           (#175)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): Dotwork packs load and show (#56)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): where HUD text gets ui_scale and text_scale (#309)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { Follow3 } from "../core/follow";
import { shell } from "../shell/app";
import { DOTWORK_MANIFESTS } from "./dotwork/boot";
import { DotworkLibrary } from "./dotwork/library";
import { DotworkShowcase } from "./dotwork/showcase";
import type { World } from "./threeHost";

const ORBIT_RADIUS = 4; // m
const ORBIT_SPEED = 0.6; // rad/s
const CAMERA_OFFSET = new THREE.Vector3(0, 4, 7); // m behind and above the box
const CAMERA_SMOOTH = 0.35; // s

export class Game implements World {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private readonly box: THREE.Mesh;
  private readonly cam = new Follow3(CAMERA_SMOOTH);
  private time = 0;
  private dotwork: DotworkLibrary | null = null;
  private showcase: DotworkShowcase | null = null;

  constructor(aspect: number) {
    this.scene.background = new THREE.Color("#10131c");
    this.camera = new THREE.PerspectiveCamera(60, aspect, 0.1, 200);

    this.scene.add(new THREE.HemisphereLight("#cfe3ff", "#3a2f28", 1.2));
    const sun = new THREE.DirectionalLight("#ffffff", 2.0);
    sun.position.set(5, 10, 4);
    sun.castShadow = true;
    this.scene.add(sun);

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.MeshStandardMaterial({ color: "#2f3b4f" }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    this.box = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: "#f2c14e" }));
    this.box.position.set(ORBIT_RADIUS, 0.5, 0);
    this.box.castShadow = true;
    this.scene.add(this.box);

    this.cam.snap(this.box.position.clone().add(CAMERA_OFFSET));
    this.camera.position.copy(this.box.position).add(CAMERA_OFFSET);
    this.camera.lookAt(this.box.position);
  }

  /** The game's Dotwork packs (none: nothing to fetch). */
  async load(progress: (v: number) => void): Promise<void> {
    if (!DOTWORK_MANIFESTS.length) return;
    this.dotwork = await DotworkLibrary.load(DOTWORK_MANIFESTS, progress);
    this.showcase = new DotworkShowcase(this.dotwork);
    this.scene.add(this.showcase);
  }

  dispose(): void {
    this.showcase?.dispose();
    this.dotwork?.dispose();
  }

  resize(aspect: number): void {
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
  }

  update(realDt: number): void {
    if (shell.plantedCrash) {
      shell.plantedCrash = false;
      throw new Error("planted crash (dev.py smoke --drive crash)"); // proves the crash hook end to end
    }
    const dt = realDt * shell.settings.access.game_speed;
    this.time += dt;
    const a = this.time * ORBIT_SPEED;
    this.box.position.set(Math.cos(a) * ORBIT_RADIUS, 0.5, Math.sin(a) * ORBIT_RADIUS);
    this.box.rotation.y = -a;
    const p = this.cam.step(this.box.position.clone().add(CAMERA_OFFSET), dt);
    this.camera.position.set(p.x, p.y, p.z);
    this.camera.lookAt(this.box.position);
    this.showcase?.update(dt, this.camera);
  }
}

// {{FOOTER}}
