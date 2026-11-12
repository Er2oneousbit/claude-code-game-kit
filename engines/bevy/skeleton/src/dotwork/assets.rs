// ---------------------------------------------------------------------------
// dotwork/assets.rs
// Purpose : What the Dotwork importer builds from a manifest: a Pack of Bevy-ready objects per manifest (clips with
//           TextureAtlasLayouts, Durations and Anchors, sprites with collision Rects, tilesets, resolved maps, bitmap
//           fonts, UI kits, icons, portraits, and the extra kinds: backgrounds, particles, transitions, normal maps
//           and loose images).
// Usage   : let pack = manifest::read_manifest(..)?;  pack.animated["hero"].directed("walk", "e")
//           map.top_left(&tileset, &cell)   // where a placed cell's image lands, in map pixels (y down)
// Notes   : Plain values, no handles: tests compare them without a window, and dotwork/mod.rs turns them into
//           sprites. Every path is an asset path (relative to the asset folder) that AssetServer::load takes.
//           Coordinates are Bevy's: y up, pivots as Anchors, collision boxes around the pivot or tile centre. The
//           map helpers (centre, top_left) answer in the spec's map pixels, y down, the numbers expected.json holds;
//           dotwork/mod.rs flips y when it spawns.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
//           Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): a tile's key and
//           origin, map layers of kind stamps, a cell's key (mask or corner bits), the five extra kinds
// ---------------------------------------------------------------------------
use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::time::Duration;

use bevy::image::TextureAtlasLayout;
use bevy::math::{IVec2, Rect, URect, UVec2, Vec2};
use bevy::sprite::{Anchor, TextureSlicer};
use serde_json::Value;

use super::autotile::{self, Shape, TerrainMode};

/// One manifest, loaded. Names are unique per kind within a pack.
#[derive(Debug, Default)]
pub struct Pack {
    pub name: String,
    /// The manifest's own path on disk.
    pub manifest: PathBuf,
    pub animated: BTreeMap<String, AnimatedSprite>,
    pub sprites: BTreeMap<String, SpriteAsset>,
    pub icons: BTreeMap<String, Icon>,
    pub portraits: BTreeMap<String, Portrait>,
    pub fonts: BTreeMap<String, BitmapFont>,
    pub ui_kits: BTreeMap<String, UiKit>,
    pub tilesets: BTreeMap<String, Tileset>,
    pub maps: BTreeMap<String, TileMap>,
    pub backgrounds: BTreeMap<String, Background>,
    pub particles: BTreeMap<String, Particles>,
    pub transitions: BTreeMap<String, Transition>,
    pub normal_maps: BTreeMap<String, NormalMap>,
    pub images: BTreeMap<String, ImageAsset>,
    /// `kind/name` of every asset skipped on purpose (unknown kinds: a newer spec minor version).
    pub skipped: Vec<String>,
    /// Skipped kinds and other things worth a line in the log.
    pub warnings: Vec<String>,
    /// Broken assets (missing files, bad fields): each is left out of the pack.
    pub errors: Vec<String>,
}

/// Named clips of frames with timing, loop flag and pivot (characters, effects, talking portraits).
#[derive(Debug, Clone)]
pub struct AnimatedSprite {
    pub name: String,
    pub role: String,
    /// `blend: add`. Bevy 0.20 sprites have no additive mode (SpriteAlphaMode is Opaque, Mask or Blend), so these
    /// draw with normal blending until the game adds a material for them.
    pub additive: bool,
    /// In the manifest's order (Godot's SpriteFrames order).
    pub clips: Vec<Clip>,
    /// `{action: {direction: clip}}`, such as walk -> s -> walk_s.
    pub directions: BTreeMap<String, BTreeMap<String, String>>,
}

impl AnimatedSprite {
    pub fn clip(&self, name: &str) -> Option<&Clip> {
        self.clips.iter().find(|c| c.name == name)
    }

    /// The clip for an action facing a direction (`walk`, `e`), through the directions table.
    pub fn directed(&self, action: &str, dir: &str) -> Option<&Clip> {
        self.directions
            .get(action)
            .and_then(|dirs| dirs.get(dir))
            .and_then(|clip| self.clip(clip))
    }
}

#[derive(Debug, Clone)]
pub struct Clip {
    pub name: String,
    pub texture: ClipTexture,
    /// Seconds each frame shows (the manifest's `duration`, holds included).
    pub durations: Vec<Duration>,
    pub looping: bool,
    pub frame_size: UVec2,
    /// The pivot, centre-relative and y up.
    pub anchor: Anchor,
}

