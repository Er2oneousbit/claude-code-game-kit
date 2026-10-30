#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# lane_img2px.py
# Purpose : any image (concept art, a photo, a render) to true pixel art at a chosen width: box-downscale, exact 8x
#           grid, light klein img2img, grid sample, palette.
# Usage   : pack spec "img2px": [{"name": "tower", "source": "assets_src/concept/tower.png", "width": 96, "denoise":
#           0.3}]
# Notes   : A busy source can lose detail against a plain shrink; both are kept in <src>/art/scenes for comparison.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import os

import numpy as np
from PIL import Image

import fcore as core
import engine as lib  # noqa: E402

PROMPT = ("pixel art sprite, detailed {style} pixel art scene, crisp pixels, clean dark outlines, limited "
          "palette, {setting}")


def run(entries, pack, man, conf):
    art = core.art(conf, "scenes")
    src_dir = core.src(conf, "art", "scenes")
    os.makedirs(src_dir, exist_ok=True)
    for k, e in enumerate(entries):
        name = core.snake(e["name"])
        sp = core.source_path(e["source"])
        seed = core.seed_of(e, 9000)
        pal = conf["fixed"]["env_palette"] if e.get("palette", "env") == "env" else conf["fixed"]["palette"]
        dst = os.path.join(art, f"spr_{name}.png")
        # resume: the source image's content plus every setting that shapes the result
        req = core.key(core.sha256_file(sp)[:12] if os.path.exists(sp) else sp, e.get("box"), e.get("width", 96),
                       (e.get("prompt") or core.prompt(PROMPT)), seed, e.get("denoise", 0.3), core.palette_key(pal),
                       e.get("max_colors", 48))
        if man.current(dst, req):
            core.log(f"img2px {name}: up to date")
            continue
        im = Image.open(sp).convert("RGB")
        if e.get("box"):
            im = im.crop(tuple(e["box"]))
        w = int(e.get("width", 96))
        h = max(1, round(im.height * w / im.width))   # a very wide source rounded to 0 rows and crashed
        small = im.resize((w, h), Image.BOX)
        core.save_clean(im, os.path.join(src_dir, f"{name}_source.png"))
        core.save_clean(small, os.path.join(src_dir, f"{name}_naive.png"))
        cw, ch = (w * 8 + 15) // 16 * 16, (h * 8 + 15) // 16 * 16
        init = Image.new("RGB", (cw, ch), (255, 255, 255))
        init.paste(small.resize((w * 8, h * 8), Image.NEAREST), (0, 0))
        fn = f"dotwork_img2px_{name}.png"
        core.ensure_comfy()
        fn = lib.put(init, fn)
        out, sec = lib.run(lib.klein((e.get("prompt") or core.prompt(PROMPT)), seed, cw, ch, f"dotwork_work/img2px/{name}", init_fn=fn,
                                     denoise=float(e.get("denoise", 0.3))))
        rgb = np.array(Image.open(out).convert("RGB"))
        arr = lib.sample(rgb, np.ones(rgb.shape[:2], bool), 8, 0, 8, 0, 0.5)[:h, :w]
        arr = lib.finish(arr, palette=pal, outline="", max_colors=int(e.get("max_colors", 48)))
        core.save_clean(Image.fromarray(arr).convert("RGB"), dst)
        man.add(dst, "scene", prompt=(e.get("prompt") or core.prompt(PROMPT)), seed=seed, routes=("klein",), request=req,
                workflow="Dotwork img2px (box down, 8x grid, klein img2img, grid sample)", size=[w, h],
                denoise=float(e.get("denoise", 0.3)), source=f"assets_src/art/scenes/{name}_source.png")
        core.log(f"img2px {name}: {w}x{h} in {sec:.0f}s")
