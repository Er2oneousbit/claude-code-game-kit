# RPG Maker MZ flow (long form)

> Copied into the game as `docs/ENGINE_FLOW.md`. Short rules: `docs/ENGINE.md`. Steps marked **(verify)** have not been
> run against a real RPG Maker MZ install yet.

## One-time setup
1. Install RPG Maker MZ (Steam or the official site) and Node.js 22 LTS or newer.
2. In the editor: File > New Project, anywhere (a scratch folder is fine). This is only a source of MZ's own files.
3. `python tools/dev.py setup --from <that folder>`: copies everything you do not already have into `game/`, registers
   GameCore and GameMain in `game/js/plugins.js`, installs Playwright and its headless Chromium.
4. `python tools/dev.py doctor`, then open the `.rmmzproject` file in `game/` in the editor (it keeps the new
   project's name, such as `Project1.rmmzproject`; setup prints it). **(verify)**
Optional: set `RPGMZ_EXE` to the editor's `RPGMZ.exe` so `python tools/dev.py run --editor` opens the project.

## Daily loop
1. Rules first, in `game/js/plugins/GameCore.js`, with a test in `tests/` (`python tools/dev.py test`).
2. Glue in `GameMain.js`: a plugin command (`@command` in the annotation plus `registerCommand`), a scene hook, a window.
   Test it with `tests/support/mzFake.js` when it has logic worth pinning.
3. `python tools/dev.py check` (syntax, annotations, database JSON, plugin list), then `smoke`.
4. Maps, events and the database: in the editor. Events call your plugin with the "Plugin Command" event command.
5. Playtest in the editor (Ctrl+R) for feel; `python tools/dev.py run` for the browser build.

## Mapped to the tools
| Kit command | What it runs |
|---|---|
| `setup [--from DIR]` | copies MZ's files into `game/` (never over yours), registers the game's plugins, `npm install`, Playwright Chromium |
| `check` | `node --check` on every plugin; the game's plugin annotations against their `registerCommand` calls; `json.load` of every data file (database lists start with `null`); `js/plugins.js` lists existing files, the game's plugins on and in order |
| `test` | `node --test --test-reporter=tap tests/**/*.test.js` (the count is parsed: zero tests is a failure) |
| `smoke` | serves `game/` on localhost, loads it in headless Chromium at 816x624, waits for `BOOT_OK` from GameMain, fails on console errors, page errors and 404s **(verify against a real project)** |
| `build` | copies `game/` to `build/web/` without `save/` and the project file |
| `run` | serves `game/` and opens your browser; `--editor` opens the project in RPG Maker MZ **(verify)** |
| `clean` | removes `build/` (`--deep`: also `node_modules/`) |
| `doctor` | node, npm, the MZ project, Playwright's browser, `RPGMZ_EXE`, plus `tools/doctor.py` |
| `dotwork [options]` | `node tools/dotwork_mz.mjs`: Dotwork's art into MZ's image layouts in `game/img` ("Dotwork art in MZ" below); `check` re-checks the last export |

## Adding a plugin command
```js
/*:
 * @command OpenShop
 * @text Open Shop
 * @desc Opens the shop for one merchant.
 * @arg merchantId
 * @type number
 * @default 1
 */
PluginManager.registerCommand("GameMain", "OpenShop", (args) => {
    const id = Number(args.merchantId);     // arguments are strings
    ...
});
```
The command shows in the event editor's Plugin Command list after the editor reloads the plugin (reopen the Plugin
Manager or the project). **(verify)**

## Testing
- **Rules:** plain Node tests against GameCore (`require("../game/js/plugins/GameCore.js")`): seeded, fast, no MZ.
- **Glue:** `tests/support/mzFake.js` runs a plugin file with small stand-ins for `PluginManager`, `Scene_Title` and
  whatever else you add. It catches typos, wrong command names and logic errors, not differences from real MZ.
- **The real engine:** `smoke` boots the actual project in Chromium. Scenario runs work like the web overlay's:
  read `location.search` in a plugin (for example `?autoplay`), log markers, and run
  `python tools/dev.py smoke --query autoplay --until DONE --fail-on LOST`.
