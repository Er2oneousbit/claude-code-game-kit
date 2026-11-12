// ---------------------------------------------------------------------------
// dotwork/mod.rs
// Purpose : The Dotwork importer (#59): loads every asset manifest in assets/dotwork/ (art Dotwork made on the
//           user's GPU, tools/art/dotwork/ASSET_MANIFEST.md) and turns it into Bevy sprites: animated characters and
//           effects, props with collision boxes, tile maps (terrain resolved by the spec's rules, stamps expanded,
//           square and isometric), bitmap-font labels, 9-slice UI parts, icons and portraits, plus the extra kinds
//           as loaded images with their data (backgrounds, particles, transitions, normal maps, loose images).
// Usage   : app.rs adds DotworkPlugin with a window, DotworkLibraryPlugin headless (smoke runs load the manifests too).
//           In a system:  fn show(mut commands: Commands, mut dw: Dotwork) {
//                             dw.spawn_clip(&mut commands, "hero", "walk_s");     // animated, pivot at its feet
//                             dw.spawn_sprite(&mut commands, "crate");            // + DotworkColliders
//                             dw.spawn_map(&mut commands, "yard");                // tiles and props as children
//                             dw.spawn_text(&mut commands, "tiny", "HELLO", Color::WHITE);
//                             for (image, layer) in dw.background_layers("hills").unwrap() { ... }
//                         }
//           Switch a character's clip: commands.entity(e).insert(dw.clip_bundle("hero", "walk_e").unwrap());
//           Data only (headless too): Res<DotworkLibrary> -> .animated("hero"), .sprite("crate").colliders,
//           .particles("embers").emitter, .normal_map("crate_n").target, ...
// Notes   : Kit code: nothing here imports the game (src/game). Pixel art rules from the spec: every texture loads
//           with ImageSampler::nearest() and no mipmaps (Bevy makes none for PNGs); a background layer's image
//           repeats (ImageAddressMode::Repeat) on its `repeat` axes and clamps on the others; draw at whole-number
//           scales (scale a parent entity); font pages and UI parts already carry the manifest's `scale` (Dotwork
//           upscaled their images, rects and margins), so they draw 1:1 like the rest. Units are the art's
//           pixels, y up; an Anchor is the pivot. Names are unique per pack; lookups take the first pack (sorted by
//           file name) that has the name. A broken manifest or asset logs an ERROR (dev.py smoke fails on it) and
//           is left out; an unknown kind logs one WARN.
//           Blend "add" is recorded (AnimatedSprite::additive) but drawn with normal blending: Bevy 0.20 sprites
//           have no additive mode. Tiles are one sprite per cell under the map entity (no tilemap crate; add
//           bevy_ecs_tilemap through an ADR if a map gets big enough to need it), on both shapes at the spec's cell
//           centres (y flipped), so an isometric map needs no tilemap of its own. The extra kinds stop at the image
//           handle and the data: the emitter, the scrolling background and the lit sprite are the game's objects
//           (Bevy 0.20 ships no particle system, and its 2D sprites have no normal-map lighting: the kit's
//           sprite_light recipe takes the normal map as a material texture).
//
// Pseudocode:
//   PreStartup: find assets/dotwork/*.assets.json -> read each (manifest.rs) -> log its warnings and errors ->
//   DotworkLibrary. Update: every DotworkAnimation advances by the frame time (player.rs) and shows its frame.
//   spawn_*: look the asset up -> load its images (nearest) and atlas layouts (cached) -> spawn sprites
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
//           Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the extra kinds
//           exposed (background images with a repeating sampler), stamps and isometric maps through spawn_map
// ---------------------------------------------------------------------------
pub mod assets;
pub mod autotile;
mod defs;
pub mod manifest;
pub mod player;

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use bevy::ecs::system::SystemParam;
use bevy::image::{
    ImageAddressMode, ImageLoaderSettings, ImageSampler, ImageSamplerDescriptor, TextureAtlas, TextureAtlasLayout,
};
use bevy::prelude::*;
use bevy::sprite::Anchor;

pub use manifest::{
    AnimatedSprite, Background, BackgroundLayer, BitmapFont, Clip, ClipTexture, Collider, Icon, ImageAsset, LayerKind,
    MapCell, MapLayer, NormalMap, Pack, Particles, Portrait, SpriteAsset, TileMap, Tileset, Transition, UiKit,
};
pub use player::FramePlayer;

