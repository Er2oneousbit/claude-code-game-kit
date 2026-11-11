// ---------------------------------------------------------------------------
// JuiceWorld.ts
// Purpose : The juice demo (main menu "Juice demo" in debug builds) in 3D: every juice module in one toy. Hit the
//           box (attack) for trauma shake, hitstop, a spring squash and a limited screen flash; walk and jump
//           with a follow camera (deadzone, look-ahead), an input buffer and coyote time; hold interact to guard.
// Usage   : Registered in src/main.ts as world "juice"; the shell starts it (shell.startGame("juice")).
// Notes   : The web overlay's JuiceScene.ts in meters on a side-on stage (x along the ground, y up, the camera on
//           +z): same modules, same order, numbers scaled at 40 px per meter. The player's settings feed the juice
//           live: effectiveShake (reduce_motion, shake_scale), flash_limit (gentle flashes), hold_to_toggle (guard),
//           timing_scale (buffer and coyote windows), auto_repeat (held attack), game_speed (dt), colorblind (this
//           demo's palette only, drawn unlit so the colours on screen are the ones tools/access/colour_check.py
//           checked). The FlashLimiter is ALWAYS on (at most 3 full-screen flashes per real second); flash_limit
//           only tones each flash down further. Time: Hitstop.scaledDt and FlashLimiter.request take real time
//           (before hitstop and game_speed); shake, follow, input buffer, coyote and spring take game time (after
//           both), so a hitstop freezes the impact frame, shake included. Shake moves the camera sideways and up
//           (offset) and rolls it (angle). A sample subtitle line plays on start, a bark and a caption on hits.
//
// Pseudocode (per frame):
//   gameDt = hitstop.scaledDt(realDt) * game_speed ; buffer, coyote, spring, follow and shake use gameDt
//   move, gravity ; jump when grounded-or-coyote and the buffer holds a jump press
//   attack in reach -> trauma, hitstop, spring kick, flash if the limiter allows (gentler with flash_limit)
//   camera = follow(player) + shake offset and roll
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import * as THREE from "three";
import { AutoRepeat } from "../core/autoRepeat";
import { CoyoteTimer } from "../core/coyoteTimer";
import { FlashLimiter } from "../core/flashLimiter";
import { FollowCamera } from "../core/followCamera";
import { Hitstop } from "../core/hitstop";
import { HoldToggle } from "../core/holdToggle";
import { INPUT_BUFFER_S, InputBuffer } from "../core/inputBuffer";
import { effectiveShake } from "../core/settings";
import { Shake } from "../core/shake";
import { Spring, squash } from "../core/spring";
import { shell } from "../shell/app";
import type { World } from "./threeHost";

// ---- Tunables ----------------------------------------------------------------
const COYOTE_S = 0.1; // coyote time before access.timing_scale
const WORLD_W = 40; // m of ground the player can walk
const WORLD_PAD = 30; // ground drawn this far past both ends, so a shaking camera never shows the void
const PLAYER_SIZE = 0.5;
const BOX_SIZE = 1.1;
const BOX_X = 14;
const PLAYER_START_X = 12.5;
const REACH = 1.9; // m between centers for a hit to land
const MOVE_SPEED = 4.75; // m/s
const GRAVITY = 37.5; // m/s^2
const JUMP_SPEED = 13.5; // m/s
const POST_EVERY = 4; // m: posts show camera motion
const POST_H = 3;
const HIT_TRAUMA = 0.6;
const HIT_FREEZE_S = 0.08;
const HIT_SQUASH = 0.45; // spring kick on the box
const FLASH_ALPHA = 0.7; // full strength (flash_limit off): still rate-limited
const FLASH_ALPHA_GENTLE = 0.3; // flash_limit on (the default): toned down as well
const FLASH_FADE_S = 0.12;
const CAM_DIST = 9; // m from the stage
const CAM_LIFT = 1.4; // m the camera looks above the player
const SHAKE = { maxOffset: 0.2, maxAngle: 0.05 }; // m and radians at full trauma (2D: 8 px)
const FOLLOW = { deadzoneW: 1.6, deadzoneH: 1.2 }; // m (2D: 64 x 48 px)
const SKY = 0x1d2b53;
const POST = 0x29366f;
const EDGE = 0x000000;

/** An unlit box whose origin is the middle of its base (it squashes onto the ground), with dark edges for shape. */
function block(size: number, colour: number): { mesh: THREE.Mesh; mat: THREE.MeshBasicMaterial } {
  const geo = new THREE.BoxGeometry(size, size, size).translate(0, size / 2, 0);
  const mat = new THREE.MeshBasicMaterial({ color: colour });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: EDGE })));
  return { mesh, mat };
}

export class JuiceWorld implements World {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private readonly player: THREE.Mesh;
  private readonly playerMat: THREE.MeshBasicMaterial;
  private readonly box: THREE.Mesh;
  private readonly boxMat: THREE.MeshBasicMaterial;
  private readonly groundMat: THREE.MeshBasicMaterial;
  private readonly guardRing: THREE.Mesh;
  private readonly guardMat: THREE.MeshBasicMaterial;
  private readonly flashMat: THREE.MeshBasicMaterial;
  private readonly shake = new Shake(SHAKE);
  private readonly hitstop = new Hitstop();
  private readonly spring = new Spring();
  private readonly flashes = new FlashLimiter();
  private readonly follow: FollowCamera;
  private buffer = new InputBuffer();
  private coyote = new CoyoteTimer();
  private timingK = 1; // the access.timing_scale the windows were made for (#166)
  private readonly attackRepeat = new AutoRepeat(); // access.auto_repeat: a held attack repeats
  private readonly guard = new HoldToggle();
  private vx = 0;
  private vy = 0;
  private flash = 0;
  private clock = 0;

