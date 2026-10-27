# ADR 0003: Content from a headless Python script, the level from C++ data

- Status: accepted
- Date: 2026-10-22

## Context
Unreal content (`.uasset`, `.umap`) is binary and normally made in the editor. The kit forbids hand-editing it, and this
example uses no editor UI. The kit's Unreal `dev.py` had no way to run editor code headless (kit gap R1, now `dev.py exec`).

## Options considered
1. **Editor Python, headless** (`dev.py exec tools/unreal/build_content.py`, the `pythonscript` commandlet): import every
   Kenney FBX and OGG through Interchange, make a map holding only a PlayerStart and the NavMesh bounds; the game builds
   rooms, props, lights and characters from `RDLevel` at runtime.
2. **Build the whole level into the map** from the same script (static meshes placed in the editor world).
3. **An Unreal MCP plugin** driving a running editor.

## Decision
Option 1. The level data lives in one C++ file that the tests read too (rooms, gates, spawns), so the map cannot drift
from the rules. The script is re-runnable: imports replace older assets.

## Consequences
- Good: `Content/` is reproducible from `assets_src/` plus one script; no LFS-heavy hand-made assets; the first import of
  120 assets takes about 15 seconds.
- Bad / costs: assets are loaded by path at runtime, so `Config/DefaultGame.ini` must always cook `/Game/Art` and
  `/Game/Audio`; lighting is dynamic (no baked lightmaps).
- What we would need to see to revisit this: art that needs hand placement (then a map made in the editor, with the
  gameplay data still in C++).
