// ---------------------------------------------------------------------------
// shell/view.rs
// Purpose : The shell's window side: draws the screen on top with bevy_ui (panels, rows, focus marks, the tab bar,
//           subtitles, toasts), turns keys and pad buttons into the shell's actions through the player's bindings,
//           finishes "press a key" rebinds, and measures every text for the accessibility sweep (ACCESS_SCREEN).
// Usage   : app.add_plugins(ShellViewPlugin) (app.rs adds it with a window; headless runs never load this)
// Notes   : The tree is rebuilt from scratch whenever Shell.version moves (a press, a timer, a new screen): a few
//           dozen nodes, so a rebuild is cheap and nothing can go stale. Text sizes are the kit's (SOP-20: body text
//           at least 18 px at 1080p) times access.text_scale; access.readable_font swaps in Atkinson Hyperlegible
//           (src/shell/fonts/, OFL, compiled into the exe) and access.line_spacing sets the line height. The focused row gets a lighter fill,
//           a white border and a ">" marker, never colour alone. Text over the game (the HUD hint, subtitles) sits on
//           a panel, so its contrast does not depend on what is behind it. Pad prompts follow the last device used.
//
// Pseudocode:
//   PreUpdate poll_input: every known key and pad button -> just pressed: finish a capture or queue its actions;
//   held: the actions bound to it -> Shell.held
//   Update rebuild_ui (version moved): despawn the root -> spawn the top screen's nodes, each text tagged UiLabel
//   Last report_access (a report was asked for two frames ago): every UiLabel's size, position, colours and
//   whether it fits -> AccessReport.result
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
use std::collections::BTreeSet;

use bevy::input::InputSystems;
use bevy::input::gamepad::Gamepad;
use bevy::prelude::*;
use bevy::text::{LineHeight, TextLayoutInfo};
use bevy::ui::UiGlobalTransform;
use bevy::window::PrimaryWindow;
use serde_json::{Value, json};

use super::screens::{self, PAGE_LINES, RowKind, TABS};
use super::{ScreenName, Shell, input};

// ---- Tunables ------------------------------------------------------------------
pub const TITLE_PX: f32 = 44.0;
pub const HEADING_PX: f32 = 32.0;
pub const BODY_PX: f32 = 22.0;
/// The smallest text: 18 px at 1080p (SOP-20, F36).
pub const SMALL_PX: f32 = 18.0;
pub const SUBTITLE_PX: [(&str, f32); 4] = [("small", 18.0), ("medium", 22.0), ("large", 28.0), ("xl", 36.0)];
pub const LIST_MAX_W: f32 = 1100.0;
pub const PANEL_PAD: f32 = 16.0;
pub const ROW_PAD: f32 = 7.0;
/// Atkinson Hyperlegible (OFL, src/shell/fonts/OFL.txt), compiled in so a shipped exe needs no font file.
pub const READABLE_FONT: &[u8] = include_bytes!("fonts/AtkinsonHyperlegible-Regular.ttf");
pub const READABLE_BOLD: &[u8] = include_bytes!("fonts/AtkinsonHyperlegible-Bold.ttf");
/// Frames between an access report request and the measurement (one to rebuild, one to lay out).
const REPORT_DELAY: u32 = 2;
/// Stick deflection that counts as a direction.
const STICK_DEADZONE_MIN: f32 = 0.2;

// Colours (contrast on PANEL: TEXT 13:1, DIM 7:1, ACCENT 9:1; all above 4.5:1, E158)
pub const BG: Color = Color::srgb(0.078, 0.086, 0.118);
pub const PANEL: Color = Color::srgb(0.137, 0.153, 0.212);
pub const ROW: Color = Color::srgb(0.165, 0.180, 0.247);
pub const ROW_FOCUS: Color = Color::srgb(0.227, 0.255, 0.376);
pub const TEXT: Color = Color::srgb(0.941, 0.941, 0.961);
pub const DIM: Color = Color::srgb(0.722, 0.737, 0.784);
pub const ACCENT: Color = Color::srgb(1.0, 0.8, 0.333);
pub const WARN: Color = Color::srgb(1.0, 0.478, 0.361);
pub const FOCUS: Color = Color::WHITE;
pub const OVERLAY: Color = Color::srgba(0.0, 0.0, 0.0, 0.6);
pub const SUBTITLE_BG: Color = Color::BLACK;

/// The fonts: Bevy's built-in one by default, Atkinson Hyperlegible when access.readable_font is on.
#[derive(Resource, Default)]
pub struct Fonts {
    pub readable: Handle<Font>,
    pub readable_bold: Handle<Font>,
}

