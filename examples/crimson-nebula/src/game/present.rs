// ---------------------------------------------------------------------------
// game/present.rs
// Purpose : Everything the player sees and touches: the neon 3D track built from the race's own geometry, kart
//           models made of simple shapes, the changing sections (walls that open, barriers that rise), item boxes,
//           a chase camera with bloom, the HUD and results, keyboard and gamepad input. Window only: headless runs
//           and tests never add this plugin.
// Usage   : app.add_plugins(PresentPlugin);
// Notes   : Map (x, y) in logic is world (x, 0, -y), so counterclockwise stays counterclockwise seen from above, and
//           a heading h is a rotation of h about +Y (models face +X). Neon = emissive materials plus the camera's
//           Bloom on an Hdr camera. Placeholder art on purpose (GDD: crude first build): no assets are loaded.
//           Pillar 3, "neon tells you everything": red = closing, cyan = opening, gold = items.
//
// Pseudocode:
//   startup: ground grid, road ribbons, edge walls (inner wall pieces that cover a shortcut's mouth are tagged with
//            that shortcut), shortcut walls, barrier blocks per closure, item boxes, karts, camera, HUD
//   every frame: input -> PlayerInput; karts and boxes follow the race; change visuals follow the schedule
//            (pulse while warning, solid when live); chase camera; HUD text; Enter restarts after the race
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use bevy::asset::RenderAssetUsages;
use bevy::camera::Hdr;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::post_process::bloom::Bloom;
use bevy::prelude::*;

use super::{GameConfig, KARTS, NAMES, PlayerInput, RaceRes, fresh_seed, new_race};
use crate::logic::kart::{Item, KartInput};
use crate::logic::race::{ChangeState, Phase, Race};
use crate::logic::track::{ChangeKind, Strip};
use crate::logic::tuning::*;

// ---- Look ----------------------------------------------------------------------
const SKY: Color = Color::srgb(0.008, 0.006, 0.02);
const ROAD: Color = Color::srgb(0.018, 0.015, 0.03);
const WALL_HEIGHT: f32 = 0.7;
const MAGENTA: LinearRgba = LinearRgba::rgb(4.0, 0.25, 3.2);
const CYAN: LinearRgba = LinearRgba::rgb(0.2, 2.6, 4.5);
const RED: LinearRgba = LinearRgba::rgb(6.0, 0.25, 0.35);
const GOLD: LinearRgba = LinearRgba::rgb(5.0, 3.2, 0.3);
const GRID: LinearRgba = LinearRgba::rgb(0.25, 0.05, 0.4);
/// Kart colors: you, Vex, Nova, Rook.
const KART_GLOW: [LinearRgba; KARTS] = [
    LinearRgba::rgb(5.0, 0.6, 4.0),
    LinearRgba::rgb(0.3, 3.5, 5.0),
    LinearRgba::rgb(1.2, 5.0, 0.6),
    LinearRgba::rgb(5.0, 1.6, 0.2),
];
// ---- Camera --------------------------------------------------------------------
const CAM_BACK: f32 = 6.5;
const CAM_UP: f32 = 3.0;
const CAM_LOOK_AHEAD: f32 = 7.0;
const CAM_FOLLOW: f32 = 14.0;
const FOV: f32 = 70.0;
const FOV_BOOST: f32 = 82.0;

pub struct PresentPlugin;

impl Plugin for PresentPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(ClearColor(SKY))
            .insert_resource(GlobalAmbientLight {
                color: Color::srgb(0.6, 0.5, 1.0),
                brightness: 20.0,
                ..default()
            })
            .add_systems(Startup, (setup_world, setup_hud))
            .add_systems(
                RunFixedMainLoop,
                read_input.in_set(RunFixedMainLoopSystems::BeforeFixedMainLoop),
            )
            .add_systems(
                Update,
                (
                    sync_karts,
                    sync_items,
                    show_changes,
                    chase_camera,
                    update_hud,
                    restart_or_quit,
                ),
            );
    }
}

// ---- Components ------------------------------------------------------------------
#[derive(Component)]
struct KartView {
    index: usize,
    body: Handle<StandardMaterial>,
    glow: Handle<StandardMaterial>,
}

#[derive(Component)]
struct ItemBoxView(usize);

