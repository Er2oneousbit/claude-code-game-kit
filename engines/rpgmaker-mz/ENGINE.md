# Engine: RPG Maker MZ (JavaScript plugins)

> Imported into CLAUDE.md. Keep it short. Long-form flow is in `docs/ENGINE_FLOW.md`.
> **Untested proof of concept: not yet verified against a real RPG Maker MZ install** (the kit's README "What was tested"): steps that depend on the
> editor or the engine are marked **(verify)**. The plugin checks and Node tests run without MZ.

## Version and setup
- **Engine:** RPG Maker MZ (Gotcha Gotcha Games / KADOKAWA), bought by you; the kit does not ship any of it. Its core
  scripts carry no open-source license, so they stay out of public repos (gotcha 7).
- **Tools:** Node.js 22.12 or newer (with npm): `node --test` for unit tests, Playwright 1.64 (headless Chromium) for
  `smoke`. No bundler: plugins are plain JavaScript files.
- **First run:** in RPG Maker MZ make a new project anywhere (File > New Project), then
  `python tools/dev.py setup --from <that project folder>`. It copies MZ's own files (core scripts, default database,
  default art and sound) into `game/` without touching yours, registers the game's plugins and installs the tools.
  Then `python tools/dev.py doctor`, and open the `.rmmzproject` file in `game/` in the editor (it keeps the name
  the new project had, such as `Project1.rmmzproject`; setup prints it). **(verify)**

## Layout
```
game/                     the RPG Maker MZ project: open its .rmmzproject file in the editor
game/js/plugins/GameCore.js   engine-free rules: no $game*, Scene_*, Window_*. Tested in Node. Yours.
game/js/plugins/GameAudio.js  the kit's audio rules (sound events, music, access), engine-free, golden-tested in Node.
game/js/plugins/GameJuice.js  the kit's juice rules (shake, hitstop, easing, follow camera, input buffer, coyote time,
                          spring and squash, flash limiter, hold toggle, auto repeat), engine-free, golden-tested.
game/js/plugins/GameShell.js  the kit's shell rules (settings with repair, effectiveShake, bindings and glyph names,
                          i18n with the pseudo-locale, versioned saves), engine-free, golden-tested.
game/js/plugins/GameAccess.js MZ glue: the settings in MZ's config file, four options on MZ's Options screen, MZ's
                          Shake Screen and Flash Screen through them (verify in MZ).
game/js/plugins/GameMain.js   MZ glue: plugin commands, scene hooks, the BOOT_OK marker. Yours.
game/js/plugins/KitShaders.js the kit's shader recipes as PIXI filters (generated: tools/shaders/; turn it on in
                          the Plugin Manager to use it)
game/js/plugins.js        the Plugin Manager's list (the editor writes it; setup adds the game's plugins)
game/data/*.json          the database and maps (the editor writes them; see gotcha 1)
game/img, audio, ...      art and sound (MZ's defaults plus yours; docs/ASSET_LOG.md for yours)
tests/                    Node tests (*.test.js); tests/support/mzFake.js loads a plugin with stand-ins for MZ
tools/                    dev.py, smoke.mjs, serve.mjs and helpers; dotwork_mz.mjs (Dotwork's art into MZ's image
                          layouts: `dev.py dotwork`, ENGINE_FLOW "Dotwork art in MZ")
build/web/                a web-browser copy of the game (git-ignored)
```
Keeping the MZ project in `game/` means the editor's Deployment exports the game and none of the kit's docs or tools.
MZ keeps its own title, options, save and load screens: the kit ships the juice and shell RULES as plugins and
GameAccess puts the accessibility settings that fit onto MZ's Options screen; ENGINE_FLOW ("The shell, juice and
accessibility in MZ") says what is wired and what is left to you. There are no `--drive` scenarios here.

## Conventions
- **Rules in GameCore, MZ in GameMain.** GameCore must stay loadable by Node (tests); anything that touches RPG Maker
  objects goes in GameMain or another glue plugin. Add plugins to `OWN_PLUGINS` in `tools/dev.py` so `check` covers them.