/// The root of the shell's UI tree; despawned and rebuilt when the shell changes.
#[derive(Component)]
pub struct UiRoot;

/// A scrolling list: labels outside it are hidden, so the sweep skips them.
#[derive(Component)]
pub struct ScrollList;

/// What the access report needs to know about one text.
#[derive(Component, Clone)]
pub struct UiLabel {
    pub id: String,
    pub px: f32,
    pub bg: Option<Color>,
    /// Panels over the game between the text and the world: (colour, alpha), top first.
    pub over_game: Vec<(Color, f32)>,
    pub state: String,
    pub clip: Option<Entity>,
}

/// The accessibility sweep's measurement of one drawn frame (ACCESS_SCREEN).
#[derive(Resource, Default)]
pub struct AccessReport {
    pending: Option<(String, bool, u32)>,
    pub result: Option<Value>,
}

impl AccessReport {
    pub fn request(&mut self, screen: &str, world: bool) {
        self.pending = Some((screen.to_string(), world, 0));
        self.result = None;
    }
}

pub struct ShellViewPlugin;

impl Plugin for ShellViewPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Fonts>()
            .init_resource::<AccessReport>()
            .add_systems(Startup, load_fonts)
            .add_systems(PreUpdate, poll_input.after(InputSystems))
            .add_systems(Update, rebuild_ui.after(super::sync_settings))
            .add_systems(Last, report_access);
    }
}

fn load_fonts(mut fonts: ResMut<Fonts>, mut assets: ResMut<Assets<Font>>) {
    fonts.readable = assets.add(Font::from_bytes(READABLE_FONT.to_vec()));
    fonts.readable_bold = assets.add(Font::from_bytes(READABLE_BOLD.to_vec()));
}

// ---- Input -------------------------------------------------------------------------------------------------
fn device_name(pad: &Gamepad) -> &'static str {
    match pad.vendor_id() {
        Some(0x045e) => "pad_xbox",
        Some(0x054c) => "pad_playstation",
        _ => "pad_generic",
    }
}

/// Keys and pad buttons -> the shell: presses as action groups (or a capture), held keys as held actions.
fn poll_input(keys: Res<ButtonInput<KeyCode>>, pads: Query<&Gamepad>, mut shell: ResMut<Shell>) {
    let bindings = shell.bindings();
    let mut held = BTreeSet::new();
    let deadzone = (shell.num("input", "deadzone") as f32).max(STICK_DEADZONE_MIN);
    let capture_slot = shell.capturing.as_ref().map(|(_, slot)| *slot);
    for (name, key) in input::all_keys() {
        let binding = format!("key:{name}");
        if keys.just_pressed(key) {
            shell.last_device = "keyboard".into();
            match capture_slot {
                Some(0) => shell.capture(&binding),
                Some(_) if key == KeyCode::Escape => shell.capture(""),
                Some(_) => {}
                None => shell.press_binding(&binding),
            }
        }
        if keys.pressed(key) {
            held.extend(input::actions_for(&bindings, &binding));
        }
    }
    for pad in &pads {
        for (name, button) in input::all_pad_buttons() {
            let binding = format!("pad:{name}");
            if pad.just_pressed(button) {
                shell.last_device = device_name(pad).into();
                match capture_slot {
                    Some(1) => shell.capture(&binding),
                    Some(_) => {}
                    None => shell.press_binding(&binding),
                }
            }
            if pad.pressed(button) {
                held.extend(input::actions_for(&bindings, &binding));
            }
        }
        // the left stick moves like the d-pad
        let x = pad.get(GamepadAxis::LeftStickX).unwrap_or(0.0);
        let y = pad.get(GamepadAxis::LeftStickY).unwrap_or(0.0);
        if x < -deadzone {
            held.insert("move_left".into());
        }
        if x > deadzone {
            held.insert("move_right".into());
        }
        if y > deadzone {
            held.insert("move_up".into());
        }
        if y < -deadzone {
            held.insert("move_down".into());
        }
    }
    shell.held = held;
}

// ---- Drawing -----------------------------------------------------------------------------------------------
/// The text style for this frame: sizes, the font and the line height follow the settings.
struct Style {
    scale: f32,
    readable: bool,
    line_spacing: f32,
    regular: Handle<Font>,
    bold: Handle<Font>,
}

