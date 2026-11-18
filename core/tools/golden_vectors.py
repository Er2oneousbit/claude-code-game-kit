#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# golden_vectors.py
# Purpose : The reference implementation of the kit's engine-free game logic (juice: screen shake, hitstop, easing,
#           camera follow, input buffer, coyote time, spring, flash limiter; shell: settings, save migration,
#           rebinding, button glyphs, localization, pseudo-locale; telemetry: the CSV columns and row format; credits:
#           HTML comments out of CREDITS.md, then the text every credits screen shows) and the writer of the
#           golden-vector files every engine port is tested against: data/golden/juice.json, data/golden/shell.json,
#           data/golden/telemetry.json (only the ports that
#           write telemetry.csv read it) and data/golden/credits.json (only the ports with a credits screen read it);
#           platform services (achievements, stats, rich presence, the overlay's pause hook, the cloud-save hooks, the
#           offline queue: docs/PLATFORM.md) in data/golden/platform.json, for the ports of that layer (#84).
# Usage   : python tools/golden_vectors.py --check        # are the vector files current? (exit 1 if not)
#           python tools/golden_vectors.py --write        # rewrite them after changing this reference
#           python tools/golden_vectors.py --show shake   # print one module's cases
# Notes   : Each engine's port (GDScript, Lua, TypeScript, C#, Rust, C++) loads the JSON in its unit tests and must
#           reproduce every expected value within the file's tolerance. Change behavior here first, then --write,
#           then fix the ports until their tests pass again: this file is the spec, docs/sop/SOP-18 and SOP-19 explain
#           it. Every formula is chosen to give the same result in every language: integer noise uses Park-Miller
#           arithmetic that stays exact in 64-bit floats (no bit operations, so Lua 5.1 and JavaScript agree), and no
#           value depends on dictionary order. Standard library only, Python 3.8+.
# Exit    : 0 ok, 1 --check found stale files, 2 usage problem
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): credits_text, one rule for the markdown marks every
#           credits screen strips (heading marks, list markers, emphasis stars), credits.json's credits_text cases (#284)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): DisplayStaging, the Display tab's Apply with a
#           keep-or-revert confirm, and shell.json's display_staging cases (#308)
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the platform services layer (#84 phase 1):
#           achievements_load, Platform (unlock once, stat rules, offline queue and replay, presence, cloud hooks),
#           NullBackend, cloud_partition, overlay_action, platform_state_load, and platform.json's cases
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the content section (#171 blood, #207 clean language),
#           CLDR 46 plural() for whole numbers with an .other fallback per locale, @clean lookups in tr and
#           tr_plural, mask_words and mature_words, and shell.json's plural_rules, tr_clean, mask_words cases
# Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compile_words and mask_word_set, so a shell folds its
#           word list once, not on every t() (#207)
# Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the feel recipe helpers SOP-18's table builds on
#           (#170, #164): impact (hit confirm scaled by damage), float_text (a damage number's ease), trail_push,
#           trail_shrink and trail_length (a tracer's point history by distance), and their juice.json cases
# ---------------------------------------------------------------------------
#
# Pseudocode
#   modules below = the behavior; build_juice() / build_shell() run scripted cases through them and record outputs
#   --write: dump both to data/golden/*.json (sorted keys, stable floats)  --check: compare with what is on disk
import argparse
import copy
import datetime
import json
import math
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]          # the game root (core/ in the kit)
OUT_DIR = ROOT / "data" / "golden"
TOLERANCE = 1e-9                                     # ports compare floats within this (absolute): every port
                                                     # is 64-bit and libm differs by about 1 ulp; at 1e-6 a
                                                     # float32 Hitstop or Ease port would pass
VECTOR_VERSION = 1

# ----------------------------------------------------------------------------------------------- juice

PM_M = 2147483647                                    # Park-Miller modulus (2^31 - 1)
PM_A = 16807


def lattice(seed, i, ch):
    """A value in (-1, 1] for integer lattice point i of channel ch. Products stay below 2^53, so doubles are exact."""
    s = (seed * 7919 + i * 104729 + ch * 15485863) % PM_M
    if s == 0:
        s = 1
    s = (s * PM_A) % PM_M
    s = (s * PM_A) % PM_M
    return s / (PM_M - 1) * 2.0 - 1.0


def noise(seed, t, ch):
    """Smooth 1D value noise: lattice values blended with smoothstep. t >= 0."""
    i = math.floor(t)
    f = t - i
    a, b = lattice(seed, i, ch), lattice(seed, i + 1, ch)
    u = f * f * (3.0 - 2.0 * f)
    return a + (b - a) * u


class Shake:
    """Trauma-based screen shake: trauma 0..1 decays linearly; the shake is trauma squared times noise."""

    def __init__(self, max_offset=8.0, max_angle=0.05, decay=1.5, frequency=15.0, seed=1):
        self.max_offset, self.max_angle, self.decay, self.frequency, self.seed = \
            max_offset, max_angle, decay, frequency, seed
        self.trauma = 0.0
        self.time = 0.0

    def add_trauma(self, a):
        self.trauma = min(max(self.trauma + a, 0.0), 1.0)

    def update(self, dt, intensity=1.0):
        """Returns (x, y, angle). intensity is the player's shake setting (0 with reduce motion)."""
        self.time += dt
        self.trauma = max(self.trauma - self.decay * dt, 0.0)
        s = self.trauma * self.trauma * intensity
        t = self.time * self.frequency
        return (self.max_offset * s * noise(self.seed, t, 0),
                self.max_offset * s * noise(self.seed, t, 1),
                self.max_angle * s * noise(self.seed, t, 2))


class Hitstop:
    """Freezes game time for a moment on impact. Overlapping hits keep the longest, capped at max_s. Feed it the real
    frame delta; everything else uses the delta it returns."""

    def __init__(self, max_s=0.25):
        self.max_s = max_s
        self.remaining = 0.0

    def hit(self, duration):
        self.remaining = min(max(self.remaining, duration), self.max_s)

    def scaled_dt(self, real_dt):
        """The game's delta for this frame: the frozen part of real_dt is removed."""
        if self.remaining <= 0.0:
            return real_dt
        used = min(self.remaining, real_dt)
        self.remaining -= used
        return real_dt - used


C1 = 1.70158
C3 = C1 + 1.0
C4 = 2.0 * math.pi / 3.0


def _bounce(t):
    n1, d1 = 7.5625, 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    if t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


EASES = {
    "linear": lambda t: t,
    "in_quad": lambda t: t * t,
    "out_quad": lambda t: 1.0 - (1.0 - t) * (1.0 - t),
    "in_out_quad": lambda t: 2.0 * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0,
    "in_cubic": lambda t: t * t * t,
    "out_cubic": lambda t: 1.0 - (1.0 - t) ** 3,
    "in_out_cubic": lambda t: 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0,
    "in_sine": lambda t: 1.0 - math.cos(t * math.pi / 2.0),
    "out_sine": lambda t: math.sin(t * math.pi / 2.0),
    "in_out_sine": lambda t: -(math.cos(math.pi * t) - 1.0) / 2.0,
    "in_back": lambda t: C3 * t * t * t - C1 * t * t,
    "out_back": lambda t: 1.0 + C3 * (t - 1.0) ** 3 + C1 * (t - 1.0) ** 2,
    "out_elastic": lambda t: 0.0 if t <= 0.0 else 1.0 if t >= 1.0 else
    2.0 ** (-10.0 * t) * math.sin((t * 10.0 - 0.75) * C4) + 1.0,
    "out_bounce": _bounce,
}


def ease(name, t):
    """t is clamped to 0..1; an unknown name is an error in every port."""
    return EASES[name](min(max(t, 0.0), 1.0))


class Follow:
    """Camera follow: a deadzone box around the camera, look-ahead along the target's velocity, and frame-rate
    independent exponential smoothing (smoothing 0 = snap)."""

    def __init__(self, deadzone_w=64.0, deadzone_h=48.0, lookahead=0.25, smoothing=8.0, x=0.0, y=0.0):
        self.dw, self.dh, self.lookahead, self.smoothing = deadzone_w, deadzone_h, lookahead, smoothing
        self.x, self.y = x, y

    @staticmethod
    def _axis(cam, target, half):
        if target > cam + half:
            return target - half
        if target < cam - half:
            return target + half
        return cam

    def update(self, dt, tx, ty, vx=0.0, vy=0.0):
        dx = self._axis(self.x, tx, self.dw / 2.0) + vx * self.lookahead
        dy = self._axis(self.y, ty, self.dh / 2.0) + vy * self.lookahead
        k = 1.0 - math.exp(-self.smoothing * dt) if self.smoothing > 0.0 else 1.0
        self.x += (dx - self.x) * k
        self.y += (dy - self.y) * k
        return self.x, self.y


class InputBuffer:
    """Remembers a press for window_s, so a jump pressed just before landing still happens."""

    def __init__(self, window_s=0.12):
        self.window = window_s
        self.pending = {}

    def press(self, action):
        self.pending[action] = self.window

    def update(self, dt):
        for a in sorted(self.pending):
            self.pending[a] -= dt
            if self.pending[a] <= 1e-12:
                del self.pending[a]

    def consume(self, action):
        if self.pending.get(action, 0.0) > 0.0:
            del self.pending[action]
            return True
        return False


class Coyote:
    """Grace window to jump after leaving a ledge; same rules as the Godot and web CoyoteTimer."""

    def __init__(self, window_s=0.1):
        self.window = max(window_s, 0.0)
        self.time_left = 0.0
        self.grounded = False
        self.consumed = False

    def update(self, dt, on_floor):
        if on_floor:
            if not self.grounded:
                self.consumed = False
            self.grounded = True
            self.time_left = self.window
        else:
            self.grounded = False
            self.time_left = max(self.time_left - dt, 0.0)

    def can_jump(self):
        return (not self.consumed) and (self.grounded or self.time_left > 0.0)

    def consume(self):
        self.consumed = True
        self.time_left = 0.0


class Spring:
    """A damped spring (semi-implicit Euler) for squash and stretch recovery, UI pops and wobble."""

    def __init__(self, frequency=4.0, damping=0.5):
        self.frequency, self.damping = frequency, damping
        self.x, self.v, self.target = 0.0, 0.0, 0.0

    def update(self, dt):
        w = 2.0 * math.pi * self.frequency
        a = -w * w * (self.x - self.target) - 2.0 * self.damping * w * self.v
        self.v += a * dt
        self.x += self.v * dt
        return self.x


def squash(amount):
    """Volume-keeping scale for a squash (amount > 0 widens and flattens, < 0 stretches). Clamped above -0.9."""
    a = max(amount, -0.9)
    return 1.0 + a, 1.0 / (1.0 + a)


class FlashLimiter:
    """Photosensitivity guard: at most max_flashes full-screen flashes in any window_s (three per second). Always on (no
    setting disables it); pass real, unscaled time, not game time."""

    def __init__(self, max_flashes=3, window_s=1.0):
        self.max, self.window = max_flashes, window_s
        self.times = []

    def request(self, now):
        self.times = [t for t in self.times if t > now - self.window]
        if len(self.times) < self.max:
            self.times.append(now)
            return True
        return False


# ------------------------------------------------------------------------------------------ feel recipes
# The small engine-free helpers SOP-18's recipe table builds on (#170): pure functions, no settings read, no clock and
# no random number generator. The rest of the recipes are compositions a game writes itself (SOP-18 step 4).
# Their tunables are the keyword defaults below (the ports use the same defaults); a game passes its own.


def impact(damage, full, hitstop_min=0.03, hitstop_max=0.1, trauma_min=0.15, trauma_max=0.6, flash_at=0.5):
    """Hit confirm scaled by damage: f = damage / full clamped to 0..1 (full <= 0 counts every hit as full), then
    hitstop and trauma linear from their min at the smallest hit to their max at a full one, and flash when
    f >= flash_at. No damage (<= 0) is no confirm at all. The flash is a request: it still goes through the flash
    limiter and the player's flash_limit, and the trauma through the shake's intensity (effective_shake)."""
    if damage <= 0.0:
        return {"hitstop": 0.0, "trauma": 0.0, "flash": False}
    f = 1.0 if full <= 0.0 else min(max(damage / full, 0.0), 1.0)
    return {"hitstop": hitstop_min + (hitstop_max - hitstop_min) * f,
            "trauma": trauma_min + (trauma_max - trauma_min) * f, "flash": f >= flash_at}


def float_text(t, life=0.8, rise=24.0, pop_s=0.12):
    """A damage number's motion at age t (game time): it rises by `rise` px on out_cubic over its life (dy is
    negative: y down), pops in with out_back over pop_s (scale overshoots 1, then settles at 1) and fades on in_cubic
    (alpha 1 to 0). done once t >= life. reduce motion: pass rise 0 and pop_s 0 (no pop: scale 1 from the start)."""
    u = min(max(t / life, 0.0), 1.0) if life > 0.0 else 1.0
    scale = ease("out_back", t / pop_s) if pop_s > 0.0 else 1.0
    return {"dy": -rise * ease("out_cubic", u), "scale": scale, "alpha": 1.0 - ease("in_cubic", u),
            "done": t >= life}


def _seg(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    return math.sqrt(dx * dx + dy * dy)


def trail_length(points):
    """Total length of a trail's points, tail (first) to head (last)."""
    total = 0.0   # a plain running sum, as every port adds: sum() compensates its rounding since Python 3.12
    for i in range(len(points) - 1):
        total += _seg(points[i], points[i + 1])
    return total


def _trim_to(points, keep):
    """Drop length from the tail until the trail is `keep` long: whole segments go, the last one is cut where the
    length runs out (the tail point slides toward the head). keep <= 0 leaves the head alone."""
    pts = [list(p) for p in points]
    excess = trail_length(pts) - max(keep, 0.0)
    while excess > 1e-12 and len(pts) > 1:
        s = _seg(pts[0], pts[1])
        if s <= excess + 1e-12:
            pts.pop(0)
            excess -= s
        else:
            k = excess / s
            pts[0] = [pts[0][0] + (pts[1][0] - pts[0][0]) * k, pts[0][1] + (pts[1][1] - pts[0][1]) * k]
            excess = 0.0
    return pts


def trail_push(points, x, y, spacing=6.0, max_len=48.0):
    """A tracer's point history (#164), in world space: the last point is the head and follows (x, y) every frame; a
    new point is kept once the head is `spacing` px past the point before it, so the history is by distance, not by
    frame (the same path at 30 and 144 fps), and a curving or homing shot leaves a curve. Longer than max_len, the
    tail is cut. Returns a new list of [x, y], tail first."""
    pts = [list(p) for p in points]
    if len(pts) < 2:
        pts.append([x, y])
    elif _seg(pts[-2], pts[-1]) >= spacing:
        pts.append([x, y])
    else:
        pts[-1] = [x, y]
    return _trim_to(pts, max_len)


def trail_shrink(points, amount):
    """The tail catching up after the shot dies: remove `amount` px (speed * dt) from the tail. Down to the head
    alone, the trail is gone: draw nothing for fewer than two points."""
    return _trim_to(points, trail_length(points) - amount)


# ----------------------------------------------------------------------------------------------- shell

DIFFICULTIES = ["story", "easy", "normal", "hard"]
COLORBLIND = ["none", "protanopia", "deuteranopia", "tritanopia"]
SUB_SIZES = ["small", "medium", "large", "xl"]
GLYPH_SETS = ["auto", "keyboard", "xbox", "playstation", "generic"]
DISPLAY_MODES = ["windowed", "fullscreen", "borderless"]
FRAME_CAPS = [0, 30, 60, 120, 144, 240]
CONSENT = ["unset", "yes", "no"]

DEFAULT_BINDINGS = {
    "ui_up": ["key:up", "pad:dpad_up"], "ui_down": ["key:down", "pad:dpad_down"],
    "ui_left": ["key:left", "pad:dpad_left"], "ui_right": ["key:right", "pad:dpad_right"],
    "ui_accept": ["key:enter", "pad:south"], "ui_cancel": ["key:escape", "pad:east"],
    "move_left": ["key:a", "pad:dpad_left"], "move_right": ["key:d", "pad:dpad_right"],
    "move_up": ["key:w", "pad:dpad_up"], "move_down": ["key:s", "pad:dpad_down"],
    "jump": ["key:space", "pad:south"], "attack": ["key:j", "pad:west"],
    "interact": ["key:e", "pad:north"], "pause": ["key:escape", "pad:start"],
}

DEFAULT_SETTINGS = {
    "version": 1,
    "display": {"mode": "windowed", "vsync": True, "frame_cap": 0, "resolution": [1920, 1080], "ui_scale": 1.0},
    "audio": {"master": 1.0, "music": 0.8, "sfx": 1.0, "ui": 1.0, "voice": 1.0, "mono": False},
    "language": "en",
    "access": {"text_scale": 1.0, "subtitles": True, "subtitle_size": "medium", "subtitle_background": 0.6,
               "speaker_names": True, "subtitle_barks": False, "captions_sfx": False, "colorblind": "none",
               "reduce_motion": False, "shake_scale": 1.0, "flash_limit": True, "hold_to_toggle": False,
               "difficulty": "normal", "game_speed": 1.0,
               # #167 cognitive: a clearer font, more space between lines, subtitles that wait for the player
               "readable_font": False, "line_spacing": 1.0, "subtitle_hold": False,
               # #166 motor: every timing window (input buffer, coyote time, double press, hold) times this, and
               # holding a button repeats its press ("hold to mash")
               "timing_scale": 1.0, "auto_repeat": False,
               # #165: every focus change, value change and screen is spoken (the OS speech or a screen reader)
               "narration": False},
    "input": {"bindings": DEFAULT_BINDINGS, "deadzone": 0.2, "invert_y": False, "glyphs": "auto"},
    "telemetry": {"consent": "unset"},
    # #171 and #207: what the game shows, not how. blood: the game's blood effects (off: a neutral hit effect in
    # their place, SOP-18); clean_language: the string tables' @clean variants and the word mask (SOP-19)
    "content": {"blood": True, "clean_language": False},
}

# per field: ("num", lo, hi) | ("bool",) | ("enum", values) | ("res",) | ("lang",); the default comes from above
SCHEMA = {
    "display": {"mode": ("enum", DISPLAY_MODES), "vsync": ("bool",), "frame_cap": ("enum", FRAME_CAPS),
                "resolution": ("res",), "ui_scale": ("num", 0.75, 2.0)},
    "audio": {k: ("num", 0.0, 1.0) for k in ("master", "music", "sfx", "ui", "voice")},
    "access": {"text_scale": ("num", 0.75, 2.0), "subtitles": ("bool",), "subtitle_size": ("enum", SUB_SIZES),
               "subtitle_background": ("num", 0.0, 1.0), "speaker_names": ("bool",), "subtitle_barks": ("bool",),
               "captions_sfx": ("bool",), "colorblind": ("enum", COLORBLIND), "reduce_motion": ("bool",),
               "shake_scale": ("num", 0.0, 1.0), "flash_limit": ("bool",), "hold_to_toggle": ("bool",),
               "difficulty": ("enum", DIFFICULTIES), "game_speed": ("num", 0.5, 1.0),
               "readable_font": ("bool",), "line_spacing": ("num", 1.0, 2.0), "subtitle_hold": ("bool",),
               "timing_scale": ("num", 1.0, 3.0), "auto_repeat": ("bool",), "narration": ("bool",)},
    "input": {"deadzone": ("num", 0.0, 0.9), "invert_y": ("bool",), "glyphs": ("enum", GLYPH_SETS)},
    "telemetry": {"consent": ("enum", CONSENT)},
    "content": {"blood": ("bool",), "clean_language": ("bool",)},
}
SCHEMA["audio"]["mono"] = ("bool",)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fix(rule, value, default):
    """(value, problem?) for one field."""
    kind = rule[0]
    if kind == "bool":
        return (value, False) if isinstance(value, bool) else (default, True)
    if kind == "num":
        if not _is_num(value) or value != value:        # NaN is not a number here
            return default, True
        clamped = min(max(float(value), rule[1]), rule[2])
        return clamped, clamped != value
    if kind == "enum":
        for allowed in rule[1]:
            if type(allowed) is type(value) or (_is_num(allowed) and _is_num(value)):
                if value == allowed:
                    return allowed, False
        return default, True
    if kind == "res":
        # isfinite first: int(Infinity) raises, int(NaN) too (Python's json reads both constants; the ports guard)
        if isinstance(value, list) and len(value) == 2 and all(_is_num(n) and math.isfinite(n) and n >= 1 and n == int(n)
                                                               for n in value):
            return [int(value[0]), int(value[1])], False
        return list(default), True
    raise ValueError(rule)


def _fix_bindings(value, problems):
    out = copy.deepcopy(DEFAULT_BINDINGS)
    if not isinstance(value, dict):
        problems.append("input.bindings")
        return out
    for action, lst in value.items():
        if not isinstance(lst, list):
            problems.append(f"input.bindings.{action}")
            continue
        clean = [b for b in lst if isinstance(b, str)]
        if len(clean) != len(lst):
            problems.append(f"input.bindings.{action}")
        out[action] = clean
    return out


def settings_load(text):
    """Settings from the file's text: (settings, problems). Missing fields take defaults, bad ones are fixed (each
    fix is one problem), unknown keys are kept as they are so a newer game's file survives an older build."""
    problems = []
    try:
        raw = json.loads(text) if text is not None else {}
    except ValueError:
        return copy.deepcopy(DEFAULT_SETTINGS), ["unreadable"]
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULT_SETTINGS), ["not an object"]
    out = {k: copy.deepcopy(v) for k, v in raw.items()}
    out["version"] = 1
    lang = raw.get("language", "en")
    if isinstance(lang, str) and 2 <= len(lang) <= 12:
        out["language"] = lang
    else:
        out["language"] = "en"
        if "language" in raw:
            problems.append("language")
    for section, fields in SCHEMA.items():
        src = raw.get(section, {})
        if not isinstance(src, dict):
            problems.append(section)
            src = {}
        sec = {k: copy.deepcopy(v) for k, v in src.items()}
        for name, rule in fields.items():
            default = DEFAULT_SETTINGS[section][name]
            if name in src:
                value, bad = _fix(rule, src[name], default)
                if bad:
                    problems.append(f"{section}.{name}")
            else:
                value = copy.deepcopy(default)
            sec[name] = value
        if section == "input":
            if "bindings" in src:
                sec["bindings"] = _fix_bindings(src["bindings"], problems)
            else:
                sec["bindings"] = copy.deepcopy(DEFAULT_BINDINGS)
        out[section] = sec
    return out, problems


def narration_line(label, role, value=""):
    """What the narration says for one control (#165): "Music volume, slider, 70 percent". The label and the value
    lose their line breaks and doubled spaces; a control with no label says "unlabelled" so it is never silent; the
    role word comes translated from the caller."""
    label = " ".join(str(label).split())
    parts = [label or "unlabelled"]
    if role:
        parts.append(" ".join(str(role).split()))
    value = " ".join(str(value).split())
    if value:
        parts.append(value)
    return ", ".join(parts)


def effective_shake(settings):
    return 0.0 if settings["access"]["reduce_motion"] else settings["access"]["shake_scale"]


def telemetry_allowed(settings):
    return settings["telemetry"]["consent"] == "yes"


def blood_enabled(settings):
    """#171: may the game show blood? The effect is the game's own; off swaps it for a neutral one (SOP-18)."""
    return settings["content"]["blood"]


def clean_language(settings):
    """#207: the translator picks @clean variants and masks the game's word list (tr's clean flag, SOP-19)."""
    return settings["content"]["clean_language"]


def group_of(action):
    return "ui" if action.startswith("ui_") else "game"


def rebind(bindings, action, slot, binding):
    """Puts binding in action's slot. Another action of the same group (ui_* or game) that used it gets this slot's
    old binding (a swap), or "" (unbound) when there was none. Returns (bindings, conflicts as sorted [action, slot])."""
    b = copy.deepcopy(bindings)
    lst = b.setdefault(action, [])
    if slot > len(lst):
        raise ValueError("slot past the end")
    old = lst[slot] if slot < len(lst) else ""
    conflicts = []
    for other in sorted(b):
        if group_of(other) != group_of(action):
            continue
        for s, name in enumerate(b[other]):
            if (other, s) != (action, slot) and name == binding and binding != "":
                conflicts.append([other, s])
    if slot == len(lst):
        lst.append(binding)
    else:
        lst[slot] = binding
    for other, s in conflicts:
        b[other][s] = old
    return b, conflicts


def glyph_set(setting, last_device):
    """Which prompt art to show: the player's choice, or (auto) the last device used."""
    if setting != "auto":
        return setting
    return {"keyboard": "keyboard", "mouse": "keyboard", "pad_xbox": "xbox",
            "pad_playstation": "playstation"}.get(last_device, "generic")


XBOX = {"south": "a", "east": "b", "west": "x", "north": "y", "l1": "lb", "r1": "rb", "l2": "lt", "r2": "rt",
        "start": "menu", "select": "view"}
PLAYSTATION = {"south": "cross", "east": "circle", "west": "square", "north": "triangle", "start": "options",
               "select": "share"}


def glyph_name(gset, binding):
    """The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick..."""
    kind, _, name = binding.partition(":")
    if kind == "key":
        return "key_" + name
    if kind == "mouse":
        return "mouse_" + name
    if kind == "pad_axis":
        name = "lstick" if name.startswith("left") else "rstick"
    elif kind != "pad":
        return "unknown"
    if gset == "xbox":
        return "xbox_" + XBOX.get(name, name)
    if gset == "playstation":
        return "ps_" + PLAYSTATION.get(name, name)
    return "pad_" + name


def prompt_binding(bindings, action, gset):
    """The binding to show for an action: slot 0 (keyboard) for the keyboard set, slot 1 (pad) otherwise."""
    lst = bindings.get(action, [])
    slot = 0 if gset == "keyboard" else 1
    return lst[slot] if slot < len(lst) else ""


SAVE_VERSION = 3


def _migrate_1_to_2(data):
    if "hp" in data:                                # the example chain: v2 renamed hp to health
        data["health"] = data.pop("hp")
    return data


def _migrate_2_to_3(data):
    data.setdefault("difficulty", "normal")         # v3 added the difficulty the game was started on
    return data


MIGRATIONS = {1: _migrate_1_to_2, 2: _migrate_2_to_3}


def _parse_save(text):
    """(envelope, problem): envelope is {"format": "save", "version": int, "data": object}."""
    if text is None:
        return None, "missing"
    try:
        env = json.loads(text)
    except ValueError:
        return None, "unreadable"
    if not isinstance(env, dict) or env.get("format") != "save" or not isinstance(env.get("data"), dict):
        return None, "not a save"
    v = env.get("version")
    if not _is_num(v) or not math.isfinite(v) or v != int(v) or v < 1:   # Infinity, NaN: a bad version, not a crash
        return None, "bad version"
    if v > SAVE_VERSION:
        return None, "newer"
    env["version"] = int(v)
    return env, ""


def save_migrate(env):
    env = copy.deepcopy(env)
    while env["version"] < SAVE_VERSION:
        env["data"] = MIGRATIONS[env["version"]](env["data"])
        env["version"] += 1
    return env


def save_load(primary, backup):
    """(envelope at SAVE_VERSION or None, source "primary" | "backup" | "none", problems). A save from a newer game
    version is never loaded and the game must not overwrite it: while the primary or the backup holds one, every
    write to that slot is refused (a write after a good primary would copy it over a newer backup)."""
    problems = []
    for source, text in (("primary", primary), ("backup", backup)):
        env, problem = _parse_save(text)
        if env is not None:
            return save_migrate(env), source, problems
        problems.append(f"{source}: {problem}")
    return None, "none", problems


def locale_chain(locale, fallback="en"):
    chain = []
    for loc in (locale, locale.split("-")[0].split("_")[0], fallback):
        if loc and loc not in chain:
            chain.append(loc)
    return chain


def _fill(text, args):
    out, i = [], 0
    while i < len(text):
        if text[i] == "{":
            j = text.find("}", i)
            if j > i:
                name = text[i + 1:j]
                if name in args:
                    out.append(str(args[name]))
                    i = j + 1
                    continue
        out.append(text[i])
        i += 1
    return "".join(out)


CLEAN_SUFFIX = "@clean"                             # "guard.insult@clean": the line with the clean-language setting
                                                     # on (#207); '@' is reserved in key names for this


def _pick(table, key, clean):
    """One locale's text for key: its @clean variant first when clean is on, else (or when there is none) the key."""
    if clean and key + CLEAN_SUFFIX in table:
        return table[key + CLEAN_SUFFIX]
    return table.get(key)


def _finish(text, args, clean, words):
    out = _fill(text, args or {})
    return mask_words(out, words) if clean and words else out


def tr(tables, locale, key, args=None, clean=False, words=None):
    """A string through the fallback chain (fr-CA -> fr -> en); a missing key returns the key itself, so it shows.
    Argument values are whole numbers or strings: format a float yourself before passing it (languages print 2.0
    differently), and count text in code points, not UTF-16 units.
    clean (#207, the content.clean_language setting): each locale of the chain is asked for key@clean, then key,
    before the next locale, so a French line without a clean variant stays French (the player's language wins; the
    audit, check_i18n.py, lists the gap) and an English @clean never replaces a French line. Then the filled text
    (placeholder values included: a player's name is text too) goes through mask_words with words, the game's
    word list for the chain (mature_words). clean off: words are ignored, the text is as written."""
    for loc in locale_chain(locale):
        text = _pick(tables.get(loc, {}), key, clean)
        if text is not None:
            return _finish(text, args, clean, words)
    return key


# ---- CLDR plural rules ------------------------------------------------------------------------------------------
# Cardinal rules for whole numbers (CLDR operands i = n, v = 0), from CLDR 46 common/supplemental/plurals.xml
# (release-46, checked 2026-11-17 by sweeping n = 0..2000 and every multiple of a million up to 10^8 through an
# evaluator of that file's rules). A language is a family; the family is the rule. Unknown languages get "one"
# (n == 1). n is a whole number; a negative one uses its absolute value (CLDR's n). "other" is in every family's
# list because it is the fallback key every plural set needs, even where a whole number never reaches it (ru, pl).
PLURAL_FAMILIES = {                                  # family -> the categories it can return, CLDR order
    "other": ("other",),
    "one": ("one", "other"),                         # n = 1
    "zero_one": ("one", "other"),                    # n = 0, 1
    "one_many": ("one", "many", "other"),            # n = 1; many: a non-zero multiple of 1000000
    "zero_one_many": ("one", "many", "other"),       # n = 0, 1; many: a non-zero multiple of 1000000
    "one_21": ("one", "other"),                      # n % 10 = 1 and n % 100 != 11 (21, 31, 101 ...)
    "fil": ("one", "other"),                         # n % 10 not 4, 6, 9 (0 and 1-3 too)
    "east_slavic": ("one", "few", "many", "other"),  # 1, 21; few 2-4, 22-24; many 0, 5-20, 25-30
    "pl": ("one", "few", "many", "other"),           # 1; few 2-4, 22-24 (not 12-14); many the rest
    "cs": ("one", "few", "other"),                   # 1; few 2-4 (CLDR's many is for fractions only)
    "lt": ("one", "few", "other"),                   # 1, 21; few 2-9, 22-29 (not 11-19); many is for fractions
    "balkan": ("one", "few", "other"),               # 1, 21; few 2-4, 22-24 (not 12-14)
    "ro": ("one", "few", "other"),                   # 1; few 0 and n % 100 = 1-19
    "lv": ("zero", "one", "other"),                  # zero n % 10 = 0 or n % 100 = 11-19; one 1, 21 (not 11)
    "he": ("one", "two", "other"),
    "sl": ("one", "two", "few", "other"),            # n % 100 = 1; 2; 3-4
    "ga": ("one", "two", "few", "many", "other"),    # 1; 2; 3-6; 7-10
    "ar": ("zero", "one", "two", "few", "many", "other"),   # 0; 1; 2; n % 100 = 3-10; n % 100 = 11-99
    "cy": ("zero", "one", "two", "few", "many", "other"),   # 0; 1; 2; 3; 6
}
PLURAL_LANGUAGES = {                                 # family -> languages (base language codes, lower case)
    "other": "ja zh ko vi th id ms lo my km yo ig jv su",
    "one": "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr",
    "zero_one": "hi bn fa gu kn hy",
    "one_many": "es it ca",
    "zero_one_many": "fr pt",
    "one_21": "is mk",
    "fil": "fil tl",
    "east_slavic": "ru uk be",
    "pl": "pl",
    "cs": "cs sk",
    "lt": "lt",
    "balkan": "hr sr bs",
    "ro": "ro mo",
    "lv": "lv",
    "he": "he",
    "sl": "sl",
    "ga": "ga",
    "ar": "ar",
    "cy": "cy",
}
PLURAL_LOCALE_FAMILIES = {"pt-pt": "one_many"}       # a region with its own rule: European Portuguese 0 is "other"
PLURAL_FAMILY_OF = {lang: fam for fam, langs in PLURAL_LANGUAGES.items() for lang in langs.split()}
MILLION = 1000000


def plural_family(locale):
    """The rule family for a locale: its full name first (pt-PT, case and '_' or '-' do not matter), then its
    language, then "one"."""
    norm = locale.replace("_", "-").lower()
    for name, fam in PLURAL_LOCALE_FAMILIES.items():
        if norm == name or norm.startswith(name + "-"):
            return fam
    return PLURAL_FAMILY_OF.get(norm.split("-")[0], "one")


def plural_categories(locale):
    """Every category plural() can return for this locale, plus "other": what a translation must provide."""
    return PLURAL_FAMILIES[plural_family(locale)]


def plural(locale, n):
    """The CLDR plural category of whole number n in locale: zero, one, two, few, many or other."""
    fam = plural_family(locale)
    n = abs(int(n))
    m10, m100 = n % 10, n % 100
    if fam == "other":
        return "other"
    if fam == "one":
        return "one" if n == 1 else "other"
    if fam == "zero_one":
        return "one" if n <= 1 else "other"
    if fam in ("one_many", "zero_one_many"):
        if n == 1 or (n == 0 and fam == "zero_one_many"):
            return "one"
        return "many" if n != 0 and n % MILLION == 0 else "other"
    if fam == "one_21":
        return "one" if m10 == 1 and m100 != 11 else "other"
    if fam == "fil":
        return "other" if m10 in (4, 6, 9) else "one"
    if fam in ("east_slavic", "balkan"):
        if m10 == 1 and m100 != 11:
            return "one"
        if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
            return "few"
        return "many" if fam == "east_slavic" else "other"
    if fam == "pl":
        if n == 1:
            return "one"
        return "few" if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else "many"
    if fam == "cs":
        return "one" if n == 1 else "few" if 2 <= n <= 4 else "other"
    if fam == "lt":
        if 11 <= m100 <= 19:
            return "other"
        return "one" if m10 == 1 else "few" if m10 >= 2 else "other"
    if fam == "ro":
        if n == 1:
            return "one"
        return "few" if n == 0 or 1 <= m100 <= 19 else "other"
    if fam == "lv":
        if m10 == 0 or 11 <= m100 <= 19:
            return "zero"
        return "one" if m10 == 1 else "other"
    if fam == "he":
        return "one" if n == 1 else "two" if n == 2 else "other"
    if fam == "sl":
        return "one" if m100 == 1 else "two" if m100 == 2 else "few" if m100 in (3, 4) else "other"
    if fam == "ga":
        return ("one" if n == 1 else "two" if n == 2 else "few" if 3 <= n <= 6 else "many" if 7 <= n <= 10
                else "other")
    if fam == "ar":
        if n <= 2:
            return ("zero", "one", "two")[n]
        return "few" if 3 <= m100 <= 10 else "many" if m100 >= 11 else "other"
    if fam == "cy":
        return {0: "zero", 1: "one", 2: "two", 3: "few", 6: "many"}.get(n, "other")
    raise ValueError(fam)


def tr_plural(tables, locale, key, n, args=None, clean=False, words=None):
    """key.<category> through the chain, each locale with its own category: in each locale, key.<its category>, then
    key.other (a table without the few or many form still shows its other form, never a raw key), then the next
    locale. @clean variants as in tr: key.few@clean before key.few. Nothing anywhere: the key with the requested
    locale's category, so it shows."""
    a = dict(args or {})
    a["n"] = n
    for loc in locale_chain(locale):
        table = tables.get(loc, {})
        for cat in dict.fromkeys((plural(loc, n), "other")):
            text = _pick(table, key + "." + cat, clean)
            if text is not None:
                return _finish(text, a, clean, words)
    return key + "." + plural(locale, n)


# ---- the word mask (#207) -------------------------------------------------------------------------------------
# A pinned, code-point-exact algorithm, so Lua, C++ and Rust (bytes), C# and Unreal (UTF-16) and Python agree: no
# str.lower(), isalpha() or unicodedata (Python's Unicode tables change between versions; no port has the same).
# Word characters: ASCII letters and digits, and every code point from U+0080 up except the ranges below
# (punctuation, symbols, spaces, emoji, variation selectors; combining marks are word characters). A word is a
# maximal run of word characters. Matching folds case with the table in fold_char (ASCII, Latin-1, Latin
# Extended-A, Greek, Cyrillic; everything else matches exactly) and compares the whole word with each listed word,
# so "class" never matches "ass". No normalization: a precomposed and a decomposed "é" are different words. The
# limits (SOP-19): Chinese and Japanese have no spaces, so a run of ideographs is one word, and a German compound
# is one word, so list the compounds themselves. A listed entry that is empty or holds a non-word character (two
# words, a hyphen) never matches. The mask is a same-length grawlix: GRAWLIX repeated, one per code point,
# starting again with each word.
GRAWLIX = "#@$%"
MASK_BOUNDARY_RANGES = [                             # inclusive code point ranges that are never word characters
    (0x0080, 0x00BF),                                # Latin-1 controls, no-break space, punctuation and signs
    (0x00D7, 0x00D7), (0x00F7, 0x00F7),              # multiplication and division signs
    (0x2000, 0x2BFF),                                # spaces, punctuation (curly quotes), symbols, arrows, dingbats
    (0x2E00, 0x2E7F),                                # supplemental punctuation
    (0x3000, 0x303F),                                # CJK symbols and punctuation (the ideographic space and stops)
    (0xFE00, 0xFE0F),                                # variation selectors
    (0xFE10, 0xFE1F), (0xFE30, 0xFE6F),              # vertical and small forms
    (0xFEFF, 0xFEFF),                                # zero-width no-break space
    (0xFF00, 0xFF0F), (0xFF1A, 0xFF20), (0xFF3B, 0xFF40), (0xFF5B, 0xFF65),   # fullwidth punctuation
    (0x1F000, 0x1FAFF),                              # emoji and pictographs
]


def is_word_char(cp):
    if cp < 0x80:
        return 0x30 <= cp <= 0x39 or 0x41 <= cp <= 0x5A or 0x61 <= cp <= 0x7A
    return not any(lo <= cp <= hi for lo, hi in MASK_BOUNDARY_RANGES)


def fold_char(cp):
    """The pinned case fold: one code point to one code point (lower case; final sigma to sigma)."""
    if 0x41 <= cp <= 0x5A or (0xC0 <= cp <= 0xDE and cp != 0xD7):
        return cp + 0x20
    if cp == 0x130:                                  # capital I with dot -> i
        return 0x69
    if cp == 0x178:                                  # Y with diaeresis -> its Latin-1 small letter
        return 0xFF
    if ((0x100 <= cp <= 0x12F or 0x132 <= cp <= 0x137 or 0x14A <= cp <= 0x177) and cp % 2 == 0) or \
            ((0x139 <= cp <= 0x148 or 0x179 <= cp <= 0x17E) and cp % 2 == 1):
        return cp + 1                                # Latin Extended-A pairs: capital, then small
    if 0x391 <= cp <= 0x3AB and cp != 0x3A2:         # Greek capitals (with dialytika) -> small
        return cp + 0x20
    if cp == 0x386:
        return 0x3AC
    if 0x388 <= cp <= 0x38A:
        return cp + 0x25
    if cp == 0x38C:
        return 0x3CC
    if cp in (0x38E, 0x38F):
        return cp + 0x3F
    if cp == 0x3C2:                                  # final sigma matches sigma
        return 0x3C3
    if 0x400 <= cp <= 0x40F:                         # Cyrillic capitals with marks -> small
        return cp + 0x50
    if 0x410 <= cp <= 0x42F:                         # Cyrillic capitals -> small
        return cp + 0x20
    return cp


def _fold(cps):
    return tuple(fold_char(c) for c in cps)


def compile_words(words):
    """The folded set mask_word_set matches against. Build it once per word list and locale (the shells cache it:
    t() runs for every label every frame, and folding a few thousand words each time is the cost, not the scan)."""
    wanted = set()
    for w in words or ():
        cps = [ord(c) for c in w]
        if cps and all(is_word_char(c) for c in cps):
            wanted.add(_fold(cps))
    return frozenset(wanted)


def mask_words(text, words):
    """text with every whole word that is in words (case folded) replaced by a same-length grawlix."""
    return mask_word_set(text, compile_words(words))


def mask_word_set(text, wanted):
    """mask_words with the word list compiled already (compile_words)."""
    if not wanted:
        return text
    cps = [ord(c) for c in text]
    out, i = [], 0
    while i < len(cps):
        if not is_word_char(cps[i]):
            out.append(chr(cps[i]))
            i += 1
            continue
        j = i
        while j < len(cps) and is_word_char(cps[j]):
            j += 1
        word = cps[i:j]
        if _fold(word) in wanted:
            out.extend(GRAWLIX[k % len(GRAWLIX)] for k in range(len(word)))
        else:
            out.extend(chr(c) for c in word)
        i = j
    return "".join(out)


MATURE_DIR = "data/i18n/mature"                      # <locale>.json per language: the game's own word list


def mature_words(text):
    """A word list file's words: {"words": ["...", ...]} (other keys, such as a "_note", are ignored). Strings
    only; anything unreadable or of another shape is no words. A game loads the file of every locale in the
    chain and passes all of them (a fallback line can come from any of them)."""
    try:
        raw = json.loads(text) if text is not None else {}
    except ValueError:
        return []
    words = raw.get("words") if isinstance(raw, dict) else None
    if not isinstance(words, list):
        return []
    return [w for w in words if isinstance(w, str)]


PSEUDO_GROWTH = 0.40                                 # translated English runs about 40 % longer (SOP-19)
PSEUDO = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "c": "ç", "n": "ñ", "y": "ý",
          "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú", "C": "Ç", "N": "Ñ", "Y": "Ý"}


