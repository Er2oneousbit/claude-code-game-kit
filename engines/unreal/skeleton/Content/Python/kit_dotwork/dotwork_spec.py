# ---------------------------------------------------------------------------
# dotwork_spec.py
# Purpose : The engine-neutral rules of a Dotwork asset manifest (tools/art/dotwork/ASSET_MANIFEST.md, spec 1.x) that
#           the Unreal importer needs, in plain Python (no `import unreal`): reading and version-checking a manifest,
#           resolving its paths, the terrain rules for map layers (cell_mask for blob47, sides4 and corners4, the
#           tile key, the variant pick by cell_roll), stamps layers expanded into tiles, where a cell's image lands
#           (cell_centre, tile_origin, draw_corner), a flipbook frame rate at which every frame's duration is a whole
#           number of frames, and comparing a loaded result with expected.json.
# Usage   : from kit_dotwork import dotwork_spec   (dotwork_paper.py and the tests import it)
# Notes   : A port of tools/art/dotwork/assetspec.py (canon, cell_mask, tile_key, hash32, cell_roll, pick_variant,
#           cell_centre, tile_origin, resolve_terrain, expand_stamps, placed_cells, draw_corner): keep the names and
#           signatures in step; scripts/test_unreal_dotwork.py in the kit compares them on the golden pack.
#           Pseudocode (resolve_terrain)
#             candidates by key: every tile of the layer's terrain, in atlas order, keyed by tile_key (its mask, or
#               the corner bits of its own terrain), with its probability (default 1)
#             per painted cell (y then x): key = cell_mask(painted, x, y, mode); tile = pick_variant(candidates[key],
#               cell_roll(x, y, layer_index)); None when no tile has the key
#           Pseudocode (flipbook_rate)
#             base = the clip's fps; for k = 1, 2, ... up to RATE_STEPS: rate = base * k
#               every duration * rate within RATE_TOLERANCE of a whole number (and at least 1): use it
#             none fits (durations that are no fraction of the fps): FALLBACK_RATE frames per second, rounded runs
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): corners4 keys, the variant
#           pick (hash32, cell_roll, pick_variant), stamps layers, cell centres and draw corners; particles are an
#           extra kind the importer loads
# ---------------------------------------------------------------------------
import json
import os

# ---- Tunables ------------------------------------------------------------------
FORMAT = "dotwork-assets"
MAJOR = 1                                   # the spec major this importer reads (ASSET_MANIFEST.md "Versioning")
RATE_STEPS = 60                             # try the clip's fps times 1..60 for a rate with whole frame runs
RATE_TOLERANCE = 1e-6                       # how close duration * rate must be to a whole number
MAX_RATE = 1000.0                           # PaperFlipbook clamps FramesPerSecond to 0..1000
FALLBACK_RATE = 1000.0                      # millisecond frames when no multiple of the fps fits
COMPARE_TOLERANCE = 1e-6                    # expected.json numbers are rounded to 6 decimals
MANIFEST_DIRS = ("assets/dotwork",)         # Dotwork's default assets_dir (outside Content/: the editor would
                                            # auto-import raw PNGs dropped under Content/)
MANIFEST_SUFFIX = ".assets.json"
# Kinds in the order an importer builds them (a portrait needs its animation, a map its tileset)
CORE_ORDER = ("sprite", "animated_sprite", "icon", "portrait", "font", "ui_kit", "tileset", "map")
# extra kinds imported as textures (particles: the texture plus its emitter JSON as metadata, Niagara is #286)
TEXTURE_KINDS = ("background", "particles", "transition", "normal_map", "image")
LAYER_KINDS = ("tiles", "terrain", "stamps")   # map layer kinds this importer draws (stamps since spec 1.1.0)

# N NE E SE S SW W NW, y down (bit 0 is N)
NB8 = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
BIT = {"n": 1, "ne": 2, "e": 4, "se": 8, "s": 16, "sw": 32, "w": 64, "nw": 128}
SIDES_ONLY = BIT["n"] | BIT["e"] | BIT["s"] | BIT["w"]
CORNERS_ONLY = BIT["ne"] | BIT["se"] | BIT["sw"] | BIT["nw"]
# a corners4 tile's corner, named per shape, and the mask bit of the cell across it: on a diamond the top corner
# touches the cell up the screen, which is NW in map coordinates (ASSET_MANIFEST.md "Autotiling and maps")
CORNER_BITS = {"square": {"top_left": BIT["nw"], "top_right": BIT["ne"], "bottom_right": BIT["se"], "bottom_left": BIT["sw"]},
               "isometric": {"top": BIT["nw"], "right": BIT["ne"], "bottom": BIT["se"], "left": BIT["sw"]}}