impl Style {
    fn from(shell: &Shell, fonts: &Fonts) -> Style {
        Style {
            scale: shell.num("access", "text_scale") as f32,
            readable: shell.flag("access", "readable_font"),
            line_spacing: shell.num("access", "line_spacing") as f32,
            regular: fonts.readable.clone(),
            bold: fonts.readable_bold.clone(),
        }
    }

    fn font(&self, px: f32, bold: bool) -> (TextFont, LineHeight) {
        let mut font = TextFont::from_font_size(px * self.scale);
        if self.readable {
            font.font = if bold { self.bold.clone() } else { self.regular.clone() }.into();
        } else if bold {
            font.weight = bevy::text::FontWeight::BOLD;
        }
        (font, LineHeight::RelativeToFont(1.2 * self.line_spacing))
    }

    fn row_h(&self) -> f32 {
        BODY_PX * self.scale * 1.2 * self.line_spacing + ROW_PAD * 2.0
    }
}

/// Spawns one text, tagged for the access report.
fn label(
    parent: &mut ChildSpawnerCommands,
    style: &Style,
    id: &str,
    text: &str,
    px: f32,
    color: Color,
    bold: bool,
    bg: Option<Color>,
    over_game: &[(Color, f32)],
    clip: Option<Entity>,
) -> Entity {
    let (font, line_height) = style.font(px, bold);
    parent
        .spawn((
            Text::new(text),
            font,
            line_height,
            TextColor(color),
            UiLabel {
                id: id.to_string(),
                px: px * style.scale,
                bg,
                over_game: over_game.to_vec(),
                state: String::new(),
                clip,
            },
        ))
        .id()
}

fn panel(width: Val, bg: Color) -> impl Bundle {
    (
        Node {
            width,
            flex_direction: FlexDirection::Column,
            padding: UiRect::all(Val::Px(PANEL_PAD)),
            row_gap: Val::Px(6.0),
            border_radius: BorderRadius::all(Val::Px(8.0)),
            ..default()
        },
        BackgroundColor(bg),
    )
}

fn full_screen(bg: Color) -> impl Bundle {
    (
        Node {
            position_type: PositionType::Absolute,
            width: Val::Percent(100.0),
            height: Val::Percent(100.0),
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            justify_content: JustifyContent::Center,
            row_gap: Val::Px(14.0),
            ..default()
        },
        BackgroundColor(bg),
        UiRoot,
    )
}

/// One menu row: the marker and label on the left, the value (bar, text or binding cells) on the right.
fn spawn_row(
    parent: &mut ChildSpawnerCommands,
    style: &Style,
    shell: &Shell,
    row: &screens::Row,
    prefix: &str,
    focused: bool,
    cell: usize,
    clip: Option<Entity>,
) {
    let bg = if focused { ROW_FOCUS } else { ROW };
    let id = format!("{prefix}{}", row.id);
    parent
        .spawn((
            Node {
                width: Val::Percent(100.0),
                min_height: Val::Px(style.row_h()),
                flex_direction: FlexDirection::Row,
                align_items: AlignItems::Center,
                padding: UiRect::axes(Val::Px(12.0), Val::Px(ROW_PAD)),
                column_gap: Val::Px(12.0),
                border: UiRect::all(Val::Px(if focused { 2.0 } else { 0.0 })),
                border_radius: BorderRadius::all(Val::Px(6.0)),
                ..default()
            },
            BackgroundColor(bg),
            BorderColor::all(if focused { FOCUS } else { Color::NONE }),
        ))
        .with_children(|r| {
            let marker = if focused { "> " } else { "  " };
            let text = format!("{marker}{}", row.label);
            r.spawn((Node {
                flex_grow: 1.0,
                ..default()
            },))
                .with_children(|l| {
                    label(l, style, &id, &text, BODY_PX, TEXT, false, Some(bg), &[], clip);
                });
            match row.kind {
                RowKind::Button => {}
                RowKind::Slider => {
                    let fraction = row.fraction.unwrap_or(0.0).clamp(0.0, 1.0);
                    r.spawn((
                        Node {
                            width: Val::Px(160.0 * style.scale.min(1.5)),
                            height: Val::Px(10.0),
                            border_radius: BorderRadius::all(Val::Px(5.0)),
                            ..default()
                        },
                        BackgroundColor(PANEL),
                    ))
                    .with_children(|bar| {
                        bar.spawn((
                            Node {
                                width: Val::Percent(fraction * 100.0),
                                height: Val::Percent(100.0),
                                border_radius: BorderRadius::all(Val::Px(5.0)),
                                ..default()
                            },
                            BackgroundColor(ACCENT),
                        ));
                    });
                    label(
                        r,
                        style,
                        &format!("{id}.value"),
                        &row.value,
                        BODY_PX,
                        TEXT,
                        false,
                        Some(bg),
                        &[],
                        clip,
                    );
                }
                RowKind::Toggle | RowKind::Choice => {
                    let text = format!("< {} >", row.value);
                    label(
                        r,
                        style,
                        &format!("{id}.value"),
                        &text,
                        BODY_PX,
                        TEXT,
                        false,
                        Some(bg),
                        &[],
                        clip,
                    );
                }
                RowKind::Binding => {
                    for slot in 0..2 {
                        let (_, cell_label) = &row.cells[slot];
                        let picked = focused && cell == slot;
                        let clash = row.conflict[slot];
                        r.spawn((
                            Node {
                                padding: UiRect::axes(Val::Px(8.0), Val::Px(2.0)),
                                border: UiRect::all(Val::Px(1.0)),
                                border_radius: BorderRadius::all(Val::Px(4.0)),
                                column_gap: Val::Px(6.0),
                                align_items: AlignItems::Center,
                                ..default()
                            },
                            BorderColor::all(if picked { FOCUS } else { Color::NONE }),
                        ))
                        .with_children(|c| {
                            let colour = if clash { WARN } else { TEXT };
                            label(
                                c,
                                style,
                                &format!("{id}.slot{slot}"),
                                cell_label,
                                BODY_PX,
                                colour,
                                false,
                                Some(bg),
                                &[],
                                clip,
                            );
                            if clash {
                                let t = shell.t("controls.conflict");
                                label(
                                    c,
                                    style,
                                    &format!("{id}.slot{slot}.conflict"),
                                    &t,
                                    SMALL_PX,
                                    WARN,
                                    false,
                                    Some(bg),
                                    &[],
                                    clip,
                                );
                            }
                        });
                    }
                }
            }
        });
}

