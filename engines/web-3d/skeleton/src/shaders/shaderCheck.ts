// ---------------------------------------------------------------------------
// shaderCheck.ts
// Purpose : The shader check page mode (?shadercheck=1): renders every kit recipe with Three.js (kitMaterial on a
//           full-canvas quad) into a 64x64 canvas and logs each picture as SHADER_PNG <name> <data URL>, then
//           SHADER_CHECK_DONE. tools/smoke.mjs --shaders writes them to build/shader_check/ and compares them.
// Usage   : python tools/dev.py smoke --shaders
// Notes   : Its own small renderer (no blending, no tone mapping): the picture is exactly what the material draws.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { kitMaterial, kitTexture, type KitName } from "./kitMaterial";
import { KIT_SHADERS } from "./kit/kitShaders";

const INPUTS = import.meta.glob("../../data/shaders/inputs/*.png", { eager: true, query: "?url", import: "default" }) as Record<string, string>;
const SIZE = 64;

function inputUrl(name: string): string {
  const file = name === "sphere" ? "sphere_normal" : name;
  const key = Object.keys(INPUTS).find((k) => k.endsWith(`/${file}.png`));
  if (!key) throw new Error(`shader check: no input ${name}`);
  return INPUTS[key];
}

async function texture(name: string): Promise<THREE.Texture> {
  return kitTexture(await new THREE.TextureLoader().loadAsync(inputUrl(name)));
}

export async function runShaderCheck(): Promise<void> {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: true, antialias: false });
  renderer.setPixelRatio(1);
  renderer.setSize(SIZE, SIZE, false);
  renderer.setClearColor(0x000000, 0);
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  let failed = 0;
  for (const name of Object.keys(KIT_SHADERS) as KitName[]) {
    try {
      const meta = KIT_SHADERS[name];
      const material = kitMaterial(name, {}, await texture(meta.main), meta.aux ? await texture(meta.aux) : null);
      material.transparent = false; // write what the shader computes, alpha included
      const scene = new THREE.Scene();
      scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));
      renderer.render(scene, camera);
      console.log(`SHADER_PNG ${name} ${canvas.toDataURL("image/png")}`);
    } catch (err) {
      failed += 1;
      console.error(`[ERROR] shader check ${name}: ${(err as Error).message}`);
    }
  }
  renderer.dispose();
  console.log(`SHADER_CHECK_DONE failed=${failed}`);
}

// {{FOOTER}}
