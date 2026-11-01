#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_store.py
# Purpose : store and platform art: key art (a wide and a tall klein render, or your own pictures), every Steam
#           capsule and library size, a logo wordmark from a glyph font, achievement icons (achieved + greyed), the
#           game icon (.png + multi-size .ico), the Steam app and shortcut icons, and a Godot boot splash.
# Usage   : pack spec "store": [{"name": "iron_oven", "title": "Iron Oven",
#                                "prompt": "a knight in iron armour holding a long loaf like a sword on a castle wall",
#                                "icon": "a round loaf of bread crossed with an iron sword",
#                                "achievements": [{"name": "first_loaf", "source": "assets/art/ui/icons/ui_icon_bread_32.png"}],
#                                "apply": true}]
#           "source" / "tall_source": your own key art (paths in the game) instead of the renders; "icon_source": an
#           existing icon; "subtitle": an official subtitle under the title (the only other text Steam allows);
#           "font" (default glyphs/title_brass.txt, capitals), "gradient" (brass / steel / copper / [hex...]),
#           "focus": [x, y] (0..1, the point of the key art every crop keeps), "bg": hex for icon / splash backing,
#           "logo_anchor": "auto" (default: the calmest spot of each size) or "fixed" (the anchors in SIZES).
# Notes   : Pixel art is only ever scaled by whole numbers: each size takes the smallest whole-number scale of the key
#           art that covers it and crops the rest (never resampled, never padded); the logo gets the largest
#           whole-number scale that fits the size's logo box. Sizes and rules: SIZES below and the README section
#           "Store art (Steam sizes)", checked against the Steamworks pages on 2026-11-01. Store files are not game
#           files: they go to <src_dir>/store/<name>/steam/; the icon, .ico, logo and boot splash ship in
#           <art_dir>/brand/<name>/. "apply": true writes the icon and boot splash into project.godot (Godot only).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os
import re

import numpy as np
from PIL import Image

import fcore as core
import godot
import lane_fonts
from lane_battle_bgs import render_raw

import engine as lib  # noqa: E402

# name: (width, height, logo, logo box as fractions of the size (w, h), logo anchor (x, y) as fractions)
# logo False = no text at all (Steam: the library hero has no words; the page background is ambient art)
SIZES = {
    "header_capsule": (920, 430, True, (0.70, 0.46), (0.5, 0.50)),
    "small_capsule": (462, 174, True, (0.90, 0.78), (0.5, 0.50)),     # Steam: the logo should nearly fill it
    "main_capsule": (1232, 706, True, (0.60, 0.34), (0.5, 0.74)),
    "vertical_capsule": (748, 896, True, (0.84, 0.26), (0.5, 0.20)),
    "page_background": (1438, 810, False, None, None),
    "library_capsule": (600, 900, True, (0.84, 0.24), (0.5, 0.18)),
    "library_header": (920, 430, True, (0.70, 0.46), (0.5, 0.50)),
    "library_hero": (3840, 1240, False, None, None),                  # Steam: no text; keep 860x380 centre safe
}
TALL = ("vertical_capsule", "library_capsule")    # these crop the tall key art, the rest the wide one
# where WIDE_TPL / TALL_TPL put the hero (x0, y0, x1, y1 as fractions of the cropped size); the logo avoids it
SUBJECT = {"wide": (0.30, 0.10, 0.70, 0.75), "tall": (0.15, 0.36, 0.85, 1.0)}
LOGO_CANVAS = (1280, 720)                          # library logo: transparent, logotype only
SAFE = 0.04                                        # a logo keeps this fraction of the size clear on every side
ICO_SIZES = (16, 32, 48, 64, 128, 256)
WIDE_TPL = ("pixel art, {style} {genre} game key art of {s}, the main subject large in the middle of the picture, "
            "open sky across the top quarter, dramatic light, rich detailed pixel art, wide cinematic composition, "
            "no text, no letters, no logo, no border, limited palette")
TALL_TPL = ("pixel art, {style} {genre} game key art of {s}, tall vertical poster composition, the main subject large "
            "in the lower two thirds, open sky across the top third, dramatic light, rich detailed pixel art, "
            "no text, no letters, no logo, no border, limited palette")