/// A list of rows in a scrolling panel; the focused row stays in view.
fn spawn_list(
    parent: &mut ChildSpawnerCommands,
    style: &Style,
    shell: &Shell,
    rows: &[screens::Row],
    prefix: &str,
    focus: Option<usize>,
    cell: usize,
    max_h: f32,
    width: f32,
) {
    let row_h = style.row_h() + 4.0;
    let visible = ((max_h - PANEL_PAD * 2.0) / row_h).floor().max(1.0) as usize;
    let scroll = match focus {
        Some(f) if f >= visible => (f + 1 - visible) as f32 * row_h,
        _ => 0.0,
    };
    let mut list = parent.spawn((
        Node {
            width: Val::Px(width),
            max_height: Val::Px(max_h),
            flex_direction: FlexDirection::Column,
            padding: UiRect::all(Val::Px(PANEL_PAD)),
            row_gap: Val::Px(4.0),
            overflow: Overflow::scroll_y(),
            border_radius: BorderRadius::all(Val::Px(8.0)),
            ..default()
        },
        BackgroundColor(PANEL),
        ScrollPosition(Vec2::new(0.0, scroll)),
        ScrollList,
    ));
    let clip = Some(list.id());
    list.with_children(|l| {
        for (i, row) in rows.iter().enumerate() {
            spawn_row(l, style, shell, row, prefix, focus == Some(i), cell, clip);
        }
    });
}

fn heading(parent: &mut ChildSpawnerCommands, style: &Style, id: &str, text: &str, px: f32) {
    label(parent, style, id, text, px, ACCENT, true, Some(BG), &[], None);
}

/// A line pinned to the bottom of the screen (hints).
fn bottom_hint(parent: &mut ChildSpawnerCommands, style: &Style, id: &str, text: &str, colour: Color) {
    parent
        .spawn((
            Node {
                position_type: PositionType::Absolute,
                bottom: Val::Px(12.0),
                left: Val::Px(16.0),
                right: Val::Px(16.0),
                justify_content: JustifyContent::Center,
                ..default()
            },
            BackgroundColor(BG),
        ))
        .with_children(|h| {
            label(h, style, id, text, SMALL_PX, colour, false, Some(BG), &[], None);
        });
}