  constructor(aspect: number) {
    shell.setObjective(shell.i18n.t("demo.objective")); // what "What now?" on the pause menu says (#167)
    const pal = shell.palette();
    this.scene.background = new THREE.Color(SKY);
    this.camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 200);

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(WORLD_W + 2 * WORLD_PAD, 40), (this.groundMat = new THREE.MeshBasicMaterial({ color: pal.ground })));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(WORLD_W / 2, 0, -10);
    this.scene.add(ground);
    for (let x = 0; x <= WORLD_W; x += POST_EVERY) {
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.1, POST_H, 0.1).translate(0, POST_H / 2, 0), new THREE.MeshBasicMaterial({ color: POST }));
      post.position.set(x, 0, -1.5);
      this.scene.add(post);
    }
    ({ mesh: this.box, mat: this.boxMat } = block(BOX_SIZE, pal.target));
    this.box.position.set(BOX_X, 0, 0);
    ({ mesh: this.player, mat: this.playerMat } = block(PLAYER_SIZE, pal.player));
    this.player.position.set(PLAYER_START_X, 0, 0);
    this.guardMat = new THREE.MeshBasicMaterial({ color: pal.accent });
    this.guardRing = new THREE.Mesh(new THREE.TorusGeometry(PLAYER_SIZE * 0.85, 0.05, 8, 32), this.guardMat);
    this.guardRing.visible = false;
    this.scene.add(this.box, this.player, this.guardRing);

    // the flash: a white quad just in front of the camera, over everything, faded by opacity
    this.flashMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthTest: false, depthWrite: false });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), this.flashMat);
    quad.position.z = -0.2;
    quad.renderOrder = 100;
    this.camera.add(quad);
    this.scene.add(this.camera);

    this.follow = new FollowCamera({ ...FOLLOW, x: PLAYER_START_X, y: CAM_LIFT });
    this.place({ x: PLAYER_START_X, y: CAM_LIFT }, { x: 0, y: 0, angle: 0 });
    shell.subtitles.say("demo.welcome");
  }

  resize(aspect: number): void {
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
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

  /** Camera on +z looking at the followed point, moved and rolled by the shake. */
  private place(f: { x: number; y: number }, o: { x: number; y: number; angle: number }): void {
    this.camera.position.set(f.x + o.x, f.y + o.y + 1, CAM_DIST);
    this.camera.lookAt(f.x + o.x, f.y + o.y, 0);
    this.camera.rotateZ(o.angle);
  }

  update(realDt: number): void {
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
    if ((input.takePress("attack") || repeat) && Math.abs(this.player.position.x - this.box.position.x) < REACH) this.hit();
    this.buffer.update(dt);
    const guarding = this.guard.update(input.isDown("interact"), s.access.hold_to_toggle);

    // movement and gravity (no physics engine: the demo is about feel, not collisions)
    const dir = (input.isDown("move_right") ? 1 : 0) - (input.isDown("move_left") ? 1 : 0);
    this.vx = guarding ? 0 : dir * MOVE_SPEED;
    const p = this.player.position;
    const grounded = p.y <= 0 && this.vy <= 0;
    this.coyote.update(dt, grounded);
    if (this.coyote.canJump() && this.buffer.consume("jump")) {
      this.vy = JUMP_SPEED;
      this.coyote.consume();
    }
    this.vy -= GRAVITY * dt;
    p.x = THREE.MathUtils.clamp(p.x + this.vx * dt, PLAYER_SIZE, WORLD_W - PLAYER_SIZE);
    p.y += this.vy * dt;
    if (p.y <= 0) {
      p.y = 0;
      this.vy = 0;
    }
    this.guardRing.position.set(p.x, p.y + PLAYER_SIZE / 2, 0);
    this.guardRing.visible = guarding;

    // the box squashes on a spring (volume kept), colours follow the colorblind setting
    const [sx, sy] = squash(this.spring.update(dt));
    this.box.scale.set(sx, sy, sx);
    this.boxMat.color.setHex(this.spring.x > 0.15 ? pal.hit : pal.target); // hit colour while the kick lasts (not a flash)
    this.playerMat.color.setHex(pal.player);
    this.groundMat.color.setHex(pal.ground);
    this.guardMat.color.setHex(pal.accent);

    // the flash fades on real time; the camera follows and shakes on game time (a hitstop freezes both)
    this.flash = Math.max(0, this.flash - (realDt / FLASH_FADE_S) * FLASH_ALPHA);
    this.flashMat.opacity = this.flash;
    const f = this.follow.update(dt, p.x, p.y + CAM_LIFT, this.vx, 0);
    this.place(f, this.shake.update(dt, effectiveShake(s)));
  }
}

// {{FOOTER}}
