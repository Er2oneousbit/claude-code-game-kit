#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# rebake.py
# Purpose : `bozzetto.py rebake <name>` and the UV-floor policy of make (#293, #203). A generated model's atlas is
#           the vendor's (Tripo: 6,805 islands over 29% of the texture; TRELLIS.2 characters just under the npc
#           floor), and the user cannot fix it without a rebake. The Blender side is tools/blender/rebake_uvs.py
#           (a fresh layout, the textures baked onto it, checked by rendering both); this file is the command line
#           for a model make already placed, the waiver `--accept-uv` both make and rebake share, and what both
#           write to the record, the asset log row and its evidence file.
# Usage   : python tools/bozzetto/bozzetto.py rebake npc_guard                   # <models>/npc_guard.glb in place
#           python tools/bozzetto/bozzetto.py rebake npc_guard --texture 1024 --no-replace   # look first
#           python tools/bozzetto/bozzetto.py rebake statue --input assets/models/statue.glb --class prop
#           python tools/bozzetto/bozzetto.py make chr_keeper --with tripo ... --accept-uv   # ship under the floor
#           Input: <models>/<name>.glb (from make), or --input any .glb. Output: the same file (and its LODs,
#           made again from the rebaked model), with the model before its first rebake kept in
#           assets_src/bozzetto/<name>/rebake/before_rebake.glb; every run starts from it, so a re-run with another
#           texture size replaces the bake instead of baking a bake. Reports, record and turntable there too.
# Needs   : Python 3.8+ (standard library), Blender 4.2+ or bpy (rebake_uvs.py, prep_export.py, validate_asset.py)
# Exit    : 0 ok, 1 the bake did not match the original or the result failed the class budget (nothing replaced),
#           2 usage, environment or files in the way
# Notes   : The policy (README "UV coverage"): the SOP-11 floor stays a failure in validate_asset.py (it measures
#           what ships, not where it came from). The remedy is the rebake: on by default for `make --with tripo`
#           (the atlas is always Tripo's), `--rebake auto` on the local route (only under the class floor: cleanup.py
#           --rebake-under, #203), `--rebake` always, `--no-rebake` to keep a vendor atlas.
#           When a model still fails on UV coverage alone (a 51k-triangle, 120-part character rebakes from 29% to
#           46%, under the hero floor of 60%: Blender's packer cannot nest islands in the holes of ring-shaped
#           ones, K01), `--accept-uv` ships it with the waiver written to the record, the asset log row and the
#           evidence file: "UV coverage waived: 46% under the hero floor 60% (--accept-uv)". Sprite sources
#           (render_sprites.py) never needed the floor: the waiver is the honest way through for them too.
# Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the policy text for --rebake auto (#203)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   waive_uv: every failure is a UV coverage one -> move them to validation["waived"], True; else False
#   log_notes / log_evidence: the rebake numbers and the waiver, from a make record, for its row and evidence file
#   rebake <name>: the model exists -> Blender found -> base: the backup when the model is still the last output,
#     else a fresh backup -> rebake_uvs.py base -> rebaked.glb + report -> prep_export.py (LODs) -> validate_asset.py
#     --class -> failed (or the bake check failed): nothing replaced, exit 1 -> --no-replace: stop ->
#     replace the model and its LODs -> record -> the model's bozzetto.json (hashes, validation) -> the asset log
#     row's notes and the evidence file -> turntable
import json
import shutil
import time
from pathlib import Path

bz = None   # bozzetto.py, bound by its build_parser (bind)

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "blender" / "rebake_uvs.py"
RECORD = "rebake_record.json"
BACKUP = "before_rebake.glb"
NOTE_PREFIX = "rebaked: "
WAIVER_PREFIX = "UV coverage waived: "
COVERAGE_FAIL = "UV coverage"   # validate_asset's failure line starts "<object>: UV coverage NN% is under MM%"


def bind(module):
    global bz
    bz = module