impl Clip {
    pub fn frame_count(&self) -> usize {
        self.durations.len()
    }

    /// Frame `i`'s rectangle in its own texture (the sheet, or the frame's file).
    pub fn frame_rect(&self, i: usize) -> URect {
        match &self.texture {
            ClipTexture::Sheet { layout, .. } => layout.textures[i],
            ClipTexture::Files { rects, .. } => rects[i],
        }
    }
}

/// Where a clip's frames are: one horizontal sheet (an atlas over it) or one PNG per frame.
#[derive(Debug, Clone)]
pub enum ClipTexture {
    Sheet { image: String, layout: TextureAtlasLayout },
    Files { images: Vec<String>, rects: Vec<URect> },
}

/// A collision box: a rectangle around the owner's origin (a sprite's pivot, a tile's centre), y up.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Collider {
    pub rect: Rect,
    /// Collides from above only (platform tiles).
    pub one_way: bool,
}

/// One image with a pivot, optional collision boxes and a contact shadow (props, enemies).
#[derive(Debug, Clone)]
pub struct SpriteAsset {
    pub name: String,
    pub role: String,
    pub image: String,
    pub size: UVec2,
    pub anchor: Anchor,
    pub colliders: Vec<Collider>,
    /// The shadow's image and its centre's offset from the pivot, y up.
    pub shadow: Option<(String, Vec2)>,
}

/// One design at several pixel sizes, smallest first.
#[derive(Debug, Clone)]
pub struct Icon {
    pub name: String,
    pub sizes: Vec<(u32, String)>,
}

impl Icon {
    /// The image of the smallest size at least `px` big, else the biggest.
    pub fn image_for(&self, px: u32) -> Option<&str> {
        self.sizes
            .iter()
            .find(|(s, _)| *s >= px)
            .or(self.sizes.last())
            .map(|(_, image)| image.as_str())
    }
}

/// A bust and its expressions (`neutral` first); `animation` names the talking-frames AnimatedSprite.
#[derive(Debug, Clone)]
pub struct Portrait {
    pub name: String,
    pub size: UVec2,
    pub expressions: Vec<(String, String)>,
    pub animation: Option<String>,
}

impl Portrait {
    pub fn expression(&self, name: &str) -> Option<&str> {
        self.expressions
            .iter()
            .find(|(n, _)| n == name)
            .map(|(_, image)| image.as_str())
    }
}

/// An AngelCode BMFont as glyph rects on its pages.
#[derive(Debug, Clone)]
pub struct BitmapFont {
    pub name: String,
    /// One image per page, page 0 first, with an atlas of its glyphs.
    pub pages: Vec<(String, TextureAtlasLayout)>,
    pub glyphs: BTreeMap<u32, Glyph>,
    pub line_height: u32,
    /// Pixels from a line's top to the baseline.
    pub base: u32,
    /// The scale Dotwork already drew the pages and metrics at (informational: draw the glyphs 1:1, never scale
    /// them by this again).
    pub scale: f32,
    /// White ink that takes a colour (true), or coloured art drawn as is (false).
    pub tint: bool,
    pub kerning: HashMap<(u32, u32), i32>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Glyph {
    pub page: usize,
    /// Index in its page's atlas.
    pub index: usize,
    /// BMFont's xoffset and yoffset: from the pen to the glyph's top-left, y down.
    pub offset: IVec2,
    pub advance: i32,
}

impl BitmapFont {
    pub fn glyph_rect(&self, g: &Glyph) -> URect {
        self.pages[g.page].1.textures[g.index]
    }

