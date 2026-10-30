---
name: dotwork
description: Make the game's pixel art on the owner's own GPU with Dotwork (tools/art/dotwork/, local AI through ComfyUI): characters with 4-direction animations, props with collision, terrain and maps from text, effects, enemies, battle backgrounds, icons, portraits, fonts and UI. Use when the GDD's art source is Dotwork, or the user says "Dotwork", "make pixel art locally", "generate sprites/tiles/effects on my GPU", or wants AI art without a paid service. Godot gets ready-made resources; other engines get PNGs, sheets and a manifest. Not for 3D (/model-pipeline) or paid services (/gen-brief).
---

# Dotwork: local pixel art

Dotwork turns a JSON spec into game-ready pixel art on this machine. Claude writes the specs, runs the tool, reviews
every result by eye and logs what ships; the models only draw. Read `tools/art/dotwork/README.md` (setup, every lane
and its keys, limits) and SOP-16 "Generating pixel art locally" before the first run.

1. **Check the tier.** The toy is built with code-drawn art (`tools/art/pixel_sprite.py`); real art waits until the
   fun is proven (GDD "Current tier"). If the game is still a toy, say so and ask before spending GPU time on art.
2. **Check the machine.** `python tools/art/dotwork/dotwork.py setup --check`. Explain each `[FAIL]` line in plain
   words. Dotwork needs an NVIDIA GPU (8 GB for sprites, 16 GB for rotation and animation), ComfyUI, two reviewed node
   packs and 15 to 78 GB of models, depending on the tier. **Never download a model, install a node pack or install
   ComfyUI without a clear yes for that item.** Node packs are untrusted code: review them as SOP-16 says. ComfyUI
   stays on 127.0.0.1. No GPU or too little memory: say so and offer the other art routes (GDD "Art source").
3. **First run, no GPU:** `python tools/art/dotwork/dotwork.py pack --spec tools/art/dotwork/examples/ui.json`
   (needs `GODOT_BIN`, or add `--engine none` on another engine). It proves the folder layout, the Godot import and the
   asset log in seconds.
4. **Write a spec from the plan.** Read GDD "Art and audio direction" and the style fragments in `docs/BRIEFS.md`
   (fill them first if blank, as `/gen-brief` does). Start from the closest file in `tools/art/dotwork/examples/` and
   save the game's spec as `assets_src/specs/<pack>.json`. Start small: one prop, one character, one tile set, then grow.
   Prompts describe the subject only; Dotwork adds the pixel-art wording. No named artists, franchises or real people.
5. **Style references (optional).** For a set that reads as one game, list 3 or 4 of the game's own finished sprites
   in `style_refs` (in dotwork.config.json under `art_src/dotwork/`, copied from `tools/art/dotwork/config.example.json`). Only sprites the owner has the rights to. A reference can
   change the subject as well as the style: check every sprite made with one.
6. **Say the cost in time before a long run.** About 16 s per sprite, 2 min per rotation, 2 min per animation clip,
   about 20 min for a character with three actions (one tested machine). Run big packs in the background.
7. **Review before anything ships.** Open the review sheets under `assets_src/` and look at them yourself, then show
   the owner. Typical faults: a character turning toward the camera, faces on back views, background left around a
   sprite, a tile edge repeating, a cropped figure. Fix one clip at a time (`character --fix CLIP:seed=N`), or render
   takes side by side and pick one (`audition`, then `--promote`). Hand polish goes through `dotwork.py aseprite`.
8. **Prove it in the game.** `pack` ends with `verify` (every asset loads, then the game's smoke). On other engines,
   import the PNGs and sheets as `docs/ENGINE.md` says and run `python tools/dev.py smoke`.
9. **Log it.** `python tools/art/dotwork/dotwork.py log --pack NAME --dry-run`, check the row, then run it without
   `--dry-run`. It writes the `ASSET_LOG.md` row (models and their licenses, `pre-generated` or `no`) and the evidence
   file. Save prompts that worked in the Prompt Library in `docs/BRIEFS.md`.

Rules:
- Never read or print API keys or `.env` files. Dotwork needs none.
- Dotwork's work folder `art_src/dotwork/` stays out of git (it writes its own `.gitignore`); ship only `assets/` and
  the sources under `assets_src/`.
- Every model file must match `tools/art/dotwork/models.lock.json` (`setup --check --hash`). A file with the right name
  from another repository can carry another license (SOP-16).
- Stores ask about AI-made assets: the log rows are the record (SOP-04).
