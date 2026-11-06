---
name: shader
description: Add, apply or change a GPU effect (hit flash, dissolve, outline, palette swap, colour-blind filter, CRT scanlines, vignette, toon shading with rim light, scrolling water, triplanar mapping, normal-mapped sprite lighting) through the kit's shader recipes, so it looks the same in every engine and a test checks it. Use when the user asks for a shader, an effect on a sprite or the screen, a material look, or says an effect looks wrong in one engine. Follows SOP-24.
---

# Shader

Follow `docs/sop/SOP-24-shaders.md`.

1. **Find the recipe:** `python tools/shaders/shader_ref.py list`. Most asks are an existing recipe, or one with other
   parameters (a red flash, a thicker dissolve band). Say which, and what each parameter does (`recipes.json` summary).
2. **Apply it in the engine:** the engine's ENGINE.md (under docs) names the generated files and shows how to put a
   recipe on a sprite, a mesh or the whole screen and how to set or tween a parameter. Give each sprite its own
   material or instance. Pixel art wants nearest filtering. Full-screen flashes go through the flash limiter (SOP-18).
3. **New or changed recipe (reference first):** edit `tools/shaders/ksl/<name>.ksl` and `recipes.json`, run
   `python tools/shaders/shader_ref.py golden --write` and show the user the new picture in
   `data/golden/shaders/`; then `python tools/shaders/shader_gen.py`. Never hand-edit a generated file, and never
   rewrite a golden image to make a port pass.
4. **Prove it:** `python tools/dev.py check` (the engine compiles every recipe) and
   `python tools/dev.py smoke --shaders` (each drawn on the GPU and compared with its golden image). Then a capture of
   the effect in the game (`smoke --screenshot` or `--record`), looked at before posting.
5. **Report:** the recipe and parameters used, where they are set in the game, the check results, and anything
   marked (verify) for this engine in its ENGINE.md.
