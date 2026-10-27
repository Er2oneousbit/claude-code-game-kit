// ---------------------------------------------------------------------------
// Game.ts
// Purpose : The game world: scene, camera, lights, and what moves each frame.
//           Rendering and the frame loop live in src/main.ts.
// Usage   : const game = new Game(aspect); each frame game.update(dt); renderer.render(game.scene, game.camera)
// Notes   : PROTOTYPE: a box circles a ground plane and the camera follows it with the
//           engine-free spring in src/core/follow.ts. Replace with your real world.
//           Units are meters, +Y is up (Three.js default), which is what Blender's glTF export gives.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { Follow3 } from "../core/follow";

const ORBIT_RADIUS = 4; // m
const ORBIT_SPEED = 0.6; // rad/s
const CAMERA_OFFSET = new THREE.Vector3(0, 4, 7); // m behind and above the box
const CAMERA_SMOOTH = 0.35; // s

export class Game {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private readonly box: THREE.Mesh;
  private readonly cam = new Follow3(CAMERA_SMOOTH);
  private time = 0;

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

  resize(aspect: number): void {
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
  }

  update(dt: number): void {
    this.time += dt;
    const a = this.time * ORBIT_SPEED;
    this.box.position.set(Math.cos(a) * ORBIT_RADIUS, 0.5, Math.sin(a) * ORBIT_RADIUS);
    this.box.rotation.y = -a;
    const p = this.cam.step(this.box.position.clone().add(CAMERA_OFFSET), dt);
    this.camera.position.set(p.x, p.y, p.z);
    this.camera.lookAt(this.box.position);
  }
}

// {{FOOTER}}
