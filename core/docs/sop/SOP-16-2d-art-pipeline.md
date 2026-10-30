# SOP-16: 2D art pipeline (GIMP, Inkscape, sprite sheets)

## Goal
Every 2D asset in the game is exported from a kept source file by a repeatable command, at the right size, with the
right edges (crisp for pixel art, smooth for painted art), and logged. Nobody hand-exports "final_final2.png".

## Folders
| Folder | Holds | In git |
|---|---|---|
| `assets_src/` (or `art_src/`) | Sources: `.xcf` (GIMP), `.svg` (Inkscape), `.kra`, `.aseprite`, `.psd`, `.blend` | Yes (LFS for big binaries, SOP-05) |
| The engine's assets folder (`docs/ENGINE.md`) | Exports the game loads: `.png`, sprite sheets, atlases | Yes |
Exports are rebuilt from sources by the commands below. Fix the source, then re-export; never paint on an export.
The tools refuse to replace an existing output: add `--overwrite` when you re-export on purpose.

## Which tool for which job
| Job | Tool | Command |
|---|---|---|
| Vector UI, icons, logos, clean characters at several sizes | Inkscape | `python tools/art/svg_export.py ui/icons.svg --out <assets>/ui --id "icon_*" --size 32 --size 64` |
| Layered paintings and pixel art to game PNGs, batch resize, palette reduction | GIMP 3 | `python tools/art/gimp_batch.py assets_src/sprites --out <assets>/art --interpolation none` |
| AI images on a magenta background to transparent PNGs | Pillow | `python tools/art/chroma_key.py <in> --out <assets>/art --despill` |
| **First art: characters and props drawn in code** (pixel art with outline, shading, walk and action frames; the floor every first build meets) | Python | `python tools/art/pixel_sprite.py build assets_src/sprites/hero.py --out <assets>/art/hero` (each character drawn new from the GDD; `pixel_sprite.py example` shows the technique only; `check` grades any atlas) |
| 3D model or animation to a sprite sheet | Blender | `blender -b --python-exit-code 1 -P tools/blender/render_sprites.py -- <model> --out <sheet.png> --directions 8 --action walk` (or the `bpy` module, SOP-11) |
| A recording to a README or store GIF | Pillow | `python tools/art/frames_to_gif.py <frames> <out.gif>` |
| AI pixel art: sprites, characters in 4 or 8 directions, animations, tilesets (paid, your token) | PixelLab API | `python tools/art/pixellab.py character --text "..." --size 64 --out <assets>/art/hero --log` (below) |
| AI pixel art on your own GPU: characters, props, tiles, edits, rotations, walk cycles (free per image, big setup) | ComfyUI + SpriteKiln | `python tools/art/comfy_local.py run --workflow art_src/comfy/npc.api.json --set "Prompt.text=..." --seed 1 --out <assets>/art/npcs --log` (below) |
| A whole art set for a Godot game from one spec, on your own GPU: characters, props, terrain and maps, effects, UI, fonts | Dotwork (ComfyUI) | `python tools/art/dotwork/dotwork.py pack --spec assets_src/specs/town.json` (below) |
| Drawing, animating and hand-polishing pixel art (including AI output) | Aseprite (paid) or Pixelorama (free); more in `docs/resources/art.md` | By hand; keep the `.aseprite` or `.pxo` file under `assets_src/` |
| Third-party packs into the project, logged | stdlib | `python tools/fetch_asset.py --url <zip> --page <license page> ...` (SOP-04) |

## Rules
1. **Pixel art:** resize only by whole multiples, with `--interpolation none` (GIMP) and nearest-neighbor filtering in the
   engine. Any other filter invents in-between colors and blurs edges.
2. **Vector art:** export at every size the game uses (`--size` repeated) instead of scaling a PNG in the engine. Convert text
   to paths in the SVG, because exports use the fonts installed on whichever machine runs the export.
