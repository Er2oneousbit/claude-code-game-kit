# ---------------------------------------------------------------------------
# dotwork_spec.py
# Purpose : The engine-neutral rules of a Dotwork asset manifest (tools/art/dotwork/ASSET_MANIFEST.md, spec 1.x) that
#           the Unreal importer needs, in plain Python (no `import unreal`): reading and version-checking a manifest,
#           resolving its paths, the blob rule (cell_mask) for terrain map layers, a flipbook frame rate at which
#           every frame's duration is a whole number of frames, and comparing a loaded result with expected.json.
# Usage   : from kit_dotwork import dotwork_spec   (dotwork_paper.py and the tests import it)
# Notes   : A port of tools/art/dotwork/assetspec.py (canon, cell_mask, resolve_terrain): keep them in step.
#           Pseudocode (flipbook_rate)
#             base = the clip's fps; for k = 1, 2, ... up to RATE_STEPS: rate = base * k
#               every duration * rate within RATE_TOLERANCE of a whole number (and at least 1): use it
#             none fits (durations that are no fraction of the fps): FALLBACK_RATE frames per second, rounded runs
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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
TEXTURE_KINDS = ("background", "transition", "normal_map", "image")   # extra kinds imported as textures only

# N NE E SE S SW W NW, y down (bit 0 is N)
NB8 = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
SIDES_ONLY = 1 | 4 | 16 | 64                # N, E, S, W


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
    """The mask a painted cell at (x, y) needs, from the set of painted (x, y) cells of the same terrain."""
    m = 0
    for b, (dx, dy) in enumerate(NB8):
        if (x + dx, y + dy) in painted:
            m |= 1 << b
    if mode == "sides4":
        return m & SIDES_ONLY
    return canon(m)


def terrain_mode(ts, set_id):
    return next((s["mode"] for s in ts.get("terrain_sets") or [] if s["id"] == set_id), None)


def resolve_terrain(ts, layer):
    """Each painted cell of a terrain layer -> [x, y, mask, [atlas, col, row] or None]: the first tile (atlas order)
    of the layer's terrain whose mask is the cell's. corners4 terrains have no mask: every tile is None (the
    reference loader does the same; Dotwork maps paint blob47 and sides4 terrains)."""
    sid, tid = layer.get("terrain_set", 0), layer["terrain"]
    mode = terrain_mode(ts, sid)
    by_mask = {}
    for at in ts["atlases"]:
        for t in at["tiles"]:
            if t.get("terrain") == tid and t.get("terrain_set", 0) == sid and "mask" in t:
                by_mask.setdefault(t["mask"], [at["id"], t["col"], t["row"]])
    painted = {(c[0], c[1]) for c in layer["cells"]}
    out = []
    for x, y in sorted(painted, key=lambda p: (p[1], p[0])):
        m = cell_mask(painted, x, y, mode)
        out.append([x, y, m, by_mask.get(m)])
    return out


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
