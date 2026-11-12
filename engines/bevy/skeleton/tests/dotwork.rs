// ---------------------------------------------------------------------------
// tests/dotwork.rs
// Purpose : The Dotwork importer exam (#59): the golden pack in data/golden/dotwork/ (every asset kind) loads into
//           Bevy objects that reproduce its expected.json (written by tools/art/dotwork/assetspec.py, the
//           reference) to 1e-6, and every real manifest the game ships in assets/dotwork/ loads without an error.
// Usage   : python tools/dev.py test   (cargo test --test dotwork -- --nocapture also prints what loaded)
// Notes   : No window: the loader builds TextureAtlasLayouts, Durations, Anchors, Rects and TextureSlicers as plain
//           values, and this file turns those objects back into the spec's loaded result (pivots from the Anchors,
//           seconds from the Durations, rects from the atlas layouts, a map's placed cells and centres from its
//           resolved layers and the tiles' origins) and compares. Numbers compare numerically, arrays in order,
//           objects as key sets. Every kind of spec 1.1.0 loads, the extra kinds included, so nothing may be
//           skipped. When the spec changes, rebuild the fixture (`python tools/art/dotwork/tests/golden_assets.py
//           --write` in the kit) and fix src/dotwork/ until this passes.
//
// Pseudocode:
//   read golden.assets.json -> loaded result from the pack's objects -> for each expected asset: equal within
//   1e-6 -> no asset the reference lacks, nothing skipped -> then load assets/dotwork/*.assets.json: no errors,
//   every terrain cell found its tile
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
//           Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): the maps' shape,
//           tile size, placed cells and centres, corner keys, the extra kinds loaded, a stamps layer
// ---------------------------------------------------------------------------
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::Duration;

use bevy::math::{URect, UVec2};
use bevy::sprite::Anchor;
use serde_json::{Map, Value, json};

use {{GAME_SLUG}}::dotwork::manifest::{self, ClipTexture, LayerKind, Pack};
use {{GAME_SLUG}}::dotwork::{DotworkLibrary, FramePlayer, default_asset_root};

