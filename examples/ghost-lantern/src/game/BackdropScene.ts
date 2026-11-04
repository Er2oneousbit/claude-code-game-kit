// ---------------------------------------------------------------------------
// BackdropScene.ts
// Purpose : The still picture behind the title and menus (the shell's HTML screens sit on top of the canvas).
// Usage   : First scene in src/main.ts, so Phaser starts it; the shell sleeps it while a game scene runs.
// Notes   : Static on purpose: `dev.py smoke --screenshot ... --compare baseline.png` needs the same pixels on
//           every run. Ghost Lantern: the game's night (#0b0b14) fading up, with a warm floor band like the
//           lantern's glow, instead of the kit's blue stripes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";

const STRIPES = [0x0b0b14, 0x0f0f1c, 0x131324, 0x17172c, 0x1b1b34];
const FLOOR = 0x3a2a1a; // a dim amber, the lantern's light on the ground

export class BackdropScene extends Phaser.Scene {
  constructor() {
    super("backdrop");
  }

  create(): void {
    const { width, height } = this.scale;
    const band = height / STRIPES.length;
    STRIPES.forEach((c, i) => this.add.rectangle(0, i * band, width, band + 1, c).setOrigin(0, 0));
    this.add.rectangle(0, height - 40, width, 40, FLOOR).setOrigin(0, 0);
  }
}
