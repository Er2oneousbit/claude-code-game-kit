// ---------------------------------------------------------------------------
// host.ts
// Purpose : What the shell needs from the renderer under it: start, pause, resume and stop a gameplay world, the
//           still picture behind the menus, the frame cap, the master volume and mono output, and a screenshot.
// Usage   : main.ts builds a host and hands it over:  shell.start(host)
//           web (Phaser 4): src/game/phaserHost.ts ; web-3d (Three.js): src/game/threeHost.ts
// Notes   : Every file of src/shell/ is the same in the web and web-3d overlays of the kit; only the host differs.
//           Keep the shell free of renderer imports, so a shell fix carries across by copying the file.
//           GameKey names the gameplay worlds the shell starts: "main" (Play) and "juice" (the juice demo).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

export type GameKey = "main" | "juice";

export interface GameHost {
  /** Starts world key: progress(0..1) while it loads, ready() once it is up and running. */
  start(key: GameKey, progress: (v: number) => void, ready: () => void): void;
  /** Freezes world key on its last frame (pause menu, a screenshot). */
  pause(key: GameKey): void;
  resume(key: GameKey): void;
  /** Ends world key. Also called after a crash, so it must cope with a half-started world. */
  stop(key: GameKey): void;
  /** The still picture behind the title and menus: hidden while a world runs. */
  backdrop(show: boolean): void;
  /** Frames per second at most; 0 = as fast as the display refreshes. */
  frameCap(fps: number): void;
  /** The renderer's own sound, if it has any: master volume 0..1 and mono output. */
  audio(master: number, mono: boolean): void;
  /** The frame on screen as a PNG data URL, or "" when the renderer cannot give one (F8 bug report). */
  snapshot(done: (png: string) => void): void;
}

// {{FOOTER}}