def pseudo(text):
    """The pseudo-locale: accented look-alikes (catches missing glyphs), 40 % longer (catches truncation; Microsoft's
    heuristic for English source text, docs/sop/SOP-19), in
    brackets (catches strings cut at either end and text that is not translatable). Placeholders {name}, %s, %d,
    %i, %f and %% pass through unchanged and do not count toward the length."""
    out, visible, i = [], 0, 0
    while i < len(text):
        c = text[i]
        if c == "{":
            j = text.find("}", i)
            if j > i:
                out.append(text[i:j + 1])
                i = j + 1
                continue
        if c == "%" and i + 1 < len(text) and text[i + 1] in "sdif%":
            out.append(text[i:i + 2])
            i += 2
            continue
        out.append(PSEUDO.get(c, c))
        visible += 1
        i += 1
    return "[" + "".join(out) + "~" * math.ceil(visible * PSEUDO_GROWTH) + "]"


# ------------------------------------------------------------------------------------------- telemetry

TELEMETRY_HEADER = "time,session,event,detail"     # the one column set every port's telemetry.csv uses
SESSION_LENGTH = 8                                  # session: a random id per launch, lowercase hex
SESSION_CHARS = "0123456789abcdef"


def csv_field(value):
    """One CSV field, quoted (RFC 4180) when it holds a comma, a quote or a line break."""
    if any(c in value for c in ',"\r\n'):
        return '"' + value.replace('"', '""') + '"'
    return value


