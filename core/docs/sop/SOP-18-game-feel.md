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
first, then the port; K01). In RPG Maker MZ it is the GameJuice plugin, and GameAccess routes MZ's own shake and flash
(`$gameScreen.startShake`, `$gameScreen.startFlash`) through the player's settings and the flash limiter
(docs/ENGINE_FLOW.md, "The shell, juice and accessibility in MZ").

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
| Recipe helpers | `impact` (hit confirm scaled by damage), `float_text` (a damage number's rise, pop and fade), `trail_push` / `trail_shrink` / `trail_length` (a tracer's path, by distance) | their keyword defaults | Step 4's recipes |

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
- **Blood can be turned off.** The shell's `content.blood` setting (on by default, the "Blood" row; #171) is read
  with `blood_enabled(settings)`. Off means no blood particles, decals or red hit splashes: draw a neutral version
  in their place (sparks or dust in the hit surface's colour), so a hit still reads. Hit feedback never depends on
  blood alone. The effect is the game's own; a game with no blood hides the row (`SHOW_BLOOD_SETTING = false`).

## 4. Effects built from the primitives (recipes)
The kit does not ship every effect a game might want: it ships the primitives above and these recipes, and a game
builds the effect it needs when it needs it, in its own code, with its own test. Three small helpers in the juice
module carry the parts that are easy to get wrong (their spec is `tools/golden_vectors.py`, their cases are in
`data/golden/juice.json`, every engine's juice test runs them): `impact` (a hit confirm scaled by damage),
`float_text` (a damage number's motion) and `trail_push` / `trail_shrink` / `trail_length` (a tracer's point history,
by distance). Everything else below is a composition. Numbers are starting points; tune them (step 5).

| Effect | Built from | Tunables (start) | Rule |
|---|---|---|---|
| Hit confirm | `impact(damage, full)` gives hitstop, trauma and whether to flash; `Hitstop.hit`, `Shake.add_trauma`, then the flash only if `FlashLimiter.request(real now)` says yes | hitstop 0.03 to 0.1 s, trauma 0.15 to 0.6, flash from half of `full` | The biggest confirm stays under the hitstop cap; the shake goes through `effective_shake`; `flash_limit` on tones the flash down (step 3) |
| Damage number | `float_text(age)` each frame: add `dy` to its y, draw it at `scale` and `alpha`, free it when `done` | life 0.8 s, rise 24 px, pop 0.12 s | Age it on game time (it holds during hitstop); with reduce motion pass rise 0 and pop 0 |
| Knockback | An impulse along the hit direction, decayed by `v *= exp(-decay * dt)` on game time | 220 px/s, decay 12/s | Hitstop freezes it (dt 0); test the distance at 30 and 144 fps |
| Recoil | A `Spring` on the weapon's (or shooter's) offset along minus the aim: add the kick to its velocity per shot; an `InputBuffer` keeps a press made during the cooldown | kick 60 px/s, 6 Hz, damping 0.5 | Game time; a held fire button repeats on the cooldown, not per frame |
| Directional camera kick | A second `Spring` on the camera offset along the shot or hit direction, added on top of the shake | kick 40 px/s, 5 Hz, damping 0.6 | Scaled by `effective_shake(settings)`; reduce motion turns it off |
| Landing squash | `amount = max * ease("out_quad", (fall speed - min) / (max speed - min))`, set as the spring's `x`, then `squash(spring.update(dt))` each frame | squash 0.3 from 200 to 600 px/s, 4 Hz | Game time; the volume stays the same |
| Pickup pop | `Spring` with `x = -0.3` scales the pickup by `1 + x`; it flies to the HUD on `ease("in_back")` | 0.4 s flight | UI motion off with reduce motion: snap instead |
| Dash afterimages | Every interval of game time while dashing, copy the sprite at its position; each copy fades on `1 - ease("in_quad", age / life)`; drop the oldest past the cap | every 0.04 s, life 0.2 s, at most 5 | A test checks the count never passes the cap |
| Shell casings, death bursts | Pooled particles (Dotwork `vfx`: `debris`, `dust_particles`), at most N a second through a second `FlashLimiter` used as a rate cap | 8 a second | Pool them; pause their speed during hitstop |
| Bullet spread | `angle = aim + spread * noise(seed, shot_index, 3)` (the shake's noise at whole numbers: one lattice value per shot) | spread 0.08 rad | No random number generator, so tests and replays repeat |
| Slow motion on a kill | The game-speed value eased from slow back to 1 on real time: `speed = slow + (1 - slow) * ease("in_quad", t / length)`; game dt = real dt times speed | 0.3 for 0.6 s | The flash limiter keeps real time, so slow motion lets no more flashes through |
| Muzzle flash (#164) | Dotwork `muzzle_flash` at the barrel tip, turned to the aim plus a little `noise` per shot, scaled 0.9 to 1.1 | 3 frames at 30 fps | A local sprite, not a full-screen flash: no limiter needed |
| Tracer (#164) | Dotwork `tracer` (or any projectile with `"trail": "tracer"`): each frame `points = trail_push(points, x, y, spacing, length)` (the manifest's `tracer` field gives spacing, length, width and colours); after the hit, `trail_shrink(points, speed * dt)` until fewer than two points are left | spacing 4 px, length 4 canvas sizes | Game time; draw nothing for fewer than two points |
| Firing light pulse (#164) | Dotwork `muzzle_light` (Godot: its PointLight2D; other engines: the manifest's `light` field), started only when `FlashLimiter.request(real now)` allows | 4 frames at 30 fps | Rapid fire must not strobe: a refused pulse is skipped (the muzzle flash still shows); `flash_limit` on halves the energy |
| Wall-impact debris (#164) | Dotwork `debris` for the hit surface (one entry per terrain, colours from `sample`), turned to the surface normal, plus a `dust` puff and a hit spark | 8 chips, at most 8 bursts a second | Pooled and rate-capped; paused during hitstop; the wall itself does not change |

**Adding one in a game:** pick the row, write it in the game's code with its numbers in the constants block, and
add a test of the rule in its last column (for knockback: the distance travelled is the same at 30 and 144 fps).
Do not change the kit's juice module for it.

**When the kit grows:** an effect joins the juice module and `data/golden/juice.json` only when the table cannot
build it from the primitives and every engine port would need the same logic (as the tracer's point history did,
#164). Then change `tools/golden_vectors.py` first, `--write`, and port it to every engine with the juice module.

## 5. Tuning (standard practice)
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
- Every effect built from a step 4 recipe has a test of its rule in the game's own tests.

## Common mistakes
- Juicing a mechanic that is not fun yet. Juice makes good actions feel great; it does not fix a boring loop (F4).
- Random offsets per frame for shake: they jitter instead of shaking. Use smooth noise.
- Hitstop through the engine's global time scale, which also freezes menus, tweens and audio.
- Lerping by a fixed fraction per frame: the camera gets twice as stiff at twice the frame rate.
- No off switch for shake or flashes. Some players cannot play without one (F33, F34).
