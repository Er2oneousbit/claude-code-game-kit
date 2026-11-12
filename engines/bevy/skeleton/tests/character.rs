// ---------------------------------------------------------------------------
// tests/character.rs
// Purpose : The rigged-character exam (#290): the kit's golden character (data/golden/character/character.glb, a
//           Mixamo-named biped with looping clips) loads through src/character.rs, has its clips by name, and
//           playing `walk` really turns the moving bone; switching the Character's clip switches the player. Also:
//           the PNG and JPEG texture formats generated characters carry decode (Cargo.toml's `jpeg` feature).
// Usage   : python tools/dev.py test   (cargo test --test character -- --nocapture also prints what it measured)
// Notes   : Headless, no window and no GPU: MinimalPlugins + AssetPlugin (rooted at the fixture folder) + the
//           world-asset (scene), mesh, glTF and animation plugins. Meshes and the skin load as plain assets; nothing
//           draws them. Time advances by a fixed 1/60 s per update, so the walk is sampled at 60 Hz. Every number
//           comes from expected.json beside the .glb (tools/blender/golden_character.py writes both); never copy one
//           in here. The swing is the largest angle between any two sampled rotations of the bone over one walk
//           loop, as the kit's own exam measures it on the keys (tools/blender/test_golden_character.py).
//
// Pseudocode:
//   app -> spawn_character(character.glb, walk) -> update until the bone entity exists and the animator is attached
//   -> facing: the left-side bone sits at -x (the model looks along -Z) -> clips: every expected name, durations match -> sample the bone's rotation for one walk loop -> swing within
//   [MIN_SWING_FRACTION, MAX_SWING_FRACTION] of expected -> set clip = idle -> the player plays idle's node only
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): the texture formats a generated character uses
//           must decode (the jpeg feature; 0.15.0 review)
// ---------------------------------------------------------------------------
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use bevy::asset::AssetPlugin;
use bevy::gltf::{Gltf, GltfPlugin};
use bevy::image::{CompressedImageFormatSupport, CompressedImageFormats};
use bevy::mesh::MeshPlugin;
use bevy::prelude::*;
use bevy::time::TimeUpdateStrategy;
use bevy::world_serialization::WorldSerializationPlugin;
use serde_json::Value;

use {{GAME_SLUG}}::character::{Character, CharacterAnimator, CharacterPlugin, clip_names, spawn_character};

// ---- Tunables ------------------------------------------------------------------
/// One update's time step: the walk is sampled at this rate.
const STEP_HZ: f64 = 60.0;
/// How long the fixture may take to load (real time; it is about 62 KB).
const LOAD_TIMEOUT: Duration = Duration::from_secs(60);
/// The measured swing must be at least this fraction of expected.json's (sampling between keys loses a little).
const MIN_SWING_FRACTION: f32 = 0.5;
/// ... and at most this fraction (more would mean the clip is applied twice or to the wrong bone).
const MAX_SWING_FRACTION: f32 = 1.1;
/// Clip lengths must match expected.json to this many seconds.
const LENGTH_TOLERANCE_S: f32 = 1e-3;

fn golden_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("data")
        .join("golden")
        .join("character")
}

