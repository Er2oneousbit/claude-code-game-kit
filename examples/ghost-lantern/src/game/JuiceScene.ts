// ---------------------------------------------------------------------------
// JuiceScene.ts
// Purpose : The juice demo (main menu "Juice demo" in debug builds): every juice module in one toy. Hit the
//           box (attack) for trauma shake, hitstop, a spring squash and a limited screen flash; walk and jump
//           with a follow camera (deadzone, look-ahead), an input buffer and coyote time; hold interact to guard.
// Usage   : Registered in src/main.ts as "juice"; the shell starts it (shell.startGame("juice")).
// Notes   : The player's settings feed the juice live: effectiveShake (reduce_motion, shake_scale), flash_limit
//           (gentle flashes), hold_to_toggle (guard), game_speed (dt), colorblind (this demo's palette only).
//           The FlashLimiter is ALWAYS on (at most 3 full-screen flashes per real second); flash_limit only
//           tones each flash down further. Time: Hitstop.scaledDt and FlashLimiter.request take real wall-clock
//           time (before hitstop and game_speed); shake, follow, input buffer, coyote and spring take game time
//           (after both), so a hitstop freezes the impact frame, shake included.
//           A sample subtitle line plays on start, a bark and a caption on hits.
//
// Pseudocode (per frame):
//   gameDt = hitstop.scaledDt(realDt) * game_speed ; buffer, coyote, spring, follow and shake use gameDt
//   move, gravity ; jump when grounded-or-coyote and the buffer holds a jump press
//   attack in reach -> trauma, hitstop, spring kick, flash if the limiter allows (gentler with flash_limit)
//   camera = follow(player) + shake offset and angle
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as Phaser from "phaser";
import { CoyoteTimer } from "../core/coyoteTimer";
import { FlashLimiter } from "../core/flashLimiter";
import { FollowCamera } from "../core/followCamera";
import { Hitstop } from "../core/hitstop";
import { HoldToggle } from "../core/holdToggle";
import { AutoRepeat } from "../core/autoRepeat";
import { INPUT_BUFFER_S, InputBuffer } from "../core/inputBuffer";
import { effectiveShake } from "../core/settings";
import { Shake } from "../core/shake";
import { Spring, squash } from "../core/spring";
import { shell } from "../shell/app";

// ---- Tunables ----------------------------------------------------------------
const COYOTE_S = 0.1; // coyote time before access.timing_scale
const WORLD_W = 1600;
const GROUND_Y = 300;
const PLAYER_SIZE = 20;
const BOX_SIZE = 44;
const WORLD_PAD = 640; // background drawn this far past both ends, so a shaking camera never shows the void
const BOX_X = 560;
const PLAYER_START_X = 500;
const REACH = 75; // px between centers for a hit to land
const MOVE_SPEED = 190; // px/s
const GRAVITY = 1500; // px/s^2
const JUMP_SPEED = 540; // px/s
const HIT_TRAUMA = 0.6;
const HIT_FREEZE_S = 0.08;
const HIT_SQUASH = 0.45; // spring kick on the box
const FLASH_ALPHA = 0.7; // full strength (flash_limit off): still rate-limited
const FLASH_ALPHA_GENTLE = 0.3; // flash_limit on (the default): toned down as well
const FLASH_FADE_S = 0.12;
const MAX_DT = 0.1;

export class JuiceScene extends Phaser.Scene {
  private player!: Phaser.GameObjects.Rectangle;
  private guardRing!: Phaser.GameObjects.Rectangle;
  private box!: Phaser.GameObjects.Rectangle;
  private ground!: Phaser.GameObjects.Rectangle;
  private flashRect!: Phaser.GameObjects.Rectangle;
  private shake = new Shake();
  private hitstop = new Hitstop();
  private spring = new Spring();
  private flashes = new FlashLimiter();
  private follow = new FollowCamera();
  private buffer = new InputBuffer();
  private coyote = new CoyoteTimer();
  private timingK = 1; // the access.timing_scale the windows were made for (#166)
  private attackRepeat = new AutoRepeat(); // access.auto_repeat: a held attack repeats
  private guard = new HoldToggle();
  private vx = 0;
  private vy = 0;
  private flash = 0;
  private clock = 0;

  constructor() {
    super("juice");
  }

