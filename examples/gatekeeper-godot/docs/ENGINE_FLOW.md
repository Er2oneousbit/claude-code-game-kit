# Godot Flow

Engine-specific workflow for a Godot 4 / GDScript project. Universal process lives in `docs/sop/`.

> **Tested.** Every command ran against Godot 4.7.2 (Windows) with GUT 9.7.1, the test commands including planted failures
> (`build` exported Windows, Linux and Web; `run` booted the game); the floor, official 4.6-stable with GUT 9.6.1, passed `check`, `test`, `smoke` and the menus and crash drives. Godot below 4.6 is not supported: the shell does not compile there, and `dev.py` refuses it (exit 2; see docs/ENGINE.md). Items marked **(verify)** are untested.

## Daily loop
```
python tools/dev.py check      # compile every .gd file inside the project (one Godot launch)
python tools/dev.py test       # GUT unit tests, headless
python tools/dev.py smoke      # boot the game headless for 120 frames, scan for errors
python tools/dev.py smoke --drive menus   # click through title, settings, back; check settings.json
python tools/dev.py run        # launch the game window
```
Edit in VS Code (godot-tools extension) or the Godot script editor. Keep the Godot editor open for scene work.
Hot reload: the editor reloads changed scripts on focus. Running games started by `dev.py run` do not hot reload.

## The universal commands, mapped to Godot
| dev.py | What it runs |
|---|---|
| `import` | `godot --headless --path . --import` builds `.godot/`; fails on asset import errors (Godot itself exits 0) |
| `check` | `godot --headless --path . -s res://tools/check_scripts.gd -- res://<file>.gd ...`, loads each script inside the project so autoloads resolve; scripts broken by a dependency count too. Skips `tests/` until GUT is installed |
| `test` | `godot --headless --path . -s addons/gut/gut_cmdln.gd -gdir=res://tests -gexit`; fails when GUT skipped a file or ran 0 tests |
| `smoke` | `godot --headless --path . --quit-after N -- --smoke --data-dir build/smoke-data`, passes if output has `BOOT_OK` and no `ERROR`/`SCRIPT ERROR`; `--drive` scenarios below |
| `run` | `godot --path .` |
| `build` | `godot --headless --path . --export-release "<preset>" <out>`. The skeleton ships `export_presets.cfg` with "Windows Desktop", "Linux" and "Web" (tests, tools and docs excluded); with no options `build` picks this computer's preset and its `export_path` (`build/windows/<game>.exe`). Verified on Godot 4.7.2: all three export from Windows in seconds and the exe boots |
| `clean` | removes `build/`, and `.godot/` with `--deep` (keeps `.godot/export_credentials.cfg`) |
| `doctor` | Godot found and 4.6+ (older: exit 2), GUT and cache present, then `tools/doctor.py` |

`check`, `test` and `smoke` run `import` first when `.godot/` is missing or a `class_name` script was added, renamed or removed:
Godot only learns class names on import, so without it valid code fails `check` and new test files are skipped.

## The front end (scripts/shell/)
The skeleton boots into a complete front end, built in code: `main.gd` prints `BOOT_OK`, then `FrontEnd` shows
title -> main menu (Play, Juice demo in debug builds, Settings, Credits, Quit) -> settings (Display, Audio,
Controls, Accessibility, Language, Privacy; Back saves) / credits (`CREDITS.md`) / play (`scenes/play.tscn`, through
a loading screen) -> pause menu (the `pause` action, or losing window focus). Cancel always goes back one screen;
keyboard and gamepad reach every control, and the focused one has an outline.
- **Shell autoload** (`scripts/shell/shell.gd`): settings (`GameSettings`), strings (`Shell.t`), bindings and
  prompt glyphs, the data folder, the log file, crash files, telemetry, F8 bug reports (debug builds).
- **Data folder** (`user://`, or `--data-dir <dir>` after `--`): `settings.json` (+ `.bak`; a missing or broken one is
  recovered from `settings.json.tmp` or `.bak`, so delete all three to reset by hand), `save_<slot>.json`
  (+ `.bak`, `SaveStore`), `<data>/logs/game.log` (version and time on line 1, 5 older ones kept), `crashes/crash_<time>.txt`
  (version, seed, error, backtrace, log tail), `telemetry.csv`, `bug_<time>/` (F8: log tail, settings, screenshot).
