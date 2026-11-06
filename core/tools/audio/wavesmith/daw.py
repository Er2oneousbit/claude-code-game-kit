#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# daw.py
# Purpose : The DAW round trip: edit a game's sounds by hand in a DAW and bring them back normalized, checked and
#           logged. REAPER gets a real project (one named region per sound, one track per music layer, the bus
#           loudness targets in the project notes) that Wavesmith renders back headless; every other DAW (FL Studio,
#           Ableton Live, Bitwig, Ardour, LMMS, Audacity ...) gets WAV stems, a MIDI file for the music and a markers
#           file, and its renders come back from a folder by name.
# Usage   : python tools/audio/wavesmith/wavesmith.py daw reaper footsteps                 # a set in data/sound_sets.json
#           python tools/audio/wavesmith/wavesmith.py daw reaper explore                   # a track in data/music.json
#           python tools/audio/wavesmith/wavesmith.py daw reaper assets/audio/ui --bus ui  # every sound in a folder
#           python tools/audio/wavesmith/wavesmith.py daw reaper --reexport assets_src/daw/footsteps
#           python tools/audio/wavesmith/wavesmith.py daw export explore build/daw_explore --song assets/audio/src/explore.song.json
#           python tools/audio/wavesmith/wavesmith.py daw import build/daw_explore        # your renders in renders/
#           python tools/audio/wavesmith/wavesmith.py daw check                            # REAPER found?
# Needs   : Python 3.8+ only. --reexport needs REAPER (REAPER_BIN, or its usual install folder); a game file kept as
#           OGG needs ffmpeg to be written back (audioio.py).
# Exit    : 0 ok, 1 something came back wrong (a region or render missing or extra, a file changed outside the DAW
#           since the project was made, REAPER rendered nothing), 2 usage, an unreadable file or REAPER not found
# Notes   : The working folder (default assets_src/daw/<name>, kept out of Godot's import by assets_src/.gdignore)
#           holds the project, a copy of every sound under media/, and wavesmith_daw.json: which region or track is
#           which game file, its bus, kind, SHA-256 (and its copy's), length, channels and loop (WAV smpl chunk, OGG
#           LOOPSTART / LOOPLENGTH). Nothing in it holds an absolute path (media and the game root are relative to
#           the folder, which must be inside the game), so it can be committed. --reexport and import run from the
#           game root it was made from (or --root).
#           The REAPER render: `reaper -newinst -nosplash -cfgfile <temp>/reaper.ini -renderproject <copy>.rpp`,
#           once per sample rate when the sounds have several (each at its own rate, so none is resampled).
#           The copy is the project with Wavesmith's render settings put back (24-bit WAV at the sounds' rate, no
#           dither, no normalization; sounds: master mix of every region, named $region; music: each stem track
#           through the master, named $track) so a render setting changed while editing cannot break the round trip.
#           The -cfgfile folder is a new temporary folder every run, holding only "[audioconfig] mode=4" (Dummy
#           Audio: no device opens and REAPER does not ask for one), and is deleted afterwards: your own REAPER
#           settings, in %APPDATA%/REAPER or ~/Library/Application Support/REAPER, are never read or written. REAPER
#           takes about 13 s per render on the test machine, most of it scanning its plug-ins in the fresh folder.
#           Back in the game (compared with the folder's copy while it has its recorded SHA-256, else with the
#           game's file while it is the original): a render whose audio matches the original (same length and
#           channels, every sample within 2.5 steps of 16-bit) leaves the game's file untouched, byte for byte. A
#           changed one is set to its
#           bus's house level (sound_sets.py rules: loudest 400 ms for one-shots, integrated for loops, true peak at
#           most -1 dBTP); music stems are levelled together, by the mix of all their renders, so their balance
#           stays as you set it and a second run lands on the same bytes. An edit undone in the DAW puts the
#           original back. A file that changed in the game since the project was made is not overwritten (--force).
#           Every written file gets a "hand_edits" entry in its sidecar (.sfx.json / .gen.json) and one ASSET_LOG
#           row per working folder ("Modified? yes", updated on later runs) with a docs/licenses evidence file.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   collect(source): a set (sound_sets.json), a music track (music.json) or a folder -> items: name, game file, bus,
#                    kind, rate, channels, frames, loop, SHA-256
#   reaper:  media copies -> .rpp (sounds end to end with a 1 s gap, a region each; or a track per stem at 0 and one
#            region) -> wavesmith_daw.json
#   export:  stems/<name>.wav, markers.csv + markers.txt, <name>_sequence.wav (sounds), <name>.mid (music), HOW_TO.txt
#   --reexport: render copy of the .rpp (our render settings) -> REAPER with a throwaway -cfgfile -> render/*.wav
#   import:  renders/*.wav matched by name (case, spaces and dashes forgiven; near misses named, not guessed)
#   bring_back(renders): per item: missing? same audio as the original? -> changed ones: mono restored, levelled
#            (per sound, or one gain for the whole music mix), loop kept -> conflict check -> write -> recheck every
#            other game file is unchanged -> sidecars, ASSET_LOG row, evidence, manifest (written SHA-256)
import argparse
import collections
import datetime
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import audioio  # noqa: E402
import loudness  # noqa: E402
import midifile  # noqa: E402
import music  # noqa: E402
import sound_sets  # noqa: E402
from wavfile import read_wav_channels  # noqa: E402

VERSION = 1
MANIFEST = "wavesmith_daw.json"
DEFAULT_OUT = "assets_src/daw"          # + /<name>
DEFAULT_SETS = "data/sound_sets.json"
DEFAULT_MUSIC = "data/music.json"
DEFAULT_AUDIO_ROOT = "assets/audio"     # what music.json's stem paths are relative to (music validate --root)
MEDIA_DIR, RENDER_DIR, STEMS_DIR, RENDERS_DIR = "media", "render", "stems", "renders"
ORIGINALS_DIR = "originals"             # daw export: the game's own OGG / FLAC bytes, for putting an undone edit back
RENDER_COPY = "_wavesmith_render.rpp"   # the project with our render settings, deleted after each render
GAP_S = 1.0                             # silence between sounds on the timeline
SAME_TOL = 2.5 / 32768                  # a render within this of the original, every sample, is the same audio
AUDIO_EXT = (".wav", ".flac", ".ogg")
UP_ONLY = re.compile(r"^(\.|\.\.(/\.\.)*)$")   # a manifest's root: the game root is this folder or above it
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")   # region / track / file names that survive every DAW
# names Windows cannot create as a file or folder (CON, nul.wav, COM1 ...), whatever the extension (#244)
WINDOWS_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
BACKUP_DIR = "backup"                   # --overwrite keeps edited working copies here, one folder per run (#243)
REAPER_ENV = "REAPER_BIN"
REAPER_TIMEOUT_S = 300
REAPER_INI = "[audioconfig]\nmode=4\n"  # mode 4 = Dummy Audio (read off REAPER 7.84's preferences, 2026-11-04)
WAV24_CFG = "ZXZhdxgAAQ=="              # REAPER's render format block for 24-bit PCM WAV
SOURCE_TYPE = {".wav": "WAVE", ".flac": "FLAC", ".ogg": "VORBIS"}
REAPER_CANDIDATES = (                   # where REAPER installs by default (the first two checked on Windows 11)
    r"C:\Program Files\REAPER (x64)\reaper.exe", r"C:\Program Files\REAPER\reaper.exe",
    "/Applications/REAPER.app/Contents/MacOS/REAPER", "~/opt/REAPER/reaper", "/opt/REAPER/reaper")
TOP_LEVEL_RENDER = ("RENDER_FILE", "RENDER_PATTERN", "RENDER_FMT", "RENDER_1X", "RENDER_RANGE", "RENDER_RESAMPLE",
                    "RENDER_ADDTOPROJ", "RENDER_STEMS", "RENDER_DITHER", "RENDER_TRIM", "RENDER_NORMALIZE",
                    "RENDER_SRATE", "SAMPLERATE")
REGION = re.compile(r"^MARKER\s+(\d+)\s+\S+\s+(\"[^\"]*\"|'[^']*'|`[^`]*`|\S+)\s+(\d+)")   # index, name, flags
MEDIA_FILE = re.compile(r'^\s*FILE\s+("[^"\r\n]*"|\'[^\'\r\n]*\'|`[^`\r\n]*`|\S+)', re.M)   # a SOURCE's file
ABS_PATH = re.compile(r'(?:^|["\s])((?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home|Volumes)/)[^"\r\n]*)')
CODE_TOOLS = (None, "sfx_synth", "chiptune", "babble")   # sidecar tools that use no model
LOG_KEY = "Wavesmith DAW project"       # how a working folder's ASSET_LOG row is found again
DEBUG = False


