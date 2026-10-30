# How Coyote Hop was made

One Claude Code session (Claude Opus 5.5) on Windows 11, Godot 4.7.2, 2026-10-21, with the user steering.
This page is the honest log: the commands, the order, what the kit caught, and what came from outside the kit.

## Iteration timeline: how the game changed after it first worked
| # | Day | Prompted by | What changed | Proof |
|---|---|---|---|---|
| 1 | 10-21 | Gray box first (sections 2 and 3) | Rectangles, then Kenney Pixel Platformer art and Kenney and SubspaceAudio sound, fetched with `fetch_asset.py` | Reachability test, autoplay bot 11/11 coins |
| 2 | 10-21 | Hand-placed coins the bot could never reach | Coins moved onto the measured jump arc (section 5) | Bot collects 11/11 |
| 3 | 10-22 | Exporting was untested in the kit | A shipped `export_presets.cfg`; `dev.py build` exports Windows, Linux and Web | The exported exe boots and the bot finishes in it |
| 4 | 10-22 | User playtest: "the player icon is horrible, looks like an alien" (every hero on the Kenney sheet wears a space helmet) | Two CC0 candidates mocked up on the real tiles; the Sunny Land fox won (idle, run and jump frames) | Same 8.52 s run, 11/11 coins; new GIF and gallery image |
| 5 | 10-22 | User: make audio, do not just fetch it | All effects and the music made with the kit's synth tools (`sfx_synth.py`, `chiptune.py`); the fetched audio left the project | FFT check of every sampled note against the song file; loops picked up by Godot; 24 GUT tests |
| 6 | 10-26 | A review that drove the real game tick by tick | Seven feel and flow bugs fixed (below, "Later: review fixes") | 14 new GUT tests (10 scene tests fail on the old code); 38 tests; bot unchanged at 8.52 s |

The kit gained things from this game too: the fox swap became the "Later: a new hero" story, and the audio work became
`tools/audio/`, used afterwards by other examples.

## 1. Scaffold (kit)
```
python scripts/new_game.py --name "Coyote Hop" --engine godot --dest ../coyote-hop
```
It was first scaffolded with an earlier profile; it now uses the neutral default (no author footer). GUT 9.7.1 was copied into
`addons/gut/` (not committed, see `docs/ENGINE.md`) and `GODOT_BIN` pointed at the console build.