/// A piece of the loop's inner wall across a shortcut's mouth: gone while that shortcut is live.
#[derive(Component)]
struct MouthWall(usize);

/// One block of a closed lane's barrier.
#[derive(Component)]
struct BarrierBlock(usize);

#[derive(Component)]
struct ChaseCam;

#[derive(Component)]
enum Hud {
    Lap,
    Place,
    Item,
    Banner,
    Center,
    Results,
}

/// Materials the change visuals recolor every frame.
#[derive(Resource)]
struct ChangeMaterials {
    shortcut_walls: Vec<Handle<StandardMaterial>>,
    shortcut_roads: Vec<Handle<StandardMaterial>>,
    barriers: Vec<Handle<StandardMaterial>>,
}

// ---- Geometry helpers ------------------------------------------------------------
fn world(p: Vec2, y: f32) -> Vec3 {
    Vec3::new(p.x, y, -p.y)
}

/// Left normal at each centerline point (averaged over the neighbouring segments).
fn normals(points: &[Vec2], closed: bool) -> Vec<Vec2> {
    let n = points.len();
    (0..n)
        .map(|i| {
            let prev = if i > 0 {
                points[i - 1]
            } else if closed {
                points[n - 1]
            } else {
                points[0]
            };
            let next = if i + 1 < n {
                points[i + 1]
            } else if closed {
                points[0]
            } else {
                points[n - 1]
            };
            (next - prev).normalize_or(Vec2::X).perp()
        })
        .collect()
}

/// A flat band between two lateral offsets along a strip, at height y.
fn ribbon(strip: &Strip, from: f32, to: f32, y: f32) -> Mesh {
    let pts = &strip.points;
    let nrm = normals(pts, strip.closed);
    let mut pos = Vec::new();
    for (p, n) in pts.iter().zip(&nrm) {
        pos.push(world(*p + *n * from, y).to_array());
        pos.push(world(*p + *n * to, y).to_array());
    }
    let count = pts.len() as u32;
    let segs = if strip.closed { count } else { count - 1 };
    let mut idx = Vec::new();
    for i in 0..segs {
        let (a, b) = (i * 2, ((i + 1) % count) * 2);
        idx.extend_from_slice(&[a, b, a + 1, a + 1, b, b + 1]);
    }
    let normals = vec![[0.0, 1.0, 0.0]; pos.len()];
    Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, normals)
        .with_inserted_indices(Indices::U32(idx))
}

/// A thin vertical wall through a run of points, both faces (it glows, so lighting barely matters).
fn wall(run: &[Vec2], height: f32) -> Mesh {
    let mut pos = Vec::new();
    for p in run {
        pos.push(world(*p, 0.0).to_array());
        pos.push(world(*p, height).to_array());
    }
    let mut idx = Vec::new();
    for i in 0..run.len().saturating_sub(1) as u32 {
        let (a, b) = (i * 2, (i + 1) * 2);
        idx.extend_from_slice(&[a, b, a + 1, a + 1, b, b + 1, a, a + 1, b, a + 1, b + 1, b]);
    }
    let normals = vec![[0.0, 1.0, 0.0]; pos.len()];
    Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, normals)
        .with_inserted_indices(Indices::U32(idx))
}

/// Splits points into runs of equal tag; each run starts on the previous run's last point, so walls have no gaps.
fn runs<T: PartialEq + Copy>(points: &[Vec2], tags: &[T]) -> Vec<(T, Vec<Vec2>)> {
    let mut out: Vec<(T, Vec<Vec2>)> = Vec::new();
    for (p, t) in points.iter().zip(tags) {
        match out.last_mut() {
            Some((tag, run)) if tag == t => run.push(*p),
            _ => {
                let mut run: Vec<Vec2> = out.last().and_then(|(_, r)| r.last().copied()).into_iter().collect();
                run.push(*p);
                out.push((*t, run));
            }
        }
    }
    out
}

fn glow(materials: &mut Assets<StandardMaterial>, color: LinearRgba) -> Handle<StandardMaterial> {
    materials.add(StandardMaterial {
        base_color: Color::BLACK,
        emissive: color,
        ..default()
    })
}

