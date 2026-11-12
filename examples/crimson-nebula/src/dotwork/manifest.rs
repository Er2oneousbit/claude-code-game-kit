// ---------------------------------------------------------------------------
// dotwork/manifest.rs
// Purpose : Reads one Dotwork asset manifest (<assets>/dotwork/<pack>.assets.json, spec version 1.x:
//           tools/art/dotwork/ASSET_MANIFEST.md) into a Pack of Bevy-ready objects: TextureAtlasLayouts from the rects,
//           per-frame Durations, Anchors from the pivots, collision Rects, tiles with their keys, maps with every
//           terrain cell resolved and every stamp expanded, glyph maps for bitmap fonts, TextureSlicers for 9-slice
//           UI parts, and the extra kinds (backgrounds, particles, transitions, normal maps, images) as data.
// Usage   : let pack = read_manifest(&asset_root.join("dotwork/town.assets.json"), &asset_root)?;
//           pack.errors (broken assets, each left out), pack.warnings (skipped kinds, empty cells, missing targets)
// Notes   : The objects are in assets.rs (re-exported here), the manifest's serde structs in defs.rs, the tile
//           rules in autotile.rs. No App, no window, no GPU: tests/dotwork.rs runs it on data/golden/dotwork/ and
//           compares with expected.json. Paths become asset paths (relative to the asset root, forward slashes)
//           that AssetServer::load takes; every file is checked on disk, and sheets, atlases and font pages are
//           measured from their PNG header. Coordinates turn y up here, once: an Anchor is (px / w - 0.5,
//           0.5 - py / h), a collision box is a Rect around the pivot (or the tile's centre), y up. Every kind of
//           spec 1.1.0 loads; unknown kinds and unknown layer kinds are skipped with one warning each; unknown
//           fields are ignored (serde's default), as the spec's versioning asks.
//
// Pseudocode:
//   read the JSON -> refuse another format or major version -> base = the manifest's folder + "base" ->
//   for each asset in the spec's order (sprite, animated_sprite, icon, portrait, font, ui_kit, tileset, map, then
//   the extra kinds): parse its fields -> check its files -> build the objects (a broken asset is an error and is
//   left out). A tileset gives each terrain tile its key (mask, or corner bits by shape). A map resolves a terrain
//   layer cell by cell: key = cell_mask -> the tiles of the layer's terrain with that key, in atlas order -> pick
//   by probability with cell_roll(x, y, layer index); a stamps layer expands each stamp into its tiles.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
//           Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): corners4 terrain,
//           the variant pick, stamps layers, tile origins, the extra kinds loaded, a cell with no tile warns once
//           per layer, an unknown layer kind is skipped
// ---------------------------------------------------------------------------
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::Path;
use std::time::Duration;

use bevy::image::TextureAtlasLayout;
use bevy::math::{IVec2, Rect, URect, UVec2, Vec2};
use bevy::sprite::{Anchor, BorderRect, TextureSlicer};
use serde::Deserialize;
use serde_json::Value;

pub use super::assets::*;
use super::autotile::{self, Shape, TerrainMode};
use super::defs::*;

/// The manifest's `format`.
pub const FORMAT: &str = "dotwork-assets";
/// The spec major version this importer reads (every 1.x.y).
pub const MAJOR: u64 = 1;
/// Manifests are `<pack>.assets.json` in `<assets>/dotwork/`.
pub const SUFFIX: &str = ".assets.json";
pub const MANIFEST_DIR: &str = "dotwork";
/// The kinds every importer handles, in the order they load (a map needs its tileset).
pub const CORE_KINDS: [&str; 8] = [
    "sprite",
    "animated_sprite",
    "icon",
    "portrait",
    "font",
    "ui_kit",
    "tileset",
    "map",
];
/// The extra kinds (spec "The extra kinds per engine"): loaded after the core kinds, as data plus their images.
pub const EXTRA_KINDS: [&str; 5] = ["background", "particles", "transition", "normal_map", "image"];

// ---- Conversions (y down in the manifest, y up in Bevy) ----------------------------------------------------------

/// A pivot in an image's pixels -> Bevy's centre-relative, y-up Anchor.
pub fn anchor_from_pivot(pivot: [f64; 2], size: UVec2) -> Anchor {
    let (w, h) = (f64::from(size.x.max(1)), f64::from(size.y.max(1)));
    Anchor(Vec2::new((pivot[0] / w - 0.5) as f32, (0.5 - pivot[1] / h) as f32))
}

/// The inverse: an Anchor back to pixels of an image of `size`, y down.
pub fn pivot_from_anchor(anchor: Anchor, size: UVec2) -> [f64; 2] {
    let a = anchor.as_vec();
    [
        (f64::from(a.x) + 0.5) * f64::from(size.x),
        (0.5 - f64::from(a.y)) * f64::from(size.y),
    ]
}