class ToolError(Exception):
    """Exit 2: usage, an unreadable file, or REAPER missing."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def posix_rel(path, start):
    """path relative to start, with / (ToolError when there is no relative path: another drive)."""
    try:
        return Path(os.path.relpath(str(Path(path).resolve()), str(Path(start).resolve()))).as_posix()
    except ValueError:
        raise ToolError(f"{path} and {start} are on different drives: keep the working folder inside the game")


def read_any(path):
    """(channels as lists, rate, loop or None) from WAV (its loop chunk), FLAC or OGG (its LOOPSTART / LOOPLENGTH
    comments, the kit's OGG loop: audioio.write_audio)."""
    path = Path(path)
    try:
        if path.suffix.lower() == ".wav":
            samples, rate, loop, ch = read_wav_channels(path)
            return [samples[c::ch] for c in range(ch)], rate, loop
        chans, rate = audioio.read_audio(path)
        chans = [list(c) for c in chans]
        return chans, rate, ogg_loop(path, len(chans[0])) if path.suffix.lower() == ".ogg" else None
    except (ValueError, audioio.AudioIOError) as exc:
        raise ToolError(f"{path.as_posix()}: {exc}")


def ogg_loop(path, frames):
    """(start, end) from an OGG Vorbis file's LOOPSTART / LOOPLENGTH comments, or None (no tags, or tags that do not
    fit the file)."""
    mod = audioio.oggvorbis_module()
    if mod is None:
        return None
    try:
        _, comments, _ = mod.stream(Path(path).read_bytes())      # the headers only: nothing is decoded
        tags = {k.upper(): v for k, v in comments}
        start, length = int(tags["LOOPSTART"]), int(tags.get("LOOPLENGTH", frames - int(tags["LOOPSTART"])))
    except Exception:              # no tags, a tag that is not a number, or one of the decoder's own error classes
        return None
    return (start, start + length - 1) if 0 <= start and length > 0 and start + length <= frames else None


# ---- what to edit ------------------------------------------------------------------------------------------------
def name_ok(name):
    """A name every DAW and every file system keeps: NAME_OK, not a Windows device name, no trailing dot (#244)."""
    return bool(NAME_OK.match(name)) and name.split(".")[0].lower() not in WINDOWS_DEVICES and not name.endswith(".")


def no_breaks(text, what):
    """Refuse a line break in text that goes into the .rpp or the records: it could end a block and add lines (#244)."""
    if re.search(r"[\r\n\x0b\x0c\x85\u2028\u2029]", text):
        raise ToolError(f"{what} {text!r} holds a line break: rename it (a project file cannot hold one safely)")
    return text


def item_for(name, path, root, bus, kind):
    if not name_ok(name):
        raise ToolError(f"{name!r} cannot be a region or track name (letters, digits, _ . - only, up to 64): rename "
                        f"{Path(path).as_posix()} or give a set of files with plain names")
    if not Path(path).is_file():
        raise ToolError(f"{Path(path).as_posix()} not found (make the sounds first: `wavesmith.py sets make`)")
    if Path(path).suffix.lower() not in AUDIO_EXT:
        raise ToolError(f"{Path(path).as_posix()}: only {', '.join(AUDIO_EXT)} files go to a DAW from here")
    rel = no_breaks(posix_rel(path, root), "the path")
    if rel.startswith("../") or rel == "..":
        raise ToolError(f"{Path(path).as_posix()} is outside the game root {Path(root).as_posix()} (pass --root)")
    chans, rate, loop = read_any(path)
    return {"name": name, "file": rel, "bus": bus, "kind": kind, "rate": rate,
            "channels": len(chans), "frames": len(chans[0]), "loop": list(loop) if loop else None,
            "sha256": sha256(path)}


def collect(args, root):
    """(meta, items) for the source named on the command line."""
    src = args.source
    if Path(src).is_dir():
        folder = Path(src)
        if not args.bus:
            raise ToolError(f"{src} is a folder: say which bus its sounds play on (--bus {'|'.join(loudness.HOUSE)})")
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT)
        if not files:
            raise ToolError(f"no {', '.join(AUDIO_EXT)} files in {folder.as_posix()}")
        items = []
        for p in files:
            it = item_for(p.stem, p, root, args.bus, "oneshot")
            it["kind"] = "loop" if it["loop"] else "oneshot"
            items.append(it)
        name = args.name or re.sub(r"[^A-Za-z0-9_.-]", "_", folder.resolve().name)
        return {"kind": "folder", "name": name, "target": args.target, "source": posix_rel(folder, root)}, items
    sets_path, music_path = root / args.sets, root / args.music
    in_sets = in_music = False
    sets = tracks = None
    if sets_path.is_file() and args.kind in (None, "set"):
        sets = sound_sets.load_sets(sets_path)
        in_sets = src in sets["sets"]
    if music_path.is_file() and args.kind in (None, "music"):
        data = music.load_json(music_path, "music")
        problems = music.validate(data)
        if problems:
            raise ToolError(f"{args.music} has problems (run `wavesmith.py music validate`): {problems[0]}")
        tracks = data
        in_music = src in data["tracks"]
    if in_sets and in_music:
        raise ToolError(f"{src!r} is both a sound set and a music track: add --kind set or --kind music")
    if in_sets:
        s = sets["sets"][src]
        out = sound_sets.out_dir_in(sets, root)
        items = [item_for(Path(f).stem, out / f, root, s["bus"], s.get("kind", "oneshot"))
                 for _, _, _, _, files in sound_sets.plan(sets, src) for f in files]
        return {"kind": "set", "name": args.name or src, "target": sets.get("target", "home"),
                "source": f"{args.sets} set {src}"}, items
    if in_music:
        t = tracks["tracks"][src]
        items = [item_for(stem, root / args.audio_root / f, root, "music", "stem") for stem, f in t["stems"].items()]
        rates = sorted({it["rate"] for it in items})
        if len(rates) > 1:
            raise ToolError(f"the stems of {src} are at {', '.join(f'{r} Hz' for r in rates)}: a track's stems share "
                            f"one sample rate (they play together; `music validate --root .` says the same), resample "
                            f"them first")
        meta = {"kind": "music", "name": args.name or src, "target": args.target, "source": f"{args.music} track {src}",
                "music": {k: t.get(k, d) for k, d in (("bpm", None), ("beats_per_bar", 4), ("bars", None),
                                                      ("loop_start_bar", 0))}}
        return meta, items
    have = []
    if sets:
        have.append(f"sets in {args.sets}: {', '.join(sets['sets'])}")
    if tracks:
        have.append(f"tracks in {args.music}: {', '.join(tracks['tracks'])}")
    raise ToolError(f"{src!r} is not a folder, a sound set or a music track" +
                    (f" ({'; '.join(have)})" if have else f" (no {args.sets} or {args.music} under {root.as_posix()})"))


def check_items(items):
    """Names that stay apart however a DAW renames a render (case, spaces, dashes), and one sound per game file:
    otherwise a render could come back as the wrong file, or two edits land on one (#242)."""
    seen, files = {}, {}
    for it in items:
        low = norm_name(it["name"])
        if low in seen:
            raise ToolError(f"two sounds are called {it['name']!r} ({seen[low]} and {it['file']}): names must differ, "
                            f"also in letter case and in - against _ (a render's name may come back changed in those)")
        seen[low] = it["file"]
        target = it["file"].casefold()
        if target in files:
            raise ToolError(f"{files[target]} and {it['name']} are both {it['file']}: one game file, one sound")
        files[target] = it["name"]


def project_shape(items, route):
    """(rate, channels) of the project: the most common rate (ties: the higher), the most channels."""
    rates = collections.Counter(it["rate"] for it in items)
    rate = max(rates, key=lambda r: (rates[r], r))
    for it in items:
        if it["rate"] != rate and route == "reaper":
            print(f"[note] {it['file']} is {it['rate']} Hz and the project runs at {rate} Hz: REAPER plays it "
                  f"resampled while you edit, and --reexport renders it back at {it['rate']} Hz (a render of its own)")
    return rate, max(it["channels"] for it in items)


def align_frames(rate, rates):
    """Project frames each sound's start is a multiple of: 1 when every sound has the project's rate, else a whole
    number of milliseconds that is a whole number of samples at every rate (44.1 and 48 kHz: 10 ms), so a sound
    rendered at its own rate starts on one of its own samples."""
    if set(rates) == {rate}:
        return 1
    ms = 1
    for r in rates:
        need = 1000 // math.gcd(int(r), 1000)
        ms = ms * need // math.gcd(ms, need)
    return rate * ms // 1000