# ---- the policy, shared with make --------------------------------------------------------------------------
def waive_uv(validation):
    """--accept-uv: when every failure is a UV coverage one, move them to validation['waived'] and return True.
    Any other failure (size, triangles, a missing texture) keeps the model out, waiver or not."""
    fails = validation.get("failures") or []
    if not fails or not all(f": {COVERAGE_FAIL} " in f for f in fails):
        return False
    validation["waived"] = fails
    validation["failures"] = []
    return True


def hint(validation, rebaked=False):
    """What to say after a budget failure that is UV coverage alone (rebaked: the rebake already ran)."""
    fails = validation.get("failures") or []
    if fails and all(f": {COVERAGE_FAIL} " in f for f in fails):
        return (" This is the UV coverage floor alone: --accept-uv ships the model with the waiver on its asset log "
                "row (README 'UV coverage')" + ("." if rebaked else
                                                "; --rebake (on by default with Tripo) gives it a fresh layout first."))
    return ""


def rebake_summary(cleanup_report):
    """The rebake entry of a cleanup.json (None when the rebake did not run)."""
    rb = (cleanup_report or {}).get("rebake")
    return rb if isinstance(rb, dict) and rb.get("uv_coverage_after") is not None else None


def waiver_text(validation, cls, floor):
    waived = validation.get("waived") or []
    if not waived:
        return ""
    cov = ", ".join(w.split(COVERAGE_FAIL, 1)[1].split()[0] for w in waived)
    return f"{WAIVER_PREFIX}{cov} under the {cls} floor {floor:.0%} (--accept-uv)"


def log_notes(record, cls, floor):
    """Notes-cell fragments for a make record: the rebake numbers, the waiver."""
    out = []
    rb = rebake_summary(record.get("cleanup"))
    if rb:
        out.append(f"UV rebaked {rb['uv_coverage_before']:.0%} -> {rb['uv_coverage_after']:.0%} at {rb['texture_px']} px")
    w = waiver_text(record.get("validation") or {}, cls, floor)
    if w:
        out.append(w)
    return out


def log_evidence(record, cls, floor):
    """Evidence-file lines for a make record."""
    out = []
    rb = rebake_summary(record.get("cleanup"))
    if rb:
        out.append("Rebake   : " + rebake_line(rb))
    w = waiver_text(record.get("validation") or {}, cls, floor)
    if w:
        out.append(f"Waiver   : {w}")
    return out


def rebake_line(rb):
    check = rb.get("check") or {}
    lit = rb.get("check_lit") or {}
    bake = rb.get("bake") or {}
    maps = ", ".join(f"{m['source']} ({m['kind']})" for m in rb.get("maps") or []) or "no textures"
    return (f"UV coverage {rb['uv_coverage_before']:.0%} ({rb['uv_islands_before']} islands) -> "
            f"{rb['uv_coverage_after']:.0%} ({rb['uv_islands_after']} islands), texture {rb['texture_px']} px, "
            f"{maps}; Smart UV Project {bake.get('uv_angle_deg', '?')} degrees, island gap "
            f"{bake.get('island_gap_px', '?')} px, bake margin {bake.get('margin_px', '?')} px, {bake.get('samples', '?')} "
            f"samples, normals tangent space; check: mean {check.get('mean_levels')} levels flat, "
            f"{lit.get('mean_levels')} lit (max {check.get('max_levels')}) over {check.get('views')} views; "
            f"{rb.get('seconds')} s")


# ---- the subcommand ------------------------------------------------------------------------------------------
def resolve(args):
    root = Path(args.project).resolve()
    if not root.is_dir():
        raise bz.ToolError(f"--project {args.project} is not a folder")
    if not bz.NAME_RULE.match(args.name):
        raise bz.ToolError(f"name {args.name!r}: lowercase letters, digits and underscores")
    out = args.out or bz.default_out(root)
    out_dir = (root / out) if not Path(out).is_absolute() else Path(out)
    if args.input:
        dst = Path(args.input)
        if not dst.is_absolute():
            dst = root / dst
    else:
        dst = out_dir / f"{args.name}.glb"
    if not dst.is_file():
        raise bz.ToolError(f"{bz.rel(root, dst)} not found: make the model first (bozzetto.py make {args.name} ...), "
                           "or name any .glb with --input")
    if dst.suffix.lower() != ".glb":
        raise bz.ToolError("--input must be a .glb")
    return root, dst, root / bz.SRC_ROOT / args.name / "rebake"