- Bot pairs (SOP-14 step 6) belong in GameCore tests: they run in seconds over many seeds.
- **Audio:** `tests/gameAudio.test.js` runs `data/golden/audio.json`, `music.json`, `access.json` through `GameAudio.js`.
- **Juice and shell:** `tests/gameJuice.test.js` and `tests/gameShell.test.js` run every case of `data/golden/juice.json`
  and `shell.json` (written by `tools/golden_vectors.py`, the reference for every engine) through `GameJuice.js` and
  `GameShell.js`; an unknown case type fails. `tests/gameAccess.test.js` runs the MZ glue against stand-ins for
  ConfigManager, Window_Options, Scene_Options, Game_Screen and Game_System (`tests/support/golden.js` is the shared
  comparison).
- **Dotwork art:** `tests/dotworkMz.test.js` loads `data/golden/dotwork/` through `tools/dotwork_mz.mjs`, compares the
  kinds MZ uses with its `expected.json`, and checks the converted images hold the right frames in MZ's cells.

## Assets and audio
- MZ's default art and sound come with your copy of MZ; log your own additions in `docs/ASSET_LOG.md` as usual.
- Images go in the matching `game/img/` folder (characters, faces, tilesets, pictures, ...). Audio must be `.ogg`, and
  `.m4a` for some platforms. **(verify which formats MZ 1.x still needs)**
- Generated audio (Wavesmith, `tools/audio/wavesmith/`): export OGG with `wavesmith.py formats convert x.wav --out x.ogg`
  (needs ffmpeg; `--loop` keeps a WAV loop point as LOOPSTART / LOOPLENGTH). Generated art: match MZ's sheet layouts (a
  character sheet is 4 x 2 characters of 3 x 4 frames). **(verify sizes)** Dotwork's art: `dev.py dotwork` (below).

