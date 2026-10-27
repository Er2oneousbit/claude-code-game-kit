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

## Done when
- Every shipped 2D asset has a source and a one-line command that recreates it.
- Pixel art is crisp at every zoom the game uses; vector exports exist at every size the game uses.
- New third-party or AI-assisted sources are logged.

## Common mistakes
- Scaling pixel art by 1.5x, or with a smooth filter (engine or export).
- Exporting by hand from an open editor window with different settings each time.
- Text in SVGs that renders in a fallback font on the build machine.
- Committing only the PNG and losing the layered source.
