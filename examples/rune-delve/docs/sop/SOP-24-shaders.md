# SOP-24: Shaders

## Goal
Effects that run on the GPU (a hit flash, a dissolve, an outline, palette swaps, colour-blind and CRT filters, toon
shading, scrolling water, triplanar mapping, lit sprites) look the same in every engine, are checked by a test that can
fail, and never become a pile of one-off shader files nobody can change. The kit ships them as recipes: one engine-free
definition per effect, a reference renderer, a golden image, and a port per engine that is compared with it.

Run it with `/shader`.

## 1. Use a recipe before writing a shader
The recipes live in `tools/shaders/`: `recipes.json` (each effect's inputs, parameters and tolerance), `ksl/<name>.ksl`
(the body, in a small GLSL subset), `shader_ref.py` (a standard-library Python renderer, the reference) and the golden
images in `data/golden/shaders/`. `python tools/shaders/shader_ref.py list` prints them. Each engine's port is
generated from the same body by `tools/shaders/shader_gen.py` into the engine's folder (the engine's ENGINE.md says
where and how to use it). A new effect starts as a question: can a recipe with other parameters do it (a red flash is
`flash` with `flash_color`; a slower dissolve is a tween)? Most can.

| Group | Recipes | Typical use |
|---|---|---|
| Sprite | `flash`, `dissolve`, `outline`, `palette_swap` | Hit feedback, defeat and spawn, selection, team colours |
| Screen (post) | `colorblind`, `crt`, `vignette` | Accessibility filter (SOP-20), retro look, focus |
| Surface | `toon_rim`, `scroll_water`, `triplanar` | 3D characters, water and lava, generated models with poor UVs |
| Lighting | `sprite_light` | 2D sprites lit with the normal maps Dotwork and PixelLab make (SOP-16) |

## 2. Changing or adding a recipe (reference first)
1. Change the reference: `ksl/<name>.ksl` and its entry in `recipes.json`, then `python tools/shaders/shader_ref.py
   golden --write` and look at the new picture in `data/golden/shaders/`.
2. Regenerate the port: `python tools/shaders/shader_gen.py` (your engine, from `.game-kit.json`). Never edit the
   generated files: the next run overwrites them, and `dev.py check` fails while they differ from the recipes.
3. `python tools/dev.py check` (compiles the shaders with the engine's own compiler; Bevy compiles them only in
   `smoke`, so its `check` checks the files) and
   `python tools/dev.py smoke --shaders` (draws every recipe on the GPU and compares it with its golden image).
4. Keep the check parameters off texel edges: a sample that lands exactly between two texels is a coin toss in float
   rounding, and GPUs toss differently (a triplanar scale of 2.0 put every sample on one edge and failed on WebGL;
   1.9 passes everywhere, K01).

A recipe body uses only what every engine has: `SAMPLE_MAIN(p)` and `SAMPLE_AUX(p)` in image space (origin top-left,
0 to 1), `u_<name>` parameters (float, vec2, vec3), `u_canvas` and `u_texel`, and plain arithmetic. No derivatives, no
loops with a variable count, no texture arrays: those differ between GLSL ES 1.00, HLSL, WGSL and WESL.

## 3. How the ports are checked (A)
Every port draws the same 64 x 64 check picture from the same inputs (`data/shaders/inputs/`) and parameters, and
`shader_ref.py compare` allows a small difference per channel plus a share of pixels past it (GPUs round `sin`, `pow`
and `normalize` differently). On the kit's test machine all eleven recipes matched in all nine engines (K01, the
README's "What was tested" table lists versions and graphics APIs). What each engine needed:
- **Godot, web (Phaser), web-3d (Three.js), RPG Maker MZ (PIXI), LÖVE:** GLSL. The web pages and MZ's PIXI emulation
  run in headless Chromium; Godot and LÖVE need a window (headless Godot and LÖVE have no renderer).
- **Unity:** unlit passes with no `LightMode` tag, which the Built-in pipeline and URP both draw (URP as
  `SRPDefaultUnlit`; K01: Built-in and URP 17.6, through a Blit and through a URP camera). HDRP is not checked.
- **Unreal:** a material per recipe around a Custom node. The pythonscript commandlet runs on the Null RHI, so the
  check starts the full editor off-screen (`-ExecCmds=py ...`; `-ExecutePythonScript` quit before the materials
  compiled, K01).
- **Bevy 0.20:** WESL, not naga_oil WGSL: imports end with `;` and come first, the bind group is
  `constants::MATERIAL_BIND_GROUP` (E156). A typed `Material2d` per recipe; Bevy compiles WESL only when it builds a
  pipeline, so `check` checks the files and `smoke --shaders` compiles and renders them.
- **C++ (SDL3):** custom render states on SDL's GPU renderer, compiled to SPIR-V, DXIL and MSL by shadercross (E155).
  Keep each recipe's shader for the renderer's life: SDL 3.4.12 caches pipelines by shader address (E155, K01).

## 4. Rules that protect players (A)
- Full-screen effects that flash or pulse (a flash on a whole-screen post effect, a CRT flicker) go through the juice
  module's flash limiter (SOP-18 step 3, SOP-20).
- The colour-blind filter is an option, never a fix: information still needs a shape, icon or label (SOP-20). Its
  matrices follow the widely used daltonize code credited to Fidaner, Lin and Ozguven **(verify against their paper
  before claiming accuracy)**.
- Reduce motion turns off `scroll_water` waves and `crt` flicker you add on top (SOP-20).

## Engine notes
Each engine's ENGINE.md (the "Shaders" note) gives the engine's file names, how to apply a recipe to a sprite or a
mesh, how to set a parameter, and how post effects attach. The parameter `u_texel` is one over the picture's size in
texels in every engine; `u_canvas` is the size pixel parameters such as `light_pos` are given in.

## Done when
- The effect is a recipe (or a recipe with other parameters), not a hand-written engine shader.
- `python tools/dev.py check` and `python tools/dev.py smoke --shaders` pass on the machine that ships the game.
- A changed recipe changed the reference and its golden image first, in the same commit.

## Common mistakes
- Editing a generated shader file instead of the `.ksl` (the next `shader_gen.py` run reverts it; `check` fails first).
- Updating the golden image to make a port pass. The reference decides; a port that differs is the bug.
- A sprite sheet sampled with linear filtering: the recipes expect nearest (pixel art blurs, and texel-exact effects
  such as `outline` and `palette_swap` break).
- One material or shader instance shared by every sprite, so one hit flashes them all (give each its own instance).
- A check parameter that lands on a texel edge (step 2.4).