## Dotwork art in MZ
Dotwork (`tools/art/dotwork/`, `/dotwork`) makes engine-neutral PNGs plus an asset manifest per pack
(`assets/dotwork/<pack>.assets.json`; `tools/art/dotwork/ASSET_MANIFEST.md`). MZ cannot load that: it reads fixed
image layouts from `img/<folder>/` by name, and the editor's pickers only see files on disk. So the kit converts once,
after every Dotwork run, instead of loading at runtime (a plugin could not put the art into the database or the event
editor):
```
python tools/dev.py dotwork --dry-run      # what it would write, and what it skips
python tools/dev.py dotwork                # write; files MZ shipped (Window.png, IconSet.png) are kept
python tools/dev.py dotwork --replace      # also replace those (the originals go to build/dotwork_mz/originals/)
```
| Dotwork | MZ file | How |
|---|---|---|
| a character (`walk_<dir>` in s, w, e, n; else `idle`) | `img/characters/$<name>.png`, or `--sheet NAME` for 4 x 2 per file | 3 frames per direction: walk frame 0 stands in the middle column (MZ shows it when idle; `--stand idle` takes idle's first frame instead), the strides a quarter and three quarters through the walk either side (MZ walks 1, 2, 1, 0). Rows: down, left, right, up. Feet on the cell's bottom centre; a cell is at least one tile |
| a prop, an animated prop | `img/characters/!$<name>.png` | an object sheet: the picture (or three frames of its clip) in every cell, for events |
| portrait expressions | `img/faces/<name>.png` | 144 x 144 cells, 4 x 2 per file, neutral first (face index 0); scaled up by a whole number to fit |
| battle poses (character entry `"poses": "battle"`) | `img/sv_actors/<name>.png` | only in side-view games (System.json, or `--side-view`): 9 x 6 cells, MZ's 18 motions from ready, idle, walk, attack, cast, defend, hurt, item, victory, weak and ko clips facing west (escape runs east); a motion with no clip shows wait |
| enemies | `img/enemies/` (front view) or `img/sv_enemies/` | the picture at the game's scale, feet on the bottom centre; the contact shadow is left out |
| a ui_kit window part (+ a hover or focus button) | Window.png in `img/system/` | background, frame and cursor from the parts, taken 1:1 (a ui_kit is already drawn at its scale); the arrows, pause sign and text colours stay as the existing skin has them |
| icons | IconSet.png in `img/system/` | appended below the icons already there (a 32 px size, or one that divides 32, scaled up); a re-run replaces only its own rows |
| blob47 terrain of a square tileset | `img/tilesets/<pack>_<tileset>_A2.png` (an animated one, such as water: `_A1.png`) | an MZ autotile per terrain, its 2 x 3 tile block built from Dotwork's quarter tiles; kept only when all 47 of Dotwork's tiles come back pixel for pixel from the block (art drawn across the quarter lines does not: it goes on B instead). A1 water plays MZ's frames 0, 1, 2, 1 at MZ's own rate |
| every other tile of a square tileset (plain tiles, sides4 and corners4 terrain, a terrain's variants) | `img/tilesets/<pack>_<tileset>_B.png` (C, D, E when full) | at MZ's tile size; multi-tile stamps stay whole; B's tile 0 is MZ's empty tile |
| a map of a square tileset | MapNNN.json in `game/data`, a row in its MapInfos.json, a tileset entry in its Tilesets.json | every layer resolved as the spec says (terrain keys, the variant roll, stamps), each cell's tiles stacked into MZ's four tile layers in the manifest's order: an autotile id where the autotile draws the cell's tile, else its B to E id; props as events showing their object sheet; collision tiles impassable in the tileset's flags. Needs MZ's own database (`setup --from` first) |
| a battle background | `img/battlebacks1/<name>.png` (the first layer), `img/battlebacks2/<name>.png` (the others over each other) | one whole factor that makes the first layer cover the screen; repeating layers tiled across it; MZ's battle backs stand still |
| any other background (scenes, parallax, weather) | `img/parallaxes/<name>[_<layer>].png` | a file per layer at its scale times the game's; the record gives MZ's loop flags and scroll speed (`sx`, `sy`) for the map's parallax settings **(verify the sign)** |

**The scale** is one whole number for the whole game: MZ's tile size (`tileSize` in the project's System.json, 48 when
absent) over the art's tile size, so 16 px Dotwork tiles become 3x. Art whose tile size does not divide MZ's is not
shrunk or blurred: set MZ's tile size to a multiple (Database > System 2, verify) or pass `--scale`.

**What it records:** `<src_dir>/dotwork/mz_export.json` (Dotwork's source folder, assets_src unless its config
says otherwise; commit it) lists every file written with its hash and the
numbers MZ's database wants: each character's file and index, each expression's face file and index, each icon's
index, each tile's B to E tile id and whether it collides, each autotile's kind and first tile id, each map's id and
tileset id. Database entries the converter owns carry `<dotwork>` in their note: remove it and the entry is yours (the
next run makes a new one); a map changed in the editor is left alone without `--replace`, like an image.
A file whose hash no longer matches (you edited it in MZ or a paint program) is left alone without `--replace`.
`python tools/dev.py check` checks the export: the files exist and have MZ's shapes.

**Not converted** (each prints a note): isometric tilesets and their maps (MZ's maps are square), effects and
spells (MZ's battle animations are Effekseer files), particles, rule-image transitions, normal maps, bitmap fonts (MZ
draws TrueType or WOFF fonts), and other pictures (copy them to `img/pictures` by hand). Lost on the way: Dotwork's
frame timing (MZ times walks by move speed and plays three frames), frames past the three MZ uses, the animation of
tiles that are not an A1 autotile (B to E tiles do not animate), flipped map cells (MZ tiles do not flip), a cell's
fifth layer and up, and collision boxes (MZ's passability is per tile, in the database). sides4 and corners4 terrain
is not autotiled (MZ's autotiles are blob-shaped): its maps place the tiles cell by cell, so they look right but
repainting them in the editor does not join them up.

**Verify in MZ:** every layout above comes from MZ's documented formats and has been checked only against stand-ins
(sizes, the right frames in the right cells, Chromium decoding the files); the autotile table, tile ids and map
drawing are RPG Maker MV's corescript (Tilemap.js), and the tests draw each converted map that way and compare it with
Dotwork's, pixel for pixel. Open a converted character, face, tileset and map in the editor once before relying on it.

## Profiling
Real numbers come from the editor's Playtest or a real browser (F12 > Performance), not headless smoke (software WebGL).
MZ's FPS counter: F2 in a Playtest. **(verify)**

## The shell, juice and accessibility in MZ (SOP-18 to SOP-20)
MZ already has the shell's screens: Scene_Title, Scene_Menu, Scene_Options, Scene_Save and Scene_Load, a pause on
focus loss (the "background" option) and its own save files. So the kit does not port the screens here. It ships
the rules as plugins, the same as every other overlay's and checked against the same golden vectors, and wires the
part that protects players into MZ (verify each hook in a test play: the overlay is not yet run against MZ):
- **GameJuice.js** (engine-free): `Shake` (trauma on value noise), `Hitstop`, `ease`, `FollowCamera`, `InputBuffer`,
  `CoyoteTimer`, `Spring` and `squash`, `FlashLimiter`, `HoldToggle`, `AutoRepeat`, and the recipe helpers of SOP-18
  step 4 (`impact`, `floatText`, `trailPush`, `trailShrink`, `trailLength`). MZ steps 60 frames a second:
  pass `dt = 1 / 60` (verify), and hold a scene still while `hitstop.scaledDt(dt)` is 0.
- **GameShell.js** (engine-free): `settingsLoad` (defaults, repair, unknown keys kept), `effectiveShake`,
  `telemetryAllowed`, `rebind` with swap, `glyphSet` / `glyphName` / `promptBinding`, `narrationLine`, `tr` /
  `trPlural` / `pseudo`, and the save envelope (`saveLoad`, `saveMigrate`, `MIGRATIONS`, `saveText`).
- **GameAccess.js** (MZ glue): the kit's settings live in MZ's `config.rpgsave` under `kit` (ConfigManager.makeData
  and applyData, repaired on load); MZ's Options screen gets Reduce Motion, Screen Shake (0 to 100 %), Gentle
  Flashes, Text Size and Line Spacing after its own rows (labels are plugin parameters, for translated games; the
  `extraRows` parameter adds on/off rows for subtitles, speaker names, captions, hold to toggle, auto repeat,
  narration and readable font, which your game reads from `GameAccess.settings().access`); MZ's Shake Screen
  is scaled by `effectiveShake` (0 with reduce motion), every Flash Screen and every flash of a battle animation
  (`Sprite_Animation.processFlashTimings`, and `Sprite_AnimationMV.startFlash` / `startScreenFlash` for MV-format
  animations) goes through the FlashLimiter (three per real second in all, always) and is softer with Gentle Flashes
  on; Text Size scales `Game_System.mainFontSize` and `Window_Base.lineHeight` grows with it and with Line Spacing;
  `DataManager.makeSaveContents` carries the kit's save version (`kitSave`) and `extractSaveContents` migrates older
  saves with `GameShell.saveMigrate` and refuses newer ones.

| Kit rule | In MZ |
|---|---|
| Settings saved and restored (SOP-19 step 2) | **Wired:** GameAccess keeps the kit's settings in config.rpgsave next to MZ's options, repaired by `GameShell.settingsLoad`; unknown keys stay |
| Shake and flash safety (SOP-18 step 3, F33, F34) | **Wired:** "Shake Screen" (and anything calling `$gameScreen.startShake`) follows Reduce Motion and Screen Shake; "Flash Screen", damage flashes (`$gameScreen.startFlash`) and battle animations' own flashes go through the limiter (method names from MZ 1.x, **verify** in a test play; a plugin that flashes by another route is yours to route through `GameAccess.flashColor`) |
| Text size (SOP-20) | **Wired:** Text Size (75 to 150 %) scales the main font, `Window_Base.lineHeight` grows with it (and with the Line Spacing row, 1 to 2), so windows built from it follow. **Left to you:** a window that sets its own height or a fixed pixel line (some plugins do) still needs a look at 150 % (verify) |
| The other accessibility settings (SOP-20) | **Wired as rows on request:** the `extraRows` plugin parameter adds on/off rows for subtitles, speaker_names, subtitle_barks, subtitle_hold, captions_sfx, hold_to_toggle, auto_repeat, narration, readable_font; they set `GameAccess.settings().access.<name>` and your game acts on them. **Left to you:** colour-blind palettes, difficulty, game speed and timing have no row (they are choices or numbers that mean something only to your game): add one the way GameAccess does (a ConfigManager property, a `Window_Options` command, one more in `Scene_Options.maxCommands`) |
| Versioned saves with migration (SOP-19 step 3) | **Wired:** MZ's save contents carry `kitSave` (the kit's version), older ones run `GameShell.MIGRATIONS` on load, newer ones refuse to load. Replace the kit's template `MIGRATIONS` with your own, and set the plugin parameter `unmarkedSaveVersion` to the version your saves had before the plugin (empty: unmarked saves count as current). **Left to you:** MZ's own save screens show no message for a refused save (it fails to load); test your migrations in Node with `GameShell.saveMigrate` |
| Rebinding and prompts (SOP-19 step 4) | **Left to you:** Input.keyMapper and Input.gamepadMapper hold MZ's bindings; a rebinding screen is a plugin (community plugins exist, check their license); `GameShell.rebind` and `glyphName` give the swap rule and the prompt names. Prompts in messages use icons or text codes |
| Localization (SOP-19 step 5) | **Left to you:** database text and messages live in data/*.json: keep the source language there and load per-locale JSON in a plugin with `GameShell.tr`; run `GameShell.pseudo` over the extracted strings in Node for the pseudo-locale check |
| Scripted runs (`--drive`) | **Built, not yet run on a real MZ project (verify):** `smoke --drive menus` opens each of MZ's screens (title, menu, item, skill, equip, status, options, save, load, game end), `--drive access` turns every kit row on the Options screen and checks it reached the saved config, `--drive crash` plants an error and must fail (tools/mz_drives.js; tested in Node against stand-ins). **Not here:** `pseudo` (MZ has no kit-owned text screens to expand: run `GameShell.pseudo` over your extracted strings in Node) |

## Packaging (release)
- `python tools/dev.py build` makes `build/web/`, a plain copy for browsers (itch.io: zip the folder's contents).
- For a release use the editor: File > Deployment > Web browsers, Windows or macOS, with **Exclude unused files** (smaller)
  and, if you want, encryption of images and audio. The editor's help says encryption does not stop determined copying.
- Desktop builds (NW.js) come only from the editor's Deployment.

## Adopting an existing project
Scaffold the kit into a new folder, move your MZ project into its `game/` folder (or keep it at the root: `dev.py` finds
a project there too, but the editor's Deployment would then also see the kit's files), then `python tools/dev.py setup`
and `check`. Your plugins are not GameCore/GameMain: either add those two (empty rules are fine) or set `OWN_PLUGINS` in
`tools/dev.py` to your own plugin names, in load order. If your project folder already had a `package.json` (MZ's own,
for NW.js), the kit's lands as `package.json.gold` at the root; only `game/package.json` belongs to MZ.

## Common errors
| Symptom | Cause | Fix |
|---|---|---|
| `GameCore is not defined` when the game starts | GameCore is off or below GameMain in the Plugin Manager | Turn it on, put it above GameMain; `check` says which |
| A plugin command does nothing | The `@command` name and the `registerCommand` name differ, or the plugin name is not the file name | `check` lists both mismatches |
| Your changes to `data/*.json` vanished | The editor was open and saved its own copy | Close the project before editing JSON (gotcha 1) |
| Smoke: `no RPG Maker MZ project in game/` | MZ's files were never copied in | `python tools/dev.py setup --from <a new MZ project>` |
| A black page in a browser opened from the file | `file://` cannot load the data | `python tools/dev.py run` |

## Scenario runs (smoke options)
`--query Q` (URL query), `--until MARKER`, `--fail-on A,B`, `--timeout S`, `--screenshot FILE`, `--record DIR`,
`--headed`: the same as the web overlay. Markers are console lines your plugins print.

## Content switches
- Content switches (#171, #207): GameAccess adds Blood and Clean Language rows to MZ's Options screen (labels
  `bloodText` / `cleanLanguageText`, hidden with `showBlood` / `showCleanLanguage` off in a game without blood or
  strong language). Your game reads `GameShell.bloodEnabled(GameAccess.settings())` (off: a neutral hit effect,
  SOP-18 step 4) and passes `GameShell.cleanLanguage(...)` to `GameShell.tr` (with a word list compiled once by
  `GameShell.compileWords`). MZ has no `--drive`: check the rows on the Options screen by hand.
