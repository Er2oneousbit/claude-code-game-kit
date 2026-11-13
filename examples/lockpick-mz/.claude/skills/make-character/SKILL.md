---
name: make-character
description: Take a character from "the main character should look like this" (an idea, a sentence or a picture) to that character moving in the game, with Bozzetto - model-ready reference views, a 3D model, a rig with clips, a swinging scarf, cape or tail, then the 3D engine's import or 8- or 4-direction sprite sheets for a 2D engine. Asks one multiple-choice question at a time, stops for the user's look and yes at every step, and quotes and asks before anything paid (Nano Banana, Tripo). Use when the user describes or shows how a character should look, says "make the hero look like this", "turn this drawing into my character", or wants a generated character in the game. Follows SOP-11.
---

# Make a character

Bozzetto (`tools/bozzetto/`) does every step; Claude asks, runs the commands, looks first, then shows the user and
waits. Read `tools/bozzetto/README.md` (setup, "Reference views", "Make a model", "Rig a character", "Secondary
motion", "In the engine") and `docs/sop/SOP-11-3d-pipeline.md` "Local generation" before the first run. A worked run
with real times is in the kit's `workflows/make-character/`.

**Ground rules**
- **One question at a time.** Use the multiple-choice prompt (AskUserQuestion) when your tools have it: 2 to 4 short
  options fitted to the answers so far, one marked "(Recommended)" with a reason, "Q2 of 6" in the question. Never a
  batch of text questions. Without the prompt, one question per message with two or three examples.
- **Every look is a gate.** After each step: look at the picture yourself first, then post a clickable link to it,
  say in a line or two what is right and what is wrong, and ask: go on, change something, or try again (another
  seed). Do not run the next step without a yes. Six gates: the concept, the reference views, the turntable,
  `clips.png`, `chain.png`, the character in the game.
- **Paid steps: quote, then an explicit yes, every time.** Print the quote first: run the exact paid command with
  `--quote-only` added (`reference`, `make --with tripo` and `rig make --with tripo` all have it; it needs no key,
  calls nothing and writes nothing, and says 0 when the journal already holds the paid task). Show its `[quote]` line
  as it is, with its "measured" or "(verify)" note, then run the real command with `--max-credits` (or `--max-cost`)
  at the quoted amount, since a quote over the cap stops before any upload. A yes to one paid step is not a yes to
  the next. Keys (`GEMINI_API_KEY`, `TRIPO_API_KEY`) come from the environment: never ask for one in chat, never read,
  print or write one; a missing key is the user's to set. A free-tier Google key cannot make images (the run says so):
  Nano Banana needs a project with billing on.
- **Tier first.** In a toy, characters are drawn in code (CLAUDE.md "crude on purpose"). If the GDD's
  `Current tier:` is Toy, say so and ask before spending GPU time or money on a generated character.
- **No look-alikes.** Nothing that copies a famous character, a named artist or a real person; no weapon without
  asking (the DINOv3 licence question in `tools/bozzetto/LICENSES.md` is the user's call).

## 0. Read the situation (no questions yet)
- The engine: `"engine"` in `.game-kit.json`. web-3d and unreal: 3D. web, love2d, cpp-sdl2, rpgmaker-mz: 2D (sprite
  sheets). godot, unity, bevy: either; the GDD's `**Perspective:**` line decides.
- The look: GDD "Art and audio direction", the style fragments in `docs/BRIEFS.md`, `docs/CONCEPTS.md`.
- The machine: `python tools/bozzetto/bozzetto.py check` and `python tools/bozzetto/bozzetto.py rig check`. They say
  which routes are ready (GPU, ComfyUI, model files, UniRig; a key is reported set or not, never shown). Only offer
  routes that are ready, and say in plain words what the others would need.

## 1. Questions (one at a time, skip what is already known)
1. What do you have? An idea in a few words / a full description / a picture (its path; ask whether it is theirs to
   use) / "you decide" (offer three short ideas that fit the GDD).
2. Free or paid? All on this computer, free (Recommended when `check` is ready) / paid where it helps (pictures:
   Nano Banana or Tripo; model and rig: Tripo; no GPU needed) / decide at each step (ask again before that step).
3. Which class? `hero` (the main character: up to 60k triangles, 2048 textures, two LODs) / `npc` (background
   characters: up to 15k, 1024).
4. 3D or sprites? Only when step 0 left it open.
5. 2D only: 8 directions (Recommended for top-down) or 4; which clips (`idle`, `walk`, `wave` from UniRig; up to five
   of Tripo's presets on the paid rig).
The part that should swing (scarf, cape, tail, long hair) is asked at step 6, once the model can be seen.

## 2. Gate 1: the concept
- From an idea: write a short description in the GDD's style (chunky shapes, colours, outfit; one colour used only
  on the part that should swing makes step 6 easy; arms and legs apart, nothing thin; no weapon). Show it and get a
  yes. Then draw just the front, in seconds:
  `python tools/bozzetto/bozzetto.py reference <name> --prompt "<description>" --views front --seed N`; show
  `assets_src/bozzetto/<name>/reference/front.png`; another seed (`--overwrite --seed M`) until the user likes one.
- From a picture: it is the concept; step 3 re-poses it (`--from`).

## 3. Gate 2: the reference views
`python tools/bozzetto/bozzetto.py reference <name> --prompt "..." --seed N --overwrite` (or `--from <picture>`).
Paid: the same with `--with nanobanana` or `--with tripo` and `--quote-only` first; then the run with `--max-cost` at
the quote. Show `assets_src/bozzetto/<name>/reference/sheet.png` and the `[look]` lines, and check by eye:
- the same costume in every view; a gap under each arm; nothing cut off;
- **left and right**: `left.png` faces the picture's left edge. Swapped (both of the kit's live local runs so far were):
  `python tools/bozzetto/bozzetto.py reference <name> --swap-sides` (no GPU, no cost; sheet, record and log follow);
- loose cloth: "hang down" can turn a flying scarf into a cape or another garment. Say so if it did.

## 4. Gate 3: the model and its turntable
`python tools/bozzetto/bozzetto.py make <name> --image assets_src/bozzetto/<name>/reference/front.png --class <class>
--seed N` (about 5 minutes warm), or paid: the same `make <name> --with tripo --class <class> --front ... --left ...
--back ... --right ...` with `--quote-only` first, then after the user's yes with `--max-credits <quote>` (a P2 model
from one picture or from views cost 110 credits on the kit's live runs). Show
`assets_src/bozzetto/<name>/turntable.png` and the validator warnings. Both routes rebake an atlas under the class's UV
coverage floor on their own (a fresh layout, the textures baked onto it, checked: Tripo always, the local route only
under the floor); still under it (a 120-part character reached 46% of the hero's 60%), say so and offer `--accept-uv` (the waiver
goes on the asset log row; the paid Tripo task is reused) or `--material vertex` on the local route (flat colours,
no bake). Facing wrong (rig refuses it, or the turntable's first view is not the front): `--turn`.

## 5. Gate 4: the rig and its clips
**Stop ComfyUI first** if it is running (and say so): UniRig peaks near 15.6 GB and ran six times slower sharing the
card. `python tools/bozzetto/bozzetto.py rig make <name>` (UniRig, free; about 3 minutes, more on the first run while
it downloads its weights), or `--with tripo --clips idle,walk --quote-only` first and, after a yes, the same with
`--max-credits <quote>` (25 credits to rig and 10 a clip, measured on the kit's live runs). Show `assets_src/bozzetto/<name>/rig/<route>/clips.png`: arms swing from the
shoulders, nothing tears, the legs walk.

## 6. Gate 5: the part that swings
Ask which part should swing (or none). Pick it by its colour: `python tools/bozzetto/bozzetto.py rig chain <name>
--part scarf=colour:#rrggbb --no-replace` (Blender, free, seconds); show
`assets_src/bozzetto/<name>/rig/chain/chain.png` (it looks from the side the part hangs on) and read the report's
`length_m` against the turntable:
- "is a lump": the selection is the part wrapped round the neck. Add a box for the hanging part only
  (`colour:#rrggbb~0.3&box:x0,y0,z0,x1,y1,z1`, metres, Y up, the character faces +Z, its left is +X).
- much shorter than the part: a baked texture's shading breaks the colour into pieces; raise the tolerance (`~0.3`).
- two tails (a scarf's two ends): one `--part` each, split by the box (`scarf_l=...&box:0,...` and `scarf_r=...`).
When the report says **rebuilt as a strip**, say what that means (colours kept; folds, fringes, knots and a pattern on
its back are not; the original paint stays on the body behind it). Then run it without `--no-replace`. In a 3D engine
the engine's spring bones can drive the chain instead (`--sway 0`; README recipes).

## 7. Gate 6: in the game
- **3D**: the rigged `<name>_rigged.glb` through the engine's helper (`docs/ENGINE.md` "Rigged characters"): Godot
  `KitCharacter.load_scene(...)` and `KitCharacter.play(hero, "walk")`; Unity `KitCharacter` (glTFast, Generic);
  Unreal `kit_character.import_character(...)` through `dev.py exec`; Bevy `spawn_character(...)`; web-3d
  `loadCharacter(...)`. Put it where the game uses it (the player), or in a preview scene the user can delete later.
- **2D**: `blender -b --python-exit-code 1 -P tools/blender/render_sprites.py -- <models>/<name>_rigged.glb --out
  assets/art/characters/<name>/<name>.png --actions all --step 2 --directions 8 --size 96 --manifest
  assets/dotwork/<name>.assets.json --name <name>` (Blender on the CPU, about 1.5 minutes for three clips; the
  `<models>` folder and the Blender path as SOP-11 says); then the engine's Dotwork importer (`/dotwork` step 8). The
  LÖVE and C++ starters draw the first manifest character walking with no new code. Show one sheet first. A 2D
  **Godot** game has no manifest importer (Godot loads Dotwork's own resources): use the sheets with the layout
  `.json` written next to each (`AtlasTexture` regions into a `SpriteFrames`, the pivot as the sprite's offset) and
  say so; nothing in the kit does that step for Godot yet.
- Capture as CLAUDE.md "While building" says: `python tools/dev.py smoke --screenshot
  captures/progress/<NN>-<name>.png`, or for the walk `smoke --record captures/frames-<NN>` and
  `tools/art/frames_to_gif.py`. Look at it first, then post the link and ask for the last yes. Run `check` and
  `test` (and `smoke`) as for any change.

## 8. Log and terms
Every step writes its own `docs/ASSET_LOG.md` row or note: reference views (`art`, the route's terms), the model
(models and licences, or Tripo's terms and credits), the rig ("rig of A-NNNN"), the chain (a note on the rig's row).
Read them back to the user: route, cost, who owns the output (yours on paid Tripo credits, Tripo terms 5.2.2; Gemini
pictures carry a SynthID watermark **(verify)**). `render_sprites.py` writes no row: log the sheets with
`/asset-intake` as made from the model's row. Mark everything AI-assisted.

## Say plainly what a generated character gets wrong
- The back and the hidden sides are invented from one front picture; small details (buttons, badges, a belt buckle)
  blur or vanish; colours drift darker.
- Thin parts (straps, fingers, a brim) merge or disappear; arms held close to the body fuse to it.
- Loose cloth: a scarf can come back as a cape; a part fused to the body is rebuilt as a plain strip.
- The clips are game-jam quality (no foot planting); UniRig's fingers stay stiff; a long coat or anything hanging
  past the hips is skinned to the legs and stretches when they step.
- Where it matters (a hero seen up close, a cut scene, a signature silhouette), a human artist pass on the model, the
  UVs and the animation is the real fix (SOP-11 "Honest division of labor").
