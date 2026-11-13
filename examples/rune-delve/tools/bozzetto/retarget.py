#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# retarget.py
# Purpose : `bozzetto.py rig retarget`: play clips from an animation pack (Quaternius' Universal Animation Library,
#           Mixamo downloads, any pack bone_map.py or a map of your own fits) on a character rigged by `rig make`
#           (#205). The Blender side is rig_retarget.py; this file is the command line, the backup of the rig before
#           its first retarget, the record and the asset log note.
# Usage   : python tools/bozzetto/bozzetto.py rig retarget npc_guard --from assets_src/packs/UAL1_Standard.glb
#             --clips Walk_Loop=walk_ual,Idle_Loop=idle_ual
#           python tools/bozzetto/bozzetto.py rig retarget npc_guard --from mixamo/Walking.fbx --clips mixamo.com=walk --replace
#           Input: <models folder>/<name>_rigged.glb (from `rig make`, Mixamo-named). Output: the same file with the
#           new clips added (its own clips stay); the rig before the first retarget is kept in
#           assets_src/bozzetto/<name>/rig/retarget/before_retarget.glb, report, record and preview beside it.
# Needs   : Python 3.8+ (standard library), Blender 4.2+ or bpy (rig_retarget.py runs in it)
# Exit    : 0 ok, 1 refused (no bone map fits, the rigs face different ways, a clip name is taken, the transfer
#           missed its own check: nothing replaced), 2 usage, environment or files in the way
# Notes   : The pack's licence is not this tool's to judge: the pack needs its own ASSET_LOG row (/asset-intake;
#           Quaternius is CC0). The model's row gets a "retarget: ..." note naming the clips and where they came
#           from (the pack's row id when the pack's path has one). Run it before `rig chain`: a chain's sway is keyed
#           into the clips the file has when the chain is made.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   options (clip list) -> <name>_rigged.glb exists -> the pack exists -> Blender found
#   first run: copy the rig to before_retarget.glb -> rig_retarget.py pack --onto rig -> retargeted.glb + report
#   failed: say why, replace nothing -> ok: replace the rig (unless --no-replace), record retarget.json (a history
#   of runs), note the clips in the model's ASSET_LOG row, warn when the pack has no row of its own
import json
import shutil
import time
from pathlib import Path

import bone_map as bm

bz = None   # bozzetto.py, bound by rig.py's add_parser (bind)

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "rig_retarget.py"
RECORD = "retarget.json"
BACKUP = "before_retarget.glb"
NOTE_PREFIX = "retarget: "


def bind(module):
    global bz
    bz = module


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
    pack = Path(args.source)
    if not pack.is_absolute() and not pack.is_file():
        pack = root / args.source
    if not pack.is_file():
        raise bz.ToolError(f"--from {args.source} not found")
    if pack.suffix.lower() not in (".glb", ".gltf", ".fbx"):
        raise bz.ToolError(f"--from {pack.name}: a .glb, .gltf or .fbx")
    return root, dst, pack.resolve(), root / bz.SRC_ROOT / args.name / "rig" / "retarget"


def log_rows(text):
    """[(id, path cell)] of the ASSET_LOG rows."""
    out = []
    for line in text.splitlines():
        cells = line.split("|")
        if line.startswith("| A-") and len(cells) > 3:
            out.append((cells[1].strip(), cells[3]))
    return out


def note_in_log(root, log_path, dst, pack_ref, clips, record_rel):
    """Add (or extend) 'retarget: ...' in the Notes cell of the model's ASSET_LOG row; no row, no change."""
    text = log_path.read_text(encoding="utf-8")
    main_rel = bz.rel(root, dst)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        cells = line.rstrip("\r\n").split("|")
        if not line.startswith("| A-") or len(cells) < 4 or f"`{main_rel}`" not in cells[3]:
            continue
        notes = [n.strip() for n in cells[-2].split(";") if n.strip()]
        what = ", ".join(f"{c['from']} as {name}" for name, c in clips.items())
        notes.append(f"{NOTE_PREFIX}{what} from {pack_ref}, record `{record_rel}`")   # no ';': notes split on it
        cells[-2] = " " + "; ".join(notes) + " "
        lines[i] = "|".join(cells) + line[len(line.rstrip("\r\n")):]
        log_path.write_bytes("".join(lines).encode("utf-8"))
        print(f"[ OK ] {cells[1].strip()}: the clips noted in {bz.fetch_asset.ASSET_LOG.as_posix()}")
        return
    print(f"[info] {main_rel} has no row in {bz.fetch_asset.ASSET_LOG.as_posix()}: nothing noted")