/// A text page: a heading, the visible lines, a hint.
fn spawn_page(
    parent: &mut ChildSpawnerCommands,
    style: &Style,
    shell: &Shell,
    title: &str,
    lines: &[String],
    prefix: &str,
    win: Vec2,
) {
    let scroll = shell
        .top()
        .map_or(0, |t| t.scroll)
        .min(lines.len().saturating_sub(PAGE_LINES));
    heading(parent, style, &format!("{prefix}.title"), title, HEADING_PX);
    let width = (win.x - 40.0).min(LIST_MAX_W);
    parent.spawn(panel(Val::Px(width), PANEL)).with_children(|p| {
        for (i, line) in lines.iter().enumerate().skip(scroll).take(PAGE_LINES) {
            let text = if line.is_empty() { " " } else { line.as_str() };
            p.spawn((Node {
                width: Val::Percent(100.0),
                ..default()
            },))
                .with_children(|l| {
                    label(
                        l,
                        style,
                        &format!("{prefix}.line{i}"),
                        text,
                        BODY_PX,
                        TEXT,
                        false,
                        Some(PANEL),
                        &[],
                        None,
                    );
                });
        }
    });
    let hint_key = if prefix == "credits" {
        "credits.hint"
    } else {
        "page.hint"
    };
    bottom_hint(parent, style, &format!("{prefix}.hint"), &shell.t(hint_key), DIM);
}

fn spawn_title(parent: &mut ChildSpawnerCommands, style: &Style, shell: &Shell, win: Vec2) {
    if shell.top().is_some_and(|t| t.consent) {
        // the consent question is the whole screen (the name and version wait), so it fits 200 % text at 1280x800
        let rows = shell.rows();
        let focus = shell.top().map_or(0, |t| t.focus);
        parent
            .spawn(panel(Val::Px((win.x - 80.0).min(760.0)), PANEL))
            .with_children(|p| {
                label(
                    p,
                    style,
                    "consent.title",
                    &shell.t("consent.title"),
                    HEADING_PX,
                    ACCENT,
                    true,
                    Some(PANEL),
                    &[],
                    None,
                );
                label(
                    p,
                    style,
                    "consent.body",
                    &shell.t("consent.body"),
                    SMALL_PX,
                    TEXT,
                    false,
                    Some(PANEL),
                    &[],
                    None,
                );
                for (i, row) in rows.iter().enumerate() {
                    spawn_row(p, style, shell, row, "", focus == i, 0, None);
                }
            });
        return;
    }
    let name = shell.t_args("title.name", &[("name", crate::game::TITLE)]);
    heading(parent, style, "title.name", &name, TITLE_PX);
    if shell.blink_on {
        label(
            parent,
            style,
            "title.press_any",
            &shell.t("title.press_any"),
            BODY_PX,
            TEXT,
            false,
            Some(BG),
            &[],
            None,
        );
    }
    let version = shell.t_args("title.version", &[("version", env!("CARGO_PKG_VERSION"))]);
    bottom_hint(parent, style, "title.version", &version, DIM);
}

fn spawn_settings(parent: &mut ChildSpawnerCommands, style: &Style, shell: &Shell, win: Vec2) {
    let Some(top) = shell.top().cloned() else {
        return;
    };
    heading(parent, style, "settings.title", &shell.t("settings.title"), HEADING_PX);
    // the tab bar: the open tab is tinted and underlined, the focused tab gets the white border too
    parent
        .spawn(Node {
            flex_direction: FlexDirection::Row,
            flex_wrap: FlexWrap::Wrap,
            justify_content: JustifyContent::Center,
            column_gap: Val::Px(6.0),
            row_gap: Val::Px(6.0),
            max_width: Val::Px(win.x - 40.0),
            ..default()
        })
        .with_children(|bar| {
            for (i, tab) in TABS.iter().enumerate() {
                let selected = i == top.tab;
                let focused = selected && top.on_tabs;
                let bg = if selected { ROW_FOCUS } else { ROW };
                bar.spawn((
                    Node {
                        padding: UiRect::axes(Val::Px(14.0), Val::Px(6.0)),
                        border: UiRect::all(Val::Px(2.0)).with_bottom(Val::Px(if selected { 4.0 } else { 2.0 })),
                        border_radius: BorderRadius::all(Val::Px(6.0)),
                        ..default()
                    },
                    BackgroundColor(bg),
                    BorderColor {
                        bottom: if selected { ACCENT } else { Color::NONE },
                        ..BorderColor::all(if focused { FOCUS } else { Color::NONE })
                    },
                ))
                .with_children(|t| {
                    let text = shell.t(&format!("settings.tab.{tab}"));
                    label(
                        t,
                        style,
                        &format!("settings.tab.{tab}"),
                        &text,
                        SMALL_PX,
                        if selected { TEXT } else { DIM },
                        false,
                        Some(bg),
                        &[],
                        None,
                    );
                });
            }
        });
    let rows = shell.rows();
    let prefix = format!("settings.{}.", TABS[top.tab.min(TABS.len() - 1)]);
    let used = TITLE_PX * style.scale * 1.5 + SMALL_PX * style.scale * 2.0 + 90.0;
    let max_h = (win.y - used).max(style.row_h() * 2.0);
    let focus = if top.on_tabs { None } else { Some(top.focus) };
    spawn_list(
        parent,
        style,
        shell,
        &rows,
        &prefix,
        focus,
        top.cell,
        max_h,
        (win.x - 40.0).min(LIST_MAX_W),
    );
    let (hint, colour) = match &shell.message {
        Some((m, _)) => (m.clone(), ACCENT),
        None => (shell.t("settings.hint"), DIM),
    };
    bottom_hint(parent, style, "settings.hint", &hint, colour);
    if let Some((action, slot)) = &shell.capturing {
        let key = if *slot == 0 {
            "controls.press_key"
        } else {
            "controls.press_button"
        };
        let action_label = shell.t(&format!("action.{action}"));
        parent.spawn(full_screen(OVERLAY)).with_children(|o| {
            o.spawn(panel(Val::Px(520.0_f32.min(win.x - 40.0)), PANEL))
                .with_children(|p| {
                    label(
                        p,
                        style,
                        "settings.capture",
                        &shell.t_args(key, &[("action", &action_label)]),
                        BODY_PX,
                        TEXT,
                        false,
                        Some(PANEL),
                        &[],
                        None,
                    );
                    label(
                        p,
                        style,
                        "settings.capture.hint",
                        &shell.t("controls.capture_cancel"),
                        SMALL_PX,
                        DIM,
                        false,
                        Some(PANEL),
                        &[],
                        None,
                    );
                });
        });
    }
}