def telemetry_time(unix_s):
    """UTC, ISO 8601, whole seconds (a fraction is dropped, not rounded): 2026-11-02T14:05:03Z."""
    t = datetime.datetime.fromtimestamp(math.floor(unix_s), datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def telemetry_row(unix_s, session, event, detail=""):
    return ",".join(csv_field(f) for f in (telemetry_time(unix_s), session, event, detail))


# --------------------------------------------------------------------------------------------- credits

COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"


def _blank(line):
    """Only spaces and tabs (the ports agree on these two; Unicode whitespace differs between languages)."""
    return all(c in " \t" for c in line)


def strip_html_comments(text):
    """CREDITS.md as a credits screen reads it: every HTML comment removed (tools/credits.py writes one; #279), one
    line or many, an unclosed one running to the end of the file. A line that held only comments (and spaces or
    tabs) goes, and when a blank line (or the top of the file) came before it, so does one blank line after it, so
    the gap the comment sat in does not double. Text around a comment on its line stays as written. CRLF becomes LF;
    the result is joined with LF. The delimiters are ASCII, so a byte-wise port (Lua, C++, Rust) gives the same
    result as a code-unit one. credits_text runs this first, then takes the markdown marks off."""
    out = []
    in_comment = False
    skip_blank = False                               # the blank line after a dropped comment-only line
    for line in text.replace("\r\n", "\n").split("\n"):
        kept, had, i = "", in_comment, 0
        while True:
            if in_comment:
                end = line.find(COMMENT_CLOSE, i)
                if end < 0:
                    break                            # the comment goes on into the next line
                in_comment, i = False, end + len(COMMENT_CLOSE)
            else:
                start = line.find(COMMENT_OPEN, i)
                if start < 0:
                    kept += line[i:]
                    break
                kept += line[i:start]
                in_comment, had, i = True, True, start + len(COMMENT_OPEN)
        if had and _blank(kept):
            skip_blank = not out or _blank(out[-1])
            continue
        if skip_blank and _blank(kept):
            skip_blank = False
            continue
        skip_blank = False
        out.append(kept)
    return "\n".join(out)


LIST_MARKERS = "-*+"                                 # a list item's first character (then a space or tab)
EMPHASIS_MARK = "*"                                  # every one goes: **bold**, *italic*; underscores stay


def credits_text(markdown):
    """CREDITS.md as every credits screen shows it (#284): strip_html_comments first, then line by line: leading
    spaces and tabs off; a heading's marks off (one or more '#' at the start, then a space, a tab or the end of the
    line; '#3' or 'C#' stay), or else a list marker ('-', '*' or '+' at the start, then a space or tab; '1.' stays);
    the spaces and tabs after either off; every '*' off (bold and italic marks; '_' stays, so file names like
    player_idle.png survive); trailing spaces and tabs off. Blank lines at the start and the end go, blank lines
    between paragraphs stay. "" means nothing to show (the placeholder). Whitespace means space and tab only, so a
    no-break space survives in every port (each language's trim() strips more, and differently)."""
    lines = []
    for line in strip_html_comments(markdown).split("\n"):
        s = line.lstrip(" \t")
        marks = len(s) - len(s.lstrip("#"))
        if marks and (marks == len(s) or s[marks] in " \t"):
            s = s[marks:].lstrip(" \t")              # a heading: its text stays
        elif len(s) >= 2 and s[0] in LIST_MARKERS and s[1] in " \t":
            s = s[1:].lstrip(" \t")                  # a list item: its text stays
        lines.append(s.replace(EMPHASIS_MARK, "").rstrip(" \t"))
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------- display staging
DISPLAY_APPLY_ORDER = ["mode", "resolution", "vsync", "frame_cap", "ui_scale"]  # mode before resolution
DISPLAY_CONFIRM_FIELDS = ("mode", "resolution")      # can black out the screen: Apply asks "keep these?"
DISPLAY_CONFIRM_S = 15.0                             # real seconds before an unanswered confirm reverts


class DisplayStaging:
    """The Display tab's Apply (#308; SOP-19 section 2): Display changes wait for Apply, every other tab applies at
    once. Engine-free: it never touches the window, it returns the (field, value) calls the shell makes through its
    set_value. Rules:
    - stage(field, v): a pending change, shown by the control; staging the applied value drops it. Refused while a
      confirm is open (the controls are disabled then).
    - apply(): the pending fields that differ from the applied ones, in DISPLAY_APPLY_ORDER; remembers the values they
      replace; a change to mode or resolution opens the confirm (DISPLAY_CONFIRM_S, counted in real time).
    - tick(dt): the countdown; reaching 0 reverts. seconds() is ceil(left) for the "Reverting in N s" line.
    - keep(): closes the confirm, the new values stay. revert(): puts back exactly what the last apply replaced.
    - back(): while a confirm is open, reverts (a screen the player cannot see must never stick); else with pending
      changes, the first back warns and the second discards them; else leaves."""

    def __init__(self, applied):
        self.applied = copy.deepcopy(applied)
        self.pending = {}
        self.replaced = {}                           # field -> the value the last apply replaced
        self.left = None                             # confirm countdown in seconds, None when closed
        self.warned = False

    def value(self, field):
        return self.pending.get(field, self.applied[field])

    def stage(self, field, v):
        if self.left is not None:
            return "busy"
        if v == self.applied[field]:
            self.pending.pop(field, None)
        else:
            self.pending[field] = copy.deepcopy(v)
        self.warned = False
        return "staged"

    def _set(self, values):
        calls = []
        for field in DISPLAY_APPLY_ORDER:
            if field in values:
                self.applied[field] = copy.deepcopy(values[field])
                calls.append([field, values[field]])
        return calls

    def apply(self):
        changed = {f: v for f, v in self.pending.items() if v != self.applied[f]}
        self.replaced = {f: copy.deepcopy(self.applied[f]) for f in changed}
        self.pending = {}
        self.warned = False
        calls = self._set(changed)
        if any(f in changed for f in DISPLAY_CONFIRM_FIELDS):
            self.left = DISPLAY_CONFIRM_S
        return calls

    def seconds(self):
        return None if self.left is None else int(math.ceil(self.left))

    def tick(self, dt):
        if self.left is None:
            return []
        self.left -= dt
        return self.revert() if self.left <= 0 else []

    def keep(self):
        self.left = None
        self.replaced = {}

    def revert(self):
        calls = self._set(self.replaced)
        self.left = None
        self.replaced = {}
        return calls

    def back(self):
        if self.left is not None:
            return "revert", self.revert()
        if self.pending and not self.warned:
            self.warned = True
            return "warn", []
        self.pending = {}
        self.warned = False
        return "leave", []


def _staging_case(name, script):
    """Run a script of [op, args...] steps; record each step's result and the state after it."""
    st = DisplayStaging(DEFAULT_SETTINGS["display"])
    steps = []
    for op in script:
        kind, args = op[0], op[1:]
        out, calls = None, []
        if kind == "stage":
            out = st.stage(*args)
        elif kind == "apply":
            calls = st.apply()
        elif kind == "tick":
            calls = st.tick(*args)
        elif kind == "keep":
            st.keep()
        elif kind == "revert":
            calls = st.revert()
        elif kind == "back":
            out, calls = st.back()
        steps.append({"op": op, "out": out, "calls": calls, "pending": copy.deepcopy(st.pending),
                      "shown": {f: st.value(f) for f in DISPLAY_APPLY_ORDER}, "applied": copy.deepcopy(st.applied),
                      "seconds": st.seconds()})
    return {"type": "display_staging", "name": name, "confirm_s": DISPLAY_CONFIRM_S,
            "applied": DEFAULT_SETTINGS["display"], "steps": steps}


def _shake_case(name, params, script):
    s = Shake(**params)
    steps = []
    for op in script:
        if op[0] == "add_trauma":
            s.add_trauma(op[1])
            steps.append({"call": "add_trauma", "a": op[1]})
        else:
            x, y, ang = s.update(op[1], op[2])
            steps.append({"call": "update", "dt": op[1], "intensity": op[2],
                          "expect": {"x": x, "y": y, "angle": ang, "trauma": s.trauma}})
    return {"type": "shake", "name": name, "params": params, "steps": steps}


def build_juice():
    cases = []
    cases.append({"type": "noise", "name": "noise points", "points": [
        [seed, t, ch, noise(seed, t, ch)] for seed, t, ch in
        [(1, 0.0, 0), (1, 0.5, 0), (1, 1.0, 1), (1, 2.75, 2), (7, 13.3, 0), (42, 1500.25, 1), (3, 99999.9, 2)]]})
    cases.append(_shake_case("one hit decays", {"max_offset": 8.0, "max_angle": 0.05, "decay": 1.5,
                                                "frequency": 15.0, "seed": 1},
                             [["add_trauma", 0.6]] + [["update", 1 / 60, 1.0]] * 6 + [["update", 0.5, 1.0]]))
    cases.append(_shake_case("stacked hits clamp and intensity", {"max_offset": 12.0, "max_angle": 0.1, "decay": 1.0,
                                                                   "frequency": 20.0, "seed": 9},
                             [["add_trauma", 0.7], ["add_trauma", 0.7], ["update", 0.02, 0.5],
                              ["update", 0.02, 0.0], ["add_trauma", -2.0], ["update", 0.02, 1.0]]))
    h = Hitstop(0.25)
    steps = []
    for op in [["scaled_dt", 1 / 60], ["hit", 0.05], ["scaled_dt", 1 / 60], ["scaled_dt", 1 / 60],
               ["scaled_dt", 1 / 60], ["scaled_dt", 1 / 60], ["hit", 0.02], ["hit", 1.0], ["scaled_dt", 0.1],
               ["scaled_dt", 0.1], ["scaled_dt", 0.1], ["hit", -1.0], ["scaled_dt", 0.1]]:
        if op[0] == "hit":
            h.hit(op[1])
            steps.append({"call": "hit", "duration": op[1]})
        else:
            steps.append({"call": "scaled_dt", "dt": op[1],
                          "expect": {"dt": h.scaled_dt(op[1]), "remaining": h.remaining}})
    cases.append({"type": "hitstop", "name": "freeze, overlap, cap", "params": {"max_s": 0.25}, "steps": steps})
    ts = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0, -0.5, 1.5]
    cases.append({"type": "ease", "name": "every easing", "points": [
        [name, t, ease(name, t)] for name in sorted(EASES) for t in ts]})
    f = Follow(64.0, 48.0, 0.25, 8.0, 0.0, 0.0)
    steps = []
    for dt, tx, ty, vx, vy in [(1 / 60, 10, 0, 0, 0), (1 / 60, 40, 0, 300, 0), (1 / 60, 60, 30, 300, 120),
                               (0.1, 120, 30, 300, 0), (0.5, 120, 30, 0, 0), (0.016, -200, -100, -50, -50)]:
        x, y = f.update(dt, tx, ty, vx, vy)
        steps.append({"call": "update", "dt": dt, "tx": tx, "ty": ty, "vx": vx, "vy": vy,
                      "expect": {"x": x, "y": y}})
    cases.append({"type": "follow", "name": "deadzone, look-ahead, smoothing",
                  "params": {"deadzone_w": 64.0, "deadzone_h": 48.0, "lookahead": 0.25, "smoothing": 8.0,
                             "x": 0.0, "y": 0.0}, "steps": steps})
    f = Follow(32.0, 32.0, 0.0, 0.0, 5.0, 5.0)
    steps = []
    for dt, tx, ty in [(0.016, 10, 10), (0.016, 40, 5), (0.016, -30, 5)]:
        x, y = f.update(dt, tx, ty)
        steps.append({"call": "update", "dt": dt, "tx": tx, "ty": ty, "vx": 0, "vy": 0, "expect": {"x": x, "y": y}})
    cases.append({"type": "follow", "name": "snap without smoothing",
                  "params": {"deadzone_w": 32.0, "deadzone_h": 32.0, "lookahead": 0.0, "smoothing": 0.0,
                             "x": 5.0, "y": 5.0}, "steps": steps})
    b = InputBuffer(0.12)
    steps = []
    for op in [["press", "jump"], ["update", 0.05], ["consume", "jump"], ["consume", "jump"], ["press", "jump"],
               ["update", 0.1], ["update", 0.02], ["consume", "jump"], ["press", "attack"], ["consume", "attack"],
               ["press", "jump"], ["press", "attack"], ["update", 0.119], ["consume", "attack"], ["consume", "jump"]]:
        if op[0] == "press":
            b.press(op[1])
            steps.append({"call": "press", "action": op[1]})
        elif op[0] == "update":
            b.update(op[1])
            steps.append({"call": "update", "dt": op[1]})
        else:
            steps.append({"call": "consume", "action": op[1], "expect": {"result": b.consume(op[1])}})
    cases.append({"type": "input_buffer", "name": "press, age, consume", "params": {"window_s": 0.12},
                  "steps": steps})
    c = Coyote(0.1)
    steps = []
    for op in [["update", 0.016, True], ["can_jump"], ["update", 0.05, False], ["can_jump"], ["consume"],
               ["can_jump"], ["update", 0.016, True], ["can_jump"], ["update", 0.2, False], ["can_jump"],
               ["update", 0.016, True], ["consume"], ["update", 0.016, True], ["can_jump"]]:
        if op[0] == "update":
            c.update(op[1], op[2])
            steps.append({"call": "update", "dt": op[1], "on_floor": op[2]})
        elif op[0] == "consume":
            c.consume()
            steps.append({"call": "consume"})
        else:
            steps.append({"call": "can_jump", "expect": {"result": c.can_jump()}})
    cases.append({"type": "coyote", "name": "grace window and landing", "params": {"window_s": 0.1},
                  "steps": steps})
    sp = Spring(4.0, 0.5)
    sp.x = 0.4
    steps = []
    for dt in [1 / 60] * 5 + [0.1, 0.1, 0.5]:
        steps.append({"call": "update", "dt": dt, "expect": {"x": sp.update(dt), "v": sp.v}})
    cases.append({"type": "spring", "name": "squash recovers", "params": {"frequency": 4.0, "damping": 0.5,
                                                                          "x": 0.4, "v": 0.0, "target": 0.0},
                  "steps": steps})
    cases.append({"type": "squash", "name": "volume kept", "points": [[a, *squash(a)] for a in
                                                                       (0.0, 0.3, -0.25, -2.0, 100.3)]})
    fl = FlashLimiter(3, 1.0)
    steps = []
    for now in [0.0, 0.1, 0.2, 0.3, 0.9, 1.0, 1.05, 1.1, 1.2, 2.5]:
        steps.append({"call": "request", "now": now, "expect": {"result": fl.request(now)}})
    cases.append({"type": "flash_limiter", "name": "three per second", "params": {"max_flashes": 3, "window_s": 1.0},
                  "steps": steps})
    # feel recipes (#170): every case passes every argument, so a port's defaults are not what is tested
    imp = dict(hitstop_min=0.03, hitstop_max=0.1, trauma_min=0.15, trauma_max=0.6, flash_at=0.5)
    pts = []
    for dmg, full in [(0.0, 10.0), (-3.0, 10.0), (1.0, 10.0), (4.0, 10.0), (5.0, 10.0), (10.0, 10.0), (25.0, 10.0),
                      (3.0, 0.0), (2.5, -1.0)]:
        r = impact(dmg, full, **imp)
        pts.append([dmg, full, r["hitstop"], r["trauma"], r["flash"]])
    cases.append({"type": "impact", "name": "hit confirm scaled by damage", "params": imp, "points": pts})
    imp2 = dict(hitstop_min=0.05, hitstop_max=0.05, trauma_min=0.0, trauma_max=1.0, flash_at=1.0)
    pts = []
    for dmg, full in [(0.5, 2.0), (1.999, 2.0), (2.0, 2.0)]:
        r = impact(dmg, full, **imp2)
        pts.append([dmg, full, r["hitstop"], r["trauma"], r["flash"]])
    cases.append({"type": "impact", "name": "flat hitstop, flash only at full", "params": imp2, "points": pts})
    for name, params, ts in [("damage number", {"life": 0.8, "rise": 24.0, "pop_s": 0.12},
                              [0.0, 0.03, 0.06, 0.12, 0.2, 0.4, 0.7, 0.8, 1.0, -0.1]),
                             ("reduce motion: no rise, no pop", {"life": 0.5, "rise": 0.0, "pop_s": 0.0},
                              [0.0, 0.25, 0.5]),
                             ("no life", {"life": 0.0, "rise": 10.0, "pop_s": 0.1}, [0.0, 0.05])]:
        pts = []
        for t in ts:
            r = float_text(t, **params)
            pts.append([t, r["dy"], r["scale"], r["alpha"], r["done"]])
        cases.append({"type": "float_text", "name": name, "params": params, "points": pts})
    for name, params, script in [
            ("straight shot by distance", {"spacing": 6.0, "max_len": 20.0},
             [["push", x, 0.0] for x in (0.0, 2.0, 4.0, 7.0, 9.0, 15.0, 30.0, 33.0)]
             + [["shrink", 5.0], ["shrink", 2.5], ["shrink", 100.0]]),
            ("curving shot keeps a curve", {"spacing": 4.0, "max_len": 30.0},
             [["push", 10.0 * math.cos(a / 4.0), 10.0 * math.sin(a / 4.0)] for a in range(10)]
             + [["shrink", 12.0], ["push", 0.0, 0.0]]),
            ("one point is no trail", {"spacing": 3.0, "max_len": 0.0},
             [["push", 1.0, 1.0], ["push", 5.0, 1.0], ["shrink", 1.0]])]:
        pts, steps = [], []
        for op in script:
            if op[0] == "push":
                pts = trail_push(pts, op[1], op[2], params["spacing"], params["max_len"])
                step = {"call": "push", "x": op[1], "y": op[2]}
            else:
                pts = trail_shrink(pts, op[1])
                step = {"call": "shrink", "amount": op[1]}
            step["expect"] = {"points": [list(p) for p in pts], "length": trail_length(pts)}
            steps.append(step)
        cases.append({"type": "trail", "name": name, "params": params, "steps": steps})
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "generator": "tools/golden_vectors.py",
            "cases": cases}