3. **Palettes:** `gimp_batch.py --indexed N` for a hard color limit; keep the palette in `docs/CONCEPTS.md` (color bible).
4. **Names:** `spr_<thing>_<state>.png`, `ui_<thing>.png`, `<name>_sheet.png` plus its `.json` layout. Lowercase, underscores.
5. **Log it:** every source made from third-party or AI-assisted material has an `ASSET_LOG.md` row (`/asset-intake`).

## Running the tools (tested, F27)
- GIMP 3 and Inkscape 1.x are found automatically on Windows (per-user and Program Files installs) or via `GIMP_CONSOLE` and
  `INKSCAPE`; on macOS and Linux put them on `PATH` **(verify the binary names for your install)**.
- **The first GIMP run on a machine can take minutes** (it builds caches); after that a batch starts in seconds.
  `gimp_batch.py` runs the whole batch in one GIMP process and reports each file; one broken file never stops the rest.
- GIMP's Python support is an install option on Windows. Without it the tool exits 2 and says so.
- Inkscape exits 0 even when it skips an export (E48), so `svg_export.py` checks every expected file itself. Trust its
  `[FAIL]` lines, not Inkscape's exit code.
- Exams: `python tools/art/test_gimp_batch.py` (13/13 on GIMP 3.2.6) and `python tools/art/test_svg_export.py` (12/12 on
  Inkscape 1.4), both on Windows (K01). They exit 2 when the program is not installed.

