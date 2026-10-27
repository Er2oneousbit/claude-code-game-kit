// ---------------------------------------------------------------------------
// GateScene.ts
// Purpose : The picture: a town wall at night, the gate, the guard Bram, the notice,
//           the traveler, and a trust meter. It only shows what the controller tells it.
// Usage   : Registered in src/main.ts; the controller calls show(state, event).
// Notes   : Kenney Tiny Dungeon tiles (A-0001), drawn 3x. Tile indices were checked against the
//           pack's single-tile files: 40 wall, 48 floor, 45 door, 97 guard (helmet knight), 84 traveler.
//           Sounds: ElevenLabs (A-0003 to A-0006): the gate, the guard, and an ambience loop at the wall.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import type { Outcome, State } from "../core/gatekeeper";
import { Log } from "../core/log";
import { RULES } from "./tuning";

const AMBIENCE_VOLUME = 0.3;   // under the guard and the gate

const SCALE = 3;
const T = 16 * SCALE;
const TILE = { wall: 40, floor: 48, door: 45, guard: 97, traveler: 84 };

export class GateScene extends Phaser.Scene {
  private guard!: Phaser.GameObjects.Sprite;
  private door!: Phaser.GameObjects.Sprite;
  private meter!: Phaser.GameObjects.Graphics;
  private label!: Phaser.GameObjects.Text;

  constructor() {
    super("gate");
  }

  preload(): void {
    this.load.spritesheet("tiles", "assets/art/tilemap_packed.png", { frameWidth: 16, frameHeight: 16 });
    this.load.audio("open", "assets/audio/gate-open.mp3");
    this.load.audio("away", "assets/audio/turned-away.mp3");
    this.load.audio("talk", "assets/audio/guard-talk.mp3");
    this.load.audio("ambience", "assets/audio/gate-ambience.wav");
  }

  create(): void {
    const cols = Math.ceil(640 / T), wallRows = 3;
    for (let y = 0; y < Math.ceil(360 / T); y++) {
      for (let x = 0; x < cols; x++) {
        this.add.sprite(x * T, y * T, "tiles", y < wallRows ? TILE.wall : TILE.floor).setOrigin(0).setScale(SCALE)
          .setTint(y < wallRows ? 0x8a8ab0 : 0x9a8a78);
      }
    }
    const gateX = Math.floor(cols / 2) * T;
    this.door = this.add.sprite(gateX, (wallRows - 1) * T, "tiles", TILE.door).setOrigin(0).setScale(SCALE);
    this.guard = this.add.sprite(gateX + T * 1.2, wallRows * T + 6, "tiles", TILE.guard).setOrigin(0).setScale(SCALE);
    this.add.sprite(gateX - T * 0.2, wallRows * T + T * 2.4, "tiles", TILE.traveler).setOrigin(0).setScale(SCALE).setFlipX(true);
    this.add.rectangle(gateX - T * 3.6, T * 0.6, T * 3.0, T * 1.5, 0xe9dcb8).setOrigin(0).setStrokeStyle(3, 0x5a4a2a);
    this.add.text(gateX - T * 3.45, T * 0.72, "NOTICE\nGate closed by order\nof Captain Wren.", {
      fontFamily: "Georgia, serif", fontSize: "15px", color: "#3a2a10", lineSpacing: 2,
    });
    this.add.rectangle(0, 0, 640, 360, 0x0b0b30, 0.25).setOrigin(0);   // night tint
    this.meter = this.add.graphics();
    this.label = this.add.text(14, 334, "", { fontFamily: "monospace", fontSize: "13px", color: "#f4ecd8" });
    this.startAmbience();
    this.game.events.emit("gate-ready", this);
    Log.info("core", "BOOT_OK Gatekeeper");
  }

  // One ambience loop for the whole session: Phaser keeps sounds across scene restarts, and a browser keeps audio
  // locked until the first key press, so the loop starts on unlock (the headless smoke browser never unlocks: fine)
  private startAmbience(): void {
    const start = () => {
      if (!this.sound.get("ambience")) this.sound.add("ambience", { loop: true, volume: AMBIENCE_VOLUME }).play();
    };
    if (this.sound.locked) this.sound.once(Phaser.Sound.Events.UNLOCKED, start);
    else start();
  }

  show(s: State, spoke = true): void {
    const w = 200, x = 14, y = 318;
    this.meter.clear().fillStyle(0x000000, 0.6).fillRect(x - 2, y - 2, w + 4, 12);
    this.meter.fillStyle(s.trust >= RULES.openAt ? 0x7fd07f : 0xffd27a, 1).fillRect(x, y, Math.round((w * s.trust) / 100), 8);
    this.meter.lineStyle(2, 0xffffff, 0.8).lineBetween(x + (w * RULES.openAt) / 100, y - 3, x + (w * RULES.openAt) / 100, y + 11);
    this.label.setText(`trust ${s.trust}   turns left ${s.turnsLeft}`);
    if (spoke) {
      this.sound.play("talk", { volume: 0.4 });
      this.tweens.add({ targets: this.guard, y: this.guard.y - 4, yoyo: true, duration: 90 });
    }
  }

  finish(outcome: Exclude<Outcome, "talking">): void {
    if (outcome === "open") {
      this.sound.play("open");
      this.tweens.add({ targets: this.door, alpha: 0, duration: 600 });
      this.tweens.add({ targets: this.guard, x: this.guard.x + T, duration: 600 });
    } else {
      this.sound.play("away");
      this.cameras.main.shake(200, 0.006);
    }
  }
}
