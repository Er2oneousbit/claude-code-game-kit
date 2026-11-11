# SOP-11: 3D Models and Animation Pipeline

## Goal
Consistent, engine-ready 3D content, with Claude doing scripting and automation and a human making the judgment calls.

## Which tool for which job
The 3D tools are separate primitives, not one suite: Bozzetto calls the Blender tools, and the Blender tools work just
as well on a model you made, bought or downloaded.
| Job | Tool | More |
|---|---|---|
| A character concept or idea to model-ready views (A-pose front, left, back, right) | `python tools/bozzetto/bozzetto.py reference <name> --from <concept.png>` (or `--prompt "..."`; `--with nanobanana` or `tripo` is paid) | [Local generation](#local-generation-bozzetto), `tools/bozzetto/README.md` "Reference views" |
| A model from a picture or a sentence, on your own GPU | `python tools/bozzetto/bozzetto.py make <name> --image <ref.png>` (or `--prompt "..."`) | [Local generation](#local-generation-bozzetto), `tools/bozzetto/README.md` |
| The same from Tripo (paid credits, no GPU; one picture, several views or a sentence) | `bozzetto.py make <name> --with tripo --image <ref.png>` (or `--front F --back B ...`, or `--prompt "..."`) | [Local generation](#local-generation-bozzetto) "The Tripo route", `tools/bozzetto/README.md` |
| Clean a raw generated mesh (merge, fragments, decimate, height, pivot) | `tools/bozzetto/cleanup.py`, in Blender | `tools/bozzetto/README.md` "What lands where" |
| Look at a model from every side | `tools/bozzetto/turntable.py`, in Blender | `tools/bozzetto/README.md` |
| Check a model against its class budget | `tools/blender/validate_asset.py <file.glb> --class <class>` | Stage 4 below |
| Make any model engine-ready (transforms, pivot, names, LODs, `.glb`) | `tools/blender/prep_export.py` | Stage 5 below |
| A 2D sprite sheet from a 3D model | `tools/blender/render_sprites.py` (or `bozzetto.py make --sprites`) | [3D source, 2D game](#3d-source-2d-game-sprite-sheets) |
| Procedural props, kits, shaders, batch jobs | Claude-written scripts in `tools/blender/` | [Claude and Blender](#claude-and-blender) |
| Rig a character (skeleton, skin weights, Mixamo bone names, clips) | `python tools/bozzetto/bozzetto.py rig make <name>` (UniRig, free, your GPU; or `--with tripo`, paid) | `tools/bozzetto/README.md` "Rig a character" |
| Secondary motion: a scarf, cape, hair or tail that swings | `python tools/bozzetto/bozzetto.py rig chain <name> --part colour:#rrggbb` (Blender, free) | `tools/bozzetto/README.md` "Secondary motion" |
| Animate beyond that, retarget, creatures | Guidance and scripts | [Animation](#animation), `docs/resources/pipelines.md` |
| Paid generators (Meshy and others) | Not wired in (Tripo is: `make --with tripo`, `rig --with tripo`, `reference --with tripo`; Gemini: `reference --with nanobanana`) | `docs/resources/ai-tools.md` |
| Log and credit an asset | `/asset-intake` | Stage 7 below |
| Ask Claude for any of it | the `model-pipeline` skill | Follows this SOP |

## Honest division of labor
| Claude is good at | You still own |
|---|---|
| Blender Python (`bpy`) scripts: procedural props, modular kits, geometry nodes, shaders | Art direction, silhouette, readability, "does it look good" |
| Batch work: rename, bake, LODs, collision meshes, export presets, texture downsizing | Sculpting and hero-asset polish |
| Pipeline glue: call text or image-to-3D APIs, download, validate, convert | Retopology and cleanup of generated meshes |
| Retarget and cleanup scripts, loops, root motion, import settings | Animation timing, weight, and game feel (combat above all) |
| Validation: poly budgets, scale, pivots, naming, UV checks | Final lighting and material look |
Expect the split most reviewed videos showed (F1, grade B): static scenery looks great, the interactive parts (animation, collision, held items) break.
Skyrim-level fidelity is a team effort. Solo target: a **cohesive stylized look** from kitbashing plus procedural variation.
Tip (F13, grade C): simple stylized shapes plus good lighting beat a failed "realistic" mesh.

## Pipeline stages
1. **Style bible** in `docs/CONCEPTS.md` and the GDD art section: poly budget per class, texel density, palette, references, scale (1 unit = 1 m), axes.
2. **Source the base.** CC0 kits first (`docs/resources/art.md`). Generated meshes are drafts: log them as AI-assisted in `ASSET_LOG.md`
   with the generator plan or tier, since commercial rights can depend on it. Prompts via `/gen-brief`. On your own GPU:
   Bozzetto (next section) makes, cleans, checks and logs a mesh from a picture or a prompt.
3. **Build or modify by script.** Claude writes `tools/blender/*.py`, run headless: `blender -b --python-exit-code 1 -P tools/blender/<script>.py -- <args>`.
   Scripts take args, print what they did, are idempotent. Fix the script, never the exported mesh (F8).
   Keep `--python-exit-code 1` before `-P`: without it Blender exits 0 after a script's traceback, so a crashed run
   passes in CI or a hook; after `-P` the flag does nothing (K01, tested on Blender 5.2; E64).
4. **Validate** with `python tools/blender/validate_asset.py <file.glb> --class <prop|kit|hero|npc>` (or `--max-tris`/`--max-dim` when `ARCHITECTURE.md` overrides the budgets). Without `--class` the loose `any` preset passes over-budget assets. Runs inside Blender or with the `bpy` module (`uv run --python 3.13 --with bpy python tools/blender/validate_asset.py ...`). Fail loudly.
5. **Export** glTF 2.0 (`.glb`) by default, FBX only when the engine requires it. One export preset, never ad hoc:
   `tools/blender/prep_export.py <source> --out assets/models/<name>.glb --class <class> [--lods 0.5,0.25]` applies rotation
   and scale, puts the pivot at the bottom center, cleans names, exports with the kit's one glTF preset, writes LODs and runs
   the validator on the result (K01: exam 17/17). Keep a downloaded pack's folder layout for the source (Kenney models
   point to a colormap image in a Textures folder beside them): the tool refuses a source whose texture files are
   missing, because the export would drop the texture without a word.
6. **Import** with the engine settings in `docs/ENGINE_FLOW.md`. Check scale, materials, collision, LODs in a test level or preview scene.
7. **Log and credit** every asset (`/asset-intake`).

## Local generation: Bozzetto
`python tools/bozzetto/bozzetto.py make <name> --image <ref.png> --class <class>` (or `--prompt "..."`) runs
stages 2 to 5 and 7 on your own GPU: TRELLIS.2 4B in a local ComfyUI makes a textured mesh from one picture, then
Blender merges it, drops fragments, decimates it to the class budget, scales it to a height (prop 1 m, hero 1.8 m by
default), sets the pivot, exports it with the kit's one preset and LODs, and `validate_asset.py --class` decides
whether it reaches the game. It writes the asset log row (pre-generated AI, models, seed, prompt) and a turntable
preview; `check` says what is missing. Setup, options and limits: `tools/bozzetto/README.md`.
- What to expect (K01, a 16 GB RTX 5060 Ti): about 5 minutes per model once warm, peak about 14 GB of VRAM; props from
  a clean picture come out right, under budget, with a baked texture. The hidden sides are invented, thin parts merge
  or vanish, the UVs pass coverage but warn on texel density, characters have no rig. Treat every result as a draft.
- Give it one object, whole, on a plain background, in a three-quarter view (characters: front view, A-pose). Audition
  pictures first (`--prompt ... --reference-only`, seconds each); a 3D run costs minutes. Try two or three seeds.
- **A character starts with reference views.** A concept in a dynamic pose (arms against the body, a flying scarf)
  makes a mesh with fused arms (K01: limbs held close to the body merged or vanished) and a rig that cannot move them. `bozzetto.py reference <name> --from <concept.png>`
  (or `--prompt "..."`) redraws the same design in a relaxed A-pose, arms about 35 degrees out, hands open, flat light,
  plain light grey background, and turns it to the left, back and right; then `make <name> --image
  assets_src/bozzetto/<name>/reference/front.png --class npc`. Local is free (Qwen-Image-Edit and FLUX.2 klein through
  ComfyUI); `--with nanobanana` (Gemini) and `--with tripo` are paid: run `--quote-only`, show the price and ask
  before the real run, and keep `--max-cost` low. Look at `assets_src/bozzetto/<name>/reference/sheet.png` before any 3D run: the same costume in
  every view, a gap under each arm, nothing cut off, and left and right not swapped (the first live run's left view
  faced the wrong way; K01). Local, cold: about 7 minutes for four views; the paid routes are not yet run live.
- Licences: TRELLIS.2 and BiRefNet are MIT; DINOv3 (its image encoder) has a use-restriction list (military, weapons)
  whose reach over game props is an open question to settle before you ship such a model (`tools/bozzetto/LICENSES.md`).
  Upstream TRELLIS.2's RMBG-2.0 and nvdiffrast are non-commercial and never loaded (E147, E148, E149).
- **The Tripo route** (`make <name> --with tripo`): the Tripo3D API makes the mesh instead (`--image`, several views
  with `--front` plus `--left`/`--back`/`--right`, or `--prompt`), then the same cleanup, budget check, LODs, turntable
  and log row follow. It costs paid API credits (a Tripo Studio plan adds none): the quote is printed first,
  `--max-credits` (default 150) caps a run, and a re-run reuses the paid task. A P2 image-to-model cost 110 credits
  in the kit's test, not the 30 of the public table (E153); Tripo has no price endpoint (E160), so the other quotes
  are set to that ceiling until measured. Outputs on paid credits are the user's (Tripo terms 5.2.2, E153). Tripo
  exports facing +X (E160): Bozzetto turns its models to glTF's +Z **(verify on a live run)**; check the turntable,
  `--turn` overrides. Ask the user before every paid run.

## Claude and Blender
- Default: headless scripts in `tools/blender/`. Diffable, repeatable, reviewable.
- Optional live control: a Blender MCP server (an official Blender MCP and a Claude Blender connector were reported in the news and shown in a video, E31 and E13; community ones exist too). Record
  the exact server in an ADR, commit before big sessions, and tell Claude to **save every `bpy` script it runs into `tools/blender/`**.
  A scene that exists only in a live Blender session cannot be rebuilt.
  Both kinds run whatever code the model sends, unguarded: the official Blender Lab server says so and recommends a VM;
  the popular community server listens on plain TCP on `localhost:9876` with no authentication (E64 **(verify)** for
  your version). Development machines only, never next to secrets or client work.
- `.blend` files are binary: Git LFS. The generating scripts stay in the repo.
- Use cases reported to work through MCP (E13, unverified here), each with the check to run afterward:
| Use case | Check afterward |
|---|---|
| Bake normal and AO from high to low poly, wire into the shader | Hide the high poly, inspect shading |
| Geometry nodes scatter with a density control | Instance count, overlaps, density slider |
| LOD0/1/2 batch with texture downsizing (4K, 1K, 512) | Triangle counts, texture sizes, silhouettes |
| Procedural shaders (toon plus outline, car paint) | Node tree simplicity, performance |
| PBR materials from an AI material generator | License, tiling, scale |
| Explain someone else's node setup | Toggle nodes to confirm |

### Claude-written `bpy` scripts (tips, E64 grade C; the tested lines are K01)
- **Name the Blender version in the prompt** (it is in `docs/ENGINE.md` or `ARCHITECTURE.md`). The API keeps renaming
  things: EEVEE's engine id was `BLENDER_EEVEE_NEXT` in 4.2 to 4.5 and is `BLENDER_EEVEE` again in 5.x (K01, Blender
  5.2.2). The `bpy` wheel matches one Python version only (`uv run --python 3.13 --with bpy` above).
- **Geometry through `bpy.data` and `bmesh`, operators only when needed.** Every operator needs its own context: a
  mesh-editing one (`bpy.ops.mesh.select_all`, `subdivide`) called from object mode fails with "poll() failed, context
  is incorrect" and no hint why, and works in edit mode; `primitive_*_add` works in object mode (K01, 5.2.2).
- **Booleans:** Blender 5.2's solvers are Float, Exact (the default) and Manifold (K01). Float does not handle
  overlapping geometry and Manifold needs manifold input (E64), so keep Exact for generated meshes.
- **Units:** 1 unit = 1 m (stage 1). glTF is metres and +Y up; STL and OBJ carry no unit at all, so pass the scale when
  exporting those (E64). `primitive_cube_add()` makes a 2 m cube unless `size=` is given.
- **Measure, then look.** A render hides non-manifold edges, loose vertices, zero-area faces and self-intersections.
  `validate_asset.py` checks budgets, scale, pivots and UVs, not these; when they matter (booleans, generated meshes,
  printed parts), have the script assert on them before rendering.
- **Generate, critique, patch:** the script opens with a parameter table; a review image shows fixed views (front,
  side, top, three-quarter) side by side; a fix changes only the parameters and comes back as a diff (E64).

## UV acceptance check (tip, F12 grade C: AI unwrapping was unreliable in E14; the check is cheap)
Have Claude call Blender's own operators (Smart UV Project, then pack islands with margin), then check with numbers, not eyes alone:
| Metric | Rule of thumb |
|---|---|
| UV coverage of the 0 to 1 square | At least 60 percent for hero assets (trim sheets: judge by eye) |
| Islands | Roughly the intended seams, not hundreds of fragments |
| Texel density spread | Within about 2x between islands |
| Overlap | None, except mirrored islands on purpose |
| Stretch | Checker texture, look |
`validate_asset.py` reports coverage, island count, and missing UVs. Hand-fix hero assets.

## Vegetation and nature (tip, grade C: one creator, E03 and E04)
Reported pattern, not a rule: research species for the setting, run a model-render-improve loop on three trees as a style test, then make them game-ready: bake leaf clusters
to textured planes (leaf cards), keep trunk and main branches as geometry, reuse painted planes for grass. Numbers reported: 34k to 2.8k triangles per tree.

## Animation
- Rig: one humanoid standard compatible with your retarget source (Mixamo-style, engine humanoid, Auto-Rig Pro). Decide once, ADR it.
- Sources: hand-keyed, retargeted libraries, or mocap-from-video. Check each tool's license and output ownership **(verify)**.
  Mocap from video is a draft (tip, E63): raw output from a local video-to-Mixamo tool slid its feet and drifted at the
  root until a cleanup pass (scripted, here with an LLM) fixed them. Plan the cleanup as part of the job.
  Read the model licenses before shipping that motion: the open-source video-to-Mixamo tools (Motion2MixamoRig,
  Prompt2Rig) are Apache-2.0 themselves but download body models and weights (SMPL-X, GVHMR, MANO) that are
  non-commercial or research-only by default, per their own READMEs (E65, read 2026-10-24; licenses change: re-read). Log them in `ASSET_LOG.md`.
- Script the boring parts: retarget, trim, loop, root motion, curve cleanup, naming (`anim_run_loop`), export.
- Secondary motion, after the rig and its clips: a scarf, cape, long hair or tail that an auto-rig left stiff gets its
  own bone chain with `bozzetto.py rig chain <name> --part <selector>` (by colour, material, vertex group or a box).
  Looping clips get a sway that keeps them looping exactly (sprite cycles need that), one-shots named in `--cloth` a
  baked cloth simulation. Run it with `--no-replace` first and look at `assets_src/bozzetto/<name>/rig/chain/chain.png`; a part
  fused to the body is rebuilt as a strip, which keeps its colours, not its folds (the README lists the limits). In a
  3D engine the same bones can run on the engine's spring bones instead (`--sway 0`; README recipes: Godot's checked
  headless (K01), Unity, Unreal and the rest **(verify)**).
- Gameplay animation (attacks, dodges): timings in data first (anticipation, active, recovery frames), art polish second.
- Test in the engine with the real controller. "Looks good in Blender" is not the bar.
- Tip (E50): when the third prompt has not fixed a contact problem (feet through a footpad, an open hand on a punch, a weapon
  held wrong), stop prompting and change the setup: a socket on the hand bone for held items, IK for contacts (feet on
  pads, hands on bars), a separate hand pose or animation layer for fists, a physics asset for falls and ejections
  **(verify the engine's names: Unreal sockets and Control Rig, Unity Animation Rigging, Godot SkeletonIK3D)**. Check the
  fix from the game camera in a recorded run, not one frame in the editor.

### Creatures and non-humanoids (experimental: tips, F16 grade C)
Mixamo-style libraries fit humanoids only. One creator (E02) built a custom pipeline: two-camera motion video, a per-creature joint detector,
triangulation, retarget. Full method and the list of approaches that failed: `docs/resources/pipelines.md`. Tips if you try it (one creator's
unreplicated pipeline **(verify before adopting)**):
1. Rig decided first, ADR. One creature, one motion (a walk) before anything else.
2. Build an **exam** first (`SOP-09`): a known random legal motion rendered from the same cameras, compared bone by bone.
3. Never trust the tool's own score. E02's script said "84 percent match, all checks passed" while most frames were broken. Look side by side.
4. Log generated motion as AI-assisted. Keep scripts so animation can be regenerated.

## Export and naming
One set of export settings for every asset script, so nothing is exported ad hoc:
- glTF binary (`.glb`) unless the engine needs FBX; +Y up; apply modifiers and transforms (scale 1.0, 1 unit = 1 m); include normals, UVs and materials; animations as named actions.
- The preset lives in `tools/blender/prep_export.py` (`GLTF_PRESET`). Asset scripts call that tool instead of exporting ad hoc; change the preset there and record why in an ADR.
- Names: `prop_<thing>`, `kit_<set>_<piece>`, `chr_<name>`, `npc_<name>`, `anim_<rig>_<action>`, lowercase with underscores, matching the `--class` you validate with. The asset log row uses the same name.

## 3D source, 2D game: sprite sheets
`tools/blender/render_sprites.py <model> --out assets/art/<name>_sheet.png --directions 8 --action walk` (launched like
every Blender script, stage 3) renders a model
(and one of its animations) into a sprite sheet: rows are camera directions, columns are frames, transparent background,
the same framing and lighting in every cell, and a JSON with the layout. `--list-actions` shows the animations in the file.
Rigged glTF models come back from Blender's importer with an extra `Icosphere` (the bones' display shape, not in the file): the
kit's Blender tools remove it on import. Real helper meshes in a file (a ground plane, a proxy) can still shrink the framing:
the tool warns and `--ignore NAME` drops them (`prep_export.py` has the same option).
Tested on a Kenney CC0 character's walk cycle and by its exam (K01: 24/24). Then treat the sheet as 2D art (`SOP-16`).
For a rigged character, `--actions all --step 2 --manifest assets/dotwork/rendered.assets.json` renders every clip in
8 (or 4) directions and writes a Dotwork asset manifest that every 2D engine's Dotwork importer loads with no new code
(clips `walk_s` ... `walk_se`, per-frame durations, the feet as the pivot; K01, #290: the web, web-3d, LÖVE, C++, Bevy and MZ
importer tests load the golden character's sheet, and the LÖVE and C++ starters draw it walking; Unity's and
Unreal's importers were not run on it **(verify)**).

A rigged character in a 3D engine: the `.glb` from `bozzetto.py rig make` loads with its clips; each engine's
`docs/ENGINE.md` "Rigged characters" has the import recipe (looping, root motion, scale, facing, bone names) and a
helper that plays a clip on a loop, tested against the kit's golden character (`data/golden/character/`, K01).
Unity: import a glTF character Generic (glTFast); Humanoid was tried and plays only humanoid (FBX) clips
(`tools/bozzetto/README.md` "In the engine").

## Budgets (placeholders, set yours in `ARCHITECTURE.md`)
| Class | Triangles | Texture | Notes |
|---|---|---|---|
| Prop (small) | 500 to 3k | 512 to 1k | |
| Environment kit piece | 1k to 8k | 1k to 2k | trim sheets |
| Hero character | 20k to 60k | 2k to 4k | LODs required |
| Background NPC | 5k to 15k | 1k to 2k | |

## Lighting and post-processing (standard practice)
- Light the gameplay first: the player, the path and the threats read at a glance; then mood. Bake what does not move
  (lightmaps, light probes) and keep dynamic shadows for what does; every dynamic light with shadows is a frame-time cost
  (measure it, SOP-10).
- Post-processing stack: tone mapping and exposure first, then color grading, then ambient occlusion, bloom and depth of
  field only where they help. Motion blur, camera shake, film grain and chromatic aberration each get an off switch
  (SOP-20, F33).
- Test the lowest target hardware with the full stack on, and give quality presets (low, medium, high) in the settings.

## Done when
- The asset passes `validate_asset.py --class <its class>`, imports at the right scale with materials, has LODs and collision where needed, is logged, and holds the frame budget in the target scene.

## Common mistakes
- Trusting a generated mesh or AI UVs as final.
- Mixed scales and pivots across kits.
- Hand-fixing the exported file instead of the script.
- Judging animation in Blender instead of in the game. Foot sliding left uncleaned.
