#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_screens.py
# Purpose : the screens around the game, as Godot scenes over a backdrop: a title screen (logo + menu), a loading
#           screen (drawn spinner, progress bar skin, text) and a credits roll (an AnimationPlayer scrolls the lines).
# Usage   : pack spec "screens": [
#             {"name": "title", "kind": "title", "backdrop": "assets/art/scenes/spr_scene_title_castle.png",
#              "title": "Iron Oven", "menu": ["New Game", "Continue", "Settings", "Quit"]},
#             {"name": "loading", "kind": "loading", "backdrop": "assets/art/scenes/spr_scene_loading_bakery.png",
#              "text": "Loading", "style": "iron"},
#             {"name": "credits", "kind": "credits", "backdrop": "assets/art/scenes/spr_scene_credits_hall.png",
#              "file": "CREDITS.md", "seconds": 40}]
#           backdrop: an image in the game (a scenes lane render is made for this); title: the logo is drawn from a
#           glyph font like the store lane's ("font", "gradient"), or "logo": an existing logo image; credits: "file"
#           (a text or Markdown file in the game, such as the CREDITS.md tools/credits.py writes) or "lines" (a list;
#           "# Heading" lines become headings); style: classic / brass / iron (lane_windows.STYLES).
# Notes   : Scenes go to <art_dir>/screens/<name>/screen_<name>.tscn, sized to the game's viewport (project.godot).
#           When the game has a UI kit theme (<assets_dir>/ui/theme_*.tres, the uikit lane), the screen uses it.
#           The menu buttons only show; what they do is the game's (the kit's shell wires its own menus).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import math
import os
import re

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_widgets import gauge
from lane_windows import STYLES

KINDS = ("title", "loading", "credits")
SPIN_FRAMES = 8
LINE_PX = 24        # credits: the height one line takes at the game's UI scale (the roll only needs an upper bound)


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def viewport(project):
    """(width, height) from project.godot, else 640 x 360."""
    p = os.path.join(project, "project.godot")
    w, h = 640, 360
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            text = f.read()
        mw = re.search(r"^window/size/viewport_width=(\d+)", text, re.M)
        mh = re.search(r"^window/size/viewport_height=(\d+)", text, re.M)
        w, h = int(mw.group(1)) if mw else w, int(mh.group(1)) if mh else h
    return w, h


def spinner(colors, size=16):
    """SPIN_FRAMES RGBA frames: eight dots on a ring, the lit one moving a step clockwise per frame with two
    dimmer dots trailing it. colors: (dark, mid, light) RGB."""
    frames = []
    c = (size - 1) / 2.0
    r = size * 0.36
    for f in range(SPIN_FRAMES):
        a = np.zeros((size, size, 4), np.uint8)
        for d in range(8):
            ang = 2 * math.pi * d / 8 - math.pi / 2
            x, y = int(round(c + r * math.cos(ang))), int(round(c + r * math.sin(ang)))
            lag = (f - d) % 8
            col = colors[2] if lag == 0 else colors[1] if lag in (1, 2) else colors[0]
            a[y - 1:y + 1, x - 1:x + 1] = col + (255,)
        frames.append(a)
    return frames


def credit_lines(e):
    """Credits text as (text, is_heading) pairs from "lines" or a text / Markdown "file" (tables become 'a  b')."""
    if e.get("lines"):
        raw = [str(x) for x in e["lines"]]
    elif e.get("file"):
        with open(core.source_path(e["file"]), encoding="utf-8") as f:
            raw = f.read().splitlines()
    else:
        raise core.ToolError(f"screens {e['name']}: a credits screen needs \"lines\" or \"file\"")
    out = []
    for line in raw:
        s = line.strip()
        if re.match(r"^\|?\s*:?-{3,}", s):            # a Markdown table rule
            continue
        if s.startswith("|"):
            s = "  ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
        head = s.startswith("#")
        s = s.lstrip("#").strip().lstrip("-*").strip()
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s).replace("**", "").replace("`", "")
        out.append((s, head))
    while out and not out[-1][0]:
        out.pop()
    return out


class Scene:
    """A tiny .tscn builder: ext resources, sub resources and nodes in order."""

    def __init__(self):
        self.ext, self.sub, self.nodes = [], [], []

    def tex(self, res_path, kind="Texture2D"):
        rid = f"{len(self.ext) + 1}_r"
        self.ext.append(f'[ext_resource type="{kind}" path="{res_path}" id="{rid}"]')
        return f'ExtResource("{rid}")'

    def node(self, name, typ, parent=None, **props):
        head = f'[node name="{name}" type="{typ}"' + (f' parent="{parent}"' if parent else "") + "]"
        self.nodes.append("\n".join([head] + [f"{k} = {v}" for k, v in props.items()]))

    def text(self):
        return (f"[gd_scene load_steps={len(self.ext) + len(self.sub) + 1} format=3]\n\n" + "\n".join(self.ext)
                + ("\n\n" + "\n\n".join(self.sub) if self.sub else "") + "\n\n" + "\n\n".join(self.nodes) + "\n")


