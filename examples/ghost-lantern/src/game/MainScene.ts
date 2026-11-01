// ---------------------------------------------------------------------------
// MainScene.ts
// Purpose : The play scene: what "Play" on the main menu starts (after the loading screen).
// Usage   : Registered in src/main.ts as "main"; the shell (src/shell/app.ts) starts, pauses and stops it.
// Notes   : PROTOTYPE: a box bouncing around proves the loop and rendering work. Replace it with your game.
//           Read the player's settings through shell.settings (game_speed scales dt here) and input through
//           shell.input (isDown / takePress with action names from settings.input.bindings).
//           BOOT_OK is logged by the shell once the title screen is up (dev.py smoke waits for it).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { shell } from "../shell/app";

const BOX_SIZE = 32;
const START_VELOCITY = { x: 160, y: 110 }; // px/s
const MAX_DT = 0.1; // s: clamp big gaps (tab in background, debugger pause)

export class MainScene extends Phaser.Scene {
  private box!: Phaser.GameObjects.Rectangle;
  private velocity = { ...START_VELOCITY };

  constructor() {
    super("main");
  }

  create(): void {
    this.velocity = { ...START_VELOCITY };
    this.box = this.add.rectangle(40, 40, BOX_SIZE, BOX_SIZE, 0xf2c14e).setOrigin(0, 0);
  }

  update(_time: number, deltaMs: number): void {
    if (shell.plantedCrash) {
      shell.plantedCrash = false;
      throw new Error("planted crash (dev.py smoke --drive crash)"); // proves the crash hook end to end
    }
    const dt = Math.min(deltaMs / 1000, MAX_DT) * shell.settings.access.game_speed;
    const { width, height } = this.scale;
    this.box.x += this.velocity.x * dt;
    this.box.y += this.velocity.y * dt;
    if (this.box.x < 0 || this.box.x + BOX_SIZE > width) this.velocity.x *= -1;
    if (this.box.y < 0 || this.box.y + BOX_SIZE > height) this.velocity.y *= -1;
    this.box.x = Phaser.Math.Clamp(this.box.x, 0, width - BOX_SIZE);
    this.box.y = Phaser.Math.Clamp(this.box.y, 0, height - BOX_SIZE);
  }
}
