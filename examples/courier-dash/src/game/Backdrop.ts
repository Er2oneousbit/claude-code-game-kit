// ---------------------------------------------------------------------------
// Backdrop.ts
// Purpose : The still 3D picture behind the title and menus (the shell's HTML screens sit on top of the canvas).
// Usage   : new ThreeHost(renderer, new Backdrop(aspect), ...)   (src/main.ts); the host draws it while no world runs.
// Notes   : Static on purpose: `dev.py smoke --screenshot ... --compare baseline.png` needs the same pixels on every
//           run, so nothing here moves and update() does nothing. Swap in key art for your game.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import type { World } from "./threeHost";

const SKY = "#1d2b53";
const GROUND = "#2f3b4f";
const PILLARS = [-6, -3, 0, 3, 6]; // x of the pillars, m
const PILLAR_COLOURS = ["#223260", "#283a6c", "#2e4278", "#283a6c", "#223260"];

export class Backdrop implements World {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;

  constructor(aspect: number) {
    this.scene.background = new THREE.Color(SKY);
    this.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 100);
    this.camera.position.set(0, 3, 12);
    this.camera.lookAt(0, 1.5, 0);
    this.scene.add(new THREE.HemisphereLight("#cfe3ff", "#3a2f28", 1.2));
    const sun = new THREE.DirectionalLight("#ffffff", 1.5);
    sun.position.set(4, 8, 6);
    this.scene.add(sun);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshStandardMaterial({ color: GROUND }));
    ground.rotation.x = -Math.PI / 2;
    this.scene.add(ground);
    PILLARS.forEach((x, i) => {
      const h = 2 + (i % 2) * 1.5;
      const p = new THREE.Mesh(new THREE.BoxGeometry(1, h, 1), new THREE.MeshStandardMaterial({ color: PILLAR_COLOURS[i] }));
      p.position.set(x, h / 2, -2);
      this.scene.add(p);
    });
  }

  update(): void {
    // still on purpose (see Notes)
  }

  resize(aspect: number): void {
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
  }
}
