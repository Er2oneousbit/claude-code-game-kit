// ---------------------------------------------------------------------------
// shell/juice.rs
// Purpose : The juice demo (debug builds, main menu > Juice demo): a box you hit (attack) that shakes the camera
//           with trauma, freezes the demo for a hitstop, squashes on a spring and flashes the screen through the
//           FlashLimiter; a follow camera with a visible deadzone; an input-buffered jump with coyote time; a held
//           guard (interact) that honours hold_to_toggle; a subtitle line and a bark; and the accessibility settings
//           applied live (game speed, timing scale, auto repeat, flash limit, reduce motion, the colour-blind palette).
// Usage   : the shell runs it while ScreenName::Juice is on the stack (shell.juice holds its state);
//           python tools/dev.py smoke --drive show:juice --screenshot captures/juice.png pictures a hit
// Notes   : Time: the hitstop and the flash limiter run on REAL time (the frame's dt); everything else (shake,
//           follow, spring, input buffer, coyote) runs on DEMO time = the hitstop-scaled dt times game_speed.
//           The limiter is always on (at most 3 flashes per real second); access.flash_limit only tones each flash
//           down to FLASH_GENTLE. Shake intensity is settings::effective_shake (0 with reduce motion). The logic
//           (Demo) is plain data the headless shell steps, so tests/shell.rs checks it without a GPU; the window
//           side (JuiceViewPlugin, added by ShellViewPlugin) draws it with sprites and gizmos.
//           The demo needs nothing from the game (src/game/ can be any shape, 2D or 3D): it brings its own 2D camera
//           on its own render layer (JUICE_LAYER), above every camera of the game's, which it switches off while it
//           is up; the game's world stays out of the demo's picture without a tag. Tag the game's HUD and other UI
//           with HideUnderJuice (the demo's camera draws the UI meanwhile): it hides while the demo is up. Leaving
//           puts back each camera's is_active and IsDefaultUiCamera and each tagged entity's Visibility as they were.
//           World units: x right, y up, the floor's top at y = 0.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): no import from game (HideUnderJuice, the demo's
//           own camera and layer), so a game that reshapes its game module keeps compiling
// ---------------------------------------------------------------------------
use bevy::camera::visibility::{RenderLayers, VisibilitySystems};
use bevy::prelude::*;

use super::{ScreenName, Shell, view};
use crate::logic::auto_repeat::AutoRepeat;
use crate::logic::coyote::Coyote;
use crate::logic::ease;
use crate::logic::flash_limiter::FlashLimiter;
use crate::logic::follow::Follow;
use crate::logic::hitstop::Hitstop;
use crate::logic::input_buffer::{self, InputBuffer};
use crate::logic::settings;
use crate::logic::shake::Shake;
use crate::logic::spring::{self, Spring};

// ---- Tunables ------------------------------------------------------------------
/// Coyote time before access.timing_scale.
pub const COYOTE_S: f64 = 0.1;
pub const WORLD_W: f64 = 1600.0;
pub const PLAYER: f64 = 20.0;
pub const TARGET: f64 = 40.0;
pub const TARGET_X: f64 = 440.0;
pub const START_X: f64 = 380.0;
pub const SPEED: f64 = 160.0;
pub const GRAVITY: f64 = 900.0;
pub const JUMP_SPEED: f64 = 340.0;
/// px between the player's and the box's centres for a hit to land.
pub const HIT_RANGE: f64 = 80.0;
pub const HIT_TRAUMA: f64 = 0.55;
pub const HIT_STOP_S: f64 = 0.09;
/// Spring displacement on a hit (the box squashes).
pub const HIT_SQUASH: f64 = 0.45;
/// A flash fades out over this (real time).
pub const FLASH_S: f64 = 0.12;
/// Peak flash opacity without / with access.flash_limit.
pub const FLASH_FULL: f64 = 0.85;
pub const FLASH_GENTLE: f64 = 0.3;
/// The "hit" ring eases out over this.
pub const POP_S: f64 = 0.25;
/// The camera looks this far above the player, so the floor sits low on the screen under the HUD.
pub const CAM_LIFT: f64 = 120.0;

/// What the player holds this frame (the shell fills it from the bindings and the stick).
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Held {
    /// -1 to 1.
    pub dir_x: f64,
    pub attack: bool,
    pub interact: bool,
}

/// The settings the demo follows, read once a frame.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Rules {
    pub game_speed: f64,
    pub timing_scale: f64,
    pub auto_repeat: bool,
    pub hold_to_toggle: bool,
    pub flash_limit: bool,
    pub shake: f64,
}

