// ---------------------------------------------------------------------------
// kitFilter.ts
// Purpose : The kit's shader recipes as Phaser 4 filters: addKitFilter(camera or game object, "flash", {amount: 1})
//           puts one on, and returns its controller (change controller.params.amount to tween it).
// Usage   : import { addKitFilter } from "./shaders/kitFilter";
//           const flash = addKitFilter(sprite, "flash");             // the recipe's default parameters
//           this.tweens.add({ targets: flash.params, amount: 0, duration: 200 });
//           addKitFilter(this.cameras.main, "vignette", { strength: 0.4 });
//           addKitFilter(sprite, "dissolve", {}, "noise");           // a second input: a texture key
// Notes   : The GLSL is generated (src/shaders/kit/kitShaders.ts, from tools/shaders/ksl); each recipe becomes a
//           render node "Kit_<name>" the first time it is used. A filter reads the object as rendered (its frame
//           buffer), so a second input must line up with it: same size, nearest filtering (pixelArt: true).
//           Checked by `python tools/dev.py smoke --shaders` against the recipes' golden images.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { KIT_FRAGMENTS, KIT_SHADERS } from "./kit/kitShaders";

export type KitName = keyof typeof KIT_SHADERS;
type Params = Record<string, number | number[]>;

/** One recipe on one camera or object: its parameters (u_<name> in the shader) and an optional second texture. */
export class KitController extends Phaser.Filters.Controller {
  params: Params;
  auxTexture: unknown = null;

  constructor(camera: Phaser.Cameras.Scene2D.Camera, name: KitName, params: Params, auxKey?: string) {
    super(camera, `Kit_${name}`);
    this.params = { ...(KIT_SHADERS[name].params as Params), ...params };
    if (auxKey) {
      const frame = camera.scene.sys.textures.getFrame(auxKey);
      if (!frame) throw new Error(`addKitFilter: no texture ${auxKey}`);
      this.auxTexture = frame.glTexture;
    }
  }
}

const registered = new Set<string>();

function register(renderer: Phaser.Renderer.WebGL.WebGLRenderer, name: KitName): void {
  if (registered.has(name)) return;
  const BaseFilterShader = Phaser.Renderer.WebGL.RenderNodes.BaseFilterShader as unknown as new (
    ...args: unknown[]
  ) => object;
  class KitNode extends BaseFilterShader {
    constructor(manager: unknown) {
      super(`Kit_${name}`, manager, null, KIT_FRAGMENTS[name]);
    }
    setupTextures(controller: KitController, textures: unknown[]): void {
      if (controller.auxTexture) textures[1] = controller.auxTexture;
    }
    setupUniforms(controller: KitController): void {
      const pm = (this as unknown as { programManager: { setUniform(n: string, v: unknown): void } }).programManager;
      for (const [k, v] of Object.entries(controller.params)) pm.setUniform(`u_${k}`, v);
      if (controller.auxTexture) pm.setUniform("uAuxSampler", 1);
    }
  }
  (renderer.renderNodes as unknown as { addNodeConstructor(n: string, c: unknown): void }).addNodeConstructor(
    `Kit_${name}`,
    KitNode,
  );
  registered.add(name);
}

/** Put a kit recipe on a camera (the whole view) or on a game object with filters. */
export function addKitFilter(
  target: Phaser.Cameras.Scene2D.Camera | (Phaser.GameObjects.GameObject & { filters?: unknown; scene: Phaser.Scene }),
  name: KitName,
  params: Params = {},
  auxKey?: string,
): KitController {
  const scene = target instanceof Phaser.Cameras.Scene2D.Camera ? target.scene : target.scene;
  const renderer = scene.sys.game.renderer as Phaser.Renderer.WebGL.WebGLRenderer;
  if (!(renderer instanceof Phaser.Renderer.WebGL.WebGLRenderer)) throw new Error("addKitFilter needs WebGL");
  register(renderer, name);
  const camera = target instanceof Phaser.Cameras.Scene2D.Camera ? target : scene.cameras.main;
  if (!(target instanceof Phaser.Cameras.Scene2D.Camera)) {
    (target as unknown as { enableFilters(): void }).enableFilters?.();
  }
  const list = (target as unknown as { filters: { internal: { add(c: KitController): KitController } } }).filters;
  return list.internal.add(new KitController(camera, name, params, auxKey));
}