M32 = 0xFFFFFFFF


class ManifestError(Exception):
    """A manifest this importer cannot read (missing, not JSON, another format or major version)."""


# ---- reading ---------------------------------------------------------------------------------
def load(path):
    """The manifest at path as a dict, checked for format and major version."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        raise ManifestError(f"{path} not found")
    except ValueError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}")
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ManifestError(f"{path}: format is {doc.get('format') if isinstance(doc, dict) else None!r}, "
                            f"expected {FORMAT!r}")
    version = str(doc.get("version", ""))
    try:
        major = int(version.split(".")[0])
    except ValueError:
        raise ManifestError(f"{path}: version {version!r} is not MAJOR.MINOR.PATCH")
    if major != MAJOR:
        raise ManifestError(f"{path}: manifest version {version} needs an importer for spec {major}.x; "
                            f"this importer reads {MAJOR}.x")
    if not isinstance(doc.get("assets"), list):
        raise ManifestError(f"{path}: no assets list")
    return doc


def base_dir(manifest_path, doc):
    """The folder every path in the manifest is relative to: the manifest's folder joined with its base."""
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(manifest_path)), doc.get("base", ".")))


def resolve(base, rel):
    """join(base, rel) for a manifest path; refuses .., a drive or a leading / (the spec forbids them)."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ":" in rel or ".." in rel.split("/") \
            or "\\" in rel:
        raise ManifestError(f"unsafe path in manifest: {rel!r}")
    return os.path.normpath(os.path.join(base, rel))


def find_manifests(project_dir, dirs=MANIFEST_DIRS):
    """Every <pack>.assets.json in the game's Dotwork folders, sorted."""
    out = []
    for d in dirs:
        folder = os.path.join(project_dir, d)
        if os.path.isdir(folder):
            out += sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(MANIFEST_SUFFIX))
    return out


def ordered(assets):
    """(core assets in build order, texture-only extras, skipped) by kind; unknown kinds land in skipped."""
    core = sorted((a for a in assets if a.get("kind") in CORE_ORDER), key=lambda a: CORE_ORDER.index(a["kind"]))
    extra = [a for a in assets if a.get("kind") in TEXTURE_KINDS]
    skipped = [a for a in assets if a.get("kind") not in CORE_ORDER + TEXTURE_KINDS]
    return core, extra, skipped


# ---- autotile (assetspec.py) -------------------------------------------------------------------
def canon(m):
    """A corner bit counts only when both sides next to it are set: 256 raw masks fold into the 47 blob masks."""
    for c in (1, 3, 5, 7):
        if not ((m >> ((c + 7) % 8)) & 1 and (m >> ((c + 1) % 8)) & 1):
            m &= ~(1 << c)
    return m


def cell_mask(painted, x, y, mode="blob47"):
    """The key a painted cell at (x, y) needs, from the set of painted (x, y) cells of the same terrain: blob47 the
    canon mask, sides4 the four side bits, corners4 the four corner bits of the canon mask (a corner is the terrain
    only when all four cells meeting there are painted)."""
    m = 0
    for b, (dx, dy) in enumerate(NB8):
        if (x + dx, y + dy) in painted:
            m |= 1 << b
    if mode == "sides4":
        return m & SIDES_ONLY
    if mode == "corners4":
        return canon(m) & CORNERS_ONLY
    return canon(m)


def tile_key(tile, mode, shape):
    """The key a tileset tile answers to: its mask (blob47, sides4), or the corner bits of its own terrain (corners4);
    None when it has neither."""
    if mode in ("blob47", "sides4"):
        return tile.get("mask")
    corners = tile.get("corners")
    if corners is None:
        return None
    names = CORNER_BITS.get(shape, CORNER_BITS["square"])
    if set(corners) != set(names):
        return None
    return sum(bit for name, bit in names.items() if corners[name] == tile["terrain"])


def terrain_mode(ts, set_id):
    return next((s["mode"] for s in ts.get("terrain_sets") or [] if s["id"] == set_id), None)


