#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_shipped.py
# Purpose : guards over every file Dotwork ships: no text that looks like an unresolved kit placeholder (a NAME in
#           double curly braces: the kit's scaffolder stops on one, so a template token in a lane breaks every new
#           game) except the placeholders the kit fills in on purpose, and no em dashes (the kit's writing rule).
#           The tokens and the dash are built from pieces here, so this file passes its own checks.
# Usage   : python tools/art/dotwork/tests/test_shipped.py   (test_dotwork.py runs it too)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
OPEN, CLOSE = "{" * 2, "}" * 2
PLACEHOLDER = re.compile(re.escape(OPEN) + r"[A-Z_]+" + re.escape(CLOSE))
EM_DASH = chr(0x2014)
# (file relative to the Dotwork folder, token): placeholders the kit substitutes on purpose
ALLOWED = {("tests/test_dotwork.py", OPEN + "DATE" + CLOSE)}
TEXT = (".py", ".md", ".json", ".txt", ".hex", ".gd", ".gdshader", ".tres", ".tscn", ".csv", ".cfg")


def shipped_text_files():
    for d, dirs, files in os.walk(DOTWORK):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f.endswith(TEXT):
                p = os.path.join(d, f)
                yield os.path.relpath(p, DOTWORK).replace(os.sep, "/"), p


class ShippedExam(unittest.TestCase):
    def test_no_unresolved_placeholders(self):
        found = []
        for rel, p in shipped_text_files():
            with open(p, encoding="utf-8", errors="replace") as fh:
                for tok in sorted(set(PLACEHOLDER.findall(fh.read()))):
                    if (rel, tok) not in ALLOWED:
                        found.append(rel + ": " + tok)
        self.assertEqual(found, [], "the kit's scaffolder would report these as unresolved placeholders")

    def test_no_em_dashes(self):
        found = []
        for rel, p in shipped_text_files():
            with open(p, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if EM_DASH in line:
                        found.append(rel + ":" + str(n))
        self.assertEqual(found, [])

    def test_the_guard_sees_a_token(self):
        token = OPEN + "REQUIRED" + CLOSE
        self.assertEqual(PLACEHOLDER.findall("var required = " + token), [token])
        self.assertEqual(PLACEHOLDER.findall("var required = __REQUIRED__"), [])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
