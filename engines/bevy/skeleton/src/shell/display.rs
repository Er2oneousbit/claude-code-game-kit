// ---------------------------------------------------------------------------
// shell/display.rs
// Purpose : The display settings (display.mode, vsync, frame_cap, resolution) applied to the primary window (#268):
//           WindowMode, PresentMode, the windowed size, and a frame limiter for the frame rate cap.
// Usage   : ShellPlugin adds apply_display (Update, after sync_settings) and limit_frame_rate (Last).
//           display::plan(&shell.settings, Some(monitor_size)) -> DisplayPlan   (the mapping, tested headless)
// Notes   : Never in automated runs (dev.py smoke, captures, the access sweep): their window must stay the size the
//           run asked for. Without a window (headless) both systems do nothing. The windowed size is clamped to the
//           monitor (like Godot's usable rect and LOVE's desktop check) and left alone until a monitor is known;
//           it is in physical pixels, the unit the settings screen shows. Fullscreen keeps the monitor's current
//           video mode (a mode switch to another resolution is left to the game). Bevy has no frame cap of its
//           own: the limiter sleeps at the end of the frame until 1/cap seconds have passed since the last one.
//
// Pseudocode:
//   plan(settings, monitor): mode: windowed -> Windowed, borderless -> BorderlessFullscreen(current monitor),
//   fullscreen -> Fullscreen(current monitor, current video mode); vsync -> AutoVsync, else AutoNoVsync;
//   size: windowed and a monitor known -> resolution clamped to the monitor, else none;
//   frame_cap 0 -> no limit, else 1/cap seconds a frame
//   apply_display: (settings version, monitor size) unchanged or automated -> nothing; else write the plan to the
//   window, changing only fields that differ (a Window write is a winit call)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::time::{Duration, Instant};

use bevy::prelude::*;
use bevy::window::{
    Monitor, MonitorSelection, PresentMode, PrimaryMonitor, PrimaryWindow, VideoModeSelection, WindowMode,
};
use serde_json::Value;

use super::Shell;
use crate::logic::settings;

/// What the display settings ask of the window.
#[derive(Debug, Clone, PartialEq)]
pub struct DisplayPlan {
    pub mode: WindowMode,
    pub present: PresentMode,
    /// The windowed size in physical pixels; None leaves the size alone (fullscreen, or no monitor known yet).
    pub size: Option<UVec2>,
    /// The shortest frame (display.frame_cap); None = no cap.
    pub frame_time: Option<Duration>,
}

/// The settings-to-window mapping. `monitor` is the current monitor's physical size, when known.
pub fn plan(s: &Value, monitor: Option<UVec2>) -> DisplayPlan {
    let mode = match settings::text(s, "display", "mode") {
        "fullscreen" => WindowMode::Fullscreen(MonitorSelection::Current, VideoModeSelection::Current),
        "borderless" => WindowMode::BorderlessFullscreen(MonitorSelection::Current),
        _ => WindowMode::Windowed,
    };
    let present = if settings::flag(s, "display", "vsync") {
        PresentMode::AutoVsync
    } else {
        PresentMode::AutoNoVsync
    };
    let wanted = s["display"]["resolution"]
        .as_array()
        .and_then(|a| Some(UVec2::new(a.first()?.as_u64()? as u32, a.get(1)?.as_u64()? as u32)))
        .filter(|r| r.x >= 1 && r.y >= 1);
    let size = match (mode, wanted, monitor) {
        (WindowMode::Windowed, Some(r), Some(m)) if m.x >= 1 && m.y >= 1 => Some(r.min(m)),
        _ => None,
    };
    let cap = settings::num(s, "display", "frame_cap");
    let frame_time = (cap >= 1.0).then(|| Duration::from_secs_f64(1.0 / cap));
    DisplayPlan {
        mode,
        present,
        size,
        frame_time,
    }
}

