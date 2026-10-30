# Dotwork: local pixel-art assets for your game

Dotwork makes a game's 2D pixel art on your own GPU, with local models through ComfyUI. You describe what you need in
a small JSON spec; Dotwork writes Godot-ready assets straight into the game (`assets/`), editable sources and review
sheets (`assets_src/`), and a manifest for `docs/ASSET_LOG.md`. Claude (or you) orchestrates; the models only draw.

What it makes (each is a **lane**): animated characters (4 directions, idle / walk / attack, battle and emote poses),
props with collision scenes, layered terrain with buildings, interiors and cliffs, maps painted from text, fences /
pipes / rails, animated water, effects and spells, enemies and bosses, battle backgrounds, title screens, icons,
portraits, pixel fonts, window skins, emote balloons, 8-direction vehicles, treasure chests / doors / switches /
save points, sprite edits and normal maps, and image-to-pixel-art.

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
7. [Licences](#licences)
8. [Tests](#tests) and [troubleshooting](#troubleshooting)

## First run (no GPU, about 10 s)
The model-free lanes (pixel fonts, window skins, emote balloons, hit effects) need no ComfyUI and no models, so you
can see Dotwork work before installing anything. From your Godot game's root folder:
```
GODOT_BIN=/path/to/godot python tools/art/dotwork/dotwork.py pack --spec tools/art/dotwork/examples/ui.json   # 60 files, verified in Godot
python tools/art/dotwork/dotwork.py verify            # every Dotwork asset of this game loads in Godot
python tools/art/dotwork/dotwork.py log --pack ui     # a docs/ASSET_LOG.md row + evidence file (run again: it updates)
```
On Windows set the variable first (PowerShell `$env:GODOT_BIN = "C:\path\godot.exe"`). A game without Godot: add
`--engine none` to `pack` (43 files: PNGs, `.fnt` fonts, the manifest; there is nothing to `verify`).

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
Save each file under the name the check prints: seven of them differ from the upstream file name (for example the
Wan GGUFs and the LoRAs), and ComfyUI finds them by that name.
`--hash` also compares SHA-256 against `models.lock.json` (needs `COMFYUI_ROOT`; reads tens of GB).

| Tier | Size | What it enables | Minimum (NVIDIA) | Ran here with |
|---|---|---|---|---|
| `sprites` | 15.3 GB | every klein lane: sprites, props, icons, enemies, textures, tiles, buildings, battle backgrounds, edits, poses | 8 GB VRAM, 16 GB RAM | 16 GB VRAM |
| `rotate` | 29.1 GB | 4- and 8-direction rotation (characters, vehicles) | 12 GB VRAM, 24 GB RAM | 16 GB VRAM, 64 GB RAM |
| `animate` | 33.4 GB | Wan 2.2 clips: walks, attacks, spell effects | 16 GB VRAM, 32 GB RAM (18 GB free per clip) | 16 GB VRAM, 64 GB RAM |
| all three | 77.8 GB | everything | as `animate` | |

The minimums are the lock's (`models.lock.json`, `tiers`); only the right-hand column was measured.

The klein VAE must be `flux2-vae-klein.safetensors` (Apache-2.0, from `Comfy-Org/flux2-klein`). A file called
`flux2-vae.safetensors` from the FLUX.2 [dev] repo is a different, non-commercial file: Dotwork swaps it out of every
workflow it loads.

### 4. Godot and Dotwork's config
- `GODOT_BIN`: your Godot 4 binary (maps are painted and every asset is verified inside the game).
- `ASEPRITE_BIN` (optional): the hand-polish round trip.
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
| `verify` | load every Dotwork asset of this game in Godot (and run its smoke test) |
| `aseprite [--reexport]` | editable `.aseprite` sources; push hand-polished files back |
| `preview battle\|title\|attack ...` | mock screens composed from the game's art (review only) |
| `log --pack NAME [--dry-run]` | `docs/ASSET_LOG.md` row + evidence file for a pack |
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
                 "poses": "battle", "clip_fix": {"walk_n": {"seed": 4247}}}],
 "props": [{"name": "gas_lamp", "prompt": "a cast iron gas street lamp", "size": 56, "footprint": "trunk"}],
 "ground": {"name": "town", "base": [{"material": "grass_lush", "variants": 4}],
            "overlays": [{"material": "dirt", "relief": "flat"}, {"material": "cobble", "relief": "raised"},
                         {"material": "water_deep", "relief": "sunken", "solid": true, "animate": {"frames": 4}},
                         {"material": "roof_clay", "style": "roof", "solid": true}, {"name": "fence", "style": "fence_wood"}],
            "fixtures": [{"name": "door", "cells": [1, 2], "fit": "height", "prompt": "a wooden door"}],
            "map": {"name": "square", "rows": ["ggdd", "gccd"], "legend": {"g": [], "d": ["dirt"], "c": ["dirt", "cobble"]},
                    "objects": [{"fixture": "door", "at": [1, 0]}], "props": [{"prop": "gas_lamp", "at": [0, 1]}]}},
 "effects": [{"name": "fire", "subject": "a burst of flames", "motion": "the flames burst up and die down", "keep": 6}],
 "enemies": [{"name": "hound", "prompt": "a brass guard hound", "size": 80}],
 "battle_bgs": [{"name": "mine", "prompt": "an underground mine with lanterns"}],
 "scenes": [{"name": "title", "prompt": "a brass city at dusk under airships"}],
 "icons": [{"name": "potion", "prompt": "a red potion bottle"}], "portraits": [{"name": "guard", "prompt": "..."}],
 "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt", "effect": "shadow"}],
 "windows": [{"name": "classic", "style": "classic"}], "balloons": [{"name": "exclaim", "symbol": "!", "color": "d83a3a"}],
 "hitfx": [{"name": "spark", "kind": "spark"}, {"name": "flash", "kind": "flash"}],
 "animprops": [{"name": "chest", "kind": "chest", "prompt": "a wooden treasure chest"}],
 "vehicles": [{"name": "airship", "prompt": "a steampunk airship", "size": 72}],
 "tools": [{"name": "guard_edit", "source": "assets/art/characters/guard/frames/spr_guard_idle_s_00.png",
            "edits": ["give him a red scarf"], "normal": true}],
 "img2px": [{"name": "tower", "source": "assets_src/concept/tower.png", "width": 96}],
 "design": {"character": {"fig_height": 66}, "tile_px": 32}
}
```
Each lane module's header documents its keys in full (`lane_<name>.py`). A key no lane reads (a typo such as
`"styl"`) is reported as a `[warn]` line; an entry without a `"name"`, or without a key its lane needs, stops the run
with an `[error]` naming it.

Paths in a spec (`source`, `glyphs`) are relative to the game folder and must stay inside it: Dotwork refuses `..`
escapes, absolute paths and network paths in a spec, because specs get shared. An absolute path you type yourself on
the command line (`character --source`) is fine. `glyphs` files are looked up in Dotwork's own `glyphs/` folder first,
then in the game. Every other name a spec gives (entry names, character actions and pose names, font `export` file
names, map props) becomes a snake_case file name, so none of them can point outside the game either; character
`directions` accept only `s`, `e`, `n` and `w`.

## Lanes and their limits
Honest list: these are the failure modes seen in testing and what Dotwork does about them.

| Lane | Limit | What Dotwork does / you do |
|---|---|---|
| characters (Wan clips) | Attacks sometimes turn the character toward the camera; back views sometimes grow a face | `keep=N` ping-pongs the good frames; back idles are a procedural 1 px bob; `audition` renders takes side by side; the turn warning misses some turns, so judge the sheet |
| characters (asymmetric) | A mirrored west view swaps which arm holds the signature item | `"asymmetric": true` generates west instead of mirroring |
| battle / emote poses (klein edits) | Vague wording returns the idle pose; some poses drop a signature prop | Wordings that name body positions (`BATTLE_POSES`, `FIELD_POSES`), `pose_text` per character, a per-pose seed fix |
| effects (Wan) | Motion can turn particles into a face or a little figure | Effect-only prompt wording, `keep`, a new seed; review every effect |
| sprites / props / icons | The refine pass can grow a figure past its canvas | Re-rendered smaller automatically (never rescaled); an icon prompt that fills the frame (a spiral) can still fail: reword it |
| sprites | White background trapped inside a figure | Removed automatically; skipped for white subjects (`keep_white` / `holes` override) |
| without `style_refs` | New art matches itself less closely (no reference to copy) | Bring 3-4 of your own finished sprites as `style_refs` |
| 8-direction vehicles | The rotation model's output order was assumed from the 4-direction run (east / west swapped) | Check `assets_src/art/vehicles/<name>_review.png`; `rot_order` fixes it |
| fonts | Models cannot draw consistent letters | Glyphs are text bitmaps (`glyphs/*.txt`), built into BMFont `.fnt`; edit a letter by editing its rows |
| battle backgrounds / scenes | 320x128 / 320x180 art shown at 2x (chunkier than 1x sprites) | Same exact-2x scale everywhere it is used |
| `--engine none` | Maps, TileSets, scenes, SpriteFrames and the damage-flash shader are Godot resources | PNGs, sprite sheets + their JSON, BMFont `.fnt` fonts, 9-slice margins (in the manifest) and the manifest still ship; maps and the flash are skipped with a log line |

Timing on the tested GPU: a sprite about 18 s, a texture tile with variants about 25 s, a Wan clip about 110 s, a
4-direction rotation about 130-170 s, an 8-direction rotation about 210 s, a battle background about 13 s.

## Godot notes
- Characters: `AnimatedSprite2D` with `<name>_frames.tres`; the node offset puts the feet on the origin (y-sort).
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
- Fonts: load the `.fnt` as a `FontFile`; white ink is tinted by `font_color`; gradient title fonts are coloured.
- Animated water: TileSet atlas animation (4 frames by default); the editor previews it.

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

## Licences
- Dotwork: the kit's licence (MIT). `glyphs/*.txt` (fonts authored as text) and the palettes are part of Dotwork.
- Models: every file in `models.lock.json` carries its licence; the ones Dotwork uses are Apache-2.0. Check each model
  card yourself before shipping. `dotwork.py log` writes them into the asset's evidence file.
- SpriteKiln (GPL-3.0) and ComfyUI-GGUF (Apache-2.0) are installed by you and called over HTTP; Dotwork contains none
  of their code or workflow files.
- What you generate: no third-party art is involved unless you supply it (`source`, `style_refs`, `img2px`).

## Tests
`python tools/art/dotwork/tests/test_dotwork.py` - offline, under a minute: a stand-in ComfyUI on 127.0.0.1 with canned
outputs; covers settings, spec parsing and exit codes (entry-level errors and warnings, options before the command),
the manifest and its model provenance, naming, cache keys and seeds, metadata stripping, spec path containment, grid
sampling, connected components, blob atlas layout and seams, the .tres/.tscn writers (multi-source animated
TileSets), mapbuild's text-to-cells, glyphs, connectors, tool timeouts (the whole process tree is stopped) and
verify's error markers.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `[error] no ComfyUI answering` | start ComfyUI, or set `COMFYUI_ROOT` so Dotwork can |
| `node types missing` | install / restart the node packs (Setup 2) |
| `SpriteKiln not configured` | set `SPRITEKILN_ROOT` to the repo clone (the folder with `workflows/api/`) |
| `only N GB RAM free` | close heavy apps; Wan clips need about 18 GB free; Dotwork resumes where it stopped |
| out of memory in ComfyUI | close other GPU apps; start ComfyUI with `--lowvram` |
| verify fails | read verify_report.json in `art_src/dotwork/` (written by the failed run): the import errors and loader lines name the file |
| `Godot crashed during import ... retrying once` in the log | a rare Godot 4.7 crash on a first import of new fonts; Dotwork retries once by itself. If the retry fails too, run `python tools/dev.py import` and then `dotwork.py verify` |
| `Cannot get keys from nonexistent section "preset.N.options"` | empty `[preset.N.options]` sections in `export_presets.cfg`; harmless (export still works) and ignored by verify |
| a sprite looks wrong (extra limbs, a face in an effect, a cropped prop) | change its `seed` (or the wording) and run the pack again; only that entry re-renders |
| `spec path ... points outside the game folder` / `absolute paths` / `network paths are refused` | move the file into the game (for example `assets_src/`) and use a relative path, or pass it on the command line |
| `[warn] ... key 'x' is not read by Dotwork` | a typo or a key from another lane: check the lane's header (`lane_<name>.py`) for the right spelling |