impl Rules {
    pub fn from_settings(s: &serde_json::Value) -> Rules {
        Rules {
            game_speed: settings::num(s, "access", "game_speed"),
            timing_scale: settings::num(s, "access", "timing_scale"),
            auto_repeat: settings::flag(s, "access", "auto_repeat"),
            hold_to_toggle: settings::flag(s, "access", "hold_to_toggle"),
            flash_limit: settings::flag(s, "access", "flash_limit"),
            shake: settings::effective_shake(s),
        }
    }
}

/// The demo's state.
#[derive(Debug, Clone)]
pub struct Demo {
    /// The player's bottom-left corner and velocity.
    pub pos: (f64, f64),
    pub vel: (f64, f64),
    pub shake: Shake,
    pub hitstop: Hitstop,
    pub cam: Follow,
    pub buffer: InputBuffer,
    pub coyote: Coyote,
    pub attack_repeat: AutoRepeat,
    pub spring: Spring,
    pub limiter: FlashLimiter,
    pub real_time: f64,
    /// Seconds of flash left (real time) and its peak opacity.
    pub flash: f64,
    pub flash_peak: f64,
    pub hits: u32,
    /// Flashes the limiter held back.
    pub refused: u32,
    pub pop: f64,
    pub guard: bool,
    /// This frame's shake: (x, y, angle).
    pub offset: (f64, f64, f64),
}

impl Default for Demo {
    fn default() -> Self {
        Demo::new()
    }
}

impl Demo {
    pub fn new() -> Demo {
        Demo {
            pos: (START_X, 0.0),
            vel: (0.0, 0.0),
            shake: Shake {
                max_offset: 10.0,
                max_angle: 0.04,
                ..Shake::default()
            },
            hitstop: Hitstop::default(),
            cam: Follow {
                deadzone_w: 96.0,
                deadzone_h: 64.0,
                lookahead: 0.2,
                smoothing: 6.0,
                x: START_X + PLAYER / 2.0,
                y: CAM_LIFT,
            },
            buffer: InputBuffer::default(),
            coyote: Coyote::new(COYOTE_S),
            attack_repeat: AutoRepeat::default(),
            spring: Spring {
                frequency: 4.0,
                damping: 0.35,
                ..Spring::default()
            },
            limiter: FlashLimiter::default(),
            real_time: 0.0,
            flash: 0.0,
            flash_peak: 0.0,
            hits: 0,
            refused: 0,
            pop: 0.0,
            guard: false,
            offset: (0.0, 0.0, 0.0),
        }
    }

    /// Is the player close enough to the box to hit it?
    pub fn in_range(&self) -> bool {
        ((self.pos.0 + PLAYER / 2.0) - (TARGET_X + TARGET / 2.0)).abs() <= HIT_RANGE
    }

    /// An attack: true when it landed (shake, hitstop, squash, the ring, a flash if the limiter allows one).
    pub fn hit(&mut self, flash_limit: bool) -> bool {
        if !self.in_range() {
            return false;
        }
        self.hits += 1;
        self.shake.add_trauma(HIT_TRAUMA);
        self.hitstop.hit(HIT_STOP_S);
        self.spring.x = HIT_SQUASH;
        self.pop = POP_S;
        if self.limiter.request(self.real_time) {
            self.flash = FLASH_S;
            self.flash_peak = if flash_limit { FLASH_GENTLE } else { FLASH_FULL };
        } else {
            self.refused += 1;
        }
        true
    }