// ---- Tunables ------------------------------------------------------------------
/// z step between a map's layers (children of the map entity), so later layers draw on top.
pub const LAYER_Z: f32 = 0.01;
/// z step between the cells of one layer, in draw order (the spec: a later cell overdraws an earlier one; on a
/// diamond grid a taller tile covers the one above it). Small enough that a 100,000-cell layer stays under LAYER_Z.
pub const CELL_Z: f32 = 0.0000001;
/// z of a map's objects above its last layer, plus Y_SORT per pixel of depth: lower on screen draws in front.
pub const OBJECT_Z: f32 = 0.1;
pub const Y_SORT: f32 = 0.0001;
/// z of a sprite's contact shadow, behind it.
pub const SHADOW_Z: f32 = -0.001;

/// Loads the manifests into DotworkLibrary at PreStartup. Needs no window, renderer or AssetServer.
pub struct DotworkLibraryPlugin;

impl Plugin for DotworkLibraryPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<DotworkLibrary>()
            .add_systems(PreStartup, load_library);
    }
}

/// DotworkLibraryPlugin plus drawing: the Dotwork system parameter and the animation clock. Needs AssetServer
/// (DefaultPlugins), so app.rs adds it only with a window.
pub struct DotworkPlugin;

impl Plugin for DotworkPlugin {
    fn build(&self, app: &mut App) {
        if !app.is_plugin_added::<DotworkLibraryPlugin>() {
            app.add_plugins(DotworkLibraryPlugin);
        }
        app.init_resource::<DotworkCache>().add_systems(Update, animate);
    }
}

/// Every pack the game ships, loaded.
#[derive(Resource, Debug, Default)]
pub struct DotworkLibrary {
    /// Sorted by manifest file name.
    pub packs: Vec<Pack>,
    /// Manifests that could not be read at all (another major version, not JSON).
    pub failed: Vec<String>,
}

/// The folder Bevy's AssetServer reads (BEVY_ASSET_ROOT, else the crate folder under cargo, else the exe's folder,
/// then `assets`): where the manifests are found.
pub fn default_asset_root() -> PathBuf {
    bevy::asset::io::file::FileAssetReader::get_base_path().join("assets")
}

/// Every `*.assets.json` in `<asset_root>/dotwork/`, sorted.
pub fn manifest_paths(asset_root: &Path) -> Vec<PathBuf> {
    let Ok(dir) = std::fs::read_dir(asset_root.join(manifest::MANIFEST_DIR)) else {
        return Vec::new();
    };
    let mut paths: Vec<PathBuf> = dir
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_file() && p.to_string_lossy().ends_with(manifest::SUFFIX))
        .collect();
    paths.sort();
    paths
}

impl DotworkLibrary {
    /// Reads every manifest under `asset_root`.
    pub fn load(asset_root: &Path) -> Self {
        let mut lib = DotworkLibrary::default();
        for path in manifest_paths(asset_root) {
            match manifest::read_manifest(&path, asset_root) {
                Ok(pack) => lib.packs.push(pack),
                Err(e) => lib.failed.push(e),
            }
        }
        lib
    }

    /// Every error: unreadable manifests and broken assets (named by their pack).
    pub fn errors(&self) -> Vec<String> {
        let packs = self
            .packs
            .iter()
            .flat_map(|p| p.errors.iter().map(move |e| format!("pack {}: {e}", p.name)));
        self.failed.iter().cloned().chain(packs).collect()
    }

    pub fn animated(&self, name: &str) -> Option<&AnimatedSprite> {
        self.packs.iter().find_map(|p| p.animated.get(name))
    }

    pub fn sprite(&self, name: &str) -> Option<&SpriteAsset> {
        self.packs.iter().find_map(|p| p.sprites.get(name))
    }

    pub fn icon(&self, name: &str) -> Option<&Icon> {
        self.packs.iter().find_map(|p| p.icons.get(name))
    }

    pub fn portrait(&self, name: &str) -> Option<&Portrait> {
        self.packs.iter().find_map(|p| p.portraits.get(name))
    }

    pub fn font(&self, name: &str) -> Option<&BitmapFont> {
        self.packs.iter().find_map(|p| p.fonts.get(name))
    }

