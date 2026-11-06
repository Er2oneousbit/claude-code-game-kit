# Dotwork: local pixel-art assets for your game

Dotwork makes a game's 2D pixel art on your own GPU, with local models through ComfyUI. You describe what you need in
a small JSON spec; Dotwork writes Godot-ready assets straight into the game (`assets/`), editable sources and review
sheets (`assets_src/`), and a manifest for `docs/ASSET_LOG.md`. Claude (or you) orchestrates; the models only draw.

What it makes (each is a **lane**): animated characters (4 or 8 directions, idle / walk / attack, battle and emote
poses), townsfolk in bulk (walk clips plus palette variants), props with collision scenes, layered terrain with
buildings, interiors and cliffs, side-view platformer tilesets with parallax backgrounds, isometric floors, blocks
and terrain transitions, maps painted from text, fences / pipes / rails, animated water, effects and spells (Wan
clips, or drawn in code: fire, ice, lightning, heal, wind, explosions, projectile orbs, auras), enemies and bosses,
battle backgrounds (optionally with drifting cloud layers), title screens, icons, portraits with expressions and
talking frames, pixel fonts, window skins, HUD widgets (gauges, button states, a Theme), a menu UI kit (one Theme for
every settings / pause menu control in every state, input prompt glyphs, cursors), screen transitions, weather,
small effects drawn in code (arrows, bolts and orbs with trails, dust puffs, pickup twinkles, level-up bursts, and
GPUParticles2D dust / sparkle / ember emitters), status-effect loops, emote balloons, 8-direction vehicles, treasure
chests / doors / switches / save points, props animated by any motion (Wan clips), sprite edits and normal maps,
image-to-pixel-art, store and platform art (every Steam capsule and library size, a logo from a glyph font, the game
icon and `.ico`, achievement icons, a boot splash), title / loading / credits screens, 2.5D dioramas (tiles as 3D
blocks, props and characters as billboards), and bitmap fonts you bring (a BDF such as an OFL CJK pixel font) cut
down to the characters your game's text uses.
Model-free tools: palette swaps (`recolor`, and `recolor_of` in the enemies lane), `clean` (any image to clean pixel
art on the game palette) and `lighting` (normal maps, CanvasTextures, light occluders and a lit demo scene for art
already in the game, computed in numpy).

Tested on Windows 11, RTX 5060 Ti 16 GB, 64 GB RAM, ComfyUI 0.43.0, Godot 4.7.2. Other GPUs and operating systems
should work (Dotwork itself is plain Python + HTTP); the numbers below are what this setup needed, not promises.

