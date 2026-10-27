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
| Sky | Morning blue | `#9fd3f0` | Background and fog |
| Ground | Lawn green | `#7cc36b` | Ground plane between roads |
| Roads | Kenney asphalt | as shipped | City Kit Roads colormap |
| Robot calm | Patrol cyan | `#59d8ff` | State light while patrolling or returning |
| Robot alert | Warning amber | `#ffb020` | Alert and search; the "!" tell |
| Robot chase | Alarm red | `#ff3b3b` | Chasing |
| UI | Paper white | `#fbf7ee` | HUD text on a translucent ink panel `#1d2433` |

## Board
| ID | Scene / asset | Direction (1 line) | Final version | Status | Drift notes / pending fixes | Used by (scene, prefab, asset ID) |
|---|---|---|---|---|---|---|
| C-0001 | Whole game look | Kenney toy town: suburban houses, road tiles, mini characters, space-kit rover as the robot, under a fixed high camera | v1 | FINAL | none yet | all scenes, A-0001 to A-0006 |

## Version log
| ID | Version | Date | Tool and prompt (or Prompt Library ID) | What changed | Drift found? |
|---|---|---|---|---|---|
| C-0001 | v1 | 2026-10-21 | No generator: locked to the Kenney pack previews (kenney.nl pages of A-0001 to A-0004, A-0006) | first version | no |