ICON_TPL = ("pixel art sprite, pixel art game icon emblem of {s}, single bold centered emblem, simple strong silhouette, "
            "dark outline, plain white background, no text, no letters")


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def cover(art, W, H, focus=(0.5, 0.5)):
    """(k, x0, y0, out): the smallest whole-number scale k of art (h x w x C) that covers W x H, then a W x H crop
    whose window keeps the focus point as central as the edges allow. Every output pixel is one art pixel."""
    h, w = art.shape[:2]
    k = max(-(-W // w), -(-H // h))
    big_w, big_h = w * k, h * k
    x0 = int(round(min(max(focus[0] * big_w - W / 2, 0), big_w - W)))
    y0 = int(round(min(max(focus[1] * big_h - H / 2, 0), big_h - H)))
    ys = (np.arange(H) + y0) // k
    xs = (np.arange(W) + x0) // k
    return k, x0, y0, art[ys][:, xs]


def wordmark(title, font_path, gradient="brass", subtitle=None, sub_font=None):
    """RGBA 1x logo: the title in the glyph font (capitals) with an outline and a vertical gradient, a 1 px drop
    shadow, and an optional subtitle in a smaller plain font centred under it. Refuses characters the font lacks."""
    meta, glyphs = lane_fonts.parse(font_path)
    text = title.upper()
    missing = sorted({c for c in text if c != " " and c not in glyphs})
    if missing:
        raise core.ToolError(f"store: the title font has no {' '.join(missing)} ({os.path.basename(font_path)}); "
                             "pick another \"font\" or change the title")
    line = _line(text, glyphs, meta, "outline", gradient)
    if subtitle:
        smeta, sglyphs = lane_fonts.parse(sub_font)
        miss = sorted({c for c in subtitle if c != " " and c not in sglyphs})
        if miss:
            raise core.ToolError(f"store: the subtitle font has no {' '.join(miss)}")
        sub = _line(subtitle, sglyphs, smeta, "outline", ["f4ead0"])
        W = max(line.shape[1], sub.shape[1])
        out = np.zeros((line.shape[0] + 2 + sub.shape[0], W, 4), np.uint8)
        out[:line.shape[0], (W - line.shape[1]) // 2:][:, :line.shape[1]] = line
        out[line.shape[0] + 2:, (W - sub.shape[1]) // 2:][:, :sub.shape[1]] = sub
        line = out
    # 1 px drop shadow down-right under everything
    h, w = line.shape[:2]
    out = np.zeros((h + 1, w + 1, 4), np.uint8)
    sh = line[..., 3] == 255
    out[1:, 1:][sh] = (10, 8, 14, 255)
    m = line[..., 3] == 255
    out[:h, :w][m] = line[m]
    return out


def _line(text, glyphs, meta, effect, gradient):
    rendered = {c: lane_fonts.render_glyph(glyphs[c], 1, effect, gradient, meta["height"])[0] for c in set(text) if c != " "}
    gh = max(a.shape[0] for a in rendered.values())
    pad = 1 if effect in ("shadow", "outline") else 0
    W = sum((rendered[c].shape[1] - 2 * pad + meta["spacing"]) if c != " " else meta["space"] for c in text) + 2 * pad
    out = np.zeros((gh, W, 4), np.uint8)
    x = 0
    for c in text:
        if c == " ":
            x += meta["space"]
            continue
        a = rendered[c]
        m = a[..., 3] > 0
        out[:a.shape[0], x:x + a.shape[1]][m] = a[m]
        x += a.shape[1] - 2 * pad + meta["spacing"]
    xs = np.nonzero(out[..., 3].any(0))[0]
    return out[:, :xs.max() + 1] if len(xs) else out


def logo_scale(logo, box_w, box_h):
    """Largest whole-number scale that fits the logo in box_w x box_h (at least 1)."""
    return max(1, min(int(box_w // logo.shape[1]), int(box_h // logo.shape[0])))


def place(canvas, logo, k, anchor):
    """Paste logo scaled by k into canvas (RGB(A) array) centred on anchor, kept SAFE clear of every edge.
    Returns the logo's (x0, y0, x1, y1) box."""
    H, W = canvas.shape[:2]
    big = np.repeat(np.repeat(logo, k, 0), k, 1)
    lh, lw = big.shape[:2]
    mx, my = int(np.ceil(W * SAFE)), int(np.ceil(H * SAFE))
    x0 = int(round(min(max(anchor[0] * W - lw / 2, mx), W - mx - lw)))
    y0 = int(round(min(max(anchor[1] * H - lh / 2, my), H - my - lh)))
    m = big[..., 3] == 255
    region = canvas[y0:y0 + lh, x0:x0 + lw]
    region[..., :3][m] = big[..., :3][m]
    if canvas.shape[2] == 4:
        region[..., 3][m] = 255
    return x0, y0, x0 + lw, y0 + lh


ANCHORS = ((0.5, 0.5), (0.5, 0.22), (0.5, 0.78), (0.28, 0.5), (0.72, 0.5), (0.28, 0.25), (0.72, 0.25),
           (0.28, 0.75), (0.72, 0.75))


def calm_anchor(img, size, preferred, subject):
    """The anchor whose logo box covers the least detail (mean colour change between neighbours) and the least of the
    subject box (where the key-art prompt puts the hero: x0, y0, x1, y1 as fractions), so the logo lands on sky,
    wall or ground rather than on the hero. The size's own anchor wins near ties (within 10 %)."""
    H, W = img.shape[:2]
    a = img[..., :3].astype(np.int16)
    edge = np.zeros((H, W), np.float32)
    edge[:, 1:] += np.abs(np.diff(a, axis=1)).sum(2)
    edge[1:, :] += np.abs(np.diff(a, axis=0)).sum(2)
    lw, lh = size
    sx0, sy0, sx1, sy1 = subject[0] * W, subject[1] * H, subject[2] * W, subject[3] * H

    def score(anc):
        x0 = int(min(max(anc[0] * W - lw / 2, 0), W - lw))
        y0 = int(min(max(anc[1] * H - lh / 2, 0), H - lh))
        ox = max(0.0, min(x0 + lw, sx1) - max(x0, sx0))
        oy = max(0.0, min(y0 + lh, sy1) - max(y0, sy0))
        return float(edge[y0:y0 + lh, x0:x0 + lw].mean() + 1.0) * (1 + 3 * ox * oy / float(lw * lh))

    best = min(ANCHORS, key=score)
    return preferred if score(preferred) <= score(best) * 1.1 else best


def compose(wide, tall, logo, focus=(0.5, 0.5), anchor="auto"):
    """{size name: (RGB array, info)} for every SIZES entry plus the transparent library logo. info records the
    art scale k, the crop origin and the logo box so the exam can check whole-number scaling and the safe area.
    anchor "auto" moves each logo to the calmest of ANCHORS; "fixed" keeps the anchors in SIZES."""
    out = {}
    for name, (W, H, has_logo, box, anc) in SIZES.items():
        k, x0, y0, img = cover(tall if name in TALL else wide, W, H, focus)
        img = img[..., :3].copy()
        info = {"k": k, "x0": x0, "y0": y0, "source": "tall" if name in TALL else "wide"}
        if has_logo:
            lk = logo_scale(logo, box[0] * W, box[1] * H)
            at = (calm_anchor(img, (logo.shape[1] * lk, logo.shape[0] * lk), anc, SUBJECT[info["source"]])
                  if anchor == "auto" else anc)
            info["logo_k"] = lk
            info["logo_anchor"] = at
            info["logo_box"] = place(img, logo, lk, at)
        out[name] = (img, info)
    W, H = LOGO_CANVAS
    canvas = np.zeros((H, W, 4), np.uint8)
    lk = logo_scale(logo, W * (1 - 2 * SAFE), H * (1 - 2 * SAFE))
    out["library_logo"] = (canvas, {"logo_k": lk, "logo_box": place(canvas, logo, lk, (0.5, 0.5))})
    return out


def icon_set(icon, bg):
    """From a 64x64 RGBA icon: {size: RGBA} for the .ico frames (16/32/48 drawn small from it, 64 itself, 128/256 by
    whole-number scaling), the 256 px shortcut icon, and the 184 px app icon (x3 = 192, 4 px cropped each side, alpha
    flattened onto bg as Steam does)."""
    from lane_props import derive_small
    if icon.shape[:2] != (64, 64):
        raise core.ToolError(f"store: the icon must be 64x64 (got {icon.shape[1]}x{icon.shape[0]})")
    im = Image.fromarray(icon)
    frames = {}
    for px in ICO_SIZES:
        if px < 64:
            frames[px] = np.array(derive_small(im, px).convert("RGBA"))
        else:
            k = px // 64
            frames[px] = np.repeat(np.repeat(icon, k, 0), k, 1)
    big = np.repeat(np.repeat(icon, 3, 0), 3, 1)[4:188, 4:188]
    app = np.zeros((184, 184, 3), np.uint8)
    app[:] = bg
    m = big[..., 3] == 255
    app[m] = big[..., :3][m]
    return frames, app


def save_ico(frames, path):
    """Multi-size .ico with exactly our frames (Pillow would otherwise resample its own from the largest)."""
    sizes = sorted(frames)
    first = Image.fromarray(frames[sizes[-1]])
    rest = [Image.fromarray(frames[s]) for s in sizes[:-1]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    first.save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=rest)
    return path


def achievement(src, bg, frame):
    """256x256 achieved + greyed icons: the source icon scaled by the largest whole number that fits 224 px, centred
    on a square plate (bg) with a 8 px frame border. Greyed = luma of the achieved icon, darkened a little."""
    a = np.array(src.convert("RGBA"))
    k = max(1, 224 // max(a.shape[:2]))
    big = np.repeat(np.repeat(a, k, 0), k, 1)
    plate = np.zeros((256, 256, 3), np.uint8)
    plate[:] = frame
    plate[8:248, 8:248] = bg
    y0, x0 = (256 - big.shape[0]) // 2, (256 - big.shape[1]) // 2
    m = big[..., 3] == 255
    region = plate[y0:y0 + big.shape[0], x0:x0 + big.shape[1]]
    region[m] = big[..., :3][m]
    luma = (plate.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)) * 0.8
    grey = np.repeat(luma.round().clip(0, 255).astype(np.uint8)[..., None], 3, 2)
    return plate, grey


def splash(logo, bg, W=640, H=360):
    """Boot splash: the logo at the largest whole-number scale that fits 80 % of W x H, centred on bg."""
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = bg
    place(img, logo, logo_scale(logo, W * 0.8, H * 0.8), (0.5, 0.5))
    return img


def apply_project(project_godot, icon_res, splash_res, bg):
    """Set application/config/icon and the boot splash in project.godot, keeping every other line as it was."""
    with open(project_godot, encoding="utf-8") as f:
        text = f.read()
    want = {"config/icon": godot.q(icon_res), "boot_splash/image": godot.q(splash_res),
            "boot_splash/bg_color": "Color(%.4g, %.4g, %.4g, 1)" % tuple(c / 255 for c in bg),
            "boot_splash/use_filter": "false"}
    lines = text.split("\n")
    try:
        start = lines.index("[application]")
    except ValueError:
        lines += ["", "[application]", ""]
        start = len(lines) - 2
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    for key, val in want.items():
        hit = [i for i in range(start + 1, end) if re.match(re.escape(key) + r"\s*=", lines[i])]
        if hit:
            lines[hit[0]] = f"{key}={val}"
        else:
            lines.insert(start + 1, f"{key}={val}")
            end += 1
    with open(project_godot, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return sorted(want)


def _render(name, prompt, seed, work, tpl, w, h, conf):
    t = render_raw(name, prompt, seed, work, tpl=tpl, w=w, h=h)
    return lib.finish(np.dstack([t, np.full(t.shape[:2], 255, np.uint8)]), palette=conf["fixed"]["env_palette"],
                      outline="", max_colors=96)[..., :3]


def _icon(e, name, seed, conf, work):
    if e.get("icon_source"):
        a = np.array(Image.open(core.source_path(e["icon_source"])).convert("RGBA"))
        if a.shape[:2] != (64, 64):
            k = 64 // max(a.shape[:2])
            if k < 1 or 64 % max(a.shape[:2]):
                raise core.ToolError(f"store {name}: icon_source must be 64x64 or a whole fraction of it (16, 32)")
            a = np.repeat(np.repeat(a, k, 0), k, 1)
            pad = np.zeros((64, 64, 4), np.uint8)
            pad[(64 - a.shape[0]) // 2:][:a.shape[0], (64 - a.shape[1]) // 2:][:, :a.shape[1]] = a
            a = pad
        return a
    from lane_props import _ref_once, fit_sprite
    prompt = core.prompt(ICON_TPL, s=e["icon"])
    cp = os.path.join(work, f"{name}_icon_s{seed}_{core.key(prompt, lib.ref_key(conf))}.png")
    if not os.path.exists(cp):   # cached like the key art: a re-run with the same prompt renders nothing
        o = fit_sprite(prompt, seed, f"dotwork/store/{name}_icon", 60, 64, baseline=63, ref_fn=_ref_once(conf, {}),
                       fit="longest", max_colors=24)
        Image.open(o["path"]).convert("RGBA").save(cp)
    return np.array(Image.open(cp).convert("RGBA"))


def _review(parts, path):
    """Every size side by side at a fixed review height (review only: the sheet itself is scaled for viewing)."""
    tiles = []
    for name, a in parts:
        im = Image.fromarray(a)
        h = 180
        w = max(1, round(im.width * h / im.height))
        if im.mode == "RGBA":
            back = Image.new("RGBA", im.size, (90, 90, 100, 255))
            back.alpha_composite(im)
            im = back
        tiles.append(im.convert("RGB").resize((w, h), Image.NEAREST))
    rows = [tiles[i:i + 5] for i in range(0, len(tiles), 5)]
    W = max(sum(t.width + 8 for t in r) + 8 for r in rows)
    sheet = Image.new("RGB", (W, len(rows) * 188 + 8), (40, 40, 48))
    for r, row in enumerate(rows):
        x = 8
        for t in row:
            sheet.paste(t, (x, 8 + r * 188))
            x += t.width + 8
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path)
    return path


def run(entries, pack, man, conf):
    for e in entries:
        name = core.snake(e["name"])
        if not e.get("title"):
            raise core.ToolError(f"store {name}: needs a \"title\" (the game name, the only text Steam allows)")
        if not (e.get("source") or e.get("prompt")):
            raise core.ToolError(f"store {name}: needs a \"prompt\" for the key art (or \"source\": your own picture)")
        if not (e.get("icon_source") or e.get("icon")):
            raise core.ToolError(f"store {name}: needs an \"icon\" prompt (or \"icon_source\": an existing icon)")
        seed = core.seed_of(e, 9100)
        work = core.work("store")
        os.makedirs(work, exist_ok=True)
        steam = core.src(conf, "store", name, "steam")
        brand = core.art(conf, "brand", name)
        bres = core.res(conf, "brand", name)
        bg = _hex(e.get("bg", "1c1a24"))
        frame = _hex(e.get("frame", "6a5a3a"))
        focus = tuple(float(v) for v in e.get("focus", (0.5, 0.5)))
        font = os.path.join(core.HERE, e.get("font", "glyphs/title_brass.txt"))
        if e.get("font") and not os.path.isfile(font):
            font = core.source_path(e["font"])
        sub_font = os.path.join(core.HERE, "glyphs", "dialogue.txt")
        logo = wordmark(e["title"], font, e.get("gradient", "brass"), e.get("subtitle"), sub_font)
        if e.get("source"):
            wide = np.array(Image.open(core.source_path(e["source"])).convert("RGB"))
        else:
            wide = _render(f"{name}_wide", e["prompt"], seed, work, WIDE_TPL, 2560, 1440, conf)
        if e.get("tall_source"):
            tall = np.array(Image.open(core.source_path(e["tall_source"])).convert("RGB"))
        elif e.get("source"):
            tall = wide
        else:
            tall = _render(f"{name}_tall", e.get("tall_prompt", e["prompt"]), seed + 1, work, TALL_TPL, 1440, 2560, conf)
        man.drop_dir(brand)
        parts = compose(wide, tall, logo, focus, e.get("logo_anchor", "auto"))
        review = []
        for size, (img, info) in parts.items():
            p = core.save_clean(Image.fromarray(img), os.path.join(steam, f"{size}.png"))
            man.add(p, "store_art", size=list(img.shape[1::-1]), store="steam", routes=("klein",) if e.get("prompt") else (),
                    **{k: (list(v) if isinstance(v, tuple) else v) for k, v in info.items()},
                    workflow="Dotwork store (whole-number scale + crop, logo from a glyph font)")
            review.append((size, img))
        icon = _icon(e, name, seed + 2, conf, work)
        frames, app = icon_set(icon, bg)
        icon_png = core.save_clean(Image.fromarray(frames[256]), os.path.join(brand, f"icon_{name}.png"))
        man.add(icon_png, "game_icon", size=[256, 256], note="project icon (application/config/icon)")
        ico = save_ico(frames, os.path.join(brand, f"icon_{name}.ico"))
        man.add(ico, "game_icon_ico", sizes=list(ICO_SIZES), note="Windows export icon (export preset application/icon)")
        core.save_clean(Image.fromarray(frames[256]), os.path.join(steam, "shortcut_icon.png"))
        Image.fromarray(app).save(os.path.join(steam, "app_icon.jpg"), quality=95)
        save_ico(frames, os.path.join(steam, "shortcut_icon.ico"))
        review += [("icon", frames[256]), ("app_icon", app)]
        lp = core.save_clean(Image.fromarray(np.repeat(np.repeat(logo, 4, 0), 4, 1)), os.path.join(brand, f"logo_{name}.png"))
        man.add(lp, "logo", scale=4, note="the wordmark at 4x for title screens")
        sp = core.save_clean(Image.fromarray(splash(logo, bg)), os.path.join(brand, f"boot_splash_{name}.png"))
        man.add(sp, "boot_splash", size=[640, 360], note="application/boot_splash/image (use_filter off)")
        for a in e.get("achievements", []):
            an = core.snake(a["name"])
            got, grey = achievement(Image.open(core.source_path(a["source"])), bg, frame)
            core.save_clean(Image.fromarray(got), os.path.join(steam, "achievements", f"{an}.png"))
            core.save_clean(Image.fromarray(grey), os.path.join(steam, "achievements", f"{an}_locked.png"))
            review += [(an, got), (an + "_locked", grey)]
        scn = godot.sprite_scene(os.path.join(brand, f"brand_{name}.tscn"), f"{bres}/boot_splash_{name}.png",
                                 node_name="BootSplash")
        man.add(scn, "scene", node="Sprite2D", note="loads the boot splash so verify proves it imports")
        scn2 = godot.sprite_scene(os.path.join(brand, f"brand_icon_{name}.tscn"), f"{bres}/icon_{name}.png",
                                  node_name="GameIcon")
        man.add(scn2, "scene", node="Sprite2D", note="loads the game icon so verify proves it imports")
        if e.get("apply"):
            pg = os.path.join(core.PROJECT, "project.godot")
            if not os.path.isfile(pg):
                raise core.ToolError(f"store {name}: \"apply\" needs a Godot game (no project.godot here)")
            keys = apply_project(pg, f"{bres}/icon_{name}.png", f"{bres}/boot_splash_{name}.png", bg)
            core.log(f"store {name}: project.godot application/{', application/'.join(keys)} set")
        sheet = _review(review, core.src(conf, "art", "store", f"store_{name}_review.png"))
        core.log(f"store {name}: {len(SIZES) + 1} Steam sizes, icon + .ico, logo, boot splash, "
                 f"{len(e.get('achievements', []))} achievements in {steam}; review {sheet}")