TABLES = {
    "en": {"menu.play": "Play", "menu.settings": "Settings", "greet": "Hello, {name}!",
           "apples.one": "{n} apple", "apples.other": "{n} apples", "only.en": "English only"},
    "fr": {"menu.play": "Jouer", "greet": "Bonjour, {name} !", "apples.one": "{n} pomme", "apples.other": "{n} pommes"},
    "fr-CA": {"menu.play": "Jouer!"},
    "ja": {"menu.play": "プレイ", "apples.other": "りんご{n}個"},
}

# CLDR plurals: ru has every form, uk lacks many (its other shows), pl has no table (English with English's rule)
PLURAL_TABLES = {
    "en": {"hits.one": "{n} hit", "hits.other": "{n} hits"},
    "ru": {"hits.one": "{n} удар", "hits.few": "{n} удара", "hits.many": "{n} ударов", "hits.other": "{n} удара"},
    "uk": {"hits.one": "{n} удар", "hits.few": "{n} удари", "hits.other": "{n} ударів"},
    "ar": {"hits.zero": "لا ضربات", "hits.one": "ضربة واحدة", "hits.two": "ضربتان", "hits.few": "{n} ضربات",
           "hits.many": "{n} ضربة", "hits.other": "{n} ضربة"},
    "fr": {"hits.one": "{n} coup", "hits.many": "{n} de coups", "hits.other": "{n} coups"},
    "cs": {"hits.one": "{n} zásah", "hits.few": "{n} zásahy", "hits.other": "{n} zásahů"},
    "de": {"hits.one": "{n} Treffer", "hits.other": "{n} Treffer"},
    "ja": {"hits.other": "{n}ヒット"},
}
PLURAL_SWEEP_LOCALES = ["en", "de", "fr", "fr-CA", "pt", "pt-BR", "pt-PT", "pt_PT", "es", "it", "ca", "ru", "RU",
                        "uk", "be", "pl", "cs", "sk", "lt", "hr", "sr", "ro", "lv", "he", "sl", "ga", "ar", "cy",
                        "is", "fil", "hi", "ja", "zh", "ko", "xx"]
