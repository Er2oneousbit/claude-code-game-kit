# Dotwork asset manifest (engine-neutral, version 1)

Dotwork makes the same art for every engine, but only Godot gets ready-made resources (SpriteFrames, TileSets, prop
scenes). For every other engine, each pack also gets one JSON file that says what the PNGs are: which frames make which
clip and for how long, where a sprite's feet are, what collides, which tile fits which neighbours, what a map paints,
how a bitmap font is laid out. An importer per engine reads it (#55 to #62); this page is the contract they are built
and tested against.

- Spec version: **1.0.0** (`assetspec.VERSION`)
- Schema: [asset_manifest.schema.json](asset_manifest.schema.json) (JSON Schema 2020-12)
- Validator and reference loader: `assetspec.py` (standard library only, Python 3.8+)
- Writer: `assetmap.py` (called by `dotwork.py pack`, `character`, the hand-polish re-exports and `manifest`)
- Golden fixture: `data/golden/dotwork/` (every kind, plus `expected.json`, the loaded result importers must match)

## Contents
1. [Where it lives](#where-it-lives)
2. [Conventions](#conventions) (coordinates, pivots, time, masks)
3. [Versioning](#versioning)
4. [The document](#the-document)
5. [Asset kinds](#asset-kinds)
6. [Autotiling and maps](#autotiling-and-maps)
7. [Godot is the reference](#godot-is-the-reference)
8. [Which lane makes which kind](#which-lane-makes-which-kind)
9. [Golden fixture and loaded result](#golden-fixture-and-loaded-result)
10. [Commands](#commands)
11. [How to write an importer](#how-to-write-an-importer) (per-engine notes for #55 to #62)
12. [Limits](#limits)

## Where it lives
One file per pack: `<assets_dir>/dotwork/<pack>.assets.json` (`assets/dotwork/<pack>.assets.json` in most games,
`public/assets/dotwork/<pack>.assets.json` in a web game, `Assets/dotwork/<pack>.assets.json` in Unity). Every path
in it is relative to the folder named by its `base` field, which is relative to the manifest's own folder. Dotwork
writes `"base": ".."`, so paths are relative to the assets folder (`art/characters/<name>/frames/<frame>.png`), and
an importer resolves a path as `join(dirname(manifest), base, path)`. Paths use forward slashes, never `..`, a drive or a leading `/`.

Dotwork writes the file after every `pack` (all packs' files are rebuilt, because two packs can write the same file,
such as a font) and after `character`; `dotwork.py manifest` writes every pack's. `aseprite --reexport` and
`pixelorama --reexport` keep the files that exist in step and create none, so an untouched round trip still changes
no file. A file is written only when its text changes. It is made from the pack's provenance manifest (`<src_dir>/dotwork/manifest_<pack>.json`,
which `dotwork.py log` reads for the asset log) and is the same with `--engine godot` and `--engine none`, except
for the optional `godot` cross-references.

Files outside the assets folder (store art in `assets_src/`) are not listed: they do not ship in the game.

## Conventions
| What | Rule |
|---|---|
| Units | pixels of the art itself (1x; a `scale` field says when an image is drawn bigger, as UI kits and fonts are) |
| Origin and axes | an image's top-left corner, x to the right, **y down** (Godot, SDL, LÖVE, Phaser, MZ). Unity, Bevy, Unreal and Three.js are y up: flip y when converting (notes below) |
| Rect | `[x, y, w, h]`, integers for image regions, numbers for collision boxes (a centred box on an odd size lands on a half pixel) |
| Pivot | `[x, y]` in the image's own pixels: the point that sits on the node's position (a character's feet, a prop's base, an effect's centre). Normalised for an engine: `px / w`, and `py / h` (y down) or `1 - py / h` (y up) |
| Time | seconds. A frame's `duration` is `hold / fps`: `hold` is the relative hold Godot stores per frame (2 shows a frame twice as long), `fps` the clip's rate. `length` is the sum |
| Colour | `#rrggbb` (terrain colours only; the art's colours are in the PNGs) |
| Names | `[A-Za-z0-9_.-]+`, unique per kind within one manifest |
| Directions | `s e n w` and the diagonals `se ne nw sw`: screen directions (n is up the screen), a character facing the camera is `s` |
| Masks | 8 bits, one per neighbour, in the order **N, NE, E, SE, S, SW, W, NW** (bit 0 is N = 1, NE = 2, E = 4, SE = 8, S = 16, SW = 32, W = 64, NW = 128). A set bit: that neighbour holds the same terrain. Details in [Autotiling](#autotiling-and-maps) |

Pixel art wants nearest-neighbour filtering, no mipmaps, no texture compression and whole-number scales; every
importer sets that on every texture it creates.

## Versioning
`version` is `MAJOR.MINOR.PATCH`. An importer reads every manifest of its own major version and refuses another major
with a message naming both. Within one major, a minor version may add optional fields and new kinds, never change or
remove one: so an importer ignores fields it does not know and skips (with a warning) kinds it does not know. A patch
only fixes the text of this page or the writer, not the format. The schema file and `assetspec.py` move with the
writer: Dotwork never writes a manifest its own validator rejects (`pack` fails if it would).

## The document
```json
{
 "format": "dotwork-assets",
 "version": "1.0.0",
 "pack": "town",
 "generator": "dotwork",
 "base": "..",
 "assets": [ {"kind": "animated_sprite", "name": "hero", "...": "..."} ]
}
```
`assets` is sorted by kind (in the order of the table below), then name. Every asset has `kind` and `name`; an asset
that Godot loads through a resource of its own also has `godot` (the path of that `.tres` / `.tscn`, only when the
file exists, so never with `--engine none`). Importers never need `godot`; it is there for the cross-check below.

## Asset kinds
The first eight are **core**: every importer handles them. The other five are **extra**: an importer may skip them
(with a line saying so) until its engine needs them.

| Kind | Core | What it is |
|---|---|---|
| `animated_sprite` | yes | named clips of frames with timing, loop flag and pivot: characters, NPCs, vehicles, animated props, effects, spells, status loops, projectiles, balloons, talking portraits |
| `sprite` | yes | one image with a pivot and optional collision boxes and contact shadow: props, enemies |
| `icon` | yes | one design at several pixel sizes |
| `portrait` | yes | a bust and its expressions; `animation` names the talking-frames `animated_sprite` |
| `tileset` | yes | atlases of tiles with terrains, autotile masks or corners, probabilities, collision, animation, multi-tile stamps |
| `map` | yes | layers of placed tiles and of terrain to paint, plus objects (props) at pixel positions |
| `font` | yes | an AngelCode BMFont: pages, metrics and the glyph map |
| `ui_kit` | yes | the images of one UI set: 9-slice margins, states, gauge parts, cursors with hotspots, prompt glyphs |
| `background` | no | layers that scroll or drift (velocity in px/s, repeat axes): battle backgrounds, parallax, scenes, weather |
| `particles` | no | an emitter's settings (Dotwork's particle JSON) and its white mask texture |
| `transition` | no | a greyscale rule image a screen transition thresholds |
| `normal_map` | no | an OpenGL-style (green up) normal map and the image it lights |
| `image` | no | any other shipped PNG: name, role (what made it), size |

### animated_sprite
| Field | Type | Meaning |
|---|---|---|
| `role` | string | the art folder it sits in (`characters`, `fx`, `props`, `vehicles`, `portraits`, `ui`) |
| `blend` | `normal` \| `add` | `add` draws additively (fire, sparks, spells) |
| `clips` | list | one per animation, in the order Godot's SpriteFrames lists them |
| `clips[].name` | string | `walk_s`, `attack_e`, `play`, `fly`, `talk` ... |
| `clips[].fps` | number | the clip's rate |
| `clips[].loop` | bool | false: play once and hold the last frame (attacks, deaths, one-shot effects) |
| `clips[].holds` | numbers | optional: the relative hold of every frame (absent: all 1) |
| `clips[].frame_size` | `[w, h]` | every frame of a clip is this size; clips of one asset may differ (a death clip is wider) |
| `clips[].pivot` | point | the feet for characters (`[w/2, h]`), the centre for effects, the head of a trail (`[w, h/2]`) |
| `clips[].sheet` | path | optional: one horizontal strip holding every frame; when present each `rect` is in it |
| `clips[].frames[]` | `{file, rect, duration}` | `file` is the frame's own PNG (always shipped); `rect` is in `sheet` when there is one, else `[0, 0, w, h]` |
| `clips[].length` | number | seconds, the sum of the durations |
| `directions` | `{action: {dir: clip}}` | optional: clips named `<action>_<dir>` grouped, `{"walk": {"s": "walk_s", "e": "walk_e"}}` |

A character's frames share one canvas per clip with the feet on the bottom edge, centred; a jump that leaves the
ground keeps its height inside the frame (README, Godot notes), so the pivot stays the ground point. A west clip made
by mirroring is shipped as its own frames: importers never flip.

### sprite
`role`, `image`, `size`, `pivot`, `content_rect` (the opaque bounding box), optional `collision`, optional `shadow`
(`{image, offset}`: a contact shadow drawn behind, its centre `offset` from the pivot).
`collision` is a list of `{rect: [x, y, w, h]}` in the image's pixels (and `one_way: true` on a tile that collides
from above only). A prop's box is its footprint: Godot's StaticBody2D rectangle, centred on the pivot's x, its bottom
on the pivot's y.

### icon
`sizes`: `[{size, image}]`, smallest first. Every size is the same design (Dotwork derives the small ones).

### portrait
`size`, `expressions` (`[{name, image}]`, `neutral` first; `talk` and `blink` are the mouth and eye frames),
optional `animation`: the name of an `animated_sprite` (`portrait_<name>`) with `idle`, `talk` (loop while text
prints) and `blink`.

### tileset
| Field | Meaning |
|---|---|
| `tile_size` | `[w, h]` of a map cell (an isometric diamond is `[w, w/2]`) |
| `shape` | `square` or `isometric` (2:1 diamond, diamond-down layout) |
| `terrain_sets` | `[{id, mode, terrains: [{id, name, color}]}]`; `mode` is `blob47`, `corners4` or `sides4` |
| `atlases` | `[{id, name, role, image, tile_size, columns, rows, tiles}]`: one atlas image each. `role` names its use (`base`, `overlay`, `decals`, `fixtures`, `pair`, `platform`, `floors`, `blocks`, `transitions`). An atlas's `tile_size` can be taller than the cell (iso blocks) |
| `atlases[].tiles[]` | `col`, `row` (atlas cell), optional `terrain_set` + `terrain` + `mask` (blob47, sides4) or `corners` (corners4), `probability` (relative pick weight among tiles with the same terrain and mask; absent = 1), `surface` (custom data: `stone`, `water`), `collision` (rects in tile pixels), `anim` (`{frames, fps}`: the frames sit in the next cells to the right), `origin` (point of the image drawn on the cell's centre, when not its own centre) |
| `stamps` | multi-cell pieces (a 1x2 door): `{name, size: [w, h], solid, tiles: [[atlas, col, row], ...]}` in reading order |
| `custom_data` | the name of the custom value tiles carry (`surface`) |

A tile is addressed as `[atlas, col, row]` everywhere (maps, stamps).

### map
`tileset` (a tileset name in the same manifest), `size` (cells), `tile_size`, `layers` drawn first to last, optional
`objects`. A layer is `{name, kind, cells}`:
- `kind: "tiles"`: cells `[x, y, atlas, col, row]`, or with a sixth number, flags (1 flip horizontally, 2 flip
  vertically, 4 transpose; transpose first, then flip; Pixelorama tilemaps use them). Optional `opacity`.
- `kind: "terrain"` with `terrain_set` and `terrain`: cells `[x, y]` to paint with that terrain. The importer picks each
  cell's tile with the rule under [Autotiling](#autotiling-and-maps).

`objects`: `[{asset, x, y}]`, an asset of this manifest (a prop `sprite`) placed with its pivot at pixel `(x, y)`
(a cell's bottom centre, for props mapbuild places). Draw objects sorted by `y` with the characters (y-sorting by feet).

### font
`file` (the `.fnt`, AngelCode BMFont text format), `pages` (PNG paths, page 0 first), `line_height`, `base` (pixels from
a line's top to the baseline), `scale`, `tint` (true: white ink that takes a colour; false: coloured, such as a
gradient title font), `chars` (`[id, x, y, w, h, xoffset, yoffset, xadvance, page]`, id = Unicode code point, sorted),
optional `kerning` (`[first, second, amount]`), optional `license` (fonts you bring ship their licence). The `chars`
table is the `.fnt` file's, so an engine with a BMFont loader can use the file and one without builds its glyph map
from `chars`.

### ui_kit
One per folder of UI images (`windows`, a widgets set, a menu kit, `glyphs`, `symbols`). `parts`:
`[{name, role, image, size, scale, state?, control?, margins?, stretch_margin?, hotspot?, glyph?}]`.
`role` is the kind of part (`window`, `button`, `panel`, `texture`, `gauge`, `cursor`, `glyph`, `symbol`, `9slice`,
`logo`), `state` a button state (`normal`, `hover`, `pressed`, `focus`, `disabled`), `control` the gauge a part
belongs to (`hp`: parts `under`, `fill`, `over`), `margins` 9-slice margins `[left, top, right, bottom]` in the
image's pixels, `stretch_margin` the ends of a gauge that never stretch, `hotspot` a cursor's click point, `glyph`
the input or symbol a glyph image shows (`key_enter`, `xbox_a`). Prompt glyphs are 1x and 16 px tall: draw them at
whole multiples.

### background
`role`, `layers`: `[{name?, image, size, velocity: [vx, vy], repeat, wobble_px?, scale?}]` drawn first to last.
`velocity` in px/s of the art; `repeat` is `none`, `x`, `y` or `xy` (the image tiles seamlessly on those axes);
`scale` the whole-number scale the art is drawn at. Weather layers move by `velocity` and sway sideways by up to
`wobble_px`; move in whole pixels.

### particles, transition, normal_map, image
- `particles`: `texture` (a white mask, tinted by the emitter's colour steps) and `emitter`, the emitter JSON as Dotwork
  writes it for engines without GPUParticles2D (amount, lifetime, one_shot, colours ...).
- `transition`: `image` (greyscale), `size`, `transition` (wipe, iris, spiral ...). A pixel is covered once the transition's
  progress (0 to 1) passes its grey value / 255 (black first, white last; lane_transitions.py's shader is the reference).
- `normal_map`: `image`, `target` (the image it lights), `convention: "opengl"` (green up; flip green for a y-down
  lighting space that expects DirectX style).
- `image`: `role` (what made it: `logo`, `sheet`, `particle_texture`, `diorama_tile` ...), `size`, optional `pivot`.

## Autotiling and maps
Three terrain modes, all Godot's terrain modes:

| Mode | Godot | Tiles carry | A cell's key |
|---|---|---|---|
| `blob47` | Match Corners and Sides | `mask` (one of 47 values) | its 8 neighbours of the same terrain; a corner bit counts only when both sides next to it are set |
| `sides4` | Match Sides | `mask` with only N, E, S, W bits | its 4 side neighbours of the same terrain |
| `corners4` | Match Corners | `corners`: terrain id per corner (`top_left`, `top_right`, `bottom_left`, `bottom_right`; isometric `top`, `right`, `bottom`, `left`) | the terrain at each of the cell's corners |

The blob rule as code (Python here; every importer ports it, a dozen lines):
```python
NB8 = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))   # N NE E SE S SW W NW, y down
def canon(m):
    for c in (1, 3, 5, 7):                                  # NE, SE, SW, NW
        if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
            m &= ~(1 << c)
    return m
def cell_mask(painted, x, y):                               # painted: the set of (x, y) cells of this terrain
    return canon(sum(1 << b for b, (dx, dy) in enumerate(NB8) if (x + dx, y + dy) in painted))
```
A terrain layer of a map paints exactly its cells; each cell takes a tile of the layer's terrain whose `mask` is
`cell_mask`. Several tiles can share a mask (texture variants): pick by `probability`, or take the first in atlas
order, which is what the loaded result names (Godot picks at random by probability, so a Godot map and another
engine's map can differ in variants, never in shape). This is the rule Godot's own terrain solver follows on these
TileSets: mapbuild checks every painted cell of every map against it in Godot (`blob_bad`). Layers that need it
stack (a path layer over the base layer), each painted on its own.

## Godot is the reference
Every Godot resource Dotwork writes goes through `godot.py`, and every writer there hands what it builds the resource
from to the manifest (`godot.record`, also under `--engine none`, when nothing is written). The manifest is made from
those records, so it carries exactly what Godot gets. The exam builds the golden pack with Godot's files and checks
the manifest against them (frames, holds, fps, loop; peering bits; collision polygons; the prop's origin and box).

| Godot (what Dotwork writes) | Manifest |
|---|---|
| `SpriteFrames` (`<name>_frames.tres`): an animation's frames, `speed`, `loop`, each frame's `duration` | `animated_sprite` clip: `frames[].file`, `fps`, `loop`, `holds`; seconds = duration / speed |
| `AnimatedSprite2D` offset (`[0, -(H // 2)]` for characters, none for centred effects) | `pivot` |
| prop scene (`prop_<name>.tscn`): centred `Sprite2D` with `offset`, `StaticBody2D` + `RectangleShape2D` at `(0, -(fh // 2))` | `sprite`: `pivot = [w/2 - offset.x, h/2 - offset.y]`, `collision` = the rectangle in image pixels |
| enemy scene: centred `Sprite2D` with `offset`, `Shadow` child at `(dx, 0)` | `sprite` with `pivot` and `shadow.offset` |
| `TileSet`: one `TileSetAtlasSource` per atlas, `texture_region_size`, per tile `terrain_set`, `terrain`, `terrains_peering_bit/*`, `probability`, `custom_data_0`, `physics_layer_0/polygon_*`, `animation_columns` / `animation_speed`, `texture_origin` | `tileset`: atlases in source order (the atlas id is Godot's source id), `mask` / `corners` from the peering bits, `probability`, `surface`, `collision` (polygons are rectangles, moved from tile-centre to top-left coordinates), `anim`, `origin` |
| `terrain_set_N/mode` (0, 1, 2) | `terrain_sets[].mode` (`blob47`, `corners4`, `sides4`) |
| map scene (`assets/maps/<name>.tscn`, painted by Godot's solver from mapbuild's plan) | `map`: the plan itself (placed tiles as tiles, overlay terrains as terrain cells, props as objects) |
| `FontFile` loaded from the `.fnt` | `font` (the same file, parsed) |
| `NinePatchRect` `patch_margin_*`, Theme `StyleBoxTexture` margins | `ui_kit` part `margins` |
| `GPUParticles2D` scene | `particles` (the JSON Dotwork writes beside it for other engines) |
| `ParallaxBackground` / scroll shader / weather `CanvasLayer` | `background` layers |
| Godot-only: Theme `.tres`, shader materials, lit `CanvasTexture` copies, diorama `Node3D`, screen scenes, `project.godot` icon and splash | not in the manifest (each engine's shell and shader recipes cover them; normal maps and the PNGs are) |

## Which lane makes which kind
| Lane (spec key) | Kinds |
|---|---|
| characters, npcs, vehicles, animprops | `animated_sprite` (vehicles: `idle_<dir>` in 8 directions) |
| effects, hitfx, spells, status, vfx, balloons | `animated_sprite` (vfx projectiles: `fly` and `trail`; particle kinds: `particles`) |
| props | `sprite` with collision (`"scene": false`: no collision) |
| enemies | `sprite` with `shadow` |
| icons | `icon`; portraits: `portrait` (+ `animated_sprite` for talking frames) |
| ground (+ its map), tiles, platforms, iso, Pixelorama tilemaps | `tileset`, `map` |
| fonts, bdf | `font` (glyph symbols exported as images: `ui_kit` `symbols`) |
| windows, widgets, uikit, ui | `ui_kit` |
| battle_bgs, scenes, img2px, platforms (background), weather | `background` |
| transitions | `transition`; lighting: `normal_map`; anything else: `image` |

## Golden fixture and loaded result
`data/golden/dotwork/` holds one small pack with every kind: `assets/` is an assets folder (its manifest is
`data/golden/dotwork/assets/dotwork/golden.assets.json`) and `expected.json` is what `assetspec.expected()` makes of it: the **loaded
result**. It is built without a GPU by `tests/golden_assets.py` through Dotwork's own writers and lane functions, and
the exam checks it is current.

| In `expected.json` | What an importer compares |
|---|---|
| `animated_sprite/<name>.clips.<clip>` | frame count, each frame's rect (in its texture), seconds per frame, length, loop, pivot, texture (the sheet, or null when the frames are separate files) |
| `animated_sprite/<name>.directions` | the action / direction table |
| `sprite/<name>` | size, pivot, collision rects |
| `icon`, `portrait` | sizes; expression names and the talking animation |
| `tileset/<name>` | tile size, shape, tile count, tiles with collision, animated tiles, terrain names, the masks (or corners) per terrain |
| `map/<name>` | size, cells per layer, every terrain cell as `[x, y, mask, [atlas, col, row]]` (the first tile with that mask), objects as `[asset, x, y]` |
| `font/<name>` | line height, base, char count, page count, the glyph of `A` |
| `ui_kit/<name>` | each part's size, margins and hotspot |
| `background/<name>` | each layer as `[w, h, vx, vy, repeat]` |

Numbers are rounded to 6 decimals; compare with a tolerance of 1e-6. The fixture's art is drawn to be told apart at a
glance (a figure whose legs move, coloured blob tiles), so an importer's own viewer shows when a rect or pivot is off.

## Commands
```
python tools/art/dotwork/dotwork.py manifest              # rebuild and validate every pack's asset manifest
python tools/art/dotwork/dotwork.py manifest --check      # validate only; exit 1 when one is stale or invalid
python tools/art/dotwork/assetspec.py validate assets/dotwork/*.assets.json   # any manifest, standard library only
python tools/art/dotwork/assetspec.py expected data/golden/dotwork/assets/dotwork/golden.assets.json
python tools/art/dotwork/tests/golden_assets.py --check   # the fixture is current (--write rebuilds it)
python tools/art/dotwork/tests/test_asset_manifest.py     # the exam (offline, about half a minute)
DOTWORK_LIVE_GROUND=1 python tools/art/dotwork/tests/test_asset_manifest.py LiveGroundExam   # with GODOT_BIN, COMFYUI_ROOT
```
The live case renders a small ground pack and has Godot paint its map: on 2026-11-11 (Godot 4.7.2) all 25 terrain
cells Godot's solver chose held the tile the blob rule names, the animated solid water included.

## How to write an importer
The importer is engine code that turns a manifest into the engine's own objects, plus a test in the engine's own
runner (`python tools/dev.py test`) that loads `data/golden/dotwork/` and compares with `expected.json`. Then the
engine's issue is "wire the importer into the starter scene".

1. **Find the manifests**: every `*.assets.json` in `<assets_dir>/dotwork/`. Check `format` and the major `version`;
   refuse another major with a clear error.
2. **Resolve paths**: `join(dirname(manifest), base, path)`. Every texture: nearest filtering, no mipmaps, no
   compression, clamp (repeat only for `background` layers on their `repeat` axes).
3. **Core kinds first**, in this order: `sprite`, `animated_sprite`, `icon`, `portrait`, `font`, `ui_kit`, `tileset`,
   `map` (a map needs its tileset, a portrait its animation). Skip unknown kinds and the extra kinds you do not
   support yet with one warning each; ignore unknown fields.
4. **Timing**: use each frame's `duration` (seconds), not `fps` alone; holds matter (an attack's wind-up and hit-stop).
   Where the engine stores a frame rate and whole-number frame counts, pick a rate at which every duration is whole
   (the clip's `fps` times the smallest step of its `holds`, such as 2 x fps for holds of 1.5) or keep your own timer.
5. **Pivots and collision**: convert with the engine's axes (y up: `1 - py / h`), keep collision rects in the same
   space as the sprite.
6. **Tiles**: build a tile per `[atlas, col, row]`; a `terrain` map layer resolves with the blob rule above (port
   `cell_mask`), or with the engine's own rule tiles when they give the same masks; a `tiles` layer is placed as is.
7. **Test** with the golden fixture: the same numbers as `expected.json`, then load every real manifest of the game
   and fail on a missing file or a broken asset (the engine's stand-in for Dotwork's Godot `verify`).
8. **Wire it**: the starter scene shows one character walking, a prop, a tile map and a label in the font when the
   game has them.

Per-engine notes (engine versions as the overlays pin them; API names marked **(verify)** are from memory, not checked
against the installed engine):

- **web, Phaser 4 (#55).** Load the manifest with the scene loader's JSON, then the PNGs. Sheets become a spritesheet
  or an atlas texture with named frames (`<clip>_<i>` from each rect); `anims.create` with per-frame `duration`.
  Phaser's per-frame `duration` adds to the clip's base rate rather than replacing it **(verify)**: either set the
  base so each frame's total equals its `duration`, or drive frames from a small timer. Pivot: `setOrigin(px / w, py / h)`
  (y down, no flip). Fonts: Phaser's bitmap text parses BMFont XML **(verify)**: build its font data from `chars` or
  convert to XML at load. Tilemaps: create a blank tilemap and `putTileAt` per cell after resolving terrain layers;
  collision rects become Arcade bodies or tile collision data. 9-slice: Phaser's NineSlice game object takes the four
  margins. Tests: Vitest on the manifest logic (`dev.py test`), the browser smoke for drawing.
- **web-3d, Three.js (#56).** Sprites are `PlaneGeometry` quads with a `MeshBasicMaterial` (or `SpriteMaterial`),
  `NearestFilter`, `colorSpace` sRGB, `alphaTest` for hard edges. Animate by moving the texture's `offset` / `repeat`
  over the sheet rect (UV y is up: `v = 1 - (y + h) / sheetH`). The pivot is the quad's origin shift. Tiles: one
  `InstancedMesh` per atlas with per-instance UV offsets, or one merged geometry per layer; the 2.5D look follows
  Dotwork's diorama lane (tiles as planes, props and characters as billboards that turn only around y). Fonts: draw
  glyph quads from `chars`. Tests: Vitest.
- **Unity (#57).** An editor importer (a `ScriptedImporter` for `.assets.json`, or an `AssetPostprocessor` plus a menu
  item run through `dev.py exec`) slices each sheet with `SpriteMetaData` rects (Unity's rect origin is bottom-left:
  `y = sheetH - y - h`) and pivots (`SpriteAlignment.Custom`, `(px / w, 1 - py / h)`), sets pixels per unit to the tile
  size, Point filter, no compression. Clips become `AnimationClip`s with `ObjectReferenceKeyframe` sprite keys at the
  cumulative frame times (`loopTime` from `loop`) and an `AnimatorController` or a small player component. Tiles:
  `Tile` assets per atlas cell; blob terrain through a custom `TileBase` that computes `cell_mask`, or 2D Tilemap
  Extras' rule tiles **(verify the package is wanted)**; collision as custom physics shapes and a `TilemapCollider2D`.
  Fonts: a TextMeshPro font asset from `chars` **(verify)**, or a sprite-based label. Tests: an EditMode test that
  imports `data/golden/dotwork/` into a temporary folder and compares.
- **Unreal (#58, done: `Content/Python/kit_dotwork/`, UE 5.8).** An editor Python script through `dev.py exec` with
  Paper2D: a `PaperSprite` per frame (source texture = the sheet, source UV and dimension = the rect, pivot mode
  custom; `CustomPivotPoint` is in the texture's own pixels, y down, so it is `rect.xy + pivot` and Paper2D flips to
  its X right, Z up plane itself), a `PaperFlipbook` per clip (whole `FrameRun` counts at the clip's fps times the
  smallest factor that makes every duration whole), textures nearest, no mips, uncompressed, Pixels2D group. Tiles:
  a `PaperTileSet` per atlas and a `PaperTileMap` with terrain layers resolved by a port of `cell_mask`; Paper2D
  draws tile layer 0 on top, so manifest layers go in reversed. The Python API reaches per-tile collision
  (`per_tile_data`; box shapes are filled with `SpriteGeometryShape.import_text`, their fields are read-only) but
  not a layer's name (the layers come from Paper2D's own Tiled importer) nor an offline `Font`'s page textures (set
  with the `set` console command, which only the pythonscript commandlet runs). An offline Font keeps one advance
  per glyph plus one font-wide kerning: xoffset and kerning pairs are lost. Not in Paper2D: tile animation,
  probability variants, additive blend. Tests: `dev.py test` runs the golden check and every game manifest through
  the commandlet, and as `Editor.Python.<Game>.kit_dotwork.*` automation tests with the PythonAutomationTest plugin.
- **Bevy 0.20 (#59).** Plain Rust with `serde_json` (already a dependency): a `TextureAtlasLayout` per sheet from the
  rects (or one image per frame), an animation component with per-frame `Duration`s and a system that advances it,
  `Anchor` from the pivot (centre-relative, y up: `(px / w - 0.5, 0.5 - py / h)` **(verify the Anchor API in 0.20)**),
  `ImageSampler::nearest()`. Tiles: one sprite per cell under a parent entity, or `bevy_ecs_tilemap` if the game adds
  it (the kit adds no crate); terrain layers resolved by `cell_mask`. Fonts: glyph sprites from `chars`. Tests: plain
  `cargo test` on the loader (no window), comparing with `expected.json`.
- **C++ / SDL3 (#60).** `nlohmann-json` (already in the overlay's vcpkg manifest) reads the manifest. SDL3 itself loads BMP; PNG needs a
  decoder: SDL3_image from vcpkg, or `stb_image`, or SDL's own PNG loader if the pinned SDL3 has one **(verify)**.
  `SDL_RenderTexture` with source rects from the frames, destination offset by the pivot, `SDL_SCALEMODE_NEAREST`
  (or the pixel-art scale mode). Frame timing from `duration`. Tiles: draw cells per layer, terrain layers resolved
  by a C++ port of `cell_mask`. Fonts: glyph quads from `chars`. Tests: doctest on the loader with the golden fixture
  (no window needed for the numbers).
- **LÖVE 11.5 (#61).** The kit's JSON module (`require("src.core.json")`) decodes the manifest. `love.graphics.newImage` with
  `setFilter("nearest", "nearest")`, a `Quad` per rect, `love.graphics.draw(image, quad, x, y, 0, sx, sy, px, py)`
  (the origin arguments are the pivot, y down, no conversion). Timing from `duration`. Tiles: a `SpriteBatch` per
  atlas and layer. Fonts: LÖVE reads BMFont text files with `love.graphics.newFont(fntPath)` **(verify against 11.5;
  it takes the `.fnt` path and finds the pages beside it)**, else build an image font from `chars`. Tests: the kit's
  Lua test runner (`dev.py test`) on the loader, headless.
- **RPG Maker MZ (#62).** MZ has fixed formats, so this importer is a converter (a Node script run by `dev.py`, or a
  plugin for runtime use), not a loader. Characters: compose MZ character sheets (3 frames by 4 directions per
  character, `$` prefix for a single-character file) from `walk_<dir>` (pick 3 frames: the stride frames, standing
  in the middle), scaling or padding to MZ's cell size **(verify the cell size against the project)**. Faces (144 x 144
  cells) from `portrait` expressions; side-view battlers from battle poses where the game uses them. Window skin:
  compose MZ's window skin (img/system/Window.png in the MZ project) from a `ui_kit` window part; icons into `IconSet.png` (32 px cells, MZ default
  **(verify)**). Tilesets: MZ's A1 to E layouts and its own autotile shapes differ from blob47; converting needs MZ's
  autotile quarter-tile layout, so start with B to E tiles (plain tiles) and leave autotiles to a later step. Tests:
  Node test on the converter's numbers against `expected.json` (the clip and portrait parts), plus the MZ smoke.

## Limits
- One manifest per pack. A game with several packs has several files; importers load them all (names are unique per
  pack, not across packs: prefix with the pack when that matters).
- A map is the plan Dotwork hands Godot. A map scene edited by hand in Godot, or a Dotwork-built map edited in
  Pixelorama and re-exported, keeps the planned layers in the manifest (only the Godot scene changes); Pixelorama
  tilemaps of your own are exported cell by cell and are exact.
- Maps are painted from terrain cells in every engine; tile variants are a random pick (by `probability`), so two
  engines show the same shapes but not always the same variant on a cell.
- Godot-only resources (Themes, shader materials, lit copies, dioramas, screen scenes) are not described: the kit's
  shells, shader recipes (`tools/shaders/`) and each engine's own UI cover those parts.
- A pack built before records existed (Dotwork before 0.15) gets no animated sprites, tilesets or maps in its asset
  manifest until the pack runs again: its provenance manifest has no records, and a hand-polish re-export adds none
  (so an untouched round trip keeps changing no file). Its PNGs still appear, as `image`, `icon`, `ui_kit` and so on.