    /// One frame of `real_dt` seconds. Returns how many hits the held attack's auto-repeat landed.
    pub fn update(&mut self, real_dt: f64, held: Held, rules: Rules) -> u32 {
        self.real_time += real_dt;
        self.flash = (self.flash - real_dt).max(0.0);
        let dt = self.hitstop.scaled_dt(real_dt) * rules.game_speed; // demo time from here on
        self.vel.0 = held.dir_x.clamp(-1.0, 1.0) * SPEED;
        self.pos.0 = (self.pos.0 + self.vel.0 * dt).clamp(0.0, WORLD_W - PLAYER);
        self.vel.1 -= GRAVITY * dt;
        self.pos.1 += self.vel.1 * dt;
        let on_floor = self.pos.1 <= 0.0;
        if on_floor {
            self.pos.1 = 0.0;
            self.vel.1 = 0.0;
        }
        // access.timing_scale (#166): every timing window, longer by the player's factor
        self.buffer.window_s = input_buffer::WINDOW_S * rules.timing_scale;
        self.coyote.window_s = COYOTE_S * rules.timing_scale;
        let mut repeats = 0;
        if rules.auto_repeat && self.attack_repeat.update(dt, held.attack) && self.hit(rules.flash_limit) {
            repeats += 1;
        }
        self.coyote.update(dt, on_floor);
        self.buffer.update(dt);
        if self.coyote.can_jump() && self.buffer.consume("jump") {
            self.vel.1 = JUMP_SPEED;
            self.coyote.consume();
        }
        if !rules.hold_to_toggle {
            self.guard = held.interact;
        }
        self.cam
            .update(dt, self.pos.0 + PLAYER / 2.0, self.pos.1 + CAM_LIFT, self.vel.0, 0.0);
        self.offset = self.shake.update(dt, rules.shake);
        self.spring.update(dt);
        self.pop = (self.pop - dt).max(0.0);
        repeats
    }

    /// The HUD's numbers line.
    pub fn stats(&self, shell: &Shell) -> String {
        let speed = format!("{}", (shell.num("access", "game_speed") * 100.0).round() as i64);
        shell.t_args(
            "juice.stats",
            &[
                ("hits", &self.hits.to_string()),
                ("trauma", &format!("{:.2}", self.shake.trauma)),
                ("shake", &format!("{:.2}", settings::effective_shake(&shell.settings))),
                ("refused", &self.refused.to_string()),
                ("speed", &speed),
            ],
        )
    }
}

// ---- The shell's side (headless) ---------------------------------------------------------------------------------
/// The demo starts: fresh state, the goal for "What now?", the guide's line.
pub fn start(shell: &mut Shell) {
    shell.juice = Some(Demo::new());
    let goal = shell.t("juice.objective");
    shell.set_objective(&goal);
    let (speaker, text) = (shell.t("play.guide"), shell.t("juice.welcome"));
    shell.say(&speaker, &text, false);
}

/// A landed hit's bark (a subtitle only with subtitle_barks on, like any bark).
fn bark(shell: &mut Shell) {
    let (speaker, text) = (shell.t("juice.box"), shell.t("juice.ouch"));
    shell.say(&speaker, &text, true);
}

/// The demo's answer to one action while it is on top (screens::action calls it).
pub fn action(shell: &mut Shell, action: &str) -> bool {
    let rules = Rules::from_settings(&shell.settings);
    let Some(demo) = shell.juice.as_mut() else {
        return false;
    };
    match action {
        "pause" => {
            shell.push(ScreenName::Pause);
            true
        }
        "jump" => {
            demo.buffer.press("jump");
            true
        }
        "attack" => {
            if demo.hit(rules.flash_limit) {
                bark(shell);
            }
            true
        }
        "interact" if rules.hold_to_toggle => {
            demo.guard = !demo.guard;
            true
        }
        _ => false,
    }
}

/// One shell frame: the demo runs while it is on top (pause freezes it) and is dropped once it leaves the stack.
pub fn frame(shell: &mut Shell, dt: f64) {
    if shell.find(ScreenName::Juice).is_none() {
        shell.juice = None;
        return;
    }
    if shell.top_name() != Some(ScreenName::Juice) {
        return;
    }
    let held = Held {
        dir_x: f64::from((shell.held_dir() + shell.stick()).clamp_length_max(1.0).x),
        attack: shell.held.contains("attack"),
        interact: shell.held.contains("interact"),
    };
    let rules = Rules::from_settings(&shell.settings);
    let Some(mut demo) = shell.juice.take() else {
        return;
    };
    let before = (demo.stats(shell), demo.guard);
    let repeats = demo.update(dt, held, rules);
    let after = (demo.stats(shell), demo.guard);
    shell.juice = Some(demo);
    for _ in 0..repeats {
        bark(shell);
    }
    if before != after {
        shell.version += 1; // the HUD's numbers (or the guard line) changed: redraw it
    }
}

// ---- The stage: the demo's own camera and layer, and what it hides (runs headless too) ----------------------------
/// The render layer the demo's sprites, gizmos and camera share: the game's world (layer 0 unless it says otherwise)
/// never shows in the demo's picture, and the demo never shows in the game's cameras.
pub const JUICE_LAYER: usize = 30;