PLURAL_SWEEP_N = 131                                 # 0..130: every last-two-digits rule, and 101..130 again
PLURAL_BIG_N = (-1, -3, 211, 1011, 1000000, 2000000, 1000001, 3000005)

# #207: en has clean variants, fr has its own for one line only, so "fr has the line, only en has @clean" shows
# the per-locale rule (the French line stays, the mask does the rest)
CLEAN_TABLES = {
    "en": {"guard.insult": "Get lost, you {name}!", "guard.insult@clean": "Get lost, you pest!",
           "guard.bye": "Damn, bye.", "shout": "Hell yes", "coins.one": "{n} damn coin", "coins.one@clean": "{n} coin",
           "coins.other": "{n} damn coins"},
    "fr": {"guard.insult": "Dégage, espèce de {name} !", "guard.bye": "Merde, salut.", "guard.bye@clean": "Bon, salut.",
           "coins.one": "{n} pièce", "coins.other": "{n} pièces"},
    # the category beats @clean inside a locale: few (plain) before other@clean
    "ru": {"coins.few": "{n} монеты", "coins.other@clean": "{n} монет"},
}
CLEAN_POINTS = [                                     # locale, key, n (None: tr), args, clean, words
    ("en", "guard.insult", None, {"name": "Ana"}, False, []),
    ("en", "guard.insult", None, {"name": "Ana"}, True, []),
    ("fr", "guard.insult", None, {"name": "crétin"}, True, ["CRÉTIN"]),
    ("fr", "guard.insult", None, {"name": "crétin"}, False, ["crétin"]),
    ("fr", "guard.bye", None, {}, True, ["merde"]),
    ("fr", "guard.bye", None, {}, False, ["merde"]),
    ("fr-CA", "guard.bye", None, {}, True, []),
    ("de", "guard.bye", None, {}, True, ["damn"]),
    ("de", "shout", None, {}, True, ["hell", "yes"]),
    ("en", "missing.key", None, {}, True, ["missing", "key"]),
    ("en", "coins", 1, {}, True, ["damn"]),
    ("en", "coins", 2, {}, True, ["damn"]),
    ("en", "coins", 2, {}, False, ["damn"]),
    ("fr", "coins", 0, {}, True, ["pièce"]),
    ("ru", "coins", 3, {}, True, ["damn"]),
    ("ru", "coins", 5, {}, True, []),
    ("ru", "nothing", 5, {}, True, []),              # nowhere: the key with the requested locale's category
]
MASK_POINTS = [                                      # text, words
    ("What the hell?", ["hell"]),
    ("HELL, Hell, hElL!", ["hell"]),
    ("hello shell hell", ["hell"]),
    ("ass class bass", ["ass", "", "two words", "x-y"]),
    ("Scheiße! scheiße", ["scheiße"]),
    ("ÉCRASÉ écrasé", ["écrasé"]),
    ("Łajdak łajdak", ["ŁAJDAK"]),
    ("СУКА сука Сука", ["сука"]),
    ("ΒΛΑΚΑΣ ΣΚΑΤΆ", ["βλακας", "σκατά"]),
    ("İSTANBUL", ["istanbul"]),
    ("ÿ Ÿ", ["ÿ"]),
    ("Ä×Ä÷ä", ["ä"]),
    ("damn’s damn's", ["damn"]),
    ("x-damn-x damn_it", ["damn"]),
    ("crap crap", ["crap"]),
    ("café café", ["café"]),
    ("\U0001D521\U0001D51E\U0001D52A\U0001D52B damn", ["\U0001D521\U0001D51E\U0001D52A\U0001D52B"]),
    ("damn\U0001F600 \U0001F600damn", ["damn"]),
    ("他妈的 他妈", ["他妈"]),
    ("Scheißkerl", ["scheiß"]),
    ("h4x0r h4x", ["h4x"]),
    ("¿Àx?", ["àx"]),
    ("a⯿b aⰀb", ["a", "b"]),
    ("", ["x"]),
    ("nothing listed", []),
]


def build_shell():
    cases = [{"type": "defaults", "name": "built-in defaults", "expect": DEFAULT_SETTINGS}]
    inputs = [
        ("empty file", ""),
        ("not json", "{volume: loud"),
        ("an array", "[1, 2]"),
        ("all defaults", json.dumps(DEFAULT_SETTINGS)),
        ("clamps and types", json.dumps({"audio": {"master": 1.5, "music": -0.2, "sfx": "loud", "mono": 1},
                                         "access": {"text_scale": 3, "difficulty": "nightmare",
                                                    "shake_scale": 0.25, "reduce_motion": True},
                                         "display": {"frame_cap": 75, "resolution": [1280.0, 720],
                                                     "mode": "fullscreen"}})),
        ("unknown keys kept", json.dumps({"future_section": {"x": 1}, "audio": {"master": 0.5, "reverb": "hall"},
                                          "language": "fr-CA"})),
        ("bad sections and bindings", json.dumps({"display": 5, "language": 7, "input": {
            "bindings": {"jump": ["key:k", 5], "dash": ["key:shift", "pad:r1"], "attack": "key:j"},
            "glyphs": "playstation", "deadzone": 0.95}})),
        # the language length counts code points: characters outside the Basic Multilingual Plane are two UTF-16
        # units each, so a port counting units (JavaScript String.length, C# Length) would get these two wrong
        ("language in code points", json.dumps({"language": "x-" + "\U0001D523\U0001D52F\U0001D51E\U0001D52B"
                                                "\U0001D520\U0001D522"}, ensure_ascii=False)),
        ("one code point is too short", json.dumps({"language": "\U0001D523"}, ensure_ascii=False)),
        # not standard JSON, but Python's reader (and some ports') accept the constants: either way the result is
        # the defaults with one problem (a port whose reader refuses them reports "unreadable", also one problem)
        ("non-finite resolution", '{"display": {"resolution": [Infinity, 720]}}'),
        ("NaN resolution", '{"display": {"resolution": [1280, NaN]}}'),
        # #261: two claims every port documents that no vector held. No file (null, not "") is the defaults with no
        # problem; and the version is 1 after a load whatever the file said, while a wrongly typed value is a problem
        # even when it spells a valid one ("true", "60": a loose port that coerces strings would pass them)
        ("no file", None),
        ("foreign version and spelled-out values", json.dumps({"version": 7, "future": True, "display": {
            "vsync": "true", "frame_cap": "60"}})),
        # #171 and #207: the content switches, a file from before them (the defaults), bad values and a bad section
        ("content switches flipped", json.dumps({"content": {"blood": False, "clean_language": True}})),
        ("content bad values", json.dumps({"content": {"blood": "no", "clean_language": 1, "gore": "max"}})),
        ("content not an object", json.dumps({"content": "off", "access": {"subtitles": False}})),
    ]
    for name, text in inputs:
        s, problems = settings_load(text)
        cases.append({"type": "settings_load", "name": name, "input": text, "expect": s,
                      "problems": len(problems), "effective_shake": effective_shake(s),
                      "telemetry_allowed": telemetry_allowed(s), "blood_enabled": blood_enabled(s),
                      "clean_language": clean_language(s)})
    s, _ = settings_load(json.dumps({"telemetry": {"consent": "yes"}}))
    cases.append({"type": "settings_load", "name": "consent given", "input": json.dumps({"telemetry": {"consent": "yes"}}),
                  "expect": s, "problems": 0, "effective_shake": effective_shake(s), "telemetry_allowed": True,
                  "blood_enabled": True, "clean_language": False})
    flipped, _ = settings_load(json.dumps({"content": {"blood": False, "clean_language": True}}))
    cases.append({"type": "settings_load", "name": "content switches survive a save and a load",
                  "input": json.dumps(flipped), "expect": flipped, "problems": 0,
                  "effective_shake": effective_shake(flipped), "telemetry_allowed": False, "blood_enabled": False,
                  "clean_language": True})
    for name, action, slot, binding in [("free key", "jump", 0, "key:k"), ("swap in group", "jump", 0, "key:j"),
                                        ("other group is fine", "ui_accept", 0, "key:space"),
                                        ("pad swap", "attack", 1, "pad:south"),
                                        ("new slot", "interact", 2, "key:f"),
                                        ("swap with an empty slot", "pause", 2, "key:a")]:
        out, conflicts = rebind(DEFAULT_BINDINGS, action, slot, binding)
        cases.append({"type": "rebind", "name": name, "bindings": DEFAULT_BINDINGS, "action": action, "slot": slot,
                      "binding": binding, "expect": {"bindings": out, "conflicts": conflicts}})
    pts = []
    for setting in GLYPH_SETS:
        for dev in ("keyboard", "mouse", "pad_xbox", "pad_playstation", "pad_other"):
            pts.append([setting, dev, glyph_set(setting, dev)])
    cases.append({"type": "glyph_set", "name": "auto follows the device", "points": pts})
    pts = []
    for gset in ("keyboard", "xbox", "playstation", "generic"):
        for b in ("key:space", "key:escape", "mouse:left", "pad:south", "pad:east", "pad:start", "pad:l2",
                  "pad:dpad_up", "pad_axis:leftx-", "pad_axis:righty+", "weird"):
            pts.append([gset, b, glyph_name(gset, b)])
    cases.append({"type": "glyph_name", "name": "prompt art names", "points": pts})
    cases.append({"type": "prompt_binding", "name": "slot per device", "bindings": DEFAULT_BINDINGS, "points": [
        [a, g, prompt_binding(DEFAULT_BINDINGS, a, g)] for a in ("jump", "pause", "missing")
        for g in ("keyboard", "xbox", "generic")]})
    saves = {
        "v1": json.dumps({"format": "save", "version": 1, "data": {"hp": 7, "level": 2}}),
        "v2": json.dumps({"format": "save", "version": 2, "data": {"health": 9, "level": 3}}),
        "v3": json.dumps({"format": "save", "version": 3, "data": {"health": 5, "difficulty": "hard"}}),
        "newer": json.dumps({"format": "save", "version": 4, "data": {}}),
        "corrupt": '{"format": "save", "version": 3, "data": {"health": 5',
        "wrong": json.dumps({"format": "settings", "version": 1, "data": {}}),
        "badver": json.dumps({"format": "save", "version": "2", "data": {}}),
        "infver": '{"format": "save", "version": Infinity, "data": {}}',
        "nanver": '{"format": "save", "version": NaN, "data": {}}',
    }
    for name, p, b in [("current", "v3", None), ("migrate from 1", "v1", None), ("migrate from 2", "v2", "v1"),
                       ("corrupt falls back", "corrupt", "v2"), ("both bad", "corrupt", "wrong"),
                       ("newer is refused", "newer", "v3"), ("bad version type", "badver", None),
                       ("infinite version", "infver", "v2"), ("NaN version", "nanver", None),
                       ("nothing saved", None, None)]:
        env, source, problems = save_load(saves.get(p), saves.get(b))
        cases.append({"type": "save_load", "name": name, "primary": saves.get(p), "backup": saves.get(b),
                      "expect": {"envelope": env, "source": source, "problems": len(problems)},
                      "current_version": SAVE_VERSION})
    pts = []
    for loc, key, args in [("en", "menu.play", {}), ("fr", "menu.play", {}), ("fr-CA", "menu.play", {}),
                           ("fr-CA", "greet", {"name": "Ana"}), ("fr_FR", "menu.settings", {}),
                           ("ja", "menu.play", {}), ("de", "greet", {"name": "Max"}), ("en", "missing.key", {}),
                           ("en", "greet", {}), ("fr", "only.en", {})]:
        pts.append([loc, key, args, tr(TABLES, loc, key, args)])
    cases.append({"type": "tr", "name": "fallback chain and placeholders", "tables": TABLES, "points": pts})
    pts = []
    for loc in ("en", "fr", "ja", "pt-BR"):
        for n in (0, 1, 2, 5):
            pts.append([loc, n, plural(loc, n), tr_plural(TABLES, loc, "apples", n)])
    cases.append({"type": "plural", "name": "one and other", "key": "apples", "tables": TABLES, "points": pts})
    pts = []
    for loc, ns in [("ru", (1, 3, 5, 11, 21, 22, 25, 101, 111)), ("uk", (2, 14)), ("pl", (1, 3, 5, 22)),
                    ("ar", (0, 1, 2, 3, 11, 100)), ("fr", (0, 1000000)), ("cs", (4, 5)), ("de", (1, 3)),
                    ("ru-RU", (2,)), ("ja", (1,))]:
        for n in ns:
            pts.append([loc, n, plural(loc, n), tr_plural(PLURAL_TABLES, loc, "hits", n)])
    cases.append({"type": "plural", "name": "CLDR forms, each locale with its own rule, other when a form is missing",
                  "key": "hits", "tables": PLURAL_TABLES, "points": pts})
    sweep = []
    for loc in PLURAL_SWEEP_LOCALES:
        sweep.append([loc, 0, " ".join(plural(loc, n) for n in range(PLURAL_SWEEP_N))])
    cases.append({"type": "plural_rules", "name": "CLDR 46 categories for 0..%d" % (PLURAL_SWEEP_N - 1),
                  "sweep": sweep, "points": [[loc, n, plural(loc, n)] for loc in PLURAL_SWEEP_LOCALES
                                             for n in PLURAL_BIG_N],
                  "categories": [[loc, list(plural_categories(loc))] for loc in PLURAL_SWEEP_LOCALES]})
    pts = []
    for loc, key, n, args, clean, words in CLEAN_POINTS:
        if n is None:
            out = tr(CLEAN_TABLES, loc, key, args, clean, words)
        else:
            out = tr_plural(CLEAN_TABLES, loc, key, n, args, clean, words)
        pts.append([loc, key, n, args, clean, words, out])
    cases.append({"type": "tr_clean", "name": "@clean variants per locale, then the word mask (#207)",
                  "tables": CLEAN_TABLES, "points": pts})
    cases.append({"type": "mask_words", "name": "whole words, folded case, same-length grawlix", "grawlix": GRAWLIX,
                  "points": [[text, words, mask_words(text, words)] for text, words in MASK_POINTS]})
    cases.append({"type": "mature_words", "name": "the word list file", "points": [
        [text, mature_words(text)] for text in ('{"words": ["damn", 3, "hell"], "_note": "the game\'s own list"}',
                                                '{"words": []}', "[]", "not json", '{"words": "damn"}', None)]})
    cases.append({"type": "narration", "name": "what a focused control says", "points": [
        [label, role, value, narration_line(label, role, value)] for label, role, value in [
            ("Music volume", "slider", "70 percent"), ("Play", "button", ""), ("Subtitles", "toggle", "on"),
            ("  Window\nmode ", "choice", "Full  screen"), ("", "button", ""), ("Settings", "screen", ""),
            ("Back", "", ""), ("Volume", "slider", "  ")]]})
    cases.append({"type": "pseudo", "name": "pseudo-locale", "points": [
        [t, pseudo(t)] for t in ("Play", "Hello, {name}!", "Score: %d%%", "", "OK", "A long settings label",
                                 "{a}{b}", "50% off")]})
    cases.append(_staging_case("vsync applies without a confirm", [
        ["stage", "vsync", False], ["apply"], ["back"]]))
    cases.append(_staging_case("mode and resolution: applied in order, kept", [
        ["stage", "resolution", [1280, 720]], ["stage", "mode", "fullscreen"], ["apply"],
        ["tick", 0.5], ["tick", 4.0], ["stage", "vsync", False], ["keep"], ["back"]]))
    cases.append(_staging_case("the countdown runs out and reverts", [
        ["stage", "mode", "borderless"], ["stage", "frame_cap", 60], ["apply"], ["tick", 10.0], ["tick", 4.5],
        ["tick", 0.5], ["tick", 1.0]]))
    cases.append(_staging_case("revert and back during the confirm", [
        ["stage", "resolution", [1600, 900]], ["apply"], ["revert"],
        ["stage", "mode", "fullscreen"], ["apply"], ["back"], ["back"]]))
    cases.append(_staging_case("staging the applied value drops it; back warns once, then discards", [
        ["stage", "ui_scale", 1.5], ["stage", "ui_scale", 1.0], ["stage", "vsync", False], ["back"],
        ["stage", "frame_cap", 30], ["back"], ["back"], ["apply"]]))
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "generator": "tools/golden_vectors.py",
            "save_version": SAVE_VERSION, "cases": cases}


