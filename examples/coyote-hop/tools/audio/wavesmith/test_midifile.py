#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_midifile.py
# Purpose : Exam for midifile.py: variable-length quantities (the SMF spec's own examples), the exact bytes of a
#           conductor track, a chiptune song's notes read back (pitches, lengths in ticks, held notes across
#           patterns, rests, drums on channel 10 with General MIDI notes, channel 10 skipped for melodic channels,
#           velocities from volume, notes outside 0..127 left out), and the command line (song, grid, dump, errors).
# Usage   : python tools/audio/wavesmith/test_midifile.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import midifile as M  # noqa: E402


def song_file(folder, song):
    p = Path(folder) / "s.song.json"
    p.write_bytes(json.dumps(song).encode("utf-8"))
    return p


class MidiExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wavesmith_midi_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = M.main([str(a) for a in argv])
        return rc, out.getvalue()

    def test_variable_length_quantities(self):
        # the examples in the Standard MIDI File 1.0 specification
        for n, want in ((0, "00"), (0x40, "40"), (0x7F, "7f"), (0x80, "8100"), (0x2000, "c000"), (0x3FFF, "ff7f"),
                        (0x4000, "818000"), (0x100000, "c08000"), (0x1FFFFF, "ffff7f"), (0x200000, "81808000"),
                        (0x0FFFFFFF, "ffffff7f")):
            self.assertEqual(M.vlq(n).hex(), want, n)

    def test_conductor_bytes(self):
        data = M.smf_bytes([M.conductor(120, 3)])
        self.assertEqual(data[:14].hex(), "4d546864" "00000006" "0001" "0001" "01e0")
        body = data[22:]
        self.assertEqual(body.hex(), "00ff510307a120" "00ff580403021808" "00ff2f00")   # 500000 us, 3/4

    def test_song_notes(self):
        song = {"bpm": 150, "steps_per_beat": 4,
                "channels": {"lead": {"volume": 0.4}, "bass": {"wave": "triangle", "volume": 0.2, "octave": -1},
                             "drums": {"wave": "drums"}},
                "patterns": {"A": {"lead": "C4 - E4 .", "bass": "A2 . . -", "drums": "k s h c"},
                             "B": {"lead": "- . F#5 Bb3"}},
                "order": ["A", "B"]}
        out = Path(self.tmp) / "s.mid"
        info = M.write_song(song_file(self.tmp, song), out)
        self.assertEqual((info["notes"], info["skipped"]), (9, 0))
        smf = M.read_smf(out.read_bytes())
        self.assertEqual(smf["ppq"], 480)
        self.assertIn((0, "tempo", 150.0), smf["tracks"][0])
        notes = {k: [v for _, kind, v in t if kind == "note"] for k, t in enumerate(smf["tracks"])}
        # lead: C4 held 2 steps, E4 one step then rest; B starts with "-": a rest before it, so nothing to hold
        self.assertEqual(notes[1], [(0, 60, 112, 240), (0, 64, 112, 360), (0, 78, 112, 840), (0, 58, 112, 960)])
        # bass: A2 an octave down (A1 = 33), the "-" after a rest holds nothing; velocity from volume 0.2 / 0.4
        self.assertEqual(notes[2], [(1, 33, 56, 120)])
        self.assertEqual([(ch, n) for ch, n, _, _ in notes[3]], [(9, 36), (9, 38), (9, 42), (9, 49)])
        self.assertEqual([v[3] - start for start, kind, v in smf["tracks"][3] if kind == "note"], [120] * 4)

    def test_channel_ten_is_skipped_and_range_checked(self):
        chans = {f"c{k}": {} for k in range(10)}
        pat = {f"c{k}": "C4" for k in range(10)}
        pat["c0"] = "C9"                                               # MIDI 120: fine
        chans["c1"] = {"octave": 4}
        pat["c1"] = "B9"                                               # B9 + 4 octaves = 167: left out
        song = {"bpm": 100, "channels": chans, "patterns": {"A": pat}, "order": ["A"]}
        out = Path(self.tmp) / "c.mid"
        info = M.write_song(song_file(self.tmp, song), out)
        self.assertEqual(info["skipped"], 1)
        smf = M.read_smf(out.read_bytes())
        used = sorted({v[0] for t in smf["tracks"] for _, kind, v in t if kind == "note"})
        self.assertNotIn(9, used)
        self.assertEqual(used, [0, 2, 3, 4, 5, 6, 7, 8, 10])

    def test_command_line(self):
        song = song_file(self.tmp, {"bpm": 90, "channels": {"a": {}}, "patterns": {"A": {"a": "C4 D4"}},
                                    "order": ["A"]})
        rc, out = self.run_tool("song", song, "--out", Path(self.tmp) / "x.mid")
        self.assertEqual(rc, 0, out)
        self.assertIn("2 note(s)", out)
        rc, out = self.run_tool("grid", "--bpm", 96, "--bars", 4, "--beats-per-bar", 3, "--out", Path(self.tmp) / "g.mid")
        self.assertEqual(rc, 0, out)
        smf = M.read_smf((Path(self.tmp) / "g.mid").read_bytes())
        self.assertEqual([v for t, kind, v in smf["tracks"][0] if kind == "marker"], ["bar 1", "bar 2", "bar 3", "bar 4"])
        self.assertIn((1440, "marker", "bar 2"), smf["tracks"][0])
        rc, out = self.run_tool("dump", Path(self.tmp) / "x.mid")
        self.assertEqual(rc, 0, out)
        self.assertIn("track 2: 2 note(s)", out)
        rc, out = self.run_tool("song", song_file(self.tmp, {"bpm": 90}), "--out", Path(self.tmp) / "y.mid")
        self.assertEqual(rc, 2)
        self.assertIn("[error]", out)
        # MIDI's tempo is 3 bytes of microseconds a quarter note: below about 3.6 BPM it does not fit (was a traceback)
        for bpm in (3, 0.5, "nan"):
            rc, out = self.run_tool("grid", "--bpm", bpm, "--bars", 1, "--out", Path(self.tmp) / "slow.mid")
            self.assertEqual(rc, 2, out)
            self.assertIn(f"[error] bpm must be {M.BPM_RANGE[0]}..{M.BPM_RANGE[1]}", out)
            self.assertNotIn("Traceback", out)
        self.assertEqual(len(M.conductor(M.BPM_RANGE[0])[0][2]), 6)                   # the slowest tempo still fits
        bad = Path(self.tmp) / "bad.mid"
        bad.write_bytes(b"RIFF....")
        rc, out = self.run_tool("dump", bad)
        self.assertEqual(rc, 2)
        self.assertIn("not a MIDI file", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