// ---- Startup -----------------------------------------------------------------------
fn setup_world(
    mut commands: Commands,
    race: Res<RaceRes>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    let track = &race.0.track;
    let road = materials.add(StandardMaterial {
        base_color: ROAD,
        perceptual_roughness: 0.6,
        ..default()
    });

    // Ground grid: thin glowing lines every 25 m under the whole track
    let grid_mat = glow(&mut materials, GRID);
    let mut lines = Vec::new();
    for i in -6..=16 {
        let x = i as f32 * 25.0;
        lines.push((Vec2::new(x, -100.0), Vec2::new(x, 350.0)));
    }
    for j in -4..=14 {
        let y = j as f32 * 25.0;
        lines.push((Vec2::new(-150.0, y), Vec2::new(400.0, y)));
    }
    for (a, b) in lines {
        let strip = Strip::new(vec![a, b], false, 0.0);
        commands.spawn((
            Mesh3d(meshes.add(ribbon(&strip, -0.08, 0.08, -0.05))),
            MeshMaterial3d(grid_mat.clone()),
        ));
    }

    // The loop: road, outer wall, inner wall (opened at shortcut mouths)
    let half = track.main.half_width;
    commands.spawn((
        Mesh3d(meshes.add(ribbon(&track.main, -half, half, 0.0))),
        MeshMaterial3d(road.clone()),
    ));
    let main_wall = glow(&mut materials, MAGENTA);
    let nrm = normals(&track.main.points, true);
    let mut outer: Vec<Vec2> = track
        .main
        .points
        .iter()
        .zip(&nrm)
        .map(|(p, n)| *p - *n * half)
        .collect();
    outer.push(outer[0]);
    commands.spawn((
        Mesh3d(meshes.add(wall(&outer, WALL_HEIGHT))),
        MeshMaterial3d(main_wall.clone()),
    ));
    let mut inner: Vec<Vec2> = track
        .main
        .points
        .iter()
        .zip(&nrm)
        .map(|(p, n)| *p + *n * half)
        .collect();
    inner.push(inner[0]);
    let mouth: Vec<Option<usize>> = inner
        .iter()
        .map(|p| track.shortcuts.iter().position(|sc| sc.strip.contains(*p, 0.5)))
        .collect();
    for (tag, run) in runs(&inner, &mouth) {
        let mut e = commands.spawn((
            Mesh3d(meshes.add(wall(&run, WALL_HEIGHT))),
            MeshMaterial3d(main_wall.clone()),
        ));
        if let Some(i) = tag {
            e.insert(MouthWall(i));
        }
    }

    // Shortcuts: road and walls in their own materials (recolored by state)
    let mut shortcut_walls = Vec::new();
    let mut shortcut_roads = Vec::new();
    for sc in &track.shortcuts {
        let wall_mat = glow(&mut materials, CYAN * 0.15);
        let road_mat = materials.add(StandardMaterial {
            base_color: ROAD,
            emissive: LinearRgba::BLACK,
            ..default()
        });
        let w = sc.strip.half_width;
        commands.spawn((
            Mesh3d(meshes.add(ribbon(&sc.strip, -w, w, 0.01))),
            MeshMaterial3d(road_mat.clone()),
        ));
        let snrm = normals(&sc.strip.points, false);
        for side in [1.0, -1.0] {
            let edge: Vec<Vec2> = sc
                .strip
                .points
                .iter()
                .zip(&snrm)
                .map(|(p, n)| *p + *n * w * side)
                .collect();
            // Only where it runs outside the loop's road
            let outside: Vec<bool> = edge.iter().map(|p| !track.main.contains(*p, -0.5)).collect();
            for (out, run) in runs(&edge, &outside) {
                if out && run.len() > 1 {
                    commands.spawn((
                        Mesh3d(meshes.add(wall(&run, WALL_HEIGHT))),
                        MeshMaterial3d(wall_mat.clone()),
                    ));
                }
            }
        }
        shortcut_walls.push(wall_mat);
        shortcut_roads.push(road_mat);
    }

    // Closures: blocks along the blocked side, tapering in like the logic's barrier
    let mut barriers = Vec::new();
    let block = meshes.add(Cuboid::new(2.6, 1.3, 1.0));
    for (i, c) in track.closures.iter().enumerate() {
        let mat = glow(&mut materials, RED);
        let mut s = c.s_from;
        while s <= c.s_to {
            let bound = c.bound(s).unwrap_or(half);
            let (p, t) = track.main.point_at(s);
            let width = (half - bound).max(0.2);
            let center = p + t.perp() * c.side.sign() * (bound + width / 2.0);
            let heading = t.y.atan2(t.x);
            commands.spawn((
                Mesh3d(block.clone()),
                MeshMaterial3d(mat.clone()),
                Transform::from_translation(world(center, 0.65))
                    .with_rotation(Quat::from_rotation_y(heading))
                    .with_scale(Vec3::new(1.0, 1.0, width)),
                Visibility::Hidden,
                BarrierBlock(i),
            ));
            s += 2.5;
        }
        barriers.push(mat);
    }
    commands.insert_resource(ChangeMaterials {
        shortcut_walls,
        shortcut_roads,
        barriers,
    });

    // Item boxes
    let cube = meshes.add(Cuboid::new(1.3, 1.3, 1.3));
    let gold = glow(&mut materials, GOLD);
    for (i, b) in race.0.boxes.iter().enumerate() {
        commands.spawn((
            Mesh3d(cube.clone()),
            MeshMaterial3d(gold.clone()),
            Transform::from_translation(world(b.pos, 1.0)),
            ItemBoxView(i),
        ));
    }

    // Karts
    for i in 0..race.0.racers.len() {
        spawn_kart(&mut commands, &mut meshes, &mut materials, i, &race.0);
    }

    // Light and camera
    commands.spawn((
        DirectionalLight {
            illuminance: 500.0,
            ..default()
        },
        Transform::from_xyz(50.0, 120.0, 40.0).looking_at(Vec3::ZERO, Vec3::Y),
    ));
    let start = &race.0.racers[0].kart;
    let fwd = world(start.forward(), 0.0);
    let eye = world(start.pos, CAM_UP) - fwd * CAM_BACK;
    commands.spawn((
        Camera3d::default(),
        Hdr,
        Bloom::NATURAL,
        Projection::from(PerspectiveProjection {
            fov: FOV.to_radians(),
            ..default()
        }),
        Transform::from_translation(eye).looking_at(world(start.pos, 1.0) + fwd * CAM_LOOK_AHEAD, Vec3::Y),
        ChaseCam,
    ));
}

