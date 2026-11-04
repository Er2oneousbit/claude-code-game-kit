// ---------------------------------------------------------------------------
// BackdropScene.ts
// Purpose : The still picture behind the title and menus (the shell's HTML screens sit on top of the canvas).
// Usage   : First scene in src/main.ts, so Phaser starts it; the shell sleeps it while a game scene runs.
// Notes   : Static on purpose: `dev.py smoke --screenshot ... --compare baseline.png` needs the same pixels on
//           every run. Gatekeeper: the night sky over the town (#0b0b14 fading up) and a band of dim stone like
//           the wall the gate sits in, instead of the kit's blue stripes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";

const STRIPES = [0x0b0b14, 0x0e0e1c, 0x111124, 0x14142c, 0x171734];
const WALL = 0x2c2c40; // the town wall at night (GateScene tints its tiles 0x8a8ab0 under a dark overlay)

export class BackdropScene extends Phaser.Scene {
  constructor() {
    super("backdrop");
  }

  create(): void {
    const { width, height } = this.scale;
    const band = height / STRIPES.length;
    STRIPES.forEach((c, i) => this.add.rectangle(0, i * band, width, band + 1, c).setOrigin(0, 0));
    this.add.rectangle(0, height - 40, width, 40, WALL).setOrigin(0, 0);
  }
}