## 2. Design first (kit: `docs/GDD.md`, `docs/FIRST_HOUR.md`)
Filled the GDD identity block: one-line pitch, three pillars ("jumps feel fair", "tiny and finished", "numbers in one
place"), the core loop. Scope: one level, no menus. Anything else went to the Parking lot.

## 3. Gray box before art (kit: SOP-01, evidence F4 "mechanics before art")
- `scripts/game/tuning.gd`: every number (speed, gravity, jump, coyote time, buffer).
- `scripts/game/level_data.gd`: the level as data (platform rectangles), not a hand-placed scene.
- `scripts/core/jump_buffer.gd` and `jump_math.gd`: engine-free logic, unit tested like the kit's `coyote_timer.gd`.
- `tests/test_level_reachable.gd`: a design guard that fails if any gap is impossible with the current tuning.
- An `--autoplay` bot in `main.gd` that holds right and jumps at each ledge: the in-engine proof the level is beatable.

First playable was colored rectangles. `check`, 20 tests and `smoke` passed, and the bot finished in 7.3 s with 0 falls.

## 4. Real art and sound (kit: `/asset-intake`, SOP-04, `tools/fetch_asset.py`)
Sources came from the kit's lists (`docs/resources/art.md` and `audio.md` both name kenney.nl and opengameart.org).
The license was read on each asset's own page before fetching (all CC0). Each pack went in with one command, which
copied only the picked files, saved the license text in `docs/licenses/` (one file per asset ID), and added the `ASSET_LOG.md` row:
```
python tools/fetch_asset.py --url https://kenney.nl/media/pages/assets/pixel-platformer/33bb4921eb-1696667883/kenney_pixel-platformer.zip \
  --page https://kenney.nl/assets/pixel-platformer --author Kenney --license CC0 --type tileset \
  --to assets/art/pixel_platformer --take "Tilemap/tilemap_packed.png" --take "Tilemap/tilemap-characters_packed.png" \
  --take "Tilemap/tilemap-backgrounds_packed.png"
python tools/fetch_asset.py --url <kenney digital-audio zip> --page https://kenney.nl/assets/digital-audio --author Kenney \
  --license CC0 --type sfx --to assets/audio/sfx --take "Audio/phaseJump1.ogg" --take "Audio/pepSound1.ogg" --take "Audio/lowDown.ogg"
python tools/fetch_asset.py --url <kenney impact-sounds zip> ... --take "Audio/impactSoft_medium_000.ogg"
python tools/fetch_asset.py --url <kenney music-jingles zip> ... --take "Audio/8-Bit jingles/jingles_NES00.ogg"
python tools/fetch_asset.py --url <opengameart 5 Action Chiptunes zip> --page https://opengameart.org/content/5-chiptunes-action \
  --author "Juhani Junkala (SubspaceAudio)" --license CC0 --type music --to assets/audio/music --take "*Level 1.wav"
```
`tools/fetch_asset.py --url <zip> --list` shows a pack's files first. `--list` was how the tile sheets were found.

## 5. Reskin
- Kenney's tiles are 18 px, so the world moved to a tile grid with a 2x camera, and every tuning number was rescaled.
  The reachability test re-checked every gap against the new numbers before anything ran.
- `scripts/game/sprites.gd` does the atlas math, so code asks for "tile 151", not pixel rectangles.
  `docs/tilesheet-labelled.png` is the sheet with every index printed on it (made with a small Pillow script).
- Coins were placed on the arcs the bot actually flies (its path was printed once, the apex cells became coin cells).
  The bot now collects 11/11.
- Music looped through Godot's import option (`loop=true` in the old `level1.ogg.import`), not code.

### Later: a new hero (playtest feedback)
The first playtester's verdict on the hero: "looks like an alien". It was one: every character on Kenney's Pixel
Platformer sheet wears a space helmet. Two CC0 candidates were mocked up standing on the real grass tiles next to a coin
(a throwaway Pillow script): the fox from ansimuz's Sunny Land and Kenney's Tiny Dungeon heroes. The fox won. It has
the same dark outline and warm palette as the tiles, and real idle, run and jump frames, where the Tiny Dungeon heroes
face the camera. One command brought in the frames:
```
python tools/fetch_asset.py --url https://opengameart.org/sites/default/files/sunny-land-files.zip   --page https://opengameart.org/content/sunny-land-2d-pixel-art-pack --author "Luis Zuno (ansimuz)" --license CC0   --type sprite --base "Sunny-land-assets-files/PNG/sprites/player" --to assets/art/sunny_land_fox   --take "Sunny-land-assets-files/PNG/sprites/player/idle/*.png" --take "Sunny-land-assets-files/PNG/sprites/player/run/*.png"   --take "Sunny-land-assets-files/PNG/sprites/player/jump/*.png" --license-file Sunny-land-assets-files/public-license.txt
```
`Sprites.animations()` loads one PNG per frame into named animations (idle, run, jump; the jump uses frame 1 rising and
frame 2 falling). The fox faces right, the alien faced left, so the flip flipped. The Kenney characters sheet left the
project and its `ASSET_LOG.md` row.

### Later: sound and music made, not fetched
All the fetched audio was replaced with audio made by the kit's `tools/audio/` synth:
```
python tools/audio/sfx_synth.py jump --set volume=0.3 --out assets/audio/sfx/jump.wav --recipe assets/audio/src/jump.sfx.json
python tools/audio/sfx_synth.py coin --set volume=0.32 --out assets/audio/sfx/coin.wav --recipe assets/audio/src/coin.sfx.json
python tools/audio/sfx_synth.py fall --out assets/audio/sfx/fall.wav --recipe assets/audio/src/fall.sfx.json
python tools/audio/sfx_synth.py land --out assets/audio/sfx/land.wav --recipe assets/audio/src/land.sfx.json
python tools/audio/chiptune.py assets/audio/src/theme.song.json --out assets/audio/music/theme.wav
python tools/audio/chiptune.py assets/audio/src/goal.song.json --out assets/audio/music/goal.wav
```
- The theme is a song file Claude wrote: 16 bars at 150 bpm in C major (A section over C, Am, F, G; B section over
  F, G, Em, G), a square lead with vibrato, a quiet 25% pulse arpeggio, a triangle bass bouncing octaves, noise drums.
- Nobody on the AI side can hear it, so it was checked by measurement: an FFT of the solo lead and bass found every
  sampled note where the song file puts it, the loop seam has no jump, and Godot's movie writer recorded the game's
  own audio (a WAV next to the recorded frames, 32-bit: read it with `tools/audio/wavfile.py`), whose spectrogram shows the music, a rising sweep at each jump and
  the jingle at the goal. Whether it is any good is your call: play it.
- Loudness was matched to the old mix by measuring both (RMS): the new theme is 5 dB quieter, so `MUSIC_DB` went
  from -8 to -3; jump and coin were rendered quieter so square waves do not grate.
- The theme loops with no import tweak: `chiptune.py` writes loop points into the WAV and Godot's default import
  ("Detect From WAV") uses them. `tests/test_audio.gd` checks that.

### Later: review fixes (2026-10-26)
A review (Claude Fable 5.1) booted the real scene headless with a throwaway harness that pressed the input actions
tick by tick and measured what the fox did. Each confirmed bug got a fix and a regression test:
| Bug (measured) | Fix | Test |
|---|---|---|
| After the flag the fox could run off the level and fall forever (no respawn, no fall count); coins still counted | `main.gd` locks the player's controls at the flag (`Player.controls_enabled`), keeps the fall check running after it, ignores coins after it | `tests/test_run_flow.gd` |
| A tap pressed just before landing (buffered) jumped full height, 67 px, against about 19 px for a tap on the ground | `player.gd` cuts the jump whenever it is not held while rising, so a buffered tap released before touch-down is cut on take-off | `tests/test_player_jump.gd` |
| Tapping again in the air cut the hop a second time (13.8 px instead of 18.9) | One cut per jump | `tests/test_player_jump.gd` |
| The camera panned back from the death point after a fall or R | `Player.respawn()` resets the camera smoothing | `tests/test_run_flow.gd` |
| `JumpMath` ignored the physics step: apex 64.22 px on paper, 67.16 px in game | Optional `dt` term (semi-implicit Euler: `v + g dt / 2`); the reach stays at or under the ticks | `tests/test_level_reachable.gd` |
| The speedrun clock ran from boot | It starts on the first move or jump input, and again after R | `tests/test_run_flow.gd` |
| R left the goal jingle playing and the fox facing left | `_restart()` stops the jingle; `respawn()` faces the fox right | `tests/test_run_flow.gd` |

With the fixes, the shortest hop (a tap shorter than one physics tick) is 14.4 px on the ground and from the buffer
alike. The bot's run did not change (8.52 s, 11/11 coins, 0 falls): it presses right on the first tick, so the
clock starts when it did, and it holds jump to the apex, so the cut never touches it. One thing the tests taught: in
Godot 4.7.2 an `Input.action_press()` made at the start of a physics tick reads as just pressed only in the next tick
(a release is seen at once), so the scene tests wait one more tick before checking what R did.

## 6. What the kit caught
| Caught by | Problem | Fix |
|---|---|---|
| `dev.py check` | Assigned `loop` on a `preload`ed constant: a parse error that would have crashed boot | Loop set in the import settings |
| `dev.py smoke` | "Resources still in use at exit": quitting while the Ogg music played leaked the playback | No music in headless runs; stop audio and wait 0.1 s before quitting; window close goes through the same path |
| `dev.py test` | The new coin test failed although the bot collected every coin | The test was wrong (ignored the player's height); rewritten in pixels |
| The `--autoplay` bot | Hand-placed coins sat two tiles below the jump arc, never collectable | Coins moved onto the measured arc |

## 7. Outside the kit (be honest)
- **Music re-encode (earlier build):** the 13 MB WAV became a 2.4 MB OGG Vorbis with PyAV (`av` Python package), row A-0005 says
  `Modified: yes`. The kit has no audio converter. Use Audacity or ffmpeg if you prefer.
- **GIF:** Godot's movie writer (`godot --path . --write-movie frames/f.png --fixed-fps 30 -- --autoplay`) plus a short
  Pillow script that keeps every second frame and saves a looping GIF.
  That script became a kit tool afterwards: `python tools/art/frames_to_gif.py frames docs/coyote-hop.gif --every 2 --width 640`
  reproduces this GIF exactly (153 frames, 899 KB with the fox).
- **Labelled tilesheet and the bot's path trace:** throwaway Python and a temporary `print`, not kept.

## 8. Verified
| Check | Result |
|---|---|
| `python tools/dev.py check` | 16 files with GUT in `addons/gut/` (10 without: the tests need GUT to parse), 0 failed |
| `python tools/dev.py test` | 38/38 (GUT 9.7.1; 24 before the 2026-10-26 review fixes) |
| `python tools/dev.py smoke` | passed, 5 runs in a row |
| `godot --headless --path . -- --autoplay` | `GOAL_REACHED 8.52 s, 11/11 coins, 0 falls`, clean exit |
| `python tools/doctor.py`, `python tools/check_links.py` | healthy, no broken references |

Played by hand? The bot proves it can be finished; the feel (is coyote time 0.10 s right?) is a human call. Tune it in
`scripts/game/tuning.gd` and the reachability test tells you if you broke the level.