- **Strings**: `data/i18n/<locale>.json`, flat `{"key": "text"}` with `{name}` placeholders; `en` is complete, `fr`
  shows the fallback (fr-CA -> fr -> en). Locale `pseudo` (debug builds) runs every string through `I18n.pseudo()`.
- **Theme**: the first `assets/ui/theme_*.tres` if there is one (Dotwork's UI kit, tools/art/dotwork, the widgets
  lane, makes one), else a plain built-in theme. Prompt art: `assets/ui/glyphs/<glyph_name>.png` at 1x, shown in whole
  multiples with nearest filtering; a missing file shows the binding as text.
- **Accessibility** applied live: text size (theme font), menu size (UI layer scale), subtitles (on, size,
  background, speaker names, barks, sound captions), colour-blind mode (swaps the demo palette from `data/access/colours.json`,
  read by `AccessColours` and checked by `tools/access/colour_check.py`; the full-screen `ColorFilter` runs only when
  that file sets `"filter": true`, #169), reduce motion and shake strength (`Shell.effective_shake()`), soften flashes (the `FlashLimiter`
  always applies; this setting also tones flashes down), toggle instead of hold, game speed (scales game time),
  difficulty (stored for the game to read), the readable font and line spacing (`UiTheme.make`), subtitles that wait
  for accept (`subtitle_hold`), longer timing windows (`timing_scale`) and hold to mash (`AutoRepeat`, #166, #167).
- **Keeping track** (#167): the pause menu's "What now?" (`HelpScreen`: the goal from `Shell.set_objective()`, the
  last line, the controls) and "Dialogue history" (`HistoryScreen`, from `Shell.history`, which `SubtitleBar` fills).
  Settings > Controls offers one-handed layouts (`data/input/presets.json`, #166).
- **Narration** (#165): `Narrator` (made by `FrontEnd`) says a line for every focus change, value change and screen
  (`Narrator.describe()`, `Bindings.narration_line()`), through `DisplayServer.tts_speak` when `access.narration` is
  on (`project.godot` turns on `audio/general/text_to_speech`); `Shell.last_narration` holds the last line.
- **Subtitles**: `SubtitleBar` reads `data/dialogue/sample.built.json` (format v0 of Wavesmith's dialogue
  subcommand, tools/audio/wavesmith: cues for a classic bar, per-character reveal times for a typewriter; unknown fields are ignored).
  A caption marked `"directional": true` gets an arrow while its source is off screen: `bar.caption(id, {"dx": .., "dy": .., "half_w": .., "half_h": ..})`.
- **Juice demo** (`scripts/game/juice_demo.gd`, debug builds): hit the box for shake, hitstop, squash on a spring and
  a limited flash; follow camera with a deadzone; buffered jump with coyote time; a held guard; a subtitle line.
  Hitstop and the flash limiter run on real time; everything else on game time (after hitstop and game speed).

### Telemetry
Off until the player answers the title screen's question (Yes / No / Later; Later asks again next launch). Events
go to `telemetry.csv` in the data folder only while consent is `yes`; nothing is sent anywhere. To add an endpoint:
send the rows with `HTTPRequest` only while `Shell.telemetry_allowed()` is true, keep No and Later meaning "nothing
leaves the computer", and update the privacy policy before shipping: what is collected, why, where it is sent and
who runs that server, how long it is kept, and how a player can opt out and have it deleted. Players in the EU and
UK must opt in before anything is sent **(verify with current GDPR guidance for your stores)**.

### Smoke scenarios
`dev.py smoke` without options keeps its old meaning (boot, 120 frames, no errors). Each run uses a fresh
`build/smoke-data/` unless `--data-dir` names a folder (never wiped; `smoke` and `run` refuse one inside an export
folder such as `build/windows/`, exit 2). Drives run with `--fixed-fps 60`, so frames are
1/60 s of game time and pictures repeat exactly.
| Command | Passes when |
|---|---|
| `smoke --drive menus` | title -> settings -> master volume 0.5 (left or right from whatever the data folder held), reduce motion toggled -> Back -> Quit; prints `SETTINGS_WRITTEN <path>` and the file holds both values. With consent unset no `telemetry.csv` appears |
| `smoke --drive crash` | exits 1 on purpose: a script error writes `crashes/crash_<time>.txt` and prints `CRASH_WRITTEN <path>` |
| `smoke --drive pseudo --locale pseudo` | every screen and settings tab is shown and no label is untranslated, clipped or off screen (`PSEUDO_OK`) |
| `smoke --drive pseudo-plant --locale pseudo` | exits 1 on purpose, naming a planted label that is too small (`PSEUDO_FAIL`) |
| `smoke --drive access[:res=WxH][,scale=N][,pad]` | every screen reported as `ACCESS_*` lines for `tools/access/sweep.py` (`AccessAudit`): texts with size, colour, background, fit and where they land, the focus graph, the subtitle and the prompts; the drive sets the window size itself (headless Godot ignores `--resolution`), `pad` presses with gamepad events only |
| `smoke --drive show:<title\|settings\|pause\|subtitle\|juice\|credits> --screenshot captures/x.png` | opens that screen (settings with a control focused) and photographs it in a window |
| `... --screenshot new.png --compare base.png [--tolerance N]` | `tools/image_diff.py` finds no difference (exit 1 when it does) |
Any run with `--locale pseudo` checks each screen as it appears. The windowed capture ignores the mouse, so a cursor
resting on the window cannot change the picture.

## Setting up tests (GUT)
1. Install GUT into `addons/gut/`. Without the editor: download the release zip for your Godot version from
   https://github.com/bitwes/Gut/releases (9.7.1 works with Godot 4.7.2; GUT 9.7 does not parse on 4.6, where 9.6.1 works) and copy the zip's `addons/gut/` folder into
   the game's `addons/`. With the editor open: AssetLib tab, search "GUT", Download, Install. The folder must be
   `addons/gut/`, not the GUT files loose in `addons/`. The next `check`/`test` re-imports automatically.
2. Enable it under Project Settings > Plugins for the editor panel. The headless `dev.py test` works without enabling it.
3. Tests live in `tests/`, files `test_*.gd`, extend `GutTest`, functions `test_*`. Example in `tests/test_coyote_timer.gd`.
   `test_golden_juice.gd` and `test_golden_shell.gd` check `scripts/core/` against every case in `data/golden/*.json`
   (the kit's reference, `tools/golden_vectors.py`); a new case type fails them until it is ported.
   `test_golden_music.gd` checks `scripts/core/music_director.gd` against `data/golden/music.json` (whole samples, tolerance 0).
   `test_golden_access.gd` checks `scripts/core/audio_access.gd` against `data/golden/access.json` (slider gains, caption arrows).
   `test_golden_telemetry.gd` checks `telemetry.gd` against `data/golden/telemetry.json` (the CSV columns every engine writes).
   `test_golden_dialogue.gd` checks the subtitle typewriter (`DialogueData.revealed`) against `data/golden/dialogue.json`.
   `test_credits_text.gd` checks the credits screen's text (`CreditsScreen.plain_text`: HTML comments, heading marks, list
   markers and emphasis stars out of CREDITS.md, the same rule on every engine) against `data/golden/credits.json`.
4. `python tools/dev.py test` runs them headless. Add `--filter <name>` to run one file.

## Adopting an existing project
`new_game.py --adopt` never edits your `project.godot`; the kit's version lands in `project.godot.gold`. After adopting:
1. Copy the `[autoload]` lines `Log="*res://scripts/core/log.gd"` and `Shell="*res://scripts/shell/shell.gd"` from `project.godot.gold` into your `project.godot` (the kit's scripts call both).
2. Print the boot marker from your own main scene's `_ready()`: `Log.info("core", "BOOT_OK <Game>")`. `smoke` passes only when it sees it.
3. Keep or delete the kit's starter files (`scenes/main.tscn`, `scripts/game/main.gd`, the CoyoteTimer example), then delete every `*.gold` file once merged (Godot ignores them meanwhile).
4. Install GUT (above), then `python tools/dev.py check`, `test`, `smoke`.

## Scenes vs code
- Structural scene work (adding nodes, wiring signals in the editor): do it in the editor. Claude can read the `.tscn` after.
- Behavior: scripts. Claude edits `.gd` freely.
- Spawn/instantiate via `preload("res://scenes/x.tscn")`, tune values from data.

## Assets and audio
- Import settings live in `*.import` files. Pixel art: Filter off, mipmaps off. Audio loops: set loop in the import tab, verify in-game.
- Audio buses: Master > Music, SFX, UI. Create in the Audio tab, expose volume sliders in settings from day one.
- Music: `MusicPlayer` (`scripts/shell/music_player.gd`) plays data/music.json on the Music bus and switches on the sample `MusicDirector` plans (import music WAVs as PCM; precision in its header).
- Naming: `spr_player_idle.png`, `sfx_jump_01.wav`, `mus_level1.ogg`, `fnt_ui.ttf`.
- Find sources in `docs/RESOURCES.md`, log in `docs/ASSET_LOG.md`.
- Tripo AI lists a Godot plugin **(verify)**. Whether you use it or just import GLB, import generated meshes as drafts and clean them in Blender first (SOP-11).

## Profiling
Editor > Debugger > Profiler and Monitors. Record: FPS, process/physics time, draw calls, object count.
Release-like check: export a release build and watch the on-screen FPS counter. Editor numbers run slower. See SOP-10.

## Packaging (export)
1. Install export templates for your exact Godot version once (Editor > Manage Export Templates, or download the
   `.tpz` for your version from godotengine.org and install it from that dialog).
2. `export_presets.cfg` comes with the project: "Windows Desktop", "Linux" and "Web", with `tests/*, tools/*, docs/*,
   addons/gut/*, data/golden/*, assets_src/*` and the kit's `.game-kit.json` excluded; `build` lists the exported
   .pck and fails when one of them is inside (a preset edited in the editor can drop the filter). `assets_src/`
   (art sources, Dotwork's review sheets) also holds
   an empty `.gdignore`, so Godot never imports it: keep anything a scene loads under `assets/`. Add macOS, Android or iOS in Project > Export (they need signing). Commit `export_presets.cfg` but
   **never** credentials: Godot 4 writes keystore passwords and the PCK encryption key to .godot/export_credentials.cfg
   (git-ignored with the rest of .godot/, denied to Claude, and kept by `clean --deep`).
3. `python tools/dev.py build` (this computer's preset), or `build --preset Web` (a folder you can upload to itch.io).
4. Check the build boots: `build/windows/<game>.exe --headless --quit-after 120` must log `BOOT_OK`.
5. Play the exported build, not the editor, before release (SOP-06).

## Common errors
| Symptom | Likely cause | Fix |
|---|---|---|
| `Identifier not found` for an autoload from a hand-run `godot --check-only --script` | `--check-only --script` runs outside the project's autoloads (confirmed on 4.7.2) | Use `dev.py check`, which loads scripts through `tools/check_scripts.gd` |
| Godot crashes (signal 11) when checking scripts | a `-s` script tried to recompile itself | `check_scripts.gd` skips itself; do not pass it to another checker |
| `Could not load resource` in headless runs | import cache missing | `python tools/dev.py import` |
| `Invalid call. Nonexistent function` after pulling | stale `.godot/` cache | `python tools/dev.py clean --deep`, then `import` |
| GUT not found | addon not installed or not enabled | See "Setting up tests" |
| `Identifier "X" not declared` / `Could not find base class "GutTest"` on valid code | class cache older than the scripts | `python tools/dev.py import` (check/test/smoke do it automatically when class names change) |
| `test` says "no tests ran" or "a test file was skipped" | `--filter` matches nothing, a test file has a parse error, or GUT was installed after the last import | Fix the file or filter; the printed lines name it |
| Test passes in editor, fails headless | depends on scene tree or window | Move logic into a `RefCounted` class |

## Claude-specific tips
- Ask Claude to create tests alongside new logic classes. Keep logic out of node scripts.
- When Claude proposes a Godot API, ask "verified or unverified?" It should check docs for your version.
- If scenes get hairy, have Claude describe the desired node tree and you build it in the editor.

## Field notes (reported, unverified)
**No MCP needed (E04).** Godot scenes, scripts, shaders, and most resources are plain text. A video creator runs agents directly against the project files with no Godot MCP server, then launches the game, checks, and iterates. That matches this kit: `tools/dev.py check|test|smoke` is the feedback loop. Binary assets (images, audio, .blend) are the exception.
Terrain note: for MultiMesh grass or foliage, test painted textures on simple planes versus real geometry for the look you want.

**Screenshots and bursts from the kit (K01):** `python tools/dev.py smoke --screenshot <file.png>` and `--record <folder>`
run the game in a real window after the headless smoke (headless has no renderer; a window opens for a few seconds),
through `tools/capture.gd`; `tools/art/frames_to_gif.py <folder> <out.gif>` makes the GIF.

**Recording gameplay (E09, verify).** A video creator reported that capturing the running game fails while Godot's window mode is "windowed". Setting Project Settings > Display > Window > Mode to fullscreen fixed capture for him. Windows Game Bar (Win+G) is a free recorder. Recordings are handy for pulling screenshots and for `/playtest-report` notes.