- **One plugin, one file, same name:** `PluginManager.registerCommand("GameMain", ...)` and `parameters("GameMain")` use
  the file name without `.js`. Every `registerCommand` needs a matching `@command` in the `/*:` annotation (`check` fails
  otherwise), or the command never shows in the event editor.
- **Alias, never replace:** keep the original method and call it (`const start = Scene_Title.prototype.start; ...
  start.call(this)`), so other plugins that hook the same method keep working.
- **Plugin parameters and command arguments are strings:** convert with `Number(...)`, `=== "true"`, `JSON.parse(...)`.
- **Version:** the `version` in package.json (SOP-06); show it where you like (a title-screen plugin line is enough).
- Errors at runtime: `console.error` reaches the smoke test, which fails on it.
- **Plugin order:** GameCore, GameAudio, GameJuice, GameShell, GameAccess, GameMain (`OWN_PLUGINS` in `tools/dev.py`;
  `setup` registers them, `check` holds the order). The player's settings: `GameAccess.settings()`; shake and flash
  in your own plugins: `GameJuice.Shake` with `GameShell.effectiveShake(GameAccess.settings())`, and MZ's own
  `$gameScreen.startShake` / `startFlash`, which already follow them.
- **Shaders:** turn on KitShaders in the Plugin Manager, then in a plugin `sprite.filters = [KitShaders.filter("flash",
  { amount: 1 })]` (a second picture, such as dissolve's noise: `KitShaders.filter(name, {}, PIXI.Texture.from(...))`).
  Coordinates run 0 to 1 over the sprite: set `filter.uniforms.u_texel` to one over its texture size (the default
  suits a 32-pixel picture) and `u_canvas` to the size pixel parameters such as `light_pos` are given in. `check` compiles the filters; `smoke --shaders` renders each one the way PIXI hands a
  filter its padded input and compares it with the golden image, before you have an MZ project. **(verify one filter
  in a real MZ game: the check emulates PIXI's filter uniforms, it is not PIXI)**

## Gotchas (Claude: read before editing)
1. **The editor keeps the database in memory.** Edits to `game/data/*.json` or `js/plugins.js` made while the project is
   open in RPG Maker MZ are overwritten the next time you save there. Close the project (or reopen it without saving)
   after Claude edits those files. **(verify)**
2. **Database files are lists that start with `null`:** entry ids start at 1 (`Actors.json` is `[null, {...}, ...]`).
   `check` enforces it.
3. **Plugin order matters:** plugins load in the Plugin Manager's order. GameCore must sit above GameMain (`@base`,
   `@orderAfter` make the editor warn, `check` fails). **(verify the editor's warning)**
4. **A page opened from disk does not run:** MZ loads its data with XHR, which `file://` pages may not use. Use
   `python tools/dev.py run` (a local server) or the editor's Playtest.
5. **Browser audio waits for the first click or key** (autoplay policy). The AudioContext warning in smoke is expected.
6. **MZ needs WebGL.** Headless smoke draws in software: it proves boot and logic, not frame rate (SOP-10).
7. **Do not commit MZ's own files to a public repo:** `js/rmmz_*.js`, `js/main.js`, `js/libs/` and the default assets are
   licensed to you as a buyer of RPG Maker MZ for use in your games, not for redistribution on their own (read your
   EULA). A private repo is fine. **(verify against the EULA)**
8. **`tests/support/mzFake.js` is not RPG Maker:** a test that passes there proves your code runs and calls what you
   meant. Only `smoke` (or the editor's Playtest) proves MZ agrees.

## Generated (do not hand-edit)
`node_modules/`, `build/`, `package-lock.json`, `game/save/`, the KitShaders plugin (edit
`tools/shaders/ksl/`, then `python tools/shaders/shader_gen.py`). The editor writes `game/data/*.json` and
`game/js/plugins.js`: edit them only with the project closed (gotcha 1). The images `dev.py dotwork` writes from
Dotwork's art (listed in `<src_dir>/dotwork/mz_export.json`, src_dir is assets_src by default): change the art in Dotwork and convert again; a file
edited by hand is kept, not overwritten.
