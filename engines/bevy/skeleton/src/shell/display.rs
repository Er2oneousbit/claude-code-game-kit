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
//   fullscreen -> Fullscreen(current monitor, current video mode), on Windows BorderlessFullscreen; vsync -> AutoVsync, else AutoNoVsync;
//   size: windowed and a monitor known -> resolution clamped to the monitor, else none;
//   frame_cap 0 -> no limit, else 1/cap seconds a frame
//   apply_display: (settings version, monitor size) unchanged or automated -> nothing; else write the plan to the
//   window, changing only fields that differ (a Window write is a winit call); a windowed size goes through
//   fit_window(size, the monitor's work area, the window's frame) -> the size and the frame's top-left
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-14 with Claude (Opus 5.5, claude-opus-5-5): on Windows "fullscreen" is borderless (winit panics
//           when Windows refuses the exclusive mode change), and the windowed size fits the screen's usable area
//           with the window's frame and is centred there (fit_window), as Godot's usable rect does (#308, both
//           seen on a real window)
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

/// What the kit's "fullscreen" asks winit for. Windows: borderless, because winit asserts that the exclusive mode
/// change succeeds and panics when Windows refuses it (DISP_CHANGE_FAILED, seen in a remote session): the game must
/// never crash on a setting. The current video mode is kept either way, so the picture is the same.
pub fn fullscreen_mode() -> WindowMode {
    if cfg!(windows) {
        WindowMode::BorderlessFullscreen(MonitorSelection::Current)
    } else {
        WindowMode::Fullscreen(MonitorSelection::Current, VideoModeSelection::Current)
    }
}

/// Where a windowed size goes: the size shrunk so it fits the usable area (`work`, physical pixels) with the
/// window's `frame` (outer minus inner size) around it, and the frame's top-left that centres it there.
pub fn fit_window(want: UVec2, work: IRect, frame: UVec2) -> (UVec2, IVec2) {
    let room = (work.size() - frame.as_ivec2()).max(IVec2::ONE);
    let size = want.as_ivec2().min(room).max(IVec2::ONE);
    (size.as_uvec2(), work.min + (room - size) / 2)
}

/// The usable area of the window's monitor (without the taskbar) and the window's frame, from Windows; None
/// elsewhere (the size is then only clamped to the monitor).
#[cfg(windows)]
fn work_area_and_frame(handle: &bevy::window::RawHandleWrapper) -> Option<(IRect, UVec2)> {
    use raw_window_handle::RawWindowHandle;
    use windows_sys::Win32::Foundation::RECT;
    use windows_sys::Win32::Graphics::Gdi::{
        GetMonitorInfoW, MONITOR_DEFAULTTONEAREST, MONITORINFO, MonitorFromWindow,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetClientRect, GetWindowRect};
    let RawWindowHandle::Win32(h) = handle.get_window_handle() else {
        return None;
    };
    let hwnd = h.hwnd.get();
    let zero = RECT {
        left: 0,
        top: 0,
        right: 0,
        bottom: 0,
    };
    let (mut outer, mut inner) = (zero, zero);
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        rcMonitor: zero,
        rcWork: zero,
        dwFlags: 0,
    };
    // SAFETY: plain Win32 queries on this game's own live window, each writing into a struct passed by pointer
    let ok = unsafe {
        GetWindowRect(hwnd, &mut outer) != 0
            && GetClientRect(hwnd, &mut inner) != 0
            && GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &mut info) != 0
    };
    if !ok {
        return None;
    }
    let w = &info.rcWork;
    let frame = IVec2::new(
        (outer.right - outer.left) - (inner.right - inner.left),
        (outer.bottom - outer.top) - (inner.bottom - inner.top),
    );
    Some((
        IRect::new(w.left, w.top, w.right, w.bottom),
        frame.max(IVec2::ZERO).as_uvec2(),
    ))
}

#[cfg(not(windows))]
fn work_area_and_frame(_handle: &bevy::window::RawHandleWrapper) -> Option<(IRect, UVec2)> {
    None
}

/// The settings-to-window mapping. `monitor` is the current monitor's physical size, when known.
pub fn plan(s: &Value, monitor: Option<UVec2>) -> DisplayPlan {
    let mode = match settings::text(s, "display", "mode") {
        "fullscreen" => fullscreen_mode(),
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
    mut frame_seen: Local<UVec2>,
    shell: Res<Shell>,
    mut windows: Query<(&mut Window, Option<&bevy::window::RawHandleWrapper>), With<PrimaryWindow>>,
    monitors: Query<(&Monitor, Has<PrimaryMonitor>)>,
    mut limit: ResMut<FrameLimit>,
) {
    if shell.automated {
        return;
    }
    let Ok((mut window, handle)) = windows.single_mut() else {
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
    if let Some(size) = p.size {
        // fit the usable area with the frame and centre it, where the platform says what that area is
        // coming back from fullscreen the window has no frame yet: use the last frame a titled window had
        let place = handle.and_then(work_area_and_frame).map(|(work, frame)| {
            *frame_seen = frame.max(*frame_seen);
            fit_window(size, work, *frame_seen)
        });
        let size = place.map_or(size, |(s, _)| s);
        if UVec2::new(window.physical_width(), window.physical_height()) != size {
            window.resolution.set_physical_resolution(size.x, size.y);
        }
        if let Some((_, at)) = place {
            window.position = WindowPosition::At(at);
        }
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
        assert_eq!(p.mode, fullscreen_mode());
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

    #[test]
    #[cfg(windows)]
    fn fullscreen_on_windows_never_asks_for_an_exclusive_mode_change() {
        // winit panics when Windows refuses the change (DISP_CHANGE_FAILED): seen in a remote session (#308)
        let p = plan(&with("fullscreen", true, 0, [1280, 720]), Some(UVec2::new(1920, 1200)));
        assert_eq!(p.mode, WindowMode::BorderlessFullscreen(MonitorSelection::Current));
    }

    #[test]
    fn the_windowed_size_fits_the_usable_area_with_its_frame_and_is_centred() {
        // a 1920x1200 screen with a 48 px taskbar and a 16x39 frame (seen: a window ran past the screen's edge)
        let work = IRect::new(0, 0, 1920, 1152);
        let (size, at) = fit_window(UVec2::new(1600, 900), work, UVec2::new(16, 39));
        assert_eq!(size, UVec2::new(1600, 900));
        assert_eq!(at, IVec2::new((1920 - 16 - 1600) / 2, (1152 - 39 - 900) / 2));
        let (size, at) = fit_window(UVec2::new(1920, 1200), work, UVec2::new(16, 39));
        assert_eq!(size, UVec2::new(1904, 1113), "the frame stays on the screen");
        assert_eq!(at, IVec2::ZERO);
        let (_, at) = fit_window(UVec2::new(800, 600), IRect::new(1920, 0, 3200, 1024), UVec2::ZERO);
        assert_eq!(at, IVec2::new(1920 + 240, 212), "a second screen's offset is kept");
    }
}

// {{FOOTER}}