/// A kart from simple shapes, nose along +X: body, nose, four wheels, driver and helmet, and a glowing underside.
fn spawn_kart(
    commands: &mut Commands,
    meshes: &mut Assets<Mesh>,
    materials: &mut Assets<StandardMaterial>,
    index: usize,
    race: &Race,
) {
    let color = KART_GLOW[index];
    let body = materials.add(StandardMaterial {
        base_color: Color::linear_rgb(color.red * 0.06, color.green * 0.06, color.blue * 0.06),
        emissive: color * 0.08,
        metallic: 0.3,
        perceptual_roughness: 0.4,
        ..default()
    });
    let glow_mat = glow(materials, color);
    let tyre = materials.add(StandardMaterial {
        base_color: Color::srgb(0.02, 0.02, 0.025),
        ..default()
    });
    let suit = materials.add(StandardMaterial {
        base_color: Color::srgb(0.15, 0.15, 0.18),
        ..default()
    });
    let kart = &race.racers[index].kart;
    let wheel = meshes.add(Cylinder::new(0.32, 0.3));
    let chassis = meshes.add(Cuboid::new(2.1, 0.35, 1.2));
    let nose = meshes.add(Cuboid::new(0.7, 0.25, 0.9));
    let driver = meshes.add(Capsule3d::new(0.26, 0.35));
    let helmet = meshes.add(Sphere::new(0.27));
    let underglow = meshes.add(Cuboid::new(2.2, 0.04, 1.3));
    commands
        .spawn((
            Transform::from_translation(world(kart.pos, 0.0)).with_rotation(Quat::from_rotation_y(kart.heading)),
            Visibility::Inherited,
            KartView {
                index,
                body: body.clone(),
                glow: glow_mat.clone(),
            },
        ))
        .with_children(|k| {
            k.spawn((
                Mesh3d(chassis),
                MeshMaterial3d(body.clone()),
                Transform::from_xyz(0.0, 0.42, 0.0),
            ));
            k.spawn((
                Mesh3d(nose),
                MeshMaterial3d(glow_mat.clone()),
                Transform::from_xyz(1.2, 0.38, 0.0),
            ));
            for (x, z) in [(0.72, 0.68), (0.72, -0.68), (-0.72, 0.72), (-0.72, -0.72)] {
                k.spawn((
                    Mesh3d(wheel.clone()),
                    MeshMaterial3d(tyre.clone()),
                    Transform::from_xyz(x, 0.32, z).with_rotation(Quat::from_rotation_x(std::f32::consts::FRAC_PI_2)),
                ));
            }
            k.spawn((
                Mesh3d(driver),
                MeshMaterial3d(suit.clone()),
                Transform::from_xyz(-0.25, 0.85, 0.0),
            ));
            k.spawn((
                Mesh3d(helmet),
                MeshMaterial3d(glow_mat.clone()),
                Transform::from_xyz(-0.2, 1.3, 0.0),
            ));
            k.spawn((
                Mesh3d(underglow),
                MeshMaterial3d(glow_mat.clone()),
                Transform::from_xyz(0.0, 0.06, 0.0),
            ));
        });
}

