#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# build_showcase.py
# Purpose : Rebuilds the Wavesmith showcase in this folder: the sounds made from code, the adaptive music as an engine
#           plays it, the dialogue with its typewriter and subtitles, the before / after loudness charts and the
#           whole-mix check. Every sound comes from a Wavesmith command (printed as it runs) or from the OGG sources
#           in media/ (voices from Qwen3-TTS, two ElevenLabs effects; README.md has the commands that made them).
#           This script only places sounds in time, mixes them and draws the pictures.
# Usage   : python workflows/wavesmith-showcase/build_showcase.py                  # everything, about 2 minutes
#           python workflows/wavesmith-showcase/build_showcase.py --only music     # code | music | dialogue | mix
#           python workflows/wavesmith-showcase/build_showcase.py --export-sources # also write code-made OGGs to media/
#           Options: --work DIR (default build/ next to this script, gitignored), --debug
# Needs   : Python 3.8+, numpy and Pillow (for the pictures), ffmpeg on PATH (decoding, OGG, MP4)
# Exit    : 0 ok, 1 a step failed, 2 environment or usage
# Notes   : Music follows data/music.json through music.py's plan(), the reference every engine's music player
#           matches, and mixes stems the way the web player does (one looping source per stem, a stem gain, a track
#           gain that fades on a transition, a stinger at the switch). Ducking under dialogue comes from
#           audio_events.py's Director, the typewriter from dialogue.py's reveal_count(), the subtitles from the
#           WebVTT file `dialogue export` writes. Loudness numbers come from `loudness measure --json` and
#           `loudness check-mix`; the chart's momentary and short-term curves use loudness.py's own BS.1770 blocks.
#           The level steps on the mix chart are this script's reading of the short-term curve at the scene's
#           changes (SCENE_STEPS). Video audio is normalized to VIDEO_LUFS so the clips play at one level.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   code:     synth presets (and seeds) + chiptune chase -> place in time -> normalize -> sheet PNG + MP4
#   music:    chiptune stems -> music validate -> game script (start, layer, request chase, request explore)
#             -> plan() for each request -> mix stems per voice (loop wrap, stem gains, fades, stinger) -> PNG + MP4
#   dialogue: OGG voices -> babble line -> dialogue build / lint / export vtt -> place lines + rain + door
#             -> Director: door play + ducking every 10 ms -> mix -> typewriter, subtitles, caption -> PNG + MP4
#   mix:      every asset -> measure (before) -> normalize --bus -> measure (after) -> chart
#             a 60 s scene twice (raw assets, then house levels + ducking) -> check-mix both -> chart
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import traceback
import wave
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
WS_DIR = KIT / "core" / "tools" / "audio" / "wavesmith"
WAVESMITH = WS_DIR / "wavesmith.py"
SRC = HERE / "src"
MEDIA = HERE / "media"
sys.path.insert(0, str(WS_DIR))

# ---- Tunables ------------------------------------------------------------------------------------------------------
RATE = 44100                   # every mix runs at this rate
FPS = 30
VW, VH = 1280, 720             # video frame
CRF = 30                       # H.264 quality (higher = smaller); the frames are mostly static
AAC_KBPS = 96
VIDEO_LUFS = -16.0             # every clip's audio, so the videos play at one level
MIX_SECONDS = 60.0             # the whole-mix scene
SCENE_STEPS = [(12.0, "music comes in"), (35.0, "dialogue starts")]   # mix chart: the level step at each
QUIET_AREA = (0.5, 11.5)       # mix chart: how far the pickups' momentary peaks stand over the rain bed here
CLIP_LEVEL = 0.999             # a sample at or above this is clipped in the 16-bit "before" capture
SFX_PLAN = [                   # (label, preset, seed or None): the code-made sound sheet, in play order
    ("jump", "jump", None), ("jump --seed 1", "jump", 1), ("jump --seed 2", "jump", 2),
    ("coin", "coin", None), ("pickup", "pickup", None), ("hit", "hit", None), ("laser", "laser", None),
    ("land", "land", None), ("fall", "fall", None), ("explosion", "explosion", None), ("blip", "blip", None),
]
SFX_GAP_S = 0.55               # silence between sheet sounds in the code clip
MUSIC_SCRIPT = [               # (time s, action, argument): what a game asks of its music player
    (0.0, "start", "explore"), (0.0, "stem", ("drums", 0.0)),
    (5.3, "layer", ("drums", 0.7)),             # tension: the drums layer comes in on the next bar
    (12.4, "request", "chase"),
    (21.3, "request", "explore"),
]
DOOR_AT_S = 11.4               # dialogue clip: the door slam (an audio event with a directional caption)
DIALOGUE_SECONDS = 16.0

# Colors: the data-viz reference palette, dark mode (surface #1a1a19). Text never wears a series color.
SURFACE, PLANE = "#1a1a19", "#0d0d0d"
INK, INK2, MUTED = "#f0efec", "#c3c2b7", "#898781"
GRID, AXIS = "#2c2c2a", "#383835"
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
CRITICAL, WARNING, GOOD = "#d03b3b", "#fab219", "#0ca30c"
RAMP = [(0.0, SURFACE), (0.35, "#104281"), (0.6, "#2a78d6"), (0.85, "#86b6ef"), (1.0, "#e8f1fc")]  # spectrogram
DEBUG = False
WORK = None                    # set by main(): the scratch folder


class BuildError(Exception):
    """Exit 1: a step failed (its output is in the message)."""


class EnvError(Exception):
    """Exit 2: something this script needs is missing."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                                    # checked in main() so -h still works
    np = Image = ImageDraw = ImageFont = None


# ---- Running Wavesmith and ffmpeg -----------------------------------------------------------------------------------
def ws(*args, ok=(0,)):
    """Run one Wavesmith command; print it (relative paths) so the run log doubles as the recipe."""
    shown = " ".join(_short(a) for a in args)
    print(f"  wavesmith.py {shown}")
    r = subprocess.run([sys.executable, str(WAVESMITH), *map(str, args)], capture_output=True,
                       encoding="utf-8", errors="replace")
    dbg(r.stdout + r.stderr)
    if r.returncode not in ok:
        raise BuildError(f"wavesmith.py {shown} exited {r.returncode}:\n{r.stdout}{r.stderr}")
    return r.stdout + r.stderr


def _short(a):
    """Paths shown relative to the work folder, this folder or the kit; everything else as is."""
    if not isinstance(a, Path):
        return f'"{a}"' if " " in str(a) else str(a)
    for base, name in ((WORK, "<work>"), (HERE, "<showcase>"), (KIT, "<kit>")):
        try:
            return f"{name}/{a.resolve().relative_to(base).as_posix()}"
        except (ValueError, OSError, TypeError):
            pass
    return a.as_posix()


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise EnvError("ffmpeg is not on PATH (install it: winget install Gyan.FFmpeg, brew install ffmpeg, "
                       "apt install ffmpeg)")
    return exe


def load(path, rate=RATE):
    """Any audio file as mono float64 samples at `rate` (ffmpeg decodes and resamples)."""
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode:
        raise BuildError(f"ffmpeg could not read {path}: {r.stderr.decode('utf-8', 'replace')}")
    return np.frombuffer(r.stdout, dtype="<f4").astype(np.float64)


def save_wav(path, x, rate=RATE):
    """16-bit mono WAV. Anything past full scale clips here, as it would in a game's output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1.0, 1.0) * 32767).round().astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def safe_peak(x, peak=0.89):
    """Scale a mix down to `peak` when it would clip (intermediate files only, never the 'before' capture)."""
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return x * (peak / m) if m > peak else x


def place(out, x, at_s, gain=1.0):
    i = int(round(at_s * RATE))
    n = max(0, min(len(x), len(out) - i))
    out[i:i + n] += x[:n] * gain


