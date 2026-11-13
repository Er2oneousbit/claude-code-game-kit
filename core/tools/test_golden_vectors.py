#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_golden_vectors.py
# Purpose : Exam for tools/golden_vectors.py, the reference every engine port of the juice and shell logic is tested
#           against: the vector files are current, and the reference itself behaves as SOP-18 and SOP-19 promise.
# Usage   : python tools/test_golden_vectors.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): credits_text, the markdown every credits screen strips (#284)
# ---------------------------------------------------------------------------
import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_vectors as gv  # noqa: E402


class VectorFiles(unittest.TestCase):
    def test_files_are_current(self):
        self.assertEqual(gv.main(["--check"]), 0, "run python tools/golden_vectors.py --write")

    def test_write_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            gv.main(["--write", "--out", d])
            first = {p.name: p.read_bytes() for p in Path(d).iterdir()}
            gv.main(["--write", "--out", d])
            self.assertEqual(first, {p.name: p.read_bytes() for p in Path(d).iterdir()})

    def test_tolerance_tells_a_float32_port_from_a_64_bit_one(self):
        # Every port is 64-bit. A port that stored its results as float32 must fail the exam: the ease and
        # hitstop vectors carry values near 1 and 0.1, where float32 rounding moves them by up to 6e-8.
        juice = json.loads((gv.OUT_DIR / "juice.json").read_text(encoding="utf-8"))
        tol = juice["tolerance"]

        def f32(x):
            return struct.unpack("f", struct.pack("f", x))[0]
        for kind, values in (("ease", [p[2] for c in juice["cases"] if c["type"] == "ease" for p in c["points"]]),
                             ("hitstop", [v for c in juice["cases"] if c["type"] == "hitstop" for st in c["steps"]
                                          if "expect" in st for v in st["expect"].values()])):
            worst = max(abs(f32(v) - v) for v in values)
            self.assertGreater(worst, tol, f"{kind}: a float32 port would pass at tolerance {tol}")

    def test_the_shell_vectors_pin_a_missing_file_and_a_foreign_version(self):
        """#261: every port documents "no file: the defaults, no problems" and "version = 1 whatever the file said",
        and no vector held either, so a port could drift on both and still pass."""
        loads = [c for c in json.loads(gv.render(gv.build_shell()))["cases"] if c["type"] == "settings_load"]
        missing = [c for c in loads if c["input"] is None]
        self.assertEqual([(c["problems"], c["expect"]) for c in missing], [(0, gv.DEFAULT_SETTINGS)])
        def version_of(text):
            try:
                raw = json.loads(text) if text else {}
            except ValueError:                           # the "not json" case
                return None
            return raw.get("version") if isinstance(raw, dict) else None
        foreign = [c for c in loads if version_of(c["input"]) not in (None, 1)]
        self.assertTrue(foreign, "no settings_load case carries a version other than 1")
        for c in foreign:
            self.assertEqual(c["expect"]["version"], 1, c["name"])
            self.assertGreater(c["problems"], 0, "the foreign-version case should also carry wrongly typed fields")

    def test_every_case_has_a_type_and_name(self):
        for build in (gv.build_juice, gv.build_shell, gv.build_telemetry):
            data = json.loads(gv.render(build()))
            self.assertEqual(data["version"], gv.VECTOR_VERSION)
            for case in data["cases"]:
                self.assertTrue(case.get("type") and case.get("name"), case)


