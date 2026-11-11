// ---------------------------------------------------------------------------
// main.ts
// Purpose : Entry point. Creates the Phaser game with the project's scenes and hands it to the kit's shell
//           (title, main menu with the difficulty, settings, pause, credits: src/shell/).
// Usage   : Loaded by index.html (<script type="module" src="/src/main.ts">).
// Notes   : 640x360 logical size, scaled to fit the window with pixel-art filtering.
//           The shell is imported first: its crash hook (crash file + Log.error, which `dev.py smoke` fails
//           on) is in place before anything else runs. Phaser's gamepad plugin is off because the shell's input
//           layer (src/shell/input.ts) reads pads for the menus; the keyboard plugin stays on because
//           GameScene reads its own keys (WASD, SPACE, R), as it did before the shell came in.
//           ?autoplay (the bot pair, the README GIF) skips the shell: GameScene is first, so Phaser starts it
//           at once and it logs BOOT_OK itself. Every other load starts at the title (BOOT_OK from the shell).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the shell gets a GameHost (src/game/phaserHost.ts),
//           not the Phaser game; Dotwork manifests are checked before the shell (kit 0.14.5, #175, #55)
// ---------------------------------------------------------------------------
import { shell } from "./shell/app";
import * as Phaser from "phaser";
import { BackdropScene } from "./game/BackdropScene";
import { GameScene } from "./game/GameScene";
import { HudScene } from "./game/HudScene";
import { JuiceScene } from "./game/JuiceScene";
import { verifyDotwork } from "./game/dotworkVerify";
import { phaserHost } from "./game/phaserHost";

const direct = new URLSearchParams(location.search).has("autoplay"); // a bot plays: straight into the game

export const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: 640,
  height: 360,
  backgroundColor: "#0b0b14",
  pixelArt: true,
  scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
  input: { gamepad: false },
  // the first one starts on its own; the shell runs the others ("main" = GameScene, "juice" = the kit's demo)
  scene: direct ? [GameScene, HudScene, BackdropScene, JuiceScene] : [BackdropScene, GameScene, HudScene, JuiceScene],
  callbacks: { postBoot: (g) => void (!direct && verifyDotwork(g).then(() => shell.start(phaserHost(g)))) },
});