def build_telemetry():
    cases = [{"type": "telemetry_format", "name": "header and session id", "header": TELEMETRY_HEADER,
              "session_length": SESSION_LENGTH, "session_chars": SESSION_CHARS}]
    pts = []
    for unix_s, session, event, detail in [
            (0, "00000000", "session_start", "0.1.0"), (951782400, "0a1b2c3d", "screen", "title"),
            (1793628303, "ffffffff", "quit", ""), (1793628303.75, "0a1b2c3d", "level_start", "1-2"),
            (1793628303, "0a1b2c3d", "screen", "title, then menu"), (1793628303, "0a1b2c3d", "note", 'say "hi"'),
            (1793628303, "0a1b2c3d", "note", "two\nlines"), (1793628303, "0a1b2c3d", "note", "cr\rhere"),
            (1793628303, "0a1b2c3d", "crash", "caf\u00e9 \u00cdsla \u201dquoted\u201d")]:
        pts.append([unix_s, session, event, detail, telemetry_row(unix_s, session, event, detail)])
    cases.append({"type": "telemetry_row", "name": "time, quoting and escaping", "points": pts})
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "generator": "tools/golden_vectors.py",
            "cases": cases}


CREDITS_HEADER = ("<!-- Generated by tools/credits.py from docs/ASSET_LOG.md: edit the asset log, not this file. "
                  "-->")                          # what tools/credits.py writes (test_golden_vectors.py checks it)


def build_credits():
    inputs = [
        ("what tools/credits.py writes", "# Credits\n\n" + CREDITS_HEADER + "\n\n## Engine\n\n- Made with an engine\n"),
        ("multi-line comment", "# Credits\n\n<!--\nnotes for the team\n- not a credit\n-->\n\n## Music\n\n"
                               "- Song by Zoë (CC0)\n"),
        ("inline comment", "- Song by Ana <!-- check the license --> (CC-BY 4.0)\n"),
        ("comment starts mid-line", "Art by Ícaro <!-- old\nline -->kept\n"),
        ("two comments on one line", "<!-- a --> \t<!-- b -->\n- B\n"),
        ("comment at the top", "<!-- top -->\n\n# Credits\n"),
        ("no blank line before it", "## Music\n<!-- x -->\n\n- C\n"),
        ("comment after the last line", "- D\n<!-- end -->"),
        ("unclosed comment runs to the end", "## Art\n- E\n<!-- never closed\n- hidden\n"),
        ("CRLF line ends", "# Credits\r\n\r\n<!-- x -->\r\n\r\n- F\r\n"),
        ("no comment, lookalikes kept", "# Credits\n\nNot one: <! -- x --> and -- > and <!- -\n\n\n- G\n"),
        ("empty file", ""),
    ]
    cases = [{"type": "strip_comments", "name": "HTML comments out of CREDITS.md",
              "points": [[name, text, strip_html_comments(text)] for name, text in inputs]}]
    shown = [
        ("what tools/credits.py writes", "# Credits\n\n" + CREDITS_HEADER + "\n\n## Engine\n\n- Made with an engine\n"),
        ("a credits.py row", "# Credits\n\n" + CREDITS_HEADER + "\n\n## Music\n\n- assets/audio/boss_theme.ogg by Zoë "
                             "(license: CC-BY 4.0; source: https://example.org/a_b)\n- Song by Ícaro (license: CC0)\n"),
        ("heading levels", "# One\n## Two\n###### Six\n#\n##   Spaced  \n"),
        ("indented heading and list items", "  ## Indented\n\t- tabbed item\n    * star item\n  + plus item\n"),
        ("a hash inside the text stays", "# Written in C#\n#hashtag stays\nTrack #3\n"),
        ("list markers need a space after them", "-not a list\n+plus\n- \n1. numbered stays\n2) also\n"),
        ("emphasis marks go, underscores stay", "**Bold** and *italic* and ***both***\n- **CC0**: x\n"
                                                "snake_case_file.png and __init__ stay\n"),
        ("a heading or a list item, not both", "# - x\n- # y\n"),
        ("space and tab only", "- Zoë \n\t# Tab heading\t\n # not a heading\n- ”quoted”  \t\n"),
        ("blank lines at the ends go, between paragraphs stay", "\n\n  \n# A\n\n\n- b\n\t\n\n"),
        ("comments go before the marks", "<!-- x -->\n# Credits\n- a <!-- note --> **b**\n<!--\n# hidden\n-->\n"),
        ("only a comment", "<!-- nothing yet -->\n"),
        ("CRLF line ends", "# A\r\n\r\n- b\r\n"),
        ("empty file", ""),
    ]
    cases.append({"type": "credits_text", "name": "CREDITS.md as the credits screen shows it",
                  "points": [[name, text, credits_text(text)] for name, text in shown]})
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "generator": "tools/golden_vectors.py",
            "cases": cases}


# ----------------------------------------------------------------------------------------------- platform services
# The engine-neutral platform layer (#84; docs/PLATFORM.md is the spec, SOP-21 section 4 cites it): achievements,
# stats, rich presence, the overlay's pause hook and the cloud-save hooks, in front of a backend (the null backend
# that records every call, by default; a store adapter such as Steam's later). Self-contained on purpose: it reads
# nothing from the shell's tables above. Every list is ordered (definition order, unlock order, first-save order),
# so no rule depends on the order of a JSON object's keys.
PLATFORM_FORMAT = "platform_state"                   # the local state file's "format"
PLATFORM_STATE_FILE = "platform_state.json"          # in the user-data folder; never synced to the cloud
PLATFORM_STATE_VERSION = 1
PLATFORM_ID_MAX = 64                                 # achievement, stat and presence key names: a letter, then
                                                     # letters, digits and '_' (ASCII), at most 64
STAT_TYPES = ["int", "float"]
PRESENCE_MAX_KEYS = 30                               # Steam's k_cchMaxRichPresenceKeys (verify)
PRESENCE_MAX_VALUE_BYTES = 255                       # UTF-8 bytes; Steam's 256 counts the closing NUL (verify)
CLOUD_MODES = ["auto", "api"]                        # auto: the store syncs the folder (Steam Auto-Cloud, no calls);
                                                     # api: the layer calls cloud_write after every cloud save
CLOUD_LOCAL_NAMES = ["settings.json", PLATFORM_STATE_FILE, "telemetry.csv", "log_tail.txt"]  # machine-specific
CLOUD_LOCAL_SUFFIXES = [".tmp", ".log"]              # half-written saves and logs
CLOUD_LOCAL_DIRS = ["logs", "crashes", "captures"]   # a first folder named so stays on the machine
OVERLAY_PAUSE_SCREENS = ["play"]                     # the overlay opening over these opens the pause menu
_ASCII_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ID_CHARS = _ASCII_LETTERS + "0123456789_"


def platform_id_ok(v):
    """An achievement, stat or presence key name: a string, 1 to 64 ASCII characters, a letter first."""
    return (isinstance(v, str) and 0 < len(v) <= PLATFORM_ID_MAX and v[0] in _ASCII_LETTERS
            and all(c in _ID_CHARS for c in v))


def _num_ok(v):
    """A finite number that is not a boolean (JSON true is not 1 here, in any port)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _whole(v):
    """Integer-valued, judged by the value, never by the type: 5 and 5.0 are the same in JavaScript and Lua."""
    return _num_ok(v) and math.floor(v) == v


def _stat_value(sdef, v):
    """A stat value as every port stores it: an int stat as a whole number, a float stat as a float."""
    return int(v) if sdef["type"] == "int" else float(v)


def _clamp_stat(sdef, v):
    lo, hi = sdef["min"], sdef["max"]
    v = max(v, lo)
    return min(v, hi) if hi is not None else v


def stat_initial(sdef):
    """A stat's value before anything happened: 0, clamped into [min, max]."""
    return _stat_value(sdef, _clamp_stat(sdef, 0))


def achievements_load(text):
    """data/achievements.json -> (definitions, problems), in settings_load's style: a bad entry is dropped and counted,
    the rest still load; no file (None or "") is no achievements and no problems. Shape:
      {"stats": [{"id", "type": "int"|"float" (int), "min" (0), "max" (none), "increment_only" (false)}],
       "achievements": [{"id", "name", "description" (""), "stat" (none), "threshold", "progress_every" (none)}]}
    name and description are localization keys (tr shows the key when a table lacks it, so plain words work too).
    Stats and achievements have their own id namespaces. A bound achievement (stat set) needs a threshold above the
    stat's initial value and at most its max (whole for an int stat); progress_every, if set, is above 0 and below
    the threshold (whole for an int stat)."""
    empty = {"version": PLATFORM_STATE_VERSION, "stats": [], "achievements": []}
    if not text:
        return empty, 0
    try:
        raw = json.loads(text)
    except ValueError:
        return empty, 1
    if not isinstance(raw, dict):
        return empty, 1
    problems = 0
    stats, achievements = [], []
    raw_stats = raw.get("stats", [])
    if not isinstance(raw_stats, list):
        raw_stats, problems = [], problems + 1
    for s in raw_stats:
        ok = isinstance(s, dict) and platform_id_ok(s.get("id")) and all(s.get("id") != t["id"] for t in stats)
        if ok:
            kind = s.get("type", "int")
            lo, hi, inc = s.get("min", 0), s.get("max"), s.get("increment_only", False)
            whole = _whole if kind == "int" else _num_ok
            ok = (kind in STAT_TYPES and whole(lo) and (hi is None or (whole(hi) and hi >= lo))
                  and isinstance(inc, bool))
        if not ok:
            problems += 1
            continue
        conv = int if kind == "int" else float
        stats.append({"id": s["id"], "type": kind, "min": conv(lo), "max": None if hi is None else conv(hi),
                      "increment_only": inc})
    by_id = {s["id"]: s for s in stats}
    raw_ach = raw.get("achievements", [])
    if not isinstance(raw_ach, list):
        raw_ach, problems = [], problems + 1
    for a in raw_ach:
        ok = (isinstance(a, dict) and platform_id_ok(a.get("id")) and all(a.get("id") != b["id"] for b in achievements)
              and isinstance(a.get("name"), str) and a.get("name") != ""
              and isinstance(a.get("description", ""), str))
        stat, threshold, every = (a.get("stat"), a.get("threshold"), a.get("progress_every")) if ok else (None,) * 3
        if ok and stat is not None:
            sdef = by_id.get(stat) if isinstance(stat, str) else None
            whole = _whole if sdef and sdef["type"] == "int" else _num_ok
            ok = (sdef is not None and whole(threshold) and threshold > stat_initial(sdef)
                  and (sdef["max"] is None or threshold <= sdef["max"])
                  and (every is None or (whole(every) and 0 < every < threshold)))
        elif ok:
            ok = threshold is None and every is None          # a threshold without a stat is a mistake
        if not ok:
            problems += 1
            continue
        sdef = by_id.get(stat)
        achievements.append({"id": a["id"], "name": a["name"], "description": a.get("description", ""),
                             "stat": stat, "threshold": None if stat is None else _stat_value(sdef, threshold),
                             "progress_every": None if every is None else _stat_value(sdef, every)})
    return {"version": PLATFORM_STATE_VERSION, "stats": stats, "achievements": achievements}, problems


