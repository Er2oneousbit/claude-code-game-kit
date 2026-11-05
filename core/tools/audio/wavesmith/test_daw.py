#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_daw.py
# Purpose : Exam for daw.py, the DAW round trip. Offline: a stand-in REAPER (a Python script that reads the .rpp and
#           renders its regions or selected tracks the way REAPER does: items, item and track volume, fade-outs,
#           24-bit WAV out) checks the golden .rpp text, that no project file holds a drive letter or a user folder,
#           an untouched round trip that changes no byte, edits that come back at their bus level with an ASSET_LOG
#           row (Modified? yes), sidecar entries and evidence, a second run that changes nothing, a file changed in
#           the game meanwhile (kept; --force), renamed regions, render settings changed while editing, music stems
#           levelled by their mix with the stem tracks deselected, the throwaway -cfgfile (in the temp folder,
#           deleted afterwards, Dummy Audio), a REAPER that hangs (stopped), REAPER missing, the universal route
#           (stems, sequence, markers, MIDI, import with missing, extra, renamed and near-miss files) and a tampered
#           manifest. ReaperLiveExam runs the real REAPER when REAPER_BIN is set (skipped without it): an untouched
#           round trip changes nothing, a fade-out edit comes back levelled, music stems render one file each, and
#           REAPER's own settings folder (%APPDATA%/REAPER) is not touched.
# Usage   : python tools/audio/wavesmith/test_daw.py
#           REAPER_BIN="C:\Program Files\REAPER (x64)\reaper.exe" python tools/audio/wavesmith/test_daw.py   # + live
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audioio  # noqa: E402
import daw  # noqa: E402
import loudness  # noqa: E402
import midifile  # noqa: E402
import sound_sets  # noqa: E402
from wavfile import read_wav_channels, write_wav  # noqa: E402