fn setup_hud(mut commands: Commands) {
    let text = |size: f32| (TextFont::from_font_size(size), TextColor(Color::srgb(0.95, 0.9, 1.0)));
    let at = |left: Option<f32>, right: Option<f32>, top: f32| Node {
        position_type: PositionType::Absolute,
        left: left.map_or(Val::Auto, Val::Px),
        right: right.map_or(Val::Auto, Val::Px),
        top: Val::Px(top),
        ..default()
    };
    let centered = |top: Val| Node {
        position_type: PositionType::Absolute,
        top,
        width: Val::Percent(100.0),
        ..default()
    };
    commands.spawn((Text::new(""), text(30.0), at(Some(24.0), None, 18.0), Hud::Lap));
    commands.spawn((Text::new(""), text(30.0), at(Some(24.0), None, 56.0), Hud::Place));
    commands.spawn((Text::new(""), text(30.0), at(None, Some(24.0), 18.0), Hud::Item));
    commands.spawn((
        Text::new(""),
        TextFont::from_font_size(34.0),
        TextColor(Color::srgb(1.0, 0.3, 0.35)),
        centered(Val::Px(110.0)),
        TextLayout::justify(Justify::Center),
        Hud::Banner,
    ));
    commands.spawn((
        Text::new(""),
        TextFont::from_font_size(90.0),
        TextColor(Color::srgb(1.0, 0.95, 0.5)),
        centered(Val::Percent(30.0)),
        TextLayout::justify(Justify::Center),
        Hud::Center,
    ));
    commands.spawn((
        Text::new(""),
        TextFont::from_font_size(30.0),
        TextColor(Color::srgb(0.9, 0.95, 1.0)),
        centered(Val::Percent(28.0)),
        TextLayout::justify(Justify::Center),
        Hud::Results,
    ));
}

// ---- Every frame ---------------------------------------------------------------------
/// Keyboard and gamepad -> PlayerInput, right before this frame's fixed ticks.
fn read_input(keys: Res<ButtonInput<KeyCode>>, pads: Query<&Gamepad>, mut input: ResMut<PlayerInput>) {
    let mut throttle: f32 = 0.0;
    let mut steer: f32 = 0.0;
    if keys.any_pressed([KeyCode::KeyW, KeyCode::ArrowUp]) {
        throttle += 1.0;
    }
    if keys.any_pressed([KeyCode::KeyS, KeyCode::ArrowDown]) {
        throttle -= 1.0;
    }
    if keys.any_pressed([KeyCode::KeyA, KeyCode::ArrowLeft]) {
        steer += 1.0;
    }
    if keys.any_pressed([KeyCode::KeyD, KeyCode::ArrowRight]) {
        steer -= 1.0;
    }
    let mut drift = keys.any_pressed([KeyCode::ShiftLeft, KeyCode::ShiftRight]);
    let mut use_item = keys.pressed(KeyCode::Space);
    for pad in &pads {
        let gas = pad.get(GamepadButton::RightTrigger2).unwrap_or(0.0);
        let brake = pad.get(GamepadButton::LeftTrigger2).unwrap_or(0.0);
        if gas > 0.05 || brake > 0.05 {
            throttle = gas - brake;
        }
        let stick = pad.get(GamepadAxis::LeftStickX).unwrap_or(0.0);
        if stick.abs() > 0.12 {
            steer = -stick;
        }
        drift |= pad.pressed(GamepadButton::RightTrigger);
        use_item |= pad.pressed(GamepadButton::South);
    }
    input.0 = KartInput {
        throttle: throttle.clamp(-1.0, 1.0),
        steer: steer.clamp(-1.0, 1.0),
        drift,
        use_item,
    };
}

