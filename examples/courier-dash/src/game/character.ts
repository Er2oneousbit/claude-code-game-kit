// ---------------------------------------------------------------------------
// character.ts
// Purpose : Load a rigged glTF character (a Bozzetto `rig make` result, or any .glb with a skin and clips) and play a
//           named clip on a loop: the AnimationMixer bookkeeping every 3D game repeats, in one small object.
// Usage   : const hero = await loadCharacter("assets/models/hero_rigged.glb");
//           scene.add(hero.root);
//           hero.play("walk");                       // loops; hero.play("wave", { loop: false }) plays once and holds
//           hero.play("walk", { restart: true });    // from the start again (play("walk") alone keeps its time)
//           each frame: hero.update(dt);
//           hero.root.getObjectByName(boneName("mixamorig:LeftUpLeg"))   // three's name: mixamorigLeftUpLeg
// Notes   : GLTFLoader keeps the clips' names (glTF animation names). Three.js strips ':' '.' '/' '[' ']' from node
//           names (PropertyBinding.sanitizeNodeName), so mixamorig:Hips is mixamorigHips: boneName() converts. No root
//           motion: the mixer plays the clips in place (Bozzetto's walk does not travel) and the game moves root.
//           The kit's rule in every engine (#296): play() of the clip that is already playing, with the same loop
//           setting, changes nothing (it keeps its time; a held one-shot keeps holding), so calling it every frame
//           is fine. Another clip, another loop setting or { restart: true } starts the clip from its start.
//           Units are metres, +Y up. glTF's front is +Z and Object3D.lookAt() turns a model's +Z toward the target,
//           so hero.root.lookAt(x, hero.root.position.y, z) faces it where it walks. parseCharacter() takes the bytes
//           (tests, or a file the player picked); a model with textures needs a DOM for its images.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): play() of the clip already playing keeps its time;
//           { restart: true } is the explicit restart (#296)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";

const FADE_S = 0.2; // seconds of crossfade when play() switches clips

export interface PlayOptions {
  loop?: boolean; // default true; false plays once and holds the last frame
  fade?: number; // crossfade seconds from the clip that was playing
  restart?: boolean; // default false; true starts the clip again although it is the one playing
}

export interface Character {
  root: THREE.Object3D;
  mixer: THREE.AnimationMixer;
  clips: Map<string, THREE.AnimationClip>;
  current: THREE.AnimationAction | null;
  /** Play a clip by name (the one already playing: nothing changes unless restart); throws when there is no such clip. */
  play(name: string, opts?: PlayOptions): THREE.AnimationAction;
  update(dt: number): void;
}

/** A glTF node or bone name as three.js stores it (mixamorig:Hips -> mixamorigHips). */
export const boneName = (gltfName: string): string => THREE.PropertyBinding.sanitizeNodeName(gltfName);

export function characterFromGltf(gltf: GLTF): Character {
  const root = gltf.scene;
  const mixer = new THREE.AnimationMixer(root);
  const clips = new Map(gltf.animations.map((c) => [c.name, c] as const));
  const ch: Character = {
    root, mixer, clips, current: null,
    play(name, opts = {}) {
      const clip = clips.get(name);
      if (!clip) throw new Error(`character has no clip "${name}" (it has ${[...clips.keys()].join(", ") || "none"})`);
      const loop = opts.loop ?? true;
      const action = mixer.clipAction(clip);
      const mode = loop ? THREE.LoopRepeat : THREE.LoopOnce;
      if (ch.current === action && action.loop === mode && !opts.restart) return action; // #296: keep its time
      action.setLoop(mode, Infinity);
      action.clampWhenFinished = !loop;
      action.reset().play();
      const fade = opts.fade ?? FADE_S;
      if (ch.current && ch.current !== action && fade > 0) action.crossFadeFrom(ch.current, fade, false);
      else if (ch.current && ch.current !== action) ch.current.stop();
      ch.current = action;
      return action;
    },
    update(dt) {
      mixer.update(dt);
    },
  };
  return ch;
}

export async function loadCharacter(url: string, loader: GLTFLoader = new GLTFLoader()): Promise<Character> {
  return characterFromGltf(await loader.loadAsync(url));
}

export async function parseCharacter(data: ArrayBuffer, path = "", loader: GLTFLoader = new GLTFLoader()): Promise<Character> {
  return characterFromGltf(await loader.parseAsync(data, path));
}
