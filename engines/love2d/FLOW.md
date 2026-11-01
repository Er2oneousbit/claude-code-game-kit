# LÖVE Flow

Engine-specific workflow for a LÖVE 11 / Lua project. Universal process lives in `docs/sop/`.

> **Tested.** Every command below ran against LÖVE 11.5 on Windows (2026-11-01), including planted syntax and runtime
> errors. macOS and Linux packaging is not run by the kit yet: marked **(verify)**.

## Daily loop
```
python tools/dev.py check      # compile every .lua with LÖVE's LuaJIT (tools/lovecheck), nothing runs
python tools/dev.py test       # tests/test_*.lua inside LÖVE, no window
python tools/dev.py smoke      # 120 frames in a small off-screen window; fails on errors, missing BOOT_OK
python tools/dev.py run        # the game window
```
Edit in VS Code with the "Lua" extension (sumneko) and add `love` to its `Lua.workspace.library` or the "Love2D
Support" extension for completions. LÖVE has no editor: assets come from Aseprite, Tiled, LDtk and the kit's tools.

## The universal commands, mapped to LÖVE
| dev.py | What it runs |
|---|---|
| `check` | `lovec tools/lovecheck <every .lua>` (all but the top-level `build/`, `captures/`, `.git/`, `.claude/`, `node_modules/`): a separate tiny LÖVE program compiles each file with `loadstring` (the game's own LuaJIT) and prints `CHECK_FAIL <file> <message>` |
| `test` | `lovec . --test [--filter name]`: `tests/runner.lua` runs every `test_*` function and prints `TESTS <run> passed <p> failed <f> files <n>`; 0 tests is exit 2, and any non-zero LÖVE exit (a crash after the summary, a timeout) fails the run |
| `smoke` | compiles conf.lua and main.lua first, then `lovec . --smoke N`: walks title > menu > play, passes on `BOOT_OK` and `SMOKE_DONE` (or `DRIVE_DONE` with `--drive`) with no `[ERROR]` / `[error]` lines and exit 0. `--headless` runs with no window. `--screenshot`, `--record`, `--compare`, `--drive`, `--data-dir`, `--locale`: see "Smoke scenarios" below |
| `run` | `love .` (the GUI build) |
| `build` | zips `main.lua`, `conf.lua`, `CREDITS.md`, `src/`, `assets/`, `data/` (not `data/golden/`) into `build/<game>.love`; on Windows fuses `love.exe` + the .love into `build/windows/<game>.exe` and copies LÖVE's DLLs and its license file (license.txt) next to it |
| `clean` | removes `build/` (`--yes` accepted, never asks) |
| `doctor` | LÖVE found, 11.4 or newer (warns on 12; fails when `--version` fails, warns when it prints no version), the boot files present, then `tools/doctor.py` |

Game options go after `--`: `python tools/dev.py smoke -- --seed 7` reaches the game as `KIT.rest`.

## Writing tests
```lua
-- tests/test_score.lua
local A = require("tests.assert")
local Score = require("src.core.score")
local T = {}
function T.test_combo_doubles() A.eq(Score.combo(2, 10), 40) end
return T
```
`A.eq`, `A.near(got, want, tol)`, `A.truthy`, `A.falsy`, `A.same(got, want, tol)` (deep, numbers within tol),
`A.raises(fn)`. Tests run with no window: keep `love.graphics` out of the code under test.

The juice and shell logic in `src/core/` is checked against the kit's golden vectors: `tests/test_juice_golden.lua`
and `tests/test_shell_golden.lua` load `data/golden/*.json` at test time and make one test per case (a case type
with no handler fails). Change behaviour in `tools/golden_vectors.py` first, `--write`, then fix the Lua until the
tests pass. JSON comes from `src/core/json.lua` (LÖVE has none): `null` is `Json.null`, and `Json.array({})` marks
a list that may be empty so it writes back as `[]`.
- `tests/test_audio_golden.lua`: `src/core/audio_director.lua` against `data/golden/audio.json`.
- `tests/test_music_golden.lua`: `src/core/music_director.lua` (grid, transition plans) against `data/golden/music.json`.
- `tests/test_access_golden.lua`: `src/core/audio_access.lua` (bus gains, caption arrows) against `data/golden/access.json`.
- `tests/test_music_player.lua`: the mixer of `src/shell/music_player.lua`, sample by sample, with no audio device.
- `tests/test_audio_wiring.lua`: bus volumes along the bus chain (`app:bus_volume`) and directional caption arrows.

## The runtime shell (src/shell/)
boot > title (press any key; asks for telemetry consent once per run while it is unset) > main menu (Play, Settings,
Credits, Quit, and Juice demo in a debug build = a run from the source folder) > loading (progress bar) > play
(`src/game/game.lua`) > pause (Resume, Settings, Quit to title; on the `pause` action and on focus loss).
- **Input:** keyboard and gamepad everywhere (`ui_up/down/left/right/accept/cancel`; cancel goes back one screen;
  the left stick works as the d-pad). The focused item has an outline and a `>` marker, not just a colour.
- **Settings** (tabs Display, Audio, Controls, Accessibility, Language): every field of the schema in
  `src/core/settings.lua`, applied as it changes, saved on Back. Controls lists the game actions with their prompt
  glyph (`assets/ui/glyphs/<glyph_name>.png` at 1x, else a text key-cap), rebinds with "press a key" (a binding
  taken from another action swaps onto it), marks clashes, resets to defaults; `glyph_set` follows the last device.
  Applied: text_scale and ui_scale (font size), subtitles (on, size, background, speaker names, barks),
  captions_sfx, reduce_motion and shake_scale (the shake intensity), flash_limit (gentler flashes; the 3-per-second
  limiter itself is always on), hold_to_toggle (the demo's guard), game_speed (the game's dt), difficulty (stored for
  the game), window mode, size, vsync, frame cap (never in automated runs), master volume and the sfx / ui buses.
  Stored only: `audio.mono` (LÖVE cannot downmix a stereo source; ship mono sources if you need it), and `voice`
  until the game plays voice; `music` drives the music player when data/music.json exists. `colorblind` swaps
  the juice demo's palette only (`src/shell/style.lua`), not a full-screen filter.
- **User data** in one folder: the save folder (`love.filesystem.getSaveDirectory()`), or `--data-dir <dir>`:
  `settings.json` (+ `.bak`), `save_<slot>.json` (+ `.bak`; the play screen saves slot 1 when you leave),
  logs/game.log (name, version and UTC time on line 1; 5 older logs as `game.1.log`..`game.5.log`),
  `crashes/crash_<timestamp>.txt` (version, seed from `-- --seed N`, the error, traceback and log tail; written by
  conf.lua's error handler), `telemetry.csv` (only after a Yes), `bug_<timestamp>/` (F8 in a debug build: screenshot,
  log tail, settings, info).
- **Telemetry** is local only: events go to `telemetry.csv` while `telemetry.consent` is `yes`, nothing is sent. To
  add an endpoint a game needs a privacy policy that says what is collected, why, how long it is kept and who
  receives it, a way to withdraw consent (the Language tab has the switch), and no sending before a Yes.
- **Localization:** `data/i18n/<locale>.json` (en complete, fr partial: missing keys fall back to English). Every
  visible string goes through `app:t(key, args)`; values a game makes up use `app:tv(value)`. Locale `pseudo` shows
  every string through `pseudo()`: accented, 40 % longer, in brackets.
- **Subtitles:** `data/dialogue/sample.built.json` (the dialogue.built.json v0 shape: lines with speaker, text, kind,
  priority, interrupt, cooldown, reveal times and cues; captions by sound event; unknown fields ignored).
  `app:say("guide.welcome")` shows a line; barks only with subtitle barks on. The typewriter reveals by the file's
  reveal times (`Subtitles.TYPEWRITER = false` shows the cue chunks instead).

## Smoke scenarios (`python tools/dev.py smoke --drive <scenario>`)
| Scenario | What it proves |
|---|---|
| (none) | title > menu > play, then the game runs for `--frames` (default 120) |
| `menus` | title > Settings > master volume 0.5, reduce motion on > Back (saves) > Quit; prints `SETTINGS_WRITTEN <path>` once the file holds both values. With consent unset it leaves no `telemetry.csv` |
| `crash` | raises an error in a frame: prints `CRASH_WRITTEN <path>`, exits 1 (expected) |
| `pseudo` | with `--locale pseudo`: visits every screen (each settings tab, top and scrolled), checks every visible label (wider than its box, past the screen edge, or not through `t()` = no leading `[`): `PSEUDO_FAIL` lines and exit 1, or `PSEUDO_PASS` |
| `pseudo-plant` | the same with one planted label too small for its text: must exit 1 naming `plant.too_small` |
| `bug` | presses F8 on the menu and checks the `bug_<timestamp>/` files: `DRIVE_BUG <path>` |
| `show:<screen>` | `title`, `settings` (a slider focused), `pause`, `subtitle`, `juice`: opens it and ends; add `--screenshot captures/<screen>.png` |

Add `--data-dir captures/run1` to keep a run's files out of the real save folder, and
`--compare <baseline.png> [--tolerance N] [--max-pixels N]` after `--screenshot` for a visual regression check
(`tools/image_diff.py`; exit 1 on a difference, a `_diff.png` next to the screenshot shows where). A scenario is a
coroutine in `src/shell/drive.lua`: add one there and list it here.

## Assets and audio
- Images: `love.graphics.newImage("assets/art/hero.png")` after `love.graphics.setDefaultFilter("nearest",
  "nearest")`. Sprite sheets: `love.graphics.newQuad`. Dotwork's non-Godot output (PNGs, sheets and a manifest)
  loads directly.
- Audio: `love.audio.newSource(path, "static")` for short sounds, `"stream"` for music. WAV and OGG are safe; MP3
  works through mpg123. Log every asset in `docs/ASSET_LOG.md`.
- Bus volumes: with data/audio_events.json, `app:bus_volume(bus)` (and `app:play_sound`) takes each slider once
  along the bus and its parents (`src/core/audio_access.lua`: ambience under sfx is not turned down twice); master
  is LÖVE's listener volume. Without that file a source gets the slider of its bus name, as before.
- Adaptive music: data/music.json (made and checked with `tools/audio/wavesmith/music.py`; stems under
  `assets/audio/`) plays through `src/shell/music_player.lua`; `app:play_music("combat")` changes track on the beat,
  bar, phrase or loop end the rule asks for. The player mixes the stems itself into a QueueableSource, so switches,
  fades and stingers are sample-exact in its mix; you hear them about 93 ms later (the queue) plus OpenAL's buffer.
  Stems are decoded whole into memory (about 10 MB per stereo minute) and must be at music.json's `sample_rate`.
- Directional captions: `app.subtitles:caption(id, { dx, dy, half_w, half_h })` adds an arrow to a caption marked
  `"directional": true` while the source is off screen (left-pointing arrows before the text, the rest after).
- Fonts: `love.graphics.newFont(path, size)` (TTF) or `love.graphics.newImageFont` for bitmap fonts; BMFont `.fnt`
  files load with `love.graphics.newFont("font.fnt")`.

## Profiling
- `love.timer.getFPS()` and `love.timer.getDelta()` on screen in debug builds; `collectgarbage("count")` for Lua
  memory (KB). Watch for garbage from tables created every frame.
- LuaJIT's profiler: `require("jit.p").start("Fl", "build/profile.txt")` in love.load, `.stop()` on quit (verify).

## Packaging
- **Windows:** `python tools/dev.py build` gives `build/windows/` with `<game>.exe` and the DLLs; zip that folder.
  The exe is `love.exe` with the game appended (LÖVE's documented fusing); LÖVE's zlib license file, license.txt, must ship with it.
  Change the exe's icon with a resource editor (rcedit) if you want your own (verify).
- **macOS:** copy `love.app`, put the .love in `Contents/Resources/`, edit `Info.plist` (bundle id, name); signing
  and notarization: docs/sop/SOP-21 (verify).
- **Linux:** the .love runs with an installed `love`; for a single file use an AppImage of LÖVE with the game
  fused in (verify).
- **Web:** love.js (a community port) can run 11.x games in a browser with limits (verify; no threads by default).

## Adopting an existing project
1. Run `new_game.py --adopt` into the project. Your `conf.lua` and `main.lua` stay; the kit's land as `.gold` files.
2. Copy the `KIT` parsing and `love.errorhandler` from `conf.lua.gold` into your conf.lua (without the handler a smoke
   or test error hangs).
3. Make `love.update` count frames and quit after `KIT.frames` in smoke mode, printing `BOOT_OK` once and
   `SMOKE_DONE` at the end (see `main.lua.gold`), or move your game into `src/game/game.lua` and take the kit's
   main.lua.

## Common errors
| Symptom | Cause | Fix |
|---|---|---|
| `smoke` reports "no exit after N s" | an error screen is waiting for a key | conf.lua lost its `love.errorhandler`, or an error happened in conf.lua itself |
| "love.graphics cannot function without a window!" | graphics created in a headless run (tests, `--headless`) | create graphics only when there is a window, or drop `--headless` |
| `module 'src/core/x' not found` | `require` with slashes, or a typo in the case | `require("src.core.x")`, check the file name's case |
| The fused exe closes at once | DLLs missing next to it | ship the whole `build/windows/` folder |
