// ---------------------------------------------------------------------------
// main.ts
// Purpose : Entry point: creates the WebGL renderer, the game, the frame loop and
//           resizing, and announces a successful boot for `dev.py smoke`.
// Usage   : Loaded by index.html (<script type="module" src="/src/main.ts">).
// Notes   : Models load first (Game.load), then the loop starts. BOOT_OK is logged after the FIRST RENDERED FRAME, so smoke proves the renderer
//           really works, not just that the script loaded. Uncaught errors go through Log.error,
//           which smoke fails on. dt is clamped so a background tab does not teleport the world.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { Log } from "./core/log";
import { Game, readOptions } from "./game/Game";

const MAX_DT = 0.1; // s

window.addEventListener("error", (e) => Log.error("core", `uncaught: ${e.message}`));
window.addEventListener("unhandledrejection", (e) => Log.error("core", `unhandled promise: ${String(e.reason)}`));

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

const aspect = () => host.clientWidth / Math.max(host.clientHeight, 1);
const loading = document.createElement("div");
loading.className = "loading";
loading.textContent = "Loading the town...";
host.appendChild(loading);

Game.load(host, aspect(), readOptions(location.search))
  .then((game) => {
    loading.remove();
    window.addEventListener("resize", () => {
      renderer.setSize(host.clientWidth, host.clientHeight);
      game.resize(aspect());
    });
    // THREE.Timer, not THREE.Clock: Clock is deprecated since r183. connect() pauses time while the tab is hidden.
    const timer = new THREE.Timer();
    timer.connect(document);
    let booted = false;
    renderer.setAnimationLoop((timestamp) => {
      timer.update(timestamp);
      const dt = Math.min(timer.getDelta(), MAX_DT);
      game.update(dt);
      renderer.render(game.scene, game.camera);
      if (!booted) {
        booted = true;
        Log.info("core", "BOOT_OK Courier Dash");
      }
    });
  })
  .catch((err) => {
    loading.textContent = "The game could not load its models. Details are in the browser console.";
    Log.error("core", `load failed: ${String(err)}`);
  });