# ---- deterministic variant pick (assetspec.py) -------------------------------------------------
def hash32(k):
    """Bob Jenkins' 32-bit integer hash (six shifts): only shifts, adds and xors, every step kept to 32 bits."""
    k &= M32
    k = (k + 0x7ED55D16 + (k << 12)) & M32
    k = (k ^ 0xC761C23C ^ (k >> 19)) & M32
    k = (k + 0x165667B1 + (k << 5)) & M32
    k = ((k + 0xD3A2646C) ^ (k << 9)) & M32
    k = (k + 0xFD7046C5 + (k << 3)) & M32
    k = (k ^ 0xB55A4F09 ^ (k >> 16)) & M32
    return k


def cell_roll(x, y, layer):
    """The roll in [0, 1) that picks a terrain cell's variant: from the cell and the index of its layer in the map's
    layers list, the same number in every engine (coordinates wrap at 16 bits)."""
    return hash32(hash32(((x & 0xFFFF) << 16) | (y & 0xFFFF)) + layer) / 4294967296.0


def pick_variant(candidates, roll):
    """candidates: [(weight, value)] in atlas order; the value whose weight span holds roll * total, the first when
    every weight is 0. Weight 0 is never picked."""
    total = sum(w for w, _ in candidates)
    if total <= 0:
        return candidates[0][1]
    u = roll * total
    for w, v in candidates:
        u -= w
        if u < 0:
            return v
    return candidates[-1][1]


def resolve_terrain(ts, layer, layer_index=0):
    """Each painted cell of a terrain layer -> [x, y, key, [atlas, col, row] or None] (sorted by y, then x): the key
    is cell_mask's (the mask, or the corner bits), the tile is picked among the layer's terrain's tiles with that key
    (atlas order) by probability with the cell's roll (cell_roll(x, y, layer_index)), None when no tile has the key."""
    sid, tid = layer.get("terrain_set", 0), layer["terrain"]
    mode = terrain_mode(ts, sid)
    shape = ts.get("shape", "square")
    by_key = {}
    for at in ts["atlases"]:
        for t in at["tiles"]:
            if t.get("terrain") == tid and t.get("terrain_set", 0) == sid:
                k = tile_key(t, mode, shape)
                if k is not None:
                    by_key.setdefault(k, []).append((t.get("probability", 1), [at["id"], t["col"], t["row"]]))
    painted = {(c[0], c[1]) for c in layer["cells"]}
    out = []
    for x, y in sorted(painted, key=lambda p: (p[1], p[0])):
        k = cell_mask(painted, x, y, mode)
        cands = by_key.get(k)
        out.append([x, y, k, pick_variant(cands, cell_roll(x, y, layer_index)) if cands else None])
    return out