class Juice(unittest.TestCase):
    def test_noise_is_bounded_and_continuous(self):
        prev = gv.noise(3, 0.0, 0)
        for k in range(1, 2000):
            v = gv.noise(3, k * 0.01, 0)
            self.assertLessEqual(abs(v), 1.0)
            self.assertLess(abs(v - prev), 0.1)          # smooth: no jumps between close samples
            prev = v

    def test_lattice_stays_exact(self):
        # the largest product the formula makes must stay below 2^53, or doubles (Lua, JS) would round
        i = 10 ** 7
        self.assertLess((7919 * 10 ** 4 + i * 104729 + 2 * 15485863), 2 ** 53)
        self.assertLess((gv.PM_M - 1) * gv.PM_A, 2 ** 53)

    def test_shake_decays_to_zero_and_respects_intensity(self):
        s = gv.Shake(decay=2.0)
        s.add_trauma(1.0)
        self.assertEqual(s.update(0.016, 0.0), (0.0, 0.0, 0.0))
        for _ in range(100):
            s.update(0.016)
        self.assertEqual(s.trauma, 0.0)
        s.add_trauma(5.0)
        self.assertEqual(s.trauma, 1.0)

    def test_hitstop_freezes_then_resumes(self):
        h = gv.Hitstop(0.1)
        h.hit(1.0)
        self.assertAlmostEqual(h.remaining, 0.1)
        self.assertEqual(h.scaled_dt(0.05), 0.0)
        self.assertAlmostEqual(h.scaled_dt(0.08), 0.03)
        self.assertEqual(h.scaled_dt(0.05), 0.05)

    def test_eases_hit_their_ends(self):
        for name in gv.EASES:
            self.assertAlmostEqual(gv.ease(name, 0.0), 0.0, msg=name)
            self.assertAlmostEqual(gv.ease(name, 1.0), 1.0, msg=name)

    def test_follow_stays_inside_deadzone(self):
        f = gv.Follow(64, 48, 0.0, 0.0)
        f.update(0.016, 20, 10)
        self.assertEqual((f.x, f.y), (0.0, 0.0))
        f.update(0.016, 100, 0)
        self.assertEqual(f.x, 68.0)

    def test_follow_is_frame_rate_independent(self):
        a, b = gv.Follow(0, 0, 0, 5.0), gv.Follow(0, 0, 0, 5.0)
        a.update(0.1, 100, 0)
        for _ in range(10):
            b.update(0.01, 100, 0)
        self.assertAlmostEqual(a.x, b.x)

    def test_flash_limiter_allows_three_per_second(self):
        fl = gv.FlashLimiter()
        self.assertEqual([fl.request(t) for t in (0, 0.1, 0.2, 0.3, 1.05)], [True, True, True, False, True])

    def test_squash_keeps_area(self):
        for a in (0.3, -0.5, 2.0):
            sx, sy = gv.squash(a)
            self.assertAlmostEqual(sx * sy, 1.0)


class Shell(unittest.TestCase):
    def test_load_of_dump_is_identity(self):
        s, problems = gv.settings_load(json.dumps(gv.DEFAULT_SETTINGS))
        self.assertEqual((s, problems), (gv.DEFAULT_SETTINGS, []))
        again, problems = gv.settings_load(json.dumps(s))
        self.assertEqual((again, problems), (s, []))

    def test_fixed_settings_load_clean(self):
        for text in ('{"audio": {"master": 9}}', '{"input": {"bindings": {"jump": [1]}}}', "[]", "nope"):
            s, _ = gv.settings_load(text)
            self.assertEqual(gv.settings_load(json.dumps(s))[1], [], text)

    def test_missing_file_is_defaults_without_problems(self):
        self.assertEqual(gv.settings_load(None), (gv.DEFAULT_SETTINGS, []))

    def test_rebind_swap_keeps_every_binding_once_per_group(self):
        out, conflicts = gv.rebind(gv.DEFAULT_BINDINGS, "jump", 0, "key:j")
        self.assertEqual(conflicts, [["attack", 0]])
        self.assertEqual((out["jump"][0], out["attack"][0]), ("key:j", "key:space"))
        self.assertEqual(gv.DEFAULT_BINDINGS["jump"][0], "key:space")    # input not modified

    def test_save_migrates_and_never_loads_newer(self):
        env, source, _ = gv.save_load('{"format": "save", "version": 1, "data": {"hp": 3}}', None)
        self.assertEqual((env["version"], env["data"], source), (3, {"health": 3, "difficulty": "normal"}, "primary"))
        env, source, problems = gv.save_load('{"format": "save", "version": 99, "data": {}}', None)
        self.assertEqual((env, source), (None, "none"))
        self.assertIn("primary: newer", problems)

    def test_non_finite_numbers_are_problems_not_crashes(self):
        """#132: int(Infinity) and int(NaN) raised out of the resolution rule and the save version check."""
        for text in ('{"display": {"resolution": [Infinity, 720]}}', '{"display": {"resolution": [1280, NaN]}}',
                     '{"display": {"resolution": [-Infinity, 720]}}'):
            s, problems = gv.settings_load(text)
            self.assertEqual(s["display"]["resolution"], gv.DEFAULT_SETTINGS["display"]["resolution"], text)
            self.assertEqual(problems, ["display.resolution"], text)
        for const in ("Infinity", "-Infinity", "NaN"):
            env, source, problems = gv.save_load('{"format": "save", "version": %s, "data": {}}' % const, None)
            self.assertEqual((env, source), (None, "none"), const)
            self.assertEqual(problems, ["primary: bad version", "backup: missing"], const)

    def test_language_length_counts_code_points(self):
        wide = "\U0001D523"                          # one code point, two UTF-16 units
        self.assertEqual(gv.settings_load(json.dumps({"language": "x-" + wide * 6}))[0]["language"], "x-" + wide * 6)
        self.assertEqual(gv.settings_load(json.dumps({"language": wide}))[0]["language"], "en")

    def test_pseudo_keeps_placeholders_and_grows(self):
        out = gv.pseudo("Hello {name}, you have %d coins")
        self.assertIn("{name}", out)
        self.assertIn("%d", out)
        self.assertGreater(len(out), len("Hello {name}, you have %d coins") * 1.35)

    def test_tr_falls_back_and_shows_missing_keys(self):
        self.assertEqual(gv.tr(gv.TABLES, "fr-CA", "greet", {"name": "Ana"}), "Bonjour, Ana !")
        self.assertEqual(gv.tr(gv.TABLES, "de", "nope"), "nope")
        self.assertEqual(gv.tr_plural(gv.TABLES, "fr", "apples", 0), "0 pomme")
        self.assertEqual(gv.tr_plural(gv.TABLES, "ja", "apples", 1), "りんご1個")


