---
name: model-pipeline
description: Create, convert, validate, or animate 3D assets with Blender scripting and generation services. Use when the user wants 3D models, props, environment kits, characters, rigs, animations, retargeting, LODs, or asks how to make assets look better. Follows SOP-11 and is honest about what needs a human artist.
---

# 3D model and animation pipeline

Follow `docs/sop/SOP-11-3d-pipeline.md`. Asset sources: `docs/resources/art.md`; AI 3D tools: `docs/resources/ai-tools.md`; creature motion: `docs/resources/pipelines.md`.

1. **Clarify the target:** asset class, style references, poly and texture budget, rig type, engine import path. Read the Art direction section of `docs/GDD.md`. If a style bible is missing, propose one first.
2. **Be upfront** about what Claude can deliver for this request (script, procedural result, pipeline glue) vs what needs a human pass (hero sculpt, retopo, animation polish). Do not promise AAA fidelity.
3. **Check tools:** is Blender available: `BLENDER_BIN` env var, then `blender` on PATH, then the default install (Windows `C:\Program Files\Blender Foundation\Blender <ver>\blender.exe`, macOS `/Applications/Blender.app/Contents/MacOS/Blender`). Without Blender, the bpy module works for scripts and validation: `uv run --python 3.13 --with bpy python tools/blender/<name>.py`. Also: is a Blender MCP available, are generation service keys configured (never read or print keys). Say what is missing.
4. **Prefer scripts:** write `tools/blender/<name>.py` with `argparse` after `--`, a header and footer per `docs/STYLE.md`, error handling, a `--debug` flag, and idempotent behavior. Run headless: `<blender> -b --python-exit-code 1 -P tools/blender/<name>.py -- <args>` (or the bpy-module form above). Prompts for generation services come from `/gen-brief`.
5. **Validate** with `tools/blender/validate_asset.py <file> --class <prop|kit|hero|npc>` (or `--max-tris`/`--max-dim` when ARCHITECTURE.md overrides budgets). Without `--class` the loose `any` preset lets over-budget assets pass. Report numbers, not vibes.
6. **Export** with `tools/blender/prep_export.py <source> --out <assets>/<name>.glb --class <class>` (one preset, pivot, LODs with `--lods`, validation built in). FBX only if the engine needs it.
6b. **2D game, 3D source:** `tools/blender/render_sprites.py <model> --out <sheet.png> --directions 8 --action <name>` (see SOP-11 "sprite sheets", then SOP-16).
7. **Engine check:** import into a test level per `docs/ENGINE_FLOW.md`, verify scale, materials, collision, LODs. Ask the user to confirm the look.
8. **Log it** with `/asset-intake`, marking AI-assisted or third-party content, and keep the generating script in the repo.
9. **Animation:** retarget or author per SOP-11. Script loop cleanup, root motion, foot-slide checks. Gameplay timings come from data first.

Label any tool, API, or Blender function claim **verified** or **unverified**. Blender's Python API changes between versions, so confirm against the installed version.