fn sync_karts(
    race: Res<RaceRes>,
    mut karts: Query<(&KartView, &mut Transform)>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    for (view, mut tf) in &mut karts {
        let Some(r) = race.0.racers.get(view.index) else {
            continue;
        };
        tf.translation = world(r.kart.pos, 0.0);
        tf.rotation = Quat::from_rotation_y(r.kart.heading);
        // A zap flashes the kart red; a boost brightens its glow
        let base = KART_GLOW[view.index];
        if let Some(mut m) = materials.get_mut(&view.body) {
            m.emissive = if r.zap_cooldown > ZAP_COOLDOWN - 0.35 {
                RED
            } else {
                base * 0.08
            };
        }
        if let Some(mut m) = materials.get_mut(&view.glow) {
            m.emissive = if r.kart.boost > 0.0 { base * 2.5 } else { base };
        }
    }
}

fn sync_items(time: Res<Time>, race: Res<RaceRes>, mut boxes: Query<(&ItemBoxView, &mut Transform, &mut Visibility)>) {
    for (view, mut tf, mut vis) in &mut boxes {
        let available = race.0.boxes.get(view.0).is_some_and(|b| b.respawn == 0.0);
        *vis = if available {
            Visibility::Inherited
        } else {
            Visibility::Hidden
        };
        tf.rotation = Quat::from_rotation_y(time.elapsed_secs() * 1.6) * Quat::from_rotation_x(0.6);
    }
}

/// Glow and visibility of every changing section, from the race schedule.
fn show_changes(
    time: Res<Time>,
    race: Res<RaceRes>,
    mats: Res<ChangeMaterials>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut mouths: Query<(&MouthWall, &mut Visibility), Without<BarrierBlock>>,
    mut blocks: Query<(&BarrierBlock, &mut Transform, &mut Visibility), Without<MouthWall>>,
) {
    let track = &race.0.track;
    let pulse = 0.5 + 0.5 * (time.elapsed_secs() * 10.0).sin();
    let mut shortcut_state = vec![ChangeState::Pending; track.shortcuts.len()];
    let mut closure_state = vec![ChangeState::Pending; track.closures.len()];
    for sc in &race.0.schedule {
        match track.changes[sc.change] {
            ChangeKind::OpenShortcut(i) => shortcut_state[i] = sc.state,
            ChangeKind::CloseLane(i) => closure_state[i] = sc.state,
        }
    }
    for (i, state) in shortcut_state.iter().enumerate() {
        let (wall, road) = match state {
            ChangeState::Warning(_) => (CYAN * (0.3 + 1.2 * pulse), CYAN * (0.05 + 0.15 * pulse)),
            ChangeState::Live => (CYAN, CYAN * 0.06),
            _ => (CYAN * 0.12, LinearRgba::BLACK),
        };
        if let Some(mut m) = materials.get_mut(&mats.shortcut_walls[i]) {
            m.emissive = wall;
        }
        if let Some(mut m) = materials.get_mut(&mats.shortcut_roads[i]) {
            m.emissive = road;
        }
    }
    for (mouth, mut vis) in &mut mouths {
        *vis = if shortcut_state[mouth.0] == ChangeState::Live {
            Visibility::Hidden
        } else {
            Visibility::Inherited
        };
    }
    for (i, state) in closure_state.iter().enumerate() {
        if let Some(mut m) = materials.get_mut(&mats.barriers[i]) {
            m.emissive = match state {
                ChangeState::Warning(_) => RED * (0.4 + 1.6 * pulse),
                _ => RED,
            };
        }
    }
    for (block, mut tf, mut vis) in &mut blocks {
        let (shown, height) = match closure_state[block.0] {
            ChangeState::Warning(left) => (true, 0.12 + 0.25 * (1.0 - left / WARN_TIME)),
            ChangeState::Live => (true, 1.0),
            _ => (false, 0.0),
        };
        *vis = if shown {
            Visibility::Inherited
        } else {
            Visibility::Hidden
        };
        tf.scale.y = height.max(0.01);
        tf.translation.y = 0.65 * height;
    }
}

