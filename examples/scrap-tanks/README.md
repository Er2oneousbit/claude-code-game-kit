# Scrap Tanks

![Scrap Tanks: the cover-using bot clears three waves of raiders](docs/scrap-tanks.gif)

A one-screen tank brawl in a scrapyard: your tractor-tank against raiders whose behavior tree you can read over their
heads (FLANK, FIRE, COVER, and RETREAT for the heavy; scouts fight to the end). Shells stop at crates, rocks and trees, so where you stand matters more than how fast
you click. Made with the [Claude Code Game Kit](../../README.md) as its **C++ / SDL3 example** (SDL2 until kit 0.14), built only with what the
kit provides: Kenney CC0 3D models rendered into sprite sheets with the kit's Blender tools, a behavior tree built by
SOP-14, and a scenario pair that proved the main pillar wrong three times before it held. Step by step:
[HOW_IT_WAS_MADE.md](HOW_IT_WAS_MADE.md).

## Play it
Needs CMake 3.21+, a C++17 compiler and vcpkg (on Windows, Visual Studio 2022 Build Tools include all three), and Python
3.8+. Set `VCPKG_ROOT` and put CMake on `PATH` (`docs/ENGINE.md`). The first build fetches SDL3 and its image, font and
sound libraries (a few minutes).
```
python tools/dev.py run
```
The kit's shell (kit 0.14.4: title, main menu, settings with rebinding, pause, credits) wraps the fight. WASD to drive
(tank controls), mouse to aim, left click, Space or the bound attack key to fire, R to restart, Escape to pause. Gamepad:
left stick drives (how far it leans sets the speed; the Stick deadzone and Invert vertical stick settings apply), right
stick aims, right trigger or A fires, Back restarts, Start pauses. Red labels are coming for you; blue ones are hiding.
A tap of fire while the gun reloads still fires when it is ready (longer with Accessibility > Timing windows), and
Accessibility > Hold actions toggle makes fire an auto-fire switch: press once to keep firing, again to stop.

Game options go after `--`, for example `build/debug/bin/Debug/scrap_tanks.exe -- --debug-ai`:
`--autoplay skilled|reckless` (a bot plays), `--seed N` (same seed, same fight), `--god`, `--debug-ai` (raider paths,
chosen spots, who can hit you, the tree).

## How it is built
| Piece | File |
|---|---|
| The whole fight, engine-free and fixed-step: tanks, shells, cover, scrap, waves | `src/core/Sim.cpp`, `src/core/Tuning.hpp` |
| A small behavior-tree library (ADR 0002) and the raiders' tree | `src/core/Bt.hpp`, `src/core/EnemyBrain.cpp` |
| Cover and firing spots, aim leading, grid A* | `src/core/Tactics.cpp`, `src/core/Nav.cpp` |
| Autoplay bots: `skilled` hides by exposure count, `reckless` charges | `src/core/Bot.cpp` |
| The camera and which of 32 sprite rows faces where | `src/core/View.hpp` |
| SDL side: sprites, labels, HUD, sound, input (ADR 0001: SDL3_image, SDL3_ttf, SDL3_mixer) | `src/game/` |
| Kenney 3D models to sprite sheets, one table | `tools/make_sprites.py` |

## Checks
```
python tools/dev.py check && python tools/dev.py test      # 110 test cases (72 are the kit's: fixed timestep, golden vectors, audio, shell files, menus, analog input, motor access, crash and bug reports), the pillar check plays 80 fights
python tools/dev.py smoke --frames 30000 --timeout 900 --until RUN_WON --fail-on PLAYER_DESTROYED -- --autoplay skilled --seed 7
python tools/dev.py smoke --frames 30000 --timeout 900 --until PLAYER_DESTROYED --fail-on RUN_WON -- --autoplay reckless --seed 7
python tools/dev.py smoke --drive menus                   # the shell: settings changed, saved, quit
python tools/dev.py smoke --drive pseudo --locale pseudo  # every shell label bracketed and 40 % longer: nothing clipped or untranslated
python tools/dev.py smoke --drive crash                   # exit 1 on purpose: CRASH_WRITTEN names the crash file
python tools/access/sweep.py                              # the accessibility sweep over the shell's screens
```

## Credits and licenses
- Game: copyright er2oneousbit, all rights reserved, free to read, run, study and reference (`../LICENSE.md`).
  Kit-provided files stay MIT (`../../LICENSE`).
- 3D models (rendered to sprites) and font: [Kenney](https://kenney.nl) (Car Kit, Tower Defense Kit, Kenney Fonts), CC0.
  Details and license copies: `docs/ASSET_LOG.md`, `docs/licenses/`.
- Sound effects and the scrapyard wind: Created in collaboration with ElevenLabs (elevenlabs.io) (generated with the kit's `tools/audio/wavesmith/eleven_audio.py` under non-commercial terms, so **non-commercial**: marked PLACEHOLDER in `docs/ASSET_LOG.md`, replace or regenerate under a license that allows commercial use before any commercial use). Earlier builds used Kenney Sci-fi Sounds (CC0).
- Libraries: SDL3, SDL3_image, SDL3_ttf, SDL3_mixer (zlib), doctest (MIT), via vcpkg.
