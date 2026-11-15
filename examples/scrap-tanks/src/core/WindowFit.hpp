// ---------------------------------------------------------------------------
// WindowFit.hpp
// Purpose : Where a windowed display.resolution goes on screen (#308): the size fitted to the screen's usable area
//           (the desktop without the taskbar) less the window's frame, and centred there, as Godot does with
//           screen_get_usable_rect. Shell::apply_display moves and sizes the window with it.
// Usage   : core::WindowPlace p = core::fit_window(1920, 1080, {0, 0, 1920, 1152}, {31, 8, 8, 8});
//           SDL_SetWindowSize(window, p.w, p.h); SDL_SetWindowPosition(window, p.x, p.y);
// Notes   : Header-only, no SDL (tests/test_window_fit.cpp). Sizes and positions are SDL window coordinates of
//           the client area (SDL_SetWindowPosition places the client's top-left; the frame is outside it). Seen on
//           a real window before this: a 1920x1080 window on a 1920x1200 screen kept its old top-left and ran
//           past the bottom edge.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <algorithm>

namespace core {

struct ScreenRect { int x, y, w, h; };          // the usable area, in window coordinates
struct FrameSize { int top, left, bottom, right; };   // the window's decorations (SDL_GetWindowBordersSize)
struct WindowPlace { int x, y, w, h; };         // the client area: position and size

// The wanted size, shrunk to what fits inside the usable area with the frame around it, centred there.
inline WindowPlace fit_window(int want_w, int want_h, ScreenRect usable, FrameSize frame) {
    const int room_w = std::max(1, usable.w - frame.left - frame.right);
    const int room_h = std::max(1, usable.h - frame.top - frame.bottom);
    const int w = std::max(1, std::min(want_w, room_w));
    const int h = std::max(1, std::min(want_h, room_h));
    return {usable.x + frame.left + (room_w - w) / 2, usable.y + frame.top + (room_h - h) / 2, w, h};
}

}  // namespace core
