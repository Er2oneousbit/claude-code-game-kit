#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_dialogue.py
# Purpose : Exam for dialogue.py: per-character reveal from voice files (estimated) and babble timelines (exact),
#           subtitle cues that follow the guidelines (40 characters, 2 lines, breaks at punctuation, no scrap cues,
#           5/6 s minimum, 7 s maximum, reading speed), SFX captions, sequences, exact SRT and WebVTT output with the
#           speaker named when it changes, errors, and the shape the engines' dialogue readers expect.
# Usage   : python tools/audio/test_dialogue.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import babble  # noqa: E402
import dialogue as D  # noqa: E402
from wavfile import write_wav  # noqa: E402

RATE = 24000
SPEAKERS = {"baker": {"name": "Baker", "color": "#E3B04B"}, "knight": {"name": "Knight"}}


def voice(path, lead=0.3, speech=2.0, tail=0.5):
    """A stand-in voice file: silence, a tone (the speech), silence."""
    n0, n1, n2 = int(lead * RATE), int(speech * RATE), int(tail * RATE)
    write_wav(path, [0.0] * n0 + [0.4 * math.sin(2 * math.pi * 220 * i / RATE) for i in range(n1)] + [0.0] * n2, RATE)


class DialogueExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def src(self, lines, sequences=None, speakers=None):
        data = {"version": 1, "locale": "en", "speakers": speakers or SPEAKERS, "lines": lines,
                "sequences": sequences or {}}
        path = self.root / "dialogue.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def build(self, lines, **kw):
        return D.build(self.src(lines, kw.pop("sequences", None), kw.pop("speakers", None)), self.root, **kw)

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = D.main([str(a) for a in args])
        return rc, out.getvalue() + err.getvalue()

    # ---- reveal
    def test_voice_file_reveal_spans_the_voiced_part(self):
        voice(self.root / "v.wav")
        built, errors, _ = self.build([{"id": "baker.greet", "speaker": "baker", "text": "Welcome, traveler.",
                                        "audio": "v.wav"}])
        self.assertEqual(errors, [])
        line = built["lines"]["baker.greet"]
        times = [r["t"] for r in line["reveal"]]
        self.assertEqual(line["reveal_source"], "estimated")
        self.assertEqual(len(times), len("Welcome, traveler."))
        self.assertEqual(times, sorted(times))
        self.assertAlmostEqual(times[0], 0.3, delta=0.01, msg="starts when the voice starts, not at the file's start")
        self.assertLess(times[-1], 2.3)
        self.assertAlmostEqual(line["duration_s"], 2.8, delta=0.01)
        gap_after_comma = times[8] - times[7]
        self.assertGreater(gap_after_comma, 2 * (times[3] - times[2]), "a pause after the comma")

    def test_babble_timeline_reveal_is_copied_exactly(self):
        text = "Hee hee! Over here!"
        wav, tl = babble.render(text, "sprite", babble.check_params(dict(babble.PRESETS["sprite"])))
        write_wav(self.root / "b.wav", wav, babble.RATE)
        (self.root / "b.timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        built, errors, _ = self.build([{"id": "sprite.hi", "speaker": "baker", "text": text, "kind": "bark",
                                        "cooldown_s": 5, "audio": "b.wav", "timeline": "b.timeline.json"}])
        self.assertEqual(errors, [])
        line = built["lines"]["sprite.hi"]
        self.assertEqual((line["reveal_source"], line["reveal"]), ("babble", tl["reveal"]))

    def test_timeline_for_another_text_is_an_error(self):
        wav, tl = babble.render("Something else.", "knight", babble.check_params(dict(babble.PRESETS["knight"])))
        (self.root / "x.timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        _, errors, _ = self.build([{"id": "k.a", "speaker": "knight", "text": "Hello.", "timeline": "x.timeline.json"}])
        self.assertTrue(any("made for another text" in e for e in errors), errors)

    def test_one_reveal_per_code_point_for_any_script(self):
        text = "Café crème, ¡olé! 👋 Ünd 漢字."
        built, errors, _ = self.build([{"id": "k.u", "speaker": "knight", "text": text}])
        self.assertEqual(errors, [])
        self.assertEqual(len(built["lines"]["k.u"]["reveal"]), len(list(text)))

    # ---- cues
    def test_cues_follow_the_guidelines(self):
        text = ("Long ago, before the kingdom had walls, the smiths of the valley forged a crown from fallen star "
                "iron. It was lost in the war, and some say it still calls to anyone brave enough to listen.")
        cues = [lines for _, lines in D.segment(text, 40)]
        for c in cues:
            self.assertLessEqual(len(c), 2)
            self.assertTrue(all(len(x) <= 40 for x in c), c)
        self.assertEqual(" ".join(" ".join(c) for c in cues), text, "every word kept, in order")
        for c in cues:
            self.assertIn(c[-1][-1], ".,;:!?", f"cue ends mid-clause: {c}")
        self.assertGreater(min(sum(len(x) for x in c) for c in cues), 10, "no scrap cue")

    def test_two_line_break_prefers_punctuation_and_bottom_heavy(self):
        self.assertEqual(D.split_two("Welcome, traveler. The bakery opens at dawn.".split(), 40),
                         ["Welcome, traveler.", "The bakery opens at dawn."])
        top, bottom = D.split_two("Bring me three iron ingots from the mine and the blade is yours".split(), 40)
        self.assertLessEqual(len(top), len(bottom) + 1)

    def test_short_lines_get_the_minimum_display_time(self):
        voice(self.root / "s.wav", lead=0.0, speech=0.2, tail=0.0)
        built, _, _ = self.build([{"id": "k.y", "speaker": "knight", "text": "Yes.", "audio": "s.wav"}])
        cue = built["lines"]["k.y"]["cues"][0]
        self.assertAlmostEqual(cue["end"] - cue["start"], D.STYLE["min_cue_s"], places=3)

    def test_reading_speed_and_long_cue_warnings(self):
        voice(self.root / "fast.wav", lead=0.0, speech=1.0, tail=0.0)
        text = "That will be twenty five gold or three loaves and one wheel of cheese."
        _, _, warnings = self.build([{"id": "b.fast", "speaker": "baker", "text": text, "audio": "fast.wav"}])
        self.assertTrue(any("characters a second" in w for w in warnings), warnings)
        voice(self.root / "slow.wav", lead=0.0, speech=9.0, tail=0.0)
        _, _, warnings = self.build([{"id": "b.slow", "speaker": "baker", "text": "Hmm.", "audio": "slow.wav"}])
        self.assertTrue(any("guideline at most 7 s" in w for w in warnings), warnings)

    def test_children_audience_is_stricter(self):
        voice(self.root / "v.wav", lead=0.0, speech=2.9, tail=0.0)
        line = [{"id": "b.k", "speaker": "baker", "text": "Bring me three iron ingots from the mine, quickly now.",
                 "audio": "v.wav"}]          # 54 characters over 2.9 s: 18.6 a second, between 17 and 20
        _, _, adults = self.build(line)
        _, _, kids = self.build(line, audience="children")
        self.assertFalse(any("characters a second" in w for w in adults), adults)
        self.assertTrue(any("guideline 17" in w for w in kids), kids)

    # ---- captions and sequences
    def test_captions_come_from_audio_events(self):
        events = {"version": 1, "buses": {"master": {}}, "events": {
            "door_creak": {"bus": "master", "files": ["d.wav"], "caption": "[door creaks]", "directional": True},
            "ui_click": {"bus": "master", "files": ["c.wav"]}}}
        (self.root / "ev.json").write_text(json.dumps(events), encoding="utf-8")
        built, _, _ = self.build([{"id": "k.a", "speaker": "knight", "text": "Hi."}], events_path=self.root / "ev.json")
        self.assertEqual(built["captions"], {"door_creak": {"text": "[door creaks]", "priority": 30, "min_s": 1.0,
                                                            "directional": True}})

    def test_sequences_and_exports(self):
        voice(self.root / "a.wav", lead=0.0, speech=1.0, tail=0.0)
        voice(self.root / "b.wav", lead=0.0, speech=1.5, tail=0.0)
        lines = [{"id": "b.one", "speaker": "baker", "text": "Fresh bread!", "audio": "a.wav"},
                 {"id": "b.two", "speaker": "baker", "text": "Two coins.", "audio": "b.wav"},
                 {"id": "k.one", "speaker": "knight", "text": "Halt!", "audio": "a.wav"}]
        seq = {"intro": [{"line": "b.one", "at": 0.5}, {"line": "b.two", "after": "b.one", "gap_s": 0.25},
                         {"line": "k.one", "after": "b.two", "gap_s": 0.25}]}
        built, errors, _ = self.build(lines, sequences=seq)
        self.assertEqual(errors, [])
        self.assertEqual(built["sequences"]["intro"], [{"line": "b.one", "start": 0.5, "end": 1.5},
                                                       {"line": "b.two", "start": 1.75, "end": 3.25},
                                                       {"line": "k.one", "start": 3.5, "end": 4.5}])
        cues = D.sequence_cues(built, "intro")
        self.assertEqual(D.to_srt(cues),
                         "1\r\n00:00:00,500 --> 00:00:01,500\r\nBAKER: Fresh bread!\r\n\r\n"
                         "2\r\n00:00:01,750 --> 00:00:03,250\r\nTwo coins.\r\n\r\n"
                         "3\r\n00:00:03,500 --> 00:00:04,500\r\nKNIGHT: Halt!\r\n")
        self.assertEqual(D.to_vtt(cues),
                         "WEBVTT\n\n00:00:00.500 --> 00:00:01.500\n<v Baker>Fresh bread!\n\n"
                         "00:00:01.750 --> 00:00:03.250\n<v Baker>Two coins.\n\n"
                         "00:00:03.500 --> 00:00:04.500\n<v Knight>Halt!\n")

    def test_speaker_named_again_after_a_long_pause(self):
        built, _, _ = self.build([{"id": "b.a", "speaker": "baker", "text": "Morning."},
                                  {"id": "b.b", "speaker": "baker", "text": "Still here."}],
                                 sequences={"s": [{"line": "b.a", "at": 0}, {"line": "b.b", "at": 120}]})
        self.assertEqual([c["name"] for c in D.sequence_cues(built, "s")], ["Baker", "Baker"])

    # ---- errors and CLI
    def test_errors_are_named(self):
        cases = [([{"id": "k.a", "speaker": "nobody", "text": "x"}], "speaker 'nobody'"),
                 ([{"id": "k.a", "speaker": "knight", "text": "x"}, {"id": "k.a", "speaker": "knight", "text": "y"}],
                  "duplicate id"),
                 ([{"id": "Big Id", "speaker": "knight", "text": "x"}], "lowercase ASCII"),
                 ([{"id": "k.a", "speaker": "knight", "text": "  "}], "text is empty"),
                 ([{"id": "k.a", "speaker": "knight", "text": "x", "audio": "gone.wav"}], "audio gone.wav not found"),
                 ([{"id": "k.a", "speaker": "knight", "text": "x", "kind": "shout"}], "kind must be"),
                 ([{"id": "k.a", "speaker": "knight", "text": "x"}], None)]
        for lines, words in cases:
            _, errors, _ = self.build(lines)
            if words is None:
                self.assertEqual(errors, [])
            else:
                self.assertTrue(any(words in e for e in errors), f"{words}: {errors}")
        _, errors, _ = self.build([{"id": "k.a", "speaker": "knight", "text": "x"}],
                                  sequences={"s": [{"line": "k.a", "after": "k.zzz"}]})
        self.assertTrue(any("'after' must name an earlier" in e for e in errors), errors)

    def test_cli_build_lint_export(self):
        self.src([{"id": "k.a", "speaker": "knight", "text": "Halt! Who goes there?"},
                  {"id": "k.b", "speaker": "knight", "text": "Hey!", "kind": "bark"}],
                 sequences={"s": [{"line": "k.a", "at": 0}]})
        out = self.root / "built.json"
        rc, text = self.run_tool("build", self.root / "dialogue.json", "--root", self.root, "--out", out)
        self.assertEqual(rc, 0, text)
        rc, text = self.run_tool("build", self.root / "dialogue.json", "--root", self.root, "--out", out)
        self.assertEqual(rc, 2, "existing output needs --overwrite")
        rc, text = self.run_tool("lint", self.root / "dialogue.json", "--root", self.root)
        self.assertEqual(rc, 0, text)
        rc, text = self.run_tool("lint", self.root / "dialogue.json", "--root", self.root, "--strict")
        self.assertEqual(rc, 1, "the bark without cooldown is a warning")
        rc, text = self.run_tool("export", out, "--sequence", "s", "--format", "vtt", "--out", self.root / "s.vtt")
        self.assertEqual(rc, 0, text)
        self.assertTrue((self.root / "s.vtt").read_text(encoding="utf-8").startswith("WEBVTT"))
        rc, text = self.run_tool("export", out, "--sequence", "nope", "--out", self.root / "n.srt")
        self.assertEqual(rc, 2, text)

    def test_docs_example_builds_clean(self):
        doc = (Path(__file__).resolve().parents[2] / "docs" / "resources" / "audio.md").read_text(encoding="utf-8")
        section = doc.split("## Dialogue and subtitles", 1)[1]
        example = json.loads(section.split("```json", 1)[1].split("```", 1)[0])
        for line in example["lines"]:            # stand-ins for the voice files the example names
            line.pop("timeline", None)
            if "audio" in line:
                (self.root / line["audio"]).parent.mkdir(parents=True, exist_ok=True)
                voice(self.root / line["audio"])
        path = self.root / "example.json"
        path.write_text(json.dumps(example), encoding="utf-8")
        built, errors, warnings = D.build(path, self.root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual([s["line"] for s in built["sequences"]["gate"]], ["guard.halt", "merchant.offer"])

    def test_built_file_has_the_shape_the_engines_read(self):
        voice(self.root / "v.wav")
        built, _, _ = self.build([{"id": "b.a", "speaker": "baker", "text": "Welcome.", "audio": "v.wav"}])
        self.assertEqual(built["version"], 1)
        for key in ("max_chars_per_line", "max_lines", "min_cue_s", "max_cps"):
            self.assertIn(key, built["style"])
        line = built["lines"]["b.a"]
        for key in ("speaker", "name", "color", "text", "kind", "priority", "interrupt", "cooldown_s", "duration_s",
                    "reveal_source", "reveal", "cues", "audio"):
            self.assertIn(key, line)
        self.assertEqual(len(line["reveal"]), len(list(line["text"])))
        self.assertTrue(all(set(c) == {"start", "end", "lines"} for c in line["cues"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
