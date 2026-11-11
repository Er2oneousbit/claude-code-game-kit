// ---------------------------------------------------------------------------
// dotwork/defs.rs
// Purpose : The Dotwork asset manifest as written (spec version 1), for serde: one struct per asset kind and part.
// Usage   : manifest.rs only: Header::deserialize(&doc), SpriteDef::deserialize(&asset), ...
// Notes   : serde ignores fields these structs do not name, as the spec's versioning asks (a minor version may add
//           optional fields). Optional fields default as the spec says (base ".", scale 1, tint true, shape square).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
pub(super) struct Header {
    pub(super) format: String,
    pub(super) version: String,
    pub(super) pack: String,
    #[serde(default = "dot")]
    pub(super) base: String,
    pub(super) assets: Vec<Value>,
}

pub(super) fn dot() -> String {
    ".".into()
}

pub(super) fn one() -> f64 {
    1.0
}

pub(super) fn yes() -> bool {
    true
}

#[derive(Deserialize)]
pub(super) struct AnimatedSpriteDef {
    #[serde(default)]
    pub(super) role: String,
    #[serde(default)]
    pub(super) blend: Option<String>,
    pub(super) clips: Vec<ClipDef>,
    #[serde(default)]
    pub(super) directions: BTreeMap<String, BTreeMap<String, String>>,
}

#[derive(Deserialize)]
pub(super) struct ClipDef {
    pub(super) name: String,
    #[serde(rename = "loop")]
    pub(super) looping: bool,
    pub(super) frame_size: [u32; 2],
    pub(super) pivot: [f64; 2],
    #[serde(default)]
    pub(super) sheet: Option<String>,
    pub(super) frames: Vec<FrameDef>,
}

#[derive(Deserialize)]
pub(super) struct FrameDef {
    pub(super) file: String,
    pub(super) rect: [u32; 4],
    pub(super) duration: f64,
}

#[derive(Deserialize)]
pub(super) struct CollisionDef {
    pub(super) rect: [f64; 4],
    #[serde(default)]
    pub(super) one_way: bool,
}

#[derive(Deserialize)]
pub(super) struct SpriteDef {
    #[serde(default)]
    pub(super) role: String,
    pub(super) image: String,
    pub(super) size: [u32; 2],
    pub(super) pivot: [f64; 2],
    #[serde(default)]
    pub(super) collision: Vec<CollisionDef>,
    #[serde(default)]
    pub(super) shadow: Option<ShadowDef>,
}

#[derive(Deserialize)]
pub(super) struct ShadowDef {
    pub(super) image: String,
    pub(super) offset: [f64; 2],
}

#[derive(Deserialize)]
pub(super) struct IconDef {
    pub(super) sizes: Vec<IconSizeDef>,
}

#[derive(Deserialize)]
pub(super) struct IconSizeDef {
    pub(super) size: u32,
    pub(super) image: String,
}