def lay_out(meta, items, rate):
    """Sets each item's start frame: sounds end to end with GAP_S between them (each start on align_frames), music
    stems all at 0."""
    at, gap = 0, int(round(GAP_S * rate))
    step = align_frames(rate, [it["rate"] for it in items])
    for it in items:
        at = -(-at // step) * step
        it["start"] = 0 if meta["kind"] == "music" else at
        at += int(round(it["frames"] * rate / it["rate"])) + gap


def seconds(frames, rate):
    s = f"{frames / rate:.12f}".rstrip("0").rstrip(".")
    return s or "0"


def item_end(it, rate):
    """(length, end) in seconds of an item on a timeline at rate: its own length, exact at its own rate."""
    if it["rate"] == rate:
        n = int(round(it["frames"] * rate / it["rate"]))
        return seconds(n, rate), seconds(it["start"] + n, rate)
    return seconds(it["frames"], it["rate"]), seconds(it["start"] * it["rate"] + it["frames"] * rate, rate * it["rate"])


def targets(meta, items):
    """Lines naming each bus's house level, for notes and HOW_TO.txt."""
    base = loudness.ASWG[meta["target"]]
    buses = sorted({it["bus"] for it in items})
    out = [f"Bus loudness targets ({meta['target']}; kit house levels, set again on the way back):"]
    for b in buses:
        how = "the mix of all stems, integrated" if meta["kind"] == "music" else \
              "one-shots by their loudest 400 ms, loops integrated"
        out.append(f"  {b}: {base + loudness.HOUSE[b]:.0f} LUFS ({how}), true peak at most "
                   f"{sound_sets.TP_CEILING:.0f} dBTP")
    return out


# ---- the REAPER project --------------------------------------------------------------------------------------------
def q(text):
    """An RPP string: quoted (REAPER's names here never hold quotes: NAME_OK and the paths written below)."""
    return '"' + text.replace('"', "'") + '"'


def render_block(meta, rate, channels, indent="  "):
    """REAPER's render settings for the round trip (top level of the project)."""
    sounds = meta["kind"] != "music"
    lines = ["RENDER_FILE " + q(RENDER_DIR), "RENDER_PATTERN " + ("$region" if sounds else "$track"),
             f"RENDER_FMT 0 {channels} {rate}", "RENDER_1X 0", "RENDER_RANGE 3 0 0 0 1000", "RENDER_RESAMPLE 3 0 1",
             "RENDER_ADDTOPROJ 0",
             # 0: the master mix (each region is one sound); 128: each selected track through the master (stems)
             "RENDER_STEMS " + ("0" if sounds else "128"), "RENDER_DITHER 0", f"SAMPLERATE {rate} 1 0",
             "<RENDER_CFG", "  " + WAV24_CFG, ">"]
    return [indent + ln for ln in lines]


def notes_lines(meta, items, work_rel):
    what = {"set": "sound set", "music": "music piece", "folder": "sounds from"}[meta["kind"]]
    out = [f"Wavesmith DAW project: {what} {meta['name']} ({meta['source']})",
           "Edit freely; keep each region's name" + (" (it is the file it becomes)." if meta["kind"] != "music" else
                                                     " and each track's name (each track is one stem)."),
           f"Back to the game: python tools/audio/wavesmith/wavesmith.py daw reaper --reexport {work_rel}",
           ""] + targets(meta, items) + ["", "Sounds:"]
    for it in items:
        out.append(f"  {it['name']} -> {it['file']} ({it['bus']}, {it['kind']})")
    return out


def rpp_text(meta, items, rate, channels, work_rel):
    """The whole .rpp: deterministic (no GUIDs, dates or absolute paths), REAPER fills in the rest when it saves."""
    m = meta.get("music") or {}
    bpm, bpb = (m["bpm"], m.get("beats_per_bar", 4)) if m else (120, 4)
    out = ['<REAPER_PROJECT 0.1 "7.0" 0', "  RIPPLE 0 0", "  PANLAW 1", f"  TEMPO {bpm:g} {bpb} 4"]
    out += render_block(meta, rate, channels)
    out += ["  <NOTES 0 2"] + ["    |" + ln for ln in notes_lines(meta, items, work_rel)] + ["  >"]
    if meta["kind"] == "music":
        length = max(int(round(it["frames"] * rate / it["rate"])) for it in items)
        out += [f"  MARKER 1 0 {q(meta['name'])} 1 0 1 R", f"  MARKER 1 {seconds(length, rate)} \"\" 1"]
        if m.get("loop_start_bar"):
            loop_at = music.bar_sample(m["loop_start_bar"], m, rate)
            out.append(f"  MARKER 2 {seconds(loop_at, rate)} {q('loop start')} 0 0 1 R")
        out.append(f"  MARKER 3 {seconds(music.bar_sample(m['bars'], m, rate), rate)} {q('loop end')} 0 0 1 R")
    else:
        for k, it in enumerate(items, 1):
            out += [f"  MARKER {k} {seconds(it['start'], rate)} {q(it['name'])} 1 0 1 R",
                    f"  MARKER {k} {item_end(it, rate)[1]} \"\" 1"]
    groups = [(it["name"], [it]) for it in items] if meta["kind"] == "music" else [(meta["name"], items)]
    for track, members in groups:
        out += ["  <TRACK", f"    NAME {q(track)}", "    VOLPAN 1 0 -1 -1 1", "    MUTESOLO 0 0 0",
                f"    SEL {1 if meta['kind'] == 'music' else 0}", "    NCHAN 2", "    MAINSEND 1 0"]
        for it in members:
            out += ["    <ITEM", f"      POSITION {seconds(it['start'], rate)}",
                    f"      LENGTH {item_end(it, rate)[0]}", f"      LOOP {1 if it['kind'] in ('loop', 'stem') else 0}",
                    "      FADEIN 1 0 0 1 0 0 0", "      FADEOUT 1 0 0 1 0 0 0",
                    f"      NAME {q(it['name'])}", "      VOLPAN 1 0 1 -1", "      SOFFS 0",
                    f"      <SOURCE {SOURCE_TYPE[Path(it['media']).suffix.lower()]}",
                    f"        FILE {q(it['media'])}", "      >", "    >"]
        out.append("  >")
    out.append(">")
    return "\n".join(out) + "\n"


def top_level(lines):
    """[(index, depth)] for each line: depth 1 is the project's own settings, 2 a track's, 3 an item's ..."""
    depth, out = 0, []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == ">":                             # a block's closing line has its opening line's depth
            depth -= 1
            out.append((i, depth))
            continue
        out.append((i, depth))
        if s.startswith("<"):
            depth += 1
    return out


def render_copy_text(text, man, rate=None, keep_region=None):
    """The user's project with Wavesmith's render settings at rate (default the project's): top-level RENDER_* /
    SAMPLERATE lines and the RENDER_CFG block replaced; for music, the stem tracks selected (and only those), since
    REAPER renders selected tracks. keep_region(name) False leaves that region out (it renders at another rate);
    None when that leaves no region."""
    lines = text.replace("\r\n", "\n").split("\n")
    depths = top_level(lines)
    regions = [m for i, d in depths if d == 1 for m in [REGION.match(lines[i].strip())] if m
               and int(m.group(3)) & 1 and m.group(2).strip("\"'`")]
    if lines[0].startswith("<REAPER_PROJECT") and not regions:
        raise ToolError("the project has no named regions left: nothing would render (REAPER would stop at a "
                        "'Nothing to render' dialog)")
    # a region is two MARKER lines with the same index: its start (named) and its end (no name)
    drop = {m.group(1) for m in regions if keep_region and not keep_region(m.group(2).strip("\"'`"))}
    if regions and drop == {m.group(1) for m in regions}:
        return None
    keep, skip_until = [], None
    track_start, stems = None, {it["name"] for it in man["items"]}
    tracks = []                                  # (start, end) of each depth-1 <TRACK block
    for i, d in depths:
        s = lines[i].strip()
        if skip_until is not None:
            if i == skip_until:
                skip_until = None
            continue
        if d == 1 and s.split(" ")[0] in TOP_LEVEL_RENDER:
            continue
        if d == 1 and drop:
            m = REGION.match(s)
            if m and int(m.group(3)) & 1 and m.group(1) in drop:
                continue
        if d == 1 and s.startswith("<RENDER_CFG"):
            skip_until = next(j for j, dj in depths[i + 1:] if dj == 1 and lines[j].strip() == ">")
            continue
        keep.append(lines[i])
        if d == 1 and s.startswith("<TRACK"):
            track_start = len(keep) - 1
        if d == 1 and s == ">" and track_start is not None:
            tracks.append((track_start, len(keep) - 1))
            track_start = None
    if not keep or not keep[0].startswith("<REAPER_PROJECT"):
        raise ToolError("the .rpp does not start with <REAPER_PROJECT: not a REAPER project")
    if man["kind"] == "music":
        for start, end in reversed(tracks):      # from the end, so an inserted line moves no block still to do
            block = keep[start:end + 1]
            inner = top_level(block)
            name = next((block[j].strip()[5:].strip().strip('"\'`') for j, dj in inner
                         if dj == 1 and block[j].strip().startswith("NAME ")), "")
            sel = f"    SEL {1 if name in stems else 0}"
            j = next((j for j, dj in inner if dj == 1 and block[j].strip().startswith("SEL ")), None)
            if j is None:
                keep.insert(start + 1, sel)
            else:
                keep[start + j] = sel
    out = [keep[0]] + render_block(man, rate or man["rate"], man["channels"]) + keep[1:]
    return "\n".join(out)


def missing_media(text, work):
    """Media files the project names that are not there. Checked before REAPER runs: it is started with
    -ignoreerrors (E145), so a missing file would otherwise render as silence instead of stopping at a dialog."""
    out = []
    for m in MEDIA_FILE.finditer(text):
        name = m.group(1)[1:-1] if m.group(1)[:1] in "\"'`" else m.group(1)
        path = Path(name) if Path(name).is_absolute() or re.match(r"^[A-Za-z]:", name) else work / name
        if not path.is_file():
            out.append(name)
    return sorted(set(out))


def absolute_paths(text):
    """Absolute paths a project holds (media from outside its folder): they leak a local path when committed."""
    return sorted({m.group(1).strip() for m in ABS_PATH.finditer(text)})


# ---- finding and running REAPER ------------------------------------------------------------------------------------
def find_reaper(given=None):
    """REAPER's executable: --reaper, REAPER_BIN, the usual install folders, `reaper` on PATH; or None."""
    for cand in (given, os.environ.get(REAPER_ENV)):
        if cand:
            return cand if Path(cand).is_file() else None
    for cand in REAPER_CANDIDATES:
        p = Path(os.path.expanduser(cand))
        if p.is_file():
            return str(p)
    return shutil.which("reaper")


def launch_argv(exe):
    """The command that starts REAPER. A .py file is run with this Python: the exams' stand-in REAPER."""
    return [sys.executable, exe] if exe.lower().endswith(".py") else [exe]


def run_reaper(exe, project, timeout):
    """Renders project headless with a throwaway configuration folder. Returns REAPER's exit code."""
    cfg = Path(tempfile.mkdtemp(prefix="wavesmith_reaper_"))
    try:
        ini = cfg / "reaper.ini"
        ini.write_bytes(REAPER_INI.encode("ascii"))
        # -ignoreerrors: no load-error dialog to wait on (missing media was checked before this)
        argv = launch_argv(exe) + ["-newinst", "-nosplash", "-ignoreerrors", "-cfgfile", str(ini), "-renderproject",
                                   str(Path(project).resolve())]
        dbg(" ".join(argv))
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ToolError(f"REAPER did not start ({exe}): {exc}")
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()                           # only the REAPER this run started
            proc.wait(timeout=30)
            raise ToolError(f"REAPER did not finish within {timeout} s and was stopped: a dialog is probably waiting "
                            f"(open the project in REAPER and render once to see it), or raise --timeout")
    finally:
        shutil.rmtree(cfg, ignore_errors=True)


def readiness():
    """[(ok, line)] for `daw check`, `daw --help` and `wavesmith.py check`."""
    exe = find_reaper()
    if exe:
        return [(True, f"daw: REAPER found ({exe}): `daw reaper` and `daw reaper --reexport` are ready"),
                (True, "daw: `daw export` / `daw import` (any DAW) are ready")]
    env = os.environ.get(REAPER_ENV)
    why = f"{REAPER_ENV}={env} is not a file" if env else f"set {REAPER_ENV} to reaper.exe / the REAPER binary"
    return [(False, f"daw: REAPER not found ({why}): `daw reaper` still writes projects; --reexport needs REAPER"),
            (True, "daw: `daw export` / `daw import` (any DAW) are ready")]


# ---- writing the working folder ------------------------------------------------------------------------------------
def check_name(name):
    if not name_ok(name):
        raise ToolError(f"{name!r} cannot name a project (letters, digits, _ . - only, up to 64): pass --name")


def work_folder(args, root, name):
    check_name(name)
    work = Path(args.out) if args.out else root / DEFAULT_OUT / name
    if (work / MANIFEST).exists() and not args.overwrite:
        raise ToolError(f"{work.as_posix()} already holds a DAW project (re-export it, or --overwrite to start again; "
                        f"the old project is kept as .bak)")
    work.mkdir(parents=True, exist_ok=True)
    return work


def save_manifest(work, man):
    (work / MANIFEST).write_bytes((json.dumps(man, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def load_manifest(where):
    where = Path(where)
    work = where.parent if where.is_file() else where
    try:
        man = json.loads((work / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"no Wavesmith DAW project in {work.as_posix()} ({MANIFEST}: {exc}); make one with "
                        f"`daw reaper <set|track|folder>` or `daw export`")
    if man.get("version") != VERSION or not isinstance(man.get("items"), list):
        raise ToolError(f"{(work / MANIFEST).as_posix()} is not a version {VERSION} Wavesmith DAW manifest")
    # a manifest is a tracked file a pull request can carry: every path in it must stay inside the game
    for it in man["items"]:
        for key in ("file", "media") + (("original",) if "original" in it else ()):
            v = it.get(key)
            if not isinstance(v, str) or not v or v.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", v) \
                    or ".." in re.split(r"[\\/]", v):
                raise ToolError(f"{MANIFEST}: {key} {v!r} must be a plain relative path inside the game")
    if not isinstance(man.get("root"), str) or not UP_ONLY.match(man["root"]):
        raise ToolError(f"{MANIFEST}: root {man.get('root')!r} must be . or ../.. (the game root above this folder)")
    try:   # an edited manifest gets the same checks as a new project (#242)
        check_items(man["items"])
    except (KeyError, TypeError, AttributeError):
        raise ToolError(f"{(work / MANIFEST).as_posix()}: an item lacks its name or file")
    return work, man


def game_root(args, work, man):
    """The game root for --reexport and import: --root, else the current folder, which must be the root the project
    was made from (so neither a wrong folder nor an edited manifest can move where the game's files are written)."""
    if args.root:
        return Path(args.root)
    made = (work / man["root"]).resolve()
    if made != Path(".").resolve():
        raise ToolError(f"{(work / MANIFEST).as_posix()} was made from the game root {made.as_posix()}, not this "
                        f"folder: run it from the game root, or pass --root")
    return Path(".")


def start_manifest(args, root, work, meta, items, route):
    up = posix_rel(root, work)
    if not UP_ONLY.match(up):
        raise ToolError(f"{work.as_posix()} is not inside the game root {root.as_posix()}: keep the working folder "
                        f"inside the game (its manifest names the root as a path up from it)")
    rate, channels = project_shape(items, route)
    lay_out(meta, items, rate)
    media = work / (MEDIA_DIR if route == "reaper" else STEMS_DIR)
    # never emptied: REAPER records into "Media" beside the project by default, and on Windows that is this folder
    media.mkdir(parents=True, exist_ok=True)
    keep_edited_copies(work)
    for it in items:
        src = root / it["file"]
        if route == "reaper" or Path(it["file"]).suffix.lower() == ".wav":
            dst = media / (it["name"] + Path(it["file"]).suffix.lower())
            shutil.copyfile(src, dst)
        else:                                   # the universal route hands every DAW a WAV
            dst = media / (it["name"] + ".wav")
            chans, r, loop = read_any(src)
            audioio.write_audio(dst, chans, r, loop=loop)
            keep = work / ORIGINALS_DIR / (it["name"] + Path(it["file"]).suffix.lower())
            keep.parent.mkdir(exist_ok=True)
            shutil.copyfile(src, keep)
            it["original"] = keep.relative_to(work).as_posix()
        it["media"] = dst.relative_to(work).as_posix()
        it["media_sha256"] = sha256(dst)        # the baseline a render is compared with: checked on the way back
    man = dict(meta, version=VERSION, route=route, root=up, rate=rate, channels=channels,
               items=items, logged=[], written={})
    man["about"] = ("Wavesmith DAW round trip (tools/audio/wavesmith/daw.py): which region or track is which game "
                    "file. Paths are relative: root from this folder, file from the root, media from this folder.")
    return man


def keep_edited_copies(work):
    """Before --overwrite copies the originals in again: every working copy the old project recorded that has
    changed since (a sound edited in place in media/, a stem, an original) goes to backup/<time>/ (#243)."""
    try:
        old = json.loads((work / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    changed = []
    for it in old.get("items", []) if isinstance(old, dict) else []:
        if not isinstance(it, dict):
            continue
        for key, want in (("media", it.get("media_sha256")), ("original", it.get("sha256"))):
            rel = it.get(key)
            if not isinstance(rel, str) or ".." in re.split(r"[\\/]", rel) or Path(rel).is_absolute():
                continue
            f = work / rel
            if f.is_file() and (not want or sha256(f) != want):
                changed.append(rel)
    if not changed:
        return
    dest = work / BACKUP_DIR / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for rel in changed:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work / rel, dest / rel)
    print(f"[note] {len(changed)} edited working cop{'y' if len(changed) == 1 else 'ies'} kept in "
          f"{posix_rel(dest, work)}/ before the originals were copied in again: {', '.join(changed[:3])}"
          + (" ..." if len(changed) > 3 else ""))


def cmd_reaper(args):
    if args.reexport:
        return reexport(args)
    if not args.source:
        raise ToolError("name a sound set, a music track or a folder (or --reexport <project folder>)")
    root = Path(args.root or ".")
    meta, items = collect(args, root)
    check_items(items)
    work = work_folder(args, root, meta["name"])
    rpp = work / f"{meta['name']}.rpp"
    if rpp.exists():
        shutil.copyfile(rpp, rpp.with_name(rpp.name + ".bak"))
    man = start_manifest(args, root, work, meta, items, "reaper")
    man["project"] = rpp.name
    work_rel = no_breaks(posix_rel(work, root), "the working folder")
    no_breaks(meta["source"], "the source")
    rpp.write_bytes(rpp_text(man, items, man["rate"], man["channels"], work_rel).encode("utf-8"))
    if meta["kind"] == "music":
        write_midi(args, man, work)
    save_manifest(work, man)
    print(f"[ OK ] {rpp.as_posix()}: {len(items)} {'stem track' if meta['kind'] == 'music' else 'region'}(s), "
          f"{man['rate']} Hz, media copied to {MEDIA_DIR}/")
    print(f"[next] open it in REAPER, edit, save; then: wavesmith.py daw reaper --reexport {work_rel}")
    if not find_reaper(args.reaper):
        print(f"[note] REAPER was not found here ({REAPER_ENV}): the project is written; --reexport needs REAPER")
    return 0


def write_midi(args, man, work):
    """<name>.mid: the song's notes when --song is given, else the tempo and bar grid (markers on each bar)."""
    m, out = man["music"], work / f"{man['name']}.mid"
    if getattr(args, "song", None):
        try:
            info = midifile.write_song(args.song, out, man["name"])
        except midifile.MidiError as exc:
            raise ToolError(str(exc))
        print(f"[ OK ] {out.as_posix()}: {info['notes']} note(s) from {Path(args.song).as_posix()}")
    else:
        bpb = m.get("beats_per_bar", 4)
        marks = [(midifile.bar_ticks(b, bpb), f"bar {b + 1}") for b in range(m["bars"])]
        if m.get("loop_start_bar"):
            marks.append((midifile.bar_ticks(m["loop_start_bar"], bpb), "loop start"))
        out.write_bytes(midifile.smf_bytes([midifile.conductor(m["bpm"], bpb, man["name"], marks)]))
        print(f"[ OK ] {out.as_posix()}: tempo {m['bpm']:g} BPM and {m['bars']} bars (no notes: pass --song "
              f"<song.json> for a chiptune piece's notes)")


def cmd_export(args):
    root = Path(args.root or ".")
    meta, items = collect(args, root)
    check_items(items)
    check_name(meta["name"])
    work = Path(args.folder)
    if (work / MANIFEST).exists() and not args.overwrite:
        raise ToolError(f"{work.as_posix()} already holds a DAW export (import it, or --overwrite)")
    work.mkdir(parents=True, exist_ok=True)
    (work / RENDERS_DIR).mkdir(exist_ok=True)
    man = start_manifest(args, root, work, meta, items, "export")
    rate = man["rate"]
    rows = []                                  # (name, start s, end s)
    if meta["kind"] == "music":
        length = max(it["frames"] for it in items)
        rows.append((meta["name"], 0.0, length / rate))
        write_midi(args, man, work)
    else:
        for it in items:
            rows.append((it["name"], it["start"] / rate, it["start"] / rate + it["frames"] / it["rate"]))
        if all(it["rate"] == rate for it in items):
            seq = [[0.0] * (items[-1]["start"] + items[-1]["frames"]) for _ in range(man["channels"])]
            for it in items:
                chans, _, _ = read_any(work / it["media"])
                for c in range(man["channels"]):
                    src = chans[min(c, len(chans) - 1)]
                    seq[c][it["start"]:it["start"] + len(src)] = src
            audioio.write_audio(work / f"{meta['name']}_sequence.wav", seq, rate)
        else:
            print("[note] the sounds have different sample rates: no sequence file (the stems are there)")
    with open(work / "markers.csv", "w", encoding="utf-8", newline="\n") as f:
        f.write("#,Name,Start,End,Length\n")
        for k, (n, a, b) in enumerate(rows, 1):
            f.write(f"R{k},{n},{a:.6f},{b:.6f},{b - a:.6f}\n")
    with open(work / "markers.txt", "w", encoding="utf-8", newline="\n") as f:
        for n, a, b in rows:
            f.write(f"{a:.6f}\t{b:.6f}\t{n}\n")
    (work / "HOW_TO.txt").write_bytes(how_to(man, posix_rel(work, root)).encode("utf-8"))
    save_manifest(work, man)
    print(f"[ OK ] {work.as_posix()}: {len(items)} stem(s) in {STEMS_DIR}/, markers.csv + markers.txt"
          + (f", {meta['name']}_sequence.wav" if meta["kind"] != "music" and (work / f"{meta['name']}_sequence.wav")
             .exists() else "") + (f", {meta['name']}.mid" if meta["kind"] == "music" else ""))
    print(f"[next] edit in your DAW, render each sound as {RENDERS_DIR}/<name>.wav (HOW_TO.txt), then: "
          f"wavesmith.py daw import {posix_rel(work, root)}")
    return 0


def how_to(man, work_rel):
    music_piece = man["kind"] == "music"
    lines = [f"Wavesmith DAW export: {man['name']} ({man['source']})", "",
             "1. Bring it into your DAW:",
             f"   - {STEMS_DIR}/: one WAV per {'stem; start them all at bar 1, together' if music_piece else 'sound'}"]
    if music_piece:
        lines.append(f"   - {man['name']}.mid: tempo, time signature and bar markers (the notes too, for a chiptune "
                     f"piece exported with --song)")
    else:
        lines.append(f"   - {man['name']}_sequence.wav: every sound end to end ({GAP_S:g} s apart), for DAWs that "
                     "render by region or marker")
    lines += ["   - markers.csv (REAPER's region list format) and markers.txt (an Audacity label track: File >",
              "     Import > Labels) name each sound on that timeline",
              "2. Edit. Keep the names.",
              f"3. Render each {'stem' if music_piece else 'sound'} you changed to {RENDERS_DIR}/<name>.wav, the name "
              "as in the list below (sounds you did not render stay as they are). WAV, any bit depth, the same "
              "sample rate.",
              "   Audacity: File > Export > Export Multiple, split by labels, name files by label.",
              "   FL Studio, Ableton Live, Bitwig: export each stem or region to its own file (verify the menu names "
              "in your version).",
              f"4. Back to the game: python tools/audio/wavesmith/wavesmith.py daw import {work_rel}", ""]
    lines += targets(man, man["items"]) + ["", "Names:"]
    lines += [f"  {it['name']} -> {it['file']}" for it in man["items"]]
    return "\n".join(lines) + "\n"


# ---- coming back ---------------------------------------------------------------------------------------------------
def reexport(args):
    work, man = load_manifest(args.reexport)
    if man.get("route") != "reaper":
        raise ToolError(f"{work.as_posix()} is a `daw export` folder: bring it back with `daw import`")
    exe = find_reaper(args.reaper)
    if not exe:
        raise ToolError(f"REAPER not found: set {REAPER_ENV} (or --reaper) to the REAPER program "
                        f"(Windows: C:\\Program Files\\REAPER (x64)\\reaper.exe)")
    rpp = work / man["project"]
    try:
        text = rpp.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError(f"cannot read {rpp.as_posix()}: {exc}")
    leaks = absolute_paths(text)
    if leaks:
        print(f"[warn] {rpp.name} names {len(leaks)} file(s) by absolute path (media from outside its folder): "
              f"committing it would publish that path. In REAPER: File > Save project as, with 'Copy all media into "
              f"project directory'. First: {leaks[0]}")
    gone = missing_media(text, work)
    if gone:
        raise ToolError(f"{rpp.name} uses {len(gone)} media file(s) that are not there: {', '.join(gone[:3])}"
                        + (" ..." if len(gone) > 3 else "") + " (put them back, or remove those items in REAPER)")
    renders = work / RENDER_DIR
    for old in (renders.glob("*.wav") if renders.is_dir() else []):     # last run's renders, so none is taken twice
        old.unlink()
    copy, codes = work / RENDER_COPY, []
    for rate, keep in render_passes(man):
        body = render_copy_text(text, man, rate, keep)
        if body is None:                         # every region of this rate renamed or removed: nothing to render
            continue
        copy.write_bytes(body.encode("utf-8"))
        try:
            codes.append(run_reaper(exe, copy, args.timeout))
        finally:
            discard(copy)
    got = {p.stem: p for p in sorted(renders.glob("*.wav"))} if renders.is_dir() else {}
    if any(c != 0 for c in codes):
        # a REAPER that failed may have rendered only part, or half a file: nothing of it goes into the game (#242)
        print(f"[FAIL] REAPER exited {', '.join(str(c) for c in codes)} (rendered {len(got)} file(s)): nothing was "
              f"brought back. Open {rpp.name} in REAPER and render once to see what it says")
        return 1
    print(f"[ OK ] REAPER rendered {len(got)} file(s) (exit {', '.join(str(c) for c in codes)})")
    if not got:
        print(f"[FAIL] REAPER rendered nothing into {RENDER_DIR}/: open {rpp.name} in REAPER and check its regions "
              f"{'and tracks ' if man['kind'] == 'music' else ''}are still there")
        return 1
    return bring_back(args, work, man, got, "REAPER", strict=True)


def render_passes(man):
    """[(rate, keep_region)]: one REAPER render per sample rate, so a sound at another rate than the project comes
    back at its own rate, sample for sample, instead of resampled. The project's rate goes first and also renders
    regions no sound is called (so they are reported as extra)."""
    if man["kind"] == "music":
        return [(man["rate"], None)]
    at = {it["name"]: it["rate"] for it in man["items"]}
    others = sorted({r for r in at.values() if r != man["rate"]})
    if not others:
        return [(man["rate"], None)]
    return [(man["rate"], lambda n: at.get(n, man["rate"]) == man["rate"])] + \
        [(r, lambda n, r=r: at.get(n) == r) for r in others]


def norm_name(name):
    return re.sub(r"[\s\-_]+", "_", name.strip().lower())


def match_renders(man, folder):
    """({item name: render path}, notes, extras): exact names first, then names that differ only in letter case,
    spaces or dashes; a file matching none is extra (a near miss is named, never guessed)."""
    files = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT) \
        if Path(folder).is_dir() else []
    names = [it["name"] for it in man["items"]]
    found, notes, extras = {}, [], []
    loose = {norm_name(n): n for n in names}
    for p in files:
        if p.stem in names and p.stem not in found:
            found[p.stem] = p
    for p in files:
        if p in found.values():
            continue
        n = loose.get(norm_name(p.stem))
        if n and n not in found:
            found[n] = p
            notes.append(f"[note] {p.name} taken as {n} (the name differs only in case, spaces or dashes)")
            continue
        near = difflib.get_close_matches(p.stem, [n for n in names if n not in found], n=1, cutoff=0.6)
        extras.append(f"{p.name}" + (f" (meant {near[0]}? rename it to {near[0]}{p.suffix})" if near else
                                     " (no sound by that name)"))
    return found, notes, extras


def cmd_import(args):
    work, man = load_manifest(args.folder)
    folder = Path(args.renders) if args.renders else work / RENDERS_DIR
    if not folder.is_dir():
        raise ToolError(f"no renders folder {folder.as_posix()}: render your edits there as <name>.wav")
    found, notes, extras = match_renders(man, folder)
    for n in notes:
        print(n)
    return bring_back(args, work, man, found, args.daw, strict=False, extras=extras)


def baseline(work, root, it, game_sha):
    """(channels, rate) of the original a render is compared with: the working folder's copy (media/ or stems/)
    while it is as it was made, else the game's file while it is the original; None when neither is (then any
    render counts as an edit). A copy changed since (an edit saved over it) is said."""
    media = work / it["media"]
    want = it.get("media_sha256")
    if media.is_file() and (not want or sha256(media) == want):
        return read_any(media)[:2]
    print(f"[note] {it['media']} " + ("changed since the project was made (an edit saved into the copy itself): "
                                      "the render counts as an edit" if media.is_file() else "is gone"))
    return read_any(root / it["file"])[:2] if game_sha == it["sha256"] else None


def original_copy(work, it):
    """The working folder's copy of the original game file (originals/ for an OGG or FLAC exported as a WAV stem,
    else media/ or stems/), or None when it is gone or no longer the original's bytes."""
    p = work / it.get("original", it["media"])
    return p if p.is_file() and sha256(p) == it["sha256"] else None


def same_audio(a, ra, b, rb):
    if ra != rb or len(a) != len(b) or len(a[0]) != len(b[0]):
        return False
    return all(abs(x - y) <= SAME_TOL for ca, cb in zip(a, b) for x, y in zip(ca, cb))


def gain_for(chans, rate, kind, bus, target):
    """(gain dB, note) to set one sound to its bus level; true peak capped (sound_sets.set_level's rule)."""
    now, how = sound_sets.level(chans, rate, kind)
    if now is None:
        raise ToolError("silent")
    goal = loudness.ASWG[target] + loudness.HOUSE[bus]
    gain, note = goal - now, f"{how} {now:.1f} -> {goal:.0f} LUFS"
    tp = loudness.db(loudness.true_peak(chans, rate))
    if tp + gain > sound_sets.TP_CEILING:
        gain, note = sound_sets.TP_CEILING - tp, note + f" (capped by true peak at {sound_sets.TP_CEILING:.0f} dBTP)"
    return gain, note


def mix_gain(stems, rate, bus, target):
    """(gain dB, note) for music: the mix of every stem to the music level, unless it is already within tolerance."""
    frames, nch = max(len(c[0]) for c in stems), max(len(c) for c in stems)
    mix = [[0.0] * frames for _ in range(nch)]
    for chans in stems:
        for c in range(nch):
            src = chans[min(c, len(chans) - 1)]
            dst = mix[c]
            for i, v in enumerate(src):
                dst[i] += v
    m = loudness.measure_channels(mix, rate)
    if m["integrated_lufs"] is None:
        raise ToolError("the stems mix to silence")
    goal = loudness.ASWG[target] + loudness.HOUSE[bus]
    now, tp = m["integrated_lufs"], m["true_peak_dbtp"]
    if abs(now - goal) <= sound_sets.BUS_TOLERANCE_LU and tp <= sound_sets.TP_CEILING:
        return 0.0, f"mix {now:.1f} LUFS, within {sound_sets.BUS_TOLERANCE_LU:.0f} LU of {goal:.0f}: kept as edited"
    gain = goal - now
    note = f"mix {now:.1f} -> {goal:.0f} LUFS"
    if tp + gain > sound_sets.TP_CEILING:
        gain, note = sound_sets.TP_CEILING - tp, note + f" (capped by true peak at {sound_sets.TP_CEILING:.0f} dBTP)"
    return gain, note


def loop_for(it, frames, man):
    """The loop to write: the original one when the length is unchanged, else the bar grid (music) or the whole file
    (loops), with a warning; one-shots have none."""
    if it.get("loop") and frames == it["frames"]:
        return tuple(it["loop"]), None
    if man["kind"] == "music":
        start, end = music.loop_points(man["music"], man["rate"])
        if frames >= end:
            return (start, end - 1), f"its length changed: loop put back on the bar grid ({start}..{end - 1})"
        return None, f"its length changed and it is now shorter than {man['music']['bars']} bars: no loop point"
    if it["kind"] == "loop":
        return (0, frames - 1), "its length changed: the loop is now the whole file (check the seam by ear)"
    return None, None


def discard(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def temp_beside(game):
    """A new, unique, empty temp file next to game (a fixed name could be a user's file, #243)."""
    fd, tmp = tempfile.mkstemp(prefix=f".{game.stem}.", suffix=".daw_tmp" + game.suffix, dir=str(game.parent))
    os.close(fd)
    return Path(tmp)


def inside_game(root, game):
    """True when game, with every symlink resolved, is still under the game root (#243)."""
    try:
        game.resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def land(make, tmp, game):
    """tmp in place of game (make() writes tmp first, when given): None, or why not. tmp never stays behind."""
    try:
        if make:
            make()
        os.replace(str(tmp), str(game))
        return None
    except OSError as exc:
        discard(tmp)
        return exc.strerror or str(exc)


def cannot_write(it, why):
    return f"{it['file']}: could not be written ({why}): close whatever holds it (the game, an editor) and run again"


def bring_back(args, work, man, renders, daw, strict, extras=()):
    """Renders -> the game's files. strict (REAPER): a missing region is a problem; otherwise a sound not rendered
    is simply kept."""
    root = game_root(args, work, man)
    problems, kept, pending = [], [], []
    before = {}
    for it in man["items"]:
        game = root / it["file"]
        before[it["file"]] = sha256(game) if game.is_file() else None
    audio, same = {}, []                               # name -> (render channels, rate); names rendered as they were
    for it in man["items"]:
        r = renders.get(it["name"])
        if r is not None and not inside_game(root, root / it["file"]):
            problems.append(f"{it['file']}: a symlinked folder takes it outside the game root: not written")
            continue
        if r is None:
            (problems if strict else kept).append(
                f"{it['name']}: no render" + (" (its region was renamed or removed? the game's file is kept)"
                                              if strict else ", kept as it is"))
            continue
        chans, rate, _ = read_any(r)
        want = man["rate"] if man["kind"] == "music" else it["rate"]
        if rate != want:
            # stems play together at the track's rate (#242), and a sound keeps its own: a render at another rate
            # would be taken as an edit and written at the wrong rate (#194). REAPER renders each rate on its own.
            problems.append(f"{it['name']}: rendered at {rate} Hz, the game's file is {want} Hz: render it at "
                            f"{want} Hz (the game's file is kept)")
            continue
        if it["channels"] == 1 and len(chans) == 2 and all(abs(x - y) <= SAME_TOL for x, y in zip(*chans)):
            chans = chans[:1]                              # a mono sound rendered on a stereo bus: mono again
        audio[it["name"]] = (chans, rate)
        base = baseline(work, root, it, before[it["file"]])
        if base is not None and same_audio(base[0], base[1], chans, rate):
            same.append(it)
        else:
            pending.append((it, chans, rate))
    for x in extras:
        problems.append(f"extra render {x}")
    if strict:
        names = {it["name"] for it in man["items"]}
        problems += [f"extra render {n}.wav: no sound by that name (a new or renamed region? only the listed "
                     f"names come back)" for n in sorted(set(renders) - names)]
    # levels: per sound, or one gain for the whole music mix. The mix is made from the renders (the project as it
    # is now), never from the game's files, so a second run lands on the same bytes as the first.
    gains, levelled_only = {}, set()
    if pending and man["kind"] == "music":
        stems = [audio[it["name"]][0] if it["name"] in audio else read_any(work / it["media"])[0]
                 for it in man["items"]]
        g, note = mix_gain(stems, man["rate"], "music", man["target"])
        if g:   # the mix moves: every stem moves with it, also the ones not edited
            for it in list(same):
                pending.append((it,) + audio[it["name"]])
                levelled_only.add(it["name"])
                same.remove(it)
            missing = [it for it in man["items"] if it["name"] not in audio]
            if missing:
                # one gain for the whole mix: written to some stems only, the mix would be left half moved (#242)
                problems += [f"{it['name']}: no render, but the mix moved by {g:+.2f} dB: render it too; no stem "
                             f"was written" for it in missing]
                kept += [f"{it['name']}: not written (the mix needs every stem)" for it, _, _ in pending]
                pending = []
        for it, _, _ in pending:
            gains[it["name"]] = (g, note)
    written, report = [], []
    try:   # a run stopped part-way still records the files it wrote, so the next run does not refuse them
        # rendered as they were: kept; or, when an earlier round trip wrote an edit now undone, the original back
        for it in same:
            cur, game = before[it["file"]], root / it["file"]
            if cur == it["sha256"]:
                kept.append(f"{it['name']}: unchanged")
            elif cur == (man.get("written") or {}).get(it["file"]) and not original_copy(work, it):
                kept.append(f"{it['name']}: rendered as the original, but the working folder's copy of the original "
                            f"is gone or changed: the game keeps the last edit")
            elif cur == (man.get("written") or {}).get(it["file"]):
                if args.dry_run:
                    report.append(f"[dry ] {it['file']}: the original would be put back (the edit was undone)")
                    continue
                tmp = temp_beside(game)
                failed = land(lambda: shutil.copyfile(original_copy(work, it), tmp), tmp, game)
                if failed:
                    problems.append(cannot_write(it, failed))
                    continue
                written.append({"item": it, "sha256": sha256(game), "gain_db": 0.0, "before": cur,
                                "note": f"the edit was undone in {daw}: the original put back",
                                "frames": it["frames"], "channels": it["channels"]})
                report.append(f"[ OK ] {it['file']}: the edit was undone in {daw}, the original is back")
            else:
                kept.append(f"{it['name']}: unchanged in {daw} (the game's file changed elsewhere and is left as "
                            f"it is)")
        for it, chans, rate in pending:
            try:
                if it["name"] not in gains:
                    gains[it["name"]] = gain_for(chans, rate, it["kind"], it["bus"], man["target"])
            except ToolError as exc:
                problems.append(f"{it['name']}: {exc}")
                continue
            g, note = gains[it["name"]]
            k = 10 ** (g / 20)
            out = [[s * k for s in c] for c in chans]
            loop, warn = loop_for(it, len(out[0]), man)
            game = root / it["file"]
            try:
                tmp = temp_beside(game)
                audioio.write_audio(tmp, out, rate, loop=loop)
            except (audioio.AudioIOError, OSError) as exc:
                discard(tmp)
                problems.append(f"{it['name']}: {exc}")
                continue
            new_sha = sha256(tmp)
            allowed = {it["sha256"], (man.get("written") or {}).get(it["file"])}
            if before[it["file"]] == new_sha:
                discard(tmp)
                what = "moved with the mix" if it["name"] in levelled_only else "edited"
                kept.append(f"{it['name']}: {what}, and the game already has this version (an earlier re-export)")
                continue
            if before[it["file"]] not in allowed and not args.force:
                discard(tmp)
                problems.append(f"{it['file']} changed in the game since the project was made (not by this round "
                                f"trip): not overwritten (--force replaces it)")
                continue
            if args.dry_run:
                discard(tmp)
                report.append(f"[dry ] {it['file']}: would be written ({note})")
                continue
            failed = land(None, tmp, game)
            if failed:
                problems.append(cannot_write(it, failed))
                continue
            written.append({"item": it, "sha256": new_sha, "gain_db": round(g, 2),
                            "note": note + ("; not edited, moved with the mix" if it["name"] in levelled_only else ""),
                            "before": before[it["file"]], "frames": len(out[0]), "channels": len(out)})
            how = "not edited, moved with the mix" if it["name"] in levelled_only else f"hand-edited in {daw}"
            report.append(f"[ OK ] {it['file']}: {how}, {g:+.2f} dB ({note})")
            if warn:
                report.append(f"[warn] {it['file']}: {warn}")
    except BaseException:
        if written:
            stamp(work, man, written, daw, root)
        raise
    for ln in report:
        print(ln)
    for ln in kept:
        print(f"[keep] {ln}")
    # nothing else moved: every game file not written still has the bytes it had before this run
    for it in man["items"]:
        game = root / it["file"]
        now = sha256(game) if game.is_file() else None
        if it["file"] not in {w["item"]["file"] for w in written} and now != before[it["file"]]:
            problems.append(f"{it['file']} changed during the re-export although nothing was written to it")
    if written:
        stamp(work, man, written, daw, root)
    for p in problems:
        print(f"[FAIL] {p}")
    print(f"[{'FAIL' if problems else ' OK '}] {len(written)} file(s) written, {len(kept)} kept, "
          f"{len(problems)} problem(s)" + (" (dry run: nothing written)" if args.dry_run else ""))
    return 1 if problems else 0


# ---- records: sidecars, ASSET_LOG, manifest --------------------------------------------------------------------------
def sidecar_path(game):
    for suffix in (".gen.json", ".sfx.json"):
        p = game.with_suffix(suffix)
        if p.is_file():
            return p
    return None


def stamp(work, man, written, daw, root):
    today = datetime.date.today().isoformat()
    work_rel = posix_rel(work, root)
    back = {w["item"]["file"] for w in written if w["sha256"] == w["item"]["sha256"]}   # originals put back
    for w in written:
        it, game = w["item"], root / w["item"]["file"]
        side = sidecar_path(game)
        meta = read_sidecar(game)
        if meta is not None:
            if it["file"] in back:          # the edit is gone: so is its record
                meta["hand_edits"] = [e for e in meta.get("hand_edits", []) if e.get("project") != work_rel]
                if not meta["hand_edits"]:
                    del meta["hand_edits"]
            else:
                meta.setdefault("hand_edits", []).append({"daw": daw, "date": today, "project": work_rel,
                                                          "gain_db": w["gain_db"], "sha256": w["sha256"]})
            side.write_bytes((json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        if it["file"] in back:
            man.setdefault("written", {}).pop(it["file"], None)
        else:
            man.setdefault("written", {})[it["file"]] = w["sha256"]
    man["logged"] = sorted((set(man.get("logged", [])) | {w["item"]["file"] for w in written}) - back)
    if man["logged"]:
        log_row(root, work_rel, man, written, daw, today)
    else:
        print(f"[note] every edit from {work_rel} is undone: its ASSET_LOG row (if any) is out of date, delete it")
    save_manifest(work, man)


def read_sidecar(game):
    side = sidecar_path(game)
    try:
        meta = json.loads(side.read_text(encoding="utf-8")) if side else None
    except (OSError, ValueError):
        meta = None
    return meta if isinstance(meta, dict) else None


def log_row(root, work_rel, man, written, daw, today):
    try:
        import fetch_asset
    except ImportError:
        print("[warn] the kit's tools/fetch_asset.py was not found: no ASSET_LOG row (log the edit by hand)")
        return
    log_path = root / fetch_asset.ASSET_LOG
    if not log_path.is_file():
        print(f"[warn] {fetch_asset.ASSET_LOG.as_posix()} not found under the game root: no row written (log the "
              f"edit by hand: Modified? yes)")
        return
    text = log_path.read_text(encoding="utf-8")
    key = f"{LOG_KEY} `{fetch_asset.md_cell(work_rel)}`"
    existing = [ln for ln in text.splitlines() if ln.startswith("| A-") and key in ln]
    if existing:
        aid, fill = existing[0].split("|")[1].strip(), False
    else:
        num, fill = fetch_asset.next_asset_id(text)
        aid = f"A-{num:04d}"
    files = man["logged"]
    folder = os.path.commonpath(files).replace("\\", "/") if len(files) > 1 else ""
    cell = fetch_asset.md_cell
    shown = f"`{cell(folder)}/` ({len(files)} files)" if folder and len(files) > 3 else \
        ", ".join(f"`{cell(f)}`" for f in files)
    kind = "music" if man["kind"] == "music" else ("voice" if all(it["bus"] == "dialogue" for it in man["items"])
                                                   else "sfx")
    origins = {f: read_sidecar(root / f) for f in files}
    all_meta = [m for m in origins.values() if m]
    licenses = sorted({m.get("license") for m in all_meta if m.get("license")})
    ai = "pre-generated" if any(m.get("tool") not in CODE_TOOLS or m.get("model") for m in all_meta) \
        else "no"
    unknown = [f for f in files if not (origins.get(f) or {})]
    lic = "; ".join(licenses + ["hand edit: own work"]) if licenses else \
        "hand edit: own work; the originals' licences: see their own rows"
    notes = (f"edited by hand in {daw} (Wavesmith daw {man['route']}), re-normalized to the house level "
             f"({man['target']})" + (f"; no sidecar for {len(unknown)} file(s): their own rows decide AI-assisted"
                                     if unknown else ""))
    row = (f"| {aid} | {kind} | {shown} | hand-edited in {fetch_asset.md_cell(daw)} from the game's sounds, {key} "
           f"| the game's sound designer (hand edit) | {fetch_asset.md_cell(lic)} |  | {ai} | yes | {today} "
           f"| {fetch_asset.md_cell(notes)} |")
    try:
        new_text = text.replace(existing[0], row, 1) if existing else fetch_asset.add_log_row(text, row, fill)
    except fetch_asset.UsageError as exc:
        print(f"[warn] no ASSET_LOG row: {exc}")
        return
    log_path.write_bytes(new_text.encode("utf-8"))
    ev = [f"{aid}  {kind}  hand-edited in {daw}, logged {today} with tools/audio/wavesmith/daw.py "
          f"(project {work_rel}, {man['source']})"]
    for w in written:
        it = w["item"]
        ev.append(f"File     : {it['file']}  SHA-256 {w['sha256']}  (original {it['sha256']})  gain {w['gain_db']:+.2f}"
                  f" dB  {w['note']}  {w['channels']} ch, {w['frames']} frames")
    lic_dir = root / fetch_asset.LICENSE_DIR
    lic_dir.mkdir(parents=True, exist_ok=True)
    ev_path = lic_dir / f"{aid}.txt"
    old = ev_path.read_text(encoding="utf-8").rstrip("\n") + "\n" if existing and ev_path.is_file() else ""
    ev_path.write_bytes((old + "\n".join(ev) + "\n").encode("utf-8"))
    print(f"[ OK ] {aid} {'updated in' if existing else 'added to'} {fetch_asset.ASSET_LOG.as_posix()} "
          f"(Modified? yes), evidence {(fetch_asset.LICENSE_DIR / (aid + '.txt')).as_posix()}")


def cmd_check(args):
    for ok, line in readiness():
        print(f"[{' OK ' if ok else 'note'}] {line}")
    return 0


def build_parser():
    ready = "; ".join(line for _, line in readiness())
    ap = argparse.ArgumentParser(
        description="Edit a game's sounds by hand in a DAW and bring them back levelled, checked and logged. "
                    "REAPER: a real project rendered back headless. Any other DAW (FL Studio, Ableton Live, Bitwig, "
                    "Ardour, LMMS, Audacity): stems, MIDI and markers out, renders back in by name.",
        epilog=f"Ready here: {ready}. Exit codes: 0 ok, 1 something came back wrong, 2 usage or REAPER missing.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", help="tracebacks and the REAPER command line")
    common.add_argument("--root", help="the game's root folder (default: here; --reexport and import check that "
                                       "the project was made from here)")
    src = argparse.ArgumentParser(add_help=False)
    src.add_argument("--sets", default=DEFAULT_SETS, help=f"sound sets file under the root ({DEFAULT_SETS})")
    src.add_argument("--music", default=DEFAULT_MUSIC, help=f"music file under the root ({DEFAULT_MUSIC})")
    src.add_argument("--audio-root", default=DEFAULT_AUDIO_ROOT,
                     help=f"what music.json's stem paths are relative to ({DEFAULT_AUDIO_ROOT})")
    src.add_argument("--kind", choices=("set", "music"), help="when a name is both a set and a music track")
    src.add_argument("--bus", choices=list(loudness.HOUSE), help="a folder's bus (its loudness target)")
    src.add_argument("--target", choices=list(loudness.ASWG), default="home",
                     help="loudness target for music and folders (sets use their own file's)")
    src.add_argument("--name", help="the project's name (default: the set, track or folder name)")
    src.add_argument("--song", help="music: a chiptune song file whose notes go into <name>.mid")
    src.add_argument("--overwrite", action="store_true", help="replace an existing project or export")
    back = argparse.ArgumentParser(add_help=False)
    back.add_argument("--force", action="store_true",
                      help="overwrite game files that changed since the project was made")
    back.add_argument("--dry-run", action="store_true", help="say what would be written, write nothing")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("reaper", parents=[common, src, back],
                       help="write a REAPER project, or --reexport one back into the game",
                       epilog=f"Ready here: {ready}.")
    r.add_argument("source", nargs="?", help="a sound set, a music track, or a folder of sounds")
    r.add_argument("--out", help=f"the project folder (default {DEFAULT_OUT}/<name> under the root)")
    r.add_argument("--reexport", metavar="PROJECT", help="the project folder (or its .rpp) to render back")
    r.add_argument("--reaper", help=f"the REAPER program (default: {REAPER_ENV}, then the usual install folders)")
    r.add_argument("--timeout", type=int, default=REAPER_TIMEOUT_S, help="seconds REAPER may take to render")
    e = sub.add_parser("export", parents=[common, src], help="stems, MIDI and markers for any DAW")
    e.add_argument("source", help="a sound set, a music track, or a folder of sounds")
    e.add_argument("folder", help="where to write them (your renders come back into its renders/)")
    i = sub.add_parser("import", parents=[common, back], help="bring a DAW's renders back by name")
    i.add_argument("folder", help="the folder `daw export` wrote")
    i.add_argument("--renders", help=f"where the renders are (default: <folder>/{RENDERS_DIR})")
    i.add_argument("--daw", default="a DAW", help="the DAW's name for the asset log (e.g. \"FL Studio\")")
    sub.add_parser("check", parents=[common], help="is REAPER here?")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    DEBUG = args.debug
    try:
        return {"reaper": cmd_reaper, "export": cmd_export, "import": cmd_import, "check": cmd_check}[args.cmd](args)
    except (ToolError, sound_sets.ToolError, music.ToolError, midifile.MidiError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, audioio.AudioIOError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