fn spawn_menu(
    parent: &mut ChildSpawnerCommands,
    style: &Style,
    shell: &Shell,
    title: &str,
    title_id: &str,
    prefix: &str,
    win: Vec2,
) {
    heading(parent, style, title_id, title, HEADING_PX);
    let rows = shell.rows();
    let focus = shell.top().map_or(0, |t| t.focus);
    let widest = rows.iter().map(|r| r.label.chars().count()).max().unwrap_or(10) as f32;
    let width = (widest * BODY_PX * style.scale * 0.62 + 120.0).clamp(320.0, win.x - 40.0);
    spawn_list(
        parent,
        style,
        shell,
        &rows,
        prefix,
        Some(focus),
        0,
        win.y - 160.0,
        width,
    );
}

fn spawn_play_hud(parent: &mut ChildSpawnerCommands, style: &Style, shell: &Shell) {
    let (_, pause_label) = shell.prompt("pause");
    let text = format!("{pause_label}: {}", shell.t("hint.pause"));
    parent
        .spawn((
            Node {
                position_type: PositionType::Absolute,
                top: Val::Px(12.0),
                left: Val::Px(12.0),
                padding: UiRect::axes(Val::Px(10.0), Val::Px(4.0)),
                border_radius: BorderRadius::all(Val::Px(6.0)),
                ..default()
            },
            BackgroundColor(PANEL),
        ))
        .with_children(|h| {
            label(
                h,
                style,
                "hud.pause_hint",
                &text,
                SMALL_PX,
                TEXT,
                false,
                Some(PANEL),
                &[],
                None,
            );
        });
}

fn spawn_subtitle(parent: &mut ChildSpawnerCommands, style: &Style, shell: &Shell, win: Vec2) {
    let Some(sub) = &shell.subtitle else {
        return;
    };
    let size = shell.text("access", "subtitle_size");
    let px = SUBTITLE_PX
        .iter()
        .find(|(n, _)| *n == size)
        .map_or(BODY_PX, |(_, p)| *p);
    let alpha = shell.num("access", "subtitle_background") as f32;
    let bg = SUBTITLE_BG.with_alpha(alpha);
    let over = [(SUBTITLE_BG, alpha)];
    parent
        .spawn((
            Node {
                position_type: PositionType::Absolute,
                bottom: Val::Px(40.0),
                max_width: Val::Px(win.x - 80.0),
                padding: UiRect::axes(Val::Px(16.0), Val::Px(8.0)),
                flex_direction: FlexDirection::Row,
                flex_wrap: FlexWrap::Wrap,
                column_gap: Val::Px(8.0),
                border_radius: BorderRadius::all(Val::Px(6.0)),
                ..default()
            },
            BackgroundColor(bg),
        ))
        .with_children(|s| {
            if shell.flag("access", "speaker_names") && !sub.speaker.is_empty() {
                // bold, not a colour: the accent falls under 4.5:1 over the translucent panel on a bright game
                let name = shell.t_args("subtitle.speaker", &[("name", &sub.speaker)]);
                label(s, style, "subtitle.speaker", &name, px, TEXT, true, None, &over, None);
            }
            let text = if sub.holding {
                format!("{} \u{25BC}", sub.text)
            } else {
                sub.text.clone()
            };
            label(s, style, "subtitle.text", &text, px, TEXT, false, None, &over, None);
        });
}