    pub fn kerning(&self, first: u32, second: u32) -> i32 {
        self.kerning.get(&(first, second)).copied().unwrap_or(0)
    }
}

/// The images of one UI set.
#[derive(Debug, Clone)]
pub struct UiKit {
    pub name: String,
    pub parts: Vec<UiPart>,
}

impl UiKit {
    pub fn part(&self, name: &str) -> Option<&UiPart> {
        self.parts.iter().find(|p| p.name == name)
    }
}

#[derive(Debug, Clone)]
pub struct UiPart {
    pub name: String,
    /// window, button, panel, texture, gauge, cursor, glyph, symbol, 9slice, logo
    pub role: String,
    pub image: String,
    pub size: UVec2,
    /// The scale Dotwork already drew the image and margins at (informational: draw the part 1:1).
    pub scale: f32,
    pub state: Option<String>,
    pub control: Option<String>,
    /// 9-slice margins as Bevy's slicer: min_inset = (left, top), max_inset = (right, bottom).
    pub slicer: Option<TextureSlicer>,
    /// A cursor's click point, in the image's pixels (y down).
    pub hotspot: Option<Vec2>,
    pub glyph: Option<String>,
}

/// Atlases of tiles with terrains, masks or corners, collision and animation.
#[derive(Debug, Clone)]
pub struct Tileset {
    pub name: String,
    pub tile_size: UVec2,
    pub shape: Shape,
    pub terrains: Vec<Terrain>,
    pub atlases: Vec<TileAtlas>,
    pub stamps: Vec<Stamp>,
}

#[derive(Debug, Clone)]
pub struct Terrain {
    pub set: u32,
    pub id: u32,
    pub name: String,
    pub mode: TerrainMode,
}

#[derive(Debug, Clone)]
pub struct TileAtlas {
    pub id: u32,
    pub name: String,
    pub role: String,
    pub image: String,
    pub tile_size: UVec2,
    pub columns: u32,
    /// One rect per atlas cell, row by row: a tile's index is row * columns + col.
    pub layout: TextureAtlasLayout,
    pub tiles: Vec<Tile>,
}

#[derive(Debug, Clone)]
pub struct Tile {
    pub col: u32,
    pub row: u32,
    pub index: usize,
    /// (terrain set, terrain).
    pub terrain: Option<(u32, u32)>,
    pub mask: Option<u8>,
    /// Terrain id per corner (-1: any other terrain), keys sorted (bottom_left, bottom_right, top_left, top_right;
    /// iso bottom, left, right, top).
    pub corners: Option<BTreeMap<String, i64>>,
    /// The key a terrain cell must have to draw this tile: the mask (blob47, sides4) or the corner bits of the
    /// tile's own terrain (corners4). None on a plain tile, or a terrain tile without a key.
    pub key: Option<u8>,
    /// The relative weight among the tiles of the same terrain and key (0 is never picked). f64 like the
    /// reference, so the pick's sums agree to the last bit.
    pub probability: f64,
    pub surface: Option<String>,
    /// Around the tile's centre, y up.
    pub colliders: Vec<Collider>,
    /// Atlas indices and durations of an animated tile (its frames sit in the next cells to the right).
    pub anim: Option<(Vec<usize>, Vec<Duration>)>,
    /// The point of the image drawn on the cell's centre, in the image's pixels, y down (the manifest's `origin`,
    /// else the atlas tile's centre).
    pub origin: [f64; 2],
    /// The same point as an Anchor (centre-relative, y up), for the tile's Sprite.
    pub anchor: Anchor,
}

#[derive(Debug, Clone)]
pub struct Stamp {
    pub name: String,
    pub size: UVec2,
    pub solid: bool,
    /// [atlas, col, row] in reading order.
    pub tiles: Vec<[u32; 3]>,
}

impl Tileset {
    pub fn atlas(&self, id: u32) -> Option<&TileAtlas> {
        self.atlases.iter().find(|a| a.id == id)
    }

    pub fn tile(&self, atlas: u32, col: u32, row: u32) -> Option<&Tile> {
        self.atlas(atlas)?.tiles.iter().find(|t| t.col == col && t.row == row)
    }
}

/// Layers of placed tiles (terrain layers resolved, stamps expanded) and objects at pixel positions.
#[derive(Debug, Clone)]
pub struct TileMap {
    pub name: String,
    pub tileset: String,
    /// Cells.
    pub size: UVec2,
    pub cell_size: UVec2,
    pub shape: Shape,
    pub layers: Vec<MapLayer>,
    pub objects: Vec<MapObject>,
}

impl TileMap {
    /// The centre of cell (x, y) in map pixels, y down (the spec's "Placing tiles": squares in rows, isometric
    /// diamonds in Godot's diamond-down layout).
    pub fn centre(&self, x: i64, y: i64) -> Vec2 {
        autotile::cell_centre(self.shape, x, y, self.cell_size.as_vec2())
    }

    /// Where a placed cell's image lands: its top-left corner in map pixels, y down (the cell's centre less the
    /// tile's origin). None for an empty cell or a tile the tileset lacks.
    pub fn top_left(&self, ts: &Tileset, cell: &MapCell) -> Option<[f64; 2]> {
        let [atlas, col, row] = cell.tile?;
        let tile = ts.tile(atlas, col, row)?;
        let c = self.centre(cell.x, cell.y).as_dvec2();
        Some([c.x - tile.origin[0], c.y - tile.origin[1]])
    }
}

/// The spec's map layer kinds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LayerKind {
    /// Cells placed as listed.
    Tiles,
    /// Painted cells, each resolved to a tile of the layer's terrain by its key and the cell roll.
    Terrain,
    /// Multi-cell pieces (a door), each expanded into its tiles.
    Stamps,
}