/// `[x, y, w, h]` in an image's pixels (y down) -> a Rect around `origin` (a pixel point of the same image), y up.
pub fn rect_around(rect: [f64; 4], origin: [f64; 2]) -> Rect {
    let [x, y, w, h] = rect;
    Rect::new(
        (x - origin[0]) as f32,
        (origin[1] - y - h) as f32,
        (x + w - origin[0]) as f32,
        (origin[1] - y) as f32,
    )
}

/// The inverse of rect_around: back to `[x, y, w, h]` in image pixels.
pub fn image_rect(rect: Rect, origin: [f64; 2]) -> [f64; 4] {
    let (min, max) = (rect.min.as_dvec2(), rect.max.as_dvec2());
    [min.x + origin[0], origin[1] - max.y, max.x - min.x, max.y - min.y]
}

/// 9-slice margins `[left, top, right, bottom]` -> Bevy's TextureSlicer (min_inset is left and top: the slicing
/// shader compares it with the texture's y-down UV, bevy_sprite_render 0.20 sprite_mesh/functions.wesl).
pub fn slicer_from_margins(m: [f64; 4]) -> TextureSlicer {
    TextureSlicer {
        border: BorderRect {
            min_inset: Vec2::new(m[0] as f32, m[1] as f32),
            max_inset: Vec2::new(m[2] as f32, m[3] as f32),
        },
        ..Default::default()
    }
}

pub fn margins_from_slicer(s: &TextureSlicer) -> [f64; 4] {
    let (min, max) = (s.border.min_inset, s.border.max_inset);
    [min.x, min.y, max.x, max.y].map(f64::from)
}

fn seconds(d: f64) -> Duration {
    Duration::from_secs_f64(if d.is_finite() && d > 0.0 { d } else { 0.0 })
}

fn urect(r: [u32; 4]) -> URect {
    URect::new(r[0], r[1], r[0] + r[2], r[1] + r[3])
}

fn uvec(v: [u32; 2]) -> UVec2 {
    UVec2::new(v[0], v[1])
}

// ---- Reading ---------------------------------------------------------------------------------------------------

/// Where the pack's files are: the asset root on disk and the asset-path prefix the manifest's `base` names.
struct Files<'a> {
    root: &'a Path,
    base: String,
}

impl Files<'_> {
    /// A manifest path -> the asset path AssetServer loads (relative to the asset root). Paths are relative,
    /// forward slashes, no `..` (the spec): anything else is refused.
    fn asset_path(&self, p: &str) -> Result<String, String> {
        if p.is_empty()
            || p.starts_with('/')
            || p.contains('\\')
            || p.contains(':')
            || p.split('/').any(|s| s == ".." || s.is_empty())
        {
            return Err(format!("path {p:?} is not a plain relative path"));
        }
        Ok(if self.base.is_empty() {
            p.to_string()
        } else {
            format!("{}/{p}", self.base)
        })
    }

    /// The asset path of a file that must exist.
    fn existing(&self, p: &str) -> Result<String, String> {
        let asset = self.asset_path(p)?;
        if self.root.join(&asset).is_file() {
            Ok(asset)
        } else {
            Err(format!("{p} is missing"))
        }
    }

    /// The asset path and pixel size of a PNG that must exist.
    fn png(&self, p: &str) -> Result<(String, UVec2), String> {
        let asset = self.existing(p)?;
        let size = png_size(&self.root.join(&asset)).map_err(|e| format!("{p}: {e}"))?;
        Ok((asset, size))
    }
}

/// (width, height) from a PNG's IHDR chunk, without decoding the image.
pub fn png_size(path: &Path) -> Result<UVec2, String> {
    use std::io::Read;
    let mut head = [0u8; 24];
    std::fs::File::open(path)
        .and_then(|mut f| f.read_exact(&mut head))
        .map_err(|e| e.to_string())?;
    if &head[..8] != b"\x89PNG\r\n\x1a\n" || &head[12..16] != b"IHDR" {
        return Err("not a PNG".into());
    }
    let w = u32::from_be_bytes([head[16], head[17], head[18], head[19]]);
    let h = u32::from_be_bytes([head[20], head[21], head[22], head[23]]);
    Ok(UVec2::new(w, h))
}

/// The asset-path prefix of `dir` (a folder on disk) inside `root`: "" for the root itself. None when it lies
/// outside the root (AssetServer could not load from it).
fn prefix_in(root: &Path, dir: &Path) -> Option<String> {
    let rel = dir.strip_prefix(root).ok()?;
    let parts: Vec<String> = rel
        .components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect();
    Some(parts.join("/"))
}

/// Lexically joins `rel` (forward slashes, `..` allowed) onto an asset-path prefix. None when it climbs out.
fn join_prefix(prefix: &str, rel: &str) -> Option<String> {
    let mut parts: Vec<&str> = prefix.split('/').filter(|s| !s.is_empty()).collect();
    for seg in rel.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                parts.pop()?;
            }
            s => parts.push(s),
        }
    }
    Some(parts.join("/"))
}

