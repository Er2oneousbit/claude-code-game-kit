// ---------------------------------------------------------------------------
// main.ts
// Purpose : Entry point. Creates the Phaser game with the project's scenes and hands it to the shell
//           (title, menus, settings, pause, subtitles: src/shell/).
// Usage   : Loaded by index.html (<script type="module" src="/src/main.ts">).
// Notes   : 640x360 logical size, scaled to fit the window with pixel-art filtering.
//           The shell is imported first: its crash hook (crash file + Log.error, which `dev.py smoke` fails
//           on) is in place before anything else runs. Phaser's keyboard and gamepad plugins are off because
//           the shell's input layer (src/shell/input.ts) reads both for menus and scenes alike.
//           The shell drives Phaser through src/game/phaserHost.ts (its GameHost), never directly.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the shell gets a GameHost, not the Phaser game (#175)
// ---------------------------------------------------------------------------
import { shell } from "./shell/app";
import * as Phaser from "phaser";
import { BackdropScene } from "./game/BackdropScene";
import { JuiceScene } from "./game/JuiceScene";
import { MainScene } from "./game/MainScene";
import { phaserHost } from "./game/phaserHost";

export const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: 640,
  height: 360,
  backgroundColor: "#1d2b53",
  pixelArt: true,
  scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
  input: { keyboard: false, gamepad: false },
  scene: [BackdropScene, MainScene, JuiceScene], // the first one starts on its own; the shell runs the others
  callbacks: { postBoot: (g) => shell.start(phaserHost(g)) },
});

// ?shadercheck=1 (python tools/dev.py smoke --shaders): render every kit shader recipe for the golden-image check
if (new URLSearchParams(location.search).has("shadercheck")) {
  void import("./shaders/shaderCheck").then((m) => m.runShaderCheck());
}

// {{FOOTER}}
