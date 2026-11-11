// ---------------------------------------------------------------------------
// main.ts
// Purpose : Entry point: creates the WebGL renderer and the host that runs the worlds (src/game/threeHost.ts),
//           then hands the host to the shell (title, menus, settings, pause, subtitles: src/shell/).
// Usage   : Loaded by index.html (<script type="module" src="/src/main.ts">).
// Notes   : The shell is imported first: its crash hook (crash file + Log.error, which `dev.py smoke` fails on) is
//           in place before anything else runs, a renderer that cannot start included. The shell starts after the
//           FIRST RENDERED FRAME and logs BOOT_OK once the title screen is up, so smoke proves the renderer really
//           draws, not just that the script loaded. Worlds: "main" (Play, src/game/Game.ts) and "juice" (the juice
//           demo, src/game/JuiceWorld.ts); the Backdrop is the still picture behind the menus. The shell's input
//           layer (src/shell/input.ts) reads keyboard and pads for menus and worlds alike. Under automation the
//           Dotwork check (src/game/dotwork/boot.ts) loads every asset manifest before the shell starts.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the shell runs over the renderer (#175)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the Dotwork load check before the shell (#56)
// ---------------------------------------------------------------------------
import { shell } from "./shell/app";
import * as THREE from "three";
import { Backdrop } from "./game/Backdrop";
import { dotworkCheck } from "./game/dotwork/boot";
import { Game } from "./game/Game";
import { JuiceWorld } from "./game/JuiceWorld";
import { ThreeHost } from "./game/threeHost";

// ?shadercheck=1 (python tools/dev.py smoke --shaders): render every kit shader recipe for the golden-image check
if (new URLSearchParams(location.search).has("shadercheck")) {
  void import("./shaders/shaderCheck").then((m) => m.runShaderCheck());
}

const host = document.getElementById("game")!;
let renderer: THREE.WebGLRenderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true });
} catch (err) {
  host.textContent = "This game needs WebGL, which this browser or machine does not provide.";
  throw new Error(`WebGL renderer could not start: ${String(err)}`);
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(host.clientWidth, host.clientHeight);
renderer.shadowMap.enabled = true;
host.appendChild(renderer.domElement);

const aspect = host.clientWidth / Math.max(host.clientHeight, 1);
export const game = new ThreeHost(
  renderer,
  new Backdrop(aspect),
  { main: (a) => new Game(a), juice: (a) => new JuiceWorld(a) },
  (err) => shell.crash(err),
);
window.addEventListener("resize", () => game.resize(host.clientWidth, host.clientHeight));
// smoke (an automated browser) loads every Dotwork manifest first: a missing image or broken asset fails the boot
game.onFirstFrame = () => void dotworkCheck().finally(() => shell.start(game));
game.run();

// {{FOOTER}}