class Telemetry(unittest.TestCase):
    def test_one_column_set(self):
        self.assertEqual(gv.TELEMETRY_HEADER.split(","), ["time", "session", "event", "detail"])
        self.assertEqual(len(gv.telemetry_row(0, "00000000", "quit").split(",")), 4)

    def test_time_is_utc_whole_seconds(self):
        self.assertEqual(gv.telemetry_time(0), "1970-01-01T00:00:00Z")
        self.assertEqual(gv.telemetry_time(59.99), "1970-01-01T00:00:59Z")     # dropped, not rounded

    def test_fields_are_quoted_only_when_needed(self):
        self.assertEqual(gv.csv_field("plain"), "plain")
        self.assertEqual(gv.csv_field('a "b", c'), '"a ""b"", c"')
        self.assertEqual(gv.csv_field("x\ny"), '"x\ny"')


class Credits(unittest.TestCase):
    """#279: tools/credits.py writes an HTML comment into CREDITS.md and every credits screen showed it."""

    def test_the_vectors_hold_the_comment_credits_py_writes(self):
        import credits                                       # tools/credits.py, next to this file
        with tempfile.TemporaryDirectory() as d:
            text = credits.credits_md([], Path(d))
        self.assertIn(gv.CREDITS_HEADER, text, "credits.py changed its comment: update CREDITS_HEADER, then --write")
        self.assertNotIn("<!--", gv.strip_html_comments(text))
        self.assertEqual(gv.strip_html_comments(text), "# Credits\n")

    def test_comments_go_and_the_gap_does_not_double(self):
        self.assertEqual(gv.strip_html_comments("# A\n\n<!-- x -->\n\n- b\n"), "# A\n\n- b\n")
        self.assertEqual(gv.strip_html_comments("# A\n<!--\nmany\nlines\n-->\n- b"), "# A\n- b")
        self.assertEqual(gv.strip_html_comments("a <!-- x --> b"), "a  b")
        self.assertEqual(gv.strip_html_comments("a\n<!-- open"), "a")

    def test_text_without_a_comment_is_unchanged(self):
        for text in ("", "# Credits\n\n\n- x\n", "<! -- no --> -->", "Zoë ”q”\n"):
            self.assertEqual(gv.strip_html_comments(text), text)


class CreditsText(unittest.TestCase):
    """#284: the credits screens disagreed on markdown (web and Unity showed '#' and '- '); credits_text is the rule."""

    def test_what_credits_py_writes_shows_without_marks(self):
        import credits
        with tempfile.TemporaryDirectory() as d:
            text = credits.credits_md([], Path(d))
        self.assertEqual(gv.credits_text(text), "Credits")

    def test_marks_go_and_the_text_stays(self):
        self.assertEqual(gv.credits_text("# Credits\n\n## Music\n\n- **Song** by *Ana* (CC0)\n"),
                         "Credits\n\nMusic\n\nSong by Ana (CC0)")
        self.assertEqual(gv.credits_text("  * a_b.png\n+ c\n1. d"), "a_b.png\nc\n1. d")
        self.assertEqual(gv.credits_text("# C#\n#3\nTrack #3"), "C#\n#3\nTrack #3")

    def test_space_and_tab_only(self):
        self.assertEqual(gv.credits_text(" # x \t \n"), " # x ")

    def test_nothing_to_show_is_empty(self):
        for text in ("", "\n \t\n", "<!-- x -->\n", "#\n- \n"):
            self.assertEqual(gv.credits_text(text), "")

    def test_running_it_twice_changes_nothing_more_on_plain_text(self):
        for text in ("Credits\n\nMusic\n\nSong by Ana", "a_b and C#", "Zoë ”q”"):
            self.assertEqual(gv.credits_text(gv.credits_text(text)), gv.credits_text(text))

    def test_the_vectors_cover_the_rule(self):
        case = [c for c in gv.build_credits()["cases"] if c["type"] == "credits_text"]
        self.assertEqual(len(case), 1)
        names = [p[0] for p in case[0]["points"]]
        self.assertEqual(len(names), len(set(names)), "case names must be unique")
        self.assertIn("space and tab only", names)


if __name__ == "__main__":
    unittest.main(verbosity=1)