fn spawn_toasts(parent: &mut ChildSpawnerCommands, style: &Style, shell: &Shell) {
    for (i, (text, _)) in shell.toasts.iter().enumerate() {
        parent
            .spawn((
                Node {
                    position_type: PositionType::Absolute,
                    top: Val::Px(12.0 + i as f32 * (style.row_h() + 6.0)),
                    padding: UiRect::axes(Val::Px(14.0), Val::Px(6.0)),
                    border_radius: BorderRadius::all(Val::Px(6.0)),
                    ..default()
                },
                BackgroundColor(PANEL),
            ))
            .with_children(|t| {
                label(
                    t,
                    style,
                    &format!("toast.{i}"),
                    text,
                    BODY_PX,
                    TEXT,
                    false,
                    Some(PANEL),
                    &[],
                    None,
                );
            });
    }
}

/// Rebuilds the UI tree when the shell changed.
fn rebuild_ui(
    mut last: Local<Option<u64>>,
    mut commands: Commands,
    shell: Res<Shell>,
    fonts: Res<Fonts>,
    windows: Query<&Window, With<PrimaryWindow>>,
    roots: Query<Entity, With<UiRoot>>,
) {
    let win = windows
        .single()
        .map(|w| Vec2::new(w.resolution.width(), w.resolution.height()))
        .unwrap_or(Vec2::new(1280.0, 720.0));
    let key = shell.version ^ ((win.x as u64) << 40) ^ ((win.y as u64) << 52);
    if *last == Some(key) {
        return;
    }
    *last = Some(key);
    for root in &roots {
        commands.entity(root).despawn();
    }
    let style = Style::from(&shell, &fonts);
    let Some(top) = shell.top() else {
        return;
    };
    let bg = if top.name.transparent() {
        OVERLAY
    } else if top.name == ScreenName::Play {
        Color::NONE
    } else {
        BG
    };
    commands.spawn(full_screen(bg)).with_children(|root| match top.name {
        ScreenName::Boot => {}
        ScreenName::Loading => {
            label(
                root,
                &style,
                "loading.title",
                &shell.t("loading.title"),
                HEADING_PX,
                DIM,
                false,
                Some(BG),
                &[],
                None,
            );
        }
        ScreenName::Title => spawn_title(root, &style, &shell, win),
        ScreenName::MainMenu => {
            let name = shell.t_args("title.name", &[("name", crate::game::TITLE)]);
            spawn_menu(root, &style, &shell, &name, "menu.title", "", win);
            let hint = format!("{}: {}", shell.prompt("ui_accept").1, shell.t("hint.select"));
            bottom_hint(root, &style, "menu.hint", &hint, DIM);
        }
        ScreenName::Settings => spawn_settings(root, &style, &shell, win),
        ScreenName::Credits => spawn_page(
            root,
            &style,
            &shell,
            &shell.t("credits.title"),
            &screens::lines_for(&shell),
            "credits",
            win,
        ),
        ScreenName::Help => spawn_page(
            root,
            &style,
            &shell,
            &shell.t("help.title"),
            &screens::lines_for(&shell),
            "help",
            win,
        ),
        ScreenName::History => spawn_page(
            root,
            &style,
            &shell,
            &shell.t("history.title"),
            &screens::lines_for(&shell),
            "history",
            win,
        ),
        ScreenName::Pause => spawn_menu(root, &style, &shell, &shell.t("pause.title"), "pause.title", "", win),
        ScreenName::Play => {
            spawn_play_hud(root, &style, &shell);
            spawn_subtitle(root, &style, &shell, win);
        }
    });
    if !shell.toasts.is_empty() {
        commands
            .spawn(full_screen(Color::NONE))
            .with_children(|root| spawn_toasts(root, &style, &shell));
    }
}

