# RPG Maker MZ flow (long form)

> Copied into the game as `docs/ENGINE_FLOW.md`. Short rules: `docs/ENGINE.md`. Steps marked **(verify)** have not been
> run against a real RPG Maker MZ install yet.

## One-time setup
1. Install RPG Maker MZ (Steam or the official site) and Node.js 22 LTS or newer.
2. In the editor: File > New Project, anywhere (a scratch folder is fine). This is only a source of MZ's own files.
3. `python tools/dev.py setup --from <that folder>`: copies everything you do not already have into `game/`, registers
   GameCore and GameMain in `game/js/plugins.js`, installs Playwright and its headless Chromium.
4. `python tools/dev.py doctor`, then open `game/game.rmmzproject` in the editor. **(verify)**
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

## Assets and audio
- MZ's default art and sound come with your copy of MZ; log your own additions in `docs/ASSET_LOG.md` as usual.
- Images go in the matching `game/img/` folder (characters, faces, tilesets, pictures, ...). Audio must be `.ogg`, and
  `.m4a` for some platforms. **(verify which formats MZ 1.x still needs)**
- Generated audio (`tools/audio/`): export OGG (ffmpeg converts a WAV). Generated art: match MZ's sheet layouts (a
  character sheet is 4 x 2 characters of 3 x 4 frames). **(verify sizes)**

## Profiling
Real numbers come from the editor's Playtest or a real browser (F12 > Performance), not headless smoke (software WebGL).
MZ's FPS counter: F2 in a Playtest. **(verify)**

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