def cloud_partition(path):
    """Which of the user-data folder's files sync to the cloud: "cloud" or "local". path is relative to that folder
    ('/' or '\\'), compared without case. Local: settings.json (the display settings belong to this machine, E79), the
    platform layer's own state, telemetry and logs, half-written *.tmp, and a first folder named logs, crashes or
    captures. Everything else (the save slots and their .bak) is "cloud"."""
    folded = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in path)   # ASCII only, in every port
    parts = [p for p in folded.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return "local"
    name = parts[-1]
    if (len(parts) > 1 and parts[0] in CLOUD_LOCAL_DIRS) or name in CLOUD_LOCAL_NAMES \
            or any(name.endswith(s) for s in CLOUD_LOCAL_SUFFIXES):
        return "local"
    return "cloud"


def overlay_action(active, screen):
    """The store overlay opened (active) or closed: "pause" opens the pause menu, "none" does nothing. Opening over
    gameplay pauses (as focus loss does, SOP-19 section 6); closing never resumes: the player resumes from the pause
    menu, which is still open."""
    return "pause" if active and screen in OVERLAY_PAUSE_SCREENS else "none"


def _utf8_len(text):
    return len(text.encode("utf-8"))


class Platform:
    """The platform layer's game-facing half (#84). Every operation returns (out, calls): calls are what it sent to
    the backend during that operation, in order, as lists ([name, args...]). The rules:
    - unlock(id): "unknown", "already" (no call, ever: an achievement unlocks once), or "unlocked": it is unlocked
      locally at once and, online, flushed at once (so the store's popup shows).
    - set_stat(id, v) / add_stat(id, d): "unknown"; "refused" (not a finite number, not whole for an int stat, or
      lower than now on an increment_only stat: the value stays); "same" (no change, nothing pending); "ok" or
      "clamped" (into [min, max]). A change is pending until a flush. Every achievement bound to the stat whose
      threshold the new value reaches unlocks, in definition order; online, a bound achievement whose progress_every
      step the value just crossed (and whose threshold it did not reach) sends indicate_progress at once. Stats wait
      for flush() (level end, pause, quit) unless an unlock flushed them.
    - flush(): "offline" (kept), "nothing", "sent" or "failed". Sends set_stat for every pending stat (definition
      order, the latest value only), set_achievement for every pending unlock (unlock order), one store_stats, then
      cloud_write for every pending cloud file (first-save order). The pending lists clear only when store_stats
      succeeds; a failed store keeps them all and the layer goes offline until connect().
    - set_presence(key, value): "refused" (a bad key, a value that is not a string or longer than 255 UTF-8 bytes,
      a 31st key), "same" (unchanged: nothing is resent) or "ok". "" removes the key. Sent at once when online;
      offline only the map changes, and connect() sends the map as it is then, keys sorted, never the history.
      clear_presence(): "same" when empty, else "ok" and clear_presence when online.
    - saved(path): after the game wrote a file (SOP-19's atomic write done): its cloud_partition. In "api" cloud mode
      a cloud file is cloud_write now (online) or queued once (offline); "auto" mode sends nothing.
    - connect(remote): the backend came (back): remote unlocks join the local ones without a call (dropped from
      pending); a remote stat replaces the local one unless a local change is pending, and on an increment_only stat
      the larger wins (pending drops when the remote is at least as far); bound achievements are checked again
      (no progress popups here); then flush() and the presence map. disconnect(): offline.
    - reset_all(): testing only; "offline" (refused: a reset is never queued), else everything back to the initial
      values, the pending lists emptied, reset_all_stats sent."""

    def __init__(self, defs, online=False, cloud="auto"):
        self.defs = defs
        self.stat_defs = {s["id"]: s for s in defs["stats"]}
        self.ach_defs = {a["id"]: a for a in defs["achievements"]}
        self.online = online
        self.cloud = cloud
        self.store_failures = 0                      # the null backend's test hook: fail the next N store_stats
        self.presence = {}
        self._reset_local()

    def _reset_local(self):
        self.unlocked = []
        self.stats = {s["id"]: stat_initial(s) for s in self.defs["stats"]}
        self.pending_stats, self.pending_unlocks, self.pending_cloud = [], [], []

    # --- what ports compare after every step
    def state(self):
        return {"format": PLATFORM_FORMAT, "version": PLATFORM_STATE_VERSION, "unlocked": list(self.unlocked),
                "stats": dict(self.stats), "pending": {"stats": [s["id"] for s in self.defs["stats"]
                                                                 if s["id"] in self.pending_stats],
                                                       "unlocks": list(self.pending_unlocks),
                                                       "cloud": list(self.pending_cloud)}}

    # --- achievements and stats
    def _unlock_local(self, aid):
        self.unlocked.append(aid)
        self.pending_unlocks.append(aid)

    def unlock(self, aid):
        if aid not in self.ach_defs:
            return "unknown", []
        if aid in self.unlocked:
            return "already", []
        self._unlock_local(aid)
        return "unlocked", (self.flush()[1] if self.online else [])

    def _check(self, sid, old, new, notify, calls):
        """Unlock what the new value reaches; online and notify: progress popups for steps just crossed."""
        unlocked = False
        for a in self.defs["achievements"]:
            if a["stat"] != sid or a["id"] in self.unlocked:
                continue
            if new >= a["threshold"]:
                self._unlock_local(a["id"])
                unlocked = True
            elif notify and self.online and a["progress_every"] is not None \
                    and math.floor(new / a["progress_every"]) > math.floor(old / a["progress_every"]):
                calls.append(["indicate_progress", a["id"], new, a["threshold"]])
        return unlocked

    def set_stat(self, sid, v):
        sdef = self.stat_defs.get(sid)
        if sdef is None:
            return "unknown", []
        if not _num_ok(v) or (sdef["type"] == "int" and not _whole(v)):
            return "refused", []
        c = _stat_value(sdef, _clamp_stat(sdef, v))
        old = self.stats[sid]
        if sdef["increment_only"] and c < old:
            return "refused", []
        if c == old:
            return "same", []
        self.stats[sid] = c
        if sid not in self.pending_stats:
            self.pending_stats.append(sid)
        calls = []
        if self._check(sid, old, c, True, calls) and self.online:
            calls += self.flush()[1]
        return ("clamped" if c != v else "ok"), calls

    def add_stat(self, sid, d):
        sdef = self.stat_defs.get(sid)
        if sdef is None:
            return "unknown", []
        if not _num_ok(d) or (sdef["type"] == "int" and not _whole(d)):
            return "refused", []
        return self.set_stat(sid, self.stats[sid] + d)

    def flush(self):
        if not self.online:
            return "offline", []
        if not (self.pending_stats or self.pending_unlocks or self.pending_cloud):
            return "nothing", []
        calls = []
        if self.pending_stats or self.pending_unlocks:
            calls += [["set_stat", s["id"], self.stats[s["id"]]] for s in self.defs["stats"]
                      if s["id"] in self.pending_stats]
            calls += [["set_achievement", aid] for aid in self.pending_unlocks]
            calls.append(["store_stats"])
            if self.store_failures > 0:              # the store said no: keep everything, wait for connect()
                self.store_failures -= 1
                self.online = False
                return "failed", calls
            self.pending_stats, self.pending_unlocks = [], []
        calls += [["cloud_write", p] for p in self.pending_cloud]
        self.pending_cloud = []
        return "sent", calls

    # --- rich presence
    def set_presence(self, key, value):
        if not platform_id_ok(key) or not isinstance(value, str) or _utf8_len(value) > PRESENCE_MAX_VALUE_BYTES:
            return "refused", []
        if value == "":
            if key not in self.presence:
                return "same", []
            del self.presence[key]
        else:
            if self.presence.get(key) == value:
                return "same", []
            if key not in self.presence and len(self.presence) >= PRESENCE_MAX_KEYS:
                return "refused", []
            self.presence[key] = value
        return "ok", ([["set_presence", key, value]] if self.online else [])

    def clear_presence(self):
        if not self.presence:
            return "same", []
        self.presence = {}
        return "ok", ([["clear_presence"]] if self.online else [])

    # --- cloud saves
    def saved(self, path):
        part = cloud_partition(path)
        calls = []
        if part == "cloud" and self.cloud == "api":
            if self.online:
                calls.append(["cloud_write", path])
            elif path not in self.pending_cloud:
                self.pending_cloud.append(path)
        return part, calls

    # --- the backend coming and going
    def connect(self, remote):
        self.online = True
        for aid in remote.get("unlocked", []):
            if aid in self.ach_defs and aid not in self.unlocked:
                self.unlocked.append(aid)
            if aid in self.pending_unlocks:
                self.pending_unlocks.remove(aid)
        rstats = remote.get("stats", {})
        for s in self.defs["stats"]:
            sid = s["id"]
            r = rstats.get(sid)
            if not _num_ok(r) or (s["type"] == "int" and not _whole(r)):
                continue
            r = _stat_value(s, _clamp_stat(s, r))
            old = self.stats[sid]
            if s["increment_only"]:
                if r >= old and sid in self.pending_stats:
                    self.pending_stats.remove(sid)
                new = max(old, r)
            else:
                new = old if sid in self.pending_stats else r
            self.stats[sid] = new
            self._check(sid, old, new, False, [])
        calls = self.flush()[1]
        if self.online:                              # a failed store on the way back leaves presence for later
            calls += [["set_presence", k, self.presence[k]] for k in sorted(self.presence)]
        return ("online" if self.online else "failed"), calls

    def disconnect(self):
        self.online = False
        return "offline", []

    def reset_all(self):
        if not self.online:
            return "offline", []
        self._reset_local()
        return "reset", [["reset_all_stats", True]]


class NullBackend:
    """The backend every game runs by default (#84): it accepts every call, keeps them in order in `calls` (what
    would have been sent), and keeps what a store would hold, so remote() can be handed to Platform.connect.
    set_stat and set_achievement are staged and land in the stored copy only at store_stats (E78: SetAchievement,
    then StoreStats); fail_stores makes the next N store_stats fail, and a failed store lands nothing. send()
    returns whether the call succeeded (only store_stats can fail)."""

    def __init__(self):
        self.calls = []
        self.unlocked, self.stats = [], {}
        self.staged_unlocks, self.staged_stats = [], {}
        self.presence, self.cloud = {}, []
        self.fail_stores = 0

    def send(self, call):
        self.calls.append(list(call))
        name, args = call[0], call[1:]
        if name == "set_achievement":
            if args[0] not in self.staged_unlocks:
                self.staged_unlocks.append(args[0])
        elif name == "set_stat":
            self.staged_stats[args[0]] = args[1]
        elif name == "store_stats":
            if self.fail_stores > 0:
                self.fail_stores -= 1
                return False
            self.unlocked += [a for a in self.staged_unlocks if a not in self.unlocked]
            self.stats.update(self.staged_stats)
            self.staged_unlocks, self.staged_stats = [], {}
        elif name == "reset_all_stats":
            self.unlocked, self.stats, self.staged_unlocks, self.staged_stats = [], {}, [], {}
        elif name == "set_presence":
            if args[1] == "":
                self.presence.pop(args[0], None)
            else:
                self.presence[args[0]] = args[1]
        elif name == "clear_presence":
            self.presence = {}
        elif name == "cloud_write" and args[0] not in self.cloud:
            self.cloud.append(args[0])
        return True

    def remote(self):
        """What connect() gets: the stored unlocks (in the order stored) and stats."""
        return {"unlocked": list(self.unlocked), "stats": dict(self.stats)}


def platform_state_load(defs, text):
    """platform_state.json -> (state, problems). No file: the initial state, no problems. Not JSON, not an object,
    another format or another version: the initial state and 1 problem (the store's own copy is the truth; the
    queue is rebuilt from play). Otherwise every entry that does not fit the definitions is dropped and counted:
    an unknown or repeated unlock, an unknown stat or a value that is not a number (not whole for an int stat;
    out of range is clamped, not counted), a pending id that is unknown, repeated or (for an unlock) not unlocked,
    a pending cloud path that is not a string or not a cloud file."""
    p = Platform(defs)
    if not text:
        return p.state(), 0
    try:
        raw = json.loads(text)
    except ValueError:
        return p.state(), 1
    if not isinstance(raw, dict) or raw.get("format") != PLATFORM_FORMAT or \
            raw.get("version") != PLATFORM_STATE_VERSION:
        return p.state(), 1
    problems = 0

    def items(v, kind):
        nonlocal problems
        if isinstance(v, kind):
            return v
        if v is not None:
            problems += 1
        return kind()
    for aid in items(raw.get("unlocked"), list):
        if isinstance(aid, str) and aid in p.ach_defs and aid not in p.unlocked:
            p.unlocked.append(aid)
        else:
            problems += 1
    for sid, v in items(raw.get("stats"), dict).items():
        sdef = p.stat_defs.get(sid)
        if sdef is None or not _num_ok(v) or (sdef["type"] == "int" and not _whole(v)):
            problems += 1
            continue
        p.stats[sid] = _stat_value(sdef, _clamp_stat(sdef, v))
    pending = items(raw.get("pending"), dict)
    for sid in items(pending.get("stats"), list):
        if isinstance(sid, str) and sid in p.stat_defs and sid not in p.pending_stats:
            p.pending_stats.append(sid)
        else:
            problems += 1
    for aid in items(pending.get("unlocks"), list):
        if isinstance(aid, str) and aid in p.unlocked and aid not in p.pending_unlocks:
            p.pending_unlocks.append(aid)
        else:
            problems += 1
    for path in items(pending.get("cloud"), list):
        if isinstance(path, str) and cloud_partition(path) == "cloud" and path not in p.pending_cloud:
            p.pending_cloud.append(path)
        else:
            problems += 1
    return p.state(), problems


SAMPLE_ACHIEVEMENTS = {
    "stats": [{"id": "enemies_defeated", "type": "int", "min": 0, "max": 1000000, "increment_only": True},
              {"id": "coins", "type": "int", "max": 999},
              {"id": "best_time_s", "type": "float", "min": 0, "max": 3600}],
    "achievements": [{"id": "first_win", "name": "ach_first_win", "description": "ach_first_win_desc"},
                     {"id": "defeat_1", "name": "ach_defeat_1", "stat": "enemies_defeated", "threshold": 1},
                     {"id": "defeat_100", "name": "ach_defeat_100", "stat": "enemies_defeated", "threshold": 100,
                      "progress_every": 25},
                     {"id": "coins_500", "name": "ach_coins_500", "stat": "coins", "threshold": 500}]}


def _platform_case(name, script, online=False, cloud="auto", defs=None):
    """Run a script of [op, args...] steps; record each step's out, its backend calls and the state after it."""
    defs = defs or achievements_load(json.dumps(SAMPLE_ACHIEVEMENTS))[0]
    p = Platform(defs, online=online, cloud=cloud)
    steps = []
    for op in script:
        kind, args = op[0], op[1:]
        if kind == "fail_store":                     # the null backend's hook: its next store_stats fails
            p.store_failures += 1
            out, calls = None, []
        elif kind == "overlay":
            out, calls = overlay_action(*args), []
        else:
            out, calls = getattr(p, kind)(*args)
        steps.append({"op": op, "out": out, "calls": calls, "state": p.state(),
                      "presence": [[k, p.presence[k]] for k in sorted(p.presence)], "online": p.online})
    return {"type": "platform_script", "name": name, "defs": defs, "online": online, "cloud": cloud, "steps": steps}


def build_platform():
    cases = [{"type": "platform_format", "name": "names and limits", "state_format": PLATFORM_FORMAT,
              "state_file": PLATFORM_STATE_FILE, "state_version": PLATFORM_STATE_VERSION, "id_max": PLATFORM_ID_MAX,
              "stat_types": STAT_TYPES, "presence_max_keys": PRESENCE_MAX_KEYS,
              "presence_max_value_bytes": PRESENCE_MAX_VALUE_BYTES, "cloud_modes": CLOUD_MODES,
              "cloud_local_names": CLOUD_LOCAL_NAMES, "cloud_local_suffixes": CLOUD_LOCAL_SUFFIXES,
              "cloud_local_dirs": CLOUD_LOCAL_DIRS, "overlay_pause_screens": OVERLAY_PAUSE_SCREENS}]
    sample = json.dumps(SAMPLE_ACHIEVEMENTS)
    loads = [
        ("the sample", sample),
        ("no file", None),
        ("empty file", ""),
        ("not json", "{achievements"),
        ("not an object", "[1, 2]"),
        ("only achievements, no stats", '{"achievements": [{"id": "win", "name": "Win"}]}'),
        ("defaults filled in", '{"stats": [{"id": "s"}], "achievements": [{"id": "a", "name": "A", "stat": "s", '
                               '"threshold": 3}]}'),
        ("a whole float is an int", '{"stats": [{"id": "s", "min": 0.0, "max": 10.0}], "achievements": '
                                    '[{"id": "a", "name": "A", "stat": "s", "threshold": 5.0, '
                                    '"progress_every": 2.0}]}'),
        ("bad stats dropped and counted",
         '{"stats": [{"id": "ok"}, {"id": "ok"}, {"id": "9lives"}, {"id": "x y"}, {"id": "t", "type": "double"}, '
         '{"id": "u", "min": 5, "max": 1}, {"id": "v", "min": 0.5}, {"id": "w", "increment_only": 1}, '
         '{"id": "f", "type": "float", "min": -1.5, "max": 2.25}, "s", {"id": "' + "s" * 65 + '"}]}'),
        ("bad achievements dropped and counted",
         '{"stats": [{"id": "s", "max": 10}, {"id": "g", "type": "float", "max": 1}], "achievements": ['
         '{"id": "a", "name": "A"}, {"id": "a", "name": "A again"}, {"id": "b"}, {"id": "c", "name": ""}, '
         '{"id": "d", "name": "D", "stat": "nope", "threshold": 1}, {"id": "e", "name": "E", "stat": "s"}, '
         '{"id": "f", "name": "F", "stat": "s", "threshold": 0}, '
         '{"id": "h", "name": "H", "stat": "s", "threshold": 11}, '
         '{"id": "i", "name": "I", "stat": "s", "threshold": 2.5}, {"id": "j", "name": "J", "threshold": 3}, '
         '{"id": "k", "name": "K", "stat": "s", "threshold": 4, "progress_every": 4}, '
         '{"id": "m", "name": "M", "stat": "g", "threshold": 0.5, "progress_every": 0.25}, '
         '{"id": "n", "name": "N", "description": 7}, {"id": "o", "name": "O", "stat": "s", "threshold": true}]}'),
        ("stats and achievements not lists", '{"stats": {"id": "s"}, "achievements": "none"}'),
    ]
    pts = []
    for name, text in loads:
        defs, problems = achievements_load(text)
        pts.append([name, text, defs, problems])
    cases.append({"type": "achievements_load", "name": "data/achievements.json as every port reads it", "points": pts})
    cases.append({"type": "cloud_partition", "name": "which user-data files sync", "points": [
        [path, cloud_partition(path)] for path in [
            "save_1.json", "save_1.json.bak", "save_1.json.tmp", "slots/2.save", "settings.json", "Settings.JSON",
            "platform_state.json", "telemetry.csv", "log_tail.txt", "game.log", "logs/today.txt", "crashes/1.txt",
            "captures/a.png", "sub/logs/x.txt", "saves\\slot_3.json", "./save_2.json", "", "notes/settings.json",
            "LOGS/A.TXT", "Ärger/save.json", "SpeicherstÄnde/GAME.LOG"]]})
    cases.append({"type": "overlay", "name": "the overlay's pause hook", "points": [
        [active, screen, overlay_action(active, screen)]
        for active in (True, False) for screen in ("play", "pause", "menu", "title", "settings")]})
    cases.append(_platform_case("an achievement unlocks once and flushes at once", [
        ["unlock", "first_win"], ["unlock", "first_win"], ["unlock", "no_such"], ["flush"]], online=True))
    cases.append(_platform_case("stats wait for a flush; thresholds unlock in definition order", [
        ["add_stat", "enemies_defeated", 0], ["set_stat", "coins", 120], ["flush"], ["flush"],
        ["add_stat", "enemies_defeated", 30], ["add_stat", "enemies_defeated", 20], ["add_stat", "enemies_defeated", 1],
        ["set_stat", "enemies_defeated", 100], ["add_stat", "enemies_defeated", 5]], online=True))
    cases.append(_platform_case("refused, clamped and same", [
        ["set_stat", "enemies_defeated", 10], ["set_stat", "enemies_defeated", 9], ["add_stat", "enemies_defeated", -1],
        ["set_stat", "enemies_defeated", 2.5], ["set_stat", "enemies_defeated", "11"],
        ["set_stat", "enemies_defeated", True],
        ["set_stat", "enemies_defeated", 10.0], ["set_stat", "coins", 5000], ["set_stat", "coins", -3],
        ["add_stat", "coins", 0.5], ["set_stat", "best_time_s", 61.25], ["set_stat", "best_time_s", 59],
        ["set_stat", "best_time_s", 9999.5], ["set_stat", "nope", 1], ["add_stat", "nope", 1], ["flush"]],
        online=True))
    cases.append(_platform_case("offline: local at once, one replay when the backend returns", [
        ["unlock", "first_win"], ["add_stat", "enemies_defeated", 1], ["add_stat", "enemies_defeated", 60],
        ["set_stat", "coins", 40], ["set_stat", "coins", 30], ["flush"], ["set_presence", "status", "In the crypt"],
        ["connect", {"unlocked": [], "stats": {}}], ["flush"]]))
    cases.append(_platform_case("a failed store keeps the queue and waits for connect", [
        ["set_stat", "coins", 7], ["fail_store"], ["flush"], ["set_stat", "coins", 8], ["unlock", "first_win"],
        ["flush"], ["connect", {}], ["disconnect"], ["set_presence", "status", "Back"], ["set_stat", "coins", 9],
        ["fail_store"], ["connect", {}], ["connect", {}]], online=True))
    cases.append(_platform_case("connect merges what the store already has", [
        ["add_stat", "enemies_defeated", 40], ["set_stat", "coins", 300], ["unlock", "first_win"],
        ["connect", {"unlocked": ["first_win", "defeat_1", "not_ours"],
                     "stats": {"enemies_defeated": 120, "coins": 999, "best_time_s": 42.5}}],
        ["disconnect"], ["add_stat", "enemies_defeated", 5],
        ["connect", {"unlocked": ["first_win", "defeat_1", "defeat_100"],
                     "stats": {"enemies_defeated": 150, "coins": "lots", "best_time_s": 30}}]]))
    cases.append(_platform_case("rich presence: limits, no resend, the map on reconnect", [
        ["set_presence", "status", "Title screen"], ["set_presence", "status", "Title screen"],
        ["set_presence", "status", "Level 2"], ["set_presence", "level", "2"], ["set_presence", "level", ""],
        ["set_presence", "level", ""], ["set_presence", "bad key", "x"], ["set_presence", "note", "x" * 256],
        ["set_presence", "note", "é" * 128], ["set_presence", "note", "é" * 127 + "a"],
        ["set_presence", "count", 3], ["disconnect"], ["set_presence", "status", "Level 3"],
        ["set_presence", "boss", "Lich"], ["clear_presence"], ["set_presence", "zone", "Crypt"],
        ["set_presence", "act", "1"], ["connect", {}], ["clear_presence"], ["clear_presence"]], online=True))
    cases.append(_platform_case("thirty presence keys and no more", [
        *[["set_presence", "k%02d" % i, "v"] for i in range(PRESENCE_MAX_KEYS)], ["set_presence", "k99", "v"],
        ["set_presence", "k00", "w"], ["set_presence", "k00", ""], ["set_presence", "k99", "v"]], online=True))
    cases.append(_platform_case("cloud hooks in api mode", [
        ["saved", "save_1.json"], ["saved", "settings.json"], ["saved", "save_1.json.tmp"], ["disconnect"],
        ["saved", "save_1.json"], ["saved", "save_2.json"], ["saved", "save_1.json"], ["saved", "logs/x.log"],
        ["connect", {}], ["saved", "save_2.json"]], online=True, cloud="api"))
    cases.append(_platform_case("cloud hooks in auto mode send nothing", [
        ["saved", "save_1.json"], ["saved", "settings.json"], ["disconnect"], ["saved", "save_1.json"],
        ["connect", {}]], online=True, cloud="auto"))
    cases.append(_platform_case("the overlay pauses gameplay only", [
        ["overlay", True, "play"], ["overlay", False, "pause"], ["overlay", True, "menu"]], online=True))
    cases.append(_platform_case("reset is for testing and never queued", [
        ["add_stat", "enemies_defeated", 3], ["unlock", "first_win"], ["reset_all"], ["disconnect"],
        ["set_stat", "coins", 5], ["reset_all"]], online=True))
    cases.append(_platform_case("no achievements file: every call is unknown", [
        ["unlock", "first_win"], ["set_stat", "coins", 1], ["flush"], ["set_presence", "status", "ok"]],
        online=True, defs=achievements_load(None)[0]))
    defs = achievements_load(sample)[0]
    good = Platform(defs)
    good.unlock("first_win")
    good.add_stat("enemies_defeated", 7)
    good.saved("save_1.json")
    good.cloud = "api"
    good.saved("save_2.json")
    states = [
        ("no file", None), ("empty file", ""), ("not json", "{"), ("not an object", '"state"'),
        ("another format", json.dumps({"format": "save", "version": 1})),
        ("a newer version", json.dumps({"format": PLATFORM_FORMAT, "version": 2, "unlocked": ["first_win"]})),
        ("what dump wrote", json.dumps(good.state())),
        ("entries that do not fit are dropped", json.dumps({
            "format": PLATFORM_FORMAT, "version": 1, "unlocked": ["first_win", "first_win", "gone", 3],
            "stats": {"enemies_defeated": 12, "coins": 2.5, "best_time_s": 5000, "gone": 1, "best": "x"},
            "pending": {"stats": ["coins", "coins", "gone"], "unlocks": ["first_win", "defeat_1"],
                        "cloud": ["save_1.json", "settings.json", 4, "save_1.json"]}})),
        ("wrong shapes", json.dumps({"format": PLATFORM_FORMAT, "version": 1, "unlocked": "first_win",
                                     "stats": [1], "pending": {"stats": {}, "unlocks": None}})),
    ]
    cases.append({"type": "platform_state_load", "name": "platform_state.json as every port reads it",
                  "defs": defs, "points": [[name, text, *platform_state_load(defs, text)] for name, text in states]})
    nb = NullBackend()
    sends = []
    for call in [["set_stat", "coins", 5], ["set_achievement", "first_win"], ["store_stats"],
                 ["set_stat", "coins", 9], ["set_achievement", "defeat_1"], ["fail_next_store"], ["store_stats"],
                 ["set_stat", "enemies_defeated", 3], ["store_stats"], ["set_presence", "status", "Menu"],
                 ["set_presence", "level", "2"], ["set_presence", "status", ""], ["cloud_write", "save_1.json"],
                 ["cloud_write", "save_1.json"], ["reset_all_stats", True], ["clear_presence"]]:
        if call == ["fail_next_store"]:          # the test hook, not a call: ok is null and calls skip it
            nb.fail_stores += 1
            ok = None
        else:
            ok = nb.send(call)
        sends.append([call, ok, nb.remote(), [[k, nb.presence[k]] for k in sorted(nb.presence)], list(nb.cloud)])
    cases.append({"type": "null_backend", "name": "the null backend keeps what a store would hold",
                  "sends": sends, "calls": nb.calls})
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "generator": "tools/golden_vectors.py",
            "cases": cases}