  create(): void {
    shell.setObjective(shell.i18n.t("demo.objective")); // what "What now?" on the pause menu says (#167)
    const { width, height } = this.scale;
    const pal = shell.palette();
    this.shake = new Shake();
    this.hitstop = new Hitstop();
    this.spring = new Spring();
    this.flashes = new FlashLimiter();
    this.buffer = new InputBuffer();
    this.coyote = new CoyoteTimer();
    this.guard = new HoldToggle();
    this.vx = this.vy = this.flash = this.clock = 0;
    this.add.rectangle(-WORLD_PAD, -height, WORLD_W + 2 * WORLD_PAD, height * 3, 0x1d2b53).setOrigin(0, 0);
    for (let x = 0; x <= WORLD_W; x += 160) this.add.rectangle(x, GROUND_Y - 120, 4, 120, 0x29366f).setOrigin(0, 0); // posts show camera motion
    this.ground = this.add.rectangle(-WORLD_PAD, GROUND_Y, WORLD_W + 2 * WORLD_PAD, height + 200, pal.ground).setOrigin(0, 0);
    this.box = this.add.rectangle(BOX_X, GROUND_Y, BOX_SIZE, BOX_SIZE, pal.target).setOrigin(0.5, 1);
    this.player = this.add.rectangle(PLAYER_START_X, GROUND_Y, PLAYER_SIZE, PLAYER_SIZE, pal.player).setOrigin(0.5, 1);
    this.guardRing = this.add.rectangle(PLAYER_START_X, GROUND_Y + 4, PLAYER_SIZE + 12, PLAYER_SIZE + 12).setOrigin(0.5, 1).setStrokeStyle(3, pal.accent).setVisible(false);
    this.flashRect = this.add.rectangle(-width, -height, width * 3, height * 3, 0xffffff).setOrigin(0, 0).setScrollFactor(0).setDepth(100).setAlpha(0);
    this.follow = new FollowCamera({ x: this.player.x, y: GROUND_Y - height * 0.25 });
    shell.subtitles.say("demo.welcome");
  }

  private hit(): void {
    const a = shell.settings.access;
    this.shake.addTrauma(HIT_TRAUMA);
    this.hitstop.hit(HIT_FREEZE_S);
    this.spring.x = HIT_SQUASH;
    if (this.flashes.request(this.clock)) this.flash = a.flash_limit ? FLASH_ALPHA_GENTLE : FLASH_ALPHA; // limiter: always, on real time
    shell.subtitles.caption("hit");
    shell.subtitles.say("demo.ouch");
  }

  update(_time: number, deltaMs: number): void {
    const realDt = Math.min(deltaMs / 1000, MAX_DT);
    const s = shell.settings;
    const pal = shell.palette();
    this.clock += realDt;
    const dt = this.hitstop.scaledDt(realDt) * s.access.game_speed;
    const input = shell.input;

    // access.timing_scale (#166): every timing window, longer by the player's factor
    if (s.access.timing_scale !== this.timingK) {
      this.timingK = s.access.timing_scale;
      this.buffer = new InputBuffer(INPUT_BUFFER_S * this.timingK);
      this.coyote = new CoyoteTimer(COYOTE_S * this.timingK);
    }
    // input: presses are buffered, so a jump pressed just before landing still happens
    if (input.takePress("jump")) this.buffer.press("jump");
    const repeat = this.attackRepeat.update(dt, input.isDown("attack")) && s.access.auto_repeat;
    if ((input.takePress("attack") || repeat) && Math.abs(this.player.x - this.box.x) < REACH) this.hit();
    this.buffer.update(dt);
    const guarding = this.guard.update(input.isDown("interact"), s.access.hold_to_toggle);

    // movement and gravity (no physics engine: the demo is about feel, not collisions)
    const dir = (input.isDown("move_right") ? 1 : 0) - (input.isDown("move_left") ? 1 : 0);
    this.vx = guarding ? 0 : dir * MOVE_SPEED;
    const grounded = this.player.y >= GROUND_Y && this.vy >= 0;
    this.coyote.update(dt, grounded);
    if (this.coyote.canJump() && this.buffer.consume("jump")) {
      this.vy = -JUMP_SPEED;
      this.coyote.consume();
    }
    this.vy += GRAVITY * dt;
    this.player.x = Phaser.Math.Clamp(this.player.x + this.vx * dt, PLAYER_SIZE, WORLD_W - PLAYER_SIZE);
    this.player.y += this.vy * dt;
    if (this.player.y >= GROUND_Y) {
      this.player.y = GROUND_Y;
      this.vy = 0;
    }
    this.guardRing.setPosition(this.player.x, this.player.y + 6).setVisible(guarding).setStrokeStyle(3, pal.accent);

    // the box squashes on a spring (volume kept), colors follow the colorblind setting
    const [sx, sy] = squash(this.spring.update(dt));
    this.box.setScale(sx, sy).setFillStyle(this.spring.x > 0.15 ? pal.hit : pal.target); // hit color while the kick lasts (not a flash)
    this.player.setFillStyle(pal.player);
    this.ground.setFillStyle(pal.ground);

    // the flash fades on real time; the camera follows and shakes on game time (a hitstop freezes both)
    this.flash = Math.max(0, this.flash - (realDt / FLASH_FADE_S) * FLASH_ALPHA);
    this.flashRect.setAlpha(this.flash);
    const cam = this.cameras.main;
    const f = this.follow.update(dt, this.player.x, this.player.y - this.scale.height * 0.25, this.vx, 0);
    const o = this.shake.update(dt, effectiveShake(s));
    cam.setScroll(f.x - this.scale.width / 2 + o.x, f.y - this.scale.height / 2 + o.y);
    cam.setRotation(o.angle);
  }
}
