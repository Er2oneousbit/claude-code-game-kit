#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# codename.py
# Purpose : Give a new game a random placeholder name, Project_<Color>_<Word> (e.g. Project_Cobalt_Wyvern), for the
#           make-a-game skill. A model asked to "pick at random" lands on the same few names; this rolls real dice.
# Usage   : python scripts/codename.py                     # print one codename
#           python scripts/codename.py --check-dir D:/Games # re-roll while a folder with that name exists there
#           python scripts/codename.py --seed 7             # repeatable, for tests and debugging
# Exit    : 0 printed a codename, 2 usage problem, --check-dir is a file or unreadable, or no free name left there
# Notes   : Standard library only. Without --check-dir it checks the folder that holds the kit (where make-a-game
#           puts new games). A name counts as taken when a folder or file there has the same slug (lowercase, every run
#           of other characters one "_", as the scaffolder makes it: "Project Cobalt Wyvern" = project_cobalt_wyvern). A folder that does not exist yet
#           takes nothing. 24 x 24 = 576 names; the pick is made among the free ones only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   parse args -> list the names already in --check-dir (normalized; files count too)
#   build every free combination -> pick one at random, print it, exit 0
#   --check-dir is a file or unreadable -> [error], exit 2; every name taken -> [error], exit 2
import argparse
import random
import re
import sys
from pathlib import Path

COLORS = ("Amber", "Azure", "Cobalt", "Coral", "Crimson", "Cyan", "Ember", "Emerald", "Gilded", "Indigo", "Ivory",
          "Jade", "Lilac", "Magenta", "Obsidian", "Ochre", "Onyx", "Saffron", "Scarlet", "Silver", "Teal", "Umber",
          "Verdant", "Violet")
WORDS = ("Aether", "Basilisk", "Comet", "Drake", "Golem", "Griffin", "Hydra", "Kraken", "Lantern", "Nebula", "Nova",
         "Oracle", "Phoenix", "Pulsar", "Quasar", "Relic", "Rune", "Specter", "Sphinx", "Starforge", "Titan", "Warden",
         "Wyvern", "Zephyr")
PREFIX = "Project"
KIT_PARENT = Path(__file__).resolve().parent.parent.parent


def normalize(name):
    """The scaffolder's slug form: lowercase, every run of other characters one underscore."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def taken_names(folder):
    """Names already used in folder (files count too: the scaffolder cannot create a folder over a file).
    A folder that does not exist yet takes nothing; a file or an unreadable folder raises OSError."""
    path = Path(folder)
    if not path.exists():
        return set()
    if not path.is_dir():
        raise OSError(f"{folder} is a file, not a folder")
    return {normalize(p.name) for p in path.iterdir()}


def roll(rng, taken):
    """A random free name, or None when every combination is taken (so None means exactly that)."""
    free = [f"{PREFIX}_{c}_{w}" for c in COLORS for w in WORDS if normalize(f"{PREFIX}_{c}_{w}") not in taken]
    return rng.choice(free) if free else None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows pipes default to cp1252
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Print a random placeholder game name, Project_<Color>_<Word>.",
                                 epilog="Exit 0 printed a name, 2 usage problem or no free name left.")
    ap.add_argument("--check-dir", default=str(KIT_PARENT),
                    help="re-roll while a folder with the same name exists here (default: the folder holding the kit)")
    ap.add_argument("--seed", type=int, help="seed the dice (repeatable output, for tests)")
    ap.add_argument("--debug", action="store_true", help="print the folder checked and how many names are taken")
    args = ap.parse_args(argv)
    try:
        taken = taken_names(args.check_dir)
    except OSError as exc:
        print(f"[error] cannot check {args.check_dir}: {exc}", file=sys.stderr)
        return 2
    if args.debug:
        print(f"[debug] checked {args.check_dir}: {len(taken)} folder name(s)", file=sys.stderr)
    name = roll(random.Random(args.seed), taken)
    if name is None:
        print(f"[error] all {len(COLORS) * len(WORDS)} codenames are taken in {args.check_dir}", file=sys.stderr)
        return 2
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