// ---- The access report -------------------------------------------------------------------------------------
fn hex(c: Color) -> String {
    let s = c.to_srgba();
    format!(
        "#{:02x}{:02x}{:02x}",
        (s.red * 255.0).round() as u8,
        (s.green * 255.0).round() as u8,
        (s.blue * 255.0).round() as u8
    )
}

/// A node's rectangle in logical pixels: [x, y, w, h].
fn rect_of(node: &ComputedNode, transform: &UiGlobalTransform) -> [f32; 4] {
    let inv = node.inverse_scale_factor;
    let size = node.size() * inv;
    let centre = transform.affine().translation * inv;
    [centre.x - size.x / 2.0, centre.y - size.y / 2.0, size.x, size.y]
}

fn inside(inner: [f32; 4], outer: [f32; 4], slack: f32) -> bool {
    inner[0] >= outer[0] - slack
        && inner[1] >= outer[1] - slack
        && inner[0] + inner[2] <= outer[0] + outer[2] + slack
        && inner[1] + inner[3] <= outer[1] + outer[3] + slack
}

/// Two frames after a request: every label's size, place and colours, as the sweep reads them.
fn report_access(
    mut report: ResMut<AccessReport>,
    windows: Query<&Window, With<PrimaryWindow>>,
    labels: Query<(
        &UiLabel,
        &ComputedNode,
        &UiGlobalTransform,
        &TextLayoutInfo,
        &TextColor,
        &InheritedVisibility,
    )>,
    clips: Query<(&ComputedNode, &UiGlobalTransform), With<ScrollList>>,
) {
    let Some((screen, world, frames)) = report.pending.as_mut() else {
        return;
    };
    *frames += 1;
    if *frames < REPORT_DELAY {
        return;
    }
    let screen = screen.clone();
    let world = *world;
    report.pending = None;
    let (win_w, win_h) = windows
        .single()
        .map(|w| (w.resolution.width(), w.resolution.height()))
        .unwrap_or((1280.0, 720.0));
    let window = [0.0, 0.0, win_w, win_h];
    let mut texts = Vec::new();
    for (meta, node, transform, layout, colour, visible) in &labels {
        if !visible.get() {
            continue;
        }
        let rect = rect_of(node, transform);
        let sf = layout.scale_factor.max(0.001);
        let block = layout.size / sf;
        // the ink is the glyphs' own box, not the layout's: a wrapped line's trailing space counts in the
        // layout width but draws nothing (an empty label has no glyphs: its box is the block)
        let (mut lo, mut hi) = (Vec2::splat(f32::MAX), Vec2::splat(f32::MIN));
        for g in &layout.glyphs {
            let half = g.atlas_info.rect.size() / 2.0;
            lo = lo.min(g.position - half);
            hi = hi.max(g.position + half);
        }
        let (ink_min, ink_size) = if layout.glyphs.is_empty() {
            (Vec2::ZERO, block)
        } else {
            (lo / sf, (hi - lo) / sf)
        };
        let block_at = Vec2::new(rect[0] + (rect[2] - block.x) / 2.0, rect[1] + (rect[3] - block.y) / 2.0);
        let ink = [block_at.x + ink_min.x, block_at.y + ink_min.y, ink_size.x, ink_size.y];
        let covered = meta
            .clip
            .and_then(|c| clips.get(c).ok())
            .is_some_and(|(cn, ct)| !inside(rect, rect_of(cn, ct), 1.0));
        let fits_node = ink_size.x <= rect[2] + 1.0 && ink_size.y <= rect[3] + 1.0;
        let fits_window = inside(ink, window, 1.0);
        let why = if !fits_node {
            "the text is wider than its box"
        } else if !fits_window {
            "off screen"
        } else {
            ""
        };
        let mut entry = json!({
            "node": meta.id,
            "text": meta.id.clone(),
            "px": meta.px,
            "fg": hex(colour.0),
            "state": meta.state,
            "rect": rect,
            "ink": ink,
            "fits": fits_node && fits_window,
            "covered": covered,
        });
        if !why.is_empty() {
            entry["why"] = json!(why);
        }
        if let Some(bg) = meta.bg {
            entry["bg"] = json!(hex(bg));
        } else if !meta.over_game.is_empty() {
            entry["over_game"] = json!(
                meta.over_game
                    .iter()
                    .map(|(c, a)| json!([hex(*c), a]))
                    .collect::<Vec<_>>()
            );
        }
        texts.push(entry);
    }
    report.result = Some(json!({
        "screen": screen,
        "world": world,
        "design": [win_w, win_h],
        "scaling": "exact",
        "texts": texts,
    }));
}

// {{FOOTER}}
