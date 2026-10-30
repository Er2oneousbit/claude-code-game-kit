#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_widgets.py
# Purpose : the rest of a menu and battle HUD, drawn in code in a window-skin style: gauges (HP, MP, ATB, EXP, limit,
#           danger) as under / fill / over textures with a TextureProgressBar scene each, buttons in five states
#           (normal, hover, pressed, disabled, focus) and a panel, all wired into one Godot Theme.
# Usage   : pack spec "widgets": [{"name": "hud", "style": "brass", "gauges": ["hp", "mp", "atb"]}]
#           gauges: kind names, or {"name": "rage", "color": ["ffb080", "f05a30", "a02010"], "ticks": 4}
#           style: classic / brass / iron (lane_windows.STYLES) or "fill" / "frame" hex lists like a window entry;
#           length / height (gauge, 1x px, default 56 x 8), button (1x px, default 16), scale (default 2),
#           buttons / panel false to skip them, font: a .fnt / .ttf path in the game for the Theme's default font.
# Notes   : Godot: apply theme_<name>.tres to a Control (or Project Settings > GUI > Theme > Custom); set the project's
#           default texture filter to Nearest so the 9-slices stay crisp. Gauge scenes are TextureProgressBar with
#           nine-patch stretch, so one texture serves any bar length.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import godot
from lane_windows import STYLES, _rgb, draw

GAUGES = {   # light, base, shade
    "hp": ["8ef07a", "3cc03c", "1e7a2a"],
    "mp": ["8ad0ff", "3a8ae8", "1e4aa0"],
    "atb": ["fff2a0", "f0c830", "a07a10"],
    "exp": ["e0a8ff", "a060e0", "5a2a90"],
    "limit": ["ffb080", "f05a30", "a02010"],
    "danger": ["ff8a8a", "e03a3a", "8a1010"],
}
STATES = ("normal", "hover", "pressed", "disabled", "focus")


def _mix(c, to, t):
    return (np.asarray(c, np.float32) * (1 - t) + np.asarray(to, np.float32) * t).astype(np.uint8)


def _hex(c):
    return "%02x%02x%02x" % tuple(int(v) for v in c)


def gauge(length, height, frame, ramp, ticks=0):
    """(under, fill, over) RGBA arrays at 1x. Frame: an outline ring and a metal ring (corners cut); under: the frame
    around a dark trough with a shadow line; fill: the ramp inside the frame, transparent on it; over: the frame
    only, plus tick marks."""
    L, H = int(length), int(height)
    if H < 5 or L < 8:
        raise core.ToolError(f"gauge {L}x{H}: at least 8 x 5 pixels (two frame rings and a 1 px bar)")
    outline, metal = _rgb(frame[0]).astype(np.uint8), _rgb(frame[2] if len(frame) > 2 else frame[1]).astype(np.uint8)
    over = np.zeros((H, L, 4), np.uint8)
    for k, c in ((0, outline), (1, metal)):
        over[k, k:L - k, :3] = over[H - 1 - k, k:L - k, :3] = c
        over[k:H - k, k, :3] = over[k:H - k, L - 1 - k, :3] = c
        over[k, k:L - k, 3] = over[H - 1 - k, k:L - k, 3] = 255
        over[k:H - k, k, 3] = over[k:H - k, L - 1 - k, 3] = 255
    for y, x in ((0, 0), (0, L - 1), (H - 1, 0), (H - 1, L - 1)):
        over[y, x] = 0
    lo = [_rgb(c).astype(np.uint8) for c in ramp]
    inner = (slice(2, H - 2), slice(2, L - 2))
    fill = np.zeros_like(over)
    fill[inner][..., :3] = lo[1]
    fill[2, 2:L - 2, :3] = lo[0]                      # highlight on the top row of the bar
    if H - 2 - 2 >= 3:
        fill[H - 3, 2:L - 2, :3] = lo[2]              # shade on the bottom row
    fill[inner][..., 3] = 255
    under = over.copy()
    trough = _mix(lo[2], (8, 8, 14), 0.75)
    under[inner][..., :3] = trough
    under[inner][..., 3] = 255
    under[2, 2:L - 2, :3] = _mix(trough, (0, 0, 0), 0.5)   # inner shadow under the frame's top edge
    if ticks:
        for i in range(1, int(ticks)):
            x = 2 + round(i * (L - 4) / int(ticks))
            over[2:H - 2, x, :3] = metal
            over[2:H - 2, x, 3] = 255
    return under, fill, over


