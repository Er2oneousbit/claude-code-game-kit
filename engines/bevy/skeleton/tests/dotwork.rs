// ---------------------------------------------------------------------------
// tests/dotwork.rs
// Purpose : The Dotwork importer exam (#59): the golden pack in data/golden/dotwork/ (every asset kind) loads into
//           Bevy objects that reproduce its expected.json (written by tools/art/dotwork/assetspec.py, the
//           reference) to 1e-6, and every real manifest the game ships in assets/dotwork/ loads without an error.
// Usage   : python tools/dev.py test   (cargo test --test dotwork -- --nocapture also prints what loaded)
// Notes   : No window: the loader builds TextureAtlasLayouts, Durations, Anchors, Rects and TextureSlicers as plain
//           values, and this file turns those objects back into the spec's loaded result (pivots from the Anchors,
//           seconds from the Durations, rects from the atlas layouts) and compares. Numbers compare numerically,
//           arrays in order, objects as key sets. The extra kinds (background, particles, transition, normal_map,
//           image) must be in the pack's skipped list instead. When the spec changes, rebuild the fixture
//           (`python tools/art/dotwork/tests/golden_assets.py --write` in the kit) and fix src/dotwork/ until this
//           passes.
//
// Pseudocode:
//   read golden.assets.json -> loaded result from the pack's objects -> for each expected asset: skipped (extra
//   kind) or equal within 1e-6 -> no asset the reference lacks -> then load assets/dotwork/*.assets.json: no errors,
//   every terrain cell found its tile
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::Duration;

use bevy::math::{URect, UVec2};
use bevy::sprite::Anchor;
use serde_json::{Map, Value, json};

use {{GAME_SLUG}}::dotwork::manifest::{self, ClipTexture, Pack};
use {{GAME_SLUG}}::dotwork::{DotworkLibrary, FramePlayer, default_asset_root};

/// The spec's tolerance for every number in expected.json.
const TOLERANCE: f64 = 1e-6;
/// The extra kinds an importer may skip (ASSET_MANIFEST.md "Asset kinds").
const EXTRA: [&str; 5] = ["background", "particles", "transition", "normal_map", "image"];

fn golden_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("data")
        .join("golden")
        .join("dotwork")
}

fn golden_pack() -> Pack {
    let root = golden_dir().join("assets");
    let path = root.join("dotwork").join("golden.assets.json");
    manifest::read_manifest(&path, &root).unwrap_or_else(|e| panic!("the golden manifest did not load: {e}"))
}