#[derive(Deserialize)]
pub(super) struct PortraitDef {
    pub(super) size: [u32; 2],
    pub(super) expressions: Vec<NamedImageDef>,
    #[serde(default)]
    pub(super) animation: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct NamedImageDef {
    pub(super) name: String,
    pub(super) image: String,
}

#[derive(Deserialize)]
pub(super) struct FontDef {
    pub(super) pages: Vec<String>,
    pub(super) line_height: u32,
    pub(super) base: u32,
    #[serde(default = "one")]
    pub(super) scale: f64,
    #[serde(default = "yes")]
    pub(super) tint: bool,
    pub(super) chars: Vec<[i64; 9]>,
    #[serde(default)]
    pub(super) kerning: Vec<[i64; 3]>,
}

#[derive(Deserialize)]
pub(super) struct UiKitDef {
    pub(super) parts: Vec<UiPartDef>,
}

#[derive(Deserialize)]
pub(super) struct UiPartDef {
    pub(super) name: String,
    #[serde(default)]
    pub(super) role: String,
    pub(super) image: String,
    pub(super) size: [u32; 2],
    #[serde(default = "one")]
    pub(super) scale: f64,
    #[serde(default)]
    pub(super) state: Option<String>,
    #[serde(default)]
    pub(super) control: Option<String>,
    #[serde(default)]
    pub(super) margins: Option<[f64; 4]>,
    #[serde(default)]
    pub(super) hotspot: Option<[f64; 2]>,
    #[serde(default)]
    pub(super) glyph: Option<String>,
}

#[derive(Deserialize)]
pub(super) struct TilesetDef {
    pub(super) tile_size: [u32; 2],
    #[serde(default = "square")]
    pub(super) shape: String,
    #[serde(default)]
    pub(super) terrain_sets: Vec<TerrainSetDef>,
    pub(super) atlases: Vec<AtlasDef>,
    #[serde(default)]
    pub(super) stamps: Vec<StampDef>,
}

pub(super) fn square() -> String {
    "square".into()
}

#[derive(Deserialize)]
pub(super) struct TerrainSetDef {
    pub(super) id: u32,
    pub(super) mode: String,
    pub(super) terrains: Vec<TerrainDef>,
}

#[derive(Deserialize)]
pub(super) struct TerrainDef {
    pub(super) id: u32,
    pub(super) name: String,
}

#[derive(Deserialize)]
pub(super) struct AtlasDef {
    pub(super) id: u32,
    #[serde(default)]
    pub(super) name: String,
    #[serde(default)]
    pub(super) role: String,
    pub(super) image: String,
    pub(super) tile_size: [u32; 2],
    pub(super) columns: u32,
    pub(super) rows: u32,
    pub(super) tiles: Vec<TileDef>,
}

#[derive(Deserialize)]
pub(super) struct TileDef {
    pub(super) col: u32,
    pub(super) row: u32,
    #[serde(default)]
    pub(super) terrain_set: Option<u32>,
    #[serde(default)]
    pub(super) terrain: Option<u32>,
    #[serde(default)]
    pub(super) mask: Option<u8>,
    #[serde(default)]
    pub(super) corners: Option<BTreeMap<String, u32>>,
    #[serde(default)]
    pub(super) probability: Option<f64>,
    #[serde(default)]
    pub(super) surface: Option<String>,
    #[serde(default)]
    pub(super) collision: Vec<CollisionDef>,
    #[serde(default)]
    pub(super) anim: Option<TileAnimDef>,
    #[serde(default)]
    pub(super) origin: Option<[f64; 2]>,
}

#[derive(Deserialize)]
pub(super) struct TileAnimDef {
    pub(super) frames: u32,
    pub(super) fps: f64,
}

#[derive(Deserialize)]
pub(super) struct StampDef {
    pub(super) name: String,
    pub(super) size: [u32; 2],
    #[serde(default)]
    pub(super) solid: bool,
    pub(super) tiles: Vec<[u32; 3]>,
}

#[derive(Deserialize)]
pub(super) struct MapDef {
    pub(super) tileset: String,
    pub(super) size: [u32; 2],
    pub(super) tile_size: [u32; 2],
    pub(super) layers: Vec<LayerDef>,
    #[serde(default)]
    pub(super) objects: Vec<ObjectDef>,
}

#[derive(Deserialize)]
pub(super) struct LayerDef {
    pub(super) name: String,
    pub(super) kind: String,
    pub(super) cells: Vec<Vec<i64>>,
    #[serde(default)]
    pub(super) terrain_set: Option<u32>,
    #[serde(default)]
    pub(super) terrain: Option<u32>,
    #[serde(default)]
    pub(super) opacity: Option<f32>,
}

#[derive(Deserialize)]
pub(super) struct ObjectDef {
    pub(super) asset: String,
    pub(super) x: f64,
    pub(super) y: f64,
}

// {{FOOTER}}
