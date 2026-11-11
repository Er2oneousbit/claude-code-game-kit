#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# chain.py
# Purpose : `bozzetto.py rig chain`: secondary motion for a rigged character. A scarf tail, cape, ponytail or tail
#           that an auto-rig skinned stiffly to the neck or spine gets its own chain of bones, weighted along it,
#           a sway keyed into every looping clip (so the clip still loops exactly) and, on request, a Blender cloth
#           simulation baked into one-shot clips. The Blender side is rig_chain.py; this file is the command line,
#           the backup of the rig before its first chain, the record and the asset log note.
# Usage   : python tools/bozzetto/bozzetto.py rig chain npc_guard --part colour:#c8202a~0.15
#           python tools/bozzetto/bozzetto.py rig chain npc_guard --part scarf=colour:#c8202a --bones 5 --sway 10
#           python tools/bozzetto/bozzetto.py rig chain npc_guard --part "tail=material:Tail" --cloth hit,death
#           python tools/bozzetto/bozzetto.py rig chain npc_guard --part "hair=box:-0.1,1.5,0.05,0.1,1.8,0.3" --no-replace
#           Input: <models folder>/<name>_rigged.glb (from `rig make`). Output: the same file, with the rig before
#           its first chain kept in assets_src/bozzetto/<name>/rig/chain/before_chain.glb (every run starts from it,
#           so a re-run replaces the chain instead of stacking a second one); report, record and preview there too.
# Needs   : Python 3.8+ (standard library), Blender 4.2+ or bpy (rig_chain.py runs in it)
# Exit    : 0 ok, 1 the part was refused (nothing selected, most of the mesh, a lump) or the result failed its rig
#           checks (nothing replaced), 2 usage, environment or files in the way
# Notes   : Selectors (`--part [label=]term[&term...]`, terms intersect):
#             colour:#rrggbb[~tol]   faces whose colour is within tol (Euclidean distance of sRGB 0..1, default
#                                    0.15) of it: the base texture at the face's UVs, else its colour attribute,
#                                    else its material's base colour (`color:` works too)
#             group:NAME             faces whose vertices are all at least half in vertex group NAME
#             material:NAME          faces with material NAME (case does not matter)
#             box:x0,y0,z0,x1,y1,z1  faces whose centre is inside the box, in metres and glTF axes (Y up, the
#                                    character faces +Z, its left is +X), as the engine shows the model
#           The parser lives here (standard library) and rig_chain.py imports it, so both sides read selectors alike.
#           This module only binds to bozzetto.py when the CLI runs (bind): rig_chain.py imports it inside Blender.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   options checked (selectors, bones, sway, lag, cloth) -> <name>_rigged.glb exists -> Blender found
#   base: the backup when the model is still the file the last chain run wrote, else a fresh backup of the model
#   rig_chain.py base -> chained.glb + report (select, separate or rebuild, bones, weights, sway, cloth, rig checks)
#   failed: say why, replace nothing -> ok: replace the model (unless --no-replace), record chain.json,
#   note the chain in the model's ASSET_LOG row, print one line per part and per clip
import json
import re
import shutil
import time
from pathlib import Path

bz = None   # bozzetto.py, bound by rig.py's add_parser (bind); None inside Blender, where only the parsers are used

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "rig_chain.py"
RECORD = "chain.json"
BACKUP = "before_chain.glb"
BONES_DEFAULT, BONES_MAX = 4, 12
SWAY_DEFAULT = "8"            # degrees each chain bone swings in a looping clip
LAG_DEFAULT = 0.12            # each bone this fraction of a sway cycle behind its parent
TOL_DEFAULT = 0.15            # colour distance (sRGB 0..1, Euclidean) when a colour selector gives none
LABEL_RULE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
HEX_RULE = re.compile(r"^#?([0-9a-fA-F]{6})$")
NOTE_PREFIX = "chain: "


