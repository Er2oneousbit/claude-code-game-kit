# Bozzetto: local 3D models for your game

Bozzetto turns a reference picture, or a sentence, into a game-ready `.glb` on your own GPU. TRELLIS.2 (Microsoft,
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
6. [Rig a character](#rig-a-character)
7. [Licences](#licences)
8. [Exams](#exams)

## Setup
1. **ComfyUI 0.43.0 or newer** (TRELLIS.2's nodes are built in: no custom node pack). Dotwork's README has the install
   steps (`tools/art/dotwork/README.md`, Setup 1). Bozzetto talks to it over HTTP on 127.0.0.1 only.
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
   Python with the `bpy` module works: `uv run --python 3.13 --with bpy python tools/bozzetto/bozzetto.py ...`.
4. Run the check from the game's root folder:
   ```
   python tools/bozzetto/bozzetto.py check          # --hash also checks every file's SHA-256 (COMFYUI_ROOT)
   ```
Hardware: an NVIDIA GPU with 16 GB of VRAM (ComfyUI fills most of it; peak about 14 GB measured) and 32 GB of RAM.
Upstream TRELLIS.2 asks for 24 GB (E109); ComfyUI's int8 build of it runs in 16 (K01).

## Make a model
```
python tools/bozzetto/bozzetto.py make prop_crate --image art_src/crate_front.png --seed 7
python tools/bozzetto/bozzetto.py make prop_chest --prompt "a wooden treasure chest with iron bands" --seed 11
python tools/bozzetto/bozzetto.py make prop_chest --prompt "..." --seed 12 --reference-only   # picture only, 10 s
python tools/bozzetto/bozzetto.py make npc_robot --prompt "a friendly round robot" --class npc --seed 3
python tools/bozzetto/bozzetto.py make prop_lamp --image ref.png --sprites assets/art/lamp_sheet.png   # 2D games
```
| Option | What it does |
|---|---|
| `--image FILE` | Your reference: one object, whole, on a plain background, no cast shadow. BiRefNet cuts it out. |
| `--prompt "..."` | FLUX.2 klein 4B draws the reference first (about 10 s). Bozzetto adds "one single object ... plain white background" (props, kits) or "full body ... A-pose, front view" (hero, npc); `--raw-prompt` sends yours as written. |
| `--reference-only` | Stop after the picture (`reference_seed<N>.png`). Audition a few seeds for seconds each, then `make --image` the one you like: a 3D run costs minutes. |
| `--class prop\|kit\|hero\|npc` | The SOP-11 budget (`list` shows them). Sets the triangle target, the default height (prop 1.0 m, kit 3.0, hero and npc 1.8), the texture size (1024 or 2048) and the default LODs (hero 0.5,0.25; kit and npc 0.5). |
| `--seed N` | One seed for every sampler. Without it the clock picks one and prints it. Shapes change between seeds: try two or three. |
| `--height M` | Height in metres after cleanup. |
| `--turn DEG` | Turn around the up axis when the model's front is not glTF's front (+Z). TRELLIS.2 put the reference's front there in every run so far. |
| `--lods 0.5,0.25` or `none` | LOD files `<name>_LOD1.glb` ... (Blender's Decimate: check them by eye). |
| `--quality normal\|high` | TRELLIS.2's grid: 1024 (about 5 min warm) or 1536 (about 19 min). |
| `--material texture\|vertex` | Baked PBR textures (base colour, metallic-roughness, normal, AO), or vertex colours only (small, no textures). A vertex job queues only its own branch, so the UV unwrap and the bakes do not run; TRELLIS.2's vertex-colour mesh has no UV map, so cleanup.py adds one (Smart UV Project) for lightmaps and the budget check. In Godot such a model renders white until one material flag is set ("In the engine" below, #202). |
| `--texture 512\|1024\|2048` | Baked texture size. |
| `--out DIR` | Models folder. Default from the game's engine: `assets/models`, web and web-3d `public/assets/models`, Unity `Assets/Models`, Unreal `SourceArt/Models` (import from there). |
| `--sprites FILE` | Also an 8-direction sprite sheet (tools/blender/render_sprites.py, with its layout in a .json of the same name beside it) for a 2D game. The sheet goes into the same asset log row and the record, with its hash. |
| `--no-log`, `--no-preview`, `--overwrite` | Scratch runs; skip the turntable; make the same name again (the asset log row is updated, not doubled). |

Exit codes: 0 ok, 1 the job or the budget check failed, 2 usage, environment, missing models or files in the way.
Every check that can fail (names, files in the way, the asset log, Blender, ComfyUI, nodes, model files) runs before
the GPU starts.

## What lands where
| Path | What |
|---|---|
| `<models>/<name>.glb`, `<name>_LOD1.glb` ... | The model, only when it passed `validate_asset.py --class`. |
| `assets_src/bozzetto/<name>/reference.png` | The picture the mesh was made from (`.jpg` or `.webp` when your `--image` was one). Metadata is removed from the copy and from what ComfyUI gets: EXIF (a photo's GPS position, the camera), XMP, IPTC, text chunks, comments and ComfyUI's embedded prompt; the pixels and the colour profile stay. |
| `assets_src/bozzetto/<name>/raw.glb` | TRELLIS.2's own output, before cleanup (its embedded ComfyUI prompt removed: it holds local paths). |
| `.../clean.glb`, `export/` | After cleanup.py, after prep_export.py. A model that fails the budget stays here. |
| `.../cleanup.json`, `.../validate.json` | The numbers: triangles in and out, vertices merged, fragments dropped, size; the validator's findings. |
| `.../bozzetto.json` | The record: seed, prompt, class, settings, models with licences, GPU time and VRAM peak, file hashes. |
| `.../turntable.png` | Eight views around the model. Look at it before anything else. |
| `docs/ASSET_LOG.md`, `docs/licenses/A-NNNN.txt` | The row (`pre-generated` AI, licences, "Built with DINOv3" credit) and the evidence file. |
| `docs/licenses/bozzetto-*` | The model licence texts, copied the first time; `tools/credits.py` ships them. |
Godot games ship `assets_src/.gdignore`, so the sources stay out of the build. `raw.glb` is a few MB: commit it (or
use Git LFS) if you want the cleanup to be repeatable, as SOP-11 asks.

Run the Blender steps on their own when you need to:
```
blender -b --python-exit-code 1 -P tools/bozzetto/cleanup.py -- raw.glb --out clean.glb --max-tris 2700 --height 0.8
blender -b --python-exit-code 1 -P tools/bozzetto/turntable.py -- model.glb --out sheet.png --frames-dir frames --background "#d8d8d8"
python tools/art/frames_to_gif.py frames turntable.gif --fps 12 --width 240
```

## What to expect
From the kit's own runs (K01, `workflows/bozzetto-showcase/`):
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
A `.glb` from Bozzetto is glTF 2.0, metres, +Y up, front +Z, pivot at the bottom centre, one mesh named after the
model, PBR textures embedded. The game's ENGINE.md (in docs/) has the import line for your engine.
- **Godot 4**: put it under `assets/` (the default) and the editor imports it; headless, run `python tools/dev.py import`
  once after a new model (`test` and `smoke` re-import only when class names change, so they would not see it);
  instance it as a scene (`load("res://assets/models/prop_chest.glb").instantiate()`). Tested: import, `check`,
  `smoke`, and a GUT test that loads it and measures its size (K01). A `--material vertex` model renders white until
  its materials get `vertex_color_use_as_albedo = true`: Godot 4.7 imports the colours but leaves that off (K01, #202;
  the loop is in the Godot ENGINE.md).
- **web-3d (Three.js)**: `public/assets/models/` (the default for web games); load it with `GLTFLoader` from
  "three/addons/loaders/GLTFLoader.js" and add `gltf.scene`. Tested in the headless smoke run (K01). Vertex colours
  need nothing extra: GLTFLoader turns `vertexColors` on by itself.
- Unity, Unreal, Bevy: see the ENGINE.md of that engine.
- 2D engines: render it to a sprite sheet (`--sprites`, or `tools/blender/render_sprites.py`).

## Rig a character
`make` gives a character as a statue. `rig` gives it a skeleton, skin weights and clips, checks that the rig really
deforms, and names the bones the way engines and animation packs expect (Mixamo's `mixamorig:Hips` ...):
```
python tools/bozzetto/bozzetto.py rig check                                  # which routes are ready
python tools/bozzetto/bozzetto.py rig make npc_guard                         # UniRig: free, your GPU
python tools/bozzetto/bozzetto.py rig make npc_guard --with tripo --clips idle,walk,run   # Tripo: paid credits
```
The input is the model `make` placed (`<models>/<name>.glb`, or `--input` any `.glb`); the result is
`<models>/<name>_rigged.glb`, with its sources and reports in `assets_src/bozzetto/<name>/rig/<route>/` and its own
asset log row ("rig of A-NNNN").

| | UniRig (`--with unirig`, the default) | Tripo (`--with tripo`) |
|---|---|---|
| Cost | free | about 25 credits ($0.25) to rig, 10 a clip; the quote is printed and checked first |
| Needs | an NVIDIA GPU (peak 15.6 GB measured), a UniRig checkout and its Python env | `TRIPO_API_KEY` with API credits (a Tripo Studio plan does not add them) |
| Clips | `--animate idle,wave,walk` (default) or `none`: keyed by `rig_finish.py`, game-jam quality | `--clips` up to 5 of Tripo's presets (`idle`, `walk`, `run`, `jump`, `turn`, ...): mocap-like |
| Time (K01) | about 85 s | about 30 s |
| Terms | UniRig MIT; trained on Articulation-XL2.0 (CC-BY-4.0: credited in the log) | outputs are yours on paid credits (Tripo terms 5.2.2), not on free ones |

**UniRig setup**, once, standard wheels only (no flash_attn, no Triton, no community builds):
```
git clone https://github.com/VAST-AI-Research/UniRig && cd UniRig
python <game>/tools/bozzetto/rig/patch_unirig.py .    # four small changes; safe to run twice; --check reports
uv venv --python 3.11 .venv                           # bpy 4.2 pins Python 3.11
uv pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install torch_scatter torch_cluster -f https://data.pyg.org/whl/torch-2.7.0+cu128.html
uv pip install spconv-cu126
uv pip install -r requirements.txt numpy==1.26.4      # remove its flash_attn line first
```
Then set `UNIRIG_DIR` to the checkout (`UNIRIG_PY` if its Python lives elsewhere). cu128 is the first CUDA build with
Blackwell (RTX 50) GPUs; older cards work with it too. The patch: flash_attn's attention class swapped for a PyTorch
stand-in with the same weights (`rig/mha_sdpa.py`, outputs within 1e-7), `sdpa` for the skeleton model, the skin
model's point encoder on its own attention (flash_attn returned wrong values at head size 16 on a Blackwell card,
which made a rig that deformed nothing), and a weights-only allowlist for one class in the skin checkpoint (instead of
the unsafe `weights_only=False`). The details and how they were found: `workflows/picture-to-game/`.

**What every rig is checked for** (`rig_finish.py`, both routes), because broken rigs here came back with exit 0:
vertices with no weight, NaN weights, vertices only on glTF's placeholder bone (`neutral_bone`), one bone holding
most of the mesh, too few bones in use. A failed check ships nothing. It also removes a mesh nothing skins (both
routes leave a stray `Icosphere`) and scales Tripo's 1.0 m output back to the model's height.

**Bone names:** UniRig's bones are `bone_0` ... `bone_N`. `rig_finish.py` finds the body by shape (the spine runs from
the root to the highest bone; of the limbs off it, the two reaching the floor are legs, the two reaching farthest
sideways are arms; left is +X) and renames hips, spine, neck, head, legs and arms to Mixamo's names (`--names keep`
skips it). Fingers keep their own names. Tripo's rig already has Mixamo names. Bipeds only: a third limb on the floor
stops it.

In the engine: the rigged `.glb` carries its clips as glTF animations. Godot: an AnimationPlayer in the imported scene;
glTF clips import without looping, so set `loop_mode` (the showcase does). Unity: set the model's rig to Humanoid; the
Mixamo names should map without hand work, so Mixamo-style clips play on it **(verify: not yet tested in Unity)**.

## Licences
`LICENSES.md` has the register. In short: TRELLIS.2 and BiRefNet are MIT; DINOv3, TRELLIS.2's image encoder, has
its own licence: worldwide and royalty-free, but with a list of prohibited uses (military, weapons, ITAR) whose reach
over game props such as swords and guns is an **open question** you decide for your game. RMBG-2.0 and nvdiffrast,
which upstream TRELLIS.2 uses, are non-commercial and never loaded (`make` refuses a workflow that names them).
Hunyuan3D 2.x (region exclusions) and Stable Fast 3D (revenue cap) were ruled out. Rigging: UniRig is MIT, its
checkpoint was trained on Articulation-XL2.0 (CC-BY-4.0, credited); its successor SkinTokens is not used (trained on
models from commercial games and VRoid Hub). Tripo is wired in for rigging only (`rig --with tripo`); other paid 3D
services (Meshy and others) are not: `docs/resources/ai-tools.md` lists them.

The tool was first called Meshwright and renamed before release: that name, and Polywright, Whittle and Plinth, were
already taken by other 3D projects. A web search on 2026-11-05 found no software named "Bozzetto" **(verify)** before
a release. The name is spelled in one constant (`TOOL` in `bozzetto.py`), this folder's name and the docs, so a
rename stays cheap.

## Exams
```
python tools/bozzetto/test_bozzetto.py          # offline: a stand-in ComfyUI and a canned mesh; Blender steps
                                                    # for real when Blender (or bpy) is found (about 20 s)
uv run --python 3.13 --with bpy python tools/bozzetto/test_bozzetto.py   # the same on the bpy module
python tools/bozzetto/test_bozzetto_live.py     # one real run on the GPU (about 5 min); skips without one
python tools/bozzetto/test_rig.py               # rig, offline: stand-in UniRig and Tripo; rig_finish.py on rigs
                                                    # built in Blender when it is found (about 25 s)
python tools/bozzetto/bozzetto.py test [--live] # the above in one go
```
