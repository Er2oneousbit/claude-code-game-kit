// ---------------------------------------------------------------------------
// main.ts
// Purpose : Entry point. Creates the Phaser game with the project's scenes.
// Usage   : Loaded by index.html (<script type="module" src="/src/main.ts">).
// Notes   : 640x360 logical size, scaled to fit the window with pixel-art filtering.
//           Uncaught errors are logged through Log.error so `dev.py smoke` sees them.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { Log } from "./core/log";
import { Controller } from "./game/controller";
import { GateScene } from "./game/GateScene";

window.addEventListener("error", (e) => Log.error("core", `uncaught: ${e.message}`));
window.addEventListener("unhandledrejection", (e) => Log.error("core", `unhandled promise: ${String(e.reason)}`));

export const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: 640,
  height: 360,
  backgroundColor: "#0b0b14",
  pixelArt: true,
  scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
  scene: [GateScene],
});

// The controller wires the page and the brain to the scene once the scene exists (once only)
game.events.once("gate-ready", (scene: GateScene) => void new Controller(scene).start());