def for_video(work, name, x):
    """The clip's audio at VIDEO_LUFS (loudness normalize, true peak capped at -1 dBTP)."""
    raw = work / "video" / f"{name}_raw.wav"
    save_wav(raw, safe_peak(x))
    out = work / "video" / f"{name}.wav"
    ws("loudness", "normalize", raw, "--lufs", VIDEO_LUFS, "--out", out, "--overwrite")
    return out


# ---- Drawing helpers ---------------------------------------------------------------------------------------------
_FONTS = {}


def font(size, kind="sans"):
    """Segoe UI / Consolas on Windows, DejaVu elsewhere, Pillow's own font as the last resort."""
    key = (size, kind)
    if key not in _FONTS:
        names = {"sans": ["segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"],
                 "bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
                 "mono": ["consola.ttf", "DejaVuSansMono.ttf", "Menlo.ttc"]}[kind]
        for n in names:
            try:
                _FONTS[key] = ImageFont.truetype(n, size)
                break
            except OSError:
                continue
        else:
            _FONTS[key] = ImageFont.load_default(size) if hasattr(ImageFont, "load_default") else None
    return _FONTS[key]


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def text_w(d, s, f):
    return d.textlength(s, font=f)


def spectrogram(x, w, h, rate=RATE, fmin=60.0, fmax=14000.0, floor_db=-60.0):
    """RGB array (h, w, 3): STFT magnitude on a log-frequency axis, one column per pixel, sequential blue ramp.
    Short sounds get a shorter window (sharper in time), long ones 2048 samples (sharper in pitch)."""
    n_fft = 2048 if len(x) > 2 * rate else 1024 if len(x) > 0.3 * rate else 512
    pad = np.concatenate([np.zeros(n_fft), x, np.zeros(n_fft)])
    centers = ((np.arange(w) + 0.5) * len(x) / w).astype(int) + n_fft
    idx = centers[:, None] + np.arange(n_fft)[None, :] - n_fft // 2
    frames = pad[idx] * np.hanning(n_fft)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    db = 20 * np.log10(mag + 1e-9)
    db -= max(db.max(), -200)
    freqs = np.fft.rfftfreq(n_fft, 1 / rate)
    rows = fmin * (fmax / fmin) ** (1 - np.arange(h) / (h - 1))          # top row = fmax
    img_db = np.stack([np.interp(rows, freqs, col) for col in db], axis=1)  # (h, w)
    v = np.clip((img_db - floor_db) / -floor_db, 0, 1)
    stops = np.array([s for s, _ in RAMP])
    cols = np.array([rgb(c) for _, c in RAMP], dtype=float)
    out = np.stack([np.interp(v, stops, cols[:, k]) for k in range(3)], axis=-1)
    return out.astype(np.uint8)