/// Tag anything of the game's that must not show while the juice demo is up: its HUD and other UI (the demo's camera
/// is the UI camera meanwhile), or anything the game put on JUICE_LAYER. The demo sets it Hidden and puts its own
/// Visibility back when it leaves. Requires Visibility, so a tagged entity always has one to hide.
#[derive(Component, Debug, Clone, Copy, Default)]
#[require(Visibility)]
pub struct HideUnderJuice;

/// The demo's 2D camera: spawned when the demo comes up (order above every camera of the game's, JUICE_LAYER only,
/// the default UI camera), despawned when it leaves.
#[derive(Component, Debug)]
pub struct JuiceCamera;

/// A game camera the demo switched off, with what to put back when it leaves.
#[derive(Component, Debug)]
struct JuiceStash {
    active: bool,
    default_ui: bool,
}

/// A tagged entity's Visibility before the demo hid it.
#[derive(Component, Debug)]
struct JuiceHidden(Visibility);

/// The demo's camera and hiding, without a renderer: JuiceViewPlugin adds it with a window, tests/shell.rs adds it to
/// a headless app to prove the demo comes and goes in a game that tags nothing.
pub struct JuiceStagePlugin;

impl Plugin for JuiceStagePlugin {
    fn build(&self, app: &mut App) {
        // PostUpdate, before the transforms propagate: nothing the game does to cameras in Update can move ours
        app.add_systems(
            PostUpdate,
            stage
                .before(TransformSystems::Propagate)
                .before(VisibilitySystems::VisibilityPropagate),
        );
    }
}

fn up(shell: &Shell) -> bool {
    shell.juice.is_some() && shell.find(ScreenName::Juice).is_some()
}

/// While the demo is up: its camera exists, every game camera is off (and gives up IsDefaultUiCamera), every
/// HideUnderJuice entity is Hidden (checked each frame, so one spawned or shown meanwhile hides too). When it leaves:
/// the camera goes and the game's cameras and entities get back exactly what they had.
#[allow(clippy::type_complexity)]
fn stage(
    mut commands: Commands,
    shell: Res<Shell>,
    juice_cams: Query<Entity, With<JuiceCamera>>,
    mut game_cams: Query<(Entity, &mut Camera, Has<IsDefaultUiCamera>, Option<&JuiceStash>), Without<JuiceCamera>>,
    mut marked: Query<
        (Entity, &mut Visibility, Has<HideUnderJuice>, Option<&JuiceHidden>),
        Or<(With<HideUnderJuice>, With<JuiceHidden>)>,
    >,
) {
    if up(&shell) {
        if juice_cams.is_empty() {
            let order = game_cams
                .iter()
                .map(|(_, cam, ..)| cam.order)
                .max()
                .map_or(0, |o| o + 1);
            commands.spawn((
                Camera2d,
                Camera { order, ..default() },
                RenderLayers::layer(JUICE_LAYER),
                IsDefaultUiCamera,
                JuiceCamera,
            ));
        }
        for (e, mut cam, default_ui, stash) in &mut game_cams {
            if stash.is_none() {
                commands.entity(e).insert(JuiceStash {
                    active: cam.is_active,
                    default_ui,
                });
            }
            if default_ui {
                commands.entity(e).remove::<IsDefaultUiCamera>(); // one default UI camera at a time: ours
            }
            if cam.is_active {
                cam.is_active = false;
            }
        }
        for (e, mut vis, tagged, saved) in &mut marked {
            if !tagged {
                continue;
            }
            if saved.is_none() {
                commands.entity(e).insert(JuiceHidden(*vis));
            }
            vis.set_if_neq(Visibility::Hidden);
        }
        return;
    }
    for e in &juice_cams {
        commands.entity(e).despawn();
    }
    for (e, mut cam, _, stash) in &mut game_cams {
        if let Some(stash) = stash {
            cam.is_active = stash.active;
            if stash.default_ui {
                commands.entity(e).insert(IsDefaultUiCamera);
            }
            commands.entity(e).remove::<JuiceStash>();
        }
    }
    for (e, mut vis, _, saved) in &mut marked {
        if let Some(saved) = saved {
            *vis = saved.0;
            commands.entity(e).remove::<JuiceHidden>();
        }
    }
}

// ---- The window side ------------------------------------------------------------------------------------------------
/// One sprite of the demo's world.
#[derive(Component, Debug, Clone, Copy, PartialEq)]
pub enum JuicePart {
    Background,
    Floor,
    Mark,
    Target,
    Player,
}

/// The full-screen flash (a UI node under the HUD, faded every frame).
#[derive(Component)]
pub struct JuiceFlash;

