# Bozzetto: local 3D models for your game

Bozzetto turns a reference picture, or a sentence, into a game-ready `.glb` on your own GPU. TRELLIS.2 (Microsoft,
MIT) makes the mesh and bakes its textures inside a local ComfyUI; Blender then cleans it, scales it to a height in
metres, puts the pivot at the bottom centre, writes LODs and checks it against the SOP-11 budget for its class.
Nothing reaches the game's models folder unless that check passes, and every model gets its `docs/ASSET_LOG.md` row.
It is the third asset lane next to Wavesmith (audio) and Dotwork (pixel art), and like them it is a set of primitives
you call, not a 3D editor: a generated mesh is a draft (SOP-11). Without a GPU, or with several views of one object,
`make --with tripo` has the Tripo3D API make the mesh instead (paid credits), and everything after it is the same.
For a whole character, from an idea or a picture to it moving in the game with a look and a yes at every step, ask
Claude for `/make-character`: it runs the commands below in order.

Tested on Windows 11, RTX 5060 Ti 16 GB, 64 GB RAM, ComfyUI 0.43.0, Blender 5.2.3 (K01). The numbers below are what
that machine needed, not promises.

## Contents
1. [Setup](#setup)
2. [Reference views](#reference-views)
3. [Make a model](#make-a-model)
4. [What lands where](#what-lands-where)
5. [What to expect](#what-to-expect) and [UV coverage](#uv-coverage)
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
| What runs | FLUX.2 klein 4B draws the front from `--prompt`; Qwen-Image-Edit-2511 re-poses a `--from` concept; Qwen-Image-Edit with the Multiple-Angles LoRA turns the front to each other view (as Dotwork's rotations do) | Google's Gemini image model ("Nano Banana", default `gemini-nano-banana-2.1`; `--model` for another), one `generateContent` call per view in one conversation on the stable `v1` endpoint: the front, then "the same character from its left side" ... (1K square pictures; `imageSize` is sent only to the models Google's guide shows it on, read 2026-11-13 **(verify)**) | Tripo's text-to-image (from a prompt) or image-to-image (from a concept, default model `banana2`), then its image-to-multiview for the other views |
| Cost | free, your GPU | per picture, about $0.034 for a 1K image plus input and thinking tokens: about $0.21 for four views **(verify: read 2026-11-11 on Google's pricing page; no free tier for image output, and a free-tier key is refused with HTTP 429)** | 10 credits a picture (text-to-image or image-to-image) and 10 for the multiview: 20 credits ($0.20) for all four (measured on a live run 2026-11-11, K01) |
| Needs | a running ComfyUI (the same `--url`/`--allow-remote` rules as `make`), Dotwork's Qwen-Image-Edit files (its `rotate` tier) and the ComfyUI-GGUF node pack; `--prompt` also its FLUX.2 klein files | `GEMINI_API_KEY` from a Google Cloud project with billing on: the free tier cannot make images (a free-tier key gets HTTP 429 with an image quota of 0; measured 2026-11-11, K01), and the run says so and stops | `TRIPO_API_KEY` with API credits |
| Who owns the pictures | you (generated locally; Apache-2.0 models) | you: the Gemini API terms say Google won't claim ownership of generated content (and may make similar content for others); every image carries a SynthID watermark **(verify)** | you, on paid API credits (Tripo terms 5.2.2); not on free credits **(verify)** |

**Paid routes, every time:** the quote is printed first (`--quote-only` prints it and stops, no key needed: show it
to whoever pays and ask; `make` and `rig make` have the same flag). `--max-cost` (dollars for nanobanana, default 1.00; credits for tripo, default 40) caps
one run: a quote over it stops before any call, and before each call the run checks what it has already spent plus
the next call. Every paid result goes into the journal, `assets_src/bozzetto/<name>/reference/journal.json` (pictures in its `steps/` folder), as it arrives,
so a run that fails or hits the cap halfway is run again and pays only for what is missing; a Tripo task the last run
left running is asked for first, never paid for twice. `--no-reuse` pays for a new take; a new `--seed` names a new
take too (the paid services take no seed: it only names the take, so the same command without one reuses its paid
work). The actual cost (Gemini: from the reply's token counts; Tripo: the task's credits) goes into the record.
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
count sees (a changed costume, a flipped side, an arm fused to the body). Left and right the wrong way round
(`left.png` facing the picture's right edge) is fixed without a new run:
```
python tools/bozzetto/bozzetto.py reference chr_keeper --swap-sides     # no GPU, no cost; run it again to undo
```
It swaps the two pictures, rebuilds the sheet, swaps the two views in the record (each picture keeps the prompt that
made it, under its new name and hash) and updates the asset log row and its evidence file. Then:
```
python tools/bozzetto/bozzetto.py make chr_keeper --image assets_src/bozzetto/chr_keeper/reference/front.png --class npc
```
or, with all four views, the paid multiview make (`make chr_keeper --with tripo --class npc --front ... --left ...
--back ... --right ...`, "Make a model"). Prefer to paste prompts into a chat image tool yourself? The same
instructions are in `docs/BRIEFS.md` ("Model-ready reference views").

Options: `--views front,left,back,right` (default all four), `--seed N` (local: every sampler; paid routes: names the
take), `--model`, `--max-cost`, `--quote-only`, `--no-reuse`, `--wait S` (each job or task, default 1800),
`--project`, `--overwrite`, `--no-log`, `--swap-sides`, `--debug`. Exit codes: 0 ok, 1 a call or job failed, 2 usage,
a missing key, the cap, the balance, or files in the way.

**What the local route did in its first live runs** (K01, 2026-11-11, 16 GB RTX 5060 Ti, ComfyUI 0.43): from a prompt,
the four views of one design in a clean A-pose with gaps under the arms, about 7 minutes cold (14 s for the FLUX.2
klein front, about 5 minutes for the first Qwen-Image-Edit job while it loads, about 50 s for each view after). From a
running concept on a city street with a flying scarf, the re-posed front kept the jacket, badges, belt, pouch, jeans
and boots, dropped the street and the light, and stood in the A-pose (56 s warm). Two things to look for: the flying
scarf came back as a cape hanging down the back (the "hang down" instruction can turn loose cloth into another
garment), and the "left side view" came back facing the picture's right, which is why every run asks you to check
the sides by eye. One view had a soft floor shadow (the look check flagged it). A second character from a prompt
(the kit's `workflows/make-character/`, 178 s for four views from a fresh ComfyUI start) came back with the sides
swapped too; `--swap-sides` fixed it in a second. The Tripo route ran live on 2026-11-11 (10 credits a task, as the
table says); Nano Banana was tried with a free-tier key and refused (HTTP 429, image quota 0), so it has not run
past the quote: it needs a key from a project with billing on.

## Make a model
```
python tools/bozzetto/bozzetto.py make prop_crate --image art_src/crate_front.png --seed 7
python tools/bozzetto/bozzetto.py make prop_chest --prompt "a wooden treasure chest with iron bands" --seed 11
python tools/bozzetto/bozzetto.py make prop_chest --prompt "..." --seed 12 --reference-only   # picture only, 10 s
python tools/bozzetto/bozzetto.py make npc_robot --prompt "a friendly round robot" --class npc --seed 3
python tools/bozzetto/bozzetto.py make prop_lamp --image ref.png --sprites assets/art/lamp_sheet.png   # 2D games
```
**Two routes** make the mesh; the rest of `make` (cleanup, the UV rebake on Tripo, budget check, LODs, turntable,
record, log row) is the same:

| | Local (`--with local`, the default) | Tripo (`--with tripo`) |
|---|---|---|
| From | `--image`, or `--prompt` (FLUX.2 klein draws the picture first) | `--image` (image-to-model), `--front` plus any of `--left`, `--back`, `--right` (multiview: two views at least), or `--prompt` (text-to-model) |
| Cost | free | paid API credits (1 credit = $0.01): a P2 image-to-model cost 110 credits in the kit's test, not the 30 of the public table (E153), and a P2 multiview-to-model 110 on the 2026-11-11 live run (K01); text-to-model, the P1 series and `--quality high` are quoted at the kit's ceiling until a run measures them (verify). `--quote-only` prints the price and stops (no key needed); on a real run the quote is printed first and `--max-credits` (default 150) and the balance stop it before anything is uploaded |
| Needs | an NVIDIA GPU with 16 GB, a local ComfyUI with 9 GB of model files, Blender | `TRIPO_API_KEY` with API credits (a Tripo Studio plan adds none), Blender; no GPU, no ComfyUI |
| Time | about 5 minutes warm (K01) | about 16 s for the P2 model in the kit's test (E153), plus the download and Blender |
| Terms | TRELLIS.2 and BiRefNet MIT, DINOv3 License (use restrictions) | outputs on paid credits are yours and not used for training (Tripo terms 5.2.2); outputs on free credits stay Tripo's (5.2.1) |

```
python tools/bozzetto/bozzetto.py make prop_crate --with tripo --image art_src/crate_front.png --seed 7
python tools/bozzetto/bozzetto.py make npc_guard --with tripo --class npc --front ref/front.png --back ref/back.png --left ref/left.png
python tools/bozzetto/bozzetto.py make prop_lamp --with tripo --prompt "a brass ship's lantern" --max-credits 120
python tools/bozzetto/bozzetto.py make npc_guard --with tripo --class npc --front ref/front.png --back ref/back.png --quote-only
```
What the Tripo route does: `--quote-only` prints the price (the kit's table, and 0 when the journal holds a finished
task for the same inputs) and stops, with no key, no call and nothing written. Otherwise the pictures lose their
metadata (as on the local route) and are kept in the source folder, the quote is printed, then the pictures go up (`/files`, PNG or JPEG up to 20 MB) and one task runs; its
actual cost (`credits_consumed`) is read back, and a charge over the quote warns. Every task is written to
`assets_src/bozzetto/<name>/tripo/tasks.json` as it is created: a re-run with the same pictures (or sentence) and
settings reuses it, a finished one with a fresh download link (links expire after about 5 minutes), a running one
by waiting for it; a failed task costs nothing and is made again. Change the pictures, `--seed`, `--class`,
`--quality` or `--tripo-model` and it is a new model; `--no-reuse` pays for a new one on purpose. Fixing the size or
the facing (`--overwrite --height ...`, `--turn ...`) reuses the paid task and spends nothing, whatever
`--max-credits` says (the cap is for one run's own charges). Tripo's models face +X (its export
default, E160): `make` turns them -90 degrees so the front is glTF's +Z **(verify on a live run)**, and cleanup scales
them from Tripo's 1 m to the class height. A character from `--prompt` gets "full body, A-pose" added (`--raw-prompt`
sends yours as written). The quote table, the endpoints and the models are in `tripo.py`; facts not measured in a
paid run are marked (verify) there.

| Option | What it does |
|---|---|
| `--image FILE` | Your reference: one object, whole, on a plain background, no cast shadow. BiRefNet cuts it out. |
| `--prompt "..."` | FLUX.2 klein 4B draws the reference first (about 10 s). Bozzetto adds "one single object ... plain white background" (props, kits) or "full body ... A-pose, front view" (hero, npc); `--raw-prompt` sends yours as written. |
| `--reference-only` | Stop after the picture (`reference_seed<N>.png`). Audition a few seeds for seconds each, then `make --image` the one you like: a 3D run costs minutes. |
| `--class prop\|kit\|hero\|npc` | Default `prop` (a name prefix such as `npc_` does not pick the class). The SOP-11 budget (`list` shows them). Sets the triangle target, the default height (prop 1.0 m, kit 3.0, hero and npc 1.8), the texture size (1024 or 2048) and the default LODs (hero 0.5,0.25; kit and npc 0.5). |
| `--seed N` | One seed for every sampler. Without it the clock picks one and prints it. Shapes change between seeds: try two or three. |
| `--height M` | Height in metres after cleanup. |
| `--turn DEG` | Turn around the up axis (counter-clockwise seen from above) when the model's front is not glTF's front (+Z). TRELLIS.2 put the reference's front there in every run so far (default 0); the Tripo route's default is -90. |
| `--lods 0.5,0.25` or `none` | LOD files `<name>_LOD1.glb` ... (Blender's Decimate: check them by eye), each with its textures at half the size of the level before ("What lands where"). |
| `--quality normal\|high` | Default `normal`. TRELLIS.2's grid: 1024 (about 5 min warm) or 1536 (about 19 min). |
| `--material texture\|vertex` | Default `texture`: baked PBR textures (base colour, metallic-roughness, normal, AO), or vertex colours only (small, no textures). A vertex job queues only its own branch, so the UV unwrap and the bakes do not run; TRELLIS.2's vertex-colour mesh has no UV map, so cleanup.py adds one (Smart UV Project) for lightmaps and the budget check. In Godot such a model renders white until one material flag is set ("In the engine" below, #202). |
| `--texture 512\|1024\|2048` | Baked texture size (the local bake, and the rebake's). |
| `--rebake`, `--rebake auto`, `--no-rebake` | A fresh UV layout in cleanup and the model's textures baked onto it ("UV coverage" below). `--rebake` always; `--rebake auto` only when the model's own atlas is under its class's UV coverage floor (logged either way), the local route's default; always with `--with tripo` (the atlas is Tripo's). Give the model's name before a bare `--rebake`. |
| `--accept-uv` | Ship a model that fails the UV coverage floor alone; the waiver goes on its asset log row and evidence file. |
| `--out DIR` | Models folder. Default from the game's engine: `assets/models`, web and web-3d `public/assets/models`, Unity `Assets/Models`, Unreal `SourceArt/Models` (import from there). |
| `--sprites FILE` | Also an 8-direction sprite sheet (tools/blender/render_sprites.py, with its layout in a .json of the same name beside it) for a 2D game. The sheet goes into the same asset log row and the record, with its hash. |
| `--no-log`, `--no-preview`, `--overwrite` | Scratch runs; skip the turntable; make the same name again (the asset log row is updated, not doubled). |
| `--wait S` | Seconds to wait for each ComfyUI job or Tripo task (default 3600). Each Blender step has its own fixed 3600 s limit. |
| `--with local\|tripo` | The route (table above). Tripo only: `--front`/`--left`/`--back`/`--right FILE`, `--max-credits N` (default 150), `--no-reuse`, `--tripo-model P2-20260801\|P1-20260311` (default P2; P1, Tripo's low-poly series, is not tested here). `--quality high` asks Tripo for detailed textures (more credits); `--material vertex`, `--reference-only` and `.webp` pictures are local only. |
| `--quote-only` | Print the price and stop: Tripo's from the kit's table and the journal (no key needed, nothing made or spent); the local route is free. |
| `--project DIR`, `--blender PATH\|bpy`, `--workflow FILE`, `--debug` | The game's root (default: the current folder); the Blender to use (default: `BLENDER_BIN`, PATH, the default install, then the bpy module); a different API-format TRELLIS.2 workflow with the same node titles; full Blender output and tracebacks. |
| `--url URL`, `--allow-remote` | Another ComfyUI address (default `COMFYUI_URL`, else `http://127.0.0.1:8188`); allow one on another computer. |

Exit codes: 0 ok, 1 the job or the budget check failed, 2 usage, environment, missing models or files in the way.
Ctrl-C stops `make` but not a job already queued in ComfyUI: cancel that one in ComfyUI (its queue panel).
Every check that can fail (names, files in the way, the asset log, Blender, ComfyUI, nodes, model files) runs before
the GPU starts.

## What lands where
| Path | What |
|---|---|
| `<models>/<name>.glb`, `<name>_LOD1.glb` ... | The model, only when it passed `validate_asset.py --class`; the LODs are made from that validated model and copied with it (they are not validated on their own). Every LOD is a whole `.glb` that any engine loads on its own, so it carries its own textures, at half the size of the level before (2048, 1024, 512; never under 256 px; #196). A rebaked 2048 px character, 51,244 triangles with three maps: 11.5 MB, LOD1 10.8 MB and LOD2 10.3 MB before (32.7 MB), 11.5, 4.6 and 1.8 MB now (17.9 MB); Godot 4.7 imported all three with 2048, 1024 and 512 px textures (K01, 2026-11-13). Shared external textures (`.gltf` beside its images) would save the rest but change the file every engine import and the kit's records expect; `tools/blender/prep_export.py --lod-textures keep` writes full-size LOD textures. |
| `assets_src/bozzetto/<name>/reference.png` | The picture the mesh was made from (`.jpg`, `.jpeg` or `.webp` when your `--image` was one). Metadata is removed from the copy and from what ComfyUI gets: EXIF (a photo's GPS position, the camera), XMP, IPTC, text chunks, comments and ComfyUI's embedded prompt; the pixels and the colour profile stay. |
| `assets_src/bozzetto/<name>/raw.glb` | TRELLIS.2's own output, before cleanup (its embedded ComfyUI prompt removed: it holds local paths), or Tripo's (glTF extras removed). |
| `.../view_front.png` ..., `.../tripo/tasks.json`, `.../tripo/tripo.glb` | Tripo route: the views as uploaded (metadata removed), the journal of paid tasks (no key in it), Tripo's file as downloaded. |
| `.../clean.glb`, `export/` | After cleanup.py, after prep_export.py. A model that fails the budget stays here. |
| `.../cleanup.json`, `.../validate.json` | The numbers: triangles in and out, vertices merged, fragments dropped, size, the rebake (coverage and islands before and after, texture size, maps, bake settings, the before/after check); the validator's findings, and `waived` with `--accept-uv`. |
| `.../rebake/` | `rebake <name>`: the model before its first rebake (`before_rebake.glb`), the rebaked file, reports, record and turntable. |
| `.../bozzetto.json` | The record: route, seed, prompt, class, turn, settings, models with licences, GPU time and VRAM peak (local) or Tripo's model, task ids, credits spent and terms (Tripo), file hashes. |
| `.../turntable.png` | Eight views around the model. Look at it before anything else. |
| `docs/ASSET_LOG.md`, `docs/licenses/A-NNNN.txt` | The row (`pre-generated` AI, licences, "Built with DINOv3" credit; Tripo: "paid service", Tripo's terms 5.2.2, the credits and task id) and the evidence file. |
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
- **UVs are the model's own unwrap**: the validator passes props on coverage, but warns about texel density (islands
  20x apart) and a few triangles outside 0..1. Fine for props seen at game distance; a hero asset gets a hand
  unwrap (SOP-11 UV check). Characters land under the floor (TRELLIS.2: 51 to 53% on the npc floor of 55%, E152;
  Tripo: 29% on the hero floor of 60%), and `make` rebakes them: "UV coverage" below.

## UV coverage
The SOP-11 budget floors UV coverage (prop 50%, npc 55%, hero 60%) because an atlas of tiny islands wastes texels;
`validate_asset.py` fails a model under it and nothing ships. A generated model's atlas is the vendor's: a Tripo
multiview character came back with 6,805 islands covering 29% of a 2048 texture, otherwise good (#293), and the user
cannot fix that without a rebake. The policy, decided from that run (K01, 2026-11-11):
- **The floor stays a failure.** The validator measures what ships, not where it came from, and a warning would be
  skipped the way warnings are.
- **The remedy is a rebake** (`tools/blender/rebake_uvs.py`, run by cleanup.py): a new UV map from Smart UV Project
  (66 degrees) packed with Blender's own packer (rotation, exact shapes, a gap of 1 px per 1024: 1 px at 1024, 2 at
  2048, as TRELLIS.2's own atlas has), then every image the materials
  read baked through both layouts onto a new image of the class texture size (base colour, metallic-roughness and
  occlusion, emission and alpha as a plain transfer; the normal map baked as a tangent-space normal, since island
  rotation changes the tangent frame). The materials keep their graphs; only the images and the UV map change. The
  result is checked by rendering both from four sides, as flat colour and lit by a sun (the normal and roughness maps
  show there): a mean difference over 16 levels (24 lit) fails the bake and nothing is written, over 4 (8) warns.
  **Always on for `make --with tripo`** (`--no-rebake` keeps Tripo's atlas). **On the local route, `--rebake auto`
  is the default**: cleanup measures the model's own coverage as the validator will and rebakes only under the class
  floor (`[info] --rebake auto: UV coverage 51.2% (264 islands) is under the floor 55%: rebaking`, or "meets the
  floor: the model's own atlas is kept"); a rebake that lands no higher, or fails its check, is dropped and the model
  keeps its own atlas, with a `[WARN]`. Why only under the floor: there the model cannot ship without a rebake, so
  nothing is lost; over it, TRELLIS.2's own atlas is often the better one (an npc at 63% came back at 57% from a
  rebake). `--rebake` rebakes every time, `--no-rebake` never.
  The numbers go into cleanup.json (`rebake_auto`: the floor, the coverage measured, whether it ran), the record, the
  asset log row ("UV rebaked 29% -> 46% at 2048 px") and its evidence file (islands, maps, bake settings, the check).
- **What it reached on TRELLIS.2 characters** (#203, K01, 2026-11-13, Blender 5.2.3; the two A-pose npcs of E152 and
  two more): 13,500 triangles each, the npc floor 55% at 1024 px: 51% (264 islands) to 59% (452) and 53% (241) to 60%
  (416), both passing now, in 25 to 75 s, the flat check 0.14 levels and the lit check 2.2. With the 2 px gap the
  kit used before they reached 55% and 57%, and the first still failed (54.6%). An npc at 63% is kept as it is; a
  54,000-triangle model at 61% of the hero floor 60% too (a rebake would have reached 63%).
- **What it reached on that character** (51,244 triangles, 120 parts): 29% to 46% coverage, 6,805 to 3,120 islands,
  texel density spread 1.14x to 1.34x, 16 s in Blender 5.2.3, the flat check 0.26 levels mean and the lit check 1.15
  (the turntables are indistinguishable). Not 60%: Smart UV Project turns every tube-like part (straps, rings, a belt)
  into a hollow ring island, and Blender's packer cannot nest islands in the holes, so about 50% is its ceiling on a
  mesh like that; merging the fragments first (tried, 3,120 islands to 190) packed no better. A hand unwrap does
  (SOP-11). The baked maps are PNG, and Tripo's colour maps came as JPEG: the file grew from 5.0 to 11.5 MB.
- **`--accept-uv` is the waiver**: a model that fails on UV coverage alone ships, and the waiver is written to the
  record (`validation.waived`), the asset log row ("UV coverage waived: 46% under the hero floor 60% (--accept-uv)")
  and the evidence file. Any other failure still stops it. A sprite source (`--sprites`, render_sprites.py) never
  needed the floor: waive it there too.
- **`bozzetto.py rebake <name>`** does the same to a model already in the models folder (free: a paid Tripo task is not
  run again), or to any `.glb` with `--input`; LODs are made again from the result, the file is replaced in place
  (the version before stays in `assets_src/bozzetto/<name>/rebake/before_rebake.glb`, and every run starts from it),
  the record and the row are updated. `--no-replace` writes the result next to the reports to look at first;
  `--texture`, `--class`, `--accept-uv` as for make. The Blender script on its own, for a mesh outside Bozzetto:
  ```
  blender -b --python-exit-code 1 -P tools/blender/rebake_uvs.py -- model.glb --out rebaked.glb --texture 2048 --json r.json
  ```
  (`--join` for a file with several meshes, `--no-weld` to keep vertices split at the old seams, `--no-check` to skip
  the renders).
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

### A rigged character (`rig make` output) in each engine (#290)
The rigged `.glb` carries its clips as glTF animations (`idle`, `walk` ...), Mixamo bone names and no root motion
(the clips walk in place: the game moves the character). Every engine's `docs/ENGINE.md` has a "Rigged characters"
recipe and a small helper that loads the file and plays a named clip on a loop, and a test that loads the kit's golden
character (`data/golden/character/`: a 1.8 m blocky biped, Mixamo names, looping `idle` and `walk`), plays `walk` and
checks that `mixamorig:LeftUpLeg` swings as far as the clip does. What was run on 2026-11-11, each on a fresh scaffold:

| Engine | Helper | Import notes | Run |
|---|---|---|---|
| Godot 4.7.2 | `KitCharacter` (scripts/core/kit_character.gd): `load_scene`, `play(hero, "walk")` | glTF clips import without looping (`play` sets `loop_mode` on the player's own copies of the clips, so two instances keep their own flags); `:` becomes `_` (`mixamorig_Hips`); faces +Z | GUT 5 tests; `check`, `test` (109), `smoke` passed |
| web-3d (three r186) | src/game/character.ts: `loadCharacter`, `hero.play("walk")`, `hero.update(dt)` | three strips `:` (`mixamorigHips`); `lookAt` turns the model's +Z front to its target | Vitest 6 tests in Node; `check`, `test` (184), `smoke` passed. Drawing a skinned model in the browser is not tested **(verify)** |
| Unity 6000.6.6f1 | `KitCharacter` (Assets/Scripts/Characters/): `Attach(model, clips).Play("walk")`, `Load(path)` at run time | needs glTFast 6.20.0 (`dev.py exec GameKitCharacters.AddGltfast`); clips are Generic with Loop Time on; names keep `:`; 1 unit = 1 m, faces +Z | EditMode 6 tests, PlayMode 1; `check`, `test` (186), PlayMode (14), `smoke` passed |
| Unreal 5.8.4 | `kit_character.import_character(glb)` (editor Python, `dev.py exec`) | Interchange: `:` becomes `_`, metres to centimetres (180 cm), front +Z to +Y, Hips the root bone; clips get Loop on, root motion off | `test` ran the check (walk sampled, 56.00 degrees); `check` passed. Playing it in a level **(verify)** |
| Bevy 0.20.1 | `spawn_character(&mut commands, &server, "models/hero.glb", "idle")` (src/character.rs), set `Character.clip` to switch | the kit's Cargo.toml adds the `jpeg` feature (Tripo textures are JPEG; Bevy's defaults decode PNG only); names keep `:`; a child half turn makes the +Z front look along `forward()` | `cargo test` headless (no window or GPU); `check`, `test` (138), `smoke` passed. A windowed draw **(verify)** |

**Unity Humanoid (tried, 2026-11-11):** glTFast makes no avatar and imports the clips as Generic. An avatar built in
script from the Mixamo names (`AvatarBuilder.BuildHumanAvatar`) maps all 22 bones from the A-pose, but glTFast's
Generic clips move nothing on a Humanoid Animator. The same character exported from Blender as FBX goes Humanoid with
Create From This Model (20 bones mapped, the shoulders left out), and its humanoid walk also played on the glTF model
through the script-built avatar (with a larger thigh swing: muscle retargeting is not 1:1). So: import a glTF
character Generic and play its own clips; Humanoid is the route for sharing Mixamo-style FBX clips. Details in the
Unity ENGINE.md.

For a 2D game, `render_sprites.py --actions all --manifest assets/dotwork/rendered.assets.json` renders every clip in 8
(or 4) directions into a Dotwork asset manifest that each engine's Dotwork importer loads as it is (SOP-11). The web,
web-3d, LÖVE, C++/SDL3, Bevy, RPG Maker MZ, Unity and Unreal importer tests load the golden character's rendered
sheet; the LÖVE and C++ starters drew it walking. Godot has no manifest importer (it loads Dotwork's own resources):
a 2D Godot game uses the sheets with the layout `.json` beside each by hand **(verify: not in a test)**.

## Rig a character
`make` gives a character as a statue. `rig` gives it a skeleton, skin weights and clips, checks that the rig really
deforms, and names the bones the way engines and animation packs expect (Mixamo's `mixamorig:Hips` ...):
```
python tools/bozzetto/bozzetto.py rig check                                  # which routes are ready
python tools/bozzetto/bozzetto.py rig make npc_guard                         # UniRig: free, your GPU
python tools/bozzetto/bozzetto.py rig make npc_guard --with tripo --clips idle,walk,run   # Tripo: paid credits
python tools/bozzetto/bozzetto.py rig make npc_guard --with tripo --clips idle,walk --quote-only   # the price, no key
```
The input is the model `make` placed (`<models>/<name>.glb`, or `--input` any `.glb`); the result is
`<models>/<name>_rigged.glb`, with its sources and reports in `assets_src/bozzetto/<name>/rig/<route>/` and its own
asset log row: "rig of A-NNNN" when the input has a row of its own (a Bozzetto model does), else "rig of <its path>".

| | UniRig (`--with unirig`, the default) | Tripo (`--with tripo`) |
|---|---|---|
| Cost | free | 25 credits ($0.25) to rig and 10 a clip (measured on live runs 2026-11-05 and 2026-11-11, E153, K01); the default `--clips idle,walk` makes 45. `--quote-only` prints the price and stops (no key needed); on a real run the quote is printed and checked first, and each step's actual cost before the next; `--max-credits` (default 100) caps one run |
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

**Clips stand where the model stands:** Tripo's in-place walk and run came back with `mixamorig:Hips` 1.4 and 2.8 m
sideways in every key (a 1.0 m model, live run 2026-11-11; idle at about 0), so the character stood metres from its
origin in those clips: an engine showed it jump away from its collider when the clip changed, and sprite sheets came
out tiny. `rig_finish.py` measures each clip's hips (the root-most bone with location keys) against the rest pose and
removes their mean sideways offset from every key, keeping the sway around it and every up-and-down bob; it prints
`walk: re-centred 2.61 m` and records each clip in `assets_src/bozzetto/<name>/rig/<route>/rig_finish.json` (`recentred`). Hips within 1% of the height of
their rest spot are left alone. A clip whose hips end more than 10% of the height from where they started travels
(root motion, not in place): it is left as it is, with a warning, since moving it would move where the motion starts.
The kit asks Tripo for in-place clips, and the UniRig route's clips only bob, so expect none. A rigged file from before
this fix: run `rig_finish.py` on it again (`render_sprites.py` names such a clip). The hips are the root-most bone
whose location keys move: a glTF round trip keys every bone, so a still root above the hips does not hide them.

**Clips keep their own frame rate (#292):** Tripo keys at 30 fps. Blender lays such keys every 0.8 frames in its 24 fps
scene, and its glTF exporter, sampling whole frames, wrote the last frame 0.8 frames short of the key that closed the
loop (the walk came back with a visible seam; the idle no longer counted as a loop for `rig chain` without `--loop`).
`rig_finish.py`, `rig_chain.py` and `render_sprites.py` now move the scene to the clips' own rate first
(`tools/blender/bpy_common.py`: the lowest common rate up to 60 fps at which every key is a whole frame), so the poses
and the length are kept exactly; the `rig/<route>/rig_finish.json` report records `fps`. A file whose clips fit no common rate is left at
24 fps with a warning. Blender 4.2's importer names each clip's action `<clip>_<armature>`; the three scripts give the
action its clip's name back, so `walk` stays `walk`.

**Bone names:** UniRig's bones are `bone_0` ... `bone_N`. `rig_finish.py` finds the body by shape (the spine runs from
the root to the highest bone; of the limbs off it, the two reaching the floor are legs, the two reaching farthest
sideways are arms; left is +X) and renames hips, spine, neck, head, legs and arms to Mixamo's names (`--names keep`
skips it). Fingers keep their own names. Tripo's rig already has Mixamo names. The hips are the bone both legs hang
from, so a ground-level root above them keeps its name. It refuses, rather than guesses, when the model faces
sideways or backward (turn it with `make ... --turn`), when an arm has fewer than 3 bones or the rig is partly
Mixamo-named (`--names keep` rigs those with their own names), and when a third limb reaches the floor (bipeds only).

**Tripo's journal:** every paid task is written to `assets_src/bozzetto/<name>/rig/tripo/tasks.json` as it is created and when it finishes, and
each step's actual cost is checked against `--max-credits` and the balance before the next paid call. If a run fails
after paying (a lost download, a missing link, a timeout), run it again: tasks for the same model are reused, with a
fresh download link; other `--clips` later reuse the paid rig and pay for the clips only. A task the last run left
running is asked for its result first; if it is still running the run stops rather than pay for a second one
(`--no-reuse` pays for new ones). `--max-credits` caps one run: a re-run that reuses everything spends nothing and
passes any cap.

Other `rig make` options: `--wait S` (each UniRig step's and Tripo task's limit, default 1800), `--out`,
`--project`, `--no-preview`, `--no-log`, `--overwrite` and `--quote-only` as for `make`; `--input FILE` rigs another
`.glb`.

**One GPU at a time:** UniRig peaks near 15.6 GB. With another program holding the card (ComfyUI, a local LLM
runner) it still finished here, but took 562 s instead of about 85: close them first.

In the engine: the rigged `.glb` carries its clips as glTF animations, starting at 0 s so an engine's loop has no
extra frame on its first pose. Each engine's recipe and what was run: [In the engine](#in-the-engine) "A rigged
character". Unity: import it Generic through glTFast; Humanoid was tried and needs humanoid (FBX) clips.

### Secondary motion
An auto-rig gives a body skeleton: a scarf tail, cape, long hair or tail is skinned stiffly to the neck or spine and
moves like part of the torso. `rig chain` gives that part its own chain of bones and keys its motion into the clips:
```
python tools/bozzetto/bozzetto.py rig chain npc_guard --part colour:#c8202a~0.15          # the scarf: the only red
python tools/bozzetto/bozzetto.py rig chain npc_guard --part scarf=colour:#c8202a --bones 5 --sway 10,idle=4 --cloth hit
python tools/bozzetto/bozzetto.py rig chain npc_guard --part "hair=material:Hair" --part "tail=group:Tail" --no-replace
```
It works on `<models>/<name>_rigged.glb` (from `rig make`) and writes the same file back, so the engine and the asset
log keep pointing at it. The rig before its first chain is kept in `assets_src/bozzetto/<name>/rig/chain/before_chain.glb`
and every run starts from it, so running again with other options replaces the chain instead of adding a second one
(a model rigged again since then becomes the new starting point). `--no-replace` writes only
`assets_src/bozzetto/<name>/rig/chain/chained.glb` and the preview, to look first. The report (chain_report.json), the
record (chain.json) and the preview chain.png (each clip from the side, and from behind for a cape or from the front
for a part down the chest: the side the chain hangs on) sit in the same folder; the
model's asset log row gets a "chain: ..." note.

**Choosing the part** (`--part [label=]selector`, terms joined with `&` must all match; the label names the bones
`label_01` ...):

| Selector | Picks the faces |
|---|---|
| `colour:#rrggbb~0.15` | whose colour is within the tolerance (straight-line distance of sRGB 0..1; 0.15 by default): the base texture at the face, else its colour attribute, else its material colour. The scarf case: the one red on the character |
| `material:NAME` | with that material (case does not matter) |
| `group:NAME` | whose vertices are all at least half in that vertex group (made by hand in Blender) |
| `box:x0,y0,z0,x1,y1,z1` | whose centre is inside the box: metres, glTF axes (Y up, the character faces +Z, its left is +X), as the engine shows the model. `colour:#c8202a&box:-1,0,-1,1,1.2,1` is the red below 1.2 m |

Only the largest connected piece of the selection is used (others are named in the output). It refuses, rather than
guesses, when nothing is selected (naming the closest colour it found, or the model's main colours), when the
selection is more than 40% of a mesh, and when the part is a lump (not longer than it is wide, and not a thin sheet
like a cape). The chain hangs from the nearest bone of the spine line (hips, spine, neck, head), or `--parent`.

**Shapes:** a part that is its own shell is separated from the body as it is. If it has too few rows along its length
to bend (a box with two ends), it is cut across its length: more rows, the same shape, texture and colours. A part
that is fused to the body along its length (generated meshes often are: the scarf is just a red area of one surface)
cannot swing without tearing a hole, so it is **rebuilt as a strip**: a box-section ribbon along the part's middle line,
its width and thickness measured slice by slice, laid just on top of the original, with its texture baked into a small
image of its own (one patch of 32 x 32 texels per strip face, every texel the colour of the nearest point of the part's
own surface, so a 0.26 m wide scarf keeps its pattern down to about 8 mm; the colours of a vertex-coloured part are
copied the same way), so it looks the same from the front. Texture coordinates
copied to the strip's corners used to sweep through the atlas between two islands and showed flecks of body texture
on the scarf (live run 2026-11-11). Its limits, measured on the
exam's fused band: the width (0.09 m of 0.085) and the colours come through; folds, fringes, knots, tassels and a
pattern on the back do not (both sides show the front); the thickness is a guess (8 to 50% of the width); the original
area stays painted on the body, so it shows behind the strip when the strip swings out; one strip follows one middle
line, so a part that wraps around the neck as well as hanging would be flattened (not tried): select the hanging part
only (`&box:...`). `--rebuild strip`
forces a strip, `--rebuild no` refuses to change the shape.

**Weights:** each vertex blends between the two nearest chain bones by its place along the part, and the first half
bone blends into the parent bone, so the root never leaves the body. The check: every vertex of the part sums to 1 and
every chain bone holds some of it.

**Motion:** a clip counts as a loop when its first and last poses match (`--loop` names mocap clips that almost do).
In each loop the chain sways a whole number of cycles over the clip's own frames (about one per 1.5 s), each bone
`--lag` of a cycle (default 0.12) behind the one above it, `--sway` degrees (default 8; per clip: `8,idle=4,run=14`):
outward, away from the body, never into it, and half that sideways. Keys are on every frame and the phase wraps at the
clip's length, so the first and last frame are the same and a sprite cycle still loops (the exam checks it). One-shot
clips named in `--cloth` (`oneshots` for all) get a Blender cloth simulation: a ribbon pinned to the parent bone,
colliding with the body, simulated over the clip, and each chain bone turned to follow it frame by frame, stored in
that clip. It starts at rest and ends where the cloth is, so let the engine blend into the next clip. Other one-shots:
the chain follows the body. The sway does not collide with anything; keep `--sway` small for a part that hangs close
to the legs. The body's own keys are never changed (checked per clip), and the result passes `rig_finish.py`'s checks
(weights, deformation) before anything is written.

**In a 3D engine** the chain bones can be driven by the engine's spring bones instead of (or on top of) the baked
motion. For engine-driven motion, run with `--sway 0` (the chain stays at rest in every clip) so the keys do not fight
the simulation. Recipes:
- Godot 4.6+: a `SpringBoneSimulator3D` child of the imported `Skeleton3D`, `setting_count = 1`,
  `set_root_bone_name(0, "scarf_01")`, `set_end_bone_name(0, "scarf_04")`. Checked headless on Godot 4.7.2 with the
  exam's character exported with `--sway 0` (K01): sliding the model 0.6 m sideways and stopping swung the scarf tip
  up to 0.44 m with only these defaults, and not at all without the node, so tune stiffness, drag and gravity. Read a
  bone's simulated pose in the skeleton's `skeleton_updated` signal (outside it you get the pose before modifiers).
  A `SpringBoneCollisionCapsule3D` on the spine to keep it out of the body **(verify)**.
- Unity **(verify)**: no spring bone in the engine itself. UniVRM's `VRMSpringBone` (MIT) works on any transforms, or
  Animation Rigging's `DampedTransform` per bone for a stiffer follow; paid assets (Dynamic Bone, Magica Cloth) exist.
- Unreal **(verify)**: an `AnimDynamics` node in the character's Animation Blueprint, bound to the chain (chain start
  `scarf_01`, end `scarf_04`), or the free Kawaii Physics plugin.
- Bevy, Three.js **(verify)**: no built-in spring bone; a small system that moves each joint toward its rest position
  with a damped spring (Verlet) and points the bones at the results is enough for a scarf.

Exits: 0 done, 1 refused or a check failed (the model is not touched), 2 usage, a clip name the file does not have,
or `--cloth` on a loop.

### Animation packs (Quaternius, Mixamo)
`rig make` gives a character Mixamo bone names, so clips from an animation pack can play on it. `rig retarget` takes
chosen clips from a pack's file and adds them to `<models>/<name>_rigged.glb`, next to its own clips:
```
python tools/bozzetto/bozzetto.py rig retarget npc_guard --from assets_src/packs/quaternius_ual/UAL1_Standard.glb --clips Walk_Loop=walk_ual,Idle_Loop=idle_ual
python tools/bozzetto/bozzetto.py rig retarget npc_guard --from assets_src/packs/mixamo/Walking.fbx --clips mixamo.com=walk --replace
python tools/bozzetto/bone_map.py pelvis thigh_l upperarm_l ...       # how a pack's bone names map, without Blender
```
`--clips` names each pack clip and what it is called on your character (`SOURCE=new_name`); a name the character
already has is refused unless `--replace`. `--map my_map.json` (`{"their_name": "Hips", ...}`) covers a pack the
built-in maps do not fit; `--no-replace` writes `assets_src/bozzetto/<name>/rig/retarget/retargeted.glb` only, to look
first. The rig before the first retarget is kept there as `before_retarget.glb`, with the report, a record of every
run (retarget.json) and `clips.png` (4 frames of each new clip). The character's asset log row gets a
"retarget: ..." note naming the clips and the pack's own row. The pack needs that row of its own, with its licence,
before the game ships: the command warns when it has none.

How it works (`rig_retarget.py`, in Blender): the pack's bones are renamed to Mixamo's (`bone_map.py`), then for
every frame each bone both rigs share is turned so it points where the pack's bone points. It is a retarget, not a
copy of curves: Quaternius' rig rests in a T-pose and Bozzetto rigs in an A-pose, and their bones roll differently, so
copying rotations by name would swing the arms 40 degrees past the body. The hips also move as the pack's do, scaled
by the two hips heights. Clips come out at your character's frame rate (its own clips' rate, else the pack's), still
looping; a pack that faces the other way (an FBX made for another engine's front) is read turned; a mirrored one is
refused. Each clip is checked before anything is written: every shared bone within 2 degrees of the pack's
(exit 1 and nothing replaced otherwise). Then the hips are re-centred as `rig make` does.

Built-in bone maps:

| Map | Bone names | Notes |
|---|---|---|
| `ual` | Quaternius' Universal Animation Library: `pelvis`, `spine_01..03`, `neck_01`, `Head`, `clavicle_l`, `upperarm_l`, `lowerarm_l`, `hand_l`, `thigh_l`, `calf_l`, `foot_l`, `ball_l`, fingers `thumb_01_l` .. `pinky_04_leaf_l` | The UE Mannequin's naming. Its ground-level `root` bone has no Mixamo role and keeps its name. Other Quaternius packs (the older animated characters) use their own rigs **(verify)**: `bone_map.py <their bone names>` says whether this map fits |
| `mixamo` | `mixamorig:Hips` in any spelling: `mixamorig1:Hips` (Mixamo numbers the prefix when a scene holds two characters), `mixamorig_Hips` (Godot, Unreal), `mixamorigHips` (three.js), bare `Hips` | All become `mixamorig:Hips` |

**Tested (2026-11-13, K01; the pack's page and licence: E162):** Quaternius **Universal Animation Library,
Standard tier** (free; quaternius.com "Universal Animation Library", downloaded from quaternius.itch.io on 2026-11-13,
`Universal Animation Library[Standard].zip`, 15 MB), licence **CC0 1.0** (its License.txt). Inside: `UAL1_Standard.glb`
(clips in place) and `UAL1_Standard_RM.glb` (root motion baked into every clip) for Unreal and Godot, the same two as
FBX for Unity: one 65-bone mannequin, 43 clips at 30 fps.

| What | Result |
|---|---|
| `rig retarget` of `Walk_Loop` and `Idle_Loop` onto the golden character (A-pose, 24 fps), from `UAL1_Standard.glb` | 64 bones renamed (`root` kept), 22 shared; Walk 1.33 s became 32 frames at 24 fps, Idle 2.5 s 60 frames, both still looping; every shared bone within 0.00 degrees of the pack's; `mixamorig:LeftUpLeg` swings 57.6 degrees in the pack and in the written file; Idle's hips stood 0.04 m to the side and were re-centred; the golden character's own `idle` and `walk` unchanged (56.0 degrees); about 6 s. `clips.png` looked at: the walk's legs alternate, arms hang beside the body as in the pack's own render |
| The same from `UAL1_Standard.fbx` | Blender's FBX importer brings it in turned half round and names the clips `Armature\|Armature\|Walk_Loop`: read turned, the same 57.6 degrees |
| Blender 5.2.3 and the bpy 4.2 module | Both runs alike |
| Godot 4.7.2, a fresh scaffold | The UAL walk put on the golden character as `walk` (`--replace`): `KitCharacter` played it and the character test's swing check passed (111 tests) once the test sampled the clip's 1.33 s (it samples 1 s, the golden walk's length) |
| The pack's own character, renamed (no `--onto`, see below), then `rig_finish.py` | 8,548 vertices, 65 bones, 52 in use, deforms 69%; the stray `Icosphere` the pack ships removed |

Other engines play the clips through the same helpers as any clip of the rig (they look bones up by the Mixamo
names); only Godot was run with a pack clip **(verify the others)**.

**Get a Quaternius pack:** on quaternius.com open the pack (Universal Animation Library), Download, then on itch.io
"Download Now" and "No thanks, just take me to the downloads" (free tiers need no account; seen 2026-11-13). Unzip it
outside the game, keep the in-place file (UAL1_Standard.glb in the zip's Unreal-Godot folder; the `_RM` file's clips travel, and
travelling clips are left as they are) and its License.txt under `assets_src/packs/quaternius_ual/`, and log it:
```
| A-0007 | animation | `assets_src/packs/quaternius_ual/UAL1_Standard.glb` | https://quaternius.com/packs/universalanimationlibrary.html (itch.io, Standard tier, free) | Quaternius | CC0 1.0 | Animations by Quaternius (optional: CC0 asks for none) | no | no | 2026-11-13 | 43 clips, 65 bones (UE Mannequin naming); License.txt in docs/licenses/A-0007.txt; clips added to npc_guard_rigged.glb by rig retarget |
```

**The pack's own character:** `rig_retarget.py` on its own, without `--onto`, writes the pack's character with Mixamo
bone names and the clips you pick (all by default), for the engines' helpers to play as they are; check and finish it
like any rig:
```
blender -b --python-exit-code 1 -P tools/bozzetto/rig_retarget.py -- assets_src/packs/quaternius_ual/UAL1_Standard.glb --clips Walk_Loop=walk,Idle_Loop=idle --out assets_src/packs/quaternius_ual/mannequin_named.glb
blender -b --python-exit-code 1 -P tools/bozzetto/rig_finish.py -- assets_src/packs/quaternius_ual/mannequin_named.glb --out assets/models/mannequin_rigged.glb --sheet clips.png
```
(`python tools/bozzetto/rig_retarget.py ...` with the bpy module instead of Blender.)

**Mixamo (verify: not tried here):** Mixamo (mixamo.com, Adobe) has no API and every download needs an Adobe login,
so the kit cannot fetch from it. Its clips come as FBX. Download settings for a clip to retarget: Format **FBX
Binary (.fbx)**, Skin **Without Skin**, Frames per Second **30**, Keyframe Reduction **none**, and tick **In Place** on
walks and runs (otherwise the clip travels). Its skeleton is named `mixamorig:Hips` ... (sometimes `mixamorig1:` and up,
which the `mixamo` map folds back), the same names `rig make` gives, so nothing is renamed and the clip goes on through
the same transfer. Blender names the action `Armature|mixamo.com|Layer0`: ask for it as `mixamo.com`
(`--clips mixamo.com=walk`). Read Adobe's terms for Mixamo before shipping its clips, and log each download.

Limits: bipeds only, like `rig make`; twist about a bone's own axis is carried only as far as the rest poses agree
(a forearm can roll a little differently from the pack's); fingers transfer only when both rigs have them (Bozzetto
rigs keep fingers under their own names); run it before `rig chain`, since a chain's sway is keyed into the clips the
file has when the chain is made (it warns when the rig has a chain). Unity Humanoid on a renamed pack character is not
tried **(verify)**.

## Licences
`LICENSES.md` has the register. In short: TRELLIS.2 and BiRefNet are MIT; DINOv3, TRELLIS.2's image encoder, has
its own licence: worldwide and royalty-free, but with a list of prohibited uses (military, weapons, ITAR) whose reach
over game props such as swords and guns is an **open question** you decide for your game. RMBG-2.0 and nvdiffrast,
which upstream TRELLIS.2 uses, are non-commercial and never loaded (`make` refuses a workflow that names them).
Hunyuan3D 2.x (region exclusions) and Stable Fast 3D (revenue cap) were ruled out. Rigging: UniRig is MIT, its
checkpoint was trained on Articulation-XL2.0 (CC-BY-4.0, credited); its successor SkinTokens is not used (trained on
models from commercial games and VRoid Hub). Tripo is wired in for models (`make --with tripo`), rigging
(`rig --with tripo`) and reference pictures (`reference --with tripo`): outputs bought with paid API credits are yours
(its terms 5.2.2). Google's Gemini is wired in for reference pictures (`reference --with nanobanana`). Other paid 3D
services (Meshy and others) are not wired in: `docs/resources/ai-tools.md` lists them.

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
python tools/bozzetto/test_tripo.py             # make --with tripo, offline: a stand-in Tripo API; with Blender,
                                                    # the real cleanup.py turns a +X-facing mesh to +Z (about 15 s)
python tools/bozzetto/test_rig.py               # rig, offline: stand-in UniRig and Tripo; rig_finish.py on rigs
                                                    # built in Blender when it is found (about 90 s)
python tools/bozzetto/test_chain.py             # rig chain: parsers and the command offline; a made-up scarf
                                                    # character built in Blender when it is found (about 1 min)
python tools/bozzetto/test_retarget.py          # rig retarget: bone maps and the command offline; a made-up pack
                                                    # with Quaternius UAL bone names onto the golden character, in
                                                    # Blender when it is found (about 30 s)
uv run --python 3.11 --with "bpy==4.2.*" python tools/bozzetto/test_rig.py    # the same on the bpy 4.2 module, the
                                                    # kit's floor (BOZZETTO_TEST_BLENDER=bpy picks the module when a
                                                    # Blender is installed too); also test_chain.py and test_bozzetto.py
python tools/bozzetto/test_reference.py         # reference, offline: stand-in ComfyUI, Gemini and Tripo (about 5 s)
python tools/bozzetto/test_rebake.py            # the UV rebake, --rebake auto and --accept-uv offline; a tiny-island
                                                    # cube rebaked, checked and (over the floor) kept, in Blender when it
                                                    # is found (about 2 min)
python tools/bozzetto/bozzetto.py test [--live] # the above in one go
```