def envelope(x, w):
    """Per pixel column (min, max) of x."""
    edges = np.linspace(0, len(x), w + 1).astype(int)
    lo = np.array([x[a:b].min() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    hi = np.array([x[a:b].max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    return lo, hi


def draw_wave(d, x, box, color, scale=None):
    x0, y0, x1, y1 = box
    lo, hi = envelope(x, int(x1 - x0))
    s = scale or max(1e-9, float(max(abs(lo.min()), hi.max())))
    mid, half = (y0 + y1) / 2, (y1 - y0) / 2
    for i, (a, b) in enumerate(zip(lo, hi)):
        ya, yb = mid - b / s * half, mid - a / s * half
        d.line([(x0 + i, ya), (x0 + i, max(yb, ya + 1))], fill=color)


def time_axis(d, box, seconds, step=None, y=None):
    x0, _, x1, y1 = box
    step = step or (1 if seconds <= 12 else 2 if seconds <= 32 else 5 if seconds <= 70 else 10)
    y = y if y is not None else y1 + 4
    f = font(13)
    t = 0.0
    while t <= seconds + 1e-6:
        x = x0 + (x1 - x0) * t / seconds
        d.line([(x, y - 4), (x, y)], fill=AXIS)
        lab = f"{t:g} s"
        d.text((x - text_w(d, lab, f) / 2, y + 1), lab, fill=MUTED, font=f)
        t += step


def header(d, title, sub, sub2=None):
    d.text((40, 22), title, fill=INK, font=font(30, "bold"))
    d.text((40, 66), sub, fill=INK2, font=font(16))
    if sub2:
        d.text((40, 89), sub2, fill=MUTED, font=font(14, "mono"))


def playhead(d, x, y0, y1):
    d.line([(x, y0), (x, y1)], fill=INK, width=2)


def write_video(out, base, audio, seconds, overlay):
    """Frames: a copy of `base` per frame, `overlay(draw, image, t)` on top; piped to ffmpeg with the audio."""
    cmd = [ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS),
           "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "slow", "-crf", str(CRF), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", f"{AAC_KBPS}k", "-shortest", "-movflags", "+faststart", str(out)]
    dbg(" ".join(cmd))
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for k in range(int(math.ceil(seconds * FPS))):
            img = base.copy()
            overlay(ImageDraw.Draw(img), img, k / FPS)
            p.stdin.write(img.tobytes())
    finally:
        p.stdin.close()
        rc = p.wait()
    if rc:
        raise BuildError(f"ffmpeg failed writing {out} (exit {rc})")
    print(f"[ OK ] {out.relative_to(HERE).as_posix()}: {seconds:.1f} s, {out.stat().st_size / 1024:.0f} KB")


def canvas(w=VW, h=VH):
    img = Image.new("RGB", (w, h), SURFACE)
    return img, ImageDraw.Draw(img)


def save_png(img, name):
    path = MEDIA / name
    img.quantize(256, method=0, dither=0).save(path, optimize=True)     # 256 colors (median cut): a third the size
    print(f"[ OK ] {path.relative_to(HERE).as_posix()}: {img.width}x{img.height}, {path.stat().st_size / 1024:.0f} KB")


# ---- 1. Sound from code ------------------------------------------------------------------------------------------
def make_code(work):
    d = work / "code"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for label, preset, seed in SFX_PLAN:
        name = preset if seed is None else f"{preset}_s{seed}"
        out = d / f"{name}.wav"
        ws("synth", preset, "--out", out, "--overwrite", *(["--seed", seed] if seed is not None else []))
        files.append((label, preset, seed, out))
    (work / "music").mkdir(parents=True, exist_ok=True)
    chase = work / "music" / "chase.wav"
    ws("chiptune", SRC / "chase.song.json", "--out", chase, "--overwrite")
    return files, chase


def build_code(work):
    print("== sound from code")
    files, chase_wav = make_code(work)
    sounds = [(label, preset, seed, load(p)) for label, preset, seed, p in files]
    chase = load(chase_wav)
    # timeline: every sheet sound with a gap, then the chiptune loop twice (the seam is inaudible)
    t, spans = 0.5, []
    for label, preset, seed, x in sounds:
        spans.append((label, preset, seed, t, t + len(x) / RATE, x))
        t += len(x) / RATE + SFX_GAP_S
    loop_at = round(t + 0.2, 1)
    total = loop_at + 2 * len(chase) / RATE + 0.6
    mix = np.zeros(int(total * RATE))
    for _, _, _, a, _, x in spans:
        place(mix, x, a)
    place(mix, chase, loop_at)
    place(mix, chase, loop_at + len(chase) / RATE)
    audio = for_video(work, "code", mix)
    sheet_png(spans, chase)
    code_video(spans, loop_at, len(chase) / RATE, load(audio), audio, total)


def sheet_png(spans, chase):
    cols, cw, ch, pad = 4, 300, 170, 16
    rows = math.ceil((len(spans) + 1) / cols)
    W, H = pad + cols * (cw + pad), 140 + rows * (ch + pad)
    img, d = canvas(W, H)
    header(d, "Sound from code", "wavesmith.py synth <preset> [--seed N] and chiptune: no model, no samples, "
           "nothing to license", None)
    cells = [(label, f"synth {preset}" + (f" --seed {seed}" if seed is not None else ""), x)
             for label, preset, seed, _, _, x in spans]
    cells.append(("chiptune loop", "chiptune chase.song.json", chase))
    for k, (label, cmd, x) in enumerate(cells):
        cx, cy = pad + (k % cols) * (cw + pad), 112 + (k // cols) * (ch + pad)
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch], 6, outline=AXIS, fill=PLANE)
        d.text((cx + 10, cy + 6), label, fill=INK, font=font(16, "bold"))
        d.text((cx + 10, cy + 28), cmd, fill=MUTED, font=font(12, "mono"))
        sw, sh = cw - 20, 82
        img.paste(Image.fromarray(spectrogram(x, sw, sh)), (cx + 10, cy + 48))
        draw_wave(d, x, (cx + 10, cy + 134, cx + 10 + sw, cy + 162), SERIES[0])
        dur = f"{len(x) / RATE:.2f} s"
        d.text((cx + cw - 10 - text_w(d, dur, font(12)), cy + 8), dur, fill=MUTED, font=font(12))
    d.text((pad, H - 26), "Each cell: spectrogram (log frequency, 60 Hz to 14 kHz, 60 dB range) over the waveform. "
           "Seeds make repeatable variations of a preset.",
           fill=MUTED, font=font(13))
    save_png(img, "wavesmith_code_sheet.png")


def code_video(spans, loop_at, loop_len, x, audio, total):
    img, d = canvas()
    header(d, "Sound from code", "Retro effects from presets and seeds (synth), then a chiptune loop played twice "
           "(the seam is seamless).", "wavesmith.py synth jump --seed 2   |   wavesmith.py chiptune chase.song.json")
    box = (40, 175, VW - 40, 455)
    img.paste(Image.fromarray(spectrogram(x, box[2] - box[0], box[3] - box[1])), box[:2])
    wbox = (40, 470, VW - 40, 560)
    draw_wave(d, x, wbox, SERIES[0])
    time_axis(d, wbox, total)

    def xt(t):
        return box[0] + (box[2] - box[0]) * t / total
    f = font(13)
    for k, (label, _, _, a, b, _) in enumerate(spans):         # two staggered label rows with leader ticks
        y = 128 if k % 2 == 0 else 150
        d.text((xt(a), y), label.replace(" --seed ", " s"), fill=INK2, font=f)
        d.line([(xt(a), y + 18), (xt(a), box[1])], fill=AXIS)
    for k in range(2):
        a = loop_at + k * loop_len
        d.line([(xt(a), 128), (xt(a), box[1])], fill=SERIES[2], width=2)
        d.text((xt(a) + 6, 128), "chiptune loop" if k == 0 else "loop point: plays again", fill=INK2, font=f)

    def overlay(dd, im, t):
        playhead(dd, xt(t), box[1], wbox[3])
        now = None
        for label, preset, seed, a, b, _ in spans:
            if a - 0.05 <= t <= b + SFX_GAP_S * 0.8:
                now = ("synth " + preset + (f" --seed {seed}" if seed is not None else ""), f"{b - a:.2f} s")
        if t >= loop_at - 0.05:
            now = ("chiptune chase.song.json", "8 s loop, pass 2 of 2" if t >= loop_at + loop_len else
                   "8 s loop, pass 1 of 2")
        dd.rounded_rectangle([40, 600, VW - 40, 690], 8, fill=PLANE, outline=AXIS)
        if now:
            dd.text((60, 612), "now playing", fill=MUTED, font=font(14))
            dd.text((60, 634), now[0], fill=INK, font=font(30, "mono"))
            dd.text((VW - 60 - text_w(dd, now[1], font(18)), 646), now[1], fill=INK2, font=font(18))
    write_video(MEDIA / "wavesmith_code.mp4", img, audio, total, overlay)


# ---- 2. Adaptive music -------------------------------------------------------------------------------------------
class MusicSim:
    """What the web music player (and every other engine's) does with data/music.json, sample for sample: one
    looping voice per stem from the track's start, a stem gain, a track gain that fades on a transition, and the
    stinger at the switch point. Decisions come from music.py's plan(), the shared reference."""

    def __init__(self, data, root):
        import music
        self.m, self.data, self.rate = music, data, data["sample_rate"]
        self.files = {}
        for t in data["tracks"].values():
            for f in t["stems"].values():
                self.files[f] = load(root / f, self.rate)
        for s in data.get("stingers", {}).values():
            self.files[s["file"]] = load(root / s["file"], self.rate)
        self.plays, self.stingers, self.current, self.plans = [], [], None, []

    def _launch(self, name, at, entry):
        p = {"name": name, "since": at, "entry": entry, "stop": None, "fade": None,
             "stems": {s: [(at, 1.0)] for s in self.data["tracks"][name]["stems"]}}
        self.plays.append(p)
        return p

    def start(self, name, at):
        self.current = self._launch(name, at, 0)

    def stem_gain(self, stem, value, at):
        self.current["stems"][stem].append((at, value))

    def next_bar(self, now):
        cur = self.current
        track = self.data["tracks"][cur["name"]]
        pos = self.m.position(track, self.rate, cur["since"], now, cur["entry"])
        return now + self.m.next_boundary(track, self.rate, pos, "bar") - pos

    def request(self, to, now):
        cur = self.current
        p = self.m.plan(self.data, cur["name"], cur["since"], cur["entry"], to, max(now, cur["since"]))
        cur["stop"] = p["from_stop_at"]
        if p["fade"] > 0:
            cur["fade"] = (p["switch_at"], p["from_stop_at"])
        if p["stinger"]:
            self.stingers.append((p["stinger"], p["stinger_at"]))
        self.current = self._launch(to, p["to_start_at"], p["to_offset"])
        self.plans.append(dict(p, frm=cur["name"], to=to, asked=now,
                               rule=self.m.rule_for(self.data, cur["name"], to)))
        return p

    def render(self, n):
        """(mix, {lane: samples}) for n samples."""
        lanes = {}
        for p in self.plays:
            track = self.data["tracks"][p["name"]]
            ls, le = self.m.loop_points(track, self.rate)
            a, b = p["since"], min(p["stop"] if p["stop"] is not None else n, n)
            if b <= a:
                continue
            t = np.arange(a, b)
            pos = t - p["since"] + p["entry"]
            wrap = pos >= le
            pos[wrap] = ls + (pos[wrap] - ls) % (le - ls)
            tg = np.ones(len(t))
            if p["fade"]:
                s0, s1 = p["fade"]
                tg = np.clip(1 - (t - s0) / max(1, s1 - s0), 0, 1)
                tg[t < s0] = 1.0
            for stem, events in p["stems"].items():
                x = self.files[track["stems"][stem]]
                times = np.array([e[0] for e in events])
                vals = np.array([e[1] for e in events])
                g = vals[np.searchsorted(times, t, side="right") - 1]
                lane = lanes.setdefault(f"{p['name']}: {stem}", np.zeros(n))
                lane[a:b] += x[np.minimum(pos, len(x) - 1)] * g * tg
        for name, at in self.stingers:
            x = self.files[self.data["stingers"][name]["file"]]
            lane = lanes.setdefault(f"stinger: {name}", np.zeros(n))
            k = min(len(x), n - at)
            lane[at:at + k] += x[:k]
        return sum(lanes.values()), lanes


def make_music(work):
    d = work / "music"
    d.mkdir(parents=True, exist_ok=True)
    for song in ("explore_base", "explore_drums", "chase", "alert"):
        ws("chiptune", SRC / f"{song}.song.json", "--out", d / f"{song}.wav", "--overwrite")
    ws("music", "validate", SRC / "music.json", "--root", work)


def run_music(work):
    """The game script through the simulated player: (mix, lanes, events for the picture, seconds)."""
    data = json.loads((SRC / "music.json").read_text(encoding="utf-8"))
    sim = MusicSim(data, work)
    rate = sim.rate
    marks, states = [], []
    for t, action, arg in MUSIC_SCRIPT:
        now = int(round(t * rate))
        if action == "start":
            sim.start(arg, now)
            states.append((0.0, "calm", "explore: base"))
        elif action == "stem":
            sim.stem_gain(arg[0], arg[1], now)
        elif action == "layer":
            at = sim.next_bar(now)
            sim.stem_gain(arg[0], arg[1], at)
            marks.append({"asked": t, "at": at / rate, "text": f"layer: {arg[0]} in on the next bar"})
            states.append((at / rate, "tense", "explore: base + drums layer"))
        elif action == "request":
            p = sim.request(arg, now)
            rule = sim.plans[-1]["rule"]
            how = f"next {rule['quantize']}" + (f", stinger {p['stinger']}" if p["stinger"] else "") + \
                  (f", {rule['fade_ms']} ms fade" if rule.get("fade_ms") else "")
            marks.append({"asked": t, "at": p["switch_at"] / rate, "enter": p["to_start_at"] / rate,
                          "text": f"request {arg}: {how}"})
            if arg == "explore":
                sim.stem_gain("drums", 0.0, p["to_start_at"])   # back to calm: the layer starts silent
                states.append((p["to_start_at"] / rate, "calm", "explore: base"))
            else:
                if p["stinger"]:
                    states.append((p["switch_at"] / rate, "stinger", f"stinger: {p['stinger']}"))
                states.append((p["to_start_at"] / rate, "chase", "chase: full"))
    seconds = states[-1][0] + 8.0
    n = int(seconds * rate)
    mix, lanes = sim.render(n)
    fade = int(0.5 * rate)                                # the video ends with a short fade (presentation only)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return mix, lanes, marks, states, sim.plans, seconds


def build_music(work):
    print("== adaptive music")
    make_music(work)
    mix, lanes, marks, states, plans, seconds = run_music(work)
    for p in plans:
        print(f"  plan {p['frm']} -> {p['to']} asked {p['asked'] / RATE:.2f} s: switch {p['switch_at'] / RATE:.2f} s, "
              f"enters {p['to_start_at'] / RATE:.2f} s, stinger {p['stinger']}, fade {p['fade']} samples")
    save_wav(work / "music" / "music_scene.wav", safe_peak(mix))
    audio = for_video(work, "music", mix)
    base, box = music_base(lanes, marks, states, seconds)
    save_png(base, "wavesmith_music.png")
    music_video(base, box, marks, states, seconds, audio)


LANE_ORDER = ["explore: base", "explore: drums", "stinger: alert", "chase: full"]


def music_base(lanes, marks, states, seconds):
    img, d = canvas()
    header(d, "Adaptive music", "One data/music.json, played by the reference planner every engine matches: "
           "a drums layer, a beat-quantized change with a stinger, a bar-quantized fade back.",
           "music.plan(data, from, since, entry, to, now)  ->  switch_at, stinger_at, to_start_at")
    x0, x1 = 210, VW - 40
    top, lh, gap = 150, 72, 12

    def xt(t):
        return x0 + (x1 - x0) * t / seconds
    peak = max(float(np.max(np.abs(v))) for v in lanes.values()) or 1.0
    for k, name in enumerate(LANE_ORDER):
        y = top + k * (lh + gap)
        d.rectangle([x0, y, x1, y + lh], fill=PLANE)
        d.text((40, y + 10), name.split(": ")[0], fill=INK, font=font(16, "bold"))
        d.text((40, y + 32), name.split(": ")[1] + (" (layer)" if name.endswith("drums") else ""), fill=MUTED,
               font=font(14))
        if name in lanes:
            draw_wave(d, lanes[name], (x0, y + 4, x1, y + lh - 4), SERIES[k], scale=peak)
    y_end = top + len(LANE_ORDER) * (lh + gap) - gap
    # state band
    sy = y_end + 18
    names = {"calm": "CALM", "tense": "TENSE", "stinger": "ALERT", "chase": "CHASE"}
    shade = {"calm": "#24303d", "tense": "#3a3324", "stinger": "#3d2626", "chase": "#40261b"}
    for k, (t, st, _) in enumerate(states):
        t1 = states[k + 1][0] if k + 1 < len(states) else seconds
        d.rectangle([xt(t), sy, xt(t1) - 2, sy + 34], fill=shade[st])
        d.text((xt(t) + 8, sy + 6), names[st], fill=INK, font=font(16, "bold"))
    d.text((40, sy + 8), "game state", fill=MUTED, font=font(14))
    time_axis(d, (x0, 0, x1, sy + 40), seconds, step=2)
    # requests (dashed) and planned switch points (solid), labels in the notes area
    for k, m in enumerate(marks):
        xa, xb = xt(m["asked"]), xt(m["at"])
        for yy in range(top - 8, y_end, 8):
            d.line([(xa, yy), (xa, yy + 4)], fill=MUTED)
        d.line([(xb, top - 8), (xb, y_end)], fill=INK2, width=2)
    ny = sy + 74
    for k, m in enumerate(marks):
        txt = f"asked at {m['asked']:.2f} s, {m['text']}: switch at {m['at']:.2f} s" + \
              (f", enters {m['enter']:.2f} s" if m.get("enter") and abs(m["enter"] - m["at"]) > 1e-3 else "")
        d.text((40, ny + k * 22), txt, fill=INK2, font=font(15, "mono"))
    d.text((VW - 40 - text_w(d, "dashed: the game asks   solid: the planner's switch", font(13)), ny + 74),
           "dashed: the game asks   solid: the planner's switch", fill=MUTED, font=font(13))
    return img, (x0, x1, top - 8, sy + 34, xt)


def music_video(base, box, marks, states, seconds, audio):
    x0, x1, y0, y1, xt = box

    def overlay(d, im, t):
        playhead(d, xt(t), y0, y1)
        cur = [s for s in states if s[0] <= t][-1]
        d.rounded_rectangle([40, 640, 640, 704], 8, fill=PLANE, outline=AXIS)
        d.text((56, 646), "now playing", fill=MUTED, font=font(13))
        d.text((56, 664), cur[2], fill=INK, font=font(22, "bold"))
        pending = [m for m in marks if m["asked"] <= t < m["at"]]
        if pending:
            d.text((360, 670), f"asked: waiting for the {pending[0]['text'].split(': ')[1].split(',')[0]}",
                   fill=WARNING, font=font(14))
    write_video(MEDIA / "wavesmith_music.mp4", base, audio, seconds, overlay)


# ---- 3. Voices and dialogue ---------------------------------------------------------------------------------------
def make_dialogue(work):
    d = work / "dialogue"
    for sub in ("voice", "sfx", "amb"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    for n in ("guide_1", "guide_2", "scout_1"):
        ws("formats", "convert", MEDIA / f"voice_{n}.ogg", "--out", d / "voice" / f"{n}.wav", "--overwrite")
    ws("formats", "convert", MEDIA / "eleven_door.ogg", "--out", d / "sfx" / "door.wav", "--overwrite")
    ws("formats", "convert", MEDIA / "eleven_rain.ogg", "--out", d / "amb" / "rain.wav", "--overwrite")
    ws("babble", "Psst! Over here. The gate is open!", "--voice", "sprite", "--out", d / "voice" / "sprite.wav",
       "--overwrite")
    built = d / "en.built.json"
    ws("events", "validate", SRC / "audio_events.json", "--root", d)
    ws("dialogue", "build", SRC / "dialogue.json", "--root", d, "--events", SRC / "audio_events.json", "--out", built,
       "--overwrite")
    ws("dialogue", "lint", SRC / "dialogue.json", "--root", d)
    vtt = MEDIA / "wavesmith_dialogue.vtt"
    ws("dialogue", "export", built, "--sequence", "river", "--format", "vtt", "--out", vtt, "--overwrite",
       ok=(0, 2))
    if not vtt.exists():
        raise BuildError("dialogue export wrote no VTT")
    return d, json.loads(built.read_text(encoding="utf-8")), vtt


def parse_vtt(path):
    """[(start, end, speaker, [lines])] from a WebVTT file (the subset dialogue export writes)."""
    def sec(s):
        h, m, rest = s.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    cues, blocks = [], path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n\n")
    for b in blocks:
        rows = [r for r in b.split("\n") if r.strip()]
        if not rows or "-->" not in rows[0]:
            continue
        a, z = rows[0].split("-->")
        speaker, lines = None, []
        for r in rows[1:]:
            if r.startswith("<v "):
                speaker, r = r[3:].split(">", 1)
            lines.append(r)
        cues.append((sec(a), sec(z.split()[0]), speaker, lines))
    return cues


def loop_bed(x, seconds, xfade_s=0.08):
    """Tile a loopable bed to `seconds` with a short crossfade at each seam (decoder padding never clicks)."""
    n, f = int(seconds * RATE), int(xfade_s * RATE)
    out = np.zeros(n + len(x))
    ramp_in, ramp_out = np.linspace(0, 1, f), np.linspace(1, 0, f)
    pos = 0
    while pos < n:
        seg = x.copy()
        if pos:
            seg[:f] *= ramp_in
        seg[-f:] *= ramp_out
        out[pos:pos + len(seg)] += seg
        pos += len(x) - f
    return out[:n]


def normalized(work, src, bus, name):
    """The asset at the kit house level for its bus (loudness normalize --bus, home target)."""
    out = work / "norm" / f"{name}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    ws("loudness", "normalize", src, "--bus", bus, "--target", "home", "--out", out, "--overwrite")
    return out


def dialogue_scene(work, d, built, seconds):
    """Mix the river sequence, the rain bed and the door at house levels, ducked by the reference director.
    Returns (mix, {bus: samples}, the ambience duck gain in dB every 10 ms)."""
    import audio_events
    seq = built["sequences"]["river"]
    lines = built["lines"]
    path = {lid: normalized(work, d / lines[lid]["audio"], "dialogue", lid.replace(".", "_")) for lid in lines}
    rain_p = normalized(work, d / "amb" / "rain.wav", "ambience", "rain")
    door_p = normalized(work, d / "sfx" / "door.wav", "sfx", "door")
    voices = {lid: load(p) for lid, p in path.items()}
    door = load(door_p)
    rain = loop_bed(load(rain_p), seconds)
    n = int(seconds * RATE)
    events = json.loads((SRC / "audio_events.json").read_text(encoding="utf-8"))
    params = {"seed": events["seed"], "ducking": events["ducking"], "events": {
        "door_slam": dict(events["events"]["door_slam"], lengths_ms=[len(door) / RATE * 1000]),
        **{f"line.{lid}": {"bus": "dialogue", "files": [lid], "lengths_ms": [len(v) / RATE * 1000]}
           for lid, v in voices.items()}}}
    director = audio_events.Director(params)
    plays = sorted([(s["start"] * 1000, f"line.{s['line']}") for s in seq] + [(DOOR_AT_S * 1000, "door_slam")])
    lanes = {k: np.zeros(n) for k in ("dialogue", "ambience", "sfx")}
    duck = []
    steps = [(t, None) for t in np.arange(0, seconds * 1000, 10.0)]
    for t, what in sorted(plays + steps, key=lambda e: (e[0], e[1] is None)):
        if what is None:
            duck.append(director.duck(float(t)).get("ambience", 0.0))
            continue
        r = director.play(what, float(t))
        gain = 10 ** (r["gain_db"] / 20)
        if what == "door_slam":
            place(lanes["sfx"], door, t / 1000, gain)
        else:
            place(lanes["dialogue"], voices[what[5:]], t / 1000, gain)
    duck = np.array(duck)
    g = 10 ** (np.repeat(duck, int(RATE * 0.01)) / 20)
    g = np.concatenate([g, np.full(max(0, n - len(g)), g[-1] if len(g) else 1.0)])[:n]
    lanes["ambience"] = rain * g
    return sum(lanes.values()), lanes, duck


def build_dialogue(work):
    print("== voices and dialogue")
    d, built, vtt = make_dialogue(work)
    mix, lanes, duck = dialogue_scene(work, d, built, DIALOGUE_SECONDS)
    audio = for_video(work, "dialogue", mix)
    cues = parse_vtt(vtt)
    base, geo = dialogue_base(lanes, duck, built)
    dialogue_video(base, geo, built, cues, audio)
    still = base.copy()
    dialogue_overlay(ImageDraw.Draw(still), geo, built, cues, 9.6)
    save_png(still, "wavesmith_dialogue.png")


def dialogue_base(lanes, duck, built):
    img, d = canvas()
    header(d, "Voices and dialogue", "Two voices designed on a local GPU (Qwen3-TTS), a babble voice from code, "
           "subtitles and a typewriter timed to the audio, rain ducked under speech.",
           "voice design / say  |  babble  |  dialogue build, lint, export --format vtt  |  events (ducking)")
    x0, x1, top, lh = 190, VW - 40, 128, 62
    secs = DIALOGUE_SECONDS

    def xt(t):
        return x0 + (x1 - x0) * t / secs
    peak = max(float(np.max(np.abs(v))) for v in lanes.values()) or 1.0
    spk = {s["line"]: built["lines"][s["line"]]["color"] for s in built["sequences"]["river"]}
    labels = [("dialogue", ["voices + babble"]), ("ambience", ["rain bed; white line:", "duck gain, 0 to -8 dB"]),
              ("sfx", ["door event"])]
    for k, (name, sub) in enumerate(labels):
        y = top + k * (lh + 8)
        d.rectangle([x0, y, x1, y + lh], fill=PLANE)
        d.text((40, y + 8), name, fill=INK, font=font(16, "bold"))
        for j, sub_row in enumerate(sub):
            d.text((40, y + 28 + j * 16), sub_row, fill=MUTED, font=font(12))
        if name == "dialogue":           # each line in its speaker's color (from dialogue.json)
            for s in built["sequences"]["river"]:
                a, b = int(s["start"] * RATE), int(s["end"] * RATE)
                seg = np.zeros_like(lanes[name])
                seg[a:b] = lanes[name][a:b]
                xa, xb = int(xt(s["start"])), int(xt(s["end"]))
                lo, hi = envelope(seg[a:b], max(1, xb - xa))
                mid, half = y + lh / 2, (lh - 8) / 2
                for i, (p, q) in enumerate(zip(lo, hi)):
                    d.line([(xa + i, mid - q / peak * half), (xa + i, mid - p / peak * half + 1)],
                           fill=spk[s["line"]])
        else:
            draw_wave(d, lanes[name], (x0, y + 4, x1, y + lh - 4), SERIES[1 if name == "ambience" else 2])
        if name == "ambience":           # the duck curve from the director, 0 to -8 dB over the lane
            pts = [(xt(i * 0.01), y + 4 + (-v / 8.0) * (lh - 8)) for i, v in enumerate(duck)]
            d.line(pts, fill=INK2, width=1)
    y_end = top + 3 * (lh + 8) - 8
    time_axis(d, (x0, 0, x1, y_end), secs, step=2)
    # the mock game screen
    d.rounded_rectangle([40, 360, VW - 40, 700], 10, fill=PLANE, outline=AXIS)
    note = "in game: everything below is drawn from en.built.json and the exported .vtt"
    d.text((VW - 56 - text_w(d, note, font(12)), 368), note, fill=MUTED, font=font(12))
    return img, {"xt": xt, "y0": top, "y1": y_end}


def wrap_text(d, s, f, width):
    words, rows, cur = s.split(), [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if text_w(d, nxt, f) > width and cur:
            rows.append(cur)
            cur = w
        else:
            cur = nxt
    return rows + ([cur] if cur else [])


def dialogue_overlay(d, geo, built, cues, t, with_playhead=False):
    import dialogue as dlg
    if with_playhead:
        playhead(d, geo["xt"](t), geo["y0"], geo["y1"])
    # speech box: the line speaking now (held a moment after it ends), typed by the reference typewriter
    seq = built["sequences"]["river"]
    act = [s for s in seq if s["start"] <= t <= s["end"] + 0.6]
    bx0, by0, bx1, by1 = 70, 400, VW - 70, 520
    d.rounded_rectangle([bx0, by0, bx1, by1], 8, fill=SURFACE, outline=AXIS)
    d.text((bx0 + 2, by0 - 20), "speech box: typewriter from the reveal times", fill=MUTED, font=font(12))
    if act:
        s = act[-1]
        line = built["lines"][s["line"]]
        shown = line["text"][:dlg.reveal_count(line, t - s["start"])]
        d.text((bx0 + 16, by0 + 10), line["name"], fill=line["color"], font=font(18, "bold"))
        for k, row in enumerate(wrap_text(d, shown, font(24), bx1 - bx0 - 32)):
            d.text((bx0 + 16, by0 + 38 + k * 32), row, fill=INK, font=font(24))
        d.text((bx1 - 16 - text_w(d, f"reveal: {line['reveal_source']}", font(12)), by0 + 12),
               f"reveal: {line['reveal_source']}", fill=MUTED, font=font(12))
    # subtitles: the exported WebVTT cue on screen now
    d.text((bx0 + 2, 548), "subtitles: the WebVTT cues from dialogue export", fill=MUTED, font=font(12))
    cue = [c for c in cues if c[0] <= t < c[1]]
    if cue:
        a, z, speaker, rows = cue[0]
        f = font(22)
        for k, row in enumerate(rows):
            txt = (f"{speaker}: " if k == 0 and speaker else "") + row
            w = text_w(d, txt, f)
            yy = 572 + k * 34
            d.rectangle([VW / 2 - w / 2 - 10, yy - 2, VW / 2 + w / 2 + 10, yy + 30], fill="#000000")
            d.text((VW / 2 - w / 2, yy), txt, fill=INK, font=f)
    # SFX caption with its direction arrow (directional events), min_s from the built captions
    cap = built["captions"]["door_slam"]
    if DOOR_AT_S <= t < DOOR_AT_S + max(cap["min_s"], 1.4):
        f = font(20)
        txt = cap["text"]
        x, y = 110, 650
        d.polygon([(x - 26, y + 13), (x - 10, y + 3), (x - 10, y + 23)], fill=INK)
        d.rectangle([x - 4, y - 2, x + text_w(d, txt, f) + 8, y + 28], fill="#000000")
        d.text((x + 2, y), txt, fill=INK, font=f)
        d.text((x + text_w(d, txt, f) + 20, y + 6), "SFX caption (directional: the door is to the left)",
               fill=MUTED, font=font(12))


def dialogue_video(base, geo, built, cues, audio):
    def overlay(d, im, t):
        dialogue_overlay(d, geo, built, cues, t, with_playhead=True)
    write_video(MEDIA / "wavesmith_dialogue.mp4", base, audio, DIALOGUE_SECONDS, overlay)


# ---- 4. Mix and loudness -----------------------------------------------------------------------------------------
def build_mix(work):
    print("== mix and loudness")
    d = work / "dialogue"
    if not (d / "en.built.json").exists():
        make_dialogue(work)
    if not (work / "music" / "music_scene.wav").exists():
        make_music(work)
        mix, *_ = run_music(work)
        save_wav(work / "music" / "music_scene.wav", safe_peak(mix))
    if not (work / "code" / "explosion.wav").exists():
        make_code(work)
    assets = [   # (label, file, bus, origin)
        ("Guide line 1", d / "voice" / "guide_1.wav", "dialogue", "Qwen3-TTS"),
        ("Scout line", d / "voice" / "scout_1.wav", "dialogue", "Qwen3-TTS"),
        ("Guide line 2", d / "voice" / "guide_2.wav", "dialogue", "Qwen3-TTS"),
        ("Sprite babble", d / "voice" / "sprite.wav", "dialogue", "babble"),
        ("Music scene", work / "music" / "music_scene.wav", "music", "chiptune"),
        ("Chase loop", work / "music" / "chase.wav", "music", "chiptune"),
        ("Rain bed", d / "amb" / "rain.wav", "ambience", "ElevenLabs"),
        ("Door slam", d / "sfx" / "door.wav", "sfx", "ElevenLabs"),
        ("Explosion", work / "code" / "explosion.wav", "sfx", "synth"),
        ("Laser", work / "code" / "laser.wav", "sfx", "synth"),
        ("Coin", work / "code" / "coin.wav", "sfx", "synth"),
        ("Jump", work / "code" / "jump.wav", "sfx", "synth"),
        ("UI blip", work / "code" / "blip.wav", "ui", "synth"),
    ]
    before = measure([a[1] for a in assets])
    norm = [normalized(work, a[1], a[2], a[1].stem + "_" + a[2]) for a in assets]
    after = measure(norm)
    import loudness
    for rows, files in ((before, [a[1] for a in assets]), (after, norm)):   # one-shots: their loudest 400 ms
        for r, f in zip(rows, files):
            if r["integrated_lufs"] is None:
                r["momentary_lufs"] = loudness.max_momentary(*loudness.read_audio(f))
    loudness_png(assets, before, after)
    scene = {}
    for kind in ("before", "house", "master"):
        if kind == "master":       # the move check-mix asked for on the house mix, applied to the master
            m = re.search(r"move the master by ([+-][0-9.]+) dB", scene["house"][1])
            gain_db = float(m.group(1)) if m else 0.0
            x = scene["house"][0] * 10 ** (gain_db / 20)
            scene["master_note"] = f"master {gain_db:+.1f} dB, as the house mix's check asked"
        else:
            x = mix_scene(assets, norm if kind == "house" else [a[1] for a in assets], kind == "house")
        path = work / "mix" / f"capture_{kind}.wav"
        save_wav(path, x)
        report = ws("loudness", "check-mix", path, "--target", "home", "--allow-short", ok=(0, 1))
        print("\n".join("    " + r for r in report.splitlines() if not r.startswith("[warn]")))
        scene[kind] = (load(path), report, path)
    mix_png(scene)


def measure(files):
    """One `loudness measure --json` row per file, in the order given."""
    out = ws("loudness", "measure", *files, "--json")
    rows = {Path(r["file"]).resolve(): r for r in json.loads(out[out.index("["):out.rindex("]") + 1])}
    return [rows[Path(f).resolve()] for f in files]


def loudness_png(assets, before, after):
    import loudness
    W, H = 1280, 150 + 38 * len(assets) + 60
    img, d = canvas(W, H)
    header(d, "Loudness: every asset to its bus level",
           "loudness measure before and after loudness normalize --bus <bus> --target home "
           "(kit house levels; a one-shot under 0.4 s by its loudest 400 ms)")
    lx0, lx1, lmin, lmax = 330, 750, -42.0, -6.0      # LUFS panel
    px0, px1, pmin, pmax = 900, 1240, -28.0, 1.0      # true peak panel
    top = 150

    def X(v, a, b, lo, hi):
        return a + (b - a) * (min(max(v, lo), hi) - lo) / (hi - lo)
    d.text((lx0, top - 34), "Integrated loudness (LUFS)", fill=INK, font=font(15, "bold"))
    d.text((px0, top - 34), "True peak (dBTP)", fill=INK, font=font(15, "bold"))
    for v in range(-42, -5, 6):
        x = X(v, lx0, lx1, lmin, lmax)
        d.line([(x, top - 8), (x, top + 38 * len(assets))], fill=GRID)
        d.text((x - 10, top + 38 * len(assets) + 4), str(v), fill=MUTED, font=font(12))
    for v in (-27, -21, -15, -9, -3):
        x = X(v, px0, px1, pmin, pmax)
        d.line([(x, top - 8), (x, top + 38 * len(assets))], fill=GRID)
        d.text((x - 8, top + 38 * len(assets) + 4), str(v), fill=MUTED, font=font(12))
    xc = X(-1, px0, px1, pmin, pmax)
    d.line([(xc, top - 8), (xc, top + 38 * len(assets))], fill=CRITICAL, width=2)
    d.text((xc + 4, top - 18), "-1 ceiling", fill=INK2, font=font(12))
    target = {b: loudness.ASWG["home"] + off for b, off in loudness.HOUSE.items()}
    for k, ((label, _, bus, origin), b, a) in enumerate(zip(assets, before, after)):
        y = top + 38 * k + 14
        if k % 2 == 0:
            d.rectangle([40, y - 15, W - 40, y + 17], fill="#1f1f1e")
        d.text((48, y - 10), label, fill=INK, font=font(15))
        d.text((190, y - 9), f"{bus} | {origin}", fill=MUTED, font=font(12))
        xt = X(target[bus], lx0, lx1, lmin, lmax)
        d.line([(xt, y - 11), (xt, y + 11)], fill=INK2, width=2)
        key = "integrated_lufs" if b["integrated_lufs"] is not None else "momentary_lufs"
        lb, la = b[key], a[key]
        xb, xa = X(lb, lx0, lx1, lmin, lmax), X(la, lx0, lx1, lmin, lmax)
        d.line([(xb, y), (xa, y)], fill=AXIS, width=2)
        if key == "integrated_lufs":
            d.ellipse([xb - 6, y - 6, xb + 6, y + 6], outline=MUTED, width=2, fill=SURFACE)
            d.ellipse([xa - 6, y - 6, xa + 6, y + 6], fill=SERIES[0])
        else:                                    # under 0.4 s: the loudest 400 ms, drawn as squares
            d.rectangle([xb - 6, y - 6, xb + 6, y + 6], outline=MUTED, width=2, fill=SURFACE)
            d.rectangle([xa - 6, y - 6, xa + 6, y + 6], fill=SERIES[0])
        d.text((lx1 + 14, y - 8), f"{lb:.1f} to {la:.1f}", fill=INK2, font=font(12))
        tb, ta = b["true_peak_dbtp"], a["true_peak_dbtp"]
        xb, xa = X(tb, px0, px1, pmin, pmax), X(ta, px0, px1, pmin, pmax)
        d.line([(xb, y), (xa, y)], fill=AXIS, width=2)
        d.ellipse([xb - 6, y - 6, xb + 6, y + 6], outline=CRITICAL if tb > -1 else MUTED, width=2, fill=SURFACE)
        d.ellipse([xa - 6, y - 6, xa + 6, y + 6], fill=SERIES[0])
    ly = top + 38 * len(assets) + 30
    d.ellipse([48, ly, 60, ly + 12], outline=MUTED, width=2)
    d.text((66, ly - 3), "before (as made)", fill=INK2, font=font(13))
    d.ellipse([200, ly, 212, ly + 12], fill=SERIES[0])
    d.text((218, ly - 3), "after normalize", fill=INK2, font=font(13))
    d.rectangle([340, ly, 352, ly + 12], outline=MUTED, width=2)
    d.text((358, ly - 3), "under 0.4 s: loudest 400 ms", fill=INK2, font=font(13))
    d.line([(560, ly - 2), (560, ly + 14)], fill=INK2, width=2)
    d.text((568, ly - 3), "house level of the bus (home: dialogue -24, music -28, ambience -34, sfx -30, ui -32)",
           fill=INK2, font=font(13))
    save_png(img, "wavesmith_loudness.png")


def mix_scene(assets, files, after):
    """A 60 s stretch of 'gameplay': a quiet area (rain, a few pickups), the music scene with an action burst in its
    chase, the dialogue over the calm end of the music, a door, then the quiet area again. before: every asset as made, no ducking. after: house levels and the
    reference director's ducking of music and ambience under dialogue."""
    by = {a[0]: load(f) for a, f in zip(assets, files)}
    n = int(MIX_SECONDS * RATE)
    sfx, music, talk = np.zeros(n), np.zeros(n), np.zeros(n)
    rain = loop_bed(by["Rain bed"], MIX_SECONDS)
    place(music, by["Music scene"], 12.0)                     # its chase runs from 26.5 to 34.5 s
    quiet = [(1.0, "UI blip"), (1.3, "UI blip"), (3.0, "Jump"), (3.6, "Coin"), (5.2, "Jump"), (5.8, "Coin"),
             (8.4, "Jump"), (9.0, "Coin"), (51.0, "Jump"), (51.6, "Coin"), (54.2, "Jump"), (57.0, "UI blip")]
    burst = [(27.0 + 0.5 * i, nm) for i, nm in enumerate(["Jump", "Coin", "Laser", "Jump", "Laser", "Coin"])]
    burst += [(30.2, "Explosion"), (30.5, "Explosion"), (31.4, "Laser"), (32.4, "Explosion"), (33.0, "Coin")]
    for t, nm in quiet + burst + [(45.4, "Door slam")]:
        place(sfx, by[nm], t)
    seq = [(35.0, "Guide line 1"), (38.5, "Scout line"), (41.5, "Guide line 2"), (47.0, "Sprite babble")]
    for t, nm in seq:
        place(talk, by[nm], t)
    if after:          # ducking: the dialogue clip's rule, a straight line in dB (audio_events.py Director)
        import audio_events
        events = json.loads((SRC / "audio_events.json").read_text(encoding="utf-8"))
        params = {"seed": 1, "ducking": events["ducking"], "events": {
            nm: {"bus": "dialogue", "files": [nm], "lengths_ms": [len(by[nm]) / RATE * 1000]} for _, nm in seq}}
        director = audio_events.Director(params)
        duck, plays = [], sorted(seq)
        for t in np.arange(0, MIX_SECONDS * 1000, 10.0):
            while plays and plays[0][0] * 1000 <= t:
                director.play(plays[0][1], plays[0][0] * 1000)
                plays.pop(0)
            duck.append(director.duck(float(t)))
        for bus, lane in (("music", music), ("ambience", rain)):
            g = np.repeat([10 ** (x.get(bus, 0.0) / 20) for x in duck], int(RATE * 0.01))[:n]
            lane *= np.concatenate([g, np.ones(n - len(g))])
    return sfx + music + rain + talk


def step_at(st, t):
    """(short-term loudness just before t, the highest short-term loudness in the 3 s after t)."""
    before = st[max(0, int(round((t - 0.2) * 10)) - 30)]
    after = max(v for v in st[int(round(t * 10)) - 30 + 10:int(round(t * 10)) - 30 + 31] if math.isfinite(v))
    return before, after


def mix_png(scene):
    import loudness
    W, H = 1280, 950
    img, d = canvas(W, H)
    header(d, "The whole-mix check", "One 60 s gameplay capture, three mixes: assets as made, at house levels with "
           "ducking, then the master move check-mix asked for.",
           "loudness check-mix capture.wav --target home --allow-short   (ASWG-R001: -24 LKFS +/-2, true peak -1 dBTP)")
    x0, x1 = 100, W - 40
    lo, hi, ph = -50.0, 0.0, 170
    target = loudness.ASWG["home"]

    def X(t):
        return x0 + (x1 - x0) * t / MIX_SECONDS
    for p, (kind, title) in enumerate((("before", "1. assets as made"), ("house", "2. house levels + ducking"),
                                       ("master", "3. plus the master move"))):
        top = 128 + p * 262
        x, report, _ = scene[kind]
        subs = [loudness.sub_block_energy(list(x), RATE)]
        mom = [lv for lv, _ in loudness.window_loudness(subs, 4)]
        st = [lv for lv, _ in loudness.window_loudness(subs, 30)]

        def Y(v):
            return top + 62 + ph * (hi - min(max(v, lo), hi)) / (hi - lo)
        # title row: what this mix is, the tool's numbers and verdict, then its findings
        verdict = "FAIL" if "[FAIL]" in report else "OK"
        nums = [r for r in report.splitlines() if r.startswith("capture:")]
        d.text((40, top), title, fill=INK, font=font(18, "bold"))
        d.text((330, top + 2), nums[0].replace("capture: 1.0 min, ", "") if nums else "", fill=INK2,
               font=font(15, "mono"))
        bt = f"check-mix: {verdict}" + (" (provisional)" if verdict == "OK" else "")
        bw = text_w(d, bt, font(15, "bold"))
        d.rounded_rectangle([x1 - bw - 20, top - 2, x1, top + 24], 5, fill=CRITICAL if verdict == "FAIL" else GOOD)
        d.text((x1 - bw - 10, top + 1), bt, fill="#ffffff", font=font(15, "bold"))
        fails = [r.replace("[FAIL] ", "") for r in report.splitlines() if r.startswith("[FAIL]")]
        if fails:
            d.text((40, top + 26), "; ".join(f.split(" (")[0] for f in fails), fill=INK2, font=font(13))
        elif kind == "master":
            d.text((40, top + 26), scene["master_note"], fill=INK2, font=font(13))
        # target band, grid, curves
        d.rectangle([x0, Y(target + 2), x1, Y(target - 2)], fill="#1f2a1f")
        for v in range(-50, 1, 10):
            d.line([(x0, Y(v)), (x1, Y(v))], fill=GRID)
            d.text((x0 - 34, Y(v) - 8), f"{v}", fill=MUTED, font=font(12))
        d.text((x1 - 6 - text_w(d, "target -24 +/-2", font(12)), Y(target + 2) - 1), "target -24 +/-2", fill=INK2,
               font=font(12))
        d.line([(X((i + 4) / 10), Y(v)) for i, v in enumerate(mom) if math.isfinite(v)], fill="#5c5b57", width=1)
        d.line([(X((i + 30) / 10), Y(v)) for i, v in enumerate(st) if math.isfinite(v)], fill=SERIES[0], width=2)
        # clipped samples (ticks above the plot) and the level step at each scene change (short-term, LU)
        clipped = np.abs(x) >= CLIP_LEVEL
        for t in np.unique(np.round(np.nonzero(clipped)[0] / RATE, 1)):
            d.line([(X(t), top + 48), (X(t), top + 58)], fill=CRITICAL, width=2)
        for t, name in SCENE_STEPS:
            a, b = step_at(st, t)
            xs = X(t + 2.2)
            d.line([(xs, Y(a)), (xs, Y(b))], fill=WARNING, width=2)
            d.line([(xs - 5, Y(a)), (xs + 5, Y(a))], fill=WARNING, width=2)
            d.polygon([(xs, Y(b)), (xs - 5, Y(b) + (8 if b > a else -8)), (xs + 5, Y(b) + (8 if b > a else -8))],
                      fill=WARNING)
            d.text((xs + 8, Y(max(a, b)) - 20), f"{name}: {b - a:+.0f} LU", fill=INK, font=font(13, "bold"))
        q = [(i, v) for i, v in enumerate(mom) if QUIET_AREA[0] <= (i + 4) / 10 <= QUIET_AREA[1] and math.isfinite(v)]
        bed = float(np.median([v for _, v in q]))
        i_peak, peak = max(q, key=lambda e: e[1])
        xs = X((i_peak + 4) / 10)
        d.line([(xs + 7, Y(bed)), (xs + 7, Y(peak))], fill=WARNING, width=2)
        d.line([(xs + 2, Y(bed)), (xs + 12, Y(bed))], fill=WARNING, width=2)
        d.text((x0 + 6, Y(0) + 4), f"pickups over the rain bed: {peak - bed:+.0f} LU", fill=INK, font=font(13, "bold"))
        time_axis(d, (x0, 0, x1, top + 62 + ph), MIX_SECONDS, step=10)
        n_clip = int(np.sum(clipped))
        summary = f"{n_clip} clipped samples" if n_clip else "no clipped samples"
        d.text((x1 - text_w(d, summary, font(13)), top + 26), summary, fill=CRITICAL if n_clip else INK2,
               font=font(13))
    ly = H - 30
    d.line([(40, ly + 8), (70, ly + 8)], fill="#5c5b57", width=1)
    d.text((76, ly), "momentary (400 ms)", fill=INK2, font=font(13))
    d.line([(212, ly + 8), (242, ly + 8)], fill=SERIES[0], width=2)
    d.text((248, ly), "short-term (3 s)", fill=INK2, font=font(13))
    d.line([(372, ly + 2), (372, ly + 14)], fill=CRITICAL, width=2)
    d.text((380, ly), "clipped", fill=INK2, font=font(13))
    d.line([(450, ly + 2), (450, ly + 14)], fill=WARNING, width=2)
    d.text((460, ly), "level steps read by the showcase script: short-term across a scene change; one-shot "
           "peaks (momentary) over the bed's median", fill=INK2, font=font(13))
    save_png(img, "wavesmith_mix_check.png")


# ---- Sources -----------------------------------------------------------------------------------------------------
def export_sources(work):
    """The code-made sources as OGG next to the generated ones (rebuildable, but handy to listen to)."""
    print("== exporting code-made sources to media/")
    for name, src in [("synth_jump", work / "code" / "jump.wav"), ("synth_coin", work / "code" / "coin.wav"),
                      ("synth_explosion", work / "code" / "explosion.wav"),
                      ("chiptune_explore_base", work / "music" / "explore_base.wav"),
                      ("chiptune_explore_drums", work / "music" / "explore_drums.wav"),
                      ("chiptune_chase", work / "music" / "chase.wav"), ("chiptune_alert", work / "music" / "alert.wav"),
                      ("babble_sprite", work / "dialogue" / "voice" / "sprite.wav")]:
        if src.exists():
            ws("formats", "convert", src, "--out", MEDIA / f"{name}.ogg", "--quality", 4, "--overwrite")


# ---- Main --------------------------------------------------------------------------------------------------------
STAGES = {"code": build_code, "music": build_music, "dialogue": build_dialogue, "mix": build_mix}


def main(argv=None):
    global DEBUG
    ap = argparse.ArgumentParser(
        description="Rebuild the Wavesmith showcase: code-made sounds, adaptive music, dialogue with subtitles, "
                    "loudness charts and the whole-mix check (MP4 + PNG in media/).",
        epilog="Stages: code (synth + chiptune), music (music director), dialogue (voices, babble, subtitles, "
               "ducking), mix (loudness before/after, check-mix). Needs numpy, Pillow and ffmpeg. "
               "Exit codes: 0 ok, 1 a step failed, 2 environment or usage.")
    ap.add_argument("--only", action="append", choices=sorted(STAGES), help="run just this stage (repeatable)")
    ap.add_argument("--work", default=str(HERE / "build"), help="scratch folder (default: build/ here, gitignored)")
    ap.add_argument("--export-sources", action="store_true", help="also write the code-made sources as OGG to media/")
    ap.add_argument("--debug", action="store_true", help="tool output, ffmpeg commands and tracebacks")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    try:
        if np is None:
            raise EnvError("numpy and Pillow are needed for the pictures: pip install numpy pillow")
        ffmpeg()
        global WORK
        work = WORK = Path(args.work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        MEDIA.mkdir(exist_ok=True)
        for name in (args.only or ["code", "music", "dialogue", "mix"]):
            STAGES[name](work)
        if args.export_sources:
            export_sources(work)
        return 0
    except EnvError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except BuildError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
