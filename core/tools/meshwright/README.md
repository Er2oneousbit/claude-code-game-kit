# Meshwright: local 3D models for your game

Meshwright turns a reference picture, or a sentence, into a game-ready `.glb` on your own GPU. TRELLIS.2 (Microsoft,
MIT) makes the mesh and bakes its textures inside a local ComfyUI; Blender then cleans it, scales it to a height in
metres, puts the pivot at the bottom centre, writes LODs and checks it against the SOP-11 budget for its class.
Nothing reaches the game's models folder unless that check passes, and every model gets its `docs/ASSET_LOG.md` row.
It is the third asset lane next to Wavesmith (audio) and Dotwork (pixel art), and like them it is a set of primitives
you call, not a 3D editor: a generated mesh is a draft (SOP-11).

Tested on Windows 11, RTX 5060 Ti 16 GB, 64 GB RAM, ComfyUI 0.43.0, Blender 5.2.3 (K01). The numbers below are what
that machine needed, not promises.

## Contents
1. [Setup](#setup)
2. [Make a model](#make-a-model)
3. [What lands where](#what-lands-where)
4. [What to expect](#what-to-expect)
5. [In the engine](#in-the-engine)
6. [Licences](#licences)
7. [Exams](#exams)

## Setup
1. **ComfyUI 0.43.0 or newer** (TRELLIS.2's nodes are built in: no custom node pack). Dotwork's README has the install
   steps (`tools/art/dotwork/README.md`, Setup 1). Meshwright talks to it over HTTP on 127.0.0.1 only.
2. **Model files**, 8.3 GB, each pinned by commit and SHA-256 in `models.lock.json`. Download each into the ComfyUI
   `models/` folder named here, then restart ComfyUI:

   | File | Folder | Size | From |
   |---|---|---|---|
   | trellis_2_int8_convrot.safetensors | diffusion_models | 5.3 GB | Comfy-Org/TRELLIS.2 |
   | dino_v3_vit_l.safetensors | clip_vision | 1.2 GB | Comfy-Org/TRELLIS.2 |
   | trellis_2_shape_vae_bf16.safetensors | vae | 1.1 GB | Comfy-Org/TRELLIS.2 |
   | trellis_2_texture_vae_bf16.safetensors | vae | 0.9 GB | Comfy-Org/TRELLIS.2 |
   | birefnet.safetensors | background_removal | 0.4 GB | Comfy-Org/BiRefNet |

   `--prompt` also needs Dotwork's FLUX.2 klein 4B files (Dotwork's sprites tier). `check` prints the exact URL of
   every missing file.
3. **Blender 4.2+**: set `BLENDER_BIN`, or have `blender` on PATH, or the default install (Windows
   `C:\Program Files\Blender Foundation\Blender <version>\`, macOS `/Applications/Blender.app`). Without the app, a
   Python with the `bpy` module works: `uv run --python 3.13 --with bpy python tools/meshwright/meshwright.py ...`.
4. Run the check from the game's root folder:
   ```
   python tools/meshwright/meshwright.py check          # --hash also checks every file's SHA-256 (COMFYUI_ROOT)
   ```
Hardware: an NVIDIA GPU with 16 GB of VRAM (ComfyUI fills most of it; peak about 14 GB measured) and 32 GB of RAM.
Upstream TRELLIS.2 asks for 24 GB (E109); ComfyUI's int8 build of it runs in 16 (K01).

## Make a model
```
python tools/meshwright/meshwright.py make prop_crate --image art_src/crate_front.png --seed 7
python tools/meshwright/meshwright.py make prop_chest --prompt "a wooden treasure chest with iron bands" --seed 11
python tools/meshwright/meshwright.py make prop_chest --prompt "..." --seed 12 --reference-only   # picture only, 10 s
python tools/meshwright/meshwright.py make npc_robot --prompt "a friendly round robot" --class npc --seed 3
python tools/meshwright/meshwright.py make prop_lamp --image ref.png --sprites assets/art/lamp_sheet.png   # 2D games
```
| Option | What it does |
|---|---|
| `--image FILE` | Your reference: one object, whole, on a plain background, no cast shadow. BiRefNet cuts it out. |
| `--prompt "..."` | FLUX.2 klein 4B draws the reference first (about 10 s). Meshwright adds "one single object ... plain white background" (props, kits) or "full body ... A-pose, front view" (hero, npc); `--raw-prompt` sends yours as written. |
| `--reference-only` | Stop after the picture (`reference_seed<N>.png`). Audition a few seeds for seconds each, then `make --image` the one you like: a 3D run costs minutes. |
| `--class prop\|kit\|hero\|npc` | The SOP-11 budget (`list` shows them). Sets the triangle target, the default height (prop 1.0 m, kit 3.0, hero and npc 1.8), the texture size (1024 or 2048) and the default LODs (hero 0.5,0.25; kit and npc 0.5). |
| `--seed N` | One seed for every sampler. Without it the clock picks one and prints it. Shapes change between seeds: try two or three. |
| `--height M` | Height in metres after cleanup. |
| `--turn DEG` | Turn around the up axis when the model's front is not glTF's front (+Z). TRELLIS.2 put the reference's front there in every run so far. |
| `--lods 0.5,0.25` or `none` | LOD files `<name>_LOD1.glb` ... (Blender's Decimate: check them by eye). |
| `--quality normal\|high` | TRELLIS.2's grid: 1024 (about 5 min warm) or 1536 (about 19 min). |
| `--material texture\|vertex` | Baked PBR textures (base colour, metallic-roughness, normal, AO), or vertex colours only (small, no textures). |
| `--texture 512\|1024\|2048` | Baked texture size. |
| `--out DIR` | Models folder. Default from the game's engine: `assets/models`, web and web-3d `public/assets/models`, Unity `Assets/Models`, Unreal `SourceArt/Models` (import from there). |
| `--sprites FILE` | Also an 8-direction sprite sheet (tools/blender/render_sprites.py) for a 2D game. |
| `--no-log`, `--no-preview`, `--overwrite` | Scratch runs; skip the turntable; make the same name again (the asset log row is updated, not doubled). |

Exit codes: 0 ok, 1 the job or the budget check failed, 2 usage, environment, missing models or files in the way.
Every check that can fail (names, files in the way, the asset log, Blender, ComfyUI, nodes, model files) runs before
the GPU starts.

## What lands where
| Path | What |
|---|---|
| `<models>/<name>.glb`, `<name>_LOD1.glb` ... | The model, only when it passed `validate_asset.py --class`. |
| `assets_src/meshwright/<name>/reference.png` | The picture the mesh was made from (ComfyUI's embedded prompt removed). |
| `assets_src/meshwright/<name>/raw.glb` | TRELLIS.2's own output, before cleanup (its embedded ComfyUI prompt removed: it holds local paths). |
| `.../clean.glb`, `export/` | After cleanup.py, after prep_export.py. A model that fails the budget stays here. |
| `.../cleanup.json`, `.../validate.json` | The numbers: triangles in and out, vertices merged, fragments dropped, size; the validator's findings. |
| `.../meshwright.json` | The record: seed, prompt, class, settings, models with licences, GPU time and VRAM peak, file hashes. |
| `.../turntable.png` | Eight views around the model. Look at it before anything else. |
| `docs/ASSET_LOG.md`, `docs/licenses/A-NNNN.txt` | The row (`pre-generated` AI, licences, "Built with DINOv3" credit) and the evidence file. |
| `docs/licenses/meshwright-*` | The model licence texts, copied the first time; `tools/credits.py` ships them. |
Godot games ship `assets_src/.gdignore`, so the sources stay out of the build. `raw.glb` is a few MB: commit it (or
use Git LFS) if you want the cleanup to be repeatable, as SOP-11 asks.

Run the Blender steps on their own when you need to:
```
blender -b --python-exit-code 1 -P tools/meshwright/cleanup.py -- raw.glb --out clean.glb --max-tris 2700 --height 0.8
blender -b --python-exit-code 1 -P tools/meshwright/turntable.py -- model.glb --out sheet.png --frames-dir frames --background "#d8d8d8"
python tools/art/frames_to_gif.py frames turntable.gif --fps 12 --width 240
```

## What to expect
From the kit's own runs (K01, `workflows/meshwright-showcase/`):
- **Props from a clean reference come out well**: the right shape, a baked texture that matches the picture, a
  closed mesh, under budget after one pass.
- **The back is invented.** TRELLIS.2 sees one picture; the hidden sides are its guess. Look at the turntable.
- **Open or thin parts**: a barrel came back with an open top in every run; thin parts (straps, handles, limbs held
  close to the body) merge or vanish. Characters in an A-pose with clear gaps between arms and body work best.
- **UVs are the model's own unwrap**: the validator passes them on coverage, but warns about texel density (islands
  20x apart) and a few triangles outside 0..1. Fine for props seen at game distance; a hero asset gets a hand
  unwrap (SOP-11 UV check).
- **No rig, no animation.** Characters come out as one static mesh. Rig and animate them per SOP-11 (or use them as
  statues, NPC stand-ins and sprite sources).
- **Seeds matter**: the same picture with another seed can change a detail or the whole shape.
- **Time**: about 5 minutes per model at normal quality once ComfyUI has the model loaded, 8 to 9 minutes cold,
  about 19 at high; cleanup, export, the check and the turntable add about 15 s.

## In the engine
A `.glb` from Meshwright is glTF 2.0, metres, +Y up, front +Z, pivot at the bottom centre, one mesh named after the
model, PBR textures embedded. The game's ENGINE.md (in docs/) has the import line for your engine.
- **Godot 4**: put it under `assets/` (the default) and the editor imports it; headless, run `python tools/dev.py import`
  once after a new model (`test` and `smoke` re-import only when class names change, so they would not see it);
  instance it as a scene (`load("res://assets/models/prop_chest.glb").instantiate()`). Tested: import, `check`,
  `smoke`, and a GUT test that loads it and measures its size (K01).
- **web-3d (Three.js)**: `public/assets/models/` (the default for web games); load it with `GLTFLoader` from
  "three/addons/loaders/GLTFLoader.js" and add `gltf.scene`. Tested in the headless smoke run (K01).
- Unity, Unreal, Bevy: see the ENGINE.md of that engine.
- 2D engines: render it to a sprite sheet (`--sprites`, or `tools/blender/render_sprites.py`).

## Licences
`LICENSES.md` has the register. In short: TRELLIS.2 and BiRefNet are MIT; DINOv3, TRELLIS.2's image encoder, has
its own licence: worldwide and royalty-free, but with a list of prohibited uses (military, weapons, ITAR) whose reach
over game props such as swords and guns is an **open question** you decide for your game. RMBG-2.0 and nvdiffrast,
which upstream TRELLIS.2 uses, are non-commercial and never loaded (`make` refuses a workflow that names them).
Hunyuan3D 2.x (region exclusions) and Stable Fast 3D (revenue cap) were ruled out. Paid 3D services (Meshy, Tripo
and others) are not wired in: `docs/resources/ai-tools.md` lists them.

The name "Meshwright" is used by two other GitHub projects (a 3D-print mesh repair tool and an agent 3D stack); it is
spelled in one constant (`TOOL` in `meshwright.py`), this folder's name and the docs, so a rename stays cheap.

## Exams
```
python tools/meshwright/test_meshwright.py          # offline: a stand-in ComfyUI and a canned mesh; Blender steps
                                                    # for real when Blender (or bpy) is found (about 20 s)
uv run --python 3.13 --with bpy python tools/meshwright/test_meshwright.py   # the same on the bpy module
python tools/meshwright/test_meshwright_live.py     # one real run on the GPU (about 5 min); skips without one
python tools/meshwright/meshwright.py test [--live] # the above in one go
```