/// Reads the manifest at `path`. `asset_root` is the folder AssetServer loads from (the game's `assets/`); every
/// path in the pack becomes relative to it. Err for a manifest that cannot be read at all (not JSON, another format,
/// another major version); a broken asset lands in `errors` and the rest still loads.
pub fn read_manifest(path: &Path, asset_root: &Path) -> Result<Pack, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let doc: Value = serde_json::from_str(&text).map_err(|e| format!("{}: not JSON: {e}", path.display()))?;
    read_document(&doc, path, asset_root)
}

/// read_manifest for an already parsed document (`path` names it in messages and places its `base`).
pub fn read_document(doc: &Value, path: &Path, asset_root: &Path) -> Result<Pack, String> {
    let at = path.display();
    let head: Header = Header::deserialize(doc).map_err(|e| format!("{at}: not a Dotwork asset manifest: {e}"))?;
    if head.format != FORMAT {
        return Err(format!("{at}: format {:?}, not {FORMAT:?}", head.format));
    }
    let major = head.version.split('.').next().and_then(|m| m.parse::<u64>().ok());
    if major != Some(MAJOR) {
        return Err(format!(
            "{at}: manifest version {} is not {MAJOR}.x, the spec version this importer reads ({})",
            head.version, "update the importer or rebuild the pack with a matching Dotwork"
        ));
    }
    let dir = path.parent().unwrap_or(Path::new("."));
    let dir_prefix = prefix_in(asset_root, dir).ok_or(format!(
        "{at}: the manifest is not inside the asset folder {}",
        asset_root.display()
    ))?;
    let base =
        join_prefix(&dir_prefix, &head.base).ok_or(format!("{at}: base {:?} leaves the asset folder", head.base))?;
    let files = Files { root: asset_root, base };
    let mut pack = Pack {
        name: head.pack.clone(),
        manifest: path.to_path_buf(),
        ..Default::default()
    };
    // core kinds in load order, then the extra kinds, then whatever is left (unknown) in the manifest's order
    let mut warned_kinds = HashSet::new();
    for kind in CORE_KINDS.iter().chain(EXTRA_KINDS.iter()) {
        for a in &head.assets {
            if a.get("kind").and_then(Value::as_str) == Some(kind) {
                add_asset(&mut pack, &files, kind, a);
            }
        }
    }
    for a in &head.assets {
        let kind = a.get("kind").and_then(Value::as_str).unwrap_or("?");
        if CORE_KINDS.contains(&kind) || EXTRA_KINDS.contains(&kind) {
            continue;
        }
        let name = a.get("name").and_then(Value::as_str).unwrap_or("?");
        pack.skipped.push(format!("{kind}/{name}"));
        if warned_kinds.insert(kind.to_string()) {
            pack.warnings.push(format!(
                "pack {}: unknown kind {kind:?} skipped (a newer spec minor version?)",
                pack.name
            ));
        }
    }
    Ok(pack)
}

/// Builds one asset into the pack, or records why it could not.
fn add_asset(pack: &mut Pack, files: &Files, kind: &str, a: &Value) {
    let name = a.get("name").and_then(Value::as_str).unwrap_or("").to_string();
    let result = match kind {
        "sprite" => parse(a).and_then(|d| sprite(&name, d, files)).map(|v| {
            pack.sprites.insert(name.clone(), v);
        }),
        "animated_sprite" => parse(a).and_then(|d| animated(&name, d, files)).map(|v| {
            pack.animated.insert(name.clone(), v);
        }),
        "icon" => parse(a).and_then(|d| icon(&name, d, files)).map(|v| {
            pack.icons.insert(name.clone(), v);
        }),
        "portrait" => parse(a).and_then(|d| portrait(&name, d, files)).map(|v| {
            if let Some(anim) = &v.animation
                && !pack.animated.contains_key(anim)
            {
                pack.warnings.push(format!(
                    "portrait/{name}: its animation {anim:?} is not in pack {}",
                    pack.name
                ));
            }
            pack.portraits.insert(name.clone(), v);
        }),
        "font" => parse(a).and_then(|d| font(&name, d, files)).map(|v| {
            pack.fonts.insert(name.clone(), v);
        }),
        "ui_kit" => parse(a).and_then(|d| ui_kit(&name, d, files)).map(|v| {
            pack.ui_kits.insert(name.clone(), v);
        }),
        "tileset" => parse(a).and_then(|d| tileset(&name, d, files)).map(|v| {
            pack.tilesets.insert(name.clone(), v);
        }),
        "map" => parse(a).and_then(|d| tile_map(&name, d, pack)).map(|(v, warnings)| {
            pack.warnings.extend(warnings);
            pack.maps.insert(name.clone(), v);
        }),
        "background" => parse(a).and_then(|d| background(&name, d, files)).map(|v| {
            pack.backgrounds.insert(name.clone(), v);
        }),
        "particles" => parse(a).and_then(|d| particles(&name, d, files)).map(|v| {
            pack.particles.insert(name.clone(), v);
        }),
        "transition" => parse(a).and_then(|d| transition(&name, d, files)).map(|v| {
            pack.transitions.insert(name.clone(), v);
        }),
        "normal_map" => parse(a).and_then(|d| normal_map(&name, d, files)).map(|v| {
            pack.normal_maps.insert(name.clone(), v);
        }),
        "image" => parse(a).and_then(|d| image(&name, d, files)).map(|v| {
            pack.images.insert(name.clone(), v);
        }),
        _ => Ok(()),
    };
    if let Err(e) = result {
        pack.errors.push(format!("{kind}/{name}: {e}"));
    }
}