/// The demo's gizmos (the guard ring, the hit ring, the deadzone box), drawn on JUICE_LAYER only.
#[derive(Default, Reflect, GizmoConfigGroup)]
pub struct JuiceGizmos;

pub struct JuiceViewPlugin;

impl Plugin for JuiceViewPlugin {
    fn build(&self, app: &mut App) {
        app.add_plugins(JuiceStagePlugin)
            .insert_gizmo_config(
                JuiceGizmos,
                GizmoConfig {
                    render_layers: RenderLayers::layer(JUICE_LAYER),
                    ..default()
                },
            )
            .add_systems(Update, spawn_or_clear.after(view::rebuild_ui))
            .add_systems(PostUpdate, draw.after(stage).before(TransformSystems::Propagate));
    }
}

const MARK_EVERY: f64 = 80.0;
const MARK: Color = Color::srgb(0.32, 0.35, 0.45);
const DEADZONE: Color = Color::srgba(0.8, 0.82, 0.9, 0.6);

/// The demo's sprites exist while it is on the stack, on JUICE_LAYER (the stage gives them a camera).
fn spawn_or_clear(
    mut commands: Commands,
    shell: Res<Shell>,
    parts: Query<Entity, With<JuicePart>>,
    flashes: Query<Entity, With<JuiceFlash>>,
) {
    let want = up(&shell);
    let have = !parts.is_empty();
    if want == have {
        return;
    }
    if !want {
        for e in parts.iter().chain(flashes.iter()) {
            commands.entity(e).despawn();
        }
        return;
    }
    let mut part = |part: JuicePart, colour: Color, at: Transform| {
        commands.spawn((
            part,
            Sprite::from_color(colour, Vec2::ONE),
            at,
            RenderLayers::layer(JUICE_LAYER),
        ));
    };
    part(JuicePart::Background, view::BG, Transform::from_xyz(0.0, 0.0, -20.0));
    part(JuicePart::Floor, Color::BLACK, Transform::from_xyz(0.0, 0.0, -10.0));
    let mut gx = 0.0;
    while gx <= WORLD_W {
        part(
            JuicePart::Mark,
            MARK,
            Transform::from_xyz((gx + 1.0) as f32, -10.0, -9.0).with_scale(Vec3::new(2.0, 8.0, 1.0)),
        );
        gx += MARK_EVERY;
    }
    part(JuicePart::Target, Color::BLACK, Transform::from_xyz(0.0, 0.0, -5.0));
    part(JuicePart::Player, Color::BLACK, Transform::from_xyz(0.0, 0.0, -4.0));
    commands.spawn((
        Node {
            position_type: PositionType::Absolute,
            width: Val::Percent(100.0),
            height: Val::Percent(100.0),
            ..default()
        },
        BackgroundColor(Color::NONE),
        GlobalZIndex(-1),
        JuiceFlash,
    ));
}