/// The spec's tolerance for every number in expected.json.
const TOLERANCE: f64 = 1e-6;

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
        let mut corners: std::collections::BTreeMap<String, BTreeSet<Vec<i64>>> = Default::default();
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
        let ts = &pack.tilesets[&m.tileset];
        let mut layers = Map::new();
        let mut terrain = Map::new();
        let mut placed = Map::new();
        for l in &m.layers {
            // the cells drawn: a terrain cell with no tile is not one
            let drawn: Vec<Value> = l
                .cells
                .iter()
                .filter_map(|c| {
                    let [atlas, col, row] = c.tile?;
                    let [left, top] = m.top_left(ts, c)?;
                    Some(json!([c.x, c.y, atlas, col, row, left, top]))
                })
                .collect();
            layers.insert(l.name.clone(), json!(drawn.len()));
            placed.insert(l.name.clone(), json!(drawn));
            if l.kind == LayerKind::Terrain {
                let cells: Vec<Value> = l.cells.iter().map(|c| json!([c.x, c.y, c.key, c.tile])).collect();
                terrain.insert(l.name.clone(), json!(cells));
            }
        }
        let centres: Vec<Value> = (0..i64::from(m.size.y))
            .flat_map(|y| (0..i64::from(m.size.x)).map(move |x| (x, y)))
            .map(|(x, y)| {
                let c = m.centre(x, y);
                json!([x, y, c.x, c.y])
            })
            .collect();
        let objects: Vec<Value> = m
            .objects
            .iter()
            .map(|o| json!([o.asset, o.position.x, -o.position.y]))
            .collect();
        out.insert(
            format!("map/{name}"),
            json!({"size": size(m.size), "shape": m.shape.name(), "tile_size": size(m.cell_size), "layers": layers,
                   "terrain": terrain, "placed": placed, "centres": centres, "objects": objects}),
        );
    }
    for (name, b) in &pack.backgrounds {
        let layers: Vec<Value> = b
            .layers
            .iter()
            .map(|l| json!([l.size.x, l.size.y, l.velocity.x, -l.velocity.y, l.repeat()]))
            .collect();
        out.insert(format!("background/{name}"), json!({"layers": layers}));
    }
    for name in pack.particles.keys() {
        out.insert(format!("particles/{name}"), json!({"kind": "particles"}));
    }
    for name in pack.transitions.keys() {
        out.insert(format!("transition/{name}"), json!({"kind": "transition"}));
    }
    for name in pack.normal_maps.keys() {
        out.insert(format!("normal_map/{name}"), json!({"kind": "normal_map"}));
    }
    for name in pack.images.keys() {
        out.insert(format!("image/{name}"), json!({"kind": "image"}));
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
    let mut kinds = BTreeSet::new();
    for (key, w) in want {
        let kind = key.split('/').next().unwrap_or("");
        match got.get(key) {
            Some(g) => {
                compare(g, w, key, &mut errs);
                kinds.insert(kind.to_string());
            }
            None => errs.push(format!("{key}: not loaded")),
        }
    }
    for key in got.keys() {
        if !want.contains_key(key) {
            errs.push(format!("{key}: loaded, but the reference has no such asset"));
        }
    }
    println!("golden pack: {} assets compared", got.len());
    assert!(
        errs.is_empty(),
        "{} difference(s) from expected.json:\n{}",
        errs.len(),
        errs.join("\n")
    );
    assert!(
        pack.skipped.is_empty(),
        "every kind of the spec loads: {:?}",
        pack.skipped
    );
    let all: BTreeSet<String> = manifest::CORE_KINDS
        .iter()
        .chain(manifest::EXTRA_KINDS.iter())
        .map(|k| k.to_string())
        .collect();
    assert_eq!(kinds, all, "the golden pack exercises every kind");
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
fn extra_kinds_are_loaded_with_their_data() {
    let pack = golden_pack();
    assert!(
        !pack.warnings.iter().any(|w| w.contains("skipped")),
        "nothing is skipped any more: {:#?}",
        pack.warnings
    );
    let hills = &pack.backgrounds["hills"];
    assert_eq!(hills.role, "battle");
    assert_eq!(hills.layers.len(), 2);
    let clouds = &hills.layers[1];
    assert_eq!(clouds.name.as_deref(), Some("clouds_near"));
    assert!(
        clouds.repeat_x && !clouds.repeat_y && clouds.repeat() == "x",
        "the clouds tile along x"
    );
    assert_eq!(clouds.velocity.x, -4.0, "px/s of the art");
    assert_eq!(clouds.scale, 2.0);
    assert!(clouds.image.ends_with(".png"));
    let embers = &pack.particles["vfx_embers_particles"];
    assert_eq!(
        embers.emitter["amount"],
        json!(12),
        "the emitter JSON as Dotwork wrote it"
    );
    assert!(embers.texture.ends_with(".png"));
    let wipe = &pack.transitions["transition_wipe"];
    assert_eq!((wipe.transition.as_str(), wipe.size), ("wipe", UVec2::new(8, 8)));
    let crate_n = &pack.normal_maps["spr_crate_n"];
    assert_eq!(crate_n.convention, "opengl");
    assert_eq!(
        crate_n.target, pack.sprites["crate"].image,
        "it lights the crate's own image"
    );
    let logo = &pack.images["logo_golden"];
    assert_eq!((logo.role.as_str(), logo.anchor), ("logo", Anchor::CENTER));
}

#[test]
fn a_stamps_layer_places_every_tile_of_the_stamp() {
    let pack = golden_pack();
    let (yard, ts) = (&pack.maps["yard"], &pack.tilesets["ground_yard"]);
    let door = &ts.stamps[0];
    let fixtures = yard
        .layers
        .iter()
        .find(|l| l.kind == LayerKind::Stamps)
        .expect("the yard places a stamp");
    assert_eq!(
        fixtures.cells.len(),
        door.tiles.len(),
        "one cell per tile of the one door"
    );
    // the door is 1 x 2: its tiles stack down from the placed cell, in reading order
    let (x, y) = (fixtures.cells[0].x, fixtures.cells[0].y);
    for (j, (c, tile)) in fixtures.cells.iter().zip(&door.tiles).enumerate() {
        assert_eq!((c.x, c.y, c.tile, c.key), (x, y + j as i64, Some(*tile), None));
    }
    // placed one cell apart: the lower tile's top-left is one cell height further down
    let tops: Vec<[f64; 2]> = fixtures.cells.iter().map(|c| yard.top_left(ts, c).unwrap()).collect();
    assert_eq!(tops[1][0], tops[0][0]);
    assert_eq!(tops[1][1] - tops[0][1], f64::from(yard.cell_size.y));
    // the isometric map: the raised block's own origin lifts its image above the diamond's centre
    let (isle, iso) = (&pack.maps["isle"], &pack.tilesets["iso_isle"]);
    let blocks = isle.layers.iter().find(|l| l.name == "Blocks").unwrap();
    let block = iso.tile(1, 0, 0).unwrap();
    assert_eq!(block.origin, [8.0, 8.0]);
    let c = &blocks.cells[0];
    let centre = isle.centre(c.x, c.y);
    let top_left = isle.top_left(iso, c).unwrap();
    assert_eq!(top_left, [f64::from(centre.x) - 8.0, f64::from(centre.y) - 8.0]);
    assert!(isle.layers.iter().all(|l| l.kind != LayerKind::Stamps));
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
    assert!(lib.background("hills").is_some() && lib.particles("vfx_embers_particles").is_some());
    assert!(lib.transition("transition_wipe").is_some() && lib.normal_map("spr_crate_n").is_some());
    assert!(lib.image_asset("logo_golden").is_some());
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
                for c in l.cells.iter().filter(|c| c.key.is_some() && c.tile.is_none()) {
                    problems.push(format!(
                        "{}: map/{name} layer {} cell [{}, {}] has no tile for key {:?}",
                        pack.name, l.name, c.x, c.y, c.key
                    ));
                }
            }
        }
        println!(
            "{}: {} animated, {} sprites, {} tilesets, {} maps, {} fonts, {} ui kits, {} backgrounds, {} skipped",
            pack.name,
            pack.animated.len(),
            pack.sprites.len(),
            pack.tilesets.len(),
            pack.maps.len(),
            pack.fonts.len(),
            pack.ui_kits.len(),
            pack.backgrounds.len(),
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
