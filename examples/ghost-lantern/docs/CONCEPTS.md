# Concept Board

> Lock one FINAL concept per scene or asset, and log what changed in each version. Inspired by a concept-board workspace seen in a
> video screenshot. Fed back into `docs/BRIEFS.md` style fragments.

## Rules
- One row per scene/asset. Exactly one version is marked FINAL. FINAL images live in the repo (LFS) under `docs/concepts/final/`, outside the engine's content folder, so they never ship
  in a build or get imported by the engine (the same images inside Godot's or Unity's asset tree would).
- Every version records the prompt, tool, and what changed from the last version.
- Drift check on every new version: palette, faction colors, proportions, camera angle, UI style. Note drift and the planned fix.
- Anything built from a concept references its row ID, so art and game stay in sync.

## Color bible
Palette with names and hex per role (ground, sky, light, danger, UI, each faction). If your mood reference is daylight and the game is night, write the translated colors here. Nothing visual ships outside it. See `docs/sop/SOP-12-job-plan-and-model-roles.md`.

| Role | Name | Hex | Notes |
|---|---|---|---|
| Darkness | Crypt black | `#0b0b14` | Everything outside the lantern; never pure black |
| Floor (lit) | Sandstone | `#e8a165` | Kenney Tiny Dungeon floor, as shipped |
| Walls | Slate brick | `#6f86a8` | Kenney Tiny Dungeon wall, as shipped |
| Light | Lantern amber | `#ffd27a` | Lantern glow and the oil meter |
| Danger | Ghost cyan | `#7fe6ff` | Ghost tint when chasing; calm ghosts stay white |
| UI | Parchment | `#f4ecd8` | Text, with a crypt-black outline |

## Board
| ID | Scene / asset | Direction (1 line) | Final version | Status | Drift notes / pending fixes | Used by (scene, prefab, asset ID) |
|---|---|---|---|---|---|---|
| C-0001 | Whole game look | Kenney Tiny Dungeon, 16 px, shown 3x; darkness overlay with an amber lantern circle | v1 | FINAL | none yet | all scenes, A-0001 |

## Version log
| ID | Version | Date | Tool and prompt (or Prompt Library ID) | What changed | Drift found? |
|---|---|---|---|---|---|
| C-0001 | v1 | 2026-10-21 | No generator: locked to the Kenney pack preview (`docs/concepts/final/Preview.png`, A-0002) | first version | no |