/// Places the sprites, the demo's camera (follow plus shake) and the gizmo outlines, and fades the flash.
/// The game's own cameras are never moved.
fn draw(
    shell: Res<Shell>,
    mut parts: Query<(&JuicePart, &mut Transform, &mut Sprite), Without<JuiceCamera>>,
    mut cameras: Query<&mut Transform, With<JuiceCamera>>,
    mut flashes: Query<&mut BackgroundColor, With<JuiceFlash>>,
    mut gizmos: Gizmos<JuiceGizmos>,
) {
    let Some(demo) = shell.juice.as_ref().filter(|_| up(&shell)) else {
        return;
    };
    let pal = shell.palette();
    let colour = |name: &str, fallback: Color| pal.get(name).copied().unwrap_or(fallback);
    let (floor, target, player, hit) = (
        colour("floor", Color::srgb(0.25, 0.27, 0.32)),
        colour("target", Color::srgb(0.35, 0.8, 0.45)),
        colour("player", Color::srgb(0.95, 0.75, 0.3)),
        colour("hit", Color::srgb(1.0, 0.3, 0.25)),
    );
    let (sx, sy) = spring::squash(demo.spring.x);
    let (tw, th) = ((TARGET * sx) as f32, (TARGET * sy) as f32);
    let (px, py) = (demo.pos.0 as f32, demo.pos.1 as f32);
    let p = PLAYER as f32;
    for (part, mut t, mut s) in &mut parts {
        match part {
            JuicePart::Background => {
                t.translation = Vec3::new(demo.cam.x as f32, demo.cam.y as f32, -20.0);
                t.scale = Vec3::new(8000.0, 8000.0, 1.0);
            }
            JuicePart::Floor => {
                s.color = floor;
                t.translation = Vec3::new((WORLD_W / 2.0) as f32, -100.0, -10.0);
                t.scale = Vec3::new((WORLD_W + 400.0) as f32, 200.0, 1.0);
            }
            JuicePart::Mark => {}
            JuicePart::Target => {
                s.color = target;
                t.translation = Vec3::new((TARGET_X + TARGET / 2.0) as f32, th / 2.0, -5.0);
                t.scale = Vec3::new(tw, th, 1.0);
            }
            JuicePart::Player => {
                s.color = player;
                t.translation = Vec3::new(px + p / 2.0, py + p / 2.0, -4.0);
                t.scale = Vec3::new(p, p, 1.0);
            }
        }
    }
    let (ox, oy, angle) = demo.offset;
    for mut cam in &mut cameras {
        cam.translation = Vec3::new((demo.cam.x + ox) as f32, (demo.cam.y + oy) as f32, cam.translation.z);
        cam.rotation = Quat::from_rotation_z(angle as f32);
    }
    let centre = Vec2::new(px + p / 2.0, py + p / 2.0);
    if demo.guard {
        gizmos.circle_2d(Isometry2d::from_translation(centre), p, player);
    }
    if demo.pop > 0.0 {
        let k = ease::ease("out_back", 1.0 - demo.pop / POP_S).unwrap_or(1.0) as f32;
        let at = Vec2::new((TARGET_X + TARGET / 2.0) as f32, (TARGET / 2.0) as f32);
        gizmos.circle_2d(Isometry2d::from_translation(at), 10.0 + 30.0 * k, hit);
    }
    gizmos.rect_2d(
        Isometry2d::from_translation(Vec2::new(demo.cam.x as f32, demo.cam.y as f32)),
        Vec2::new(demo.cam.deadzone_w as f32, demo.cam.deadzone_h as f32),
        DEADZONE,
    );
    let alpha = if FLASH_S > 0.0 {
        (demo.flash_peak * demo.flash / FLASH_S) as f32
    } else {
        0.0
    };
    for mut bg in &mut flashes {
        bg.0 = hit.with_alpha(alpha);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const RULES: Rules = Rules {
        game_speed: 1.0,
        timing_scale: 1.0,
        auto_repeat: false,
        hold_to_toggle: false,
        flash_limit: true,
        shake: 1.0,
    };

    #[test]
    fn a_hit_in_range_shakes_freezes_squashes_and_flashes() {
        let mut demo = Demo::new();
        assert!(demo.in_range(), "the player starts next to the box");
        assert!(demo.hit(true));
        assert_eq!(demo.hits, 1);
        assert!(demo.shake.trauma > 0.5 && demo.hitstop.remaining > 0.0 && demo.spring.x > 0.0);
        assert_eq!(demo.flash_peak, FLASH_GENTLE, "flash_limit tones the flash down");
        let x = demo.pos.0;
        demo.update(
            1.0 / 60.0,
            Held {
                dir_x: 1.0,
                ..Held::default()
            },
            RULES,
        );
        assert_eq!(demo.pos.0, x, "the hitstop freezes the demo's time");
        assert!(demo.flash < FLASH_S, "the flash fades on real time");
    }

    #[test]
    fn the_limiter_holds_back_the_fourth_flash_in_a_second() {
        let mut demo = Demo::new();
        for _ in 0..4 {
            demo.hit(false);
        }
        assert_eq!((demo.hits, demo.refused), (4, 1));
    }

    #[test]
    fn a_buffered_jump_leaves_the_floor_and_lands() {
        let mut demo = Demo::new();
        demo.buffer.press("jump");
        demo.update(1.0 / 60.0, Held::default(), RULES);
        assert!(demo.vel.1 > 0.0, "the jump went off");
        for _ in 0..120 {
            demo.update(1.0 / 60.0, Held::default(), RULES);
        }
        assert_eq!(demo.pos.1, 0.0, "back on the floor");
    }

    #[test]
    fn far_from_the_box_an_attack_misses() {
        let mut demo = Demo::new();
        for _ in 0..120 {
            demo.update(
                1.0 / 60.0,
                Held {
                    dir_x: -1.0,
                    ..Held::default()
                },
                RULES,
            );
        }
        assert!(!demo.hit(false));
        assert_eq!(demo.hits, 0);
        assert!(demo.cam.x < START_X, "the camera followed the player left");
    }
}

// {{FOOTER}}