def pick_base(dst, work, record):
    """The model to rebake: the backup when the model is still the file the last run wrote (a re-run replaces
    the bake), else the model itself, copied to the backup first."""
    backup = work / BACKUP
    cur = bz.sha256_bytes(dst.read_bytes())
    if backup.is_file() and record.get("output_sha256") == cur:
        return backup, "the model before its rebake (a re-run replaces the bake)"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dst, backup)
    return backup, "the model as it is now (kept as " + BACKUP + ")"


def model_record(root, name):
    """The make record of this model, if it has one: (path, dict)."""
    path = root / bz.SRC_ROOT / name / bz.RECORD
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return path, {}


def cmd_rebake(args):
    root, dst, work = resolve(args)
    log_path = root / bz.fetch_asset.ASSET_LOG
    if not args.no_log and not log_path.is_file():
        raise bz.ToolError(f"{bz.fetch_asset.ASSET_LOG.as_posix()} not found under {root}: run from the game's root "
                           "folder (or --project), or pass --no-log")
    blender = bz.find_blender(args.blender)
    if blender is None:
        raise bz.ToolError(f"Blender not found (set {bz.BLENDER_ENV}); rebake_uvs.py runs in it")
    rec_path, made = model_record(root, args.name)
    cls = args.asset_class or made.get("class") or "any"
    if cls not in bz.va.CLASS_BUDGETS:
        raise bz.ToolError(f"--class {cls!r}: one of {', '.join(sorted(bz.va.CLASS_BUDGETS))}")
    budget = bz.va.CLASS_BUDGETS[cls]
    lods = made.get("lods") if isinstance(made.get("lods"), list) else bz.parse_lods(None, cls) if cls in bz.CLASS_SETTINGS else []
    texture = args.texture or made.get("texture_px") or 0
    own = work / RECORD
    try:
        old = json.loads(own.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    base, why = pick_base(dst, work, old)
    print(f"[info] starting from {why}; class {cls}" + (f", texture {texture} px" if texture else ""))
    rebaked, report = work / "rebaked.glb", work / "rebake.json"
    export = work / "export" / dst.name
    validate = work / "validate.json"
    for stale in (rebaked, report, export, validate):
        if stale.exists():
            stale.unlink()                     # an older run's result never stands in for this one
    t0 = time.monotonic()
    argv = [base, "--out", rebaked, "--json", report, "--overwrite"] + (["--texture", texture] if texture else [])
    rc, _ = bz.run_bpy(blender, SCRIPT, argv + (["--debug"] if bz.DEBUG else []), "rebake")
    rb = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    if rc == 2:
        raise bz.ToolError("rebake_uvs.py stopped on a usage or environment problem (--debug shows its output)")
    if rc != 0 or not rebaked.is_file():
        raise bz.JobError(f"the rebake did not match the original (exit {rc}); {bz.rel(root, dst)} is unchanged; "
                          f"the report is {bz.rel(root, report)}")
    rc, _ = bz.run_bpy(blender, bz.TOOLS / "blender" / "prep_export.py",
                       [rebaked, "--out", export, "--class", cls, "--no-validate", "--overwrite"]
                       + (["--lods", ",".join(str(r) for r in lods)] if lods else []), "prep_export")
    if rc != 0:
        raise (bz.JobError if rc == 1 else bz.ToolError)(f"prep_export.py failed (exit {rc})")
    rc, _ = bz.run_bpy(blender, bz.TOOLS / "blender" / "validate_asset.py",
                       [export, "--class", cls, "--json", validate], "validate_asset")
    if rc not in (0, 1) or not validate.is_file():
        raise bz.JobError(f"validate_asset.py did not finish (exit {rc}); {bz.rel(root, dst)} is unchanged")
    validation = json.loads(validate.read_text(encoding="utf-8"))
    validation["asset"] = bz.rel(root, export)
    if rc == 1 and args.accept_uv and waive_uv(validation):
        rc = 0
        print(f"[WARN] {waiver_text(validation, cls, budget['min_uv_coverage'])}")
    validate.write_text(json.dumps(validation, indent=2), encoding="utf-8")
    if rc == 1:
        raise bz.JobError(f"{args.name} fails the {cls} budget after the rebake: "
                          f"{'; '.join(validation.get('failures') or [])}. {bz.rel(root, dst)} is unchanged; the files "
                          f"are in {bz.rel(root, work)}/." + hint(validation, True))
    lod_out = [export.with_name(f"{export.stem}_LOD{i}.glb") for i in range(1, len(lods) + 1)]
    record = {"tool": f"tools/{bz.TOOL.lower()}/{bz.TOOL.lower()}.py rebake {bz.VERSION}",
              "date": time.strftime("%Y-%m-%d"), "base": bz.rel(root, base),
              "base_sha256": bz.sha256_bytes(base.read_bytes()), "class": cls, "texture_px": rb.get("texture_px"),
              "report": rb, "validation": {k: validation.get(k) for k in ("failures", "warnings", "notes", "objects",
                                                                           "total_tris", "waived")},
              "lods": lods}
    print(f"[ OK ] {rebake_line(rb)}")
    if args.no_replace:
        record.update(output=bz.rel(root, export), output_sha256=old.get("output_sha256"))
        own.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"[ OK ] wrote {bz.rel(root, export)} only (--no-replace): {bz.rel(root, dst)} is unchanged")
        return 0
    placed = []
    for src, target in [(export, dst)] + [(p, dst.with_name(f"{dst.stem}_LOD{i}.glb"))
                                           for i, p in enumerate(lod_out, 1)]:
        target.write_bytes(src.read_bytes())
        placed.append(target)
        print(f"[ OK ] {bz.rel(root, target)}")
    record.update(output=bz.rel(root, dst), output_sha256=bz.sha256_bytes(dst.read_bytes()))
    own.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if made and not args.input:
        update_make_record(root, rec_path, made, record, placed)
    if not args.no_log:
        note_in_log(root, log_path, dst, rb, validation, cls, budget["min_uv_coverage"], bz.rel(root, own))
    if not args.no_preview:
        rc, _ = bz.run_bpy(blender, HERE / "turntable.py", [dst, "--out", work / "turntable.png", "--overwrite"],
                           "turntable")
        if rc != 0:
            print(f"[warn] turntable preview failed (exit {rc}); the model itself is fine")
    print(f"[ OK ] rebaked in {time.monotonic() - t0:.0f} s (the model before: {bz.rel(root, work / BACKUP)})")
    print(f"[next] look at {bz.rel(root, work / 'turntable.png')}; the engine imports the changed file as it does any")
    return 0


