#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# example_hero.py
# Purpose : The kit's reference character for tools/art/pixel_sprite.py: a steampunk hero with a piston fist,
#           32x32, facing down, left, right (mirrored) and up, walking and punching. It is the first-art floor made
#           concrete: a readable figure with hair, goggles, a scarf, 2 or 3 shades per material and an outline.
#           Copy it (`pixel_sprite.py example`), then change the palette and the body parts for your own character.
# Usage   : python tools/art/pixel_sprite.py build tools/art/sprites/example_hero.py --out build/hero
# Notes   : How the drawing works: each direction has a function that paints body parts back to front (legs, torso,
#           head, arm) with rect() on a 32x32 grid; the tool adds the dark outline and the ground shadow. Animation
#           is a few numbers per frame (leg lift, swing, body bob, piston extension). Right-facing frames are the
#           left-facing ones mirrored (MIRROR). Atlas rows: ROWS, 4 frames each.
# Authored: Written with Claude (Sonnet 5.5), iterated by hand; ported to the sprite-file format with
#           Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
from pixel_sprite import Sprite

CELL = 32
FRAMES = 4
MIRROR = {"right": "left"}
ROWS = [("walk", "down"), ("walk", "left"), ("walk", "right"), ("walk", "up"),
        ("punch", "down"), ("punch", "left"), ("punch", "right"), ("punch", "up")]

# Palette: browns, brass, teal-blue, olive and a red scarf. Edit here to re-skin everything at once.
PALETTE = {
    "outline": (27, 20, 16),
    "hair": (122, 63, 31), "hairL": (165, 90, 42),
    "skin": (240, 185, 138), "skinD": (210, 145, 100),
    "dark": (27, 20, 16), "white": (255, 255, 255), "lens": (90, 167, 201),
    "brass": (201, 149, 58), "brassL": (240, 205, 106), "brassD": (138, 95, 31),
    "steel": (120, 130, 140), "steelL": (176, 186, 196), "steelD": (85, 92, 100),
    "scarf": (184, 51, 47), "scarfD": (130, 34, 32),
    "shirt": (59, 95, 130), "shirtD": (42, 70, 98),
    "pants": (85, 107, 58), "pantsD": (62, 80, 42),
    "boot": (107, 59, 30), "bootD": (70, 38, 18),
    "belt": (90, 55, 28), "glove": (150, 90, 50),
    "spark": (255, 224, 80), "sparkW": (255, 255, 230),
}

# Animation tunables: walk leg lift (front/back views) and leg swing (side view) per frame, piston extension and
# body lean per punch frame (windup, extend, full + spark, recoil), idle bob.
LIFT = [(0, 0), (1, 0), (0, 0), (0, 1)]
SWING = [(0, 0), (-2, 2), (0, 0), (2, -2)]
PUNCH_EXT = [0, 3, 6, 2]
PUNCH_OY = [0, 0, 1, 0]
IDLE_OY = [0, 0, 1, 1]


def piston(s, bx, by, dx, dy, ext):
    """The piston arm from base (bx, by) heading (dx, dy): cylinder(4) + rod(ext) + brass cuff(1) + fist(4),
    4 px thick. Returns the tip pixel so the hit spark can sit on it."""
    segs = [("brassD", 4), ("steel", ext), ("brass", 1), ("steelL", 4)]
    pos = 0
    tip = (bx, by)
    for col, length in segs:
        for _ in range(length):
            for t in range(4):
                if col == "steel" and t in (0, 3):
                    continue  # the rod is thinner than the cylinder
                c = col
                if col == "brassD" and t == 0:
                    c = "brassL"  # highlight edge
                if col == "steelL" and t == 3:
                    c = "steelD"  # shaded edge
                x = bx + dx * pos + (t if dy else 0)
                y = by + dy * pos + (t if dx else 0)
                s.dot(x, y + s.oy, c)
                tip = (x, y + s.oy)
            pos += 1
    return tip


def spark(s, cx, cy):
    """A small impact star centred on (cx, cy)."""
    for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
        s.dot(cx + dx, cy + dy, "sparkW" if (dx, dy) == (0, 0) else "spark")
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2), (2, 2), (-2, -2), (2, -2), (-2, 2)):
        s.dot(cx + dx, cy + dy, "spark")


# ---- body parts per facing direction; ext None = idle arm, a number = punching ------------------------------------
def draw_down(lf=0, rf=0, oy=0, ext=None):
    s = Sprite(PALETTE, CELL)
    s.rect(12, 22, 15, 26 - lf, "pants"); s.rect(17, 22, 20, 26 - rf, "pants")
    s.rect(11, 26 - lf, 15, 28 - lf, "boot"); s.rect(17, 26 - rf, 21, 28 - rf, "boot")
    s.oy = oy
    s.rect(11, 15, 20, 22, "shirt"); s.rect(11, 19, 20, 20, "shirtD")
    s.rect(11, 21, 20, 22, "belt"); s.rect(15, 21, 16, 22, "brassL")
    s.rect(11, 14, 20, 16, "scarf"); s.rect(7, 12, 10, 14, "scarf"); s.rect(8, 15, 10, 16, "scarfD")
    s.rect(14, 17, 17, 18, "scarfD")
    s.rect(8, 16, 10, 20, "shirt"); s.rect(8, 21, 10, 23, "glove")
    s.rect(10, 5, 21, 13, "skin"); s.rect(10, 12, 21, 13, "skinD")
    s.rect(9, 1, 22, 4, "hair"); s.rect(12, 1, 15, 2, "hairL")
    s.rect(9, 5, 10, 9, "hair"); s.rect(21, 5, 22, 9, "hair"); s.rect(7, 3, 8, 6, "hair"); s.rect(23, 3, 24, 5, "hair")
    s.rect(10, 5, 10, 7, "brass"); s.rect(21, 5, 21, 7, "brass"); s.rect(15, 6, 16, 6, "brass")
    s.rect(11, 5, 14, 7, "lens"); s.rect(17, 5, 20, 7, "lens")
    s.rect(11, 5, 11, 5, "white"); s.rect(17, 5, 17, 5, "white")
    s.rect(12, 9, 13, 10, "dark"); s.rect(18, 9, 19, 10, "dark")
    s.rect(15, 12, 16, 12, "skinD")
    s.rect(21, 14, 24, 15, "brass")
    tip = piston(s, 21, 16, 0, 1, 1 if ext is None else ext)
    return s, tip