/// The frame rate cap the limiter keeps, and when the last frame ended.
#[derive(Resource, Debug, Default)]
pub struct FrameLimit {
    pub frame_time: Option<Duration>,
    last: Option<Instant>,
}

/// The display settings -> the primary window, whenever the settings or the monitor change (never automated).
pub fn apply_display(
    mut last: Local<Option<(u64, Option<UVec2>)>>,
    shell: Res<Shell>,
    mut windows: Query<&mut Window, With<PrimaryWindow>>,
    monitors: Query<(&Monitor, Has<PrimaryMonitor>)>,
    mut limit: ResMut<FrameLimit>,
) {
    if shell.automated {
        return;
    }
    let Ok(mut window) = windows.single_mut() else {
        return;
    };
    // the primary monitor (winit marks it), else the first one; a window on a second screen still fits there
    let monitor = monitors
        .iter()
        .max_by_key(|(_, primary)| *primary)
        .map(|(m, _)| m.physical_size());
    let key = (shell.settings_version, monitor);
    if *last == Some(key) {
        return;
    }
    *last = Some(key);
    let p = plan(&shell.settings, monitor);
    if window.mode != p.mode {
        window.mode = p.mode;
    }
    if window.present_mode != p.present {
        window.present_mode = p.present;
    }
    if let Some(size) = p.size
        && UVec2::new(window.physical_width(), window.physical_height()) != size
    {
        window.resolution.set_physical_resolution(size.x, size.y);
    }
    limit.frame_time = p.frame_time;
    info!(
        "display: {:?}, {:?}, size {:?}, frame cap {:?}",
        p.mode, p.present, p.size, p.frame_time
    );
}

/// The frame rate cap: sleeps out the rest of the frame (no cap, no sleep).
pub fn limit_frame_rate(mut limit: ResMut<FrameLimit>) {
    let now = Instant::now();
    if let (Some(frame), Some(last)) = (limit.frame_time, limit.last) {
        let spent = now.duration_since(last);
        if spent < frame {
            std::thread::sleep(frame - spent);
        }
    }
    limit.last = Some(Instant::now());
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn with(mode: &str, vsync: bool, cap: i64, res: [u32; 2]) -> Value {
        let mut s = settings::defaults();
        s["display"]["mode"] = json!(mode);
        s["display"]["vsync"] = json!(vsync);
        s["display"]["frame_cap"] = json!(cap);
        s["display"]["resolution"] = json!(res);
        s
    }

    #[test]
    fn modes_vsync_and_the_cap_map_to_the_window() {
        let p = plan(&with("borderless", false, 60, [1280, 720]), None);
        assert_eq!(p.mode, WindowMode::BorderlessFullscreen(MonitorSelection::Current));
        assert_eq!(p.present, PresentMode::AutoNoVsync);
        assert_eq!(p.size, None, "a fullscreen mode keeps the monitor's size");
        assert_eq!(p.frame_time, Some(Duration::from_secs_f64(1.0 / 60.0)));
        let p = plan(&with("fullscreen", true, 0, [1280, 720]), Some(UVec2::new(2560, 1440)));
        assert_eq!(
            p.mode,
            WindowMode::Fullscreen(MonitorSelection::Current, VideoModeSelection::Current)
        );
        assert_eq!((p.present, p.size, p.frame_time), (PresentMode::AutoVsync, None, None));
    }

    #[test]
    fn the_windowed_size_fits_the_monitor_and_waits_for_one() {
        let s = with("windowed", true, 0, [1920, 1080]);
        assert_eq!(
            plan(&s, Some(UVec2::new(2560, 1440))).size,
            Some(UVec2::new(1920, 1080))
        );
        assert_eq!(plan(&s, Some(UVec2::new(1600, 900))).size, Some(UVec2::new(1600, 900)));
        assert_eq!(plan(&s, None).size, None, "no monitor known yet: leave the size alone");
        assert_eq!(plan(&s, None).mode, WindowMode::Windowed);
    }
}

// {{FOOTER}}
