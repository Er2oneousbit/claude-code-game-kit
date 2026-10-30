#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# engine.py
# Purpose : Dotwork's pixel engine and ComfyUI connection. The proven sprite lane (FLUX.2 klein + a pixel-art LoRA:
#           txt2img -> key the background -> shrink onto an exact 8 px grid -> klein img2img refine -> sample one
#           colour per cell -> OKLab palette lock -> colour cap -> 1 px outline), grid sampling for textures, and the
#           numpy image helpers every lane shares (connected components, erosion, keying, contact sheets).
# Usage   : imported by the lanes (not run directly)
# Notes   : ComfyUI over HTTP only, through the kit's comfy_local.py helpers (local-only by default): images go up
#           with /upload/image, results come back with /history + /view and are mirrored into
#           <work>/comfy_out/<subfolder>/<file> (PNG text chunks stripped), so lane code reads plain files.
#           Dependencies: Pillow + numpy only (connected components are a run-length union-find, not scipy).
#           Style reference: the user's own sprites from config "style_refs" (a collage), or none.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import fnmatch
import json
import os
import sys
import time
import urllib.parse

import numpy as np
from PIL import Image, ImageDraw

import fcore

sys.path.insert(0, os.path.dirname(fcore.HERE))   # tools/art: the kit's comfy_local.py sits next to dotwork/
try:
    import comfy_local as cl  # noqa: E402
except ImportError:  # pragma: no cover - Dotwork outside the kit
    cl = None

KLEIN_VAE = "flux2-vae-klein.safetensors"   # Apache-2.0 klein VAE (README: models); the flux2-dev VAE is non-commercial
KLEIN_UNET = "flux-2-klein-4b.safetensors"
KLEIN_CLIP = "qwen_3_4b.safetensors"
PIXEL_LORA = "spritekiln_klein_pixel_art.safetensors"
WHITE_BG = "plain solid white background, no ground shadow"
N4 = ((-1, 0), (1, 0), (0, -1), (0, 1))
N8 = N4 + ((-1, -1), (-1, 1), (1, -1), (1, 1))
_CONF = None


def bind(conf):
    """Remember the run's settings (server URL, style refs, palettes)."""
    global _CONF
    _CONF = conf


def comfy_out(*parts):
    return os.path.join(fcore.WORK, "comfy_out", *parts)


# ---- ComfyUI over HTTP -------------------------------------------------------------
class _Args:
    def __init__(self, url, allow_remote):
        self.url, self.allow_remote = url, allow_remote


def base_url():
    if cl is None:
        raise fcore.ToolError("comfy_local.py not found next to dotwork/ (Dotwork runs from the kit's tools/art/ folder)")
    c = _CONF["comfyui"]
    try:
        # refuse a non-loopback URL before any request goes to it (ensure_comfy probes the URL first)
        cl.server_url(_Args(c.get("url"), bool(c.get("allow_remote"))))
        return cl.server_url(_Args(fcore.ensure_comfy(_CONF), bool(c.get("allow_remote"))))
    except cl.ToolError as exc:
        raise fcore.ToolError(str(exc))


def put(img, name):
    """Upload a PIL image (or PNG path) to ComfyUI's input; returns the name a LoadImage node should use."""
    base = base_url()
    path = fcore.work("uploads", name)
    (Image.open(img) if isinstance(img, str) else img).save(path)
    with open(path, "rb") as f:
        body, ctype = cl.multipart("image", name, f.read(), {"overwrite": "true", "type": "input"})
    status, data = cl.http("POST", base + "/upload/image", body, {"Content-Type": ctype})
    if status != 200:
        raise fcore.ToolError(f"upload of {name} failed: HTTP {status} {data[:200].decode('utf-8', 'replace')}")
    info = json.loads(data.decode("utf-8"))
    return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]


