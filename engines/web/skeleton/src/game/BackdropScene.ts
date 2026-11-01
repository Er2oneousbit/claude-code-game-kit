// ---------------------------------------------------------------------------
// BackdropScene.ts
// Purpose : The still picture behind the title and menus (the shell's HTML screens sit on top of the canvas).
// Usage   : First scene in src/main.ts, so Phaser starts it; the shell sleeps it while a game scene runs.
// Notes   : Static on purpose: `dev.py smoke --screenshot ... --compare baseline.png` needs the same pixels on
//           every run. Swap in key art for your game.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";

const STRIPES = [0x1d2b53, 0x223260, 0x283a6c, 0x2e4278, 0x344a84];

export class BackdropScene extends Phaser.Scene {
  constructor() {
    super("backdrop");
  }

  create(): void {
    const { width, height } = this.scale;
    const band = height / STRIPES.length;
    STRIPES.forEach((c, i) => this.add.rectangle(0, i * band, width, band + 1, c).setOrigin(0, 0));
    this.add.rectangle(0, height - 40, width, 40, 0x5f574f).setOrigin(0, 0);
  }
}

// {{FOOTER}}
