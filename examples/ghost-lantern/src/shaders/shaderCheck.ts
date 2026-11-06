// ---------------------------------------------------------------------------
// shaderCheck.ts
// Purpose : The shader check page mode (?shadercheck=1): renders every kit recipe through Phaser on its test inputs
//           into a 64x64 canvas and logs each picture as SHADER_PNG <name> <data URL>, then SHADER_CHECK_DONE.
//           tools/smoke.mjs --shaders writes them to build/shader_check/ and compares them with the golden images.
// Usage   : python tools/dev.py smoke --shaders
// Notes   : One small Phaser game per recipe (64x64, pixelArt, a camera filter over the main input drawn to fill
//           it), so each picture is exactly what addKitFilter draws. Loaded only in this mode (main.ts).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { addKitFilter, type KitName } from "./kitFilter";
import { KIT_SHADERS } from "./kit/kitShaders";

const INPUTS = import.meta.glob("../../data/shaders/inputs/*.png", { eager: true, query: "?url", import: "default" }) as Record<string, string>;
const SIZE = 64;
const SETTLE_FRAMES = 3;

function inputUrl(name: string): string {
  const key = Object.keys(INPUTS).find((k) => k.endsWith(`/${name === "sphere" ? "sphere_normal" : name}.png`));
  if (!key) throw new Error(`shader check: no input ${name}`);
  return INPUTS[key];
}

function renderOne(name: KitName): Promise<string> {
  const meta = KIT_SHADERS[name];
  return new Promise((resolve, reject) => {
    const parent = document.createElement("div");
    document.body.appendChild(parent);
    let frames = 0;
    const game = new Phaser.Game({
      type: Phaser.WEBGL,
      parent,
      width: SIZE,
      height: SIZE,
      transparent: true,
      pixelArt: true,
      render: { preserveDrawingBuffer: true, antialias: false },
      banner: false,
      scene: {
        preload(this: Phaser.Scene) {
          this.load.image("main", inputUrl(meta.main));
          if (meta.aux) this.load.image("aux", inputUrl(meta.aux));
        },
        create(this: Phaser.Scene) {
          this.add.image(0, 0, "main").setOrigin(0, 0).setDisplaySize(SIZE, SIZE);
          addKitFilter(this.cameras.main, name, {}, meta.aux ? "aux" : undefined);
        },
        update() {
          frames += 1;
          if (frames !== SETTLE_FRAMES) return;
          try {
            const url = game.canvas.toDataURL("image/png");
            game.destroy(true);
            parent.remove();
            resolve(url);
          } catch (err) {
            reject(err);
          }
        },
      },
    });
  });
}

export async function runShaderCheck(): Promise<void> {
  let failed = 0;
  for (const name of Object.keys(KIT_SHADERS) as KitName[]) {
    try {
      console.log(`SHADER_PNG ${name} ${await renderOne(name)}`);
    } catch (err) {
      failed += 1;
      console.error(`[ERROR] shader check ${name}: ${(err as Error).message}`);
    }
  }
  console.log(`SHADER_CHECK_DONE failed=${failed}`);
}