fn parse<T: for<'de> Deserialize<'de>>(a: &Value) -> Result<T, String> {
    T::deserialize(a).map_err(|e| e.to_string())
}

fn sprite(name: &str, d: SpriteDef, files: &Files) -> Result<SpriteAsset, String> {
    let size = uvec(d.size);
    let shadow = match d.shadow {
        Some(s) => Some((
            files.existing(&s.image)?,
            Vec2::new(s.offset[0] as f32, -s.offset[1] as f32),
        )),
        None => None,
    };
    Ok(SpriteAsset {
        name: name.into(),
        role: d.role,
        image: files.existing(&d.image)?,
        size,
        anchor: anchor_from_pivot(d.pivot, size),
        colliders: d
            .collision
            .iter()
            .map(|c| Collider {
                rect: rect_around(c.rect, d.pivot),
                one_way: c.one_way,
            })
            .collect(),
        shadow,
    })
}

fn animated(name: &str, d: AnimatedSpriteDef, files: &Files) -> Result<AnimatedSprite, String> {
    let mut clips = Vec::new();
    for c in d.clips {
        let at = format!("clip {}", c.name);
        if c.frames.is_empty() {
            return Err(format!("{at} has no frames"));
        }
        let frame_size = uvec(c.frame_size);
        for f in &c.frames {
            files.existing(&f.file).map_err(|e| format!("{at}: {e}"))?;
        }
        let texture = match &c.sheet {
            Some(sheet) => {
                let (image, size) = files.png(sheet).map_err(|e| format!("{at}: {e}"))?;
                let mut layout = TextureAtlasLayout::new_empty(size);
                for f in &c.frames {
                    let r = urect(f.rect);
                    if r.max.x > size.x || r.max.y > size.y {
                        return Err(format!("{at}: rect {:?} leaves the {size} sheet", f.rect));
                    }
                    layout.add_texture(r);
                }
                ClipTexture::Sheet { image, layout }
            }
            None => ClipTexture::Files {
                images: c
                    .frames
                    .iter()
                    .map(|f| files.existing(&f.file))
                    .collect::<Result<_, _>>()?,
                rects: c.frames.iter().map(|f| urect(f.rect)).collect(),
            },
        };
        clips.push(Clip {
            name: c.name,
            texture,
            durations: c.frames.iter().map(|f| seconds(f.duration)).collect(),
            looping: c.looping,
            frame_size,
            anchor: anchor_from_pivot(c.pivot, frame_size),
        });
    }
    for (action, dirs) in &d.directions {
        for clip in dirs.values() {
            if !clips.iter().any(|c| &c.name == clip) {
                return Err(format!("directions {action} names clip {clip:?}, which is not here"));
            }
        }
    }
    Ok(AnimatedSprite {
        name: name.into(),
        role: d.role,
        additive: d.blend.as_deref() == Some("add"),
        clips,
        directions: d.directions,
    })
}

fn icon(name: &str, d: IconDef, files: &Files) -> Result<Icon, String> {
    let mut sizes = d
        .sizes
        .into_iter()
        .map(|s| Ok((s.size, files.existing(&s.image)?)))
        .collect::<Result<Vec<_>, String>>()?;
    sizes.sort();
    Ok(Icon {
        name: name.into(),
        sizes,
    })
}

fn portrait(name: &str, d: PortraitDef, files: &Files) -> Result<Portrait, String> {
    Ok(Portrait {
        name: name.into(),
        size: uvec(d.size),
        expressions: d
            .expressions
            .into_iter()
            .map(|e| Ok((e.name, files.existing(&e.image)?)))
            .collect::<Result<_, String>>()?,
        animation: d.animation,
    })
}

fn font(name: &str, d: FontDef, files: &Files) -> Result<BitmapFont, String> {
    let mut pages = Vec::new();
    for p in &d.pages {
        let (image, size) = files.png(p)?;
        pages.push((image, TextureAtlasLayout::new_empty(size)));
    }
    let mut glyphs = BTreeMap::new();
    for c in &d.chars {
        let [id, x, y, w, h, xoff, yoff, adv, page] = *c;
        let page = usize::try_from(page).map_err(|_| format!("char {id}: page {page}"))?;
        let Some((_, layout)) = pages.get_mut(page) else {
            return Err(format!("char {id} is on page {page}, which is not listed"));
        };
        let num = |v: i64| u32::try_from(v).map_err(|_| format!("char {id}: {v} is not a pixel position"));
        let rect = URect::new(num(x)?, num(y)?, num(x + w)?, num(y + h)?);
        if rect.max.x > layout.size.x || rect.max.y > layout.size.y {
            return Err(format!("char {id}: rect leaves page {page}"));
        }
        let index = layout.add_texture(rect);
        glyphs.insert(
            num(id)?,
            Glyph {
                page,
                index,
                offset: IVec2::new(xoff as i32, yoff as i32),
                advance: adv as i32,
            },
        );
    }
    Ok(BitmapFont {
        name: name.into(),
        pages,
        glyphs,
        line_height: d.line_height,
        base: d.base,
        scale: d.scale as f32,
        tint: d.tint,
        kerning: d
            .kerning
            .iter()
            .filter_map(|&[a, b, amount]| Some(((u32::try_from(a).ok()?, u32::try_from(b).ok()?), amount as i32)))
            .collect(),
    })
}