def cmd_rig_retarget(args):
    try:
        pairs = bm.parse_clips(args.clips)
    except ValueError as e:
        raise bz.ToolError(str(e))
    if pairs == "all":
        raise bz.ToolError("--clips is required: SOURCE=new_name pairs, e.g. Walk_Loop=walk_ual,Idle_Loop=idle_ual "
                           "(a pack can hold dozens of clips)")
    if args.map and not Path(args.map).is_file():
        raise bz.ToolError(f"--map {args.map} not found")
    root, dst, pack, work = resolve(args)
    log_path = root / bz.fetch_asset.ASSET_LOG
    if not args.no_log and not log_path.is_file():
        raise bz.ToolError(f"{bz.fetch_asset.ASSET_LOG.as_posix()} not found under {root}: run from the game's root "
                           "folder (or --project), or pass --no-log")
    blender = bz.find_blender(args.blender)
    if blender is None:
        raise bz.ToolError(f"Blender not found (set {bz.BLENDER_ENV}); rig_retarget.py runs in it")
    chain_rec = work.parent / "chain" / "chain.json"
    if chain_rec.is_file():
        print(f"[WARN] {bz.rel(root, dst)} has a chain (rig chain): the new clips will not sway it. Retarget first, "
              "then run rig chain again (README 'Animation packs')")
    work.mkdir(parents=True, exist_ok=True)
    rec_path = work / RECORD
    try:
        old = json.loads(rec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    if not (work / BACKUP).is_file():
        shutil.copyfile(dst, work / BACKUP)
    out, report, sheet = work / "retargeted.glb", work / "retarget_report.json", work / "clips.png"
    for stale in (out, report, sheet):
        if stale.exists():
            stale.unlink()                     # an older run's result never stands in for this one
    argv = [pack, "--onto", dst, "--out", out, "--report", report, "--clips", args.clips]
    if args.map:
        argv += ["--map", Path(args.map).resolve()]
    if args.replace:
        argv.append("--replace")
    if not args.no_preview:
        argv += ["--sheet", sheet]
    if bz.DEBUG:
        argv.append("--debug")
    t0 = time.monotonic()
    rc, _ = bz.run_bpy(blender, SCRIPT, argv, "rig_retarget")
    rep = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    pack_rel = bz.rel(root, pack)
    pack_id = next((aid for aid, cell in log_rows(text) if f"`{pack_rel}`" in cell), None)
    run = {"tool": f"tools/{bz.TOOL.lower()}/{bz.TOOL.lower()}.py rig retarget {bz.VERSION}",
           "date": time.strftime("%Y-%m-%d"), "pack": pack_rel, "pack_sha256": bz.sha256_bytes(pack.read_bytes()),
           "pack_asset": pack_id, "clips": args.clips, "map": rep.get("map"), "report": rep}
    history = old.get("runs", [])
    if rc != 0 or not out.is_file():
        rec_path.write_text(json.dumps(dict(old, runs=history, last_attempt=run), indent=2) + "\n", encoding="utf-8")
        msg = "; ".join(rep.get("failures", [])) or f"exit {rc}"
        if rc == 2:
            raise bz.ToolError(f"rig_retarget.py stopped: {msg} (--debug shows its output)")
        raise bz.JobError(f"no clips added ({msg}); {bz.rel(root, dst)} is unchanged; reports in {bz.rel(root, work)}/")
    if args.no_replace:
        run["output"] = bz.rel(root, out)
        print(f"[ OK ] wrote {bz.rel(root, out)} only (--no-replace): {bz.rel(root, dst)} is unchanged")
    else:
        dst.write_bytes(out.read_bytes())
        run["output"] = bz.rel(root, dst)
        print(f"[ OK ] {bz.rel(root, dst)} (the rig before its first retarget: {bz.rel(root, work / BACKUP)})")
    run["output_sha256"] = bz.sha256_bytes(Path(root / run["output"]).read_bytes())
    rec_path.write_text(json.dumps({"runs": history + [run]}, indent=2) + "\n", encoding="utf-8")
    if not args.no_replace and not args.no_log:
        note_in_log(root, log_path, dst, pack_id or f"`{pack_rel}`", rep.get("clips", {}), bz.rel(root, rec_path))
    if not pack_id and not args.no_log:
        print(f"[WARN] {pack_rel} has no row of its own in {bz.fetch_asset.ASSET_LOG.as_posix()}: log the pack and "
              "its licence (/asset-intake; Quaternius packs are CC0) before the game ships")
    print(f"[ OK ] {len(rep.get('clips', {}))} clip(s) in {time.monotonic() - t0:.0f} s; in the file: "
          + ", ".join(rep.get("clips_in_file", [])))
    print("[next] look at " + (bz.rel(root, sheet) if sheet.is_file() else "the model in the engine")
          + "; play a clip in the engine as any of the rig's own (docs/ENGINE.md \"Rigged characters\")")
    return 0


def add_parser(rs, common):
    import argparse
    c = rs.add_parser("retarget", parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
                      help="play clips from an animation pack (Quaternius, Mixamo) on a rigged character",
                      epilog="Bone maps: " + "; ".join(f"{k}: {v}" for k, v in bm.MAP_NOTES.items())
                             + ".\nREADME.md 'Animation packs' has the download steps and the limits.")
    c.add_argument("name", help="the character's name (its <models>/<name>_rigged.glb from `rig make`)")
    c.add_argument("--from", dest="source", required=True, metavar="PACK",
                   help="the pack's file (.glb, .gltf or .fbx), e.g. Quaternius' UAL1_Standard.glb")
    c.add_argument("--clips", required=True,
                   help="SOURCE=new_name pairs, comma-separated, e.g. Walk_Loop=walk_ual,Idle_Loop=idle_ual "
                        "(a Mixamo FBX holds one clip: mixamo.com=walk)")
    c.add_argument("--map", help="a JSON bone map for a pack the built-in maps do not fit: {\"their_name\": \"Hips\"}")
    c.add_argument("--replace", action="store_true", help="replace a clip the rig already has by that name")
    c.add_argument("--out", help="models folder (default: the engine's, as for make)")
    c.add_argument("--project", default=".", help="the game's root folder (default: the current folder)")
    c.add_argument("--no-replace", action="store_true",
                   help="write the result to assets_src/.../rig/retarget/retargeted.glb only: look before replacing")
    c.add_argument("--no-preview", action="store_true", help="skip the clips.png contact sheet")
    c.add_argument("--no-log", action="store_true", help="do not touch docs/ASSET_LOG.md (scratch runs)")
    c.set_defaults(fn=cmd_rig_retarget)