def update_make_record(root, rec_path, made, record, placed):
    """The model's bozzetto.json: the rebake summary, the validation, fresh hashes of the files that changed."""
    made["rebake"] = {k: record[k] for k in ("tool", "date", "texture_px", "class")}
    made["rebake"]["report"] = {k: record["report"].get(k) for k in ("uv_coverage_before", "uv_islands_before",
                                                                     "uv_coverage_after", "uv_islands_after", "maps",
                                                                     "bake", "check", "check_lit", "seconds")}
    made["validation"] = record["validation"]
    by_name = {bz.rel(root, p): p for p in placed}
    for f in made.get("files", []):
        p = by_name.get(f.get("file"))
        if p is not None:
            data = p.read_bytes()
            f["sha256"] = bz.sha256_bytes(data)
            if "triangles" in f:
                f["triangles"] = bz.glb_triangles(bz.cl.read_glb(data)[0])
    rec_path.write_text(json.dumps(made, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ OK ] {bz.rel(root, rec_path)} updated (rebake, validation, file hashes)")


def note_in_log(root, log_path, dst, rb, validation, cls, floor, record_rel):
    """'rebaked: ...' (and the waiver) in the Notes cell of the model's ASSET_LOG row, and lines in its evidence
    file; no row, no change."""
    text = log_path.read_text(encoding="utf-8")
    main_rel = bz.rel(root, dst)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        cells = line.rstrip("\r\n").split("|")
        if not line.startswith("| A-") or len(cells) < 4 or f"`{main_rel}`" not in cells[3]:
            continue
        notes = [n.strip() for n in cells[-2].split(";")
                 if n.strip() and not n.strip().startswith((NOTE_PREFIX, WAIVER_PREFIX, "UV rebaked "))]
        notes.append(f"{NOTE_PREFIX}UV {rb['uv_coverage_before']:.0%} -> {rb['uv_coverage_after']:.0%} at "
                     f"{rb['texture_px']} px, record `{record_rel}`")   # no ';': the notes are split on it
        waiver = waiver_text(validation, cls, floor)
        if waiver:
            notes.append(waiver)
        cells[-2] = " " + "; ".join(notes) + " "
        end = line[len(line.rstrip("\r\n")):]
        lines[i] = "|".join(cells) + end
        log_path.write_bytes("".join(lines).encode("utf-8"))
        aid = cells[1].strip()
        ev = root / bz.fetch_asset.LICENSE_DIR / f"{aid}.txt"
        if ev.is_file():
            extra = [f"Rebake   : {time.strftime('%Y-%m-%d')} " + rebake_line(rb)] + ([f"Waiver   : {waiver}"] if waiver else [])
            ev.write_bytes((ev.read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join(extra) + "\n").encode("utf-8"))
        print(f"[ OK ] {aid}: the rebake noted in {bz.fetch_asset.ASSET_LOG.as_posix()}"
              + (f" and {bz.rel(root, ev)}" if ev.is_file() else ""))
        return
    print(f"[info] {main_rel} has no row in {bz.fetch_asset.ASSET_LOG.as_posix()}: nothing noted")


def add_parser(sub, common):
    import argparse
    p = sub.add_parser("rebake", parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
                       help="a fresh UV layout for a model make placed, its textures baked onto it (any .glb with "
                            "--input)",
                       epilog="The model before its first rebake is kept in assets_src/bozzetto/<name>/rebake/; "
                              "every run starts from it.\nREADME.md 'UV coverage' has the policy and the numbers.")
    p.add_argument("name", help="the model's name (its <models>/<name>.glb from make)")
    p.add_argument("--input", metavar="FILE", help="rebake this .glb instead (in place; its sources go under the name)")
    p.add_argument("--texture", type=int, choices=(256, 512, 1024, 2048, 4096),
                   help="texture size (default: the make record's, else the largest image the model reads)")
    p.add_argument("--class", dest="asset_class", choices=sorted(bz.va.CLASS_BUDGETS),
                   help="budget class to validate against (default: the make record's, else any)")
    p.add_argument("--accept-uv", action="store_true",
                   help="ship a model that fails the UV coverage floor alone; the waiver goes on its asset log row")
    p.add_argument("--out", help="models folder (default: the engine's, as for make)")
    p.add_argument("--project", default=".", help="the game's root folder (default: the current folder)")
    p.add_argument("--no-replace", action="store_true",
                   help="write the result to assets_src/.../rebake/export/ only: look before replacing")
    p.add_argument("--no-preview", action="store_true", help="skip the turntable contact sheet")
    p.add_argument("--no-log", action="store_true", help="do not touch docs/ASSET_LOG.md (scratch runs)")
    p.set_defaults(fn=cmd_rebake)