def draw_up(lf=0, rf=0, oy=0, ext=None):
    s = Sprite(PALETTE, CELL)
    s.rect(12, 22, 15, 26 - lf, "pants"); s.rect(17, 22, 20, 26 - rf, "pants")
    s.rect(11, 26 - lf, 15, 28 - lf, "boot"); s.rect(17, 26 - rf, 21, 28 - rf, "boot")
    s.oy = oy
    s.rect(11, 15, 20, 22, "shirt"); s.rect(11, 21, 20, 22, "belt")
    s.rect(12, 13, 19, 21, "brassD"); s.rect(13, 13, 14, 21, "brassL"); s.rect(12, 12, 19, 12, "brass")
    s.rect(16, 15, 18, 16, "brass"); s.rect(15, 18, 18, 19, "brass")
    s.rect(11, 14, 20, 15, "scarf"); s.rect(8, 16, 11, 22, "scarf"); s.rect(8, 20, 10, 22, "scarfD")
    s.rect(8, 16, 10, 20, "shirt"); s.rect(8, 21, 10, 23, "glove")
    s.rect(10, 4, 21, 13, "hair"); s.rect(12, 13, 19, 14, "skinD")
    s.rect(9, 2, 22, 5, "hair"); s.rect(12, 1, 15, 2, "hairL"); s.rect(7, 3, 8, 6, "hair"); s.rect(23, 3, 24, 5, "hair")
    s.rect(10, 8, 21, 8, "brass"); s.rect(12, 6, 14, 6, "hairL")
    s.rect(21, 14, 24, 15, "brass")
    if ext is None:
        piston(s, 21, 16, 0, 1, 1)
        tip = (22, 24)
    else:
        tip = piston(s, 21, 15, 0, -1, ext)
    return s, tip


def draw_left(bk=0, fw=0, oy=0, ext=None):
    s = Sprite(PALETTE, CELL)
    s.rect(15 + bk, 22, 17 + bk, 26, "pantsD"); s.rect(13 + bk, 26, 17 + bk, 28, "bootD")
    s.rect(13 + fw, 22, 15 + fw, 26, "pants"); s.rect(11 + fw, 26, 15 + fw, 28, "boot")
    s.oy = oy
    s.rect(12, 15, 19, 22, "shirt"); s.rect(12, 21, 19, 22, "belt"); s.rect(12, 21, 13, 22, "brassL")
    s.rect(17, 13, 21, 20, "brassD"); s.rect(17, 13, 17, 20, "brassL"); s.rect(18, 11, 20, 12, "brass")
    s.rect(12, 14, 19, 16, "scarf"); s.rect(20, 14, 25, 15, "scarf"); s.rect(22, 16, 26, 16, "scarfD")
    s.rect(10, 5, 20, 13, "skin"); s.rect(10, 12, 20, 13, "skinD")
    s.rect(16, 4, 21, 11, "hair"); s.rect(9, 1, 21, 4, "hair"); s.rect(11, 1, 14, 2, "hairL")
    s.rect(19, 5, 22, 9, "hair"); s.rect(22, 3, 24, 7, "hair"); s.rect(9, 4, 10, 5, "hair")
    s.rect(10, 5, 14, 7, "lens"); s.rect(10, 5, 10, 5, "white"); s.rect(15, 6, 20, 6, "brass")
    s.rect(14, 5, 14, 7, "brass")
    s.rect(11, 9, 12, 10, "dark"); s.rect(9, 10, 9, 10, "skin"); s.rect(11, 12, 12, 12, "skinD")
    s.rect(13, 15, 17, 16, "brass")
    if ext is None:
        piston(s, 13, 16, 0, 1, 1)
        tip = (14, 24)
    else:
        tip = piston(s, 13, 16, -1, 0, ext)
    return s, tip


DRAWERS = {"down": draw_down, "up": draw_up, "left": draw_left}
SPARK_OFFSET = {"left": (-3, 1), "down": (1, 3), "up": (1, -3)}


def draw(pose, direction, frame):
    """Called by pixel_sprite.py for every atlas cell. direction is never "right" (MIRROR flips "left")."""
    side = direction == "left"
    f = frame % 4
    if pose == "idle":
        a, b, oy, ext = 0, 0, IDLE_OY[f], None
    elif pose == "walk":
        (a, b), oy, ext = (SWING if side else LIFT)[f], 0, None
    elif pose == "punch":
        a, b, oy, ext = 0, 0, PUNCH_OY[f], PUNCH_EXT[f]
    else:
        raise ValueError(f"unknown pose {pose}")
    s, tip = DRAWERS[direction](a, b, oy, ext)
    if pose == "punch" and f == 2:
        dx, dy = SPARK_OFFSET[direction]
        spark(s, tip[0] + dx, tip[1] + dy)
    return s
