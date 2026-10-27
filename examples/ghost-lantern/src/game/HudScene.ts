// ---------------------------------------------------------------------------
// HudScene.ts
// Purpose : The HUD: oil meter, key, timer, and the win or caught message.
//           A separate scene so the 2x game camera zoom never touches the UI.
// Usage   : Launched by GameScene; listens to its "hud" event (HudState).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import type { HudState } from "./GameScene";

const AMBER = 0xffd27a;
const TEXT = { fontFamily: "monospace", fontSize: "14px", color: "#f4ecd8", stroke: "#0b0b14", strokeThickness: 4 };

export class HudScene extends Phaser.Scene {
  private bar!: Phaser.GameObjects.Graphics;
  private info!: Phaser.GameObjects.Text;
  private message!: Phaser.GameObjects.Text;
  private debug!: Phaser.GameObjects.Text;

  constructor() {
    super("hud");
  }

  create(): void {
    this.bar = this.add.graphics();
    this.info = this.add.text(12, 26, "", TEXT);
    this.message = this.add.text(320, 170, "", { ...TEXT, fontSize: "22px" }).setOrigin(0.5);
    this.debug = this.add.text(628, 10, "", { ...TEXT, fontSize: "11px" }).setOrigin(1, 0);
    this.add.text(628, 344, "WASD move  SPACE brighten  R restart", { ...TEXT, fontSize: "10px" }).setOrigin(1, 1);
    const game = this.scene.get("game");
    game.events.on("hud", (s: HudState) => this.draw(s));
    this.events.once("shutdown", () => game.events.off("hud"));
  }

  private draw(s: HudState): void {
    const w = 120;
    this.bar.clear();
    this.bar.fillStyle(0x0b0b14, 0.8).fillRect(10, 10, w + 4, 12);
    this.bar.fillStyle(s.bright ? 0xffffff : AMBER, 1).fillRect(12, 12, Math.round(w * s.oil), 8);
    this.info.setText(`${s.hasKey ? "KEY  " : ""}${s.time.toFixed(1)} s`);
    this.message.setText(s.message);
    this.debug.setText(s.debug.join("\n"));
  }
}
