// ---------------------------------------------------------------------------
// examples/shader_check.rs
// Purpose : Renders every kit shader recipe (src/kit_shaders.rs, assets/shaders/kit/*.wesl) into its own 64x64
//           image with the real Bevy renderer and saves each as <out>/<name>.png, for
//           tools/shaders/shader_ref.py compare. `python tools/dev.py smoke --shaders` runs it.
// Usage   : cargo run --example {{GAME_SLUG}}_shader_check -- build/shader_check
//           (the name Cargo.toml's [[example]] gives this file: the game's own, so games sharing one
//           CARGO_TARGET_DIR do not link into one shader_check.pdb, #294)
// Notes   : Pseudocode
//             per recipe: inputs read from data/shaders/inputs/ (linear, nearest), a 64x64 Rgba8Unorm render
//             target, a Camera2d on its own render layer (no tonemapping, no MSAA, transparent clear), and a
//             64x64 Rectangle with the recipe's material at its default parameters on that layer
//             wait until every shader asset is loaded, then WARMUP_FRAMES more (pipelines compile on other
//             threads), then one Screenshot per target -> PNG; SHADER_CHECK_DONE <recipes> <failed>, exit
//           The capture is written by png() below: Bevy's own saver converts only sRGB and float formats, and
//           the target must be linear (Rgba8Unorm) so the picture holds exactly what the shader returned.
//           No window: DefaultPlugins without winit, driven by the schedule runner (headless_renderer style),
//           but with a GPU adapter. A shader that does not compile logs an error and draws nothing: dev.py fails
//           on the error line, and the empty picture fails the compare.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): run under the game's own example name (#294)
// ---------------------------------------------------------------------------
use std::path::PathBuf;
use std::time::{Duration, Instant};

use bevy::app::ScheduleRunnerPlugin;
use bevy::asset::{LoadState, RenderAssetUsages};
use bevy::camera::RenderTarget;
use bevy::camera::visibility::RenderLayers;
use bevy::core_pipeline::tonemapping::Tonemapping;
use bevy::image::{CompressedImageFormats, ImageSampler, ImageType};
use bevy::prelude::*;
use bevy::render::render_resource::{TextureFormat, TextureUsages};
use bevy::render::view::screenshot::{Screenshot, ScreenshotCaptured};
use bevy::shader::Shader;
use bevy::window::ExitCondition;
use bevy::winit::WinitPlugin;

use {{GAME_SLUG}}::kit_shaders::{KIT_RECIPES, KitShadersPlugin, spawn_recipe};

// ---- Tunables ------------------------------------------------------------------
const SIZE: u32 = 64; // the check canvas (tools/shaders/recipes.json)
const INPUTS: &str = "data/shaders/inputs";
const WARMUP_FRAMES: u32 = 30; // after every shader loaded: the pipelines compile on other threads
const WARMUP_MIN: Duration = Duration::from_secs(2);
const GIVE_UP: Duration = Duration::from_secs(240);

