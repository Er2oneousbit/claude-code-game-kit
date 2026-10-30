#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# title_mock.py
# Purpose : compose a 640x360 title screen from the game's Dotwork art: backdrop, logo in the brass title font,
#           subtitle, menu with the hand cursor; a preview, not a shipped asset.
# Usage   : dotwork.py preview title --title "MY GAME" [--subtitle TEXT] [--scene title]
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fcore as core  # noqa: E402
from battle_mock import Font  # noqa: E402



def width(font, text):
    return sum((font.g[c].shape[1] + font.meta["spacing"]) * font.scale if c in font.g else font.meta["space"] * font.scale
               for c in text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dotwork.py preview title", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", default="MY GAME")
    ap.add_argument("--subtitle", default="An Age of Brass")
    ap.add_argument("--scene", default="title")
    ap.add_argument("--out", help="PNG to write (default <src_dir>/preview/title_mock.png)")
    a = ap.parse_args(argv)
    conf = core.cfg()
    a.out = a.out or core.src(conf, "preview", "title_mock.png")
    bg = Image.open(core.art(conf, "scenes", f"spr_scene_{a.scene}.png"))
    scr = bg.convert("RGBA").resize((640, 360), Image.NEAREST)
    logo = Font("title_brass.txt", scale=4, effect="outline", gradient="brass", caps_only=True)
    sub = Font("title_brass.txt", scale=2, effect="outline", gradient="steel", caps_only=True)
    menu = Font("dialogue.txt", scale=2, effect="shadow")
    logo.draw(scr, a.title, (640 - width(logo, a.title)) // 2, 70)
    sub.draw(scr, a.subtitle, (640 - width(sub, a.subtitle)) // 2, 124)
    items = ["New Game", "Continue", "Config"]
    x0 = (640 - max(width(menu, t) for t in items)) // 2
    for i, t in enumerate(items):
        menu.draw(scr, t, x0, 250 + i * 24)
    cur = Image.open(core.art(conf, "ui", "symbols", "ui_cursor_hand.png"))
    scr.alpha_composite(cur.convert("RGBA"), (x0 - cur.width - 8, 250 + 2))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    scr.convert("RGB").save(a.out)
    scr.convert("RGB").resize((1280, 720), Image.NEAREST).save(a.out[:-4] + "_2x.png")
    print(f"[+] {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