fn expected() -> Value {
    let path = golden_dir().join("expected.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).expect("expected.json is JSON")
}

fn rect(r: URect) -> Value {
    json!([r.min.x, r.min.y, r.width(), r.height()])
}

fn size(s: UVec2) -> Value {
    json!([s.x, s.y])
}

fn secs(d: Duration) -> f64 {
    d.as_secs_f64()
}

fn pivot(anchor: Anchor, s: UVec2) -> Value {
    json!(manifest::pivot_from_anchor(anchor, s))
}

/// The spec's loaded result, rebuilt from the importer's own objects (not from the manifest's JSON).
fn loaded_result(pack: &Pack) -> Map<String, Value> {
    let mut out = Map::new();
    for (name, a) in &pack.animated {
        let mut clips = Map::new();
        for c in &a.clips {
            clips.insert(
                c.name.clone(),
                json!({
                    "frames": c.frame_count(),
                    "rects": (0..c.frame_count()).map(|i| rect(c.frame_rect(i))).collect::<Vec<_>>(),
                    "seconds": c.durations.iter().copied().map(secs).collect::<Vec<_>>(),
                    "length": secs(c.durations.iter().sum()),
                    "loop": c.looping,
                    "pivot": pivot(c.anchor, c.frame_size),
                    "texture": match &c.texture {
                        ClipTexture::Sheet { image, .. } => json!(image),
                        ClipTexture::Files { .. } => Value::Null,
                    },
                }),
            );
        }
        out.insert(
            format!("animated_sprite/{name}"),
            json!({"blend": if a.additive { "add" } else { "normal" }, "clips": clips, "directions": a.directions}),
        );
    }
    for (name, s) in &pack.sprites {
        let p = manifest::pivot_from_anchor(s.anchor, s.size);
        let collision: Vec<Value> = s
            .colliders
            .iter()
            .map(|c| json!(manifest::image_rect(c.rect, p)))
            .collect();
        out.insert(
            format!("sprite/{name}"),
            json!({"size": size(s.size), "pivot": p, "collision": collision}),
        );
    }
    for (name, i) in &pack.icons {
        let sizes: Vec<u32> = i.sizes.iter().map(|(s, _)| *s).collect();
        out.insert(format!("icon/{name}"), json!({"sizes": sizes}));
    }
    for (name, p) in &pack.portraits {
        let mut names: Vec<&str> = p.expressions.iter().map(|(n, _)| n.as_str()).collect();
        names.sort();
        out.insert(
            format!("portrait/{name}"),
            json!({"size": size(p.size), "expressions": names, "animation": p.animation}),
        );
    }
    for (name, t) in &pack.tilesets {
        let (mut count, mut solid, mut animated) = (0, 0, 0);
        let mut masks: Map<String, Value> = Map::new();
        let mut blob: std::collections::BTreeMap<String, BTreeSet<u8>> = Default::default();
        let mut corners: std::collections::BTreeMap<String, BTreeSet<Vec<u32>>> = Default::default();
        for a in &t.atlases {
            for tile in &a.tiles {
                count += 1;
                solid += usize::from(!tile.colliders.is_empty());
                animated += usize::from(tile.anim.is_some());
                let Some((set, id)) = tile.terrain else { continue };
                let key = format!("{set}/{id}");
                if let Some(m) = tile.mask {
                    blob.entry(key).or_default().insert(m);
                } else if let Some(c) = &tile.corners {
                    // corner keys are sorted (a BTreeMap), as the reference sorts them
                    corners.entry(key).or_default().insert(c.values().copied().collect());
                }
            }
        }
        for (k, v) in blob {
            masks.insert(k, json!(v));
        }
        for (k, v) in corners {
            masks.insert(k, json!(v));
        }
        let terrains: Map<String, Value> = t
            .terrains
            .iter()
            .map(|tr| (format!("{}/{}", tr.set, tr.id), json!(tr.name)))
            .collect();
        out.insert(
            format!("tileset/{name}"),
            json!({
                "tile_size": size(t.tile_size), "shape": t.shape.name(), "tiles": count, "collision_tiles": solid,
                "animated_tiles": animated, "terrains": terrains, "masks": masks,
            }),
        );
    }
    for (name, m) in &pack.maps {
        let mut layers = Map::new();
        let mut terrain = Map::new();
        for l in &m.layers {
            layers.insert(l.name.clone(), json!(l.cells.len()));
            if l.terrain.is_some() {
                let cells: Vec<Value> = l.cells.iter().map(|c| json!([c.x, c.y, c.mask, c.tile])).collect();
                terrain.insert(l.name.clone(), json!(cells));
            }
        }
        let objects: Vec<Value> = m
            .objects
            .iter()
            .map(|o| json!([o.asset, o.position.x, -o.position.y]))
            .collect();
        out.insert(
            format!("map/{name}"),
            json!({"size": size(m.size), "layers": layers, "terrain": terrain, "objects": objects}),
        );
    }
    for (name, f) in &pack.fonts {
        let sample = f
            .glyphs
            .get(&65)
            .map(|g| (65, g))
            .or(f.glyphs.iter().next().map(|(id, g)| (*id, g)));
        let sample = sample.map(|(id, g)| {
            let r = f.glyph_rect(g);
            json!([
                id,
                r.min.x,
                r.min.y,
                r.width(),
                r.height(),
                g.offset.x,
                g.offset.y,
                g.advance,
                g.page
            ])
        });
        out.insert(
            format!("font/{name}"),
            json!({"line_height": f.line_height, "base": f.base, "chars": f.glyphs.len(), "pages": f.pages.len(),
                   "sample": sample}),
        );
    }
    for (name, k) in &pack.ui_kits {
        let parts: Map<String, Value> = k
            .parts
            .iter()
            .map(|p| {
                let margins = p.slicer.as_ref().map(manifest::margins_from_slicer);
                let hotspot = p.hotspot.map(|h| [h.x, h.y]);
                (
                    p.name.clone(),
                    json!({"size": size(p.size), "margins": margins, "hotspot": hotspot}),
                )
            })
            .collect();
        out.insert(format!("ui_kit/{name}"), json!({"parts": parts}));
    }
    out
}

/// Every difference between `got` and `want` under `at`.
fn compare(got: &Value, want: &Value, at: &str, out: &mut Vec<String>) {
    match (got, want) {
        (Value::Number(g), Value::Number(w)) => {
            let (g, w) = (g.as_f64().unwrap_or(f64::NAN), w.as_f64().unwrap_or(f64::NAN));
            if (g - w).abs() > TOLERANCE || g.is_nan() {
                out.push(format!("{at}: got {g}, want {w}"));
            }
        }
        (Value::Array(g), Value::Array(w)) => {
            if g.len() != w.len() {
                out.push(format!("{at}: {} items, want {}", g.len(), w.len()));
                return;
            }
            for (i, (g, w)) in g.iter().zip(w).enumerate() {
                compare(g, w, &format!("{at}[{i}]"), out);
            }
        }
        (Value::Object(g), Value::Object(w)) => {
            let (gk, wk): (BTreeSet<&String>, BTreeSet<&String>) = (g.keys().collect(), w.keys().collect());
            if gk != wk {
                out.push(format!("{at}: keys {gk:?}, want {wk:?}"));
                return;
            }
            for (k, w) in w {
                compare(&g[k], w, &format!("{at}.{k}"), out);
            }
        }
        _ if got == want => {}
        _ => out.push(format!("{at}: got {got}, want {want}")),
    }
}

#[test]
fn golden_pack_matches_the_reference_loaded_result() {
    let pack = golden_pack();
    assert!(
        pack.errors.is_empty(),
        "the golden pack has broken assets: {:#?}",
        pack.errors
    );
    let want = expected();
    assert_eq!(want["format"], "dotwork-assets-expected");
    assert_eq!(want["pack"], json!(pack.name));
    let want = want["assets"].as_object().expect("expected.json has assets");
    let got = loaded_result(&pack);
    let mut errs = Vec::new();
    let mut core = BTreeSet::new();
    for (key, w) in want {
        let kind = key.split('/').next().unwrap_or("");
        if pack.skipped.contains(key) {
            if !EXTRA.contains(&kind) {
                errs.push(format!("{key}: a core kind was skipped"));
            }
            continue;
        }
        match got.get(key) {
            Some(g) => {
                compare(g, w, key, &mut errs);
                core.insert(kind.to_string());
            }
            None => errs.push(format!("{key}: not loaded and not skipped")),
        }
    }
    for key in got.keys() {
        if !want.contains_key(key) {
            errs.push(format!("{key}: loaded, but the reference has no such asset"));
        }
    }
    println!(
        "golden pack: {} assets compared, {} skipped ({:?})",
        got.len(),
        pack.skipped.len(),
        pack.skipped
    );
    assert!(
        errs.is_empty(),
        "{} difference(s) from expected.json:\n{}",
        errs.len(),
        errs.join("\n")
    );
    let all_core: BTreeSet<String> = manifest::CORE_KINDS.iter().map(|k| k.to_string()).collect();
    assert_eq!(core, all_core, "the golden pack exercises every core kind");
}

/// A sheet render_sprites.py made from the golden rigged character (#290): rows are directions, columns frames, so a
/// clip's rects sit on its own row of a shared sheet. The importer loads it as it loads Dotwork's packs.
#[test]
fn a_sheet_render_sprites_rendered_matches_its_loaded_result() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("data")
        .join("golden")
        .join("character")
        .join("sprites");
    let pack = manifest::read_manifest(&root.join("dotwork").join("character.assets.json"), &root)
        .unwrap_or_else(|e| panic!("the rendered manifest did not load: {e}"));
    assert!(pack.errors.is_empty(), "broken assets: {:#?}", pack.errors);
    assert!(pack.skipped.is_empty(), "nothing to skip: {:?}", pack.skipped);
    let path = root.join("expected.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let want: Value = serde_json::from_str(&text).expect("expected.json is JSON");
    let want = want["assets"].as_object().expect("expected.json has assets");
    let got = loaded_result(&pack);
    let mut errs = Vec::new();
    compare(&Value::Object(got), &Value::Object(want.clone()), "rendered", &mut errs);
    assert!(
        errs.is_empty(),
        "{} difference(s) from expected.json:\n{}",
        errs.len(),
        errs.join("\n")
    );
}

#[test]
fn extra_kinds_are_skipped_with_one_warning_each() {
    let pack = golden_pack();
    for kind in EXTRA {
        let lines = pack
            .warnings
            .iter()
            .filter(|w| w.contains(&format!("{kind} assets skipped")))
            .count();
        assert_eq!(lines, 1, "{kind}: {:#?}", pack.warnings);
    }
}

#[test]
fn clips_are_bevy_atlases_with_frame_durations() {
    let pack = golden_pack();
    let hero = &pack.animated["hero"];
    let walk = hero.directed("walk", "s").expect("walk faces south");
    let ClipTexture::Sheet { image, layout } = &walk.texture else {
        panic!("walk_s has a sheet");
    };
    assert_eq!(image, "art/characters/hero/hero_walk_s_sheet.png");
    assert_eq!(
        layout.size,
        UVec2::new(64, 24),
        "the sheet's own size, read from its PNG"
    );
    assert_eq!(layout.textures.len(), 4);
    assert_eq!(walk.anchor, Anchor::BOTTOM_CENTER, "a character's pivot is its feet");
    // the attack's hold: 0.1, 0.2, 0.1 s, played once
    let attack = hero.clip("attack_e").unwrap();
    let mut player = FramePlayer::new(attack.durations.clone(), attack.looping);
    player.advance(Duration::from_millis(250));
    assert_eq!(player.frame(), 1, "frame 1 shows from 0.1 to 0.3 s");
    player.advance(Duration::from_millis(160));
    assert!(player.finished() && player.frame() == 2);
    let spark = &pack.animated["fx_spark"];
    assert!(spark.additive);
    assert!(matches!(spark.clips[0].texture, ClipTexture::Files { ref images, .. } if images.len() == 3));
}

#[test]
fn tiles_fonts_and_ui_parts_index_their_atlases() {
    let pack = golden_pack();
    let yard = &pack.tilesets["ground_yard"];
    for a in &yard.atlases {
        for t in &a.tiles {
            let r = a.layout.textures[t.index];
            assert_eq!(
                r.min,
                UVec2::new(t.col, t.row) * a.tile_size,
                "atlas {} tile {},{}",
                a.id,
                t.col,
                t.row
            );
        }
    }
    let water = yard.tile(2, 0, 0).unwrap();
    let (frames, durations) = water.anim.as_ref().expect("the water animates");
    assert_eq!(frames, &vec![water.index, water.index + 1]);
    assert_eq!(durations, &vec![Duration::from_millis(250); 2]);
    let font = &pack.fonts["tiny"];
    let a = font.glyphs[&65];
    assert_eq!(font.glyph_rect(&a), URect::new(1, 1, 4, 6));
    assert_eq!(font.kerning(65, 66), -1);
    let window = pack.ui_kits["windows"].part("ui_window_plain").unwrap();
    assert_eq!(manifest::margins_from_slicer(window.slicer.as_ref().unwrap()), [3.0; 4]);
}

#[test]
fn the_library_finds_assets_across_packs() {
    let lib = DotworkLibrary::load(&golden_dir().join("assets"));
    assert!(lib.errors().is_empty(), "{:#?}", lib.errors());
    assert_eq!(lib.packs.len(), 1);
    assert!(lib.animated("hero").is_some() && lib.sprite("crate").is_some() && lib.font("tiny").is_some());
    let (_, map, tileset) = lib.map("yard").expect("the yard map and its tileset");
    assert_eq!(tileset.name, map.tileset);
    assert!(lib.animated("nobody").is_none());
}

#[test]
fn every_manifest_the_game_ships_loads() {
    // the engine's stand-in for Dotwork's Godot `verify`: a missing PNG or a broken asset fails here
    let root = default_asset_root();
    let lib = DotworkLibrary::load(&root);
    if lib.packs.is_empty() && lib.failed.is_empty() {
        println!("no Dotwork manifests in {} yet", root.join("dotwork").display());
        return;
    }
    let mut problems = lib.errors();
    for pack in &lib.packs {
        for (name, map) in &pack.maps {
            for l in &map.layers {
                for c in l.cells.iter().filter(|c| c.mask.is_some() && c.tile.is_none()) {
                    problems.push(format!(
                        "{}: map/{name} layer {} cell [{}, {}] has no tile for mask {:?}",
                        pack.name, l.name, c.x, c.y, c.mask
                    ));
                }
            }
        }
        println!(
            "{}: {} animated, {} sprites, {} tilesets, {} maps, {} fonts, {} ui kits, {} skipped",
            pack.name,
            pack.animated.len(),
            pack.sprites.len(),
            pack.tilesets.len(),
            pack.maps.len(),
            pack.fonts.len(),
            pack.ui_kits.len(),
            pack.skipped.len()
        );
    }
    assert!(
        problems.is_empty(),
        "{} problem(s):\n{}",
        problems.len(),
        problems.join("\n")
    );
}

// {{FOOTER}}