# ---- parsers (also used inside Blender by rig_chain.py) --------------------------------------------------------
def parse_part(text, index=1):
    """'[label=]term[&term...]' -> {"label", "text", "terms": [...]}; ValueError with a plain message when wrong."""
    raw = text.strip()
    label = None
    head, sep, rest = raw.partition("=")
    if sep and ":" not in head:
        label, raw = head.strip().lower(), rest.strip()
        if not LABEL_RULE.match(label):
            raise ValueError(f"part label {label!r}: lowercase letters, digits and underscores, starting with a letter")
    if not raw:
        raise ValueError(f"--part {text!r} names no selector")
    terms = [parse_term(t) for t in raw.split("&")]
    return {"label": label or f"chain{index}", "text": raw, "terms": terms}


def parse_term(text):
    kind, sep, value = text.strip().partition(":")
    kind = kind.strip().lower()
    value = value.strip()
    if not sep or not value:
        raise ValueError(f"selector {text!r}: write kind:value (colour:#c8202a~0.15, group:Scarf, material:Scarf, "
                         "box:x0,y0,z0,x1,y1,z1)")
    if kind in ("colour", "color"):
        hexpart, _, tol = value.partition("~")
        m = HEX_RULE.match(hexpart.strip())
        if not m:
            raise ValueError(f"colour {hexpart!r}: write it as #rrggbb, e.g. #c8202a")
        h = m.group(1)
        try:
            t = float(tol) if tol.strip() else TOL_DEFAULT
        except ValueError:
            raise ValueError(f"colour tolerance {tol!r} is not a number (e.g. ~0.15)")
        if not 0.0 < t <= 1.0:
            raise ValueError(f"colour tolerance {t:g}: between 0 and 1 (0.15 is a good start)")
        rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        return {"kind": "colour", "rgb": rgb, "tol": t, "hex": "#" + h.lower()}
    if kind in ("group", "material"):
        return {"kind": kind, "name": value}
    if kind == "box":
        try:
            nums = [float(x) for x in value.split(",")]
        except ValueError:
            nums = []
        if len(nums) != 6:
            raise ValueError(f"box {value!r}: six numbers x0,y0,z0,x1,y1,z1 in metres (glTF axes, Y up)")
        lo = [min(nums[i], nums[i + 3]) for i in range(3)]
        hi = [max(nums[i], nums[i + 3]) for i in range(3)]
        if any(h - l <= 0 for l, h in zip(lo, hi)):
            raise ValueError(f"box {value!r} has no volume")
        return {"kind": "box", "lo": lo, "hi": hi}
    raise ValueError(f"selector kind {kind!r}: colour, group, material or box")


def parse_sway(text):
    """'8' or '8,idle=4,walk=12' -> (default degrees, {clip: degrees})."""
    default, per = None, {}
    for item in [t.strip() for t in text.split(",") if t.strip()]:
        name, sep, val = item.partition("=")
        try:
            deg = float(val if sep else name)
        except ValueError:
            raise ValueError(f"--sway {item!r}: degrees, or clip=degrees")
        if not 0.0 <= deg <= 45.0:
            raise ValueError(f"--sway {deg:g}: between 0 and 45 degrees per bone")
        if sep:
            per[name.strip().lower()] = deg
        else:
            default = deg
    return (float(SWAY_DEFAULT) if default is None else default), per


def parse_clips(text):
    """'none' -> [], 'oneshots' -> ['*oneshots*'], 'hit,death' -> ['hit', 'death'] (names lowercased)."""
    t = (text or "").strip().lower()
    if t in ("", "none"):
        return []
    if t in ("oneshots", "one-shots", "all"):
        return ["*oneshots*"]
    return [c.strip() for c in t.split(",") if c.strip()]


# ---- the command ---------------------------------------------------------------------------------------------
def bind(module):
    global bz
    bz = module