def render(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reference logic and golden vectors for the engine ports.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="exit 1 if data/golden/*.json differ from this reference")
    g.add_argument("--write", action="store_true", help="rewrite data/golden/*.json")
    g.add_argument("--show", metavar="TYPE", help="print the cases of one type (shake, settings_load, ...)")
    ap.add_argument("--out", default=str(OUT_DIR), help="folder for the JSON files (default data/golden)")
    args = ap.parse_args(argv)
    files = {"juice.json": render(build_juice()), "shell.json": render(build_shell()),
             "telemetry.json": render(build_telemetry()), "credits.json": render(build_credits())}
    files["platform.json"] = render(build_platform())     # the platform layer (#84): its own line, its own file
    out = Path(args.out)
    if args.show:
        for text in files.values():
            for case in json.loads(text)["cases"]:
                if case["type"] == args.show:
                    print(json.dumps(case, indent=1, ensure_ascii=False))
        return 0
    if args.write:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / name).write_bytes(text.encode("utf-8"))
            print(f"[ OK ] wrote {out / name}")
        return 0
    stale = [n for n, t in files.items() if not (out / n).exists() or (out / n).read_bytes() != t.encode("utf-8")]
    for n in files:
        print(f"[{'FAIL' if n in stale else ' OK '}] {n}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
