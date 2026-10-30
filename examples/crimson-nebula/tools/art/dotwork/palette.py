#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# palette.py
# Purpose : build a game palette from your own art: `extract` picks N colours from PNGs (weighted k-means in OKLab,
#           snapped to colours that really occur), `extend` keeps a base palette and adds the colours the sources
#           need that it lacks (gap colours further than --gap in OKLab). Writes .hex (one RRGGBB per line) + a swatch.
# Usage   : python dotwork.py palette extract "assets_src/sprites/*.png" --colors 64 --out art_src/dotwork/game.hex
#           python dotwork.py palette extend --base art_src/dotwork/game.hex "art_src/dotwork/materials/*.png" --add 32
#           --out art_src/dotwork/game_env.hex     then point "palette" / "env_palette" at them in dotwork.config.json
# Notes   : A palette is only colours, but build it from art you own: the defaults shipped with Dotwork were made from
#           Dotwork's own material renders (README: Palettes).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import os

import numpy as np
from PIL import Image

import fcore
from engine import load_hex, oklab


def load_colors(patterns):
    """(unique RGB (N, 3) uint8, counts (N,), files) of the opaque pixels of every PNG matching the globs."""
    files = sorted({f for p in patterns for f in glob.glob(p)})
    if not files:
        raise fcore.ToolError(f"no PNG files match {', '.join(patterns)}")
    px = []
    for f in files:
        a = np.asarray(Image.open(f).convert("RGBA")).reshape(-1, 4)
        px.append(a[a[:, 3] >= 128, :3])
    uniq, counts = np.unique(np.concatenate(px), axis=0, return_counts=True)
    return uniq, counts, files


def weighted_kmeans(x, w, k, iters=60, seed=1234):
    """Weighted k-means with k-means++ seeding. x (N, D), w (N,)."""
    rng = np.random.default_rng(seed)
    k = min(k, len(x))
    w = w.astype(np.float64)
    centers = [x[rng.choice(len(x), p=w / w.sum())]]
    for _ in range(1, k):
        d = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        p = d * w
        centers.append(x[rng.choice(len(x), p=p / p.sum())] if p.sum() > 0 else x[rng.integers(len(x))])
    c = np.array(centers)
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([np.average(x[lab == i], axis=0, weights=w[lab == i]) if np.any(lab == i) else c[i]
                        for i in range(k)])
        if np.allclose(new, c, atol=1e-6):
            break
        c = new
    return c


def _snap(uniq, lab, centers):
    idx = np.argmin(((lab[:, None, :] - centers[None]) ** 2).sum(-1), axis=0)
    return np.unique(uniq[idx], axis=0)


def mean_error(uniq, counts, pal):
    d = np.sqrt(np.min(((oklab(uniq)[:, None, :] - oklab(pal)[None]) ** 2).sum(-1), axis=1))
    return float(np.average(d, weights=counts))


def extract(patterns, k):
    uniq, counts, files = load_colors(patterns)
    lab = oklab(uniq)
    pal = _snap(uniq, lab, weighted_kmeans(lab, counts, k))
    return pal[np.argsort(oklab(pal)[:, 0])], mean_error(uniq, counts, pal), len(files)


def extend(base, patterns, add, gap=0.04):
    uniq, counts, files = load_colors(patterns)
    lab, blab = oklab(uniq), oklab(base)
    dist = np.sqrt(np.min(((lab[:, None, :] - blab[None]) ** 2).sum(-1), axis=1))
    far = dist > gap
    if far.sum() < add:
        raise fcore.ToolError(f"only {int(far.sum())} source colours are further than {gap} from the base; lower --gap "
                              "or --add")
    added = _snap(uniq[far], lab[far], weighted_kmeans(lab[far], counts[far], add))
    pal = np.unique(np.concatenate([base, added]), axis=0)
    pal = pal[np.argsort(oklab(pal)[:, 0])]
    return pal, mean_error(uniq, counts, base), mean_error(uniq, counts, pal), len(files), len(added)


def write(pal, out):
    fcore.write_text(out, "\n".join("%02x%02x%02x" % tuple(int(v) for v in c) for c in pal) + "\n")
    n, cols = len(pal), 16
    sw = Image.new("RGB", (cols * 12, ((n + cols - 1) // cols) * 12), (0, 0, 0))
    for i, c in enumerate(pal):
        sw.paste(tuple(int(v) for v in c), ((i % cols) * 12, (i // cols) * 12, (i % cols) * 12 + 12, (i // cols) * 12 + 12))
    sw.save(os.path.splitext(out)[0] + "_swatch.png")
    return out


def cmd(args):
    if args.action == "extract":
        pal, err, nf = extract(args.sources, args.colors)
        write(pal, args.out)
        print(f"[ OK ] {len(pal)} colours from {nf} files -> {args.out} (mean OKLab error {err:.4f})")
    else:
        base = load_hex(args.base)
        pal, before, after, nf, na = extend(base, args.sources, args.add, args.gap)
        write(pal, args.out)
        print(f"[ OK ] {len(base)} base + {na} added = {len(pal)} colours -> {args.out}; mean OKLab error on {nf} "
              f"files {before:.4f} -> {after:.4f}")
    return 0