def button(fill, frame, state, size=16):
    """One button state at 1x (square 9-slice): the window drawing at button size, then recoloured per state."""
    if state == "focus":   # a bright ring drawn over the button by Godot; the inside stays clear
        a = np.zeros((size, size, 4), np.uint8)
        c = _rgb(frame[1]).astype(np.uint8)
        a[0, 1:-1, :3] = a[-1, 1:-1, :3] = a[1:-1, 0, :3] = a[1:-1, -1, :3] = c
        a[0, 1:-1, 3] = a[-1, 1:-1, 3] = a[1:-1, 0, 3] = a[1:-1, -1, 3] = 255
        return a, 2
    fr = list(frame)
    if state == "pressed" and len(frame) > 2:   # the highlight ring goes dull, as if lit from inside the recess
        fr[1] = frame[2]
    img, m = draw(fill, fr, False, size)
    rgb = img[..., :3].astype(np.float32)
    n = len(frame)
    inside = (slice(n, size - n), slice(n, size - n))   # the fill, inside the frame rings
    if state == "hover":   # only the fill lights up; the frame stays crisp
        rgb[inside] = rgb[inside] * 0.7 + 255 * 0.3
    elif state == "pressed":
        rgb[inside] = rgb[inside] * 0.65
    elif state == "disabled":
        grey = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        rgb = (rgb * 0.25 + grey[..., None] * 0.75) * 0.7
    img[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return img, m


def _scaled(a, s):
    return np.kron(a, np.ones((s, s, 1), np.uint8))


def gauge_scene(path, res, name, scale, length, height):
    m = 2 * scale
    node = "Gauge" + name.title().replace("_", "")
    lines = ['[gd_scene load_steps=4 format=3]', ""]
    for i, part in enumerate(("under", "fill", "over"), 1):
        lines.append(f'[ext_resource type="Texture2D" path="{res}/ui_gauge_{name}_{part}.png" id="{i}_{part}"]')
    lines += ["", f'[node name="{node}" type="TextureProgressBar"]', "texture_filter = 1",
              f"offset_right = {length * scale}.0", f"offset_bottom = {height * scale}.0", "value = 75.0",
              "nine_patch_stretch = true", f"stretch_margin_left = {m}", f"stretch_margin_top = {m}",
              f"stretch_margin_right = {m}", f"stretch_margin_bottom = {m}",
              'texture_under = ExtResource("1_under")', 'texture_over = ExtResource("3_over")',
              'texture_progress = ExtResource("2_fill")', ""]
    return godot._write(path, "\n".join(lines))


def theme(path, res, name, margins, panel_margin, scale, font_res=None):
    """Theme .tres: Button styles per state, Panel / PanelContainer from the panel skin, an optional default font."""
    ext, sub, props = [], [], []
    for st in [s for s in STATES if s in margins] + (["panel"] if panel_margin else []):
        tex = f"ui_panel_{name}.png" if st == "panel" else f"ui_button_{name}_{st}.png"
        ext.append(f'[ext_resource type="Texture2D" path="{res}/{tex}" id="{len(ext) + 1}_{st}"]')
        m = (panel_margin if st == "panel" else margins[st]) * scale
        pad = m + 2 * scale
        top = pad + (scale if st == "pressed" else 0)   # the label sinks one pixel when pressed
        sub.append("\n".join([f'[sub_resource type="StyleBoxTexture" id="StyleBoxTexture_{st}"]',
                              f'texture = ExtResource("{len(ext)}_{st}")',
                              *(f"texture_margin_{side} = {m}.0" for side in ("left", "top", "right", "bottom")),
                              f"content_margin_left = {pad}.0", f"content_margin_top = {top}.0",
                              f"content_margin_right = {pad}.0", f"content_margin_bottom = {pad - (top - pad)}.0", ""]))
        if st == "panel":
            props += ['Panel/styles/panel = SubResource("StyleBoxTexture_panel")',
                      'PanelContainer/styles/panel = SubResource("StyleBoxTexture_panel")']
        else:
            props.append(f'Button/styles/{st} = SubResource("StyleBoxTexture_{st}")')
    if font_res:
        ext.append(f'[ext_resource type="FontFile" path="{font_res}" id="{len(ext) + 1}_font"]')
        props.insert(0, f'default_font = ExtResource("{len(ext)}_font")')
    text = (f'[gd_resource type="Theme" load_steps={len(ext) + len(sub) + 1} format=3]\n\n' + "\n".join(ext) + "\n\n"
            + "\n".join(sub) + "\n[resource]\n" + "\n".join(props) + "\n")
    return godot._write(path, text)


def _review(path, parts, scale):
    """Gauges at 25 / 60 / 100 % above the button states and the panel, on the dark review background."""
    rows = []
    for name, (under, fill, over) in parts["gauges"].items():
        row = []
        for f in (0.25, 0.6, 1.0):
            c = under.copy()
            w = 2 + round((fill.shape[1] - 4) * f)
            m = fill[:, :w, 3] == 255
            c[:, :w][m] = fill[:, :w][m]
            m = over[..., 3] == 255
            c[m] = over[m]
            row.append(c)
        rows.append(row)
    rows.append([parts["buttons"][s] for s in STATES if s in parts["buttons"]] +
                ([parts["panel"]] if parts.get("panel") is not None else []))
    gap = 6
    W = max(sum(a.shape[1] + gap for a in r) for r in rows) + gap
    H = sum(max(a.shape[0] for a in r) + gap for r in rows) + gap
    sheet = Image.new("RGBA", (W, H), (58, 58, 68, 255))
    y = gap
    for r in rows:
        x = gap
        for a in r:
            sheet.alpha_composite(Image.fromarray(a), (x, y))
            x += a.shape[1] + gap
        y += max(a.shape[0] for a in r) + gap
    sheet = sheet.resize((W * scale, H * scale), Image.NEAREST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path)
    return path


def run(entries, pack, man, conf):
    for e in entries:
        name = core.snake(e["name"])
        art = core.art(conf, "ui", "widgets", name)
        res = f'{conf["fixed"]["res_root"]}/{conf["fixed"]["art_dir"]}/ui/widgets/{name}'
        st = dict(STYLES.get(e.get("style", "classic"), STYLES["classic"]))
        st.update({k: e[k] for k in ("fill", "frame") if k in e})
        if e.get("style", "classic") not in STYLES and not ("fill" in e and "frame" in e):
            raise core.ToolError(f"widgets {name}: style {e.get('style')!r} is not one of {', '.join(STYLES)} "
                                 "(or give \"fill\" and \"frame\" hex lists)")
        scale = int(e.get("scale", 2))
        length, height = int(e.get("length", 56)), int(e.get("height", 8))
        man.drop_dir(art)
        parts = {"gauges": {}, "buttons": {}, "panel": None}
        for g in e.get("gauges", ["hp", "mp", "atb"]):
            g = {"name": g} if isinstance(g, str) else dict(g)
            gname = core.snake(g["name"])
            ramp = g.get("color") or GAUGES.get(gname)
            if not ramp or len(ramp) != 3:
                raise core.ToolError(f"widgets {name}: gauge {gname!r} needs \"color\": [light, base, shade] hex "
                                     f"(built in: {', '.join(GAUGES)})")
            under, fill, over = gauge(length, height, st["frame"], ramp, g.get("ticks", 0))
            parts["gauges"][gname] = (under, fill, over)
            for part, a in (("under", under), ("fill", fill), ("over", over)):
                p = core.save_clean(Image.fromarray(_scaled(a, scale)), os.path.join(art, f"ui_gauge_{gname}_{part}.png"))
                man.add(p, "ui_gauge", gauge=gname, part=part, scale=scale, stretch_margin=2 * scale,
                        workflow="Dotwork widgets (drawn in code)")
            scn = gauge_scene(os.path.join(art, f"gauge_{gname}.tscn"), res, gname, scale, length, height)
            man.add(scn, "scene", node="TextureProgressBar", stretch_margin=2 * scale)
        margins = {}
        if e.get("buttons", True):
            for state in STATES:
                a, m = button(st["fill"], st["frame"], state, int(e.get("button", 16)))
                parts["buttons"][state] = a
                margins[state] = m
                p = core.save_clean(Image.fromarray(_scaled(a, scale)), os.path.join(art, f"ui_button_{name}_{state}.png"))
                man.add(p, "ui_button", state=state, scale=scale, patch_margin=m * scale,
                        workflow="Dotwork widgets (drawn in code)")
        pm = 0
        if e.get("panel", True):
            a, pm = draw(st["fill"], st["frame"], st.get("rivets", False), 24)
            parts["panel"] = a
            p = core.save_clean(Image.fromarray(_scaled(a, scale)), os.path.join(art, f"ui_panel_{name}.png"))
            man.add(p, "ui_panel", scale=scale, patch_margin=pm * scale, workflow="Dotwork widgets (drawn in code)")
        font_res = None
        if e.get("font"):
            fp = core.project_path(e["font"])
            if not os.path.isfile(fp):
                raise core.ToolError(f"widgets {name}: font {e['font']!r} not found (make it with the fonts lane first)")
            font_res = "res://" + os.path.relpath(fp, core.PROJECT).replace(os.sep, "/")   # res:// is the game root
        if margins or pm:
            th = theme(os.path.join(art, f"theme_{name}.tres"), res, name, margins, pm, scale, font_res)
            man.add(th, "theme", buttons=sorted(margins), panel=bool(pm), font=font_res,
                    note="apply to a Control or as the project theme; default texture filter Nearest")
        sheet = _review(core.src(conf, "art", "ui", f"widgets_{name}_review.png"), parts, 3)
        core.log(f"widgets {name}: {len(parts['gauges'])} gauges, {len(parts['buttons'])} button states"
                 f"{', panel' if pm else ''}; review {sheet}")
