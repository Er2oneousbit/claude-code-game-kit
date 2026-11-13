#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# golden_vectors.py
# Purpose : The reference implementation of the kit's engine-free game logic (juice: screen shake, hitstop, easing,
#           camera follow, input buffer, coyote time, spring, flash limiter; shell: settings, save migration,
#           rebinding, button glyphs, localization, pseudo-locale; telemetry: the CSV columns and row format; credits:
#           HTML comments out of CREDITS.md, then the text every credits screen shows) and the writer of the
#           golden-vector files every engine port is tested against: data/golden/juice.json, data/golden/shell.json,
#           data/golden/telemetry.json (only the ports that
#           write telemetry.csv read it) and data/golden/credits.json (only the ports with a credits screen read it).
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


def tr(tables, locale, key, args=None):
    """A string through the fallback chain (fr-CA -> fr -> en); a missing key returns the key itself, so it shows.
    Argument values are whole numbers or strings: format a float yourself before passing it (languages print 2.0
    differently), and count text in code points, not UTF-16 units."""
    for loc in locale_chain(locale):
        table = tables.get(loc, {})
        if key in table:
            return _fill(table[key], args or {})
    return key


def plural(locale, n):
    base = locale.split("-")[0].split("_")[0]
    if base in ("ja", "zh", "ko"):
        return "other"
    if base == "fr":
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


def tr_plural(tables, locale, key, n, args=None):
    a = dict(args or {})
    a["n"] = n
    return tr(tables, locale, key + "." + plural(locale, n), a)


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
    result as a code-unit one. Every port runs this before its own markdown handling (heading marks and so on)."""
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
    return {"version": VECTOR_VERSION, "tolerance": TOLERANCE, "generator": "tools/golden_vectors.py",
            "cases": cases}


TABLES = {
    "en": {"menu.play": "Play", "menu.settings": "Settings", "greet": "Hello, {name}!",
           "apples.one": "{n} apple", "apples.other": "{n} apples", "only.en": "English only"},
    "fr": {"menu.play": "Jouer", "greet": "Bonjour, {name} !", "apples.one": "{n} pomme", "apples.other": "{n} pommes"},
    "fr-CA": {"menu.play": "Jouer!"},
    "ja": {"menu.play": "プレイ", "apples.other": "りんご{n}個"},
}


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
    ]
    for name, text in inputs:
        s, problems = settings_load(text)
        cases.append({"type": "settings_load", "name": name, "input": text, "expect": s,
                      "problems": len(problems), "effective_shake": effective_shake(s),
                      "telemetry_allowed": telemetry_allowed(s)})
    s, _ = settings_load(json.dumps({"telemetry": {"consent": "yes"}}))
    cases.append({"type": "settings_load", "name": "consent given", "input": json.dumps({"telemetry": {"consent": "yes"}}),
                  "expect": s, "problems": 0, "effective_shake": effective_shake(s), "telemetry_allowed": True})
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
    cases.append({"type": "narration", "name": "what a focused control says", "points": [
        [label, role, value, narration_line(label, role, value)] for label, role, value in [
            ("Music volume", "slider", "70 percent"), ("Play", "button", ""), ("Subtitles", "toggle", "on"),
            ("  Window\nmode ", "choice", "Full  screen"), ("", "button", ""), ("Settings", "screen", ""),
            ("Back", "", ""), ("Volume", "slider", "  ")]]})
    cases.append({"type": "pseudo", "name": "pseudo-locale", "points": [
        [t, pseudo(t)] for t in ("Play", "Hello, {name}!", "Score: %d%%", "", "OK", "A long settings label",
                                 "{a}{b}", "50% off")]})
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