fn ui_kit(name: &str, d: UiKitDef, files: &Files) -> Result<UiKit, String> {
    let parts = d
        .parts
        .into_iter()
        .map(|p| {
            Ok(UiPart {
                image: files.existing(&p.image).map_err(|e| format!("part {}: {e}", p.name))?,
                name: p.name,
                role: p.role,
                size: uvec(p.size),
                scale: p.scale as f32,
                state: p.state,
                control: p.control,
                slicer: p.margins.map(slicer_from_margins),
                hotspot: p.hotspot.map(|h| Vec2::new(h[0] as f32, h[1] as f32)),
                glyph: p.glyph,
            })
        })
        .collect::<Result<_, String>>()?;
    Ok(UiKit {
        name: name.into(),
        parts,
    })
}

fn tileset(name: &str, d: TilesetDef, files: &Files) -> Result<Tileset, String> {
    let shape = Shape::parse(&d.shape).ok_or(format!("unknown shape {:?}", d.shape))?;
    let mut terrains = Vec::new();
    for s in &d.terrain_sets {
        let mode = TerrainMode::parse(&s.mode).ok_or(format!("terrain set {}: unknown mode {:?}", s.id, s.mode))?;
        for t in &s.terrains {
            terrains.push(Terrain {
                set: s.id,
                id: t.id,
                name: t.name.clone(),
                mode,
            });
        }
    }
    let mode_of = |set: u32, id: u32| terrains.iter().find(|t| t.set == set && t.id == id).map(|t| t.mode);
    let mut atlases = Vec::new();
    for a in d.atlases {
        let tile_size = uvec(a.tile_size);
        let (image, size) = files.png(&a.image)?;
        let grid = tile_size * UVec2::new(a.columns, a.rows);
        if grid.x > size.x || grid.y > size.y {
            return Err(format!(
                "atlas {}: {} x {} tiles of {tile_size} need {grid}, the image is {size}",
                a.id, a.columns, a.rows
            ));
        }
        let mut layout = TextureAtlasLayout::from_grid(tile_size, a.columns, a.rows, None, None);
        layout.size = size;
        let centre = [f64::from(tile_size.x) / 2.0, f64::from(tile_size.y) / 2.0];
        let mut tiles = Vec::new();
        for t in a.tiles {
            let at = format!("atlas {} tile {},{}", a.id, t.col, t.row);
            if t.col >= a.columns || t.row >= a.rows {
                return Err(format!("{at} is outside the {} x {} grid", a.columns, a.rows));
            }
            let index = (t.row * a.columns + t.col) as usize;
            let anim = match &t.anim {
                Some(an) if an.frames > 0 => {
                    if t.col + an.frames > a.columns {
                        return Err(format!("{at}: {} animation frames leave the row", an.frames));
                    }
                    let step = seconds(1.0 / an.fps.max(f64::MIN_POSITIVE));
                    Some((
                        (0..an.frames as usize).map(|k| index + k).collect(),
                        vec![step; an.frames as usize],
                    ))
                }
                _ => None,
            };
            let terrain = t.terrain.map(|id| (t.terrain_set.unwrap_or(0), id));
            // the key a cell must have to draw this tile: its mask, or (corners4) the corner bits of its terrain
            let key = match terrain.and_then(|(set, id)| Some((id, mode_of(set, id)?))) {
                Some((_, TerrainMode::Blob47 | TerrainMode::Sides4)) => t.mask,
                Some((id, TerrainMode::Corners4)) => {
                    t.corners.as_ref().and_then(|c| autotile::corners_key(c, id, shape))
                }
                None => None,
            };
            if let Some((set, id)) = terrain
                && mode_of(set, id).is_none()
            {
                return Err(format!(
                    "{at}: terrain {set}/{id} is not in a terrain set of this tileset"
                ));
            }
            let origin = t.origin.unwrap_or(centre);
            tiles.push(Tile {
                col: t.col,
                row: t.row,
                index,
                terrain,
                mask: t.mask,
                corners: t.corners,
                key,
                probability: t.probability.unwrap_or(1.0),
                surface: t.surface,
                colliders: t
                    .collision
                    .iter()
                    .map(|c| Collider {
                        rect: rect_around(c.rect, centre),
                        one_way: c.one_way,
                    })
                    .collect(),
                anim,
                origin,
                anchor: anchor_from_pivot(origin, tile_size),
            });
        }
        atlases.push(TileAtlas {
            id: a.id,
            name: a.name,
            role: a.role,
            image,
            tile_size,
            columns: a.columns,
            layout,
            tiles,
        });
    }
    Ok(Tileset {
        name: name.into(),
        tile_size: uvec(d.tile_size),
        shape,
        terrains,
        atlases,
        stamps: d
            .stamps
            .into_iter()
            .map(|s| Stamp {
                name: s.name,
                size: uvec(s.size),
                solid: s.solid,
                tiles: s.tiles,
            })
            .collect(),
    })
}