def check_options(args):
    """Every option checked before Blender starts. Returns the parsed parts."""
    if not args.part:
        raise bz.ToolError("--part is required: which part gets the chain (e.g. --part colour:#c8202a~0.15)")
    parts = []
    for i, p in enumerate(args.part, 1):
        try:
            parts.append(parse_part(p, i))
        except ValueError as e:
            raise bz.ToolError(str(e))
    labels = [p["label"] for p in parts]
    if len(set(labels)) != len(labels):
        raise bz.ToolError(f"two parts are both labelled {sorted(l for l in labels if labels.count(l) > 1)[0]!r}: "
                           "give them their own labels (--part scarf=... --part hair=...)")
    if not 2 <= args.bones <= BONES_MAX:
        raise bz.ToolError(f"--bones {args.bones}: from 2 to {BONES_MAX}")
    if not 0.0 <= args.lag <= 0.5:
        raise bz.ToolError(f"--lag {args.lag:g}: a fraction of a sway cycle, from 0 to 0.5")
    try:
        parse_sway(args.sway)
    except ValueError as e:
        raise bz.ToolError(str(e))
    return parts


def resolve(args):
    root = Path(args.project).resolve()
    if not root.is_dir():
        raise bz.ToolError(f"--project {args.project} is not a folder")
    if not bz.NAME_RULE.match(args.name):
        raise bz.ToolError(f"name {args.name!r}: lowercase letters, digits and underscores")
    out = args.out or bz.default_out(root)
    out_dir = (root / out) if not Path(out).is_absolute() else Path(out)
    dst = out_dir / f"{args.name}_rigged.glb"
    if not dst.is_file():
        raise bz.ToolError(f"{bz.rel(root, dst)} not found: rig the character first (bozzetto.py rig make "
                           f"{args.name})")
    return root, out_dir, dst, root / bz.SRC_ROOT / args.name / "rig" / "chain"


def pick_base(dst, work, record):
    """The rig to add chains to: the backup when the model is still the file the last chain run wrote (a re-run
    replaces that chain), else the model itself, copied to the backup first (the first run, or a re-rig since)."""
    backup = work / BACKUP
    cur = bz.sha256_bytes(dst.read_bytes())
    if backup.is_file() and record.get("output_sha256") == cur:
        return backup, "the rig before its chain (a re-run replaces the chain)"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dst, backup)
    return backup, "the model as it is now (kept as " + BACKUP + ")"


