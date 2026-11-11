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
2. [Reference views](#reference-views)
3. [Make a model](#make-a-model)
4. [What lands where](#what-lands-where)
5. [What to expect](#what-to-expect)
6. [In the engine](#in-the-engine)
7. [Rig a character](#rig-a-character)
8. [Licences](#licences)
9. [Exams](#exams)

## Setup
1. **ComfyUI 0.43.0 or newer** (TRELLIS.2's nodes are built in: no custom node pack). Dotwork's README has the install
   steps (`tools/art/dotwork/README.md`, Setup 1). Bozzetto talks to it over HTTP, on this machine by default (`http://127.0.0.1:8188`; another address with
   `COMFYUI_URL` or `--url`, and a ComfyUI on another computer only with `--allow-remote`).
2. **Model files**, about 9.0 GB (8.3 GiB), each pinned by commit and SHA-256 in `models.lock.json`. Download each into the ComfyUI
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
   python tools/bozzetto/bozzetto.py check          # --hash also checks the five files' SHA-256 (needs COMFYUI_ROOT;
                                                    # Dotwork's FLUX.2 klein files are not hashed here)
   ```
Hardware: an NVIDIA GPU with 16 GB of VRAM (ComfyUI fills most of it; peak about 14 GB measured) and 32 GB of RAM.
Upstream TRELLIS.2 asks for 24 GB (E109); ComfyUI's int8 build of it runs in 16 (K01).

## Reference views
A character concept is usually a dynamic pose: arms against the body, a scarf flying, one view. 3D generators and
auto-riggers want something else: the same design in a relaxed A-pose with a gap between each arm and the body,
orthographic and straight-on, flat light, a plain background, ideally from the front, the side and the back.
`reference` makes those views from your concept picture or from a sentence:
```
python tools/bozzetto/bozzetto.py reference chr_keeper --prompt "a lanky lighthouse keeper in a yellow coat" --seed 4
python tools/bozzetto/bozzetto.py reference chr_keeper --from art_src/keeper_concept.png --seed 4
python tools/bozzetto/bozzetto.py reference chr_keeper --from art_src/keeper_concept.png --with nanobanana --quote-only
python tools/bozzetto/bozzetto.py reference chr_keeper --prompt "..." --with tripo --views front,back --max-cost 30
```
Every route asks for the same thing: a relaxed A-pose (arms about 35 degrees out, hands open, legs a little apart, feet
flat), orthographic straight-on camera, flat even light with no cast shadow, a plain light grey background, nothing
else in frame, loose cloth (scarves, capes, coat tails, long hair) hanging down instead of flying. From a concept the
instruction is "keep every design detail identical, change only the pose, the camera, the light and the background".
The front is always made first; the other views are turned from it.

| | local (default) | nanobanana | tripo |
|---|---|---|---|
| What runs | FLUX.2 klein 4B draws the front from `--prompt`; Qwen-Image-Edit-2511 re-poses a `--from` concept; Qwen-Image-Edit with the Multiple-Angles LoRA turns the front to each other view (as Dotwork's rotations do) | Google's Gemini image model ("Nano Banana", default `gemini-nano-banana-2.1`; `--model` for another), one `generateContent` call per view in one conversation: the front, then "the same character from its left side" ... | Tripo's text-to-image (from a prompt) or image-to-image (from a concept, default model `banana2`), then its image-to-multiview for the other views |
| Cost | free, your GPU | per picture, about $0.034 for a 1K image plus input and thinking tokens: about $0.21 for four views **(verify: read 2026-11-11 on Google's pricing page; no free tier for image output)** | about 5 to 10 credits a picture and 10 for the multiview: up to 20 credits ($0.20) for all four **(verify: upper bounds from Tripo's pricing summary, 2026-11-11)** |
| Needs | a running ComfyUI (the same `--url`/`--allow-remote` rules as `make`), Dotwork's Qwen-Image-Edit files (its `rotate` tier) and the ComfyUI-GGUF node pack; `--prompt` also its FLUX.2 klein files | `GEMINI_API_KEY` on a project with billing | `TRIPO_API_KEY` with API credits |
| Who owns the pictures | you (generated locally; Apache-2.0 models) | you: the Gemini API terms say Google won't claim ownership of generated content (and may make similar content for others); every image carries a SynthID watermark **(verify)** | you, on paid API credits (Tripo terms 5.2.2); not on free credits **(verify)** |

**Paid routes, every time:** the quote is printed first (`--quote-only` prints it and stops, no key needed: show it
to whoever pays and ask). `--max-cost` (dollars for nanobanana, default 1.00; credits for tripo, default 40) caps
one run: a quote over it stops before any call, and before each call the run checks what it has already spent plus
the next call. Every paid result goes into the journal, `assets_src/bozzetto/<name>/reference/journal.json` (pictures in its `steps/` folder), as it arrives,
so a run that fails or hits the cap halfway is run again and pays only for what is missing; a Tripo task the last run
left running is asked for first, never paid for twice. `--no-reuse` pays for a new take; a new `--seed` names a new
take too. The actual cost (Gemini: from the reply's token counts; Tripo: the task's credits) goes into the record.
Keys are read from the environment and sent only in request headers; every picture sent out has its metadata (EXIF,
GPS, XMP, text) removed first.

What lands in `assets_src/bozzetto/<name>/reference/`: `front.png`, `left.png`, `back.png`, `right.png` (the views
asked for), `sheet.png` (the views side by side, front, left, back, right), `concept.png` (your concept, metadata
removed), the record reference.json (route, model, prompts, seeds, cost, terms, the look check) and, on paid
routes, the journal and `steps/`. The asset log gets an `art` row with the route and its terms (`--no-log` for scratch
runs); `--overwrite` makes the views again and updates the same row. "Left" is the character's own left side: in
`left.png` it faces the left edge of the picture.

**The look check** prints `[look]` lines when a background is not flat or not light, a figure touches the edge, or
the views differ in height or feet line. It is a hint, not a gate: look at `sheet.png` yourself for what no pixel
count sees (a changed costume, a flipped side, an arm fused to the body). Then:
```
python tools/bozzetto/bozzetto.py make chr_keeper --image assets_src/bozzetto/chr_keeper/reference/front.png --class npc
```
or, with all four views, a multiview make (#287). Prefer to paste prompts into a chat image tool yourself? The same
instructions are in `docs/BRIEFS.md` ("Model-ready reference views").

Options: `--views front,left,back,right` (default all four), `--seed N` (local: every sampler; paid routes: names the
take), `--model`, `--max-cost`, `--quote-only`, `--no-reuse`, `--wait S` (each job or task, default 1800),
`--project`, `--overwrite`, `--no-log`, `--debug`. Exit codes: 0 ok, 1 a call or job failed, 2 usage, a missing key,
the cap, the balance, or files in the way. Not yet run live: no route has made a real character yet (K01 covers the
offline exam only).

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
| `--class prop\|kit\|hero\|npc` | Default `prop` (a name prefix such as `npc_` does not pick the class). The SOP-11 budget (`list` shows them). Sets the triangle target, the default height (prop 1.0 m, kit 3.0, hero and npc 1.8), the texture size (1024 or 2048) and the default LODs (hero 0.5,0.25; kit and npc 0.5). |
| `--seed N` | One seed for every sampler. Without it the clock picks one and prints it. Shapes change between seeds: try two or three. |
| `--height M` | Height in metres after cleanup. |
| `--turn DEG` | Turn around the up axis when the model's front is not glTF's front (+Z). TRELLIS.2 put the reference's front there in every run so far. |
| `--lods 0.5,0.25` or `none` | LOD files `<name>_LOD1.glb` ... (Blender's Decimate: check them by eye). |
| `--quality normal\|high` | Default `normal`. TRELLIS.2's grid: 1024 (about 5 min warm) or 1536 (about 19 min). |
| `--material texture\|vertex` | Default `texture`: baked PBR textures (base colour, metallic-roughness, normal, AO), or vertex colours only (small, no textures). A vertex job queues only its own branch, so the UV unwrap and the bakes do not run; TRELLIS.2's vertex-colour mesh has no UV map, so cleanup.py adds one (Smart UV Project) for lightmaps and the budget check. In Godot such a model renders white until one material flag is set ("In the engine" below, #202). |
| `--texture 512\|1024\|2048` | Baked texture size. |
| `--out DIR` | Models folder. Default from the game's engine: `assets/models`, web and web-3d `public/assets/models`, Unity `Assets/Models`, Unreal `SourceArt/Models` (import from there). |
| `--sprites FILE` | Also an 8-direction sprite sheet (tools/blender/render_sprites.py, with its layout in a .json of the same name beside it) for a 2D game. The sheet goes into the same asset log row and the record, with its hash. |
| `--no-log`, `--no-preview`, `--overwrite` | Scratch runs; skip the turntable; make the same name again (the asset log row is updated, not doubled). |
| `--wait S` | Seconds to wait for each ComfyUI job (default 3600). Each Blender step has its own fixed 3600 s limit. |
| `--project DIR`, `--blender PATH\|bpy`, `--workflow FILE`, `--debug` | The game's root (default: the current folder); the Blender to use (default: `BLENDER_BIN`, PATH, the default install, then the bpy module); a different API-format TRELLIS.2 workflow with the same node titles; full Blender output and tracebacks. |
| `--url URL`, `--allow-remote` | Another ComfyUI address (default `COMFYUI_URL`, else `http://127.0.0.1:8188`); allow one on another computer. |

Exit codes: 0 ok, 1 the job or the budget check failed, 2 usage, environment, missing models or files in the way.
Ctrl-C stops `make` but not a job already queued in ComfyUI: cancel that one in ComfyUI (its queue panel).
Every check that can fail (names, files in the way, the asset log, Blender, ComfyUI, nodes, model files) runs before
the GPU starts.

## What lands where
| Path | What |
|---|---|
| `<models>/<name>.glb`, `<name>_LOD1.glb` ... | The model, only when it passed `validate_asset.py --class`; the LODs are made from that validated model and copied with it (they are not validated on their own). |
| `assets_src/bozzetto/<name>/reference.png` | The picture the mesh was made from (`.jpg`, `.jpeg` or `.webp` when your `--image` was one). Metadata is removed from the copy and from what ComfyUI gets: EXIF (a photo's GPS position, the camera), XMP, IPTC, text chunks, comments and ComfyUI's embedded prompt; the pixels and the colour profile stay. |
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
- **Godot 4**: put it under `assets/` (the default) and the editor imports it; headless, `check`, `test` and `smoke`
  import a new or changed model first (or run `python tools/dev.py import`);
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
asset log row: "rig of A-NNNN" when the input has a row of its own (a Bozzetto model does), else "rig of <its path>".

| | UniRig (`--with unirig`, the default) | Tripo (`--with tripo`) |
|---|---|---|
| Cost | free | about 25 credits ($0.25) to rig, 10 a clip; the default `--clips idle,walk` makes 45. The quote is printed and checked first, and each step's actual cost before the next; `--max-credits` (default 100) caps one run |
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
vertices with no weight, NaN, infinite or negative weights, weights that do not sum to 1, vertices only on glTF's
placeholder bone (`neutral_bone`), one bone holding most of the mesh, too few bones in use, and, by bending every
bone 15 degrees, a mesh that does not move (the rig must deform). A failed check ships nothing. It also removes a mesh nothing skins (both
routes leave a stray `Icosphere`) and scales Tripo's 1.0 m output back to the model's height.

**Bone names:** UniRig's bones are `bone_0` ... `bone_N`. `rig_finish.py` finds the body by shape (the spine runs from
the root to the highest bone; of the limbs off it, the two reaching the floor are legs, the two reaching farthest
sideways are arms; left is +X) and renames hips, spine, neck, head, legs and arms to Mixamo's names (`--names keep`
skips it). Fingers keep their own names. Tripo's rig already has Mixamo names. The hips are the bone both legs hang
from, so a ground-level root above them keeps its name. It refuses, rather than guesses, when the model faces
sideways or backward (turn it with `make ... --turn`), when an arm has fewer than 3 bones or the rig is partly
Mixamo-named (`--names keep` rigs those with their own names), and when a third limb reaches the floor (bipeds only).

**Tripo's journal:** every paid task is written to `assets_src/bozzetto/<name>/rig/tripo/tasks.json` as it is created and when it finishes, and
each step's actual cost is checked against `--max-credits` and the balance before the next paid call. If a run fails
after paying (a lost download, a missing link, a timeout), run it again: tasks for the same model and clips are
reused, with a fresh download link. A task the last run left running is asked for its result first; if it is
still running the run stops rather than pay for a second one (`--no-reuse` pays for new ones).

Other `rig make` options: `--wait S` (each UniRig step's and Tripo task's limit, default 1800), `--out`,
`--project`, `--no-preview`, `--no-log` and `--overwrite` as for `make`; `--input FILE` rigs another `.glb`.

**One GPU at a time:** UniRig peaks near 15.6 GB. With another program holding the card (ComfyUI, a local LLM
runner) it still finished here, but took 562 s instead of about 85: close them first.

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
models from commercial games and VRoid Hub). Tripo is wired in for rigging (`rig --with tripo`) and reference
pictures (`reference --with tripo`), Google's Gemini for reference pictures (`reference --with nanobanana`); other
paid 3D services (Meshy and others) are not: `docs/resources/ai-tools.md` lists them.

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
python tools/bozzetto/test_reference.py         # reference, offline: stand-in ComfyUI, Gemini and Tripo (about 5 s)
python tools/bozzetto/bozzetto.py test [--live] # the above in one go
```
