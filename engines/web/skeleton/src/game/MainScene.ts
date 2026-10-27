// ---------------------------------------------------------------------------
// MainScene.ts
// Purpose : First scene. Announces a successful boot so `dev.py smoke` can verify
//           the game starts in a real browser without errors.
// Usage   : Registered in src/main.ts.
// Notes   : PROTOTYPE: a box bouncing around proves the loop and rendering work.
//           Replace with your real scenes. Keep the BOOT_OK log line (or update
//           BOOT_MARKER in tools/dev.py).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { Log } from "../core/log";

const BOX_SIZE = 32;
const START_VELOCITY = { x: 160, y: 110 }; // px/s

export class MainScene extends Phaser.Scene {
  private box!: Phaser.GameObjects.Rectangle;
  private velocity = { ...START_VELOCITY };

  constructor() {
    super("main");
  }

  create(): void {
    this.box = this.add.rectangle(40, 40, BOX_SIZE, BOX_SIZE, 0xf2c14e).setOrigin(0, 0);
    this.add.text(8, 8, "{{GAME_NAME}}", { fontFamily: "monospace", fontSize: "16px", color: "#ffffff" });
    Log.info("core", "BOOT_OK {{GAME_NAME}}");
  }

  update(_time: number, deltaMs: number): void {
    const dt = Math.min(deltaMs / 1000, 0.1); // clamp big gaps (tab in background, debugger pause)
    const { width, height } = this.scale;
    this.box.x += this.velocity.x * dt;
    this.box.y += this.velocity.y * dt;
    if (this.box.x < 0 || this.box.x + BOX_SIZE > width) this.velocity.x *= -1;
    if (this.box.y < 0 || this.box.y + BOX_SIZE > height) this.velocity.y *= -1;
    this.box.x = Phaser.Math.Clamp(this.box.x, 0, width - BOX_SIZE);
    this.box.y = Phaser.Math.Clamp(this.box.y, 0, height - BOX_SIZE);
  }
}

// {{FOOTER}}
