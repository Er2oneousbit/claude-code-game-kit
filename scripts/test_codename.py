#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_codename.py
# Purpose : Exam for codename.py, the first thing the make-a-game skill runs. Checks the slug form names are compared
#           in, that folders AND files count as taken (in any spelling the scaffolder would slug the same), that the
#           pick never lands on a taken name (one name left free must be the one printed, for every seed), that a
#           folder that does not exist takes nothing, that --seed repeats, and that a file as --check-dir, every name
#           taken and a bad --seed exit 2 with an [error] or usage line.
# Usage   : python scripts/test_codename.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only, offline. Every CLI run passes --check-dir with a temp folder, so the exam never
#           depends on what sits next to the kit.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codename  # noqa: E402

TOOL = HERE / "codename.py"
SEEDS = range(25)                 # enough dice rolls that "never picks a taken name" means something
ALL = [f"{codename.PREFIX}_{c}_{w}" for c in codename.COLORS for w in codename.WORDS]
NAME_RE = re.compile(r"^Project_(%s)_(%s)$" % ("|".join(codename.COLORS), "|".join(codename.WORDS)))


def cli(*args):
    r = subprocess.run([sys.executable, "-B", str(TOOL), *[str(a) for a in args]], capture_output=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout.strip(), r.stderr


class CodenameExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fill(self, names, as_files=False):
        """Make a folder (or an empty file) per name in the temp check-dir."""
        for n in names:
            p = self.dir / n
            if as_files:
                p.write_bytes(b"")
            else:
                p.mkdir()

    # ---- helpers in the module --------------------------------------------
    def test_normalize_matches_the_scaffolder_slug(self):
        for spelling in ("Project_Cobalt_Wyvern", "project cobalt wyvern", "PROJECT-Cobalt--Wyvern!", " Project.Cobalt.Wyvern "):
            self.assertEqual(codename.normalize(spelling), "project_cobalt_wyvern", spelling)

    def test_name_pool_is_576_distinct_names(self):
        self.assertEqual(len(ALL), 576)
        self.assertEqual(len({codename.normalize(n) for n in ALL}), 576)

    def test_taken_names(self):
        self.assertEqual(codename.taken_names(self.dir / "not-there-yet"), set())
        self.fill(["Project_Amber_Comet"])
        self.fill(["project jade relic.txt"], as_files=True)
        self.assertEqual(codename.taken_names(self.dir), {"project_amber_comet", "project_jade_relic_txt"})
        with self.assertRaises(OSError):
            codename.taken_names(self.dir / "project jade relic.txt")

    def test_roll_never_picks_a_taken_name(self):
        free = "Project_Ochre_Sphinx"
        taken = {codename.normalize(n) for n in ALL if n != free}
        for seed in SEEDS:
            self.assertEqual(codename.roll(random.Random(seed), taken), free, f"seed {seed}")
        self.assertIsNone(codename.roll(random.Random(0), taken | {codename.normalize(free)}))

    # ---- the command line --------------------------------------------------
    def test_prints_a_well_formed_name_and_seed_repeats(self):
        code, out, err = cli("--check-dir", self.dir, "--seed", "7")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, NAME_RE)
        self.assertEqual(cli("--check-dir", self.dir, "--seed", "7")[1], out, "--seed must repeat")
        outs = {cli("--check-dir", self.dir, "--seed", s)[1] for s in (1, 2, 3, 4, 5)}
        self.assertGreater(len(outs), 1, "different seeds should not all give one name")

    def test_existing_folder_and_file_are_skipped(self):
        first = cli("--check-dir", self.dir, "--seed", "7")[1]
        self.fill([first.lower().replace("_", " ")])          # same slug, other spelling: still taken
        second = cli("--check-dir", self.dir, "--seed", "7")[1]
        self.assertNotEqual(codename.normalize(second), codename.normalize(first))
        self.fill([second], as_files=True)                    # a file blocks the folder too
        third = cli("--check-dir", self.dir, "--seed", "7")[1]
        self.assertNotIn(codename.normalize(third), {codename.normalize(first), codename.normalize(second)})

    def test_one_free_name_left_is_the_one_printed(self):
        free = "Project_Teal_Golem"
        self.fill([n for n in ALL if n != free][:300])
        self.fill([n for n in ALL if n != free][300:], as_files=True)
        for seed in (0, 1, 2, 3):
            code, out, err = cli("--check-dir", self.dir, "--seed", seed)
            self.assertEqual((code, out), (0, free), err)

    def test_all_taken_exits_2(self):
        self.fill(ALL, as_files=True)
        code, out, err = cli("--check-dir", self.dir)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("[error] all 576 codenames are taken", err)

    def test_check_dir_is_a_file_exits_2(self):
        f = self.dir / "a_file.txt"
        f.write_bytes(b"x")
        code, out, err = cli("--check-dir", f)
        self.assertEqual(code, 2)
        self.assertIn("[error] cannot check", err)
        self.assertIn("is a file", err)
        self.assertNotIn("Traceback", err)

    def test_missing_check_dir_takes_nothing(self):
        code, out, err = cli("--check-dir", self.dir / "games" / "not-made-yet", "--debug")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, NAME_RE)
        self.assertIn("[debug] checked", err)
        self.assertIn("0 folder name(s)", err)

    def test_bad_seed_is_a_usage_error(self):
        code, out, err = cli("--check-dir", self.dir, "--seed", "seven")
        self.assertEqual(code, 2)
        self.assertIn("--seed", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