## Contents
0. [First run](#first-run-no-gpu-about-10-s) - see it work in seconds, before installing any model
1. [Setup](#setup) - ComfyUI, node packs (review first), models, Godot, Dotwork's config
2. [Commands](#commands)
3. [Pack spec](#pack-spec) - every lane and its keys
4. [Lanes and their limits](#lanes-and-their-limits)
5. [Godot notes](#godot-notes)
6. [Palettes and style references](#palettes-and-style-references)
   - [Hand polish (Aseprite or Pixelorama)](#hand-polish-aseprite-or-pixelorama)
   - [Store art (Steam sizes)](#store-art-steam-sizes)
   - [Image to 3D (tested, not part of Dotwork)](#image-to-3d-tested-not-part-of-dotwork)
7. [Licences](#licences)
8. [Tests](#tests) and [troubleshooting](#troubleshooting)

## First run (no GPU, about 10 s)
The model-free lanes (pixel fonts, window skins, HUD widgets, emote balloons, hit effects; `examples/screen.json` and
`examples/status.json` add transitions, weather and status loops, `examples/vfx.json` projectiles, puffs and
particles) need no ComfyUI and no models, so you can see Dotwork work before installing anything. From your Godot
game's root folder:
```
GODOT_BIN=/path/to/godot python tools/art/dotwork/dotwork.py pack --spec tools/art/dotwork/examples/ui.json   # 102 files, verified in Godot
python tools/art/dotwork/dotwork.py verify            # every Dotwork asset of this game loads in Godot
python tools/art/dotwork/dotwork.py log --pack ui     # a docs/ASSET_LOG.md row + evidence file (run again: it updates)
```
On Windows set the variable first (PowerShell `$env:GODOT_BIN = "C:\path\godot.exe"`). A game without Godot: add
`--engine none` to `pack` (76 files: PNGs, `.fnt` fonts, the manifest; there is nothing to `verify`).

## Setup
You need an NVIDIA GPU (tested; see the tiers in step 3 for VRAM and RAM) and about 78 GB of disk for all models.

### 1. ComfyUI (the model server)
Install ComfyUI in its own folder with its own Python (3.10-3.12). Install the PyTorch build for your GPU first, with
the selector at https://pytorch.org/get-started/locally/, then ComfyUI's requirements:
```
git clone https://github.com/comfyanonymous/ComfyUI            # tested: 0.43.0, commit 0df1646a9cd7
cd ComfyUI && python -m venv .venv
.venv/Scripts/python -m pip install torch torchvision torchaudio --index-url <the URL the selector gives you>
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py --listen 127.0.0.1                # http://127.0.0.1:8188
```
On Linux and macOS the venv's Python is `.venv/bin/python`.
ComfyUI has **no login**: keep it on 127.0.0.1. Dotwork refuses any other address unless you set
`comfyui.allow_remote` (think twice). Either start ComfyUI yourself, or set `COMFYUI_ROOT` and Dotwork starts it on
127.0.0.1 when needed and stops it afterwards (it never stops a server it did not start).

### 2. Node packs (review before you install)
Custom node packs run arbitrary Python inside ComfyUI. Review each one before installing (SOP-16, "Generating pixel
art locally (ComfyUI, opt-in, free per image)": clone into a quarantine folder with git hooks disabled, read it for network calls, `eval`/`exec`, unpickling and
install scripts, pin the commit, copy without `.git`). Dotwork needs exactly two:

| Pack | Pin | Licence | Used for |
|---|---|---|---|
| SpriteKiln (`brunocpf/spritekiln`, folder `ComfyUI-SpriteKiln/` into `ComfyUI/custom_nodes/`) | `864d188071ed45e6f673029d2bc7eb918e17edd7` | GPL-3.0 | 16 `SK_*` nodes + the API workflows Dotwork loads (rotation, animation, edits, inpaint, normal maps) |
| ComfyUI-GGUF (`city96/ComfyUI-GGUF`) | `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` | Apache-2.0 | `UnetLoaderGGUF` (the quantized Qwen and Wan models) |

SpriteKiln notes: **do not run its install.sh or its web UI server (webui/serve.py)** (Dotwork needs neither). Keep the whole repo
clone too and point `SPRITEKILN_ROOT` at it: the folder that holds `workflows/` and `ComfyUI-SpriteKiln/` (the copy
in `ComfyUI/custom_nodes/` is only the node pack and has no workflows). Dotwork only reads `workflows/api/`, by name,
and patches the workflows at run time; it bundles none of SpriteKiln's files (GPL-3.0 vs the kit's MIT). With `.git`
in the clone, `setup --check` confirms the pinned commit; a copy without `.git` works but the check can only warn. The reviewed copy this was
tested with carries one local hardening patch in `SK_SaveParts` (folder containment, nodes_hd.py); Dotwork never uses
that node.

### 3. Models
`python tools/art/dotwork/dotwork.py setup --check` lists every model Dotwork needs, asks your ComfyUI which ones it has,
and prints the pinned URL and the `ComfyUI/models/<folder>/` for each missing file (with ComfyUI not running yet, it
prints the whole list from `models.lock.json`, marked not checked). **Dotwork never downloads
anything**; fetch them yourself (browser, `curl -L -o NAME URL`, or the Hugging Face CLI) and re-run the check.
Save each file under the name the check prints: nine of them differ from the upstream file name (for example the
Wan GGUFs and the LoRAs), and ComfyUI finds them by that name.
`--hash` also compares SHA-256 against `models.lock.json` (needs `COMFYUI_ROOT`; reads tens of GB).

| Tier | Size | What it enables | Minimum (NVIDIA) | Ran here with |
|---|---|---|---|---|
| `sprites` | 15.3 GB | every klein lane: sprites, props, icons, enemies, textures, tiles, buildings, battle backgrounds, edits, poses | 8 GB VRAM, 16 GB RAM | 16 GB VRAM |
| `rotate` | 29.1 GB | 4- and 8-direction rotation (characters, vehicles) | 12 GB VRAM, 24 GB RAM | 16 GB VRAM, 64 GB RAM |
| `animate` | 33.4 GB | Wan 2.2 clips: walks, attacks, spell effects | 16 GB VRAM, 32 GB RAM (18 GB free per clip) | 16 GB VRAM, 64 GB RAM |
| `pose` (optional) | 19.3 GB | skeleton-driven clips (the `skeleton` key): Wan 2.2 Fun-Control A14B, GGUF Q4_K_M, Apache-2.0; uses the animate tier's VAE, text encoder and LoRAs | 16 GB VRAM, 32 GB RAM | 16 GB VRAM, 64 GB RAM |
| all three | 77.8 GB | everything | as `animate` | |

The minimums are the lock's (`models.lock.json`, `tiers`); only the right-hand column was measured.

The klein VAE must be `flux2-vae-klein.safetensors` (Apache-2.0, from `Comfy-Org/flux2-klein`). A file called
`flux2-vae.safetensors` from the FLUX.2 [dev] repo is a different, non-commercial file: Dotwork swaps it out of every
workflow it loads.

### 4. Godot and Dotwork's config
- `GODOT_BIN`: your Godot 4 binary (maps are painted and every asset is verified inside the game).
- `ASEPRITE_BIN` (optional): the Aseprite hand-polish round trip. The Pixelorama one needs nothing set: Dotwork reads
  and writes `.pxo` files itself ([Hand polish](#hand-polish-aseprite-or-pixelorama)). `PIXELORAMA_BIN` (optional)
  only runs the live Pixelorama exam ([Tests](#tests)).
- Python for Dotwork: 3.8 or newer with Pillow + numpy (the ComfyUI venv has both, and works fine to run Dotwork).
- Settings: copy what you want to change from `config.example.json` into `<game>/art_src/dotwork/dotwork.config.json`.
  That file is tracked in git and can name programs Dotwork runs (`godot_bin`, `aseprite_bin`, `comfyui.python`,
  `comfyui.root`): review changes to it like code, especially in pull requests.
  Environment variables win over both: `COMFYUI_URL`, `COMFYUI_ROOT`, `COMFYUI_PYTHON`, `SPRITEKILN_ROOT`,
  `GODOT_BIN`, `ASEPRITE_BIN`, `DOTWORK_WORK`. Dotwork writes its caches, the renders it fetches from ComfyUI and its
  log to `art_src/dotwork/` and drops a `.gitignore` there that keeps everything but `dotwork.config.json` out of git (keep
  your specs somewhere else, such as `assets_src/specs/`), plus an empty `.gdignore` so Godot never tries to import
  the raw renders (ComfyUI's animated `.webp` clips fail Godot's importer).
```json
{ "spritekiln_root": "/path/to/spritekiln", "godot_bin": "/path/to/godot",
  "style_refs": ["assets_src/sprites/hero_south.png", "assets_src/sprites/npc_baker.png"],
  "project": { "assets_dir": "assets" } }
```
Then: `python tools/art/dotwork/dotwork.py setup --check` until it says `[ OK ] ready`.

## Commands
Run from the game's folder (or pass `--project GAME`). Global options, before or after the command:
`--project GAME`, `--config FILE`, `--engine godot|none`, `--debug`. Exit codes: 0 ok, 1 a task failed, 2 environment
or usage (the `[error]` line says what to fix). `preview KIND --help` lists each preview's own options.

| Command | What it does |
|---|---|
| `setup --check [--tier T] [--hash]` | readiness: Python, ComfyUI, node types, models, SpriteKiln commit, Godot, palettes |
| `pack --spec FILE [--no-verify]` | build every lane in the spec into the game, then verify it in Godot |
| `character --name N --prompt TEXT \| --source PNG [...]` | one character (see `--help`: actions, directions, `--fix`, `--poses`) |
| `audition --name N --clip walk_e --seeds ...` | extra takes of one clip on one sheet; `--promote TAG` ships one |
| `materials [--only ...] [--extend-palette]` | render the material catalog for review; grow the environment palette |
| `palette extract\|extend ...` | build a palette from your own art |
| `recolor --source GLOB --hue DEG\|--to #RRGGBB --out DIR` | palette swap, no model: turns the coloured ramps, keeps outline and greys, snaps to the palette; every file shares one colour map, so an animation stays consistent |
| `clean --source GLOB --out DIR [--cell N\|--width W]` | any image to clean pixel art, no model: measures the pixel grid of upscaled or generated art (or shrinks to `--width`), keys a plain background, snaps to the palette (`--palette none --colors N` reduces instead), drops specks; `--outline #RRGGBB` adds one |
| `verify` | load every Dotwork asset of this game in Godot (shader materials compiled, held frames counted) and run its smoke test |
| `qa pack [--json OUT] [--lineup OUT.png]` | style check over every PNG the game's manifests list (not sheets, normal maps, or store art, the game icon and boot splash, which are scaled up on purpose), read only: pixel scale, each lane's palette lock (the table under Palettes), outline colour and thickness, light side, figure height in tiles, contrast on the ground tiles, colour-blind separation of gauge fills, status marks, button states and palette swaps (Machado 2009 simulation); `--lineup` draws every character and prop at game scale on a ground tile; exit 1 on findings |
| `aseprite [--reexport] [--overwrite]` | editable `.aseprite` sources (frames timed by their holds); push hand-polished files back |
| `pixelorama [--reexport] [--overwrite] [--clear-export-path]` | the same round trip with Pixelorama `.pxo` files, no install needed, plus tilemaps (yours into a TileSet and maps; the game's maps and TileSets into tilemap projects and back); `--clear-export-path` blanks the local export folder Pixelorama saves in each file; `--install-extension` puts the Dotwork panel into Pixelorama (`--info PXO` is what it asks) ([Hand polish](#hand-polish-aseprite-or-pixelorama)) |
| `preview battle\|title\|attack ...` | mock screens composed from the game's art (review only) |
| `capture --scene S [--frames N] [--fps F] [--size WxH] [--gif]` | record any scene with Godot's Movie Maker: a fixed frame rate, every frame written as PNG (trailer cuts, side-by-side reviews), a contact strip and an optional GIF; a window opens for the capture |
| `log --pack NAME [--dry-run]` | `docs/ASSET_LOG.md` row + evidence file for a pack |
| `fonts-check --font F --strings FILE... [--caps-only]` | font coverage, no model, writes nothing: every character the strings use (JSON string values at any depth, CSV / Godot translation CSV, PO / POT, plain text) must be in the font (a glyph file or a built `.fnt`); lists each missing one with its language and string ids, exit 1 when one is missing |
| `config` | print the merged settings |

A run resumes: renders are cached in the work folder under a key of everything that shapes them (prompt, seed, size,
palette contents, style reference), so re-running a spec only renders the entries you changed. An entry without a
`seed` gets one from its name, so adding or reordering entries never changes the others. A character's clips
re-render one by one when their `clip_fix` seed or motion, or the character's `motions` / `subject` wording, changes;
a new character design (prompt, source, seeds, height, symmetry, reference) moves its earlier renders to
`art_src/dotwork/<name>/_old_<key>/` and starts fresh. Every PNG Dotwork ships is saved without metadata (ComfyUI embeds
the prompt and local paths).

## Pack spec
A JSON object with a `"name"` and any of the lane keys below. Prompts describe the subject; Dotwork adds the
pixel-art wording. Ready-to-run specs for every capability are in `examples/` (see examples/README.md); the shapes:
```json
{
 "name": "town",
 "characters": [{"name": "guard", "prompt": "a town guard in a brass helmet", "actions": ["idle", "walk", "attack"],
                 "poses": "battle", "clip_fix": {"walk_n": {"seed": 4247}},
                 "variants": [{"name": "guard_winter", "edit": "a fur-lined winter coat"}, {"name": "guard_red", "hue": 130}]}],
 "npcs": [{"name": "baker", "prompt": "a plump baker in a white apron", "variants": [{"name": "baker_green", "hue": 120}]}],
 "props": [{"name": "gas_lamp", "prompt": "a cast iron gas street lamp", "size": 56, "footprint": "trunk"}],
 "ground": {"name": "town", "base": [{"material": "grass_lush", "variants": 4}],
            "overlays": [{"material": "dirt", "relief": "flat"}, {"material": "cobble", "relief": "raised"},
                         {"material": "water_deep", "relief": "sunken", "solid": true, "animate": {"frames": 4}},
                         {"material": "roof_clay", "style": "roof", "solid": true}, {"name": "fence", "style": "fence_wood"}],
            "fixtures": [{"name": "door", "cells": [1, 2], "fit": "height", "prompt": "a wooden door"}],
            "map": {"name": "square", "rows": ["ggdd", "gccd"], "legend": {"g": [], "d": ["dirt"], "c": ["dirt", "cobble"]},
                    "objects": [{"fixture": "door", "at": [1, 0]}], "props": [{"prop": "gas_lamp", "at": [0, 1]}]}},
 "effects": [{"name": "fire", "subject": "a burst of flames", "motion": "the flames burst up and die down", "keep": 6}],
 "enemies": [{"name": "hound", "prompt": "a brass guard hound", "size": 80},
             {"name": "frost_hound", "recolor_of": "hound", "hue": 150}],
 "battle_bgs": [{"name": "mine", "prompt": "an underground mine with lanterns"},
                {"name": "plains", "prompt": "grassy plains under a big cloudy sky", "scroll": -4}],
 "scenes": [{"name": "title", "prompt": "a brass city at dusk under airships"}],
 "icons": [{"name": "potion", "prompt": "a red potion bottle"}], "portraits": [{"name": "guard", "prompt": "...", "expressions": true, "talking": true}],
 "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt", "effect": "shadow"}],
 "windows": [{"name": "classic", "style": "classic"}], "balloons": [{"name": "exclaim", "symbol": "!", "color": "d83a3a"}],
 "widgets": [{"name": "hud", "style": "brass", "gauges": ["hp", "mp", "atb"]}],
 "uikit": [{"name": "menu", "style": "iron", "font": "assets/art/ui/fonts/font_dialogue.fnt", "keys": ["minus"]}],
 "transitions": [{"name": "battle_swirl", "kind": "spiral"}, {"name": "mosaic", "kind": "mosaic"}],
 "weather": [{"name": "storm", "kind": "rain", "intensity": 0.8}],
 "status": [{"name": "poison"}, {"name": "zzz", "kind": "sleep"}],
 "hitfx": [{"name": "spark", "kind": "spark"}, {"name": "flash", "kind": "flash"}],
 "spells": [{"name": "fire"}, {"name": "frost", "kind": "ice"}, {"name": "zap", "kind": "bolt", "color": "#ffe070"}],
 "vfx": [{"name": "arrow"}, {"name": "spark_bolt", "kind": "bolt", "trail": "line"}, {"name": "step", "kind": "footstep"},
         {"name": "forge_embers", "kind": "ember_particles", "amount": 24}],
 "animprops": [{"name": "chest", "kind": "chest", "prompt": "a wooden treasure chest"},
               {"name": "torch", "kind": "flame", "prompt": "a wall torch with a lit flame"},
               {"name": "pot", "kind": "clip", "prompt": "a clay pot", "motion": "it bursts into pieces"}],
 "vehicles": [{"name": "airship", "prompt": "a steampunk airship", "size": 72}],
 "tools": [{"name": "guard_edit", "source": "assets/art/characters/guard/frames/spr_guard_idle_s_00.png",
            "edits": ["give him a red scarf"], "normal": true}],
 "img2px": [{"name": "tower", "source": "assets_src/concept/tower.png", "width": 96}],
 "store": [{"name": "iron_oven", "title": "Iron Oven", "prompt": "a knight in iron armour holding a long loaf of bread",
            "icon": "a round loaf crossed with an iron sword", "apply": true,
            "achievements": [{"name": "first_loaf", "source": "assets/art/ui/icons/ui_icon_bread_32.png"}]}],
 "bdf": [{"name": "ja", "source": "assets_src/fonts/ark-pixel-12px-proportional-ja.bdf",
          "license": "assets_src/fonts/OFL.txt", "strings": ["data/strings_ja.json"]}],
 "diorama": [{"name": "yard", "legend": {"g": {"top": "assets/art/tiles/street/base_grass_lush.png"},
                                        "w": {"top": "assets/art/tiles/street/overlay_cobble.png", "tile": "solid",
                                              "side": "assets/art/tiles/street/overlay_stone_wall.png", "height": 1}},
              "rows": ["gggg", "gwwg", "gggg"], "sprites": [{"source": "assets/art/props/spr_barrel.png", "at": [0, 2]}]}],
 "screens": [{"name": "title", "kind": "title", "backdrop": "assets/art/scenes/spr_scene_title.png", "title": "Iron Oven"},
             {"name": "loading", "kind": "loading", "backdrop": "assets/art/scenes/spr_scene_title.png"},
             {"name": "credits", "kind": "credits", "backdrop": "assets/art/scenes/spr_scene_title.png", "file": "CREDITS.md"}],
 "platforms": [{"name": "meadow", "fill": {"material": "dirt"}, "surface": {"material": "grass_lush"},
                "background": {"prompt": "rolling green hills under a blue sky"}}],
 "iso": [{"name": "village", "floors": [{"material": "grass_lush", "variants": 2}, {"material": "cobble"}],
          "blocks": [{"name": "wall", "top": {"material": "stone_floor"}, "side": {"material": "brick_wall"}}],
          "transitions": [{"upper": {"material": "cobble"}, "lower": {"material": "grass_lush"}}]}],
 "lighting": [{"name": "town_lit", "frames": ["assets/art/characters/*/*_frames.tres"],
               "tilesets": ["res://assets/art/tiles/street/ground_street_tileset.tres"],
               "props": ["assets/art/props/spr_*.png"], "bevel": 3, "light_color": "#ffd8a0", "light_energy": 1.2}],
 "design": {"setting": "steampunk", "character": {"fig_height": 66}, "tile_px": 32}
}
```
**Art direction.** No built-in prompt assumes a world. `design.style` (the art era, default `"16-bit era"`),
`design.genre` (default `"RPG"`) and `design.setting` (default empty) fill every template, from the spec's `design`
or from `dotwork.config.json`: `"setting": "steampunk"`, `"cozy farm village"` or `"neon cyberpunk city"`. The
examples set `"steampunk"` because that is their sample content. Changing them re-renders what they shape (the cache
keys and a character's design stamp include the filled-in prompt).
Each lane module's header documents its keys in full (`lane_<name>.py`). A key no lane reads (a typo such as
`"styl"`) is reported as a `[warn]` line; an entry without a `"name"`, or without a key its lane needs, stops the run
with an `[error]` naming it.

Paths in a spec (`source`, `glyphs`) are relative to the game folder and must stay inside it: Dotwork refuses `..`
escapes, absolute paths and network paths in a spec, because specs get shared. An absolute path you type yourself on
the command line (`character --source`) is fine. `glyphs` files are looked up in Dotwork's own `glyphs/` folder first,
then in the game. Every other name a spec gives (entry names, character actions and pose names, font `export` file
names, map props) becomes a snake_case file name, so none of them can point outside the game either; character
`directions` accept only `s`, `e`, `n`, `w` and the diagonals `se`, `ne`, `nw`, `sw`.

## Lanes and their limits
Honest list: these are the failure modes seen in testing and what Dotwork does about them.

| Lane | Limit | What Dotwork does / you do |
|---|---|---|
| characters (Wan clips) | Attacks sometimes turn the character toward the camera; back views sometimes grow a face | `keep=N` ping-pongs the good frames; back idles are a procedural 1 px bob; `audition` renders takes side by side; the turn warning misses some turns, so judge the sheet |
| characters (Wan clips: drift, matte, shadow) | A clip can drift into another view's design (a staff the side view does not have, a turned body); the generator's white could stay between the limbs as a matte; the ground shadow could blink because each frame was judged alone (#24, #22, #25) | Drift: colours another direction's sprite has and this one lacks, over 4 % of the figure two frames running, trim the clip to the frames before it (played back and forth) when 3 or more remain, and otherwise stop the character with an audition command to run; `clip_fix: {"<clip>": {"allow_drift": true}}` keeps it. A small feature (a beak, about 1 %) is not caught: the head-signature note still asks for review. Matte: flat generator white touching the outside in the unlocked frames is removed with its rim; skipped when the sprite itself is 5 % or more white (clothing and matte look alike) or has white at its own edge. Shadow: the clip learns its shadow colours from the frames where the per-frame pass worked and removes them under the feet in every frame |
| npcs | Each NPC is still a rotation and a Wan clip per walk direction (about 8 minutes for a symmetric one) | Idles are the code-drawn breathing bob in every direction (`idle: "clip"` renders them), so walk is the only clip; `variants` recolour the finished NPC into more townsfolk with one colour map across every frame, no render |
| characters (skeleton) | A free image-to-video clip decides the motion itself: strides vary, limbs drift, loops do not close | `"skeleton": ["walk", "run"]` drives those actions with a procedural OpenPose skeleton (walk, run, idle, attack, jump, hurt, cast, shoot, death; side, three-quarter and front / back views, chibi proportions) fitted to exactly where the sprite sits on the model canvas; Wan 2.2 Fun-Control follows it. Needs the optional `pose` tier (`setup --check --tier pose`). The skeleton fixes the motion, not the drawing: judge the sheet as usual. Every clip used to be pinned to the feet line frame by frame, which flattened a jump into standing frames (the skeleton lifts the feet 18 % of the figure and Wan follows): a jump now keeps its height (Godot notes). Hurt, cast and shoot plant the feet and come back to rest (hurt: lean back and guard the face; cast: draw the hands in, thrust them out, hold; shoot: raise the weapon, aim, recoil). Death is the one clip that does not loop: stagger, drop to the knees, fall backward (side views) or sideways (front and back), and lie still, centred where the character stood. The lying frames are wider than a standing figure, and every animation of a character shares one canvas, so `death` widens all of them; the feet stay on the same line. Back-view idles stay the code-drawn bob even when `idle` is in `skeleton`; `"clip_fix": {"idle_n": {"wan": true}}` renders one from the skeleton instead (the back view has no face points, and the live check drew a gentle breathing back with no face on the head, one take out of one). Live check of run, idle, attack, jump, cast and shoot (2026-11-03, one symmetric test character holding a sword, 4 directions, one take per clip; walk earlier), every clip loaded in the in-game verify: the side views follow the skeleton (run strides, attack's overhead swing, a jump's crouch, rise, tuck and landing with its height kept, cast's thrust and hold). Front and back views move less, because motion toward or away from the camera foreshortens: the front attack reads as a sideways flourish, the back attack barely moves until its last two frames, and front and back cast and shoot bring the hands to the chest. A held item can leave the hand when the skeleton moves it: the sword vanished while both hands cast and came and went during shoot (a few loose pixels of it stayed beside the front cast), and Wan drew a small spark in front of the casting hand. Judge strikes on the sheet and give a game that strikes toward the camera side-view strikes or its own art. Hurt and death are not rendered live yet |
| characters (polish) | A generated clip shows every frame for the same time and draws no in-betweens: a strike has no wind-up, no weight and no hit-stop, and a sprite has no flash or dissolve for a hit or a defeat | All opt-in: an entry without these keys exports the same files as before. `"holds": true` times attack, cast and shoot around their frame of peak motion, measured from the frames (the silhouette change between each frame's neighbours, body aligned); a skeleton clip uses the skeleton's own strike frame instead (the middle of the swing, the middle of the thrust, the shot's recoil), found from the frames SpriteKiln kept, which each new render records: the frame before it is held as the wind-up, the frame after it as the impact (attack 2 and 3, a hit-stop; cast 2 and 2; shoot 3 and 1.5). `{"attack_w": [1, 1, 2, 1, 3, 1, 1, 1]}` lists one clip's durations, `{"walk": {"3": 2}}` holds single frames (numbered from 0, as in the file names), `{"shoot": {"windup": 3, "impact": 1}}` sets the pair. `"smear": true` redraws that peak frame with the moving part dragged back along its motion in the frame's own colours, thinning to a checker; it replaces the frame (the count, loop and holds stay). The body is aligned first and outline redraws are ignored, but on an 8-frame Wan clip a thin blade leaves a small smear and a part that sweeps over the body leaves none (the QA note says which): judge the sheet. Only a part is dragged: the body's thick mass (torso, coat, legs) and the feet are left out, and a frame where the body made most of the change (a step or a lunge reshapes the coat and moves the boots) gets no smear, with a note saying so. `"anticipation": true` gives skeleton attack, cast and shoot a wind-up (lean away, sink, draw the arm back, then strike; `{"cast": 0.5}` for less); it is a new skeleton, so those clips re-render. Live check (2026-11-03, one test character, attack, cast and shoot with and without it, 4 directions, one take each): the side views show the wind-up clearly (the sword goes over and behind the head as the body leans back; the body leans back and the hands gather before the cast; the arm draws back, then the shot points at full length, which the plain clip never reached), the front and back views barely change (a small lean, the arms opening), and Wan added debris in two back views (a grey streak beside the attack, sword fragments at the hip in the shoot). Holds on a plain skeleton shoot used to land on the rest frame (its largest motion is the arm coming up); with anticipation they landed on the drawn-back aim (verify counted the 24 held frames in both runs). The strike frame fixes that: on those live frames the aim before the shot is held, then the recoil (checked offline, not re-rendered (verify)). A trim that cuts the strike off (`keep`, a drift trim) falls back to the measured peak; list a clip's durations (`{"shoot_e": [...]}`) to place them by hand. The party example's duelist (2026-11-04, a rapier, attack and cast in 4 directions, one take each): the attack smear landed on the west strike and was skipped in the other three (under 6 px clear of the body), the holds put the east attack's wind-up on the blade drawn back and its hit-stop on the blade out in front, and the cast smears dragged the sinking coat hem and feet into a checker, so the example smears the attack only. `"shaders": true` writes the damage flash (the hitfx lane's, the same files) and a pixel-art dissolve to `fx/shaders` (Godot notes) |
| characters (8 directions) | Each generated direction is another set of clips (a symmetric 8-way character renders s, se, e, ne and n; w, sw and nw are mirrors) | Add the diagonals to `directions`; the rotation runs 8-way (about 200 s) and the back diagonals idle in code like n. The animation node knows one diagonal view wording ("three-quarter view"), so diagonal clips drift toward front or side more often than cardinal ones: judge the review sheet |
| character variants | Editing each finished frame for a new outfit flickers (every frame gets its own coat) | `variants` with `edit` render a whole character from the once-edited south sprite (a full character's cost); with `hue` / `to` they recolour every frame with one map and cost nothing |
| characters (four-legged) | The character lane draws upright chibi figures and the skeleton is a person's: asked for a warhorse, it drew a horse standing on two legs in a hood, and its back-view walk turned to face the camera (2026-10-31 rehearsal) | A two-legged mount (a big bird, a walker machine: the `mount` example) works as a character. A horse or a wolf to ride is an 8-direction `vehicles` entry for now: it turns, but has no walk cycle |
| characters (held weapons) | An east view faces right, so a weapon in the right hand is on the far side of the body: in seven trial designs (2026-11-04, one take each) a sword, an axe and a staff vanished behind the body or the head in the side views, and a skeleton attack swung the empty arm. Asking for the left hand did not change which hand the model drew | Design for it: a weapon held up high (the dwarf example's hammer shows above his helmet in every walk frame) or worn on both hands. A free Wan attack (leave `attack` out of `skeleton`) brought the dwarf's hammer down in front of him where the skeleton clip did not; the turned-around check reads where the face sits when one shows, so such a swing is not a turn (#190); with no face (a full helmet) it falls back to the head's colours, which a swing can change, so judge the sheet |
| characters (asymmetric) | A mirrored west view swaps which arm holds the signature item | `"asymmetric": true` generates west instead of mirroring |
| characters (which way a view faces) | The rotation model reads "right side view" either way round from one character to the next (one test character's east view faced left, another's faced right; a front quarter view flipped on a third), so a fixed output order put some characters' east walk on the west | After the rotation, each east / west pair is judged by where the face sits in the head and swapped when the east view faces left (the log says so; clips and poses made from it move to `_old_facing/` and re-render). Back views and faceless characters (helmets, machines) cannot be judged: the manifest asks you to check them on the review sheet, and `"rot_swap": ["ne"]` swaps a pair by hand |
| battle / emote poses (klein edits) | Vague wording returns the idle pose; some poses drop a signature prop | Wordings that name body positions (`BATTLE_POSES`, `FIELD_POSES`), `pose_text` per character, a per-pose seed fix (`clip_fix: {"weak_w": {"seed": N}}`). A pose named like one of the character's actions in a direction that action has a clip (the battle set's `cast`, `hurt` and `jump`) ships beside the animation as `<pose>_pose_<dir>` (`cast_pose_w`), and its fix entry uses that name |
| effects (Wan) | Motion can turn particles into a face or a little figure | Effect-only prompt wording, `keep`, a new seed; review every effect. Or use the `spells` lane: fire, ice, bolt, heal, wind, burst (one-shots), orb and aura (loops), drawn in code with the kind's colour ramp or your own (`color`, `colors`), so every frame is exact, free and repeatable; it cannot draw a one-off subject (a summon's creature), which stays a Wan effect |
| store | The key art is a render: the hero can land anywhere, and a busy picture leaves no calm spot for the logo. Steam allows no text but the game's name (and an official subtitle), none at all on the library hero | Each size crops the key art at a whole-number scale around `focus` (by default the centre; for the lane's own renders moved up per size until the crop keeps the top of where the prompt places the hero, which the centre crop of `small_capsule` and `library_hero` cut off) and puts the logo on the calmest spot outside where the prompt places the hero (`logo_anchor: "fixed"` keeps the table's spots); review the sheet and pass your own `source` / `tall_source` art when a render will not do. The logo font has capitals, digits and title punctuation only (a missing character stops the run naming it). Screenshots are not made: Steam wants gameplay, so capture them from the game (`capture`, or the kit's `dev.py smoke --screenshot`) |
| screens | A title screen's buttons only show: what New Game does is the game's | The kit's shell wires its own menus; use the screen as the backdrop and logo layer, or wire the buttons' `pressed` signals. The credits roll scrolls for a length worked out from the line count (24 px a line), so a theme with a much larger font needs `seconds` raised |
| bdf (fonts you bring) | Hand-drawn glyph text cannot cover Chinese or Japanese (thousands of characters); a complete CJK pixel font is a download, and every glyph of it would make a big font | Point `source` at a BDF (Ark Pixel Font, OFL-1.1: github.com/TakWolf/ark-pixel-font, the 12 px proportional BDF set has ja, ko, zh_hans, zh_hant, zh_hk and zh_tw variants of 26,179 glyphs each; pick the variant of the language, since shared characters are drawn differently) and `strings` at the game's text: the `.fnt` keeps only the characters used plus ASCII (a menu and a story line came to about 120 glyphs on one 256 px page). A character the strings use that the font lacks stops the run naming it, the file and the key. Not checked: right-to-left scripts and shaping (Arabic, Hebrew), which BMFont cannot lay out |
| diorama (2.5D) | Flat sprites in 3D are cards: a side-view prop shows its one face from every angle, and a character's 4 directions do not turn with the camera | Billboards turn around their vertical axis to face the camera (fixed-Y), so keep the camera's yaw fixed (the lane's camera looks from the south) and pick the animation that faces it (`walk_s`); blocks put the same side tile on all four faces. Image-to-3D models are not part of Dotwork: Bozzetto (`tools/bozzetto/`) makes them |
| vfx (drawn in code) | Particles are a Godot node, so their exact motion cannot ship as frames; a projectile's Line2D trail is a fixed streak behind the body, not a record of its path | Projectiles (arrow, bolt, orb: flight loops pointing right) carry a trail that fades along its length: a sprite strip (frames, works in any engine), a Line2D with a stepped gradient, or a world-space GPUParticles2D that lags behind as the node moves (`trail`; use particles for curving shots). Puffs (dust, footstep, landing) and bursts (pickup_sparkle, level_up) are one-shots that end on an empty frame. `dust_particles`, `sparkle_particles` and `ember_particles` are GPUParticles2D scenes with a white mask texture and colour steps from the ramp over each particle's life (`amount`, `one_shot`); `vfx_<name>_particles.json` lists the same settings for other engines, and the review sheet shows a simulated preview, not Godot's run |
| sprites / props / icons | The refine pass can grow a figure past its canvas | Re-rendered smaller automatically (never rescaled); an icon prompt that fills the frame (a spiral) can still fail: reword it |
| sprites | White background trapped inside a figure | Removed automatically; skipped for white subjects (`keep_white` / `holes` override) |
| enemies (ground slabs) | The model bakes a soft ground shadow under a figure, and the palette has no dark neutral, so it came out as a light-grey slab (#28, #26) | Removed automatically (wide, flat, light, under the feet, with the outline ring that framed it; `keep_shadow: true` keeps it) and replaced by a dark dithered contact shadow drawn in code: `spr_enemy_<name>_shadow.png`, a `Shadow` child drawn behind the sprite (`shadow: false` skips it). Props: `"slab": "remove"` opts in (an iso plinth looks like a slab, so it is not the default) |
| props (white pockets) | Trapped white background and flat white glass, paper or a dial look the same | Not removed by default; each candidate pocket is named in the log and the manifest QA with its box, and `holes: true` clears them |
| without `style_refs` | New art matches itself less closely (no reference to copy) | Bring 3-4 of your own finished sprites as `style_refs` |
| 8-direction vehicles | The rotation model treats its source as the front: a three-quarter source shifted every view one step, and a straight front view comes back as a flat cutout | The source stays three-quarter, all 8 views are generated, and `source_facing: "auto"` labels them by which views mirror each other (the log prints the scores). The review sheet runs s, sw, w ... clockwise, so a wrong view breaks the turn; `source_facing: "se"` (or `rot_order`) fixes it |
| palette swaps (`recolor`) | A swap turns hues; it cannot add a colour the palette lacks (a blue variant on a palette with few blues comes out greyer) | `--palette env` or your own palette; `--hues LO HI` limits the swap to one part (the red cloak only); `--min-chroma 0.04` (`min_chroma` in a spec) keeps dark browns and muted tones, so only the trim turns |
| `clean` | Generated "pixel art" often has no true grid (cells drift), so `--cell auto` cannot measure one | It refuses with the x / y sizes it saw; give `--cell N` or `--width W` |
| talking portraits | Mouth flaps drawn as whole new portraits would shift the hair and collar every frame | `"talking": true` adds the talk and blink frames; only the mouth band (0.52-0.82 of the bust height) and the eye band (0.26-0.50) of their edits are kept, so nothing else moves. SpriteFrames idle / talk (an uneven 6-frame flap at 10 fps, looping while text prints) / blink (once), a scene, and a sheet + JSON. No audio lip sync |
| icons at 16 px | A 14 px render came back as a blob for 5 of 39 icons, and a crashed run left items in one size only | Only the largest size is rendered; smaller sizes are reduced from it (same design, 1 px margin, fresh outline) and the run fails if any size is missing. `"small": "render"` renders every size instead |
| portrait expressions (klein edits) | An edit can redraw more than the face (hair, collar) or barely change it | `face_only` (default) keeps only the face box of the edit, so the rest stays pixel-identical, and logs a QA line when most of the edit fell outside it; `expression_fix: {"angry": {"seed": N}}` for another take |
| treasure chests / doors (states) | Each state was drawn on its own, so the chest morphed instead of opening (#27) | States are edits of the closed render, and only the moving part is kept: the chest's lid (its upper half and anything above), the door's panel inside its frame; the rest stays pixel-identical. Door edits skip the background flood (a door fills its cell, and the flood ate light planks). A QA line names a state whose edit mostly fell outside the moving part (it may look unchanged: another seed, or `whole_edit: true`) |
| ambient props (`flame`, `flag`, `smoke`, `spin`, `sway`) | Animation models drift and do not loop exactly | The motion is code on one render, so every loop is exact: fire flickers in its own colours, a banner waves pinned at its pole, smoke puffs rise from the top (the canvas grows 28 px), a gear turns one symmetry step (render the turning part on its own), a plant sways at the top. `flame` stops the run if the render has no fire colours |
| animated props (`clip`) | The code loops move pixels; they cannot change an object's shape (a pot breaking, liquid churning) | `"kind": "clip"` with a `motion` runs Wan 2.2 on the prop's render, palette locked to its colours; a one-shot keeps its first and last frames (`start` / `play` / `end` / `back`), `"loop": true` finds a loop point (`idle`). Wan keeps its subject in frame, so a change that removes the object (a pot bursting) comes back whole: use an effect over the prop for that. Like every model clip it can drift or redraw the object: review the sheet, a new `seed` gives another take, `anchor` changes how frames are aligned (default sideways only); Wan's grey ground shadow is removed (a faint shadow tinted by the prop's colours, right against it, can remain: judge the sheet); `"slab": "remove"` (any animprops kind, opt-in as for props) strips a flat light-grey ground slab under the base render before anything is animated from it; a light shadow cast diagonally beside the prop is not a slab and stays (a new `seed` or an edit of the base) |
| platforms (side view) | A platformer needs edges, a top surface and one-way ledges that join in every combination | 16 tiles indexed by which sides are exposed (fill inside, the surface lip on top, shaded rims and an outline on open sides, rounded outer corners) plus 3 one-way pieces; a Match Sides TileSet with full-tile collision that `verify` paints and checks side by side; the background is made seamless left to right and ships with a ParallaxBackground scene |
| iso (2:1 isometric) | Iso tiles drawn one by one do not continue each other | Floors and blocks are projected from the ground lane's seamless textures, so neighbouring diamonds continue one texture; blocks are taller tiles with a texture origin. `transitions` add the 16 corner tiles between two materials (the pair lane's wang16 tiles, projected the same way), a Match Corners terrain set per pair that Godot's terrain tool paints; `verify` paints shapes in both directions and checks every shared corner across the diamond's sides |
| uikit (focus on sliders) | Godot's `Slider` draws one highlight for hover and for focus (`grabber_highlight`, `grabber_area_highlight`), so no Theme can tell a hovered slider from a focused one | Every other control gets a focus ring in its own colour drawn outside the control (never a brighter hover); the slider highlight uses the focus colour, and the kit's settings screen outlines the focused row. The test suite composites focus and hover of every control from the shipped textures and compares them pixel by pixel |
| uikit (glyphs) | Prompt glyphs are generic drawn shapes: letters in neutral circles, outline cross / circle / square / triangle, a four-dot diamond, labelled shoulders and triggers, a lit d-pad arm; no maker's logos or colours | One neutral set per game (`assets/ui/glyphs/`), shared by every uikit entry; a rebound key with no glyph yet: add it to `keys` (the label comes from the glyph font), or the shell shows its text label |
| fonts | Models cannot draw consistent letters | Glyphs are text bitmaps (`glyphs/*.txt`), built into BMFont `.fnt`; edit a letter by editing its rows |
| fonts (accents) | A 9-row font has no room above a capital for an accent, and a missing glyph shows as a gap in game | `glyphs/dialogue_latin.txt` and `glyphs/title_brass_latin.txt` add Latin-1 Supplement and Latin Extended-A (French, Italian, German, Spanish, Portuguese, Polish, Czech, Hungarian, Turkish) with 2 (title: 3) rows above the capitals for accents, so their line is taller; their ASCII glyphs are the old ones, unchanged. The title font is capitals only: with `caps_only` accented lowercase uses its capital, but ß and ı have none. `"check": ["assets/i18n/strings.csv"]` on a font entry (paths in the game, like `glyphs`; or `dotwork.py fonts-check`) lists every character the game's strings use that the font lacks, with its language and string ids, and fails the pack (exit 1) after building every font |
| battle backgrounds / scenes | 320x128 / 320x180 art shown at 2x (chunkier than 1x sprites) | Same exact-2x scale everywhere it is used |
| battle backgrounds (moving sky) | Cutting the painted sky off at the horizon and scrolling it split mountain peaks (the tip drifted away from its base) | `"scroll": -4` keeps the picture whole and adds two cloud layers drawn in code in its own lightest sky colours (far: small, half speed; near: bigger, full speed) that tile sideways; `horizon` sets how far down they reach, `clouds` how many. They drift over far mountains, which reads as nearer clouds; leave `scroll` off for caves and interiors |
| pixelorama tilemaps | Pixelorama keeps one flat list of square tiles with no animation, collision or custom data, and its Auto and Stack tile modes add and renumber tiles as you draw | Your own tilemaps: collision and surface come from each tile's user data (`solid`, a surface name), terrains and probabilities carry over. A game's map edited there keeps its TileSet: each tile carries its atlas slot, so a renumbered tile still lands in its slot, and a tile Pixelorama added stops the re-export with the fix (draw in Manual mode); an animated tile's other frames stay as they are |
| lighting (normal maps, no model) | A normal map guessed from one picture cannot know the real shape: it reads a rounded rim from the alpha edge (`bevel` px) and small relief from brightness (`detail` px), so dark paint reads as a dent and a flat-coloured cloak reads flat; an atlas tile cannot see its neighbours | Opaque tiles get no rim at their borders and the brightness relief wraps inside each tile, so Dotwork's seamless tiles stay seamless (a tile whose opposite edge is clear repeats its own edge instead). Occluders are the largest opaque region only, `base` (default) spans the feet of the bottom quarter, `full` the whole outline, at most `occluder_points` corners, never self-crossing (a crossing outline falls back to its convex hull). A sprite node that is scaled, flipped or nested in its own scene gets a fresh lit scene instead of a copy. Headless Godot renders nothing: `verify` proves the lit resources are wired (both textures, same size, normals that decode with z > 0, occluder polygons, cells on lit tiles), not how the light looks; judge `assets_src/art/lit/<name>/<name>_review.png` and the demo scene in the editor |
| `--engine none` | Maps, TileSets, scenes, SpriteFrames and the damage-flash and dissolve shaders are Godot resources | PNGs, sprite sheets + their JSON (with any hold `durations`), BMFont `.fnt` fonts, 9-slice margins (in the manifest) and the manifest still ship; maps and the shaders are skipped with a log line; the hand-polish round trip (`aseprite`, `pixelorama`, `--reexport`) works the same, with no `verify` |

Timing on the tested GPU: a sprite about 18 s, a texture tile with variants about 25 s, a Wan clip about 110 s, a
4-direction rotation about 130-170 s, an 8-direction rotation about 210 s, a battle background about 13 s.

## Godot notes
- Characters: `AnimatedSprite2D` with `<name>_frames.tres`; the node offset puts the feet on the origin (y-sort).
  A jump keeps its rise and fall in the frames (the canvas bottom is the ground, so the sprite leaves it without
  code). A game whose physics already lifts the body (a platformer) sets `"design": {"character": {"actions":
  {"jump": {"airborne": false}}}}` and gets jump frames that stand on the feet line like every other action.
- Character holds: a held frame carries its `duration` in the SpriteFrames (relative: it shows duration / speed
  seconds, so 2.0 is twice as long); the sheet JSON lists them as `durations` for other engines. A smeared frame is an
  ordinary frame.
- Sprite shaders (`"shaders": true` on a character): fx/shaders/mat_damage_flash.tres under the art folder (tween `shader_parameter/flash`
  1 -> 0 on a hit) and `mat_dissolve.tres` (tween `shader_parameter/progress` 0 -> 1 for a defeat, 1 -> 0 to appear;
  `edge_color`, `edge_width`, `noise_scale`, `pixel_size` and `seed` shape it). The dissolve works per whole texel and
  reads texel centres, so it stays on the pixel grid with hard edges. A material file is shared by every node that
  uses it: give each sprite its own copy (`material.duplicate()`, or Local To Scene in the inspector), or one hit
  flashes every character.
- Props: `prop_<name>.tscn` is a `StaticBody2D` with the origin at the feet and a footprint box; put props under a
  `Node2D` with `y_sort_enabled` and characters walk behind tree canopies and lamp posts by their feet.
- Ground: one TileSet for stacked `TileMapLayer`s: Base (plain tiles, random paint), one layer per overlay terrain,
  Decals, Fixtures. Overlays are 47-tile blob sets (Match Corners and Sides): paint a terrain on its own empty layer
  with the editor's defaults and exactly the painted cells fill (single cells are islands, 1-wide lines are paths).
  Stack lower terrains under upper ones (dirt under cobble, sand under water) so no gap opens between their edges.
- Maps: `assets/maps/<name>.tscn` (painted by Godot's own solver, props instanced under a y-sorted `Props` node),
  plus `assets_src/maps/<name>_preview.png` from the cells Godot chose.
- Effects: `fx_<name>.tscn` (additive material, autoplay). Damage flash: `mat_damage_flash.tres`, tween its
  `shader_parameter/flash` from 1 to 0 on hit.
- VFX: `fx/vfx/<name>/vfx_<name>.tscn`. A projectile is a `Node2D` pointing right (a `Trail` behind a `Body`):
  set `rotation` to the flight direction and move it. Puffs and bursts autoplay once and stop on an empty frame
  (free them on `animation_finished`); ground kinds have the origin on the ground line. Particle kinds are a
  `GPUParticles2D`; a one-shot bursts on spawn (a small `Start` AnimationPlayer arms it, because Godot 4.7 stops a
  one-shot that starts emitting from the scene file) and sends `finished`; `restart()` replays it.
- Fonts: load the `.fnt` as a `FontFile`; white ink is tinted by `font_color`; gradient title fonts are coloured.
  The Latin fonts are taller than the ASCII ones they extend (at 2x: dialogue_latin 26 px lines instead of 22,
  title_brass_latin 34 instead of 24) and their baseline sits lower in the line (the accent rows come first), so a
  Label that switches to one shows its text a few pixels lower.
- UI kit: `assets/ui/theme_<name>.tres` (the kit's shell loads the first `assets/ui/theme_*.tres`, sorted by name); textures in
  `assets/art/ui/uikit/<name>/`; set the project's default texture filter to Nearest. Prompt glyphs: `assets/ui/glyphs/<name>.png`,
  1x and 16 px tall (draw them at whole multiples), glyphs.json gives each width. `cursor_pointer.png` / `cursor_select.png`
  (hotspots in the manifest). `uikit_preview_<name>.tscn` shows every control; `verify` checks its Theme items in Godot and walks
  its focus chain with ui_down / ui_up (`UIKIT_FOCUS_RESULT PASS` in the log). Vertical sliders, vertical scroll bars and item lists
  use ui_up / ui_down themselves, so they sit last in a focus chain (or are reached with ui_left / ui_right).
- Animated water: TileSet atlas animation (4 frames by default); the editor previews it.
- Store: `"apply": true` sets `application/config/icon` and the boot splash (`boot_splash/image`, `bg_color`,
  `use_filter` off so the splash stays crisp) in `project.godot`; for the Windows export, point the preset's
  `application/icon` at `assets/art/brand/<name>/icon_<name>.ico`. `verify` loads the icon and splash too.
- Diorama: `diorama_<name>.tscn` is a `Node3D`: `Tiles` (a `PlaneMesh` per cell, a `BoxMesh` under raised ones),
  `Sprites` (`Sprite3D` / `AnimatedSprite3D`, billboard fixed-Y, pixel size 1 / tile_px, nearest filter, alpha
  scissor), a sun with shadows, ambient light and a `Camera3D` with optional depth of field. One unit is one tile.
- Screens: `screen_<name>.tscn` is a full-rect `Control` over the backdrop (`TextureRect`, keep aspect covered,
  nearest filter), using the first `assets/ui/theme_*.tres` when the game has one; the loading screen's
  `Progress` is a `TextureProgressBar` (set `value`), the credits `Player` autoplays the roll.
- Lighting (`lighting` lane): `assets/art/lit/<name>/` holds lit copies that point at the original PNGs, which stay
  untouched: `<frames>_lit.tres` (every frame a CanvasTexture: diffuse + normal map), `<tileset>_lit.tres` (every atlas
  a CanvasTexture; terrains and collision copied, so Godot's terrain tool paints it as before), `props/<png>_lit.tscn`
  (the prop's own scene with the CanvasTexture and a LightOccluder2D under the root; collision kept) and
  `<name>_demo.tscn`. Normal maps are OpenGL style (green up), what Godot 4 expects; Godot flips green into its
  y-down canvas itself. A normal map changes nothing until a light shines: add a `PointLight2D` with a texture, a
  `height` above 0 (the demo uses 48 px; at 0 a flat surface gets no light) and `shadow_enabled` for the occluders,
  and a `CanvasModulate` to darken the rest. An occluder shadows everything behind it, its own sprite included,
  which is why `base` keeps it to the feet.

## Palettes and style references
Dotwork ships two palettes, both built from dotwork's own renders (no third-party art):
`palettes/dotwork_default_env.hex` (136 colours, config key `env_palette`: terrain, buildings, backdrops, enemies):
112 extracted with `dotwork.py palette extract` from Dotwork's own renders of the material catalog (`catalog/materials.json`), plus 24
sky and backdrop colours added with `dotwork.py palette extend` from dotwork's own battle-background and title-scene
renders (without them, skies collapsed into flat grey and cyan bands); and `palettes/dotwork_default.hex` (168 colours,
config key `palette`: props and other objects), the environment palette plus 32 accent colours from dotwork's own
unquantized prop renders. A
`_swatch.png` sits next to each. Point `palette` / `env_palette` in `dotwork.config.json` at your own files (relative to
the game, or absolute); a missing file is a setup error. Editing a palette changes the cache key, so the next `pack`
re-renders what used it.

**A Lospec palette.** `lospec.com/palette-list` offers each palette as a `.hex` download (`<page>.hex`, one `RRGGBB`
per line), which is this format: save it in the game and point `palette` or `env_palette` at it (`clean` and `recolor`
take `--palette <file>`). Checked 2026-10-31: a tilemap cleaned onto ENDESGA 32 kept 20 colours, all on the palette.
Lospec palettes are small (8 to 64 colours, against 136 and 168 here), so expect flatter shading and fewer in-between
tones in renders; `max_colors` cannot add colours a palette lacks. Credit the palette's creator in the asset log.

**What the lock does.** After the 8 px grid sample, every opaque pixel is snapped to the nearest palette colour in
OKLab. Then `max_colors` caps the piece: if it still uses more than `max_colors` distinct colours, the most-used
ones are kept and the rest are re-snapped to them. Lanes that draw an outline add it last. `max_colors` only acts
together with a palette lock; where a lane uses no palette it has no effect.

| Lane | Palette | Colour cap | Spec keys |
|---|---|---|---|
| props, animprops, vehicles | `palette` | 40 | props: `"palette": "env"` switches an entry (a grass block, a water tile) to the environment palette |
| ground textures, overlays, decals, fixtures; the pair `tiles` lane | `env_palette` | 24 per texture at 64 px and up, 16 below; decals 12, fixtures 24; pair tiles 24 / 14 | none |
| battle_bgs / scenes / enemies | `env_palette` | 64 / 96 / 48 | `max_colors` |
| img2px | `env_palette` by default | 48 | `max_colors`; `"palette"` set to anything but `"env"` uses the object palette |
| icons, portraits | none: the sampled colours are kept | none | none |
| effects | none: each effect is reduced to 16 colours of its own, no outline | 16 | none |
| tools (edits, inpaint) | the source sprite's own colours plus `palette` (untouched pixels map back exactly) | source count + 12 | none |
| hit sparks / slashes (drawn in code) | a 4-step ramp of the entry's `color` | about 4 per frame | `color` |
| uikit (drawn in code) | the style's fill / frame colours plus a focus colour; glyphs and cursors one fixed neutral set | about 12 per theme, 12 for glyphs | `style`, `fill`, `frame`, `focus` |
| vfx (drawn in code) | the kind's ramp (bolt, orb, level-up and embers share the spells ramps), or one built around `color`, or `colors` as given; particle textures are white masks tinted by the same steps | the ramp's 2-6 colours | `color`, `colors` |
| characters | none of the files: every animation frame is locked to the colours of the direction sprite it was animated from | per character | none |

So props, enemies, terrain and backdrops read as one set because they share the two files; characters, icons,
portraits and effects match through the style reference and the prompt wording instead.

**Build your own.** `dotwork.py palette extract "assets_src/sprites/*.png" --colors 64 --out art_src/dotwork/game.hex`
picks N colours from your PNGs (weighted k-means in OKLab, snapped to colours that really occur) and writes a
swatch; `dotwork.py palette extend --base art_src/dotwork/game.hex "art_src/dotwork/materials/*.png" --add 32 --gap 0.04
--out art_src/dotwork/game_env.hex` keeps a base palette and adds the colours the sources need that it lacks.
`dotwork.py materials` renders the material catalog for review, and `dotwork.py materials --extend-palette --add 32` grows
the environment palette from those renders into `art_src/dotwork/palettes/env_<N>.hex`. A palette built only from
existing art cannot show new hues: add the ones new characters need before locking them.

**Style references.** `style_refs` is empty by default: Dotwork renders from the prompt alone. List 3-4 of your own
finished sprites (paths relative to the game) and Dotwork uploads them once per run as one collage the image model
copies for style, outline and shading; changing the list re-renders what used it. A spec can switch the reference off
for one pack with `"design": {"character": {"style_ref": ""}}`.

## Hand polish (Aseprite or Pixelorama)
Both editors get the same round trip. `dotwork.py aseprite` or `dotwork.py pixelorama` writes one editable file per
character (one tag per animation, named like the animation, such as `walk_s`), per effect and per single image (props,
icons, portraits, window skins) under `<src_dir>/aseprite/` or `<src_dir>/pixelorama/`. Each frame shows for as long as
it does in the game: its hold divided by the clip's frame rate. Polish there and save, then `--reexport` writes the
frames back to the shipped PNGs, sheets, sheet data and SpriteFrames, keeps each clip's holds (a frame you retime
becomes a hold), removes frames you deleted and runs `verify`. Neither half needs Godot with `--engine none`: the
build reads the shipped PNGs and the re-export writes PNGs, sheets, sheet data and manifest rows, then reports
`[ OK ] re-exported (N files changed; no Godot verify with --engine none)`; only the SpriteFrames and `verify` are
Godot's. A frame that still looks the same keeps its shipped
file byte for byte (editors drop the colour stored under fully clear pixels; that alone is not a change), and an
untouched hold keeps its exact value. Manifest rows change only for files that changed: such a file keeps its row
(models, workflow, canvas, anchor, position) and gains its new hash and a polish note, so an untouched round trip
rewrites no manifest and a frame drawn in code never gains a model. A frame or clip you add gets a new row with its
sibling's provenance only (models, workflow, routes, blend), never the sibling's holds, checks or prompt. Tag names
use letters, digits and `_` only (they become file names), and a tag holds at most 100 frames (the shipped names
carry two digits). Effects in the effects lane's layout (`fx/<name>/spr_fx_<name>_NN.png`, which hit effects share)
are included. Spells, VFX, status marks, animated props, balloons and vehicles keep their lanes' own files and are
drawn from their specs, so neither editor gets them. A character whose clips have different frame sizes (two packs
wrote it) gets one canvas, the widest and the tallest: each clip sits centred on its bottom edge, so every clip's feet
stand on one line, and comes back at its own size. Keep a clip's art inside its box; art outside it stops the
re-export with the frame's name. An effect's frames must all be one size.

| | Aseprite | Pixelorama |
|---|---|---|
| Needs | `ASEPRITE_BIN`: Aseprite runs headless for both directions | nothing: Dotwork reads and writes `.pxo` in Python |
| Versions | Lua scripting (`--script`); run with Aseprite 1.3.18 on Windows | writes `pxo_version` 7 (Pixelorama 1.2.0 to 1.2.3 write it; 1.2.3 and 1.2.4 opened, exported and saved Dotwork's files); reads 7 and 8 (Pixelorama 1.2.4, where a cel keeps its own size and offset; a file 1.2.4 saved, with a pixel edited in it, re-exported exactly). Dotwork keeps writing 7: 1.2.3 reads every cel as a whole canvas, so a cropped version 8 file would load wrong there, and 1.2.4 opens 7 as it is |
| The file | indexed on the asset's own colours when that loses nothing (at most 255 opaque colours, no partly clear pixels); RGB otherwise, such as a portrait of 1,800 colours | RGBA in one layer `art`, the asset's own colours as the project palette; the project's frame rate is the one most of the character's frames play at, and other clips carry per-frame durations |
| Layers you add | flattened by Aseprite on export | composited as Pixelorama 1.2.4 does (below): cel, layer and animated opacity (every keyframe curve), z-index, pass-through groups, every blend mode, clipping masks and groups that blend their own layers (with their opacity); a tilemap layer is drawn from its tiles (see Tilemaps below); a visible layer with layer effects, or a visible 3D layer, stops the re-export with its name (apply the effects, merge it down or hide it); hidden layers are ignored |
| A file that exists | kept when it differs from the game's frames (Aseprite exports it to compare the tags, frames and frame times; one that still matches is left as it is); `--overwrite` replaces it and keeps the old file as `<name>.aseprite.bak` | kept when it differs from the game's frames (Dotwork reads it to compare the tags, frames and frame times; one that still matches, such as a file Pixelorama only opened and saved, is left as it is); `--overwrite` replaces it and keeps the old file as `<name>.pxo.bak` |
| Size | read by Aseprite | a project whose frames would take over 512 MB, whose visible cels would unpack to over 1 GB, or with over 256 layers is refused before any image is read |

Pixelorama 1.2.4 has two layer composites, and they do not agree. Without a window (its command-line export) it
blends Normal layers on the CPU and leaves blend modes, clipping masks and a group's own blending out; with a window
(its canvas and File > Export) it blends on the GPU with a shader that applies them all, and a partly clear pixel over
another partly clear one comes out differently there (the shader weighs the layer by how opaque the pixels under it
are). Dotwork picks per project: one of Normal layers composites as the command-line export does, equal byte for
byte; one that uses a blend mode, a clipping mask or a group that blends composites as the shader does, in 32-bit
floats like the GPU. The GPU rounds values near a half step its own way, so there 85 to 94 % of pixels come out equal
to Pixelorama's and nearly all the rest one or two steps off (measured on one machine: a few pixels where a group
holds an all but clear pixel over a partly clear one land further off). A frame of one layer at full opacity, the
shape Dotwork writes, is copied as it is, so an untouched trip changes no file (Pixelorama's export can make a partly
clear pixel of it one step darker). Layer effects are shaders too, run only with a window: apply them first. #66 has
the measurements.

**Tilemaps.** Pixelorama's tilemap layers (square tiles) go both ways. A `.pxo` of your own with tilemap layers, put
in `<src_dir>/pixelorama/tilemaps/<name>.pxo`, re-exports to `<art_dir>/tilemaps/<name>/`: `tiles_<name>.png` (the
tileset at its own tile size; Pixelorama's tile N sits at slot N - 1, 16 to a row, so a tile you add moves no other),
`<name>_tileset.tres` (Dotwork's TileSet writer, as the ground lane uses it: each tile's terrain and peering bits and
its probability; its user data names its `surface`, the custom data the terrain lanes write, and the word `solid`
there gives it a full-tile collision box), `<name>.tscn` (a Node2D with one TileMapLayer per visible tilemap layer,
first layer drawn first, every cell flipped and transposed as in Pixelorama; a project of several frames gets
`<name>_NN.tscn` per frame) and `<name>_map.json` for every engine (cells as `[x, y, tile, flags]`, flags 1 flip_h,
2 flip_v, 4 transpose). With `--engine none`, the PNG and the JSON. `dotwork.py pixelorama` also opens the game's own
maps in Pixelorama: one tilemap project per map scene mapbuild painted (one layer per TileMapLayer), and one per
square TileSet no map uses (its tiles where they sit in its atlas). Each tile names its atlas slot in its user data:
leave that as it is. On `--reexport`, an edited tile goes back into its slot in the atlas PNG and an edited cell into
the map scene, where only the `tile_map_data` lines change; the TileSet itself is never rewritten. So draw in
Pixelorama's Manual tile mode: Auto and Stack add a new tile when you draw on one that several cells use, a new tile
has no atlas slot, and the re-export stops and says so. Only an animated tile's first frame is in the project. Two
projects that change one tile differently stop the re-export; a project with no edits is rebuilt when the game's
map changes, one with edits is kept (`--overwrite` keeps a `.bak`). Isometric and hexagonal tilemaps, a tilemap layer
with a blend mode or a clipping mask, and one moved off the tile grid are refused. Checked with Pixelorama 1.2.4 (its
own drawing of every flip and transpose equals Dotwork's; a cell and a tile edited there change only the atlas, the
map and the manifest) and Godot 4.7.2 (a Movie Maker capture of both kinds of map equals Dotwork's drawing on every
opaque pixel). Pixelorama's command-line export draws tilemap layers empty (it exports before they are redrawn from
their tiles); its window and the files it saves draw them.

Pixelorama stores the folder you last exported to, a full path on your machine, in every `.pxo` it saves: in a public
repository, that path is public too. `pixelorama` and `pixelorama --reexport` name each `.pxo` that holds one (a
`[warn]` line), and `tools/publish_check.py` warns about it before you publish; `--clear-export-path` blanks the
folder (nothing else in the file changes, and the round trip still gives the same frames). Dotwork never rewrites a
`.pxo` for this without that flag. Pixelorama 1.2.4 fills a blank folder with the `.pxo`'s own folder when it opens
the file, and gives a file Dotwork wrote the folder of the last file you opened (your Desktop on a fresh install), so
the path comes back on every save: clear it again before you commit. Aseprite 1.3.18 on Windows built the sources and re-exported them untouched
with every file unchanged, a character with clips of two sizes included; an edit made in Aseprite's window is not
tested yet.

**The Dotwork panel in Pixelorama.** A Pixelorama extension (source in `pixelorama_extension/`) adds a tab named
Dotwork. For the `.pxo` open in Pixelorama it shows which game asset it is (character, effect, image or tilemap), its
game files, the QA notes Dotwork made for it (a turned-around clip, smear and drift notes), why a re-export would stop
before you try (a layer effect, a character with no tags, a tile with no atlas slot) and whether the file holds a
folder of your machine. **Re-export to game** saves the `.pxo` and runs `dotwork.py pixelorama --reexport
--clear-export-path` for the game (the same command you would type: every Dotwork `.pxo`, untouched ones change no
file, and every export folder blanked), then shows Dotwork's result lines. **Next asset** opens the game's next
Dotwork `.pxo`; **Show in game folder** opens the asset's shipped files in your file manager. A first time, from the
game folder:

1. `python tools/art/dotwork/dotwork.py pixelorama` (once, so there are `.pxo` files to open).
2. `python tools/art/dotwork/dotwork.py pixelorama --install-extension`, with the Python you run Dotwork with and
   `GODOT_BIN` set (the panel's re-export runs `verify` in Godot; Pixelorama started from a menu does not see your
   shell's variables, so the install records it). This copies `DotworkPanel.zip` into Pixelorama's extensions folder
   (`%APPDATA%\pixelorama\extensions` on Windows, `~/.local/share/pixelorama/extensions` on Linux,
   `~/Library/Application Support/pixelorama/extensions` on macOS; `--pixelorama-user DIR` for another, such as a
   portable Pixelorama **(verify)**) and writes its config, dotwork_panel.json, beside it: which Python, `dotwork.py` and game
   folder to use, full paths on your machine that stay in Pixelorama's folder, never in the game. It changes none of
   Pixelorama's settings. Run it again from each game you polish (one row per game) and after you move a game or
   change Python.
3. Restart Pixelorama, then Edit > Preferences > Extensions: select **Dotwork panel**, press Enable and confirm (once;
   Pixelorama remembers it). The tab joins the panel beside the tools; Window > Panels shows or hides it, and Window >
   Layouts moves it like any other panel.
4. Open a `.pxo` from `<src_dir>/pixelorama/`, polish, press **Re-export to game**, read the result, then **Next
   asset**.

Dotwork runs in the background, so Pixelorama stays usable; the buttons wait until it finishes (a re-export with
`verify` takes a few seconds to a minute). A `.pxo` from somewhere else, a Python or game folder that moved, or a
missing config gets a message in the panel that says what to run. Pixelorama checks the extension's API version: the
panel declares API 10 (Pixelorama 1.2.4) and a later Pixelorama that changes the API says so instead of loading it.
To remove it, Edit > Preferences > Extensions > Uninstall. Tested with Pixelorama 1.2.4 on Windows, headless: the live
exam installs the panel into a user folder of its own, opens a `.pxo`, sets a pixel and drives the panel's own
refresh and re-export, and the game changes exactly as the command-line path changes it (real `verify` in Godot
4.7.2 when `GODOT_BIN` is set); the panel's text helpers run under plain Godot. How the tab looks and the buttons'
clicks in Pixelorama's window are not tested by a program: give it a look.

## Store art (Steam sizes)
What the `store` lane writes to `assets_src/store/<name>/steam/`, checked against the Steamworks documentation on
2026-11-01 (pages: store/assets/standard, store/assets/libraryassets, store/assets/rules, store/assets,
store/assets/community, features/achievements/ach_guide on partner.steamgames.com). Steam says older dimensions are no
longer accepted, so check the pages again before a release; the sizes live in `SIZES` in `lane_store.py`.

| File | Size | Steam's rule | What Dotwork puts there |
|---|---|---|---|
| `header_capsule.png` | 920 x 430 | no text beyond the game's name; logo legible | wide key art, logo |
| `small_capsule.png` | 462 x 174 | the logo should nearly fill it | wide key art, logo at up to 90 % of the width |
| `main_capsule.png` | 1232 x 706 | no text beyond the name | wide key art, logo |
| `vertical_capsule.png` | 748 x 896 | no text beyond the name | tall key art, logo |
| `page_background.png` | 1438 x 810 | optional, ambient | wide key art, no logo |
| `library_capsule.png` | 600 x 900 | logo, no other text | tall key art, logo |
| `library_header.png` | 920 x 430 | no text beyond the name | wide key art, logo |
| `library_hero.png` | 3840 x 1240 | no text at all; keep what matters in the centred 860 x 380 | wide key art, no logo |
| `library_logo.png` | 1280 x 720 | transparent PNG, the logotype only | the logo, transparent |
| `shortcut_icon.png` / `.ico` | 256 x 256 | ICO or PNG (256 or 512) | the game icon x4; the .ico holds 16 to 256 |
| `app_icon.jpg` | 184 x 184 | JPG | the game icon x3, cropped 4 px a side, on `bg` |
| `achievements/<name>.png`, `<name>_locked.png` | 256 x 256 | PNG recommended; achieved in colour, unachieved greyscale | your icon on a plate, and its greyed twin |

Base capsules may carry only the artwork, the game's name and an official subtitle: no review scores, awards,
discount or "buy now" text, or other products. All capsule art must be PG-13. Screenshots (1920 x 1080 or larger,
16:9, at least five) must show gameplay, so Dotwork does not make them. Everything is pixel art at whole-number
scales: a size takes the smallest whole multiple of the key art that covers it and crops the rest (the `focus` point
stays in), so no pixel is ever resampled. The widest sizes keep under half of a 16:9 key art's height: without `focus`,
the lane's own renders keep the top of where the prompt puts the hero (the feet give way first), and your own
`source` art is cropped round its centre, so set `"focus": [x, y]` (0 to 1) when its subject is off centre and check
the review sheet. The game itself gets `assets/art/brand/<name>/`: `icon_<name>.png` (256),
`icon_<name>.ico`, `logo_<name>.png` (4x, for a title screen) and `boot_splash_<name>.png` (640 x 360).

## Image to 3D (tested, not part of Dotwork)
**Since 0.11 the kit has a 3D lane: Bozzetto (`tools/bozzetto/`, README there), TRELLIS.2 through ComfyUI's
built-in nodes on a 16 GB card.** The notes below are the earlier TRELLIS (v1) trial, kept for its pixel-art findings.

Turning a sprite into a 3D model was tried on 2026-11-01 (RTX 5060 Ti 16 GB, Windows 11) and is not built in. The
2.5D path Dotwork does ship is the `diorama` lane (billboards over 3D tiles).
- **TRELLIS** (github.com/microsoft/TRELLIS, MIT code and weights, `microsoft/TRELLIS-image-large` in safetensors):
  the only candidate that passed the licence check and a code audit. Its README asks for 16 GB of VRAM and is tested on
  Linux only. On Windows it ran only after changes: DINOv2 loaded from a local safetensors folder instead of
  `torch.hub` (which runs code fetched at load time and reads `.pth` weights), no background remover (it downloads a
  model on first use; give an RGBA picture instead), the mesh path only (its Gaussian and texture-bake renderers carry
  non-commercial or research licences), and its attention routed through PyTorch's own because the xformers build had
  no kernels for this GPU. Two 64 px pixel-art props each took 20-70 s and up to 10 GB of VRAM; after decimation, UV
  unwrap and a colour bake in Blender, both GLBs pass `tools/blender/validate_asset.py --class prop`, but the shapes
  were wrong (a barrel came back as a box, a crate as crossed planes).
  **The cause, found on 2026-11-04 (same card and setup): that run blew the sprites up 8x with nearest neighbour
  before TRELLIS saw them, and TRELLIS gets hard pixel steps wrong. The DINOv2 swap is not at fault.** Measured
  on the coarse 64x64x64 shape TRELLIS builds first, seeds 1 to 3:
  - The plain 64 px RGBA sprite (TRELLIS's own crop and Lanczos resize then smooth the pixels): the barrel came
    back a barrel and the crate a framed box, 3 of 3 seeds each. The full meshes (seed 1, 21-39 s, 9.9-11.0 GB
    peak) keep those shapes.
  - Blown up with nearest neighbour first, as before: the crate came back crossed planes or a box on a post in
    3 of 3 seeds, the barrel a box (seed 1, the earlier run's seed) or a plain cylinder. Nearest neighbour on a
    neutral grey background: crate wrong 3 of 3, barrel right 3 of 3. Blurring or bicubic upscaling instead gave
    an empty or flat result in 13 of 18 runs.
  - Controls: plain Blender renders of a barrel and a crate, the same renders cut down to 64 px pixel art, and
    TRELLIS's own crate and castle examples all came back the right shape (the Blender barrel with a thin ground
    plate under it).
  - DINOv2: the local copy loads all 440 tensors of its safetensors file unchanged, and its tokens match an
    independent float64 re-implementation of the original ViT-L/14 forward pass on the same weights (cosine
    1.000000 on every token). TRELLIS's own attention path and the routed one give identical shapes. Whether the
    safetensors weights equal Meta's original `.pth` was not checked (no `.pth` on the test machine) **(verify)**.

  So give TRELLIS the sprite at its own size with transparency, never pre-scaled, and try more than one seed:
  shapes change between seeds. TRELLIS's own crate example still runs out of memory in the mesh decoder on 16 GB
  (about 53,000 occupied cells, four times a prop's; 12.4 GB allocated when it failed under an 85 % cap), and
  the mesh path gives no usable colour without a bake. It stays out of Dotwork: it needs the changes above and was
  tried on two sprites only.
- **TRELLIS.2** (MIT) asks for at least 24 GB of VRAM upstream; ComfyUI 0.43.0's int8 build of it runs on a 16 GB card
  and is what Bozzetto uses (E150).
- **Hunyuan3D 2.0**: its community licence excludes the European Union, the United Kingdom and South Korea and needs a
  separate licence above 1 million monthly users, so the kit does not recommend it.

## Licences
- Dotwork: the kit's licence (MIT). `glyphs/*.txt` (fonts authored as text) and the palettes are part of Dotwork.
- Models: every file in `models.lock.json` carries its licence; the ones Dotwork uses are Apache-2.0. Check each model
  card yourself before shipping. `dotwork.py log` writes them into the asset's evidence file.
- SpriteKiln (GPL-3.0) and ComfyUI-GGUF (Apache-2.0) are installed by you and called over HTTP; Dotwork contains none
  of their code or workflow files.
- What you generate: no third-party art is involved unless you supply it (`source`, `style_refs`, `img2px`).
- Fonts you bring (`bdf`): the font's own licence applies. `license` is required and is copied next to the `.fnt`
  as `font_<name>_LICENSE.txt`; the SIL Open Font License lets you ship a cut-down copy inside a game when the
  licence text goes with it and the font declares no Reserved Font Name (Ark Pixel Font declares none). Credit it
  in `docs/ASSET_LOG.md`.

## Tests
`python tools/art/dotwork/tests/test_lighting.py` - offline, seconds: normal maps (unit length, facing the camera,
rims pointing outward, seamless tiles), occluder outlines and the lighting lane end to end on a throwaway game.
`python tools/art/dotwork/tests/test_dotwork.py` - offline, under a minute: a stand-in ComfyUI on 127.0.0.1 with canned
outputs; covers settings, spec parsing and exit codes (entry-level errors and warnings, options before the command),
the manifest and its model provenance, naming, cache keys and seeds, metadata stripping, spec path containment, grid
sampling, connected components, blob atlas layout and seams, the .tres/.tscn writers (multi-source animated
TileSets), mapbuild's text-to-cells, glyphs, connectors, tool timeouts (the whole process tree is stopped) and
verify's error markers. `python -I -B tools/art/dotwork/tests/test_vfx.py` covers the vfx lane: frame counts and sizes,
one-shots that end empty, loops that wrap, ramp-only colours, trails that fade, the particle scenes and spec errors.
`python tools/art/dotwork/tests/test_animpolish.py` - offline, a few seconds: the animation polish keys. Defaults match
digests of the skeleton and of a character export taken before the polish; the smear lands on the frame of peak motion
in that frame's colours; holds reach the SpriteFrames; the wind-up moves against the strike; the shader files are
well-formed and the flash is the hitfx lane's byte for byte.
`tests/test_qapack.py` (seconds): `qa pack` on a synthetic game, clean and with planted
outliers (a 2x upscale, an off-palette prop, a mirrored prop, a red / green gauge pair); lit TileSet normal maps and
store art in the manifests add no findings.
`python tools/art/dotwork/tests/test_fonts.py` - offline, seconds: the Latin glyph fonts (height, baseline, coverage,
accents drawn over unchanged base letters), the coverage check (JSON, CSV, PO, text; command line and pack) and the
old fonts' output against golden hashes.
`python tools/art/dotwork/tests/test_pixelorama.py` - offline, seconds: both hand-polish round trips. `.pxo` files
(tags, frame durations from holds, palette, the same bytes on every build, polish never overwritten), an untouched
re-export that changes no file, an edit and a new hold reaching the game, layers composited against what Pixelorama
1.2.4 itself made from small projects (`tests/fixtures/pixelorama_composites.json`: headless exactly, the blend modes,
clipping masks and groups within two steps of its windowed composite), every refused layer feature stopping before a
file is written, `pxo_version` 8 cels and the fields Pixelorama 1.2.3 and 1.2.4 save, and tilemaps (every flip and transpose drawn as
Pixelorama draws it, your own tilemaps into an atlas, a TileSet, scenes and a JSON map, a game's map and TileSets
into tilemap projects and back after Pixelorama renumbered their tiles), the Dotwork panel (its package, the install
writing only the zip and its config, `--info` for every kind of source; with `GODOT_BIN`, its text helpers under
Godot);
Aseprite's frame times in the build list and through a re-export rounded to milliseconds (its script runs stubbed).
Two live exams run only when their editor is set: `ASEPRITE_BIN` runs the export script in Aseprite, and
`PIXELORAMA_BIN` (about 13 s) has Pixelorama open, save and export Dotwork's `.pxo` files headless, through a small
extension installed in a user folder of the exam's own (your Pixelorama settings are not touched), then re-exports
them: no file changes, a pixel set in Pixelorama changes only its frame, and partly clear layers with cel, layer and
animated opacity in groups come out of Pixelorama's export equal to Dotwork's, byte for byte; tilemaps saved there
round trip unchanged, and a cell and a tile edited there change only the atlas and the map; the Dotwork panel,
installed there by `--install-extension`, names the asset and its QA notes and its re-export changes the game as the
command line does. With
`PIXELORAMA_WINDOW=1` as well, one case opens Pixelorama's window for a few seconds and compares its GPU export of
blend modes, a clipping mask and a blending group with Dotwork's (within two steps; #66).

## Troubleshooting
| Symptom | Fix |
|---|---|
| `[error] no ComfyUI answering` | start ComfyUI, or set `COMFYUI_ROOT` so Dotwork can |
| `node types missing` | install / restart the node packs (Setup 2) |
| `SpriteKiln not configured` | set `SPRITEKILN_ROOT` to the repo clone (the folder with `workflows/api/`) |
| `only N GB RAM free` | close heavy apps; Wan clips need about 18 GB free; Dotwork resumes where it stopped |
| out of memory in ComfyUI | close other GPU apps; start ComfyUI with `--lowvram` |
| `<entry>/<clip>: cancelled in ComfyUI` | the job was cancelled in ComfyUI's queue (or ComfyUI restarted): run the same command again, it resumes |
| verify fails | read verify_report.json in `art_src/dotwork/` (written by the failed run): the import errors and loader lines name the file |
| `Godot crashed during import ... retrying once` in the log | a rare Godot 4.7 crash on a first import of new fonts; Dotwork retries once by itself. If the retry fails too, run `python tools/dev.py import` and then `dotwork.py verify` |
| `Cannot get keys from nonexistent section "preset.N.options"` | empty `[preset.N.options]` sections in `export_presets.cfg`; harmless (export still works) and ignored by verify |
| a sprite looks wrong (extra limbs, a face in an effect, a cropped prop) | change its `seed` (or the wording) and run the pack again; only that entry re-renders |
| `spec path ... points outside the game folder` / `absolute paths` / `network paths are refused` | move the file into the game (for example `assets_src/`) and use a relative path, or pass it on the command line |
| `[warn] ... key 'x' is not read by Dotwork` | a typo or a key from another lane: check the lane's header (`lane_<name>.py`) for the right spelling |