FULL = {"anchors_preset": "15", "anchor_right": "1.0", "anchor_bottom": "1.0", "grow_horizontal": "2",
        "grow_vertical": "2"}


def _root(sc, name, theme_res):
    props = dict(layout_mode="3", **FULL)
    if theme_res:
        props["theme"] = sc.tex(theme_res, "Theme")
    sc.node(name, "Control", **props)
    return sc


def _backdrop(sc, res_path, dim=0.0):
    sc.node("Backdrop", "TextureRect", ".", layout_mode="1", **FULL, texture=sc.tex(res_path),
            expand_mode="1", stretch_mode="6", texture_filter="1")
    if dim:
        sc.node("Dim", "ColorRect", ".", layout_mode="1", **FULL, color=f"Color(0, 0, 0, {dim})",
                mouse_filter="2")


def _label(sc, name, parent, text, align=1, **props):
    sc.node(name, "Label", parent, text=godot.q(text), horizontal_alignment=str(align), **props)


def run(entries, pack, man, conf):
    W, H = viewport(core.PROJECT)
    themes = sorted(glob.glob(os.path.join(core.asset(conf, "ui"), "theme_*.tres")))
    theme_res = ("res://" + os.path.relpath(themes[0], core.PROJECT).replace(os.sep, "/")) if themes else None
    for e in entries:
        name = core.snake(e["name"])
        kind = e.get("kind", name if name in KINDS else "")
        if kind not in KINDS:
            raise core.ToolError(f"screens {name}: \"kind\" must be one of {', '.join(KINDS)}")
        style = e.get("style", "classic")
        if style not in STYLES:
            raise core.ToolError(f"screens {name}: style {style!r} is not one of {', '.join(STYLES)}")
        if not e.get("backdrop"):
            raise core.ToolError(f"screens {name}: needs a \"backdrop\" image (a scenes lane render, or your own)")
        bd = core.source_path(e["backdrop"])
        bd_res = "res://" + os.path.relpath(bd, core.PROJECT).replace(os.sep, "/")
        art = core.art(conf, "screens", name)
        res = core.res(conf, "screens", name)
        man.drop_dir(art)
        sc = _root(Scene(), f"Screen{name.title().replace('_', '')}", theme_res)
        frame = [_hex(c) for c in STYLES[style]["frame"]]
        if kind == "title":
            _backdrop(sc, bd_res)
            if e.get("logo"):
                logo_res = "res://" + os.path.relpath(core.source_path(e["logo"]), core.PROJECT).replace(os.sep, "/")
                lw, lh = Image.open(core.source_path(e["logo"])).size
            else:
                if not e.get("title"):
                    raise core.ToolError(f"screens {name}: a title screen needs \"title\" (or \"logo\": an image)")
                import lane_store
                font = os.path.join(core.HERE, e.get("font", "glyphs/title_brass.txt"))
                logo = lane_store.wordmark(e["title"], font, e.get("gradient", "brass"))
                k = lane_store.logo_scale(logo, W * 0.7, H * 0.3)
                big = np.repeat(np.repeat(logo, k, 0), k, 1)
                p = core.save_clean(Image.fromarray(big), os.path.join(art, f"logo_{name}.png"))
                man.add(p, "screen_logo", scale=k, workflow="Dotwork screens (wordmark from a glyph font)")
                logo_res, (lh, lw) = f"{res}/logo_{name}.png", big.shape[:2]
            sc.node("Logo", "TextureRect", ".", layout_mode="1", anchors_preset="5", anchor_left="0.5",
                    anchor_right="0.5", offset_left=f"{-lw // 2}.0", offset_top=f"{int(H * 0.12)}.0",
                    offset_right=f"{lw - lw // 2}.0", offset_bottom=f"{int(H * 0.12) + lh}.0", grow_horizontal="2",
                    texture=sc.tex(logo_res), texture_filter="1")
            items = e.get("menu", ["New Game", "Continue", "Settings", "Quit"])
            mh = len(items) * 28
            sc.node("Menu", "VBoxContainer", ".", layout_mode="1", anchors_preset="7", anchor_left="0.5",
                    anchor_top="1.0", anchor_right="0.5", anchor_bottom="1.0", offset_left="-80.0",
                    offset_top=f"{-mh - int(H * 0.1)}.0", offset_right="80.0", offset_bottom=f"{-int(H * 0.1)}.0",
                    grow_horizontal="2", grow_vertical="0")
            for i, it in enumerate(items):
                sc.node(f"Item{i}", "Button", "Menu", text=godot.q(it), focus_mode="2")
        elif kind == "loading":
            _backdrop(sc, bd_res, dim=0.35)
            cols = (frame[-1], frame[2], frame[1])
            spin = spinner(cols)
            files = []
            for i, a in enumerate(spin):
                fn = f"spr_spinner_{name}_{i:02d}.png"
                core.save_clean(Image.fromarray(a), os.path.join(art, fn))
                files.append(fn)
            sf = godot.sprite_frames(os.path.join(art, f"spinner_{name}.tres"), res, {"spin": (files, 12.0, True)})
            man.add(sf, "sprite_frames", animations=["spin"], frames=SPIN_FRAMES, workflow="Dotwork screens (drawn)")
            ramp = [STYLES[style]["frame"][i] for i in (1, 2, 3)]
            under, fill, over = gauge(120, 8, STYLES[style]["frame"], ramp)
            for part, a in (("under", under), ("fill", fill), ("over", over)):
                p = core.save_clean(Image.fromarray(np.repeat(np.repeat(a, 2, 0), 2, 1)),
                                    os.path.join(art, f"ui_progress_{name}_{part}.png"))
                man.add(p, "ui_gauge", part=part, scale=2, stretch_margin=4, workflow="Dotwork screens (drawn)")
            sc.node("Spinner", "AnimatedSprite2D", ".", position=f"Vector2({W - 28}, {H - 28})", scale="Vector2(2, 2)",
                    texture_filter="1", sprite_frames=sc.tex(f"{res}/spinner_{name}.tres", "SpriteFrames"),
                    animation='&"spin"', autoplay='"spin"')
            sc.node("Progress", "TextureProgressBar", ".", layout_mode="1", anchors_preset="7", anchor_left="0.5",
                    anchor_top="1.0", anchor_right="0.5", anchor_bottom="1.0", offset_left="-120.0",
                    offset_top=f"{-int(H * 0.18)}.0", offset_right="120.0", offset_bottom=f"{-int(H * 0.18) + 16}.0",
                    grow_horizontal="2", grow_vertical="0", texture_filter="1", value="0.0",
                    nine_patch_stretch="true", stretch_margin_left="4", stretch_margin_top="4",
                    stretch_margin_right="4", stretch_margin_bottom="4",
                    texture_under=sc.tex(f"{res}/ui_progress_{name}_under.png"),
                    texture_over=sc.tex(f"{res}/ui_progress_{name}_over.png"),
                    texture_progress=sc.tex(f"{res}/ui_progress_{name}_fill.png"))
            _label(sc, "Text", ".", e.get("text", "Loading"), layout_mode="1", anchors_preset="7",
                   anchor_left="0.5", anchor_top="1.0", anchor_right="0.5", anchor_bottom="1.0",
                   offset_left="-120.0", offset_top=f"{-int(H * 0.18) - 28}.0", offset_right="120.0",
                   offset_bottom=f"{-int(H * 0.18) - 4}.0", grow_horizontal="2", grow_vertical="0")
        else:
            _backdrop(sc, bd_res, dim=0.55)
            lines = credit_lines(e)
            seconds = float(e.get("seconds", max(10, len(lines) * 1.2)))
            end = -(len(lines) * LINE_PX + 40)
            sc.sub.append("\n".join([
                '[sub_resource type="Animation" id="Animation_roll"]', 'resource_name = "roll"',
                f"length = {seconds}", 'tracks/0/type = "value"', "tracks/0/imported = false",
                "tracks/0/enabled = true", 'tracks/0/path = NodePath("Roll:position:y")', "tracks/0/interp = 1",
                "tracks/0/loop_wrap = true", "tracks/0/keys = {", '"times": PackedFloat32Array(0, %s),' % seconds,
                '"transitions": PackedFloat32Array(1, 1),', '"update": 0,', f'"values": [{H}.0, {end}.0]', "}"]))
            sc.sub.append('[sub_resource type="AnimationLibrary" id="AnimationLibrary_roll"]\n_data = {\n'
                          '&"roll": SubResource("Animation_roll")\n}')
            sc.node("Roll", "VBoxContainer", ".", offset_top=f"{H}.0", offset_right=f"{W}.0",
                    offset_bottom=f"{H + len(lines) * LINE_PX}.0")
            for i, (text, head) in enumerate(lines):
                props = {"theme_type_variation": '&"HeaderSmall"'} if head else {}
                _label(sc, f"Line{i}", "Roll", text, **props)
            sc.node("Player", "AnimationPlayer", ".", libraries='{\n&"": SubResource("AnimationLibrary_roll")\n}',
                    autoplay='&"roll"')
        scn = godot._write(os.path.join(art, f"screen_{name}.tscn"), sc.text())
        man.add(scn, "scene", node="Control", screen=kind, size=[W, H], theme=theme_res,
                workflow="Dotwork screens (Godot scene over a backdrop)")
        core.log(f"screens {name}: {kind} screen {W}x{H}{' with theme ' + theme_res if theme_res else ''}")