    pub fn ui_kit(&self, name: &str) -> Option<&UiKit> {
        self.packs.iter().find_map(|p| p.ui_kits.get(name))
    }

    /// A map and its tileset (from the same pack).
    pub fn map(&self, name: &str) -> Option<(&Pack, &TileMap, &Tileset)> {
        self.packs.iter().find_map(|p| {
            let m = p.maps.get(name)?;
            Some((p, m, p.tilesets.get(&m.tileset)?))
        })
    }

    pub fn background(&self, name: &str) -> Option<&Background> {
        self.packs.iter().find_map(|p| p.backgrounds.get(name))
    }

    pub fn particles(&self, name: &str) -> Option<&Particles> {
        self.packs.iter().find_map(|p| p.particles.get(name))
    }

    pub fn transition(&self, name: &str) -> Option<&Transition> {
        self.packs.iter().find_map(|p| p.transitions.get(name))
    }

    pub fn normal_map(&self, name: &str) -> Option<&NormalMap> {
        self.packs.iter().find_map(|p| p.normal_maps.get(name))
    }

    pub fn image_asset(&self, name: &str) -> Option<&ImageAsset> {
        self.packs.iter().find_map(|p| p.images.get(name))
    }
}

fn load_library(mut lib: ResMut<DotworkLibrary>) {
    let root = default_asset_root();
    *lib = DotworkLibrary::load(&root);
    for pack in &lib.packs {
        for w in &pack.warnings {
            warn!("{w}");
        }
    }
    for e in lib.errors() {
        error!("{e}");
    }
    if !lib.packs.is_empty() || !lib.failed.is_empty() {
        let count = |f: fn(&Pack) -> usize| lib.packs.iter().map(f).sum::<usize>();
        info!(
            "DOTWORK packs={} animated={} sprites={} maps={} fonts={} ui_kits={} extras={} errors={}",
            lib.packs.len(),
            count(|p| p.animated.len()),
            count(|p| p.sprites.len()),
            count(|p| p.maps.len()),
            count(|p| p.fonts.len()),
            count(|p| p.ui_kits.len()),
            count(|p| {
                p.backgrounds.len() + p.particles.len() + p.transitions.len() + p.normal_maps.len() + p.images.len()
            }),
            lib.errors().len()
        );
    }
}

// ---- Components ------------------------------------------------------------------

/// A playing Dotwork clip (or animated tile): the frame clock and what each frame shows.
#[derive(Component, Debug, Clone)]
pub struct DotworkAnimation {
    /// The animated sprite and clip names ("" for an animated tile).
    pub sprite: String,
    pub clip: String,
    pub player: FramePlayer,
    frames: Vec<FrameImage>,
}

#[derive(Debug, Clone)]
enum FrameImage {
    /// An index in the sprite's atlas (a sheet clip, an animated tile).
    Atlas(usize),
    /// A whole image per frame (a clip without a sheet).
    Image(Handle<Image>),
}

impl DotworkAnimation {
    /// Has a one-shot clip played to its end?
    pub fn finished(&self) -> bool {
        self.player.finished()
    }
}

/// Collision boxes of a sprite or tile around its origin (the pivot, or the tile's centre), in its pixels, y up.
#[derive(Component, Debug, Clone, Default)]
pub struct DotworkColliders(pub Vec<Collider>);

/// The text a Dotwork label shows (its glyphs are child sprites).
#[derive(Component, Debug, Clone)]
pub struct DotworkText(pub String);

fn animate(time: Res<Time>, mut sprites: Query<(&mut DotworkAnimation, &mut Sprite)>) {
    for (mut anim, mut sprite) in &mut sprites {
        if !anim.player.advance(time.delta()) {
            continue;
        }
        match anim.frames.get(anim.player.frame()) {
            Some(FrameImage::Atlas(index)) => {
                if let Some(atlas) = sprite.texture_atlas.as_mut() {
                    atlas.index = *index;
                }
            }
            Some(FrameImage::Image(image)) => sprite.image = image.clone(),
            None => {}
        }
    }
}

/// Image and atlas-layout handles already made, so spawning the same art twice shares them.
#[derive(Resource, Debug, Default)]
pub struct DotworkCache {
    layouts: HashMap<String, Handle<TextureAtlasLayout>>,
}