/// A map with its terrain layers resolved and its stamps expanded (the spec's "Autotiling and maps"): each painted
/// cell of a terrain layer takes a tile of the layer's terrain whose key is the cell's (`cell_mask`), picked among
/// the tiles with that key, in atlas order, by probability with the cell's roll (`cell_roll(x, y, layer index)`),
/// so every engine shows the same tile; Godot rolls its own dice among the same tiles. A cell with no tile for its
/// key stays empty (one warning per layer). Returns the map and its warnings.
fn tile_map(name: &str, d: MapDef, pack: &Pack) -> Result<(TileMap, Vec<String>), String> {
    let ts = pack
        .tilesets
        .get(&d.tileset)
        .ok_or(format!("tileset {:?} is not in this pack (or did not load)", d.tileset))?;
    let size = uvec(d.size);
    let mut warnings = Vec::new();
    let mut layers = Vec::new();
    // the roll's layer index counts every layer of the manifest, skipped kinds included
    for (li, l) in d.layers.into_iter().enumerate() {
        let at = format!("layer {}", l.name);
        let inside = |x: i64, y: i64| x >= 0 && y >= 0 && x < i64::from(size.x) && y < i64::from(size.y);
        let mut cells = Vec::new();
        let (kind, terrain) = match l.kind.as_str() {
            "tiles" => {
                for c in &l.cells {
                    let &[x, y, atlas, col, row, ..] = c.as_slice() else {
                        return Err(format!("{at}: cell {c:?} needs x, y, atlas, col, row"));
                    };
                    let tile = [atlas, col, row].map(|v| u32::try_from(v).unwrap_or(u32::MAX));
                    if !inside(x, y) || ts.tile(tile[0], tile[1], tile[2]).is_none() {
                        return Err(format!(
                            "{at}: cell {c:?} is outside the map or names a tile the tileset lacks"
                        ));
                    }
                    let flags = c.get(5).copied().unwrap_or(0).clamp(0, 7) as u8;
                    cells.push(MapCell {
                        x,
                        y,
                        tile: Some(tile),
                        key: None,
                        flags,
                    });
                }
                (LayerKind::Tiles, None)
            }
            "terrain" => {
                let set = l.terrain_set.unwrap_or(0);
                let id = l.terrain.ok_or(format!("{at}: a terrain layer needs terrain"))?;
                let mode = ts
                    .terrains
                    .iter()
                    .find(|t| t.set == set && t.id == id)
                    .map(|t| t.mode)
                    .ok_or(format!("{at}: terrain {set}/{id} is not in tileset {}", ts.name))?;
                // the candidates per key, in atlas order (atlases as listed, tiles in list order), with weights
                let mut by_key: HashMap<u8, Vec<(f64, [u32; 3])>> = HashMap::new();
                for a in &ts.atlases {
                    for t in &a.tiles {
                        if t.terrain == Some((set, id))
                            && let Some(k) = t.key
                        {
                            by_key.entry(k).or_default().push((t.probability, [a.id, t.col, t.row]));
                        }
                    }
                }
                let mut painted: HashSet<(i64, i64)> = HashSet::new();
                for c in &l.cells {
                    let &[x, y, ..] = c.as_slice() else {
                        return Err(format!("{at}: cell {c:?} needs x, y"));
                    };
                    if !inside(x, y) {
                        return Err(format!("{at}: cell [{x}, {y}] is outside the map"));
                    }
                    painted.insert((x, y));
                }
                let mut order: Vec<(i64, i64)> = painted.iter().copied().collect();
                order.sort_by_key(|&(x, y)| (y, x));
                let mut empty: Vec<String> = Vec::new();
                for (x, y) in order {
                    let key = autotile::cell_mask(&painted, x, y, mode);
                    let tile = by_key
                        .get(&key)
                        .and_then(|cands| autotile::pick(cands, autotile::cell_roll(x, y, li)))
                        .copied();
                    if tile.is_none() {
                        empty.push(format!("[{x}, {y}] key {key}"));
                    }
                    cells.push(MapCell {
                        x,
                        y,
                        tile,
                        key: Some(key),
                        flags: 0,
                    });
                }
                if !empty.is_empty() {
                    warnings.push(format!(
                        "map/{name} {at}: {} cell(s) have no tile of terrain {set}/{id} for their key in tileset {} \
                         (left empty; a corners4 terrain needs shapes at least 2 cells thick): {}",
                        empty.len(),
                        ts.name,
                        empty.join(", ")
                    ));
                }
                (LayerKind::Terrain, Some((set, id)))
            }
            "stamps" => {
                for c in &l.cells {
                    let &[x, y, stamp, ..] = c.as_slice() else {
                        return Err(format!("{at}: cell {c:?} needs x, y, stamp"));
                    };
                    let st = usize::try_from(stamp)
                        .ok()
                        .and_then(|i| ts.stamps.get(i))
                        .ok_or(format!(
                            "{at}: cell {c:?} names stamp {stamp}, which tileset {} lacks",
                            ts.name
                        ))?;
                    for (sx, sy, tile) in autotile::stamp_cells(x, y, st.size.x, &st.tiles) {
                        if !inside(sx, sy) || ts.tile(tile[0], tile[1], tile[2]).is_none() {
                            return Err(format!(
                                "{at}: stamp {} at [{x}, {y}] puts tile {tile:?} at [{sx}, {sy}], outside the map \
                                 or not in the tileset",
                                st.name
                            ));
                        }
                        cells.push(MapCell {
                            x: sx,
                            y: sy,
                            tile: Some(tile),
                            key: None,
                            flags: 0,
                        });
                    }
                }
                (LayerKind::Stamps, None)
            }
            other => {
                warnings.push(format!(
                    "map/{name} {at}: unknown layer kind {other:?} skipped (a newer spec minor version?)"
                ));
                continue;
            }
        };
        layers.push(MapLayer {
            name: l.name,
            kind,
            terrain,
            opacity: l.opacity.unwrap_or(1.0),
            cells,
        });
    }
    let mut objects = Vec::new();
    for o in d.objects {
        if !pack.sprites.contains_key(&o.asset) && !pack.animated.contains_key(&o.asset) {
            warnings.push(format!(
                "map/{name}: object {:?} is not a sprite of pack {} (placed nowhere)",
                o.asset, pack.name
            ));
        }
        objects.push(MapObject {
            asset: o.asset,
            position: Vec2::new(o.x as f32, -o.y as f32),
        });
    }
    Ok((
        TileMap {
            name: name.into(),
            tileset: d.tileset,
            size,
            cell_size: uvec(d.tile_size),
            shape: ts.shape,
            layers,
            objects,
        },
        warnings,
    ))
}