def run_job(graph, timeout=1800):
    """Queue an API graph, wait, mirror every output image into <work>/comfy_out/<subfolder>/<file>.
    Returns {"files": [local paths], "seconds": GPU seconds}."""
    base = base_url()
    try:
        pid = cl.queue(base, graph)
        entry, seconds = cl.wait_history(base, pid, timeout)
    except cl.ToolError as exc:
        raise fcore.ToolError(str(exc))
    except cl.JobError as exc:
        raise fcore.JobError(str(exc))
    files = []
    for item in cl.output_files(entry, include_temp=False):
        q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                    "type": item.get("type", "output")})
        status, data = cl.http("GET", f"{base}/view?{q}")
        if status != 200:
            raise fcore.JobError(f"could not fetch {item['filename']} (HTTP {status})")
        if item["filename"].lower().endswith(".png"):
            data = cl.strip_png(data)
        sub = [p for p in item.get("subfolder", "").replace("\\", "/").split("/") if p and p != ".."]
        path = comfy_out(*sub, cl.safe_name(item["filename"]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        files.append(path)
    if not files:
        raise fcore.JobError("the ComfyUI job finished but saved no images")
    return {"files": sorted(files), "seconds": seconds}


def job_files(r, pattern):
    """This job's files whose name matches pattern ("r_*.png"), sorted. Never glob the comfy_out mirror instead:
    ComfyUI's file counter keeps climbing (r_00001_ from an earlier design sits next to r_00002_), so a glob hands
    back the old renders first."""
    return sorted(p for p in r["files"] if fnmatch.fnmatch(os.path.basename(p), pattern))


def run(graph, timeout=1800):
    """(first output path, seconds) - the single-image form most lanes use."""
    r = run_job(graph, timeout)
    return r["files"][0], r["seconds"]


def free_models():
    """Ask ComfyUI to unload models (back-to-back Wan clips otherwise pile up in system RAM)."""
    try:
        base = base_url()
        cl.http("POST", base + "/free", json.dumps({"unload_models": True, "free_memory": True}).encode(),
                {"Content-Type": "application/json"})
        time.sleep(2)
    except Exception as exc:  # noqa: BLE001
        fcore.log(f"[warn] /free failed: {exc}")


def missing_nodes(graph):
    base = base_url()
    info = cl.get_json(base, "/object_info")
    return cl.missing_nodes(graph, info)


# ---- graphs ------------------------------------------------------------------------
class G:
    def __init__(self):
        self.nodes, self.n = {}, 0

    def add(self, cls, **inp):
        self.n += 1
        self.nodes[str(self.n)] = {"class_type": cls, "inputs": {k: ([v[0], v[1]] if isinstance(v, tuple) else v)
                                                                 for k, v in inp.items()}}
        return str(self.n)


def klein(prompt, seed, w, h, prefix, ref_fn=None, init_fn=None, denoise=1.0, lora=0.8, steps=None, ref2_fn=None,
          mask_fn=None):
    """FLUX.2 klein 4B + pixel LoRA. txt2img, or img2img with init_fn; ref_fn = uploaded style reference;
    mask_fn (with init_fn): white = repaint, black = keep."""
    g = G()
    unet = g.add("UNETLoader", unet_name=KLEIN_UNET, weight_dtype="default")
    lo = g.add("LoraLoaderModelOnly", model=(unet, 0), lora_name=PIXEL_LORA, strength_model=lora)
    clip = g.add("CLIPLoader", clip_name=KLEIN_CLIP, type="flux2", device="default")
    vae = g.add("VAELoader", vae_name=KLEIN_VAE)
    pos = g.add("CLIPTextEncode", text=prompt, clip=(clip, 0))
    neg = g.add("ConditioningZeroOut", conditioning=(pos, 0))
    for r in (ref_fn, ref2_fn):
        if r:
            li = g.add("LoadImage", image=r)
            sc = g.add("ImageScaleToTotalPixels", image=(li, 0), upscale_method="nearest-exact", megapixels=1.0,
                       resolution_steps=16)
            enc = g.add("VAEEncode", pixels=(sc, 0), vae=(vae, 0))
            pos = g.add("ReferenceLatent", conditioning=(pos, 0), latent=(enc, 0))
            neg = g.add("ReferenceLatent", conditioning=(neg, 0), latent=(enc, 0))
    if init_fn:
        init = g.add("LoadImage", image=init_fn)
        lat = g.add("VAEEncode", pixels=(init, 0), vae=(vae, 0))
        if mask_fn:
            mk = g.add("LoadImageMask", image=mask_fn, channel="red")
            lat = g.add("SetLatentNoiseMask", samples=(lat, 0), mask=(mk, 0))
        sig = g.add("Flux2Scheduler", steps=steps or 8, width=w, height=h)
        sig = g.add("SplitSigmasDenoise", sigmas=(sig, 0), denoise=denoise)
        sig_out = (sig, 1)
    else:
        lat = g.add("EmptyFlux2LatentImage", width=w, height=h, batch_size=1)
        sig = g.add("Flux2Scheduler", steps=steps or 4, width=w, height=h)
        sig_out = (sig, 0)
    noise = g.add("RandomNoise", noise_seed=seed)
    guide = g.add("CFGGuider", model=(lo, 0), positive=(pos, 0), negative=(neg, 0), cfg=1.0)
    samp = g.add("KSamplerSelect", sampler_name="euler")
    out = g.add("SamplerCustomAdvanced", noise=(noise, 0), guider=(guide, 0), sampler=(samp, 0), sigmas=sig_out,
                latent_image=(lat, 0))
    dec = g.add("VAEDecode", samples=(out, 0), vae=(vae, 0))
    g.add("SaveImage", images=(dec, 0), filename_prefix=prefix)
    return g.nodes


# ---- numpy image helpers ------------------------------------------------------------
def label(mask, conn=4):
    """Connected components of a bool mask (4- or 8-connected). Returns (labels int32, count); 0 = background.
    Run-length union-find: fast enough for 1024 px renders without scipy."""
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    parent = [0]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    prev = []
    for y in range(H):
        d = np.diff(np.concatenate(([0], mask[y].astype(np.int8), [0])))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        cur, j = [], 0
        for s, e in zip(starts.tolist(), ends.tolist()):
            lid = len(parent)
            parent.append(lid)
            lo, hi = (s, e) if conn == 4 else (s - 1, e + 1)
            while j < len(prev) and prev[j][1] <= lo:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < hi:
                a, b = find(lid), find(prev[k][2])
                if a != b:
                    parent[max(a, b)] = min(a, b)
                k += 1
            cur.append((s, e, lid))
            lab[y, s:e] = lid
        prev = cur
    roots = np.array([find(i) for i in range(len(parent))], np.int32)
    _, compact = np.unique(roots, return_inverse=True)
    return compact.astype(np.int32)[lab], int(compact.max())


def shift(m, dy, dx, fill=False):
    out = np.full_like(m, fill)
    H, W = m.shape[:2]
    out[max(0, dy):H + min(0, dy), max(0, dx):W + min(0, dx)] = m[max(0, -dy):H + min(0, -dy), max(0, -dx):W + min(0, -dx)]
    return out


def erode(m, conn=4):
    out = m.copy()
    for dy, dx in (N4 if conn == 4 else N8):
        out &= shift(m, dy, dx, False)
    return out


def dilate(m, conn=4):
    out = m.copy()
    for dy, dx in (N4 if conn == 4 else N8):
        out |= shift(m, dy, dx, False)
    return out


def border_flood(near):
    """True where `near` is connected to the image border (the plain background)."""
    lab, _ = label(near, 4)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    return np.isin(lab, border[border > 0])


def key_bg(rgb, bg="white", tol=0.06):
    """Figure alpha: flood the plain background in from the borders (white details inside the figure survive)."""
    if bg == "white":
        near = rgb.astype(np.int32).min(axis=2) >= 255 * (1 - tol)
    else:
        near = rgb.astype(np.int32).max(axis=2) <= 255 * tol * 1.5
    return ~border_flood(near)


def sample(rgb, alpha, px, phx, py, phy, inner=0.5):
    """One pixel per grid cell: median colour of the cell's inner area, opaque when mostly figure."""
    H, W = alpha.shape
    # a partial leading cell exists only when the grid phase is past 0; at phase 0 the cell before it lies wholly
    # off the image and used to duplicate column/row 0, shifting every cropped texture by 1 px (2026-10-30 audit)
    xs = np.arange(phx - px if phx > 0 else 0, W, px)
    ys = np.arange(phy - py if phy > 0 else 0, H, py)
    out = np.zeros((len(ys), len(xs), 4), np.uint8)
    for j, y0 in enumerate(ys):
        for i, x0 in enumerate(xs):
            xa = max(0, int(round(x0 + px * (1 - inner) / 2)))
            xb = min(W, max(int(round(x0 + px * (1 + inner) / 2)), xa + 1))
            ya = max(0, int(round(y0 + py * (1 - inner) / 2)))
            yb = min(H, max(int(round(y0 + py * (1 + inner) / 2)), ya + 1))
            if xa >= xb or ya >= yb:
                continue
            a = alpha[ya:yb, xa:xb]
            if a.mean() < 0.5:
                continue
            out[j, i, :3] = np.median(rgb[ya:yb, xa:xb][a], axis=0)
            out[j, i, 3] = 255
    return out


def sample_mode(rgb, alpha, cell):
    """Dominant colour per cell (5-bit vote), then the median of the winning pixels."""
    H, W = alpha.shape
    out = np.zeros((H // cell, W // cell, 4), np.uint8)
    q = (rgb >> 3).astype(np.int32)
    key = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    for j in range(H // cell):
        for i in range(W // cell):
            sl = (slice(j * cell + 1, j * cell + cell - 1), slice(i * cell + 1, i * cell + cell - 1))
            if alpha[sl].mean() < 0.5:
                continue
            k = key[sl][alpha[sl]]
            v, c = np.unique(k, return_counts=True)
            m = (key[sl] == v[c.argmax()]) & alpha[sl]
            out[j, i, :3] = np.median(rgb[sl][m], axis=0)
            out[j, i, 3] = 255
    return out


def hard_alpha(a):
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    return a


def drop_islands(a, min_px=4):
    op = a[..., 3] == 255
    lab, n = label(op, 8)
    if n > 1:
        sizes = np.bincount(lab.ravel())
        a[np.isin(lab, np.where(sizes < min_px)[0]) & op, 3] = 0
    return a


def defringe(a, min_channel=190, passes=3):
    """Peel near-white halo pixels off the silhouette edge (white keying leftovers)."""
    for _ in range(passes):
        opq = a[..., 3] == 255
        fr = opq & ~erode(opq) & (a[..., :3].min(axis=2) >= min_channel)
        if not fr.any():
            break
        a[fr, 3] = 0
    return a


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.uint8)


def outline(a, color):
    op = a[..., 3] == 255
    a[op & ~erode(op), :3] = color
    return a


def load_hex(path):
    with open(path, encoding="utf-8") as f:
        cols = [l.strip().lstrip("#") for l in f if len(l.strip().lstrip("#")) == 6]
    if not cols:
        raise fcore.ToolError(f"palette {path} has no colours (one RRGGBB per line)")
    return np.array([[int(h[i:i + 2], 16) for i in (0, 2, 4)] for h in cols], np.uint8)


def oklab(rgb):
    c = rgb.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def quantize(a, pal):
    """Snap opaque pixels to the nearest palette colour in OKLab."""
    out = a.copy()
    flat = out.reshape(-1, 4)
    m = flat[:, 3] >= 128
    if m.any():
        lab, pl = oklab(flat[m, :3]), oklab(pal)
        flat[m, :3] = pal[np.argmin(((lab[:, None, :] - pl[None]) ** 2).sum(-1), axis=1)]
    return out


def cap_colors(a, n):
    op = a[..., 3] == 255
    cols, cnt = np.unique(a[op][:, :3], axis=0, return_counts=True)
    if len(cols) <= n:
        return a
    return quantize(a, cols[np.argsort(cnt)[::-1][:n]])


def kmeans_palette(a, k, iters=12, seed=0):
    op = a[..., 3] == 255
    px = a[op][:, :3].astype(np.float32)
    if len(np.unique(px, axis=0)) <= k:
        return a
    cent = px[np.random.default_rng(seed).choice(len(px), k, replace=False)]
    for _ in range(iters):
        lab = ((px[:, None] - cent[None]) ** 2).sum(2).argmin(1)
        for c in range(k):
            if (lab == c).any():
                cent[c] = px[lab == c].mean(0)
    out = a.copy()
    out[op, :3] = cent[((px[:, None] - cent[None]) ** 2).sum(2).argmin(1)].round().astype(np.uint8)
    return out


def finish(arr, palette=None, colors=0, outline_hex="#050407", max_colors=40, **kw):
    """Palette lock (shared game palette) + per-sprite colour cap, or per-sprite k-means; then 1 px outline."""
    outline_hex = kw.get("outline", outline_hex)
    if palette:
        arr = quantize(arr, load_hex(palette))
        arr[..., 3] = np.where(arr[..., 3] >= 128, 255, 0)
        if max_colors:
            arr = cap_colors(arr, max_colors)
    elif colors:
        arr = kmeans_palette(arr, colors)
    if outline_hex:
        arr = outline(arr, hexrgb(outline_hex))
    return arr


def to_canvas(arr, canvas, baseline=None):
    """Crop to content, centre, feet on the baseline. Never resamples; too big = JobError (callers retry)."""
    im = Image.fromarray(arr)
    bb = im.getbbox()
    if not bb:
        return im
    im = im.crop(bb)
    if im.width > canvas or im.height > canvas:
        return im
    can = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    base = baseline or canvas - 3
    can.alpha_composite(im, ((canvas - im.width) // 2, max(0, min(canvas - im.height, base - im.height))))
    return can


# ---- sprite lane ---------------------------------------------------------------------
def shrink(raw_path, fig, cells=126, fit="height", tol=0.06, bg="white"):
    """Key, crop, BOX-resize the figure (height, longest side, or a (w, h) box) onto a plain cells^2 canvas;
    returns (init image at 8x, small RGBA)."""
    rgb = np.array(Image.open(raw_path).convert("RGB"))
    alpha = key_bg(rgb, bg, tol)
    ys, xs = np.nonzero(alpha)
    if not len(ys):
        raise fcore.JobError(f"{os.path.basename(raw_path)}: nothing but background in the render")
    im = Image.fromarray(np.dstack([rgb, alpha.astype(np.uint8) * 255]))
    im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    if isinstance(fit, (tuple, list)):
        s = min(fit[0] / im.width, fit[1] / im.height)
    else:
        s = fig / (im.height if fit == "height" else max(im.size))
    small = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BOX)
    # a figure bigger than the canvas (a 192 px boss on 126 cells) was cut off at the edges: grow the canvas instead,
    # keeping 8 render px per pixel; an even cell count keeps the render a multiple of 16 (2026-10-30)
    cells = max(cells, max(small.size) + 6)
    cells += cells % 2
    fill = (255, 255, 255, 255) if bg == "white" else (0, 0, 0, 255)
    can = Image.new("RGBA", (cells, cells), fill)
    can.alpha_composite(small, ((cells - small.width) // 2, (cells - small.height) // 2))
    return can.convert("RGB").resize((cells * 8, cells * 8), Image.NEAREST), small


def sample8(path, mode="dominant", bg="white"):
    rgb = np.array(Image.open(path).convert("RGB"))
    alpha = key_bg(rgb, bg, 0.06)
    a = sample(rgb, alpha, 8, 0, 8, 0, 0.5) if mode == "median" else sample_mode(rgb, alpha, 8)
    a = hard_alpha(a)
    if bg == "white":
        a = defringe(a)
    return drop_islands(a, 4)


def sprite(prompt, seed, tag, fig=66, canvas=72, baseline=69, ref_fn=None, denoise=0.45, fit="height",
           mode="dominant", palette=None, colors=0, outline="#050407", bg="white", max_colors=40):
    """txt2img 1008 -> shrink onto the 8 px grid -> klein refine -> sample -> palette -> outline -> canvas.
    The refine runs at the init's size: 1008 for figures up to ~120 px, larger for bosses (1584 for a 192 px one)."""
    work = fcore.work("sprites", tag.replace("/", "_"))
    full = f"{prompt}, {WHITE_BG if bg == 'white' else 'plain solid black background'}"
    t0 = time.time()
    raw, _ = run(klein(full, seed, 1008, 1008, f"dotwork_work/sprites/{tag}/raw_s{seed}", ref_fn=ref_fn))
    init, _ = shrink(raw, fig, fit=fit, bg=bg)
    init_name = put(init, f"dotwork_init_{tag.replace('/', '_')}_s{seed}.png")
    ref_out, _ = run(klein(full, seed + 1000, init.width, init.height, f"dotwork_work/sprites/{tag}/refine_s{seed}",
                           ref_fn=ref_fn, init_fn=init_name, denoise=denoise))
    arr = sample8(ref_out, mode, bg)
    arr = finish(arr, palette, colors, outline, max_colors)
    out = to_canvas(arr, canvas, baseline)
    path = os.path.join(work, f"s{seed}.png")
    os.makedirs(work, exist_ok=True)
    out.save(path)
    return {"path": path, "raw": raw, "refine": ref_out, "seconds": round(time.time() - t0, 1)}


# ---- style reference -------------------------------------------------------------------
def ref_key(conf):
    """Cache-key part for the style reference a lane would use, without uploading it (works offline): "none", or a
    key over the configured style_refs. A spec's "design": {"character": {"style_ref": ""}} switches it off."""
    refs = conf.get("style_refs") or []
    if not refs or conf["design"]["character"].get("style_ref", "cast") == "":
        return "none"
    return fcore.sha256_text("|".join(refs))[:10]


def ref(name=None):
    """The user's own style sprites (config "style_refs") as one collage, uploaded once per run; None without refs
    (the portable default: no third-party art ships with Dotwork). `name` is kept for older lane calls."""
    refs = (_CONF or {}).get("style_refs") or []
    if not refs or name == "":
        return None
    key = "dotwork_style_" + fcore.sha256_text("|".join(refs))[:10] + ".png"
    if getattr(ref, "_cache", {}).get(key):
        return ref._cache[key]
    tiles = []
    for p in refs:
        path = p if os.path.isabs(p) else os.path.join(fcore.PROJECT, p)
        if not os.path.exists(path):
            raise fcore.ToolError(f"style_refs: {path} not found")
        tiles.append(Image.open(path).convert("RGBA"))
    w, h = max(t.width for t in tiles), max(t.height for t in tiles)
    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    col = Image.new("RGBA", (w * cols, h * rows), (0, 0, 0, 0))
    for k, t in enumerate(tiles):
        col.alpha_composite(t, ((k % cols) * w, (k // cols) * h))
    scale = 8 if len(tiles) == 1 else 4
    big = col.resize((col.width * scale, col.height * scale), Image.NEAREST)
    bgim = Image.new("RGBA", big.size, (255, 255, 255, 255))
    bgim.alpha_composite(big)
    name_up = put(bgim.convert("RGB"), key)
    ref._cache = {key: name_up}
    return name_up


# ---- review sheets ----------------------------------------------------------------------
def sheet(rows, out, scale=3, cell=None, labels=True, bg=(58, 58, 68)):
    """rows: [(label, [paths])] -> nearest-scaled contact sheet PNG."""
    ims = [[Image.open(p).convert("RGBA") if p and os.path.exists(p) else None for p in ps] for _, ps in rows]
    cw = cell or max((i.width for r in ims for i in r if i), default=72) * scale
    ch = max((i.height for r in ims for i in r if i), default=72) * scale
    lw = 120 if labels else 0
    ncol = max([len(r) for r in ims] + [1])
    s = Image.new("RGBA", (lw + ncol * (cw + 4), max(1, len(rows)) * (ch + 4)), bg + (255,))
    d = ImageDraw.Draw(s)
    for r, ((lab, _), row) in enumerate(zip(rows, ims)):
        y = r * (ch + 4)
        if labels:
            d.text((4, y + ch // 2 - 6), lab[:18], fill=(240, 220, 160))
        for c, im in enumerate(row):
            if im is None:
                continue
            k = max(1, min(cw // im.width, ch // im.height))
            big = im.resize((im.width * k, im.height * k), Image.NEAREST)
            s.alpha_composite(big, (lw + c * (cw + 4) + (cw - big.width) // 2, y + (ch - big.height) // 2))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    s.save(out)
    return out