RATE = 44100
LIVE_REAPER = os.environ.get("REAPER_BIN", "")
ASSET_LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-11-04 | |
"""
SETS = {"version": 1, "out_dir": "assets/audio", "target": "home",
        "sets": {"blips": {"generator": "sfx_synth", "bus": "ui", "takes": 1,
                           "variants": {"high": {"wave": "square", "freq": 1200, "sustain": 0.08, "decay": 0.12},
                                        "low": {"wave": "triangle", "freq": 300, "sustain": 0.1, "decay": 0.15}}}}}

# The stand-in REAPER: what `reaper -cfgfile <ini> -renderproject <project>` does, for the parts of a project the
# round trip uses. It logs its command line, environment folders and ini text to WAVESMITH_FAKE_REAPER_LOG.
FAKE_REAPER = r'''
import json, os, re, struct, sys, time, wave
argv = sys.argv[1:]
log = os.environ.get("WAVESMITH_FAKE_REAPER_LOG")
cfg = argv[argv.index("-cfgfile") + 1]
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "ini": open(cfg, encoding="utf-8").read(),
                            "cfg_dir_exists": os.path.isdir(os.path.dirname(cfg))}) + "\n")
if os.environ.get("WAVESMITH_FAKE_REAPER") == "hang":
    time.sleep(120)
proj = argv[argv.index("-renderproject") + 1]
base = os.path.dirname(proj)
lines = open(proj, encoding="utf-8").read().split("\n")
top, regions, tracks, depth, cur, item = {}, {}, [], 0, None, None
def val(s):
    s = s.strip()
    return s[1:-1] if s[:1] in "\"'`" and s[-1:] == s[:1] else s
for ln in lines:
    s = ln.strip()
    if s == ">":
        if depth == 3 and item is not None:
            cur["items"].append(item); item = None
        elif depth == 2 and cur is not None:
            tracks.append(cur); cur = None
        depth -= 1
        continue
    if depth == 1:
        if s.startswith("MARKER"):
            m = re.match(r"MARKER\s+(\d+)\s+(\S+)\s+(\"[^\"]*\"|\S+)\s+(\d+)", s)
            idx, pos, name, flags = int(m.group(1)), float(m.group(2)), val(m.group(3)), int(m.group(4))
            if flags & 1:
                if name:
                    regions[idx] = [name, pos, None]
                elif idx in regions:
                    regions[idx][2] = pos
        elif not s.startswith("<"):
            top[s.split(" ")[0]] = s[len(s.split(" ")[0]):].strip()
    if s.startswith("<TRACK"):
        cur = {"name": "", "sel": 0, "vol": 1.0, "items": []}
    elif s.startswith("<ITEM"):
        item = {"pos": 0.0, "len": 0.0, "vol": 1.0, "fadeout": 0.0, "file": None}
    elif depth == 2 and cur is not None:
        if s.startswith("NAME "): cur["name"] = val(s[5:])
        if s.startswith("SEL "): cur["sel"] = int(s.split()[1])
        if s.startswith("VOLPAN "): cur["vol"] = float(s.split()[1])
    elif depth >= 3 and item is not None:
        if s.startswith("POSITION "): item["pos"] = float(s.split()[1])
        if s.startswith("LENGTH "): item["len"] = float(s.split()[1])
        if s.startswith("VOLPAN "): item["vol"] = float(s.split()[1])
        if s.startswith("FADEOUT "): item["fadeout"] = float(s.split()[2])
        if s.startswith("FILE "): item["file"] = val(s[5:])
    if s.startswith("<"):
        depth += 1
fmt = top["RENDER_FMT"].split()
nch, rate = int(fmt[1]), int(fmt[2])
stems = int(top.get("RENDER_STEMS", "0"))
out_dir = os.path.join(base, val(top["RENDER_FILE"]))
os.makedirs(out_dir, exist_ok=True)
def read(path):
    with wave.open(path) as w:
        n, ch = w.getnframes(), w.getnchannels()
        data = struct.unpack("<%dh" % (n * ch), w.readframes(n))
    return [[data[i * ch + c] / 32768.0 for i in range(n)] for c in range(ch)]
def render(trks, a, b):
    n = int(round((b - a) * rate))
    buf = [[0.0] * n for _ in range(nch)]
    for t in trks:
        for it in t["items"]:
            src = read(os.path.join(base, it["file"]))
            start, length = int(round((it["pos"] - a) * rate)), int(round(it["len"] * rate))
            fade = int(round(it["fadeout"] * rate))
            for i in range(min(length, len(src[0]))):
                j = start + i
                if 0 <= j < n:
                    g = t["vol"] * it["vol"] * (min(1.0, (length - i) / fade) if fade else 1.0)
                    for c in range(nch):
                        buf[c][j] += src[min(c, len(src) - 1)][i] * g
    return buf
def write24(path, chans):
    frames = len(chans[0])
    raw = bytearray()
    for i in range(frames):
        for c in chans:
            v = max(-8388608, min(8388607, int(round(c[i] * 8388608))))
            raw += struct.pack("<i", v)[:3]
    fmt = struct.pack("<HHIIHH", 1, len(chans), rate, rate * 3 * len(chans), 3 * len(chans), 24)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(raw)) + raw
    open(path, "wb").write(b"RIFF" + struct.pack("<I", len(body)) + body)
for name, a, b in regions.values():
    if stems & 128:
        for t in tracks:
            if t["sel"]:
                write24(os.path.join(out_dir, t["name"] + ".wav"), render([t], a, b))
    else:
        write24(os.path.join(out_dir, name + ".wav"), render(tracks, a, b))
'''


def tone(seconds, freq, amp=0.3, rate=RATE, stereo=False):
    n = int(round(seconds * rate))
    mono = [amp * math.sin(2 * math.pi * freq * i / rate) * (1 - i / n) for i in range(n)]
    return [s for v in mono for s in (v, v * 0.6)] if stereo else mono


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = daw.main([str(a) for a in argv])
    return rc, out.getvalue() + err.getvalue()


class GameDir(unittest.TestCase):
    """A small game in a temp folder: an asset log, a sound set made from code, a folder of plain tones."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wavesmith_daw_"))
        self.root = self.tmp / "game"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "ASSET_LOG.md").write_bytes(ASSET_LOG.encode("utf-8"))
        (self.root / "data").mkdir()
        (self.root / "data" / "sound_sets.json").write_bytes(json.dumps(SETS).encode("utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sound_sets.main(["make", str(self.root / "data" / "sound_sets.json"),
                                              "--root", str(self.root)]), 0)
        self.fake = self.tmp / "fake_reaper.py"
        self.fake.write_bytes(FAKE_REAPER.encode("utf-8"))
        self.log = self.tmp / "fake_reaper.log"
        self.env = {k: os.environ.get(k) for k in ("REAPER_BIN", "WAVESMITH_FAKE_REAPER_LOG", "WAVESMITH_FAKE_REAPER")}
        os.environ["REAPER_BIN"] = str(self.fake)
        os.environ["WAVESMITH_FAKE_REAPER_LOG"] = str(self.log)
        os.environ.pop("WAVESMITH_FAKE_REAPER", None)
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*")
                if p.is_file() and "assets_src" not in p.parts and "build" not in p.parts}

    def changed(self, before):
        after = self.snapshot()
        return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))

    def rpp(self, name="blips"):
        return self.root / "assets_src" / "daw" / name / f"{name}.rpp"

    def edit_rpp(self, name, fn):
        p = self.rpp(name)
        p.write_bytes(fn(p.read_text(encoding="utf-8")).encode("utf-8"))

    def item_line(self, text, item, key, new):
        """text with the `key` line of the item called `item` replaced by `new`."""
        lines = text.split("\n")
        at = lines.index(f'      NAME "{item}"')
        for j in range(at - 6, at + 4):
            if lines[j].strip().startswith(key + " "):
                lines[j] = "      " + new
                return "\n".join(lines)
        raise AssertionError(f"no {key} line for {item}")

    def make_music(self, mono_bass=True):
        music = self.root / "assets" / "audio" / "music"
        music.mkdir(parents=True)
        frames = int(round(4 * 60 / 120 * 2 * RATE))                      # 2 bars of 4/4 at 120 BPM: 4 s
        lead = [0.2 * math.sin(2 * math.pi * 440 * i / RATE) for i in range(frames)]
        write_wav(music / "explore_lead.wav", [s for v in lead for s in (v, v * 0.5)], RATE, loop=(0, frames - 1),
                  channels=2)
        bass = [0.3 * math.sin(2 * math.pi * 110 * i / RATE) for i in range(frames)]
        write_wav(music / "explore_bass.wav", bass if mono_bass else [s for v in bass for s in (v, v)], RATE,
                  loop=(0, frames - 1), channels=1 if mono_bass else 2)
        data = {"version": 1, "sample_rate": RATE,
                "tracks": {"explore": {"bpm": 120, "beats_per_bar": 4, "bars": 2,
                                       "stems": {"lead": "music/explore_lead.wav", "bass": "music/explore_bass.wav"}}}}
        (self.root / "data" / "music.json").write_bytes(json.dumps(data).encode("utf-8"))
        return frames

    def mixed_rates(self):
        """assets/audio/mixed: two sounds at 44.1 kHz and one at 48 kHz (the project runs at 44.1 kHz)."""
        folder = self.root / "assets" / "audio" / "mixed"
        folder.mkdir(parents=True)
        write_wav(folder / "beep.wav", tone(0.1, 880), RATE)
        write_wav(folder / "boop.wav", tone(0.13, 440), RATE)
        write_wav(folder / "chirp.wav", tone(0.0937, 1500, rate=48000), 48000)
        return folder