## Generating pixel art with PixelLab (opt-in, paid)
PixelLab (pixellab.ai) makes pixel art from text: images, characters facing 4 or 8 directions and their animations,
tilesets, effects, UI panels, fonts and props, and fixes existing pixel art. It needs your own account; one developer's trial was 40 generations (E61) **(verify the current plans)**.
- **Scripted, logged: `tools/art/pixellab.py`.** Reads the token from `PIXELLAB_API_KEY` (never prints it), prints what each
  request cost, waits for PixelLab's background jobs, checks every PNG, and with `--log` writes the `ASSET_LOG.md` row
  and evidence file (prompt, plan, cost, SHA-256). `check` shows the generations left; `--dry-run` spends nothing.
  Tested by the kit offline against PixelLab's published API spec (K01); live so far: `check`, a 16 px `character --legacy`,
  `prop`, `vfx`, `iso-tile`, `tileset --kind sidescroller`, `edit` and `fix`; the rest **(verify)** live.
  Commands and rough costs in generations (PixelLab's help, 2026-10 **(verify)**; each command prints its real cost):

  | Command | Makes | Cost |
  |---|---|---|
  | `character` | a character in 4 or 8 directions | 2 to 9 (v3) |
  | `animate-character --mode template` / `skeleton-v3` | a stock motion (walk, cross-punch...) on that character | 1 / 2 to 4 per direction |
  | `animate-character --mode v3` / `pixminimax`, `animate` | a motion from text | by size and frames |
  | `tileset` (top-down or `--kind sidescroller`), `iso-tile`, `prop` | terrain, platforms, one block, one map prop | 1 to 2 |
  | `vfx` | an animated effect: GIF, spritesheet, JSON with its anchor | lite 1, `--pro` 6 |
  | `edit`, `pixelate` | change one thing in an image; a picture into real pixels | 1 |
  | `fix` | reduce colors, clean stray pixels, unzoom, remove a background, a normal map | 0.1 to 0.5 |
  | `object`, `ui` | a prop in 1 or 8 directions; a UI panel or bar | 10 to 25 |
  | `font` | a pixel font (.ttf + atlas) | 15 |
  | `tiles-pro` **[paid plan only]** | pro tile variations, a terrain set, road autotiles, a building kit | 10 to 25 |
  | `outfit` **[paid plan only]** | one outfit onto every frame of an animation | 10 to 25 |

  Lessons from a real game (tip, the owner's Obsidian Wyvern, 2026-10): fix the **base sprite** before animating
  (`edit`: "change ONLY the hand into a fist"); `--mode template` redraws the character and can drop big props, while
  `skeleton-v3` keeps them; animate the direction where the prop is on the near side, then mirror. Free in the MCP
  (no generations for subscribers): `vfx_workbench` effects and the `pixelart_workbench` editor.
- **Interactive: PixelLab's MCP server.** In a terminal (not in a chat with Claude, which would put the token in the
  transcript): `claude mcp add pixellab https://api.pixellab.ai/mcp -t http -H "Authorization: Bearer <your token>"`.
  Claude Code stores the token in its own config. Every call spends generations: never allow-list its tools, so each
  one asks first. Log what you keep with `/asset-intake`. Claude Desktop instead reads a JSON config file (PixelLab's
  site has a ready snippet per tool, with your token in it: paste it into the file, not a chat); after editing it, quit
  Desktop fully (its background processes too) and wait until the server shows as running (tip, E66).
- **Cheapest path first** (tip, E61): one developer made his still art elsewhere (free credits) and called PixelLab only
  for what that could not do well, animation: 38 generations gave 22 animations, inside a 40-generation trial; he quotes
  about $12 a month for about 2,000 generations **(verify the current plans)**. "If you're not careful, Claude will go
  ahead and always call Pixel Lab": say in the job (or `CLAUDE.md`) when it may be used, and price one before many
  (SOP-12, E51). The same developer later compared both paths on one character (E66): 4-frame sheets from a general
  image tool, animated in code, walked stiffly and drifted between frames; PixelLab's 8-frame walk was clearly smoother.
- **Make each character once, animate from it** (tip, E66): PixelLab keeps the character, so later motions (attack,
  hurt) start from the same look: `animate-character --from <the folder its character command wrote>`, not a new
  character or re-sent reference pictures.
- **Keep animation smoothness even** (tip, E66): one fluid hero beside choppy enemies or animals looks wrong. Pick frame
  counts per kind of thing (characters, enemies, critters) and hold them, or make low frame counts the game's style.
- **PixelLab's own workflow tips** (tip, E67: the vendor's tutorial; the features checked against its MCP tool
  descriptions 2026-10-27, its claims about result quality are the vendor's own). `pixellab.py` does not have Pro Flash, a style image or a last frame yet: use the MCP tools named here.
  - One look for a whole set: pass the same anchor sprite (the hero's south view) as the style image on every
    `create_image_pro_flash` call; without it each call picks its own look. One changed word ("shorter") varies a
    design without losing the style.
  - Variants by editing: `edit_image_pro_flash` from the last good result (winter outfit, then a royal one), enemy
    variants (the same beetle made of ice), states (walking, hurt, sleeping; say "front facing" or the pose turns).
    `inpaint_image_pro_flash` with "New layer with changes" gives a separate layer per piece (hair, shirt, pants):
    swappable overlays.
  - Animation: give the frame room before a big motion (a 64 px sprite on an 80 px canvas for a slam). On 8
    directions, write the motion for each direction: an enhanced prompt written from the south view says "towards the
    camera", which fights north-east. Name an effect's color, or each direction picks its own. Mirror a direction
    that works instead of generating the opposite one. For a clean loop, pin the last frame to the first
    (`animate_image_pixminimax` `last_frame`) and drop the duplicate frame. Clean up every result by hand.
  - PixMiniMax takes 4 to 40 frames (multiples of 4) and is priced by the canvas it upscales to: 40 frames cost 6
    generations at 128x128 and 2 at 132x132 **(verify)**. The vendor now recommends the `skeleton-v3` templates.
- **Every paid generation gets a yes first.** Claude shows the exact request (`--dry-run`), what it makes and its
  expected cost, and waits for the owner's yes for that request; an earlier plan is not a yes. A trial's few dozen
  generations go fast.
- **License** (PixelLab's FAQ, read 2026-10) **(verify the current terms before shipping)**: commercial use allowed;
  do not train AI models on the output. Stores ask about
  AI assets (SOP-04). Keep each prompt: `--log` does, and `docs/BRIEFS.md` holds the style fragments that keep a set
  consistent (E61 kept one running document of every art, sound and music prompt).

## Generating pixel art locally (ComfyUI, opt-in, free per image)
ComfyUI runs image models on your own NVIDIA GPU through a node graph; the SpriteKiln node pack adds about 30 pixel-art
workflows (text, image or a style reference to pixel art, edit, inpaint, 4 or 8 direction rotation, walk sheets,
animation, seamless tiles, wang16 and blob47 autotiles). No account and no per-image cost; you pay in setup time, disk
and GPU minutes. One owner's setup and test (tip, E68):
- **Hardware it ran on:** RTX 5060 Ti 16 GB, 64 GB RAM, Windows 11. RTX 50 cards need PyTorch built for CUDA 12.8 or
  newer. Give ComfyUI its own Python environment (3.12 at the time; the newest Python was too new for PyTorch).
- **Download only the tier you need** (sizes from that first experiment; Dotwork's own tiers are smaller, 15.3, 29.1
  and 33.4 GB, about 78 GB for all three: `tools/art/dotwork/README.md`): core 38 GB (Z-Image Turbo, FLUX.2 klein 4B, BiRefNet
  background removal, pixel-art LoRAs); best rotations 31 GB (Qwen-Image-Edit 2511 GGUF with a multi-angle LoRA);
  animation 36 GB (Wan 2.2 image-to-video 14B GGUF); SDXL 8 GB (not worth it there). About 108 GB for everything.
- **Results on that machine:**

  | Job | Result |
  |---|---|
  | Character, prop, icon, UI piece or isometric piece (FLUX.2 klein 4B + pixel LoRA + a 2x2 collage of the game's sprites as the style reference, then the refine step below) | Usable: about 16 s each; portraits need a bust prompt |
  | 4 or 8 direction rotation, Qwen multi-angle | Keeps lopsided details (a fist on one arm): about 2 to 3 min for 4, 5 min for 8; klein is fast but drops details |
  | Edit by instruction, masked inpaint, normal map | Usable: 16 s, 13 s, 3 s |
  | Animation (Wan 2.2 image-to-video, SpriteKiln workflow 10): idle, walk, kick in 4 directions from a rotated sprite | Good: about 1.7 min per clip (a 4-direction set of 6 actions is about 35 min); scale and palette hold. Needs about 20 GB free RAM; free the models between clips (`POST /free`) |
  | Seamless 128 px terrain (refine, then inpaint the seam cross) | Usable, 6 of 8; plain AI tiles at 32 px are noise |
  | Corner autotiles from those textures (a small script, no AI) | Usable, under 1 s |
  | Whole-scene map | Angle and scale drift: backdrops only. Repaint a map drawn in code instead, at strength 0.3 to 0.45 |
  | Effects (fireball, explosion, muzzle flash, heal, steam) drawn on black and animated with Wan | Good to excellent: about 2 min per clip; draw them with additive blending (Godot: `CanvasItemMaterial` blend mode Add) |
  | 8-direction objects; sidescroller tiles | 8 directions made in Dotwork (an airship; its views come out rotated one step, KNOWN_ISSUES); sidescroller tiles not run yet **(verify)** |

- **The refine step** (tip, E68): never shrink a klein render straight to sprite size, which loses the detail. Shrink
  to the target size, enlarge 8x by nearest neighbor, run image-to-image at about 0.45 with the same reference, then
  sample the grid and lock the palette. A single sprite as the reference also hands over its outfit and props: use a
  collage of several. Strength is not linear on klein (0.45 can wipe a busy scene; try 0.3 first).
- **Effects grow faces** (tip, E68): a character-animation prompt (SpriteKiln's preset says "consistent character
  design") turns fading explosions and heal rings into cartoon creatures. For effects, replace the animation text
  prompt with an effect-only one ("abstract glowing energy... particles and light only, no faces, no eyes, no
  characters, no creatures", black background, locked camera). Long one-shot fades still grow faces: keep about 3
  frames of an explosion and fade the rest out with a dither. Loops are fine.
- **Negative prompts do nothing for Wan at cfg 1.0** (tip, E68). The 4-step Lightning LoRAs in SpriteKiln's
  animation workflow run it at cfg 1.0, so steer with the positive text ("throws a punch with the big brass
  mechanical fist") or fix the frames afterwards.
- **Attacks and casts** (tip, E68):
  - **Facing:** turn the character to face the direction of travel first (rotate, then animate the side view), and
    check facing on the pixels: SpriteKiln's 4-direction rotation files run S, W, N, E, not S, E, N, W (Dotwork renames them to s, e, n, w).
  - **Timing:** spawn the effect on the peak frame (the one whose upper body reaches furthest toward the target) and
    hold that pose while the effect leaves.
  - **Presets:** they invent props and moves (a pistol firing a beam, a white swirl). Write a custom motion and add
    negatives for what appeared.
  - **Edges:** fade one-shot effects with a round dither vignette so the video frame's edge never shows.
- **Animation sets** (tip, E68):
  - **Settings:** one seed for every clip so the motion matches; a palette lock to each direction's sprite; feet
    pinned to the bottom center. Mirror east for west.
  - **Picking the action:** Wan's action is a fixed list (walk, idle, run, attack, hurt...). Name the view per
    direction: "front view", "side view", "keep facing direction" for the back.
  - **Checking the result:** put every frame of every clip on one review sheet and look at it. Characters turn to face
    the camera, mostly in attacks and north clips: keep the first good frames and play them back to the rest pose, or
    re-render only that clip with a new seed. For a hard clip, audition: several seeds times two or three motion
    wordings on one sheet, then pick by eye (a side punch: 1 clean take of 8, with a wording that locks the profile
    and names the limb; automatic scores missed turned takes). If every take fails the same way, fix the starting
    sprite instead: a three-quarter "side" view with the attacking limb hidden behind the body gave 4 of 4 takes that
    never punched. Name limbs by what they are ("the arm with the brass gauntlet"), not "near" or "far". Back views grow a face on the back of the head (3 of 3 seeds for a north
    idle): use a 1 px breathing bob of the back sprite instead.
  - **Ground shadows:** render the clip without the palette lock, remove the flat neutral blob at the feet, then
    lock. Locked first, the shadow is painted in the sprite's own dark colors and cannot be told apart.
  - **Picking the base sprite:** an automatic pick by image quality can miss the prompt (an "old" lamplighter came
    out young). Look at the candidates.
- **Hand polish as a round trip** (tip, E68): generated frames go into one `.aseprite` per character with a frame tag
  per animation, indexed on the asset's own colors. After the artist's pass, a script exports each tag back to the
  shipped paths and rebuilds the engine resources, then the import check runs again. Prove the trip is lossless first:
  with no edits, 0 of 120 PNGs changed there. Two scripting traps: Aseprite on Windows is a GUI program, so start it
  from Python's `subprocess.run` (which waits) or PowerShell's `ProcessStartInfo` with `WaitForExit`, not `&`; and in
  Lua, an indexed `Image` saved on its own loses its palette (all black), so convert the sprite to RGB in memory first.
- **Godot terrain: prefer blob (47 tiles, Match Corners and Sides) for overlays** (tip, E68). In corner mode the
  visible edge sits half a tile inside the painted cells and single cells vanish; blob mode fills exactly the painted
  cells, keeps single cells as islands and 1-wide lines as paths. Give each overlay terrain its own TileMapLayer over
  a base layer of plain tiles in a few seamless variants, plus a decal layer. Render terrain textures at the pixel
  grid they will ship at; a texture rendered big and shrunk 16x came out as flat 2-color blobs.
- **Judge a set on a mock screen** (tip, E68): before writing game code, compose one screenshot from the generated
  packs at the game's real resolution (a battle: background, enemies, a party pose, windows, fonts, damage numbers).
  Mismatched scale, palette or perspective show there, not in single-asset sheets. Pose edits need specific wording;
  vague wording returned the idle pose.
- **Long terrain edges repeat unless every variant has every edge tile** (tip, E68). Give each texture variant all
  47 blob tiles, not just the interior, and let Godot pick by probability. Paint the bank material under water, so
  the water's inset edge shows a bank instead of the grass around it. Fences, pipes and rails can be blob overlays
  drawn in code: the painted sides give the straight, elbow, tee, cross and dead end.
- **Ship props as scenes, not just PNGs** (tip, E68): a StaticBody2D with the origin at the feet (for y-sort) and a
  collision footprint. Trees, lamps and posts get a narrow trunk footprint so characters can walk behind the top;
  flat things (rugs, plates, spikes) stay non-solid.
- **Fonts are not a generation job** (tip, E68): image models do not draw a consistent set of letters. Use an OFL or
  CC0 pixel font (`tools/fetch_asset.py` logs it), or author glyphs as text bitmaps and build an AngelCode BMFont
  `.fnt` plus a PNG page, which Godot imports as a FontFile with no plugin. Draw glyphs white and tint them in the
  engine.
- **If you use wang16 corner tiles** (tip, E68): Godot's match-corners solver needs a tile whose center terrain
  matches the painted terrain. With one copy of each of the 16 tiles, single cells, 1-wide lines and diagonals
  mismatched; an atlas with every tile twice (once per center terrain) gave 0 mismatched corners. Test by painting
  those shapes in a script. In code, fill the base terrain first: on an empty layer, `set_cells_terrain_connect` with
  the default `ignore_empty_terrains = true` leaves the region's outer ring unpainted. One 32 px fill tile repeats
  visibly at 640x360: add decor overlay tiles (tufts, pebbles, cracks) on a second layer.
  Use it for **concepts, variants and style references**; final sprites and animation still needed hand polish or
  another route on that machine (the same cheapest-path-first idea as E61).
- **One palette for both:** build a palette from the game's existing sprites and apply it in every local workflow
  (SpriteKiln's palette node), so art from every source reads as one game. Extend it with the hues new characters and
  environments need first, or a purple dress turns maroon. Keep the palette in `docs/CONCEPTS.md`. Use
  the 1x outputs; the enlarged previews are for looking.
- **Treat custom nodes as untrusted code.** A node pack is Python that runs with your rights, often plus JavaScript in
  the UI. Clone it into a separate quarantine folder with git hooks off, read it (network calls, `subprocess`, `eval`,
  `torch.load` without `weights_only=True`, code that runs on import, auto `pip install`), then copy it in without
  `.git` and write its commit and any local patches in a note beside it (PINNED.txt). Update by repeating the review, not with the
  Manager's update button or the pack's own install script. That review found and patched a path escape in SpriteKiln's
  part saver, and its bundled web UI server (webui/serve.py) strips the Origin header that ComfyUI's CSRF check needs: never run it (E68).
- **Models: `.safetensors` or `.gguf` only** (pickle formats such as `.ckpt`, `.pt`, `.bin` can run code when loaded),
  each pinned to a Hugging Face commit with its SHA-256 recorded.
- **ComfyUI has no login.** Keep it on `127.0.0.1` (the default); `--listen` lets anyone who reaches the port run
  workflows and install nodes.
- **Licenses are per model; check each model card.** At the time: FLUX.2 klein 4B Apache-2.0; klein 9B non-commercial
  (skip it for a game you might sell); SDXL base OpenRAIL++; Pixel Art XL CreativeML OpenRAIL-M; small LoRAs from
  single uploaders vary **(verify each card)**. ComfyUI and SpriteKiln are GPL-3.0, ComfyUI-GGUF Apache-2.0,
  ComfyUI_essentials and PixelArt-Detector MIT: licenses for the tools, not your images.
  **Check every file, not the model's name:** a VAE, text encoder or LoRA can come from a repository with another
  license. That setup first loaded `flux2-vae.safetensors` from the FLUX.2 [dev] repository (non-commercial) next
  to klein 4B; the klein repository has its own Apache-2.0 VAE with a different SHA-256. Every image made with the
  wrong file, and everything rotated or animated from one, had to be made again (E68). Keep a table of each file,
  its repository, its license and its SHA-256.
- **Log every kept image** in `ASSET_LOG.md` (`/asset-intake`): "ComfyUI (local)", the workflow, base model, LoRAs with
  their commits, seed and prompt, so it can be made again. ComfyUI's saved PNGs embed the whole prompt and workflow (local
  paths included): re-save an image without it before you publish or share it. Stores ask about AI assets (SOP-04).
- **Scripted, logged: `tools/art/comfy_local.py`.** Build and test a workflow in ComfyUI's UI, save it in API format
  ("Export (API)") under `art_src/comfy/`, then: `check --workflow <file>` (server up, every node installed, the models
  it names); `run --workflow <file> --set NODE.INPUT=VALUE --seed N --image NODE=<png> --out <folder> --log` (the
  images without ComfyUI's embedded workflow, a `comfy_local.gen.json` record, and the `ASSET_LOG.md` row with the
  models to license-check); `strip <png...> --out <folder>` for images saved by hand. It talks only to a server on
  this machine. `--dry-run` prints the edited workflow. Tested offline (K01) and `check` live on ComfyUI 0.43.0; a
  live `run` **(verify)**. Ask the owner before Claude starts a multi-gigabyte download or installs a node pack.
- **The whole pipeline: `tools/art/dotwork/`.** One JSON spec in (ready-made ones in `tools/art/dotwork/examples/`); out,
  straight into the game: characters in 4 directions with idle, walk, attack and pose clips as SpriteFrames, props as
  collision scenes, layered terrain and maps painted from text, effects, enemies, battle backgrounds, icons,
  portraits, pixel fonts and window skins, plus editable sources and review sheets under `assets_src/` and a manifest
  that `dotwork.py log --pack NAME` turns into the `ASSET_LOG.md` row. Start with
  `python tools/art/dotwork/dotwork.py setup --check` (the models per tier, 15 to 33 GB; it never downloads), then
  `pack --spec <file>`, which ends by loading every asset in Godot and running the game's smoke test. The lanes drawn
  in code (fonts, window skins, balloons, hit effects) need no GPU: `pack --spec tools/art/dotwork/examples/ui.json` is
  a good first run (set `GODOT_BIN` first, or add `--engine none`). Godot only for now; `--engine none` writes the PNGs, sheets and manifest for any engine. Tested
  offline and in a freshly made Godot game (K01); the model lanes on one machine (E68). Its README lists every lane,
  key and limit.
- **Bring 3 or 4 of your own sprites** (tip, E68). Dotwork's `style_refs` is empty by default, so the style comes only
  from the pixel-art LoRA, the palette and the refine step, and a set is less uniform. List 3 or 4 finished sprites
  from the game (drawn by hand, drawn in code with `pixel_sprite.py`, or kept from an earlier run) and Dotwork copies
  their outline and shading. Only use sprites you have the rights to: the reference shapes everything made from it.

## Done when
- Every shipped 2D asset has a source and a one-line command that recreates it.
- Pixel art is crisp at every zoom the game uses; vector exports exist at every size the game uses.
- New third-party or AI-assisted sources are logged.

## Common mistakes
- Scaling pixel art by 1.5x, or with a smooth filter (engine or export).
- Exporting by hand from an open editor window with different settings each time.
- Text in SVGs that renders in a fallback font on the build machine.
- Committing only the PNG and losing the layered source.