#[derive(Resource)]
struct Check {
    out: PathBuf,
    targets: Vec<(&'static str, Handle<Image>)>,
    shaders: Vec<(&'static str, Handle<Shader>)>,
    loaded_at: Option<(u32, Instant)>,
    frame: u32,
    started: Instant,
    requested: bool,
    pending: usize,
    failed: usize,
}

fn main() -> AppExit {
    let out = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("build/shader_check"));
    if let Err(e) = std::fs::create_dir_all(&out) {
        eprintln!("[error] cannot make {}: {e}", out.display());
        return AppExit::from_code(2);
    }
    App::new()
        .add_plugins(
            DefaultPlugins
                .set(WindowPlugin {
                    primary_window: None,
                    exit_condition: ExitCondition::DontExit,
                    ..default()
                })
                .disable::<WinitPlugin>(),
        )
        .add_plugins(ScheduleRunnerPlugin::run_loop(Duration::from_millis(1)))
        .add_plugins(KitShadersPlugin)
        .insert_resource(Check {
            out,
            targets: Vec::new(),
            shaders: Vec::new(),
            loaded_at: None,
            frame: 0,
            started: Instant::now(),
            requested: false,
            pending: 0,
            failed: 0,
        })
        .add_systems(Startup, setup)
        .add_systems(Update, step)
        .run()
}

/// An input picture as a linear, nearest-filtered image ("sphere" is the sphere's normal map).
fn input(name: &str) -> Result<Image, String> {
    let file = if name == "sphere" { "sphere_normal" } else { name };
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join(INPUTS)
        .join(format!("{file}.png"));
    let bytes = std::fs::read(&path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
    Image::from_buffer(
        &bytes,
        ImageType::Extension("png"),
        CompressedImageFormats::NONE,
        false,
        ImageSampler::nearest(),
        RenderAssetUsages::default(),
    )
    .map_err(|e| format!("{}: {e}", path.display()))
}

fn setup(world: &mut World) {
    let mesh = world
        .resource_mut::<Assets<Mesh>>()
        .add(Rectangle::new(SIZE as f32, SIZE as f32));
    let mut targets = Vec::new();
    let mut shaders = Vec::new();
    for (i, (name, main, aux)) in KIT_RECIPES.iter().enumerate() {
        let (main, aux) = match (input(main), aux.map(input).transpose()) {
            (Ok(m), Ok(a)) => (m, a),
            (Err(e), _) | (_, Err(e)) => {
                eprintln!("[error] shader check {name}: {e}");
                std::process::exit(2);
            }
        };
        let mut images = world.resource_mut::<Assets<Image>>();
        let main = images.add(main);
        let aux = aux.map(|a| images.add(a));
        let mut target = Image::new_target_texture(SIZE, SIZE, TextureFormat::Rgba8Unorm, None);
        target.texture_descriptor.usage |= TextureUsages::COPY_SRC;
        let target = images.add(target);
        let layer = RenderLayers::layer(i + 1);
        world.spawn((
            Camera2d,
            Camera {
                order: i as isize,
                clear_color: ClearColorConfig::Custom(Color::NONE),
                ..default()
            },
            RenderTarget::Image(target.clone().into()),
            Tonemapping::None,
            Msaa::Off,
            layer.clone(),
        ));
        spawn_recipe(
            world,
            name,
            main,
            aux,
            (Mesh2d(mesh.clone()), Transform::default(), layer),
        );
        targets.push((*name, target));
        let path = format!("shaders/kit/{name}.wesl");
        shaders.push((*name, world.resource::<AssetServer>().load::<Shader>(path)));
    }
    let mut check = world.resource_mut::<Check>();
    check.targets = targets;
    check.shaders = shaders;
}

fn step(mut commands: Commands, mut check: ResMut<Check>, assets: Res<AssetServer>, mut exit: MessageWriter<AppExit>) {
    check.frame += 1;
    if check.started.elapsed() > GIVE_UP {
        eprintln!(
            "[error] shader check: gave up after {} s ({} picture(s) never arrived)",
            GIVE_UP.as_secs(),
            check.pending
        );
        exit.write(AppExit::from_code(1));
        return;
    }
    if check.loaded_at.is_none() {
        let mut waiting = false;
        let mut failures = Vec::new();
        for (name, h) in &check.shaders {
            match assets.load_state(h) {
                LoadState::Loaded => {}
                LoadState::Failed(e) => failures.push(format!("SHADER_FAIL {name} {e}")),
                _ => waiting = true,
            }
        }
        if !failures.is_empty() {
            for f in &failures {
                println!("{f}");
            }
            println!("SHADER_CHECK_DONE {} {}", check.shaders.len(), failures.len());
            exit.write(AppExit::from_code(1));
            return;
        }
        if !waiting {
            check.loaded_at = Some((check.frame, Instant::now()));
        }
        return;
    }
    let (frame, at) = check.loaded_at.unwrap();
    if !check.requested {
        if check.frame < frame + WARMUP_FRAMES || at.elapsed() < WARMUP_MIN {
            return;
        }
        check.requested = true;
        let targets = check.targets.clone();
        check.pending = targets.len();
        for (name, target) in targets {
            let path = check.out.join(format!("{name}.png"));
            commands.spawn(Screenshot::image(target)).observe(
                move |shot: On<ScreenshotCaptured>, mut check: ResMut<Check>| {
                    check.pending = check.pending.saturating_sub(1);
                    let data = shot.image.data.clone().unwrap_or_default();
                    match png(SIZE, SIZE, &data)
                        .and_then(|bytes| std::fs::write(&path, bytes).map_err(|e| e.to_string()))
                    {
                        Ok(()) => println!("SHADER_OK {name}"),
                        Err(e) => {
                            check.failed += 1;
                            println!("SHADER_FAIL {name} {e}");
                        }
                    }
                },
            );
        }
        return;
    }
    if check.pending == 0 {
        println!("SHADER_CHECK_DONE {} {}", check.targets.len(), check.failed);
        exit.write(if check.failed > 0 {
            AppExit::from_code(1)
        } else {
            AppExit::Success
        });
    }
}

/// An 8-bit RGBA PNG of `rgba` (rows top first), deflate "stored" blocks: no compression crate needed.
fn png(w: u32, h: u32, rgba: &[u8]) -> Result<Vec<u8>, String> {
    let row = (w * 4) as usize;
    if rgba.len() != row * h as usize {
        return Err(format!("capture holds {} bytes, not {}", rgba.len(), row * h as usize));
    }
    let mut raw = Vec::with_capacity((row + 1) * h as usize);
    for line in rgba.chunks(row) {
        raw.push(0); // filter: none
        raw.extend_from_slice(line);
    }
    let mut z = vec![0x78, 0x01];
    let blocks: Vec<&[u8]> = raw.chunks(65535).collect();
    for (i, block) in blocks.iter().enumerate() {
        z.push(u8::from(i + 1 == blocks.len()));
        let n = block.len() as u16;
        z.extend_from_slice(&n.to_le_bytes());
        z.extend_from_slice(&(!n).to_le_bytes());
        z.extend_from_slice(block);
    }
    let (mut a, mut b) = (1u32, 0u32);
    for &byte in &raw {
        a = (a + byte as u32) % 65521;
        b = (b + a) % 65521;
    }
    z.extend_from_slice(&((b << 16) | a).to_be_bytes());
    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&w.to_be_bytes());
    ihdr.extend_from_slice(&h.to_be_bytes());
    ihdr.extend_from_slice(&[8, 6, 0, 0, 0]); // 8-bit, RGBA, deflate, no filter set, no interlace
    let mut out = vec![0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
    for (kind, body) in [(b"IHDR", &ihdr), (b"IDAT", &z), (b"IEND", &Vec::new())] {
        out.extend_from_slice(&(body.len() as u32).to_be_bytes());
        let start = out.len();
        out.extend_from_slice(kind);
        out.extend_from_slice(body);
        out.extend_from_slice(&crc32(&out[start..]).to_be_bytes());
    }
    Ok(out)
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            crc = if crc & 1 != 0 {
                (crc >> 1) ^ 0xEDB8_8320
            } else {
                crc >> 1
            };
        }
    }
    !crc
}

// {{FOOTER}}
