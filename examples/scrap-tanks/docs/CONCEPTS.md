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
| Ground | Scrapyard green | as rendered | Tower Defense Kit tile, seen from above |
| Player | Hazard yellow | as rendered | Car Kit tractor |
| Raiders | Police white and blue | as rendered | Car Kit police tractor; the heavy is the green shovel tractor |
| Intent: attack | Alarm red | `#ff4d4d` | FIRE, FLANK labels |
| Intent: defend | Steel blue | `#7fb2ff` | COVER, RETREAT labels |
| UI | Paper white | `#fbf7ee` | HUD text on ink `#1d2433` |

## Board
| ID | Scene / asset | Direction (1 line) | Final version | Status | Drift notes / pending fixes | Used by (scene, prefab, asset ID) |
|---|---|---|---|---|---|---|
| C-0001 | Whole game look | Kenney 3D kits rendered to sprites at 55 degrees by tools/make_sprites.py; one screen, toy proportions (turrets 1.8x, cover 2.25x) | v1 | FINAL | none yet | all, A-0001, A-0002 |

## Version log
| ID | Version | Date | Tool and prompt (or Prompt Library ID) | What changed | Drift found? |
|---|---|---|---|---|---|
| C-0001 | v1 | 2026-10-21 | No generator: the Kenney packs rendered with the kit's render_sprites.py | first version | no |