#[derive(Debug, Clone)]
pub struct MapLayer {
    pub name: String,
    pub kind: LayerKind,
    /// The terrain painted, for terrain layers: (set, terrain).
    pub terrain: Option<(u32, u32)>,
    pub opacity: f32,
    /// The cells drawn, in draw order: as listed for tiles layers, stamps expanded tile by tile in reading order,
    /// terrain cells sorted by row then column (so on a diamond grid a taller tile overdraws the one above it).
    pub cells: Vec<MapCell>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MapCell {
    pub x: i64,
    pub y: i64,
    /// [atlas, col, row]; None when a terrain cell's key has no tile (warned, drawn empty).
    pub tile: Option<[u32; 3]>,
    /// The key a terrain cell resolved to: its blob mask, side bits or corner bits.
    pub key: Option<u8>,
    pub flags: u8,
}

/// An asset of the pack (a prop sprite) placed with its pivot at a pixel position of the map, y up (y = -pixel y).
#[derive(Debug, Clone, PartialEq)]
pub struct MapObject {
    pub asset: String,
    pub position: Vec2,
}

// ---- The extra kinds -------------------------------------------------------------------------------------------

/// Scrolling layers of a battle background, a scene or a weather sheet, drawn first to last.
#[derive(Debug, Clone)]
pub struct Background {
    pub name: String,
    /// battle, scene, platform, weather, ...
    pub role: String,
    pub layers: Vec<BackgroundLayer>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BackgroundLayer {
    pub name: Option<String>,
    pub image: String,
    /// The art's size in pixels.
    pub size: UVec2,
    /// Pixels per second of the art, y up (the manifest's `vy` negated, like every position here).
    pub velocity: Vec2,
    /// The image tiles seamlessly along x and along y: load it with a repeating sampler on those axes
    /// (`Dotwork::background_image`) and draw it past its edges (`SpriteImageMode::Tiled`, or a quad with UVs
    /// past 1).
    pub repeat_x: bool,
    pub repeat_y: bool,
    /// A weather layer sways sideways by up to this many pixels; move in whole pixels.
    pub wobble_px: f32,
    /// The whole-number scale the art is drawn at.
    pub scale: f32,
}

impl BackgroundLayer {
    /// The manifest's `repeat`: none, x, y or xy.
    pub fn repeat(&self) -> &'static str {
        match (self.repeat_x, self.repeat_y) {
            (false, false) => "none",
            (true, false) => "x",
            (false, true) => "y",
            (true, true) => "xy",
        }
    }
}

/// A particle texture (a white mask the emitter tints) and the emitter as Dotwork wrote it (amount, lifetime,
/// one_shot, colors, ...), for the game's own emitter: Bevy 0.20 ships no particle system.
#[derive(Debug, Clone)]
pub struct Particles {
    pub name: String,
    pub texture: String,
    pub emitter: Value,
}

/// A greyscale wipe image: a pixel is covered once the transition's progress (0 to 1) passes its grey / 255 (the
/// kit's transition shader recipe takes it as its threshold texture).
#[derive(Debug, Clone)]
pub struct Transition {
    pub name: String,
    pub image: String,
    pub size: UVec2,
    /// wipe, iris, spiral, ...
    pub transition: String,
}

/// A normal map and the image it lights (`target`, an asset path). Bevy 0.20's 2D sprites have no normal-map
/// lighting: the game draws the target through its own lit material (the kit's sprite_light recipe) with this
/// image; the importer only loads it.
#[derive(Debug, Clone)]
pub struct NormalMap {
    pub name: String,
    pub image: String,
    pub size: Option<UVec2>,
    pub target: String,
    /// `opengl` (green up, the default) or `directx` (green down).
    pub convention: String,
}

/// A loose image (a logo, a sheet, a particle texture) with an optional pivot.
#[derive(Debug, Clone)]
pub struct ImageAsset {
    pub name: String,
    pub role: String,
    pub image: String,
    pub size: UVec2,
    /// The pivot as an Anchor; Anchor::CENTER when the manifest names none.
    pub anchor: Anchor,
}

// {{FOOTER}}
