# Choosing an Engine (before you scaffold)

> Pick once per game, record it in `docs/adr/` after scaffolding (`/adr`). Evidence IDs point at `core/docs/EVIDENCE.md`.

## Decision tree
First game and no strong preference: **web** (2D) or **web-3d** (3D). Fewest installs (Node.js only), and `START_HERE.md` and
the `make-a-game` skill default to it. Otherwise:
```
Should people play it in a browser with no install (itch.io, a link you share, game jams)?
  yes, and it is 2D -> web     (Phaser 4 + TypeScript: everything is text, instant reload, one link to play)
  yes, and it is 3D -> web-3d  (Three.js + TypeScript: same tooling, you build the game loop on a 3D renderer)
Is it a classic JRPG (maps, menus, turn-based battles) and do you own RPG Maker MZ (or want to buy it)?
  yes -> rpgmaker-mz  (the editor makes maps, events and the database; Claude writes JavaScript plugins and tests their
                       rules in Node. An untested proof of concept: never run against MZ in this kit, its engine steps say (verify))
Do you want the whole game as Rust code, no editor (an ECS engine)?
  yes -> bevy  (Bevy 0.20: everything is text, tests and smoke runs need no GPU; the first build takes 5 to 15 minutes,
                and Bevy changes its API every few months, so Claude checks the pinned version's source)
Is the main goal to learn low-level programming (C++, memory, loops)?
  yes -> cpp-sdl2  (you write the engine layer; slowest path to content, best for learning)
  no  -> Is the game 2D, or stylized 3D that runs on modest hardware?
           yes -> godot  (scenes, scripts and shaders are plain text, so Claude can read and edit almost everything, E04)
           no  -> Do you need high-end 3D (Lumen, Nanite, AAA-style lighting) and own a strong GPU?
                    yes -> unreal  (Claude does C++ and data; Blueprints and maps are binary, so editor work stays yours. E27 claims Claude drove the editor from the CLI, unverified)
                    no  -> unity  (C# plus a large MCP and asset ecosystem; YAML scenes are text but fragile, E16, E20)
Shipping on Roblox, or one of the engines in "Not in the kit yet" below?
  -> no overlay yet. Roblox was done through a Roblox Studio MCP (E26). Copy engines/_template to build an overlay.
     Godot can also export to the web (heavier download).
```

## At a glance
| | Godot 4 | C++ / SDL2 | Unreal 5 | Unity | Web (Phaser 4) | Web 3D (Three.js) | RPG Maker MZ | Bevy (Rust) |
|---|---|---|---|---|---|---|---|---|
| Overlay status | Tested against real Godot 4.7.2 + GUT 9.7.1 on Windows, including export and `run` | Built, tested and smoke-run on Windows (MSVC 14.44, vcpkg); example game: `examples/scrap-tanks` | UE 5.8: C++ compile, tests, smoke and packaging verified (Blueprint-only packaging not yet); example game: `examples/rune-delve` | Tested against Unity 6000.6.6f1 (all but `run`); example game: `examples/graveyard-shift` | Tested on Windows with Node 26: setup, check, test, build, smoke (headless Chromium), clean, `run`, with planted failures | Same tooling as Web, tested the same way except `clean`; starter scene renders in headless smoke; example game: `examples/courier-dash` | **Not run against MZ yet** (built without it): `check`, `test`, `setup --from`, `smoke` and `build` tested against a fake MZ project; example: `examples/lockpick-mz` | Bevy 0.20 on Windows (Rust 1.99.1, MSVC): `doctor`, `check` (rustfmt, clippy), `test`, `smoke` (headless, `--until`, `--fail-on`, `--screenshot`, `--record`), release `build`, `run`, `clean`, with planted failures; example game: `examples/crimson-nebula` |
| What Claude can edit | Almost everything (text resources) | Everything | C++, config, data assets via import; not Blueprints or maps | C#, asmdefs, ScriptableObject code; scenes and prefabs with care | Everything (TypeScript, JSON maps, HTML) | Everything (TypeScript); models come from Blender as .glb | Plugins (JavaScript) and the data JSON with the editor closed; maps and events are easier in the editor | Everything (Rust, RON or JSON data, assets come from other tools) |
| License cost **(verify current terms)** | Free (MIT) | Free (your code; SDL2 is zlib) | Free until a revenue threshold, then a royalty; submit Epic's Release Form before launch | Plan tiers depend on revenue and funding (Personal has a cap) | Free (Phaser is MIT) | Free (Three.js is MIT) | Paid editor; games you make may be sold, MZ's own files only inside them (read the EULA) | Free (Bevy is MIT or Apache-2.0) |
| Hardware | Light | Light | Heavy (strong GPU, about 50 GB install, E27) | Medium | Light (any machine with Node.js and a browser) | Light to medium (players need decent WebGL) | Light (Windows or macOS editor; games run in a browser or NW.js) | Light to run; building needs several GB of disk and a few minutes of CPU the first time |
| Agent tooling seen | No MCP needed (E04); Godot MCPs exist (E06, unread) | Plain CLI | Unreal MCP plugins, CLI | Several Unity MCPs (E17, E20) | Plain CLI; Phaser ships its own agent skills in the npm package | Plain CLI; no bundled skills, use threejs.org docs and the installed examples | Plain CLI (Node, a browser); community MCP servers exist (unread) | Plain CLI (cargo); rust-analyzer in VS Code |

