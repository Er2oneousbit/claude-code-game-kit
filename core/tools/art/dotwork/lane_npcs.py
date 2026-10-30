#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_npcs.py
# Purpose : townsfolk in bulk: a character made the cheap way (walk clips only; idles are the code-drawn 1 px
#           breathing bob in every direction, so a symmetric NPC costs one rotation and three Wan clips instead of six
#           or more), plus palette variants of it (recolor.py over every frame with one colour map: no render), each a
#           full character of its own (frames, sheets, SpriteFrames).
# Usage   : pack spec "npcs": [{"name": "baker", "prompt": "a plump baker in a white apron and a flat cap",
#           "variants": [{"name": "baker_green", "hue": 120}, {"name": "baker_dark", "lightness": -0.08}]}]
#           keys: every character key (prompt / source, seed, asymmetric, directions, clip_fix ...); actions (default
#           idle and walk); idle: "bob" (default) or "clip" (render Wan idles like a party member); variants: name +
#           hue / to / saturation / lightness / hues / min_chroma as in recolor.py; keep_skin (default true here)
#           leaves skin tones alone.
# Notes   : Variants share the base's colour map across every frame, so they animate exactly like it; outline and greys
#           stay (min_chroma). A variant's colours snap to the object palette. Review: <src>/art/characters/
#           npcs_lineup.png shows each NPC and its variants side by side.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import copy
import os

from PIL import Image

import fcore as core
import recolor
from lane_character import Character

import engine as lib  # noqa: E402

ALL_DIRS = ["s", "e", "n", "w"]


def check(entries):
    """Spec errors before any render: variant names unique and not an NPC's own name, swap options valid."""
    names = {core.snake(e["name"]) for e in entries}
    seen = set()
    for e in entries:
        if e.get("idle", "bob") not in ("bob", "clip"):
            raise core.ToolError(f"npc {e['name']}: idle is \"bob\" or \"clip\", not {e.get('idle')!r}")
        for v in e.get("variants") or []:
            if not isinstance(v, dict) or not v.get("name"):
                raise core.ToolError(f"npc {e['name']}: every variant needs a \"name\"")
            vn = core.snake(v["name"])
            if vn in names or vn in seen:
                raise core.ToolError(f"npc {e['name']}: variant name {vn!r} is already used")
            seen.add(vn)
            if not v.get("edit"):   # an outfit variant ("edit") renders; a palette swap is checked here
                recolor.options(dict({"keep_skin": True}, **v))


def npc_conf(conf, e):
    """The design an NPC renders with: the code-drawn idle in every direction unless idle is "clip"."""
    c = copy.deepcopy(conf)
    if e.get("idle", "bob") == "bob":
        c["design"]["character"]["procedural_idle"] = list(ALL_DIRS)
    return c


def variant(base, clips, rot, v, pack, man, conf, pal):
    """Recolour every frame, still and rotation of a built character with one map and export it under v's name."""
    name = core.snake(v["name"])
    frames = [f for fr, _ in clips.values() for f in fr] + [Image.open(p).convert("RGBA") for p in rot.values()]
    cols, counts = recolor.colours_of(frames)
    mapping = recolor.plan(cols, counts, pal, **recolor.options(dict({"keep_skin": True}, **v)))
    vc = Character({"name": name, "actions": base.actions, "directions": base.dirs, "asymmetric": base.asym}, pack, man,
                   conf)
    vrot = {}
    for k, p in rot.items():
        dst = os.path.join(vc.work, f"rot_{k}.png")
        core.save_clean(recolor.apply(Image.open(p), mapping), dst)
        vrot[k] = dst
    vclips = {key: ([recolor.apply(f, mapping) for f in fr], notes + [f"palette variant of {base.name}"])
              for key, (fr, notes) in clips.items()}
    man.assume(f"{name}: palette variant of {base.name} ({len(mapping)} colours moved, no render)")
    vc.export(vclips, vrot)
    core.log(f"npc {name}: palette variant of {base.name} ({len(mapping)} colours moved)")
    return vc


def lineup(rows, out):
    """One row per NPC: the first south idle frame of the NPC and of each variant."""
    lib.sheet(rows, out, scale=3)
    return out


def run(entries, pack, man, conf):
    check(entries)
    pal = lib.load_hex(conf["fixed"]["palette"])
    rows = []
    for e in entries:
        e2 = dict(e)
        e2.setdefault("actions", ["idle", "walk"])
        nconf = npc_conf(conf, e)
        c = Character(e2, pack, man, nconf)
        clips, rot = c.build()
        c.export(clips, rot)
        made = [c]
        for v in e.get("variants") or []:
            if v.get("edit"):   # an outfit: a whole NPC of its own from the edited south sprite
                c.outfit(v)
                made.append(Character({"name": core.snake(v["name"])}, pack, man, nconf))   # for the lineup
            else:
                made.append(variant(c, clips, rot, v, pack, man, nconf, pal))
        first = f"{'idle' if 'idle' in c.actions else c.actions[0]}_s"
        rows.append((c.name, [os.path.join(x.out, "frames", f"spr_{x.name}_{first}_00.png") for x in made]))
    if rows:
        lineup(rows, core.src(conf, "art", "characters", "npcs_lineup.png"))