/// What a system needs to put Dotwork art on screen.
#[derive(SystemParam)]
pub struct Dotwork<'w> {
    pub library: Res<'w, DotworkLibrary>,
    server: Res<'w, AssetServer>,
    layouts: ResMut<'w, Assets<TextureAtlasLayout>>,
    cache: ResMut<'w, DotworkCache>,
}

impl Dotwork<'_> {
    /// An image of the asset folder, nearest-filtered (pixel art: no smoothing, no mipmaps), clamped at its edges.
    pub fn image(&self, path: &str) -> Handle<Image> {
        self.image_with(path, false, false)
    }

    /// An image that repeats along x and/or y when drawn past its edges (a seamless background layer):
    /// ImageAddressMode::Repeat on those axes of the sampler, ClampToEdge on the rest, still nearest-filtered.
    /// The image's `.meta` settings are per path, so a path loaded with two samplers keeps the first.
    pub fn image_with(&self, path: &str, repeat_x: bool, repeat_y: bool) -> Handle<Image> {
        let mode = |on: bool| {
            if on {
                ImageAddressMode::Repeat
            } else {
                ImageAddressMode::ClampToEdge
            }
        };
        let sampler = ImageSampler::Descriptor(ImageSamplerDescriptor {
            address_mode_u: mode(repeat_x),
            address_mode_v: mode(repeat_y),
            ..ImageSamplerDescriptor::nearest()
        });
        self.server
            .load_builder()
            .with_settings(move |s: &mut ImageLoaderSettings| s.sampler = sampler.clone())
            .load(path.to_owned())
    }

    /// A background's layers, first to last, each with its image loaded to repeat on its `repeat` axes. The
    /// scrolling (`velocity`, `wobble_px`) and the drawing past the edges are the game's: a quad whose UVs run past
    /// 1 reaches the repeating sampler; a `Sprite` with `SpriteImageMode::Tiled` repeats the image on its own (its
    /// tiles keep UVs inside 0..1). None when the library has no such background.
    pub fn background_layers(&self, name: &str) -> Option<Vec<(Handle<Image>, BackgroundLayer)>> {
        let bg = self.library.background(name)?;
        Some(
            bg.layers
                .iter()
                .map(|l| (self.image_with(&l.image, l.repeat_x, l.repeat_y), l.clone()))
                .collect(),
        )
    }

    /// A particle texture (a white mask to tint) and its emitter JSON, for the game's own emitter.
    pub fn particles(&self, name: &str) -> Option<(Handle<Image>, Particles)> {
        let p = self.library.particles(name)?;
        Some((self.image(&p.texture), p.clone()))
    }

    /// A transition's greyscale image (the threshold texture of the kit's transition recipe) and its data.
    pub fn transition(&self, name: &str) -> Option<(Handle<Image>, Transition)> {
        let t = self.library.transition(name)?;
        Some((self.image(&t.image), t.clone()))
    }

    /// A normal map's image and the image it lights (its `target`), for a lit material of the game's: Bevy 0.20's
    /// 2D sprites do not read a normal map themselves.
    pub fn normal_map(&self, name: &str) -> Option<(Handle<Image>, Handle<Image>, NormalMap)> {
        let n = self.library.normal_map(name)?;
        Some((self.image(&n.image), self.image(&n.target), n.clone()))
    }

    /// A loose image (a logo, a sheet) as a Sprite with its pivot as the Anchor.
    pub fn image_sprite(&self, name: &str) -> Option<(Sprite, Anchor)> {
        let i = self.library.image_asset(name)?;
        Some((Sprite::from_image(self.image(&i.image)), i.anchor))
    }

    fn layout(&mut self, key: String, layout: &TextureAtlasLayout) -> Handle<TextureAtlasLayout> {
        let layouts = &mut self.layouts;
        self.cache
            .layouts
            .entry(key)
            .or_insert_with(|| layouts.add(layout.clone()))
            .clone()
    }

    /// Sprite, Anchor and DotworkAnimation for one clip, from its first frame. Insert it on a new entity, or on an
    /// existing one to switch clips (walk_s -> walk_e). None when the sprite or clip is not in the library.
    pub fn clip_bundle(&mut self, sprite: &str, clip: &str) -> Option<(Sprite, Anchor, DotworkAnimation)> {
        let c = self.library.animated(sprite)?.clip(clip)?.clone();
        let (image, atlas, frames) = match &c.texture {
            ClipTexture::Sheet { image, layout } => {
                let handle = self.layout(format!("clip:{sprite}/{clip}"), layout);
                let frames = (0..c.frame_count()).map(FrameImage::Atlas).collect();
                (
                    self.image(image),
                    Some(TextureAtlas {
                        layout: handle,
                        index: 0,
                    }),
                    frames,
                )
            }
            ClipTexture::Files { images, .. } => {
                let handles: Vec<Handle<Image>> = images.iter().map(|p| self.image(p)).collect();
                (
                    handles[0].clone(),
                    None,
                    handles.into_iter().map(FrameImage::Image).collect(),
                )
            }
        };
        let sprite_component = Sprite {
            image,
            texture_atlas: atlas,
            ..default()
        };
        let anim = DotworkAnimation {
            sprite: sprite.into(),
            clip: clip.into(),
            player: FramePlayer::new(c.durations.clone(), c.looping),
            frames,
        };
        Some((sprite_component, c.anchor, anim))
    }

    /// Spawns a clip playing. None when it is not in the library.
    pub fn spawn_clip(&mut self, commands: &mut Commands, sprite: &str, clip: &str) -> Option<Entity> {
        let bundle = self.clip_bundle(sprite, clip)?;
        Some(commands.spawn(bundle).id())
    }

    /// Sprite, Anchor and DotworkColliders of a still sprite (a prop, an enemy).
    pub fn sprite_bundle(&mut self, name: &str) -> Option<(Sprite, Anchor, DotworkColliders)> {
        let s = self.library.sprite(name)?.clone();
        Some((
            Sprite::from_image(self.image(&s.image)),
            s.anchor,
            DotworkColliders(s.colliders),
        ))
    }

    /// Spawns a still sprite, with its contact shadow as a child behind it.
    pub fn spawn_sprite(&mut self, commands: &mut Commands, name: &str) -> Option<Entity> {
        let shadow = self.library.sprite(name)?.shadow.clone();
        let entity = commands.spawn(self.sprite_bundle(name)?).id();
        if let Some((image, offset)) = shadow {
            commands.spawn((
                Sprite::from_image(self.image(&image)),
                Transform::from_translation(offset.extend(SHADOW_Z)),
                ChildOf(entity),
            ));
        }
        Some(entity)
    }

    /// An icon at the smallest size at least `px` pixels big.
    pub fn icon_sprite(&self, name: &str, px: u32) -> Option<Sprite> {
        let path = self.library.icon(name)?.image_for(px)?.to_owned();
        Some(Sprite::from_image(self.image(&path)))
    }

    /// A portrait's expression ("neutral", "happy", ...). Its talking frames are the AnimatedSprite it names.
    pub fn portrait_sprite(&self, name: &str, expression: &str) -> Option<Sprite> {
        let path = self.library.portrait(name)?.expression(expression)?.to_owned();
        Some(Sprite::from_image(self.image(&path)))
    }

    /// A UI part, 9-sliced to `size` when it has margins (a window, a button), else drawn at `size`.
    pub fn ui_sprite(&self, kit: &str, part: &str, size: Option<Vec2>) -> Option<Sprite> {
        let p = self.library.ui_kit(kit)?.part(part)?.clone();
        let mut sprite = Sprite::from_image(self.image(&p.image));
        sprite.custom_size = size;
        if let Some(slicer) = p.slicer {
            sprite.image_mode = SpriteImageMode::Sliced(slicer);
        }
        Some(sprite)
    }

    /// Spawns a map: a parent entity at the map's top-left corner, one sprite per placed cell (terrain resolved and
    /// stamps expanded at load; layers stacked by z and cells in draw order within a layer; square or isometric
    /// centres with the tile's origin on them, y flipped; animated tiles playing, DotworkColliders on solid tiles)
    /// and its objects y-sorted on top.
    pub fn spawn_map(&mut self, commands: &mut Commands, name: &str) -> Option<Entity> {
        let (pack, map, ts) = self.library.map(name)?;
        let (pack, map, ts) = (pack.name.clone(), map.clone(), ts.clone());
        let mut atlases = HashMap::new();
        for a in &ts.atlases {
            let layout = self.layout(format!("tiles:{pack}/{}/{}", ts.name, a.id), &a.layout);
            atlases.insert(a.id, (self.image(&a.image), layout));
        }
        let root = commands
            .spawn((
                Name::new(format!("dotwork map {name}")),
                Transform::default(),
                Visibility::default(),
            ))
            .id();
        for (li, layer) in map.layers.iter().enumerate() {
            for (ci, c) in layer.cells.iter().enumerate() {
                let Some([atlas, col, row]) = c.tile else {
                    continue;
                };
                let (Some(tile), Some((image, layout))) = (ts.tile(atlas, col, row), atlases.get(&atlas)) else {
                    continue;
                };
                let centre = map.centre(c.x, c.y);
                let (angle, scale) = autotile::flags_transform(c.flags);
                // later layers above earlier ones; within a layer, later cells above earlier ones (a taller iso
                // tile overdraws the one up the screen)
                let z = li as f32 * LAYER_Z + ci as f32 * CELL_Z;
                let mut e = commands.spawn((
                    Sprite {
                        image: image.clone(),
                        texture_atlas: Some(TextureAtlas {
                            layout: layout.clone(),
                            index: tile.index,
                        }),
                        color: Color::WHITE.with_alpha(layer.opacity),
                        ..default()
                    },
                    tile.anchor,
                    Transform {
                        translation: Vec3::new(centre.x, -centre.y, z),
                        rotation: Quat::from_rotation_z(angle),
                        scale: scale.extend(1.0),
                    },
                    ChildOf(root),
                ));
                if let Some((indices, durations)) = &tile.anim {
                    e.insert(DotworkAnimation {
                        sprite: String::new(),
                        clip: String::new(),
                        player: FramePlayer::new(durations.clone(), true),
                        frames: indices.iter().copied().map(FrameImage::Atlas).collect(),
                    });
                }
                if !tile.colliders.is_empty() {
                    e.insert(DotworkColliders(tile.colliders.clone()));
                }
            }
        }
        let top = map.layers.len() as f32 * LAYER_Z + OBJECT_Z;
        for o in &map.objects {
            if let Some(bundle) = self.sprite_bundle(&o.asset) {
                let z = top - o.position.y * Y_SORT; // position.y is minus the pixel y: further down, further front
                commands.spawn((bundle, Transform::from_translation(o.position.extend(z)), ChildOf(root)));
            }
        }
        Some(root)
    }

    /// Spawns a label in a bitmap font: a parent entity at the text's top-left corner, one sprite per glyph, drawn
    /// 1:1 (the pages and metrics already carry the font's `scale`). `color` tints white-ink fonts; coloured fonts
    /// draw as they are.
    /// Unknown characters show as '?' when the font has it, else are skipped.
    pub fn spawn_text(&mut self, commands: &mut Commands, font: &str, text: &str, color: Color) -> Option<Entity> {
        let f = self.library.font(font)?.clone();
        let pages: Vec<(Handle<Image>, Handle<TextureAtlasLayout>)> = f
            .pages
            .iter()
            .enumerate()
            .map(|(i, (image, layout))| (self.image(image), self.layout(format!("font:{font}/{i}"), layout)))
            .collect();
        let tint = if f.tint { color } else { Color::WHITE };
        let root = commands
            .spawn((DotworkText(text.into()), Transform::default(), Visibility::default()))
            .id();
        let (mut pen, mut line, mut prev) = (0i32, 0i32, None::<u32>);
        for ch in text.chars() {
            if ch == '\n' {
                (pen, prev) = (0, None);
                line += f.line_height as i32;
                continue;
            }
            let id = ch as u32;
            let Some((id, g)) = f
                .glyphs
                .get(&id)
                .map(|g| (id, g))
                .or(f.glyphs.get(&63).map(|g| (63, g)))
            else {
                continue;
            };
            if let Some(p) = prev {
                pen += f.kerning(p, id);
            }
            let rect = f.glyph_rect(g);
            if rect.width() > 0 && rect.height() > 0 {
                let (image, layout) = &pages[g.page];
                commands.spawn((
                    Sprite {
                        image: image.clone(),
                        texture_atlas: Some(TextureAtlas {
                            layout: layout.clone(),
                            index: g.index,
                        }),
                        color: tint,
                        ..default()
                    },
                    Anchor::TOP_LEFT,
                    Transform::from_xyz((pen + g.offset.x) as f32, -(line + g.offset.y) as f32, 0.0),
                    ChildOf(root),
                ));
            }
            pen += g.advance;
            prev = Some(id);
        }
        Some(root)
    }
}