def expand_stamps(ts, layer):
    """Each [x, y, stamp] of a stamps layer -> the stamp's tiles as [x, y, atlas, col, row] in reading order (tile j
    at (x + j % w, y + j // w)), in the order of the layer's cells."""
    stamps = ts.get("stamps") or []
    out = []
    for c in layer["cells"]:
        st = stamps[c[2]]
        sw = st["size"][0]
        for j, (atlas, col, row) in enumerate(st["tiles"]):
            out.append([c[0] + j % sw, c[1] + j // sw, atlas, col, row])
    return out


def placed_cells(ts, layer, layer_index):
    """Every cell a layer draws, as [x, y, atlas, col, row]: tiles layers as they are (flags dropped), terrain layers
    resolved (cells with no tile left out), stamps layers expanded."""
    if layer["kind"] == "terrain":
        return [[x, y] + tile for x, y, _, tile in resolve_terrain(ts, layer, layer_index) if tile]
    if layer["kind"] == "stamps":
        return expand_stamps(ts, layer)
    return [list(c[:5]) for c in layer["cells"]]


# ---- cells on the screen (assetspec.py) --------------------------------------------------------
def cell_centre(shape, x, y, tile_size):
    """The centre of map cell (x, y) in map pixels (y down): squares in rows, isometric diamonds in Godot's
    diamond-down layout (x runs down-right, y down-left; cell (0, 0) at (w/2, h/2)). Paper2D lays both projections
    out the same way, half a cell over: its cell (0, 0) is centred on the tile map's origin (dotwork_paper)."""
    w, h = tile_size
    if shape == "isometric":
        return [(x - y + 1) * w / 2, (x + y + 1) * h / 2]
    return [(x + 0.5) * w, (y + 0.5) * h]


def tile_origin(tile, atlas):
    """The image point drawn on the cell centre: the tile's own origin, else the centre of the atlas tile."""
    if tile.get("origin"):
        return list(tile["origin"])
    return [atlas["tile_size"][0] / 2, atlas["tile_size"][1] / 2]


def draw_corner(ts, shape, tile_size, cell):
    """Where a placed cell's image lands: [left, top] in map pixels, the cell centre less the tile's origin."""
    x, y, aid, col, row = cell
    atlas = next(a for a in ts["atlases"] if a["id"] == aid)
    tile = next((t for t in atlas["tiles"] if t["col"] == col and t["row"] == row), {})
    cx, cy = cell_centre(shape, x, y, tile_size)
    ox, oy = tile_origin(tile, atlas)
    return [round6(cx - ox), round6(cy - oy)]


def drawing_offset(atlas, tile_size):
    """Paper2D's per-tile-set DrawingOffset (pixels, whole numbers) that puts this atlas's tiles where the spec
    draws them, and the tiles whose origin that offset cannot honour. Paper2D draws a tile's top-left at the cell's
    top-left plus (DrawingOffset.x, DrawingOffset.y + cell_h - tile_h) (PaperTileMapComponent::RebuildRenderData);
    the spec draws it at centre - origin, so the offset is (cell_w / 2 - ox, tile_h - cell_h / 2 - oy). One offset
    per tile set: the first tile's origin decides, tiles that disagree (or a half-pixel offset) are reported."""
    w, h = tile_size
    th = atlas["tile_size"][1]
    offsets = {}
    for t in atlas["tiles"]:
        ox, oy = tile_origin(t, atlas)
        offsets.setdefault((w / 2 - ox, th - h / 2 - oy), []).append([t["col"], t["row"]])
    if not offsets:
        ox, oy = tile_origin({}, atlas)
        return (int(w / 2 - ox), int(th - h / 2 - oy)), []
    chosen = next(iter(offsets))
    odd = [cell for off, cells in offsets.items() if off != chosen for cell in cells]
    if chosen != (int(chosen[0]), int(chosen[1])):
        odd = [cell for cells in offsets.values() for cell in cells]
    return (int(round(chosen[0])), int(round(chosen[1]))), odd


def paper_layer_index(i, count):
    """Paper2D draws layer 0 on top (its Tiled importer reverses Tiled's bottom-first order); manifests list
    layers first to last, last on top."""
    return count - 1 - i


# ---- timing ----------------------------------------------------------------------------------
def flipbook_rate(fps, durations):
    """(frames per second, whole frame runs per frame, exact): a rate at which every duration is whole."""
    if not durations:
        return (float(fps) if fps else 1.0), [], True
    base = float(fps) if fps and fps > 0 else 1.0 / min(durations)
    for k in range(1, RATE_STEPS + 1):
        rate = base * k
        if rate > MAX_RATE:
            break
        runs = [d * rate for d in durations]
        if all(abs(r - round(r)) <= RATE_TOLERANCE and round(r) >= 1 for r in runs):
            return rate, [int(round(r)) for r in runs], True
    return FALLBACK_RATE, [max(1, int(round(d * FALLBACK_RATE))) for d in durations], False


# ---- comparing ---------------------------------------------------------------------------------
def compare(expected, actual, where="$", tol=COMPARE_TOLERANCE, out=None):
    """Differences between a loaded result and expected.json, as readable lines (empty: they match).
    Numbers within tol are equal; bools are not numbers."""
    out = [] if out is None else out
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            out.append(f"{where}: expected {expected!r}, got {actual!r}")
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if abs(expected - actual) > tol:
            out.append(f"{where}: expected {expected!r}, got {actual!r}")
    elif isinstance(expected, dict) and isinstance(actual, dict):
        for k in expected:
            if k not in actual:
                out.append(f"{where}.{k}: missing")
            else:
                compare(expected[k], actual[k], f"{where}.{k}", tol, out)
        for k in actual:
            if k not in expected:
                out.append(f"{where}.{k}: not expected")
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(f"{where}: expected {len(expected)} items, got {len(actual)}")
        for i, (e, a) in enumerate(zip(expected, actual)):
            compare(e, a, f"{where}[{i}]", tol, out)
    elif expected != actual:
        out.append(f"{where}: expected {expected!r}, got {actual!r}")
    return out


def round6(x):
    """Numbers as expected.json writes them: 6 decimals, integers stay integers."""
    x = round(float(x), 6)
    return int(x) if x == int(x) else x