fn chase_camera(
    time: Res<Time>,
    race: Res<RaceRes>,
    mut cam: Query<(&mut Transform, &mut Projection), With<ChaseCam>>,
) {
    let Ok((mut tf, mut proj)) = cam.single_mut() else {
        return;
    };
    let kart = &race.0.racers[0].kart;
    let fwd = world(kart.forward(), 0.0);
    let want_eye = world(kart.pos, CAM_UP) - fwd * CAM_BACK;
    let k = 1.0 - (-CAM_FOLLOW * time.delta_secs()).exp();
    tf.translation = tf.translation.lerp(want_eye, k);
    tf.look_at(world(kart.pos, 1.0) + fwd * CAM_LOOK_AHEAD, Vec3::Y);
    if let Projection::Perspective(p) = proj.as_mut() {
        let want = if kart.boost > 0.0 { FOV_BOOST } else { FOV };
        p.fov += (want.to_radians() - p.fov) * k;
    }
}

fn update_hud(race: Res<RaceRes>, mut hud: Query<(&Hud, &mut Text)>) {
    let r = &race.0;
    let me = &r.racers[0];
    let banner = r
        .schedule
        .iter()
        .find_map(|sc| match (sc.state, r.track.changes[sc.change]) {
            (ChangeState::Warning(_), ChangeKind::CloseLane(i)) => Some(format!(
                "TRACK SHIFT: {} LANE CLOSING",
                if r.track.closures[i].side.sign() > 0.0 {
                    "LEFT"
                } else {
                    "RIGHT"
                }
            )),
            (ChangeState::Warning(_), ChangeKind::OpenShortcut(_)) => Some("TRACK SHIFT: SHORTCUT OPENING".into()),
            _ => None,
        })
        .unwrap_or_default();
    let center = if r.phase == Phase::Countdown {
        format!("{}", (COUNTDOWN - r.time).ceil().max(1.0) as i32)
    } else if r.time < COUNTDOWN + 1.0 {
        "GO!".into()
    } else {
        String::new()
    };
    let results = if r.phase == Phase::Over {
        let mut lines = vec!["RESULTS".to_string()];
        for (place, &k) in r.standings().iter().enumerate() {
            let time = r.racers[k]
                .finished
                .map_or("did not finish".to_string(), |t| format!("{t:.2} s"));
            lines.push(format!("{}. {}   {}", place + 1, NAMES[k], time));
        }
        lines.push(String::new());
        lines.push(format!("Track seed {}   Enter: race again   Esc: quit", r.seed));
        lines.join("\n")
    } else {
        String::new()
    };
    for (which, mut text) in &mut hud {
        text.0 = match which {
            Hud::Lap => format!("LAP {}/{}", r.lap_of(0), LAPS),
            Hud::Place => format!("POS {}/{}", r.place_of(0), r.racers.len()),
            Hud::Item => match me.kart.item {
                Some(Item::Boost) => "[ BOOST ]  Space".into(),
                None => "[  --  ]".into(),
            },
            Hud::Banner => banner.clone(),
            Hud::Center => center.clone(),
            Hud::Results => results.clone(),
        };
    }
}

fn restart_or_quit(
    keys: Res<ButtonInput<KeyCode>>,
    pads: Query<&Gamepad>,
    race: Res<RaceRes>,
    cfg: Res<GameConfig>,
    mut commands: Commands,
    mut exit: MessageWriter<AppExit>,
) {
    if keys.just_pressed(KeyCode::Escape) {
        exit.write(AppExit::Success);
    }
    let again = keys.just_pressed(KeyCode::Enter) || pads.iter().any(|p| p.just_pressed(GamepadButton::Start));
    if again && race.0.phase == Phase::Over && cfg.autoplay.is_none() {
        commands.insert_resource(new_race(fresh_seed()));
    }
}