// ---- The extra kinds -------------------------------------------------------------------------------------------

fn background(name: &str, d: BackgroundDef, files: &Files) -> Result<Background, String> {
    let layers = d
        .layers
        .into_iter()
        .enumerate()
        .map(|(i, l)| {
            let (repeat_x, repeat_y) = match l.repeat.as_str() {
                "none" => (false, false),
                "x" => (true, false),
                "y" => (false, true),
                "xy" => (true, true),
                other => return Err(format!("layer {i}: repeat {other:?} is not none, x, y or xy")),
            };
            Ok(BackgroundLayer {
                image: files.existing(&l.image).map_err(|e| format!("layer {i}: {e}"))?,
                name: l.name,
                size: uvec(l.size),
                velocity: Vec2::new(l.velocity[0] as f32, -l.velocity[1] as f32),
                repeat_x,
                repeat_y,
                wobble_px: l.wobble_px as f32,
                scale: l.scale as f32,
            })
        })
        .collect::<Result<_, String>>()?;
    Ok(Background {
        name: name.into(),
        role: d.role,
        layers,
    })
}

fn particles(name: &str, d: ParticlesDef, files: &Files) -> Result<Particles, String> {
    Ok(Particles {
        name: name.into(),
        texture: files.existing(&d.texture)?,
        emitter: d.emitter,
    })
}

fn transition(name: &str, d: TransitionDef, files: &Files) -> Result<Transition, String> {
    Ok(Transition {
        name: name.into(),
        image: files.existing(&d.image)?,
        size: uvec(d.size),
        transition: d.transition,
    })
}

/// The target is a path (the image it lights), checked like every other file: a normal map whose target is gone
/// is a broken asset.
fn normal_map(name: &str, d: NormalMapDef, files: &Files) -> Result<NormalMap, String> {
    Ok(NormalMap {
        name: name.into(),
        image: files.existing(&d.image)?,
        size: d.size.map(uvec),
        target: files.existing(&d.target).map_err(|e| format!("target {e}"))?,
        convention: d.convention,
    })
}

