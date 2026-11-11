// ---------------------------------------------------------------------------
// main.ts
// Purpose : Entry point. Creates the Phaser game with the project's scenes and hands it to the kit's shell
//           (title, main menu, settings, pause, credits: src/shell/).
// Usage   : Loaded by index.html (<script type="module" src="/src/main.ts">).
// Notes   : 640x360 logical size, scaled to fit the window with pixel-art filtering.
//           The shell is imported first: its crash hook (crash file + Log.error, which `dev.py smoke` fails
//           on) is in place before anything else runs. Phaser's gamepad plugin is off because the shell's input
//           layer (src/shell/input.ts) reads pads for the menus.
//           ?autoplay (the scripted runs and the real-model run in the README) skips the shell: GateScene is
//           first, so Phaser starts it at once and the page panels show as before. Every other load starts at
//           the title; "Play" runs GateScene as the shell's "main" scene and shows the panels under the canvas.
//           The panels are HTML the player types into, so their key presses stay with them (the shell's input
//           would take WASD, Space and Enter for its own actions); Escape still reaches the shell and pauses.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): the kit's shell wired in (#182)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the shell gets a GameHost (src/game/phaserHost.ts),
//           not the Phaser game; Dotwork manifests are checked before the shell (kit 0.14.5, #175, #55)
// ---------------------------------------------------------------------------
import { shell } from "./shell/app";
import * as Phaser from "phaser";
import { BackdropScene } from "./game/BackdropScene";
import { Controller } from "./game/controller";
import { GateScene } from "./game/GateScene";
import { JuiceScene } from "./game/JuiceScene";
import { verifyDotwork } from "./game/dotworkVerify";
import { phaserHost } from "./game/phaserHost";

const MENUS_CLASS = "in-menus"; // on <body> while the shell's title or menus are up: the page panels hide (index.html)

const direct = new URLSearchParams(location.search).has("autoplay"); // a script plays: straight into the game

export const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: 640,
  height: 360,
  backgroundColor: "#0b0b14",
  pixelArt: true,
  scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
  input: { gamepad: false },
  // the first one starts on its own; the shell runs the others ("main" = GateScene, "juice" = the kit's demo)
  scene: direct ? [GateScene, BackdropScene, JuiceScene] : [BackdropScene, GateScene, JuiceScene],
  callbacks: { postBoot: (g) => void (!direct && verifyDotwork(g).then(() => shell.start(phaserHost(g)))) },
});

let controller: Controller | null = null;

if (!direct) wirePage();

// The controller wires the page and the brain to the scene the first time the scene exists; after the title
// screen ("Quit to title", then "Play") it starts a new conversation with the guard the player already picked
game.events.on("gate-ready", (scene: GateScene) => {
  document.body.classList.remove(MENUS_CLASS);
  if (!controller) {
    controller = new Controller(scene);
    void controller.start();
    if (!direct) followPause(scene);
  } else {
    controller.reopened();
  }
});
game.events.on("gate-closed", () => {
  if (!direct) document.body.classList.add(MENUS_CLASS);
  controller?.closed();
});

/** Shell mode: panels hidden behind the title, and typing in them never reaches the shell's key bindings. */
function wirePage(): void {
  document.body.classList.add(MENUS_CLASS);
  document.querySelector("main")?.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") e.stopPropagation(); // the shell listens on window: it never sees these
  });
}

/** Pause takes the focus out of the chat box (the pause menu needs the arrow keys), resume gives it back. */
function followPause(scene: GateScene): void {
  scene.events.on(Phaser.Scenes.Events.PAUSE, () => (document.activeElement as HTMLElement | null)?.blur?.());
  scene.events.on(Phaser.Scenes.Events.RESUME, () => {
    const line = document.getElementById("line") as HTMLInputElement | null;
    if (line && line.offsetParent !== null) line.focus(); // only when the chat is on screen
  });
}