class ProjectExam(GameDir):
    def test_golden_rpp_text(self):
        folder = self.root / "assets" / "audio" / "tones"
        folder.mkdir(parents=True)
        write_wav(folder / "beep.wav", tone(0.1, 880), RATE)
        write_wav(folder / "boop.wav", tone(0.05, 440, stereo=True), RATE, channels=2)
        rc, out = run("reaper", "assets/audio/tones", "--bus", "sfx")
        self.assertEqual(rc, 0, out)
        text = self.rpp("tones").read_text(encoding="utf-8")
        self.assertEqual(text, GOLDEN_RPP)
        man = json.loads((self.rpp("tones").parent / daw.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(man["root"], "../../..")
        self.assertEqual([(i["name"], i["file"], i["media"], i["frames"], i["channels"]) for i in man["items"]],
                         [("beep", "assets/audio/tones/beep.wav", "media/beep.wav", 4410, 1),
                          ("boop", "assets/audio/tones/boop.wav", "media/boop.wav", 2205, 2)])

    def test_no_project_file_holds_a_local_path(self):
        self.make_music()
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.assertEqual(run("reaper", "explore")[0], 0)
        self.assertEqual(run("export", "blips", "build/daw_blips")[0], 0)
        self.assertEqual(run("export", "explore", "build/daw_explore")[0], 0)
        leaks = [str(self.tmp), str(self.tmp).replace("\\", "/"), str(Path.home()), Path.home().as_posix()]
        user = Path.home().name
        texts = [p for p in self.root.rglob("*") if p.suffix in (".rpp", ".json", ".txt", ".csv")
                 and ("assets_src" in p.parts or "build" in p.parts)]
        self.assertGreaterEqual(len(texts), 8)
        for p in texts:
            t = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", t), p)
            self.assertIsNone(re.search(r"(^|[\s\"'(])(/Users/|/home/|\\\\)", t), p)
            for leak in leaks:
                self.assertNotIn(leak, t, p)
            self.assertIsNone(re.search(rf"\b{re.escape(user)}\b", t), f"{p} names the user folder {user}")

    def test_existing_project_needs_overwrite_and_keeps_a_bak(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        rc, out = run("reaper", "blips")
        self.assertEqual(rc, 2)
        self.assertIn("already holds a DAW project", out)
        self.edit_rpp("blips", lambda t: t.replace("RIPPLE 0 0", "RIPPLE 1 0"))
        take = self.rpp().parent / "media" / "my_recording.wav"           # REAPER records into Media/ by default
        write_wav(take, tone(0.1, 300), RATE)
        self.assertEqual(run("reaper", "blips", "--overwrite")[0], 0)
        self.assertIn("RIPPLE 1 0", self.rpp().with_name("blips.rpp.bak").read_text(encoding="utf-8"))
        self.assertTrue(take.is_file(), "--overwrite deleted a recording in media/")
        rc, out = run("reaper", "blips", "--name", "../../escape")
        self.assertEqual(rc, 2)
        self.assertIn("cannot name a project", out)

    def test_unknown_source_and_bad_names(self):
        rc, out = run("reaper", "nothing")
        self.assertEqual(rc, 2)
        self.assertIn("sets in data/sound_sets.json: blips", out)
        bad = self.root / "assets" / "audio" / "odd"
        bad.mkdir(parents=True)
        write_wav(bad / "two words.wav", tone(0.1, 500), RATE)
        rc, out = run("reaper", "assets/audio/odd", "--bus", "sfx")
        self.assertEqual(rc, 2)
        self.assertIn("cannot be a region or track name", out)
        rc, out = run("reaper", "assets/audio/blips")
        self.assertEqual(rc, 2)
        self.assertIn("--bus", out)


class ReexportExam(GameDir):
    def test_untouched_round_trip_changes_nothing(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("0 file(s) written, 2 kept, 0 problem(s)", out)
        self.assertEqual(self.changed(before), [])

    def test_the_throwaway_config_folder(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.assertEqual(run("reaper", "--reexport", "assets_src/daw/blips")[0], 0)
        rec = json.loads(self.log.read_text(encoding="utf-8").splitlines()[-1])
        argv = rec["argv"]
        for flag in ("-newinst", "-nosplash", "-ignoreerrors", "-cfgfile", "-renderproject"):
            self.assertIn(flag, argv)
        cfg = Path(argv[argv.index("-cfgfile") + 1])
        self.assertTrue(rec["cfg_dir_exists"])
        self.assertEqual(rec["ini"], daw.REAPER_INI)
        self.assertIn("mode=4", rec["ini"])
        self.assertEqual(Path(os.path.commonpath([str(cfg), tempfile.gettempdir()])), Path(tempfile.gettempdir()))
        if os.environ.get("APPDATA"):
            self.assertNotIn(os.environ["APPDATA"].lower(), str(cfg).lower().replace(tempfile.gettempdir().lower(), ""))
        self.assertFalse(cfg.parent.exists(), "the throwaway REAPER folder was not deleted")
        self.assertFalse((self.rpp().parent / daw.RENDER_COPY).exists())

    def test_edits_come_back_levelled_and_logged(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        before = self.snapshot()
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.changed(before), ["assets/audio/blips/blips_high.sfx.json",
                                                "assets/audio/blips/blips_high.wav", "docs/ASSET_LOG.md",
                                                "docs/licenses/A-0001.txt"])
        chans, rate, loop = sound_sets.read_channels(self.root / "assets/audio/blips/blips_high.wav")
        lufs, _ = sound_sets.level(chans, rate, "oneshot")
        self.assertAlmostEqual(lufs, loudness.ASWG["home"] + loudness.HOUSE["ui"], delta=0.2)
        self.assertEqual(len(chans), 1)                                  # mono stays mono
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        row = [ln for ln in log.splitlines() if ln.startswith("| A-0001")][0]
        self.assertIn("`assets/audio/blips/blips_high.wav`", row)
        self.assertIn("| yes |", row)
        self.assertIn("hand-edited in REAPER", row)
        self.assertIn("Wavesmith DAW project `assets_src/daw/blips`", row)
        self.assertIn("| no | yes |", row)                               # code-made: not AI output
        side = json.loads((self.root / "assets/audio/blips/blips_high.sfx.json").read_text(encoding="utf-8"))
        self.assertEqual(side["hand_edits"][0]["daw"], "REAPER")
        self.assertTrue(side["ship_safe"])
        ev = (self.root / "docs" / "licenses" / "A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("assets/audio/blips/blips_high.wav  SHA-256", ev)
        # a second run: the game already has this version, nothing is written, the row is not doubled
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("already has this version", out)
        self.assertEqual(self.changed(before), [])
        # a later edit of the other sound updates the same row
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_low", "VOLPAN", "VOLPAN 0.2 0 1 -1"))
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_low", "FADEOUT", "FADEOUT 1 0.1 0 1 0 0 0"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        log = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        rows = [ln for ln in log.splitlines() if ln.startswith("| A-")]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("blips_low.wav", rows[0])
        self.assertIn("blips_high.wav", rows[0])

    def test_dry_run_writes_nothing(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("would be written", out)
        self.assertEqual(self.changed(before), [])

    def test_a_file_changed_in_the_game_meanwhile_is_kept(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        game = self.root / "assets/audio/blips/blips_high.wav"
        write_wav(game, tone(0.2, 999), RATE)                            # regenerated since the project was made
        mine = game.read_bytes()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 1, out)
        self.assertIn("changed in the game since the project was made", out)
        self.assertEqual(game.read_bytes(), mine)
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips", "--force")
        self.assertEqual(rc, 0, out)
        self.assertNotEqual(game.read_bytes(), mine)

    def test_renamed_region_is_a_problem_and_keeps_the_file(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: t.replace('"blips_low" 1 0 1 R', '"blips_lo" 1 0 1 R'))
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 1, out)
        self.assertIn("blips_low: no render", out)
        self.assertIn("extra render blips_lo.wav", out)
        self.assertEqual(self.changed(before), [])

    def test_render_settings_changed_while_editing_do_not_matter(self):
        self.assertEqual(run("reaper", "blips")[0], 0)

        def mess(t):
            t = t.replace("RENDER_PATTERN $region", "RENDER_PATTERN $project-$region")
            t = t.replace(f"RENDER_FMT 0 1 {RATE}", "RENDER_FMT 0 2 48000").replace("RENDER_STEMS 0", "RENDER_STEMS 2")
            return t.replace("ZXZhdxgAAQ==", "bDNwbUAAAAABAAAA").replace(f"SAMPLERATE {RATE} 1 0", "SAMPLERATE 48000 0 0")
        self.edit_rpp("blips", mess)
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.changed(before), [])
        self.assertIn("RENDER_PATTERN $project-$region", self.rpp().read_text(encoding="utf-8"))   # yours stays

    def test_missing_media_stops_before_reaper(self):
        # REAPER runs with -ignoreerrors (no dialog to hang on), so a missing file must be caught here first
        self.assertEqual(run("reaper", "blips")[0], 0)
        (self.rpp().parent / "media" / "blips_low.wav").unlink()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 2)
        self.assertIn("media/blips_low.wav", out)
        self.assertIn("not there", out)
        self.assertFalse(self.log.exists())

    def test_no_regions_left_stops_before_reaper(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: "\n".join(ln for ln in t.split("\n") if not ln.strip().startswith("MARKER")))
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 2)
        self.assertIn("no named regions", out)
        self.assertFalse(self.log.exists())

    def test_music_stems_levelled_by_their_mix(self):
        frames = self.make_music()
        rc, out = run("reaper", "explore")
        self.assertEqual(rc, 0, out)
        text = self.rpp("explore").read_text(encoding="utf-8")
        self.assertEqual(text.count("<TRACK"), 2)
        self.assertIn("RENDER_STEMS 128", text)
        self.assertIn("TEMPO 120 4 4", text)
        self.assertTrue((self.rpp("explore").parent / "explore.mid").is_file())
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/explore")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.changed(before), [])
        # turn the lead down, and deselect every track (REAPER saves the selection): the render copy selects stems
        self.edit_rpp("explore", lambda t: t.replace('NAME "lead"\n    VOLPAN 1 0', 'NAME "lead"\n    VOLPAN 0.5 0')
                      .replace("    SEL 1", "    SEL 0"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/explore")
        self.assertEqual(rc, 0, out)
        self.assertIn("explore_bass.wav: not edited, moved with the mix", out)
        stems = []
        for name, ch in (("lead", 2), ("bass", 1)):
            samples, rate, loop, channels = read_wav_channels(self.root / f"assets/audio/music/explore_{name}.wav")
            self.assertEqual((channels, loop, len(samples) // channels), (ch, (0, frames - 1), frames), name)
            stems.append([samples[c::channels] for c in range(channels)])
        g, note = daw.mix_gain(stems, RATE, "music", "home")
        self.assertEqual(g, 0.0, note)                                   # the mix now sits at the music level
        # again: the mix is made from the renders, not from the game's (now quieter) files, so nothing moves
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/explore")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("already has this version"), 2, out)
        self.assertEqual(self.changed(before), [])

    def test_an_undone_edit_puts_the_original_back(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        original = (self.root / "assets/audio/blips/blips_high.wav").read_bytes()
        plain = self.rpp().read_text(encoding="utf-8")
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        self.assertEqual(run("reaper", "--reexport", "assets_src/daw/blips")[0], 0)
        self.assertNotEqual((self.root / "assets/audio/blips/blips_high.wav").read_bytes(), original)
        self.edit_rpp("blips", lambda t: plain)                          # undone in the DAW
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("the edit was undone in REAPER, the original is back", out)
        self.assertEqual((self.root / "assets/audio/blips/blips_high.wav").read_bytes(), original)
        side = json.loads((self.root / "assets/audio/blips/blips_high.sfx.json").read_text(encoding="utf-8"))
        self.assertNotIn("hand_edits", side)
        self.assertIn("every edit from assets_src/daw/blips is undone", out)

    def test_a_sound_at_another_rate_renders_at_its_own_rate(self):
        self.mixed_rates()
        rc, made = run("reaper", "assets/audio/mixed", "--bus", "sfx")
        self.assertEqual(rc, 0, made)
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/mixed")       # untouched: no file is resampled
        self.assertEqual(rc, 0, out)
        self.assertIn("0 file(s) written, 3 kept, 0 problem(s)", out)
        self.assertEqual(self.changed(before), [])
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 2)   # one REAPER run per rate
        self.edit_rpp("mixed", lambda t: self.item_line(t, "chirp", "FADEOUT", "FADEOUT 1 0.05 0 1 0 0 0"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/mixed")
        self.assertEqual(rc, 0, out)
        self.assertIn("1 file(s) written, 2 kept", out)
        self.assertNotIn("length changed", out)
        _, rate, _, _ = read_wav_channels(self.root / "assets/audio/mixed/chirp.wav")
        self.assertEqual(rate, 48000)
        self.assertIn("renders it back at 48000 Hz", made)

    def test_music_stems_at_different_rates_are_refused(self):
        self.make_music()
        bass = self.root / "assets/audio/music/explore_bass.wav"
        write_wav(bass, tone(4.0, 110, rate=48000), 48000)
        rc, out = run("reaper", "explore")
        self.assertEqual(rc, 2, out)
        self.assertIn("one sample rate", out)

    def test_an_edit_saved_into_media_is_never_put_back_as_the_original(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        plain = self.rpp().read_text(encoding="utf-8")
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        self.assertEqual(run("reaper", "--reexport", "assets_src/daw/blips")[0], 0)
        media = self.rpp().parent / "media" / "blips_high.wav"
        write_wav(media, tone(0.2, 999), RATE)                           # a destructive edit in the copy itself
        self.edit_rpp("blips", lambda t: plain)
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("the original is back", out)
        self.assertIn("media/blips_high.wav changed since the project was made", out)
        self.assertNotEqual((self.root / "assets/audio/blips/blips_high.wav").read_bytes(), media.read_bytes())

    def test_a_hanging_reaper_is_stopped(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        os.environ["WAVESMITH_FAKE_REAPER"] = "hang"
        t0 = time.time()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips", "--timeout", "3")
        self.assertEqual(rc, 2)
        self.assertIn("did not finish within 3 s", out)
        self.assertLess(time.time() - t0, 60)

    def test_reaper_missing(self):
        os.environ["REAPER_BIN"] = str(self.tmp / "no_reaper.exe")
        rc, out = run("reaper", "blips")                                  # writing a project needs no REAPER
        self.assertEqual(rc, 0, out)
        self.assertIn("REAPER was not found", out)
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 2)
        self.assertIn("REAPER not found", out)
        self.assertFalse(daw.readiness()[0][0])
        self.assertIn("is not a file", daw.readiness()[0][1])
        rc, out = run("check")
        self.assertEqual(rc, 0)
        self.assertIn("REAPER not found", out)
        os.environ["REAPER_BIN"] = str(self.fake)
        self.assertTrue(daw.readiness()[0][0])

    def test_absolute_media_paths_are_warned_about(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: t.replace("  RIPPLE 0 0", '  RIPPLE 0 0\n  RECORD_PATH "C:\\Users\\someone\\x" ""'))
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("by absolute path", out)

    def test_a_tampered_manifest_is_refused(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        man_path = self.rpp().parent / daw.MANIFEST
        for bad in ("../../outside.wav", "C:/x.wav", "/etc/x.wav"):
            man = json.loads(man_path.read_text(encoding="utf-8"))
            man["items"][0]["file"] = bad
            man_path.write_bytes(json.dumps(man).encode("utf-8"))
            rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
            self.assertEqual(rc, 2, bad)
            self.assertIn("plain relative path", out)

    def test_a_tampered_root_cannot_move_the_writes(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        man_path = self.rpp().parent / daw.MANIFEST
        good = json.loads(man_path.read_text(encoding="utf-8"))
        outside = self.tmp / "outside"
        outside.mkdir()
        for bad in (outside.as_posix(), "../../../..", "../../../../outside", "/outside"):
            man_path.write_bytes(json.dumps(dict(good, root=bad)).encode("utf-8"))
            rc, out = run("reaper", "--reexport", "assets_src/daw/blips", "--force")
            self.assertEqual(rc, 2, f"{bad}: {out}")
            self.assertIn("[error]", out)
            self.assertEqual([p for p in self.tmp.rglob("*.wav") if self.root not in p.parents], [], bad)
        # the real root, but run from somewhere else: refused without --root, fine with it
        man_path.write_bytes(json.dumps(good).encode("utf-8"))
        os.chdir(self.root / "docs")
        rc, out = run("reaper", "--reexport", "../assets_src/daw/blips")
        self.assertEqual(rc, 2, out)
        self.assertIn("--root", out)
        rc, out = run("reaper", "--reexport", "../assets_src/daw/blips", "--root", "..")
        self.assertEqual(rc, 0, out)
        self.assertIn("1 file(s) written", out)

    def test_a_file_that_cannot_be_replaced_mid_run(self):
        # Windows: a game engine or player holding blips_low.wav open makes os.replace fail. The file written before
        # it must still be recorded, no temporary file may stay, and the next run must not refuse anything.
        self.assertEqual(run("reaper", "blips")[0], 0)
        for name in ("blips_high", "blips_low"):
            self.edit_rpp("blips", lambda t, n=name: self.item_line(t, n, "FADEOUT", "FADEOUT 1 0.1 0 1 0 0 0"))
        real = os.replace

        def locked(src, dst):
            if Path(dst).name == "blips_low.wav":
                raise PermissionError(13, "The process cannot access the file", dst)
            return real(src, dst)
        with unittest.mock.patch("os.replace", side_effect=locked):
            rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 1, out)
        self.assertIn("blips_low.wav: could not be written", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(sorted(p.name for p in self.root.rglob("*daw_tmp*")), [])
        man = json.loads((self.rpp().parent / daw.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(sorted(man["written"]), ["assets/audio/blips/blips_high.wav"])
        self.assertIn("blips_high.wav", (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("1 file(s) written", out)
        self.assertIn("blips_high: edited, and the game already has this version", out)

    def test_a_working_folder_outside_the_game_is_refused(self):
        rc, out = run("reaper", "blips", "--out", self.tmp / "elsewhere")
        self.assertEqual(rc, 2, out)
        self.assertIn("inside the game", out)
        self.assertFalse((self.tmp / "elsewhere" / daw.MANIFEST).exists())


class RenderCopyExam(unittest.TestCase):
    MAN = {"kind": "music", "rate": RATE, "channels": 2, "items": [{"name": "lead"}, {"name": "bass"}]}

    def test_stem_tracks_are_selected_and_others_not(self):
        text = "\n".join(['<REAPER_PROJECT 0.1 "7.0" 0', "  RENDER_FMT 0 1 8000", "  <RENDER_CFG", "    abc", "  >",
                          '  MARKER 1 0 "explore" 1 0 1 R', '  MARKER 1 4 "" 1',
                          '  <TRACK', '    NAME "lead"', "    <ITEM", "      SEL 0", "    >", "  >",
                          '  <TRACK', '    NAME "notes"', "    SEL 1", "  >",
                          '  <TRACK', '    NAME bass', "    SEL 0", "  >", ">"])
        out = daw.render_copy_text(text, self.MAN).split("\n")
        self.assertNotIn("abc", "\n".join(out))
        self.assertNotIn("  RENDER_FMT 0 1 8000", out)
        self.assertIn(f"  RENDER_FMT 0 2 {RATE}", out)
        self.assertEqual(out.count("  RENDER_STEMS 128"), 1)
        lead = out.index('    NAME "lead"')
        self.assertEqual(out[lead - 1:lead + 1], ["    SEL 1", '    NAME "lead"'])   # inserted: it had none
        self.assertEqual(out[out.index('    NAME "notes"') + 1], "    SEL 0")
        self.assertEqual(out[out.index("    NAME bass") + 1], "    SEL 1")
        self.assertIn("      SEL 0", out)                                 # an item's own SEL is not a track's

    def test_not_a_project(self):
        with self.assertRaises(daw.ToolError):
            daw.render_copy_text("hello\n", dict(self.MAN, kind="set"))


class UniversalExam(GameDir):
    def test_export_writes_stems_sequence_and_markers(self):
        rc, out = run("export", "blips", "build/daw_blips")
        self.assertEqual(rc, 0, out)
        work = self.root / "build" / "daw_blips"
        man = json.loads((work / daw.MANIFEST).read_text(encoding="utf-8"))
        names = [it["name"] for it in man["items"]]
        self.assertEqual(names, ["blips_high", "blips_low"])
        for it in man["items"]:
            self.assertEqual((work / it["media"]).read_bytes(), (self.root / it["file"]).read_bytes())
        seq, rate, _, ch = read_wav_channels(work / "blips_sequence.wav")
        hi = man["items"][0]["frames"]
        self.assertEqual(len(seq) // ch, hi + RATE + man["items"][1]["frames"])
        csv = (work / "markers.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(csv[0], "#,Name,Start,End,Length")
        self.assertTrue(csv[1].startswith(f"R1,blips_high,0.000000,{hi / RATE:.6f},"))
        labels = (work / "markers.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(labels[1].split("\t"), [f"{(hi + RATE) / RATE:.6f}",
                                                 f"{(hi + RATE + man['items'][1]['frames']) / RATE:.6f}", "blips_low"])
        how = (work / "HOW_TO.txt").read_text(encoding="utf-8")
        self.assertIn("python tools/audio/wavesmith/wavesmith.py daw import build/daw_blips", how)
        self.assertTrue((work / daw.RENDERS_DIR).is_dir())

    def test_music_export_writes_a_midi_file(self):
        self.make_music()
        song = self.root / "explore.song.json"
        song.write_bytes(json.dumps({"bpm": 120, "steps_per_beat": 4, "channels": {"lead": {}, "drums": {"wave": "drums"}},
                                     "patterns": {"A": {"lead": "C4 - E4 .", "drums": "k . s ."}},
                                     "order": ["A"]}).encode("utf-8"))
        rc, out = run("export", "explore", "build/daw_explore", "--song", song)
        self.assertEqual(rc, 0, out)
        smf = midifile.read_smf((self.root / "build/daw_explore/explore.mid").read_bytes())
        notes = [v for t in smf["tracks"] for _, kind, v in t if kind == "note"]
        self.assertEqual(sorted((ch, n) for ch, n, _, _ in notes), [(0, 60), (0, 64), (9, 36), (9, 38)])
        rc, out = run("export", "explore", "build/daw_grid")
        self.assertEqual(rc, 0, out)
        smf = midifile.read_smf((self.root / "build/daw_grid/explore.mid").read_bytes())
        self.assertIn((0, "tempo", 120.0), smf["tracks"][0])
        self.assertIn((1920, "marker", "bar 2"), smf["tracks"][0])

    def test_import_by_name_with_missing_extra_and_renamed_files(self):
        self.assertEqual(run("export", "blips", "build/daw_blips")[0], 0)
        work = self.root / "build" / "daw_blips"
        renders = work / daw.RENDERS_DIR
        samples, rate, _, _ = read_wav_channels(work / "stems" / "blips_low.wav")
        write_wav(renders / "Blips Low.wav", [s * (1 - i / len(samples)) for i, s in enumerate(samples)], rate)
        write_wav(renders / "blips_hihg.wav", samples, rate)              # a typo: named, never guessed
        write_wav(renders / "crash.wav", samples, rate)
        before = self.snapshot()
        rc, out = run("import", "build/daw_blips", "--daw", "FL Studio")
        self.assertEqual(rc, 1, out)
        self.assertIn("Blips Low.wav taken as blips_low", out)
        self.assertIn("blips_hihg.wav (meant blips_high? rename it to blips_high.wav)", out)
        self.assertIn("crash.wav (no sound by that name)", out)
        self.assertIn("blips_high: no render, kept as it is", out)
        self.assertEqual(self.changed(before), ["assets/audio/blips/blips_low.sfx.json",
                                                "assets/audio/blips/blips_low.wav", "docs/ASSET_LOG.md",
                                                "docs/licenses/A-0001.txt"])
        row = [ln for ln in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
               if ln.startswith("| A-0001")][0]
        self.assertIn("hand-edited in FL Studio", row)
        self.assertIn("| yes |", row)
        # an unchanged render (DAW dither within 2 steps of 16-bit) is the same audio: kept byte for byte
        for p in renders.iterdir():
            p.unlink()
        hi, rate, _, _ = read_wav_channels(work / "stems" / "blips_high.wav")
        write_wav(renders / "blips_high.wav", [s + (1.5 if i % 2 else -1.5) / 32768 for i, s in enumerate(hi)], rate)
        before = self.snapshot()
        rc, out = run("import", "build/daw_blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("blips_high: unchanged", out)
        self.assertEqual(self.changed(before), [])

    def make_ogg(self):
        """assets/audio/amb/hum.ogg, a 2 s ambience loop from 0.1 s to the end (LOOPSTART / LOOPLENGTH tags)."""
        folder = self.root / "assets" / "audio" / "amb"
        folder.mkdir(parents=True)
        n = 2 * RATE
        hum = [0.25 * math.sin(2 * math.pi * 220 * i / RATE) for i in range(n)]
        audioio.write_audio(folder / "hum.ogg", [hum], RATE, loop=(4410, n - 1))
        return folder / "hum.ogg", n

    def render_hum(self, gain):
        """renders/hum.wav: the exported stem at `gain` (an edit when gain is not 1)."""
        work = self.root / "build" / "daw_amb"
        samples, rate, _, _ = read_wav_channels(work / "stems" / "hum.wav")
        (work / daw.RENDERS_DIR).mkdir(exist_ok=True)
        write_wav(work / daw.RENDERS_DIR / "hum.wav", [s * gain for s in samples], rate)

    @unittest.skipUnless(audioio.find_ffmpeg(), "writing OGG needs ffmpeg")
    def test_an_edited_ogg_lands_on_the_same_bytes_twice(self):
        game, _ = self.make_ogg()
        self.assertEqual(run("export", "assets/audio/amb", "build/daw_amb", "--bus", "ambience")[0], 0)
        self.render_hum(0.5)
        rc, out = run("import", "build/daw_amb")
        self.assertEqual(rc, 0, out)
        self.assertIn("1 file(s) written", out)
        before = self.snapshot()
        rc, out = run("import", "build/daw_amb")                         # the same render again: nothing moves
        self.assertEqual(rc, 0, out)
        self.assertIn("hum: edited, and the game already has this version", out)
        self.assertEqual(self.changed(before), [])

    @unittest.skipUnless(audioio.find_ffmpeg(), "writing OGG needs ffmpeg")
    def test_an_edited_ogg_loop_keeps_its_loop_point(self):
        game, n = self.make_ogg()
        self.assertEqual(run("export", "assets/audio/amb", "build/daw_amb", "--bus", "ambience")[0], 0)
        man = json.loads((self.root / "build/daw_amb" / daw.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual((man["items"][0]["loop"], man["items"][0]["kind"]), ([4410, n - 1], "loop"))
        self.assertEqual(read_wav_channels(self.root / "build/daw_amb/stems/hum.wav")[2], (4410, n - 1))
        self.render_hum(0.5)
        rc, out = run("import", "build/daw_amb")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("length changed", out)
        tags = dict(audioio.oggvorbis_module().decode(game.read_bytes())[2])
        self.assertEqual((tags.get("LOOPSTART"), tags.get("LOOPLENGTH")), ("4410", str(n - 4410)))

    @unittest.skipUnless(audioio.find_ffmpeg(), "writing OGG needs ffmpeg")
    def test_an_undone_edit_of_an_ogg_puts_the_original_back(self):
        # the stems are WAV, the game's file OGG: the original comes back from the copy kept in originals/
        game, _ = self.make_ogg()
        original = game.read_bytes()
        self.assertEqual(run("export", "assets/audio/amb", "build/daw_amb", "--bus", "ambience")[0], 0)
        self.render_hum(0.5)
        self.assertEqual(run("import", "build/daw_amb")[0], 0)
        self.assertNotEqual(game.read_bytes(), original)
        self.render_hum(1.0)                                              # undone in the DAW
        rc, out = run("import", "build/daw_amb")
        self.assertEqual(rc, 0, out)
        self.assertIn("the edit was undone in a DAW, the original is back", out)
        self.assertEqual(game.read_bytes(), original)
        man = json.loads((self.root / "build/daw_amb" / daw.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual((man["written"], man["logged"]), ({}, []))

    def test_an_edit_saved_over_a_stem_counts_as_an_edit(self):
        self.assertEqual(run("export", "blips", "build/daw_blips")[0], 0)
        work = self.root / "build" / "daw_blips"
        samples, rate, _, _ = read_wav_channels(work / "stems" / "blips_high.wav")
        faded = [s * (1 - i / len(samples)) for i, s in enumerate(samples)]
        write_wav(work / "stems" / "blips_high.wav", faded, rate)          # the DAW saved over its source file
        write_wav(work / daw.RENDERS_DIR / "blips_high.wav", faded, rate)
        rc, out = run("import", "build/daw_blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("stems/blips_high.wav changed since the project was made", out)
        self.assertIn("1 file(s) written", out)
        self.assertIn("assets/audio/blips/blips_high.wav: hand-edited in a DAW", out)

    def test_import_of_a_reaper_folder_and_reexport_of_an_export_are_refused(self):
        self.assertEqual(run("export", "blips", "build/daw_blips")[0], 0)
        rc, out = run("reaper", "--reexport", "build/daw_blips")
        self.assertEqual(rc, 2)
        self.assertIn("daw import", out)
        rc, out = run("import", "build/nothing_here")
        self.assertEqual(rc, 2)


GOLDEN_RPP = '''<REAPER_PROJECT 0.1 "7.0" 0
  RIPPLE 0 0
  PANLAW 1
  TEMPO 120 4 4
  RENDER_FILE "render"
  RENDER_PATTERN $region
  RENDER_FMT 0 2 44100
  RENDER_1X 0
  RENDER_RANGE 3 0 0 0 1000
  RENDER_RESAMPLE 3 0 1
  RENDER_ADDTOPROJ 0
  RENDER_STEMS 0
  RENDER_DITHER 0
  SAMPLERATE 44100 1 0
  <RENDER_CFG
    ZXZhdxgAAQ==
  >
  <NOTES 0 2
    |Wavesmith DAW project: sounds from tones (assets/audio/tones)
    |Edit freely; keep each region's name (it is the file it becomes).
    |Back to the game: python tools/audio/wavesmith/wavesmith.py daw reaper --reexport assets_src/daw/tones
    |
    |Bus loudness targets (home; kit house levels, set again on the way back):
    |  sfx: -30 LUFS (one-shots by their loudest 400 ms, loops integrated), true peak at most -1 dBTP
    |
    |Sounds:
    |  beep -> assets/audio/tones/beep.wav (sfx, oneshot)
    |  boop -> assets/audio/tones/boop.wav (sfx, oneshot)
  >
  MARKER 1 0 "beep" 1 0 1 R
  MARKER 1 0.1 "" 1
  MARKER 2 1.1 "boop" 1 0 1 R
  MARKER 2 1.15 "" 1
  <TRACK
    NAME "tones"
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    SEL 0
    NCHAN 2
    MAINSEND 1 0
    <ITEM
      POSITION 0
      LENGTH 0.1
      LOOP 0
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      NAME "beep"
      VOLPAN 1 0 1 -1
      SOFFS 0
      <SOURCE WAVE
        FILE "media/beep.wav"
      >
    >
    <ITEM
      POSITION 1.1
      LENGTH 0.05
      LOOP 0
      FADEIN 1 0 0 1 0 0 0
      FADEOUT 1 0 0 1 0 0 0
      NAME "boop"
      VOLPAN 1 0 1 -1
      SOFFS 0
      <SOURCE WAVE
        FILE "media/boop.wav"
      >
    >
  >
>
'''


def appdata_snapshot():
    """{path: (size, mtime)} of REAPER's own settings folder, or {} when there is none."""
    base = os.environ.get("APPDATA")
    folder = Path(base) / "REAPER" if base else Path.home() / "Library" / "Application Support" / "REAPER"
    if not folder.is_dir():
        folder = Path.home() / ".config" / "REAPER"
    if not folder.is_dir():
        return {}
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*")}


@unittest.skipUnless(LIVE_REAPER and os.path.isfile(LIVE_REAPER),
                     "set REAPER_BIN to run the round trip through a real REAPER")
class ReaperLiveExam(GameDir):
    """The real REAPER (headless -renderproject with a throwaway -cfgfile; checked with REAPER 7.84 on Windows 11,
    in evaluation). About 15 s a render."""

    def setUp(self):
        super().setUp()
        os.environ["REAPER_BIN"] = LIVE_REAPER
        self.user = appdata_snapshot()

    def tearDown(self):
        try:
            self.assertEqual(appdata_snapshot(), self.user, "REAPER's own settings folder changed")
        finally:
            super().tearDown()

    def test_untouched_then_edited_round_trip(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertIn("REAPER rendered 2 file(s)", out)
        self.assertEqual(self.changed(before), [])
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_high", "FADEOUT", "FADEOUT 1 0.15 0 1 0 0 0"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.changed(before), ["assets/audio/blips/blips_high.sfx.json",
                                                "assets/audio/blips/blips_high.wav", "docs/ASSET_LOG.md",
                                                "docs/licenses/A-0001.txt"])
        chans, rate, _ = sound_sets.read_channels(self.root / "assets/audio/blips/blips_high.wav")
        lufs, _ = sound_sets.level(chans, rate, "oneshot")
        self.assertAlmostEqual(lufs, loudness.ASWG["home"] + loudness.HOUSE["ui"], delta=0.2)

    def reaper_save(self, rpp):
        """REAPER opens rpp and saves it in place (-saveas, its own full format: GUIDs, every default), with a
        throwaway -cfgfile. REAPER 7.84 does not quit after -saveas, so the run is stopped once the file is saved."""
        import subprocess
        cfg = Path(tempfile.mkdtemp(prefix="wavesmith_reaper_"))
        out = rpp.with_name("saved_by_reaper.rpp")
        try:
            (cfg / "reaper.ini").write_bytes(daw.REAPER_INI.encode("ascii"))
            proc = subprocess.Popen([LIVE_REAPER, "-newinst", "-nosplash", "-cfgfile", str(cfg / "reaper.ini"),
                                     str(rpp), "-saveas", str(out)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            size, stable, t0 = -1, 0, time.time()
            while time.time() - t0 < 60 and stable < 3:
                time.sleep(1)
                now = out.stat().st_size if out.exists() else -1
                stable = stable + 1 if now == size and now > 0 else 0
                size = now
            proc.kill()
            proc.wait(timeout=30)
        finally:
            shutil.rmtree(cfg, ignore_errors=True)
        self.assertTrue(out.is_file(), "REAPER did not save the project")
        os.replace(str(out), str(rpp))

    def test_a_project_saved_by_reaper_round_trips(self):
        self.assertEqual(run("reaper", "blips")[0], 0)
        self.edit_rpp("blips", lambda t: self.item_line(t, "blips_low", "FADEOUT", "FADEOUT 1 0.1 0 1 0 0 0"))
        self.reaper_save(self.rpp())
        text = self.rpp().read_text(encoding="utf-8")
        self.assertIn("TRACKID {", text)                                  # REAPER's own format now
        self.assertIn('FILE "media/blips_low.wav"', text)                 # media stays relative
        self.assertEqual(daw.absolute_paths(text), [])
        self.assertIn("|Wavesmith DAW project", text)                     # the notes survive
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/blips")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.changed(before), ["assets/audio/blips/blips_low.sfx.json",
                                                "assets/audio/blips/blips_low.wav", "docs/ASSET_LOG.md",
                                                "docs/licenses/A-0001.txt"])

    def test_a_sound_at_another_rate_comes_back_at_its_own_rate(self):
        self.mixed_rates()
        self.assertEqual(run("reaper", "assets/audio/mixed", "--bus", "sfx")[0], 0)
        before = self.snapshot()
        rc, out = run("reaper", "--reexport", "assets_src/daw/mixed")
        self.assertEqual(rc, 0, out)
        self.assertIn("REAPER rendered 3 file(s) (exit 0, 0)", out)
        self.assertEqual(self.changed(before), [])                    # the 48 kHz sound too: not resampled
        chirp = self.rpp("mixed").parent / "render" / "chirp.wav"
        self.assertEqual(read_wav_channels(chirp)[1], 48000)
        self.edit_rpp("mixed", lambda t: self.item_line(t, "chirp", "FADEOUT", "FADEOUT 1 0.05 0 1 0 0 0"))
        rc, out = run("reaper", "--reexport", "assets_src/daw/mixed")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.changed(before), ["assets/audio/mixed/chirp.wav", "docs/ASSET_LOG.md",
                                                "docs/licenses/A-0001.txt"])
        samples, rate, _, ch = read_wav_channels(self.root / "assets/audio/mixed/chirp.wav")
        self.assertEqual((rate, len(samples) // ch), (48000, int(round(0.0937 * 48000))))

    def test_music_stems_one_file_each(self):
        frames = self.make_music(mono_bass=False)
        self.assertEqual(run("reaper", "explore")[0], 0)
        before = self.snapshot()
        self.edit_rpp("explore", lambda t: t.replace("    SEL 1", "    SEL 0"))     # the render copy selects them
        rc, out = run("reaper", "--reexport", "assets_src/daw/explore")
        self.assertEqual(rc, 0, out)
        self.assertIn("REAPER rendered 2 file(s)", out)
        self.assertEqual(self.changed(before), [])
        self.assertEqual(sorted(p.name for p in (self.rpp("explore").parent / daw.RENDER_DIR).iterdir()),
                         ["bass.wav", "lead.wav"])
        self.assertEqual(len(read_wav_channels(self.rpp("explore").parent / "render" / "lead.wav")[0]) // 2, frames)


if __name__ == "__main__":
    unittest.main(verbosity=1)