fn expected() -> Value {
    let path = golden_dir().join("expected.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).expect("expected.json is JSON")
}

/// A headless App whose asset folder is the fixture's folder.
fn character_app() -> App {
    let mut app = App::new();
    app.add_plugins((
        MinimalPlugins,
        AssetPlugin {
            file_path: golden_dir().to_string_lossy().into_owned(),
            ..default()
        },
        TransformPlugin,
        WorldSerializationPlugin,
        MeshPlugin,
        GltfPlugin::default(),
        AnimationPlugin,
        CharacterPlugin,
    ))
    // No renderer to ask: the fixture has no textures, so no compressed formats are needed
    .insert_resource(CompressedImageFormatSupport(CompressedImageFormats::NONE))
    .insert_resource(TimeUpdateStrategy::ManualDuration(Duration::from_secs_f64(
        1.0 / STEP_HZ,
    )));
    app.finish();
    app.cleanup();
    app
}

/// The entity named `name` (glTF node names arrive as Bevy `Name`s).
fn named(app: &mut App, name: &str) -> Option<Entity> {
    let mut q = app.world_mut().query::<(Entity, &Name)>();
    q.iter(app.world()).find(|(_, n)| n.as_str() == name).map(|(e, _)| e)
}

fn animator(app: &mut App) -> Option<(Entity, CharacterAnimator)> {
    let mut q = app.world_mut().query::<(Entity, &CharacterAnimator)>();
    q.iter(app.world()).next().map(|(e, a)| (e, a.clone()))
}

/// Spawns the fixture playing `clip` and updates until its bone and animator exist. Returns (character, bone).
fn spawn_and_load(app: &mut App, file: &str, bone: &str, clip: &str) -> (Entity, Entity) {
    let server = app.world().resource::<AssetServer>().clone();
    let character = {
        let mut commands = app.world_mut().commands();
        spawn_character(&mut commands, &server, file, clip)
    };
    app.world_mut().flush();
    let start = Instant::now();
    loop {
        app.update();
        if let (Some(b), Some(_)) = (named(app, bone), animator(app)) {
            return (character, b);
        }
        if start.elapsed() > LOAD_TIMEOUT {
            let state = server.get_load_state(&app.world().get::<Character>(character).unwrap().gltf);
            panic!("{file} did not load and play within {LOAD_TIMEOUT:?} (load state {state:?})");
        }
        std::thread::sleep(Duration::from_millis(1)); // the loader runs on the task pool
    }
}

fn quat_angle_deg(a: Quat, b: Quat) -> f32 {
    let dot = a.dot(b).abs().min(1.0);
    (2.0 * dot.acos()).to_degrees()
}

#[test]
fn the_golden_character_walks() {
    let exp = expected();
    let file = exp["file"].as_str().expect("expected.json names the file");
    let bone = exp["moving_bone"]
        .as_str()
        .expect("expected.json names the moving bone");
    let swing = exp["moving_bone_swing_deg"]
        .as_f64()
        .expect("expected.json has the swing") as f32;
    let walk_s = exp["clips"]["walk"]["seconds"].as_f64().expect("walk has a length") as f32;

    let mut app = character_app();
    let (character, bone_entity) = spawn_and_load(&mut app, file, bone, "walk");
    println!(
        "bone entity Name as Bevy stores it: {:?}",
        app.world().get::<Name>(bone_entity).unwrap().as_str()
    );

    // Facing: spawn_character turns the model to look along Transform::forward() (-Z), so its left side is Bevy's
    // left (-X): the moving bone is a left-side bone (Mixamo "Left..."), so it must sit at negative x
    let bone_x = app.world().get::<GlobalTransform>(bone_entity).unwrap().translation().x;
    println!("{bone} world x {bone_x:.3} (negative: the character faces -Z)");
    assert!(
        bone.contains("Left"),
        "the facing check needs a left-side moving bone, got {bone}"
    );
    assert!(
        bone_x < 0.0,
        "{bone} is at x {bone_x}: the character does not face Transform::forward()"
    );

    // Clips: every expected name is there, with its length
    let gltf_handle = app.world().get::<Character>(character).unwrap().gltf.clone();
    let names = clip_names(app.world().resource::<Assets<Gltf>>().get(&gltf_handle).unwrap());
    println!("clips: {names:?}");
    let clips = app.world().resource::<Assets<AnimationClip>>();
    let gltfs = app.world().resource::<Assets<Gltf>>();
    let gltf = gltfs.get(&gltf_handle).unwrap();
    for (name, spec) in exp["clips"].as_object().expect("expected.json lists the clips") {
        assert!(names.contains(name), "clip {name} missing; the file has {names:?}");
        let clip = clips
            .get(&gltf.named_animations[name.as_str()])
            .expect("clip asset loaded");
        let want = spec["seconds"].as_f64().unwrap() as f32;
        assert!(
            (clip.duration() - want).abs() < LENGTH_TOLERANCE_S,
            "clip {name} lasts {} s, expected {want} s",
            clip.duration()
        );
    }

    // Walk: sample the bone's local rotation over one loop
    let steps = (walk_s as f64 * STEP_HZ).ceil() as usize + 1;
    let mut samples = Vec::with_capacity(steps);
    for _ in 0..steps {
        app.update();
        samples.push(app.world().get::<Transform>(bone_entity).unwrap().rotation);
    }
    let measured = samples
        .iter()
        .flat_map(|a| samples.iter().map(move |b| quat_angle_deg(*a, *b)))
        .fold(0.0f32, f32::max);
    println!("{bone} swung {measured:.1} degrees over walk (expected.json: {swing})");
    assert!(
        measured >= MIN_SWING_FRACTION * swing,
        "{bone} swung {measured:.1} degrees, expected at least {:.1}",
        MIN_SWING_FRACTION * swing
    );
    assert!(
        measured <= MAX_SWING_FRACTION * swing,
        "{bone} swung {measured:.1} degrees, more than {:.1}",
        MAX_SWING_FRACTION * swing
    );

    // Switching the clip switches the player to that node alone
    app.world_mut().get_mut::<Character>(character).unwrap().clip = "idle".into();
    app.update();
    let (player_entity, anim) = animator(&mut app).unwrap();
    assert_eq!(anim.playing.as_deref(), Some("idle"));
    let player = app.world().get::<AnimationPlayer>(player_entity).unwrap();
    assert!(player.is_playing_animation(anim.clips["idle"]), "idle is not playing");
    assert!(!player.is_playing_animation(anim.clips["walk"]), "walk still plays");
}

/// A generated character's textures come as PNG (Bozzetto's bakes) or JPEG (Tripo's): both must decode, or the
/// whole .glb fails to load. Bevy's default features decode PNG only; Cargo.toml adds `jpeg` (the golden
/// character has no textures, so the walk test above cannot catch a missing format).
#[test]
fn the_texture_formats_a_generated_character_uses_decode() {
    use bevy::image::ImageFormat;
    for mime in ["image/png", "image/jpeg"] {
        assert!(
            ImageFormat::from_mime_type(mime).is_some(),
            "{mime} is not decodable: add its feature to bevy in Cargo.toml"
        );
    }
}

// {{FOOTER}}
