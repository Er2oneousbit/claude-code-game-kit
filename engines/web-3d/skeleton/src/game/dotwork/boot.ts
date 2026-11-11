// ---------------------------------------------------------------------------
// boot.ts
// Purpose : The game's Dotwork manifests (public/assets/dotwork/*.assets.json, listed at build time) and the load
//           check smoke runs: every manifest imports, every image it names loads, every asset builds.
// Usage   : import { DOTWORK_MANIFESTS, dotworkCheck } from "./game/dotwork/boot";
//           game.onFirstFrame = () => void dotworkCheck().finally(() => shell.start(game));   (src/main.ts)
// Notes   : The list comes from the dotwork-manifests plugin in vite.config.ts (`virtual:dotwork-manifests`):
//           restart `dev.py run` after Dotwork writes a new pack. The check runs in a browser under automation
//           (navigator.webdriver: Playwright, which `dev.py smoke` uses) or with ?dotwork=check, never for a
//           player; it holds the shell (and BOOT_OK) until it is done, so smoke always waits for it. A failure is
//           Log.error (smoke fails on it), a skipped kind a warning. DOTWORK_OK <manifests> <assets> <images> marks
//           a pass (dev.py smoke --debug prints it). No manifests: nothing to do.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import manifests from "virtual:dotwork-manifests";
import { Log } from "../../core/log";
import { DotworkLibrary } from "./library";
import { disposeScene } from "../threeHost";
import type * as THREE from "three";

/** Every manifest of the game, as URLs relative to the page ("assets/dotwork/town.assets.json"). */
export const DOTWORK_MANIFESTS: string[] = manifests;

/** Loads and builds everything once when asked to (smoke, ?dotwork=check); never rejects. */
export async function dotworkCheck(search = location.search): Promise<void> {
  const asked = navigator.webdriver || new URLSearchParams(search).get("dotwork") === "check";
  if (!asked || !DOTWORK_MANIFESTS.length) return;
  try {
    const lib = await DotworkLibrary.load(DOTWORK_MANIFESTS);
    let assets = 0;
    const built: THREE.Object3D[] = [];
    for (const p of lib.packs) {
      for (const [name, def] of p.animated) {
        const a = lib.animated(name, { pack: p.pack });
        for (const clip of def.clips.keys()) {
          a.play(clip, true);
          a.update(def.clips.get(clip)!.length * 1.5); // every frame's texture rect, to the end and past it
        }
        a.dispose();
      }
      for (const name of p.sprites.keys()) built.push(lib.sprite(name, { pack: p.pack }));
      for (const [name, def] of p.icons) for (const s of def.sizes) built.push(lib.icon(name, s.size, { pack: p.pack }));
      for (const [name, def] of p.portraits) {
        const q = lib.portrait(name, undefined, { pack: p.pack });
        for (const e of def.expressions) q.setExpression(e.name);
        built.push(q);
      }
      for (const name of p.maps.keys()) built.push(lib.map(name, p.pack));
      for (const [name, def] of p.fonts) {
        built.push(lib.text(name, String.fromCodePoint(...[...def.glyphs.keys()].slice(0, 512)), { pack: p.pack }));
      }
      for (const [name, kit] of p.uiKits) {
        for (const part of kit.parts.values()) built.push(lib.nineSlice(name, part.name, part.size[0] * 2, part.size[1] * 2, { pack: p.pack }));
      }
      assets += p.animated.size + p.sprites.size + p.icons.size + p.portraits.size + p.tilesets.size + p.maps.size + p.fonts.size + p.uiKits.size;
    }
    for (const o of built) disposeScene(o);
    Log.info("dotwork", `DOTWORK_OK ${lib.packs.length} manifest(s), ${assets} asset(s), ${lib.textureCount} image(s)`);
    lib.dispose();
  } catch (err) {
    Log.error("dotwork", `DOTWORK_FAIL ${err instanceof Error ? err.message : String(err)}`);
  }
}

// {{FOOTER}}