## Not in the kit yet
Popular engines without an overlay. None needs changes to the kit itself: an overlay is `engine.json`, docs, starter files and a
`dev.py` that maps the seven commands to the engine's own tools (`engines/_template/README.md`). Facts here are from general
knowledge, not live-checked: **verify licenses and command-line tools before building one**.

| Engine | Language | Good for | What its `dev.py` would map to | Watch out |
|---|---|---|---|---|
| GameMaker | GML | Beginner 2D, a huge community | Its command-line builder (Igor) | License tiers and the CLI are the least documented of this list (verify) |
| Defold | Lua | 2D, mobile and web, small builds | `bob.jar` (needs Java) for check and build | Unit tests run in-engine |
| LÖVE (Love2D) | Lua | Small 2D games, learning | `love .` for run and smoke (SDL dummy driver for headless, verify); busted or a tiny runner for tests | Footer comments use `--` (the scaffolder supports it) |
| Pygame (pygame-ce) | Python | Learning games with Python | pytest; SDL dummy video driver for smoke | Packaging for players needs PyInstaller or similar |
| Ren'Py | Ren'Py script, Python | Visual novels | `lint` as check; a scripted launch for smoke | Logic lives in scripts, so unit tests are thin |
| MonoGame / FNA | C# | Code-first 2D and 3D (Stardew Valley, Celeste) | `dotnet build`, xunit | Content pipeline tool |
| raylib | C, C++ | Simpler than SDL2 | Same shape as the C++/SDL2 overlay | Could be a variant of it |
| Babylon.js, PlayCanvas | TypeScript | Browser 3D with more built in than Three.js | Same as `web-3d` | PlayCanvas editor hosting terms (verify) |
| Roblox | Luau | The largest young audience | Rojo syncs code as text files | No local headless run: `smoke` and `run` through Studio or cloud tools, or exit 2 "not available" |
| PICO-8 | Lua | Game jams, fantasy console | Its own command line (verify headless) | Paid |
| UEFN / Verse | Verse | Fortnite creators | Nothing: no command line | Docs only; not a fit for the command contract |
| Stride, O3DE, Flax | C#, C++ | Open 3D engines | Their own CLIs | Small communities |
| Ink, Twine | Narrative scripts | Dialogue and branching story | Add-on to another engine, not an overlay | |

## Rules that hold for every engine
- Same command contract: `python tools/dev.py check | test | smoke | build | run | clean | doctor`.
- Same SOPs, same interaction smoke checklist (`SOP-09`), same asset logging (`SOP-04`).
- MCP servers are optional and always get an ADR.
