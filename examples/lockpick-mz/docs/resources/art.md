# Art: 2D, 3D, UI, fonts, VFX

Asset libraries and tools. AI generators are in `ai-tools.md`, prompt patterns in `docs/BRIEFS.md`, the 3D process in `docs/sop/SOP-11-3d-pipeline.md`.

> **Read this caveat.** Written from general knowledge plus video notes, not live-checked. Sites change terms, go offline, or rename
> licenses. The license that matters is the one on the **specific asset page on the day you download it**. Save the license text in
> `docs/licenses/` and log the asset in `docs/ASSET_LOG.md` via `/asset-intake`. Anything marked **(verify)** is the most likely to have changed.

## Art (2D)
- `kenney.nl`. CC0, huge, consistent style. Best prototyping source.
- `opengameart.org`, `itch.io/game-assets` (filter free, check license per pack).
- `lospec.com` palettes (palette lists are free to use) plus pixel art tutorials.
- Pixel art editors (for drawing, animating and hand-polishing sprites, including AI output). What you make with any of
  them is yours; the license is about the program. Searched 2026-10-29 through secondary pages, so check each
  project's own page **(verify)**:

  | Editor | Cost and license | Platforms | Good for | Notes |
  |---|---|---|---|---|
  | **Aseprite** | Paid once (about $20; Steam, itch.io or its site); source-available under its own EULA, not open source | Windows, macOS, Linux | The standard: layers, animation timeline, onion skin, tilemaps, palettes, sprite sheet + JSON export, Lua scripting, a command line for batch export | You may build it from source for yourself but not hand the build to others. On Windows it is a GUI program: a script must start it as a process and wait for it to get a real exit code (`&` in PowerShell does neither) |
  | **Pixelorama** | Free, MIT | Windows, macOS, Linux, browser | Layers, animation, onion skin, tilemaps, palettes, sprite sheet export; open-source alternative to Aseprite | Made with Godot by Orama Interactive. Version 1.2 or newer at the time **(verify)** |
  | **LibreSprite** | Free, GPL (a fork of Aseprite's last GPLv2 code; one listing says GPLv3) | Windows, macOS, Linux | An Aseprite-like workflow at no cost | Older feature set than today's Aseprite |
  | **Piskel** | Free, open source (Apache-2.0 **(verify)**) | Browser, desktop builds | Quick small sprites and animations, GIF and sheet export | Simple; good for a first sprite |
  | **Lospec Pixel Editor** | Free, in the browser | Browser | Quick edits with `lospec.com` palettes | Very basic |
  | **GrafX2** | Free, open source (GPL **(verify)**) | Windows, macOS, Linux | Palette-based (indexed) art, retro platforms | Deluxe Paint style; steep for newcomers |
  | **Pyxel Edit** | Paid, proprietary | Windows, macOS | Tilesets: draw tiles and paint levels with them | Updates have been slow **(verify)** |
  | **Krita** | Free, GPL | Windows, macOS, Linux | Painting with pixel brushes and an animation timeline; its AI Diffusion plugin can drive a local ComfyUI | A general painting program, not pixel-first |
  | **GIMP** | Free, GPL | Windows, macOS, Linux | Batch export, indexed palettes, pixel-safe resizing (`tools/art/gimp_batch.py`) | Not made for animation |
- Other 2D tools: `Inkscape` (vector: UI, icons, clean characters), `Tiled` (maps), `LDtk` (levels), `TexturePacker`,
  `Shoebox`. Kit tools drive GIMP and Inkscape headless: `tools/art/gimp_batch.py`, `tools/art/svg_export.py`
  (`docs/sop/SOP-16-2d-art-pipeline.md`).
- Local AI pixel art for Godot: `tools/art/dotwork/` turns a JSON spec into characters, props, terrain, maps, effects,
  UI and fonts on your own GPU through ComfyUI (opt-in, 15 to 33 GB of models; the code-drawn UI lanes need no GPU).
  Setup and licenses in its README.
- Backgrounds and parallax: itch.io packs, or paint your own with a limited palette.

## Art (3D)
- `kenney.nl` 3D kits (CC0), `quaternius.com` (CC0), `polyhaven.com` (CC0 models, HDRIs, textures),
  `ambientcg.com` (CC0 textures), `sketchfab.com` (per-model license, filter downloadable plus CC).
- Unreal: `fab.com` (Epic's unified marketplace that absorbed the old Unreal Marketplace and Quixel Megascans). **(verify current terms)**
- Animation: `mixamo.com` (Adobe terms apply). **(verify)**
- Tools: `Blender`, `Material Maker`, `Substance` (paid), `Cascadeur`.

**3D generators (AI drafts, not final assets)** **(verify all: sources are third-party reviews, mid-2026)**
- **Tripo AI** (`tripo3d.ai`): text-to-3D and single-image-to-3D, smart retopology, auto-rigging with skin weights, PBR texturing,
  export to GLB, FBX, OBJ, USD, STL, 3MF. Has a credit-based API, an MCP server, and plugins for Blender, Unity, Unreal, Godot, ComfyUI.
  **Commercial use:** a third-party review says the Free plan is NOT for commercial use and paid plans are. Confirm on Tripo's own terms
  and record your plan in `ASSET_LOG.md` at generation time.
- Alternatives mentioned in the same review: Meshy (stronger for 3D printing), Rodin (photoreal product look). Also Hunyuan3D and others, check current status.
- Always plan for cleanup in Blender: topology, UVs, scale, pivots, material rebuild (`docs/sop/SOP-11-3d-pipeline.md`).

## UI and icons
- `kenney.nl` UI packs (CC0), `game-icons.net` (CC BY 3.0, attribution needed), `Font Awesome Free`, `Lucide`.
- Keep a single UI skin and spacing scale. Define it once in a theme resource.

## Fonts
- `fonts.google.com` (mostly OFL), `fontsquirrel.com` (commercial-use filtered), itch.io pixel fonts
  (check each license), `Press Start 2P` and `m5x7` are popular pixel choices. **(verify each license)**
- Ship the font license file with the game.

## VFX and shaders
- Godot: `godotshaders.com` (per-shader license, many CC0). Unreal: built-in Niagara samples.
- `shadertoy.com` for ideas only. License varies, port logic from scratch.
- Kenney particle packs (CC0).

Back to the index: `docs/RESOURCES.md`.
