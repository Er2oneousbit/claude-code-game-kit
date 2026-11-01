# SOP-18: Game feel ("juice")

## Goal
Every action the player takes answers back: a hit lands with weight, a jump that should have worked does, the camera
keeps the action in view, and none of it makes anyone sick or puts anyone at risk. Juice is tuning, not decoration:
it comes after the mechanic works (F4) and before anyone judges whether it is fun.

Run it with `/game-feel`.

## 1. Pick the moments, not the effects
List the five to ten moments that matter most (hit, get hit, jump, land, pick up, open, die, win) and, for each, what
the player should feel ("heavy", "snappy", "relief"). Then pick at most two or three effects per moment from step 2.
Stacking every effect on every event is noise; the strongest moment should get the strongest response.

## 2. The kit's juice module
Every engine overlay ships the same engine-free module (its file names: `docs/ENGINE.md`), tested against one shared
set of expected values, `data/golden/juice.json`, written by `tools/golden_vectors.py` (the reference: change it there
first, then the port; K01).

| Piece | What it does | Tunables (defaults) | Typical use |
|---|---|---|---|
| Shake | Trauma 0 to 1 per hit, decays linearly; the offset is trauma squared times smooth noise (tip: E89) | max offset 8 px, max angle 0.05 rad, decay 1.5/s, frequency 15 Hz, seed | Hits, explosions, landing from high |
| Hitstop | Freezes game time for a moment; overlapping hits keep the longest, capped | cap 0.25 s; per hit 0.03 to 0.1 s | Melee hits, parries, a boss's final blow |
| Easing | 14 curves (quad, cubic, sine, back, elastic, bounce; in, out, in-out) | none | UI motion, pickups flying to the HUD, doors |
| Follow camera | A deadzone box, look-ahead along velocity, exponential smoothing that is the same at any frame rate (E91, checked by K01) | deadzone 64x48 px, look-ahead 0.25 s, smoothing 8/s | Platformers, top-down |
| Input buffer | Remembers a press for a short window, so a jump pressed just before landing happens | 0.12 s | Jump, attack, dash |
| Coyote time | A short grace window to jump after leaving a ledge | 0.1 s | Platformers |
| Spring and squash | A damped spring for recovery; a volume-keeping squash/stretch scale | 4 Hz, damping 0.5 | Landing squash, UI pop, wobble |
| Flash limiter | Refuses a full-screen flash past three in any one second (F34) | 3 per 1.0 s | Hit flashes, lightning, explosions |

Shake, easing, the follow camera, the input buffer, coyote time and the spring run on game time you pass in (`dt`
after hitstop and the game-speed setting). Hitstop and the flash limiter take real, unscaled time (the frame's own
delta), or a slowed game could let more than three flashes through in a real second. None of it reads a global
clock or random number generator: the same inputs give the same frames, in tests and in replays.

## 3. Rules that protect players (A)
- **Every shake, camera bob and full-screen effect can be turned off** (F33); an intensity slider is the form the
  guideline's examples use, and the kit gives one. The shell's settings give `shake_scale` (0 to 100 %) and
  `reduce_motion`; pass `effective_shake(settings)` as the shake's
  intensity, and turn camera bob, screen-wide pulses and parallax wobble off with reduce motion.
- **No more than three full-screen flashes in any one second, and prefer removing a trigger to warning about it**
  (F34). The flash limiter is always on: no setting turns it off. The player's `flash_limit` setting (on by default)
  also tones full-screen flashes down. Counting flashes is the minimum, not proof of safety: luminance, red flashes,
  long low-intensity flicker and high-contrast stripes also fail (E73, E74). For anything bright the design needs,
  remove or soften it first; if it stays, check a recording with a flash analysis tool (E73 lists the Harding FPA
  test) before release.
- **Effects never hide information.** A shake or flash must not cover the HUD or a telegraph the player needs to read.

## 4. Tuning (standard practice)
1. Put every number in the constants block or a data file (`docs/STYLE.md`); expose the important ones in a debug
   panel and change them while the game runs.
2. Record a burst before and after (`dev.py smoke --record`, CLAUDE.md "While building") and compare frame by frame:
   a hit should read in the first two or three frames.
3. Start strong and cut back. A first pass is usually too weak to notice; halve it once it is visible.
4. Test at 30 and at 144 frames per second, or step `dt` in a unit test: anything that changes with the frame rate is
   a bug (the follow camera's exam does exactly this, K01).
5. Playtest with one question (SOP-03): "did that feel like it hit?" Write the answer down with the tuning values.

## Engine notes
Each overlay's `docs/ENGINE_FLOW.md` names the files. Shake moves the camera (Godot `Camera2D.offset`, Phaser
`camera.scrollX`, LÖVE `love.graphics.translate` before drawing the world, Unity and Unreal the camera transform),
never the world. Hitstop scales the game's delta, not the engine's global time scale, so menus and audio keep running.

## Done when
- The moment list exists with the effects chosen for each.
- Juice numbers live in one place and a debug panel or file reload changes them live.
- Shake intensity follows the settings and reduce motion turns it off; flashes go through the flash limiter.
- The juice tests pass against `data/golden/juice.json`; a recorded burst shows each key moment.

## Common mistakes
- Juicing a mechanic that is not fun yet. Juice makes good actions feel great; it does not fix a boring loop (F4).
- Random offsets per frame for shake: they jitter instead of shaking. Use smooth noise.
- Hitstop through the engine's global time scale, which also freezes menus, tweens and audio.
- Lerping by a fixed fraction per frame: the camera gets twice as stiff at twice the frame rate.
- No off switch for shake or flashes. Some players cannot play without one (F33, F34).