def cmd_rig_chain(args):
    check_options(args)
    root, out_dir, dst, work = resolve(args)
    log_path = root / bz.fetch_asset.ASSET_LOG
    if not args.no_log and not log_path.is_file():
        raise bz.ToolError(f"{bz.fetch_asset.ASSET_LOG.as_posix()} not found under {root}: run from the game's root "
                           "folder (or --project), or pass --no-log")
    blender = bz.find_blender(args.blender)
    if blender is None:
        raise bz.ToolError(f"Blender not found (set {bz.BLENDER_ENV}); rig_chain.py runs in it")
    rec_path = work / RECORD
    try:
        old = json.loads(rec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    base, why = pick_base(dst, work, old)
    print(f"[info] starting from {why}")
    out, report, sheet = work / "chained.glb", work / "chain_report.json", work / "chain.png"
    for stale in (out, report, sheet):
        if stale.exists():
            stale.unlink()                     # an older run's result never stands in for this one
    argv = [base, "--out", out, "--report", report, "--bones", args.bones, "--sway", args.sway, "--lag", args.lag,
            "--cloth", args.cloth, "--loop", args.loop or "none", "--rebuild", args.rebuild]
    for p in args.part:
        argv += ["--part", p]
    if args.parent:
        argv += ["--parent", args.parent]
    if not args.no_preview:
        argv += ["--sheet", sheet]
    if bz.DEBUG:
        argv.append("--debug")
    t0 = time.monotonic()
    rc, _ = bz.run_bpy(blender, SCRIPT, argv, "rig_chain")
    rep = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    record = {"tool": f"tools/{bz.TOOL.lower()}/{bz.TOOL.lower()}.py rig chain {bz.VERSION}",
              "date": time.strftime("%Y-%m-%d"), "base": bz.rel(root, base),
              "base_sha256": bz.sha256_bytes(base.read_bytes()),
              "options": {"part": args.part, "bones": args.bones, "parent": args.parent, "sway": args.sway,
                          "lag": args.lag, "cloth": args.cloth, "loop": args.loop, "rebuild": args.rebuild},
              "report": rep}
    if rc == 2:
        rec_path.write_text(json.dumps(dict(old, last_attempt=record), indent=2) + "\n", encoding="utf-8")
        raise bz.ToolError("; ".join(rep.get("failures", [])) or "rig_chain.py stopped on a usage problem "
                           "(--debug shows its output)")
    if rc != 0 or not out.is_file():
        rec_path.write_text(json.dumps(dict(old, last_attempt=record), indent=2) + "\n", encoding="utf-8")
        raise bz.JobError(f"no chain added ({'; '.join(rep.get('failures', [])) or f'exit {rc}'}); "
                          f"{bz.rel(root, dst)} is unchanged; reports in {bz.rel(root, work)}/")
    for p in rep.get("parts", []):
        print(f"[ OK ] {p['label']}: {len(p['bones'])} bones on {p['parent']}; " + part_summary(p))
    for name, c in rep.get("clips", {}).items():
        print(f"[ OK ] clip {name}: " + clip_summary(c))
    if args.no_replace:
        record["output"] = bz.rel(root, out)
        record["output_sha256"] = old.get("output_sha256")   # the model was not touched
        rec_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"[ OK ] wrote {bz.rel(root, out)} only (--no-replace): {bz.rel(root, dst)} is unchanged")
    else:
        dst.write_bytes(out.read_bytes())
        record["output"] = bz.rel(root, dst)
        record["output_sha256"] = bz.sha256_bytes(dst.read_bytes())
        rec_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"[ OK ] {bz.rel(root, dst)} (the rig before its first chain: {bz.rel(root, work / BACKUP)})")
        if not args.no_log:
            note_in_log(root, log_path, dst, rep, bz.rel(root, rec_path))
    print(f"[ OK ] {len(rep.get('parts', []))} chain(s) in {time.monotonic() - t0:.0f} s")
    print("[next] look at " + (bz.rel(root, sheet) if sheet.is_file() else "the model in the engine")
          + "; in a 3D engine the chain bones can also be driven by a spring-bone node (README 'Secondary motion')")
    return 0


def part_summary(p):
    how = {"none": "separated as it was", "cuts": f"separated, {p.get('rows_before')} rows along it cut to "
           f"{p.get('rows_after')} so it can bend", "strip": "rebuilt as a strip"}.get(p.get("rebuild"), "")
    if p.get("rebuild") == "strip":
        how += f" ({p.get('reason')}; look: {p.get('look')})"
    return how


def clip_summary(c):
    if c.get("motion") == "sway":
        return (f"loop, sway {c.get('amplitude_deg'):g} degrees, {c.get('cycles')} cycle(s) per loop, first and "
                f"last frame equal (error {c.get('loop_error', 0):.1e})")
    if c.get("motion") == "cloth":
        return f"one-shot, cloth baked into the chain (swings up to {c.get('max_deg', 0):.0f} degrees)"
    return "one-shot, the chain follows the body (name it in --cloth for a simulated swing)"


