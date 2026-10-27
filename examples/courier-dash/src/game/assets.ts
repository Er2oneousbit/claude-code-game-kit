// ---------------------------------------------------------------------------
// assets.ts
// Purpose : Load every model once (GLTFLoader) and fit copies into level footprints, so what the
//           player sees matches the collision boxes in src/core/level.ts.
// Usage   : const lib = await loadModels(); const house = fitted(lib.get("building-type-a"), 6, 5)
// Notes   : Relative URLs (assets/...), never /assets/..., so builds work from a subfolder.
//           Kenney's town kit is "mini" scale (a house is 1.3 m wide), so every model is scaled
//           at runtime instead of baking a scale into the files.
//           Static models are cloned (shared geometry and materials); the courier is used as is
//           because it is skinned and animated.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { type GLTF, GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const MODEL_URLS: Record<string, string> = {
  courier: "assets/models/characters/courier.glb",
  crate: "assets/models/platformer/crate.glb",
  flag: "assets/models/platformer/flag.glb",
  rover: "assets/models/space/rover.glb",
  "road-straight": "assets/models/roads/road-straight.glb",
  "road-crossroad": "assets/models/roads/road-crossroad.glb",
  "road-end": "assets/models/roads/road-end.glb",
  "building-type-a": "assets/models/suburban/building-type-a.glb",
  "building-type-c": "assets/models/suburban/building-type-c.glb",
  "building-type-f": "assets/models/suburban/building-type-f.glb",
  "building-type-k": "assets/models/suburban/building-type-k.glb",
  "tree-large": "assets/models/suburban/tree-large.glb",
  "tree-small": "assets/models/suburban/tree-small.glb",
  fence: "assets/models/suburban/fence-1x4.glb",
};

export class ModelLibrary {
  constructor(private readonly gltfs: Map<string, GLTF>) {}

  get(name: string): THREE.Object3D {
    return this.gltf(name).scene;
  }

  gltf(name: string): GLTF {
    const g = this.gltfs.get(name);
    if (!g) throw new Error(`model "${name}" is not in MODEL_URLS (src/game/assets.ts)`);
    return g;
  }
}

/** Load all models in parallel. Rejects with the URL that failed. */
export async function loadModels(onProgress?: (done: number, total: number) => void): Promise<ModelLibrary> {
  const loader = new GLTFLoader();
  const entries = Object.entries(MODEL_URLS);
  let done = 0;
  const loaded = await Promise.all(
    entries.map(async ([name, url]) => {
      try {
        const gltf = await loader.loadAsync(url);
        gltf.scene.traverse((o) => {
          if ((o as THREE.Mesh).isMesh) o.castShadow = o.receiveShadow = true;
        });
        onProgress?.(++done, entries.length);
        return [name, gltf] as const;
      } catch (err) {
        throw new Error(`could not load ${url}: ${String(err)}`);
      }
    }),
  );
  return new ModelLibrary(new Map(loaded));
}

/**
 * A copy of `src` scaled uniformly to fit inside a w x d footprint (times `oversize`), turned by
 * quarter turns, centered on x/z, standing on y = 0.
 */
export function fitted(src: THREE.Object3D, w: number, d: number, turns = 0, oversize = 1): THREE.Group {
  const inner = src.clone(true);
  inner.rotation.y = (turns * Math.PI) / 2;
  const holder = new THREE.Group();
  holder.add(inner);
  const size = new THREE.Box3().setFromObject(holder).getSize(new THREE.Vector3());
  inner.scale.setScalar(Math.min(w / size.x, d / size.z) * oversize);
  const box = new THREE.Box3().setFromObject(holder);
  const c = box.getCenter(new THREE.Vector3());
  inner.position.set(-c.x, -box.min.y, -c.z);
  return holder;
}

/** A copy scaled so its longest side along the ground is `length`, laid along x. */
export function fittedLong(src: THREE.Object3D, length: number): THREE.Group {
  const size = new THREE.Box3().setFromObject(src).getSize(new THREE.Vector3());
  const alongZ = size.z > size.x;
  return fitted(src, length, length, alongZ ? 1 : 0);
}

/** A copy scaled to a height, standing on y = 0, centered on x/z. */
export function fittedHeight(src: THREE.Object3D, height: number, clone = true): THREE.Group {
  const inner = clone ? src.clone(true) : src;
  const holder = new THREE.Group();
  holder.add(inner);
  const size = new THREE.Box3().setFromObject(holder).getSize(new THREE.Vector3());
  inner.scale.multiplyScalar(height / size.y);
  const box = new THREE.Box3().setFromObject(holder);
  const c = box.getCenter(new THREE.Vector3());
  inner.position.set(-c.x, -box.min.y, -c.z);
  return holder;
}