fn image(name: &str, d: ImageDef, files: &Files) -> Result<ImageAsset, String> {
    let size = uvec(d.size);
    Ok(ImageAsset {
        name: name.into(),
        role: d.role,
        image: files.existing(&d.image)?,
        size,
        anchor: d.pivot.map_or(Anchor::CENTER, |p| anchor_from_pivot(p, size)),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pivots_turn_into_anchors_and_back() {
        let size = UVec2::new(16, 24);
        let a = anchor_from_pivot([8.0, 24.0], size);
        assert_eq!(a, Anchor::BOTTOM_CENTER, "feet on the bottom edge, centred");
        assert_eq!(anchor_from_pivot([8.0, 12.0], size), Anchor::CENTER);
        assert_eq!(anchor_from_pivot([0.0, 0.0], size), Anchor::TOP_LEFT);
        assert_eq!(pivot_from_anchor(a, size), [8.0, 24.0]);
    }

    #[test]
    fn collision_boxes_sit_around_the_pivot_y_up() {
        // the golden crate: 16 x 16, pivot (8, 16), box [3, 4, 10, 12] reaches the feet
        let r = rect_around([3.0, 4.0, 10.0, 12.0], [8.0, 16.0]);
        assert_eq!(r, Rect::new(-5.0, 0.0, 5.0, 12.0));
        assert_eq!(image_rect(r, [8.0, 16.0]), [3.0, 4.0, 10.0, 12.0]);
    }

    #[test]
    fn margins_are_left_top_right_bottom() {
        let s = slicer_from_margins([1.0, 2.0, 3.0, 4.0]);
        assert_eq!(s.border.min_inset, Vec2::new(1.0, 2.0));
        assert_eq!(s.border.max_inset, Vec2::new(3.0, 4.0));
        assert_eq!(margins_from_slicer(&s), [1.0, 2.0, 3.0, 4.0]);
    }

    #[test]
    fn base_paths_stay_inside_the_asset_folder() {
        assert_eq!(join_prefix("dotwork", "..").as_deref(), Some(""));
        assert_eq!(join_prefix("packs/dotwork", "..").as_deref(), Some("packs"));
        assert_eq!(join_prefix("", "..").as_deref(), None);
        let files = Files {
            root: Path::new("."),
            base: "packs".into(),
        };
        assert_eq!(files.asset_path("art/a.png").unwrap(), "packs/art/a.png");
        for bad in ["../a.png", "/a.png", "C:/a.png", "a\\b.png", "a//b.png", ""] {
            assert!(files.asset_path(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn another_major_version_or_format_is_refused() {
        let root = Path::new("assets");
        let path = root.join("dotwork/x.assets.json");
        let doc = |format: &str, version: &str| {
            serde_json::json!({
                "format": format, "version": version, "pack": "x", "base": "..", "assets": []
            })
        };
        assert!(read_document(&doc(FORMAT, "1.4.0"), &path, root).is_ok());
        let err = read_document(&doc(FORMAT, "2.0.0"), &path, root).unwrap_err();
        assert!(err.contains("2.0.0") && err.contains("1.x"), "{err}");
        assert!(read_document(&doc("something-else", "1.0.0"), &path, root).is_err());
    }

    #[test]
    fn unknown_kinds_and_fields_are_skipped_with_one_warning() {
        let root = Path::new("assets");
        let doc = serde_json::json!({
            "format": FORMAT, "version": "1.9.0", "pack": "x", "base": "..", "new_top_field": 1,
            "assets": [
                {"kind": "hologram", "name": "a"}, {"kind": "hologram", "name": "b"},
                {"kind": "image", "name": "logo", "image": "art/logo.png", "size": [1, 1]},
                {"kind": "icon", "name": "gem", "sizes": [], "glitter": true}
            ]
        });
        let pack = read_document(&doc, &root.join("dotwork/x.assets.json"), root).unwrap();
        assert_eq!(
            pack.skipped,
            ["hologram/a", "hologram/b"],
            "an image is an extra kind: loaded, not skipped"
        );
        assert_eq!(pack.warnings.len(), 1, "{:?}", pack.warnings);
        assert!(pack.warnings[0].contains("hologram"), "{:?}", pack.warnings);
        assert_eq!(pack.errors.len(), 1, "the image's PNG is not there: {:?}", pack.errors);
        assert!(pack.errors[0].starts_with("image/logo:"), "{:?}", pack.errors);
        assert!(pack.icons.contains_key("gem"), "the unknown field is ignored");
    }

    /// A tileset and map in memory (no files: the atlas image is the only file a tileset needs, so the map
    /// rules are checked through the golden pack in tests/dotwork.rs; here only what needs no PNG).
    #[test]
    fn an_unknown_layer_kind_is_skipped_with_one_warning() {
        let ts = Tileset {
            name: "t".into(),
            tile_size: UVec2::new(8, 8),
            shape: Shape::Square,
            terrains: Vec::new(),
            atlases: Vec::new(),
            stamps: Vec::new(),
        };
        let mut pack = Pack::default();
        pack.tilesets.insert("t".into(), ts);
        let d: MapDef = serde_json::from_value(serde_json::json!({
            "tileset": "t", "size": [2, 2], "tile_size": [8, 8],
            "layers": [{"name": "Fog", "kind": "volumes", "cells": [[0, 0, 1]]}]
        }))
        .unwrap();
        let (map, warnings) = tile_map("m", d, &pack).unwrap();
        assert!(map.layers.is_empty(), "the layer is left out");
        assert_eq!(warnings.len(), 1, "{warnings:?}");
        assert!(warnings[0].contains("volumes"), "{warnings:?}");
    }
}