def note_in_log(root, log_path, dst, rep, record_rel):
    """Add (or replace) 'chain: ...' in the Notes cell of the model's ASSET_LOG row; no row, no change."""
    text = log_path.read_text(encoding="utf-8")
    main_rel = bz.rel(root, dst)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        cells = line.rstrip("\r\n").split("|")
        if not line.startswith("| A-") or len(cells) < 4 or f"`{main_rel}`" not in cells[3]:
            continue
        notes = [n.strip() for n in cells[-2].split(";") if n.strip() and not n.strip().startswith(NOTE_PREFIX)]
        what = ", ".join(f"{p['label']} ({len(p['bones'])} bones" + (", rebuilt as a strip" if p.get("rebuild") ==
                                                                        "strip" else "") + ")"
                         for p in rep.get("parts", []))
        notes.append(f"{NOTE_PREFIX}{what}, chain record `{record_rel}`")   # no ';': the notes are split on it
        cells[-2] = " " + "; ".join(notes) + " "
        end = line[len(line.rstrip("\r\n")):]
        lines[i] = "|".join(cells) + end
        log_path.write_bytes("".join(lines).encode("utf-8"))
        print(f"[ OK ] {cells[1].strip()}: the chain noted in {bz.fetch_asset.ASSET_LOG.as_posix()}")
        return
    print(f"[info] {main_rel} has no row in {bz.fetch_asset.ASSET_LOG.as_posix()}: nothing noted")


def add_parser(rs, common):
    import argparse
    c = rs.add_parser("chain", parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
                      help="secondary motion: a bone chain for a scarf, cape, hair or tail, swaying in every loop",
                      epilog="Selectors: colour:#rrggbb[~tol] | group:NAME | material:NAME | box:x0,y0,z0,x1,y1,z1 "
                             "(metres, glTF axes);\njoin terms with & to intersect them, prefix label= to name the "
                             "chain (bones label_01 ...).\nREADME.md 'Secondary motion' has the details and limits.")
    c.add_argument("name", help="the character's name (its <models>/<name>_rigged.glb from `rig make`)")
    c.add_argument("--part", action="append", metavar="[LABEL=]SELECTOR",
                   help="the part that gets a chain, e.g. colour:#c8202a~0.15 (the scarf: the only red); repeat "
                        "for more parts")
    c.add_argument("--bones", type=int, default=BONES_DEFAULT, help=f"bones in each chain (default {BONES_DEFAULT})")
    c.add_argument("--parent", help="body bone the chain hangs from (default: the nearest of the spine line, hips "
                                    "to head; 'Neck' finds mixamorig:Neck)")
    c.add_argument("--sway", default=SWAY_DEFAULT,
                   help=f"degrees each bone swings out from the body in looping clips (half that sideways), "
                        f"optionally per clip: 8,idle=4,run=14; 0 for engine spring bones (default {SWAY_DEFAULT})")
    c.add_argument("--lag", type=float, default=LAG_DEFAULT,
                   help=f"each bone this fraction of a sway cycle behind the one above it (default {LAG_DEFAULT})")
    c.add_argument("--cloth", default="none",
                   help="one-shot clips (hit, attack, death) to give a Blender cloth simulation baked into the "
                        "chain: names, 'oneshots' for all, or none (default)")
    c.add_argument("--loop", help="clips to treat as loops even though their first and last poses differ a little "
                                  "(mocap)")
    c.add_argument("--rebuild", choices=("auto", "strip", "no"), default="auto",
                   help="auto: rebuild the part as a strip only when it is fused to the body along its length, cut "
                        "it into rows when it has too few; strip: always rebuild; no: never change its shape")
    c.add_argument("--out", help="models folder (default: the engine's, as for make)")
    c.add_argument("--project", default=".", help="the game's root folder (default: the current folder)")
    c.add_argument("--no-replace", action="store_true",
                   help="write the result to assets_src/.../rig/chain/chained.glb only: look before replacing")
    c.add_argument("--no-preview", action="store_true", help="skip the chain.png contact sheet")
    c.add_argument("--no-log", action="store_true", help="do not touch docs/ASSET_LOG.md (scratch runs)")
    c.set_defaults(fn=cmd_rig_chain)
