// ---------------------------------------------------------------------------
// robotView.ts
// Purpose : Makes the robot readable (pillar 1): body glowing in its state color, a "!" or "?" above it, and
//           its sight cone drawn on the ground exactly as far as it really sees.
// Usage   : const view = new RobotView(lib); scene.add(view.root, view.cone); view.sync(sim, time)
// Notes   : The cone is rebuilt each frame from rays against the same boxes the simulation
//           uses (rayDistance in src/core/geom.ts), so a building really hides you where the
//           cone stops. Colors come from the color bible in docs/CONCEPTS.md.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { rayDistance } from "../core/geom";
import type { RobotState } from "../core/robot";
import type { Sim } from "../core/sim";
import { type ModelLibrary, fitted } from "./assets";

export const STATE_COLORS: Record<RobotState, string> = {
  patrol: "#59d8ff",
  return: "#59d8ff",
  alert: "#ffb020",
  search: "#ffb020",
  chase: "#ff3b3b",
};
const FOOTPRINT = 1.4; // m
const MODEL_YAW = 0; // rover model forward
const CONE_RAYS = 40;
const CONE_Y = 0.09; // m, just above the road tiles
const CONE_OPACITY: Record<RobotState, number> = { patrol: 0.2, return: 0.2, alert: 0.3, search: 0.3, chase: 0.38 };
const TELL_Y = 2.3; // m, the "!" above the robot
const GLOW = 0.45; // emissive strength of the state color on the body

function tellTexture(text: string, color: string): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  g.font = "bold 110px sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.lineWidth = 12;
  g.strokeStyle = "#1d2433";
  g.strokeText(text, 64, 70);
  g.fillStyle = color;
  g.fillText(text, 64, 70);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export class RobotView {
  readonly root = new THREE.Group();
  readonly cone: THREE.Mesh<THREE.BufferGeometry, THREE.MeshBasicMaterial>;
  private readonly body: THREE.Group;
  private readonly glow: THREE.MeshStandardMaterial[] = [];
  private readonly tell: THREE.Sprite;
  private readonly tells: Record<"alert" | "search", THREE.CanvasTexture>;

  constructor(lib: ModelLibrary) {
    this.body = fitted(lib.get("rover"), FOOTPRINT, FOOTPRINT);
    this.root.add(this.body);
    // State light: the body's own materials glow in the state color (own copies, so the
    // shared library model stays untouched).
    this.body.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).map((m) => {
        const copy = (m as THREE.MeshStandardMaterial).clone();
        this.glow.push(copy);
        return copy;
      });
      mesh.material = Array.isArray(mesh.material) ? mats : mats[0];
    });

    this.tells = { alert: tellTexture("!", STATE_COLORS.alert), search: tellTexture("?", STATE_COLORS.search) };
    this.tell = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.tells.alert, depthTest: false }));
    this.tell.scale.setScalar(0.9);
    this.tell.position.y = TELL_Y;
    this.tell.renderOrder = 10;
    this.root.add(this.tell);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array((CONE_RAYS + 2) * 3), 3));
    const index: number[] = [];
    for (let i = 1; i <= CONE_RAYS; i++) index.push(0, i + 1, i);
    geo.setIndex(index);
    this.cone = new THREE.Mesh(
      geo,
      new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }),
    );
    this.cone.frustumCulled = false;
  }

  sync(sim: Sim, time: number): void {
    const r = sim.robot;
    this.root.position.set(r.pos.x, 0, r.pos.z);
    this.body.rotation.y = r.yaw + MODEL_YAW;
    const color = STATE_COLORS[r.state];
    for (const m of this.glow) {
      m.emissive.set(color);
      m.emissiveIntensity = GLOW;
    }
    this.cone.material.color.set(color);
    this.cone.material.opacity = CONE_OPACITY[r.state];

    const tell = r.state === "alert" || r.state === "chase" ? "alert" : r.state === "search" ? "search" : null;
    this.tell.visible = tell !== null;
    if (tell) {
      this.tell.material.map = this.tells[tell];
      this.tell.position.y = TELL_Y + Math.sin(time * 8) * 0.06;
    }

    // Sight cone: a fan of rays, each stopped by the first building it hits.
    const pos = this.cone.geometry.getAttribute("position") as THREE.BufferAttribute;
    pos.setXYZ(0, r.pos.x, CONE_Y, r.pos.z);
    const half = sim.t.robot.sightHalfAngle;
    for (let i = 0; i <= CONE_RAYS; i++) {
      const a = r.yaw - half + (2 * half * i) / CONE_RAYS;
      const dir = { x: Math.sin(a), z: Math.cos(a) };
      const d = rayDistance(r.pos, dir, sim.t.robot.sightRange, sim.boxes);
      pos.setXYZ(i + 1, r.pos.x + dir.x * d, CONE_Y, r.pos.z + dir.z * d);
    }
    pos.needsUpdate = true;
  }
}
