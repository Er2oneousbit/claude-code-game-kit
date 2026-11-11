// ---------------------------------------------------------------------------
// phaserHost.ts
// Purpose : The shell's GameHost (src/shell/host.ts) on Phaser 4: worlds are scenes ("main", "juice", "backdrop"),
//           pause and stop are Phaser's scene calls, the frame cap is the loop's FPS limit, the master volume and
//           mono output go to Phaser's sound manager, the screenshot is the renderer's snapshot.
// Usage   : new Phaser.Game({ ..., callbacks: { postBoot: (g) => shell.start(phaserHost(g)) } })   (src/main.ts)
// Notes   : The loading screen's progress is the scene's loader; ready() fires on the scene's "create" event.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import type * as Phaser from "phaser";
import { Log } from "../core/log";
import type { GameHost } from "../shell/host";

const BACKDROP = "backdrop"; // the scene behind the menus (BackdropScene)

export function phaserHost(game: Phaser.Game): GameHost {
  return {
    start(key, progress, ready) {
      const scene = game.scene.getScene(key);
      if (!scene) throw new Error(`no scene "${key}" (register it in src/main.ts)`);
      const onProgress = (v: number) => progress(v);
      scene.load.on("progress", onProgress);
      scene.events.once("create", () => {
        scene.load.off("progress", onProgress);
        ready();
      });
      game.scene.start(key);
    },
    pause: (key) => game.scene.pause(key),
    resume: (key) => game.scene.resume(key),
    stop: (key) => game.scene.stop(key),
    backdrop(show) {
      if (!show) game.scene.sleep(BACKDROP);
      else if (game.scene.isSleeping(BACKDROP)) game.scene.wake(BACKDROP);
    },
    frameCap: (fps) => game.loop.setFPSLimit(fps),
    audio(master, mono) {
      game.sound.volume = master;
      try {
        const ctx = (game.sound as unknown as { context?: AudioContext }).context;
        if (ctx) {
          ctx.destination.channelCountMode = "explicit";
          ctx.destination.channelInterpretation = "speakers";
          ctx.destination.channelCount = mono ? 1 : Math.max(1, Math.min(2, ctx.destination.maxChannelCount));
        }
      } catch (err) {
        Log.debug("core", `mono audio not applied: ${String(err)}`);
      }
    },
    snapshot(done) {
      game.renderer.snapshot((img) => done(img instanceof HTMLImageElement ? img.src : ""));
    },
  };
}

// {{FOOTER}}
