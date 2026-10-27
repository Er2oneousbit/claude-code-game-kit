# SOP-11: 3D Models and Animation Pipeline

## Goal
Consistent, engine-ready 3D content, with Claude doing scripting and automation and a human making the judgment calls.

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
   with the generator plan or tier, since commercial rights can depend on it. Prompts via `/gen-brief`.
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

## Budgets (placeholders, set yours in `ARCHITECTURE.md`)
| Class | Triangles | Texture | Notes |
|---|---|---|---|
| Prop (small) | 500 to 3k | 512 to 1k | |
| Environment kit piece | 1k to 8k | 1k to 2k | trim sheets |
| Hero character | 20k to 60k | 2k to 4k | LODs required |
| Background NPC | 5k to 15k | 1k to 2k | |

## Done when
- The asset passes `validate_asset.py --class <its class>`, imports at the right scale with materials, has LODs and collision where needed, is logged, and holds the frame budget in the target scene.

## Common mistakes
- Trusting a generated mesh or AI UVs as final.
- Mixed scales and pivots across kits.
- Hand-fixing the exported file instead of the script.
- Judging animation in Blender instead of in the game. Foot sliding left uncleaned.
