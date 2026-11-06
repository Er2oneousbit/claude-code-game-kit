// ---------------------------------------------------------------------------
// kitMaterial.ts
// Purpose : The kit's shader recipes as Three.js materials: kitMaterial("toon_rim", { albedo: [0.2, 0.6, 0.9] })
//           returns a ShaderMaterial; set .uniforms.u_<name>.value to change a parameter, .uniforms.uMainSampler and
//           .uniforms.uAuxSampler for the textures.
// Usage   : import { kitMaterial } from "./shaders/kitMaterial";
//           const water = kitMaterial("scroll_water", {}, waterTexture);
//           mesh.material = water;  water.uniforms.u_time.value = clock.elapsedTime;   (each frame)
// Notes   : The GLSL is generated (src/shaders/kit/kitShaders.ts, from tools/shaders/ksl). The recipes work in image
//           space on the mesh's UVs: a sprite plane, a full-screen quad (post), or any UV-mapped surface. Textures
//           want NearestFilter for pixel art (kitTexture() sets it). Checked by `python tools/dev.py smoke --shaders`
//           against the recipes' golden images.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { KIT_FRAGMENTS, KIT_SHADERS } from "./kit/kitShaders";

export type KitName = keyof typeof KIT_SHADERS;
type Params = Record<string, number | number[]>;

const VERTEX = `varying vec2 vTextureCoord;
void main() {
  vTextureCoord = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

function uniformValue(v: number | number[]): number | THREE.Vector2 | THREE.Vector3 | THREE.Vector4 {
  if (!Array.isArray(v)) return v;
  if (v.length === 2) return new THREE.Vector2(v[0], v[1]);
  if (v.length === 3) return new THREE.Vector3(v[0], v[1], v[2]);
  return new THREE.Vector4(v[0], v[1], v[2], v[3]);
}

/** A texture set up for the recipes: nearest filtering, no mipmaps, no colour-space conversion. */
export function kitTexture(texture: THREE.Texture): THREE.Texture {
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  texture.colorSpace = THREE.NoColorSpace;
  texture.needsUpdate = true;
  return texture;
}

/** A ShaderMaterial for one recipe, its parameters defaulting to the recipe's own. */
export function kitMaterial(
  name: KitName,
  params: Params = {},
  main: THREE.Texture | null = null,
  aux: THREE.Texture | null = null,
): THREE.ShaderMaterial {
  const all = { ...(KIT_SHADERS[name].params as Params), ...params };
  const uniforms: Record<string, THREE.IUniform> = {
    uMainSampler: { value: main },
    uAuxSampler: { value: aux },
  };
  for (const [k, v] of Object.entries(all)) uniforms[`u_${k}`] = { value: uniformValue(v) };
  return new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: KIT_FRAGMENTS[name],
    uniforms,
    transparent: KIT_SHADERS[name].group === "sprite",
    toneMapped: false,
  });
}

// {{FOOTER}}
