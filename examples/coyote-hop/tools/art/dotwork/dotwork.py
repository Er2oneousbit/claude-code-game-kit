#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dotwork.py
# Purpose : make a game's 2D pixel art with local models (ComfyUI on your own GPU): characters with 4-direction
#           idle / walk / attack animations and battle or emote poses, props with collision scenes, layered terrain
#           and buildings, maps from text, effects, enemies, battle backgrounds, title screens, fonts, window skins.
#           Everything lands in the game itself (assets/ and assets_src/) with a manifest for docs/ASSET_LOG.md.
# Usage   : python tools/art/dotwork/dotwork.py setup --check            # ComfyUI, nodes, models, SpriteKiln, Godot
#           python tools/art/dotwork/dotwork.py pack --spec assets_src/specs/town.json
#           python tools/art/dotwork/dotwork.py character --name guard --prompt "a town guard in a brass helmet"
#           python tools/art/dotwork/dotwork.py audition --name guard --clip walk_e --seeds 8101 8102 8103
#           python tools/art/dotwork/dotwork.py materials [--only cobble sand] | palette extract "assets_src/*.png" ...
#           python tools/art/dotwork/dotwork.py verify | aseprite [--reexport] | preview battle|title|attack ... | log
#           Global: --project GAME (default: current folder), --config FILE, --engine godot|none, --debug
# Notes   : Needs ComfyUI (local, http://127.0.0.1:8188 by default) with the SpriteKiln and GGUF node packs and the
#           models in models.lock.json; Godot 4 for maps and verify. README.md walks through setup and every lane.
#           Python: Pillow + numpy (the ComfyUI venv has both). Exit: 0 ok, 1 a task failed, 2 environment or usage.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import ast
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fcore  # noqa: E402

LANES = ("props", "effects", "tiles", "ui", "icons", "portraits", "tools", "img2px", "fonts", "battle_bgs", "enemies",
         "windows", "balloons", "scenes", "hitfx", "animprops", "vehicles")


# ---- binding -------------------------------------------------------------------------
def setup_run(a, spec=None, game=True):
    """Settings for this game, bound into every module before any lane is imported. game=True (every command that
    writes into the game) refuses a folder that is not a game and creates the work folder; setup, config and palette
    pass game=False and create nothing."""
    s = fcore.Settings(a.project, a.config, a.engine, spec)
    if game:
        s.require_game()
        s.ensure_work()
    fcore.bind(s)
    fcore.load_lock()
    import engine
    import godot
    import spritekiln
    engine.bind(s.conf)
    spritekiln.bind(s.conf)
    godot.ENABLED = s.godot()
    return s


def load_spec(path):
    try:
        with open(path, encoding="utf-8") as f:   # specs are hand-written UTF-8 (glyph keys like the hand cursor)
            spec = json.load(f)
    except FileNotFoundError:
        raise fcore.ToolError(f"spec {path} not found")
    except ValueError as exc:
        raise fcore.ToolError(f"spec {path} is not valid JSON: {exc}")
    if not isinstance(spec, dict) or "name" not in spec:
        raise fcore.ToolError(f"spec {path}: a JSON object with at least a \"name\" (see README: Pack spec)")
    unknown = set(spec) - set(LANES) - {"name", "_comment", "design", "characters", "ground"}
    if unknown:
        raise fcore.ToolError(f"spec {path}: unknown keys {', '.join(sorted(unknown))} (lanes: {', '.join(LANES)}, "
                              "characters, ground)")
    for lane in [x for x in (*LANES, "characters") if spec.get(x) is not None]:
        entries = spec[lane]
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise fcore.ToolError(f"spec {path}: \"{lane}\" must be a list of objects (README: Pack spec)")
        known = entry_keys(lane)
        for i, e in enumerate(entries):
            if not isinstance(e.get("name"), str) or not e["name"].strip():
                raise fcore.ToolError(f"spec {path}: {lane} entry {i + 1} needs a \"name\"")
            for k in sorted(set(e) - known):
                print(f"[warn] spec {path}: {lane} {e['name']!r}: key {k!r} is not read by Dotwork (a typo?)",
                      file=sys.stderr)
    return spec


ENTRY_VARS = ("e", "self.e", "entry")   # the names lane code gives a spec entry


def _dotted(node):
    """"e" / "self.e" for a Name or one-level Attribute node, else None (ast.unparse needs Python 3.9; the kit's
    floor is 3.8)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _subscript_key(node):
    """The constant inside e["k"]: Python 3.8 wraps it in ast.Index, 3.9+ does not."""
    s = node.slice
    if isinstance(s, getattr(ast, "Index", ())):
        s = s.value
    return s.value if isinstance(s, ast.Constant) and isinstance(s.value, str) else None


def entry_keys(lane):
    """Every key the lane's code reads from a spec entry (e["k"], e.get("k"), "k" in e, on e or self.e), found by
    reading the lane's source (and the lane modules it imports from) without importing it. A spec key outside this set
    is warned about: a window entry with "styl" used to build the default style without a word (2026-10-30 audit)."""
    files, seen, keys = [f"lane_{'character' if lane == 'characters' else lane}.py"], set(), {"name", "seed", "_comment"}
    while files:
        fn = files.pop()
        if fn in seen or not os.path.exists(os.path.join(HERE, fn)):
            continue
        seen.add(fn)
        with open(os.path.join(HERE, fn), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("lane_"):
                files.append(n.module + ".py")
            elif isinstance(n, ast.Subscript) and _dotted(n.value) in ENTRY_VARS and _subscript_key(n):
                keys.add(_subscript_key(n))
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args
                    and _dotted(n.func.value) in ENTRY_VARS and isinstance(n.args[0], ast.Constant)):
                keys.add(n.args[0].value)
            elif (isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant) and isinstance(n.ops[0], ast.In)
                    and _dotted(n.comparators[0]) in ENTRY_VARS):
                keys.add(n.left.value)
    return keys


def finish_verify(s, man, no_verify):
    if no_verify or not s.godot():
        return 0
    import verify
    r = verify.verify(s, [row["file"] for row in man.data["assets"]])
    if not r["ok"]:
        raise fcore.JobError(f"verify failed in the game (see {fcore.work('verify_report.json')})")
    return 0


# ---- commands --------------------------------------------------------------------------
def spec_path(a):
    """--spec as typed (relative to the current folder), else relative to --project; the error names both paths it
    tried (it used to show only the relative one)."""
    if os.path.isabs(a.spec) or os.path.exists(a.spec):
        return a.spec
    alt = os.path.join(a.project, a.spec)
    if os.path.exists(alt):
        return alt
    raise fcore.ToolError(f"spec not found: looked for {os.path.abspath(a.spec)} and {os.path.abspath(alt)}")


def cmd_pack(a):
    a.spec = spec_path(a)
    spec = load_spec(a.spec)
    s = setup_run(a, spec)
    man = fcore.Manifest(s, spec["name"])
    conf = s.conf
    where = "characters"   # the lane running now, for the missing-key message below
    try:
        if spec.get("characters"):
            import lane_character
            for e in spec["characters"]:
                lane_character.Character(e, s.project, man, conf).run()
        for lane in LANES:
            if spec.get(lane):
                where = lane
                mod = __import__(f"lane_{lane}")
                mod.run(spec[lane], s.project, man, conf)
        where = "ground"
        grounds = spec.get("ground") or []
        for g in grounds if isinstance(grounds, list) else [grounds]:
            import lane_ground
            import mapbuild
            built = lane_ground.run(g, s.project, man, conf)
            for m in g.get("maps", []) + ([g["map"]] if g.get("map") else []):
                scene, summary = mapbuild.build(m, built, s.project, conf)
                man.add(scene, "scene", node="Node2D + TileMapLayers", layers=summary, tileset=built["res"],
                        note="painted by Godot's terrain solver from an ASCII map (mapbuild)")
    except KeyError as exc:   # a key a lane needs is not in the entry: say so instead of "unexpected failure"
        if fcore.DEBUG:
            raise
        raise fcore.ToolError(f"spec {a.spec}: a {where} entry is missing the key {exc} (README: Pack spec; "
                              "--debug shows where it was read)")
    finally:
        fcore.stop_comfy()
    man.drop_engine_rows()
    man.save()
    print(f"[ OK ] pack {spec['name']}: {len(man.data['assets'])} files; manifest {os.path.relpath(man.path, s.project)}")
    return finish_verify(s, man, a.no_verify)


def cmd_character(a):
    s = setup_run(a)
    import lane_character
    fixes = {}
    for item in a.fix:   # "punch_w:keep=4"
        clip, sep, kv = item.partition(":")
        k, sep2, v = kv.partition("=")
        if not sep or not sep2:
            raise fcore.ToolError(f"--fix {item!r}: use CLIP:KEY=VALUE, e.g. punch_w:keep=4")
        fixes.setdefault(clip, {})[k] = int(v) if v.lstrip("-").isdigit() else v
    bad = [m for m in a.motion if "=" not in m]
    if bad:
        raise fcore.ToolError(f"--motion {bad[0]!r}: use ACTION=TEXT, e.g. attack=\"swing the wrench overhead\"")
    if a.source and os.path.isabs(a.source):
        fcore.TRUSTED.add(os.path.normpath(a.source))   # typed by the user, so it may live outside the game
    entry = {"name": a.name, "prompt": a.prompt, "source": a.source, "asymmetric": a.asymmetric, "actions": a.actions,
             "directions": a.directions, "seeds": a.seeds, "east_edit": a.east_edit, "subject": a.subject,
             "clip_fix": fixes, "motions": dict(m.split("=", 1) for m in a.motion),
             "poses": a.poses, "pose_dirs": a.pose_dirs}
    if not (a.prompt or a.source):
        raise fcore.ToolError("character needs --prompt (generate the south sprite) or --source (an existing one)")
    man = fcore.Manifest(s, a.name)
    try:
        tres, canvas = lane_character.Character(entry, s.project, man, s.conf).run()
        fcore.log(f"character {a.name} done: canvas {canvas}")
    finally:
        fcore.stop_comfy()
    if man.drop_engine_rows():
        man.save()
    return finish_verify(s, man, a.no_verify)


def cmd_audition(a):
    s = setup_run(a)
    import audition
    hue = tuple(int(x) for x in a.feature_hue.split("-")) if a.feature_hue else None
    entry = {"name": a.name, "asymmetric": a.asymmetric, "subject": a.subject,
             "motions": dict(m.split("=", 1) for m in a.char_motion)}
    if a.promote:
        meta = audition.promote(entry, a.clip, a.promote)
        print(f"[ OK ] {a.promote} is now the shipped {a.clip}. Re-run the character with its usual arguments plus:\n"
              f"       --fix {audition.apply_hint(a.clip, meta)}")
        return 0
    if not a.seeds:
        raise fcore.ToolError("audition needs --seeds (or --promote TAG)")
    try:
        report, sheet, ranked = audition.run(entry, a.clip, a.seeds, a.motion, hue, s.project)
    finally:
        fcore.stop_comfy()
    print(f"[ OK ] {sheet}")
    for t in ranked:
        extra = f" feature {t['feature_retention']:.0%}" if "feature_retention" in t else ""
        print(f"  #{t['rank']} {t['tag']:<10} score {t['score']:>6}{extra} reach {t['reach_px']}px"
              f"{' TURN?' if t['turned'] else ''}{' HEIGHT' if t['height_drift'] else ''}")
    if ranked:
        print(f"[info] the score only sorts the sheet; look at it. To ship #1: --fix {audition.apply_hint(a.clip, ranked[0])}")
    return 0


def cmd_materials(a):
    s = setup_run(a)
    import materials
    if a.extend_palette:
        return materials.extend_palette(a.add, a.out)
    try:
        p, n = materials.render(a.only)
    finally:
        fcore.stop_comfy()
    print(f"[ OK ] {n} materials -> {p}")
    return 0


def cmd_palette(a):
    setup_run(a, game=False)   # builds a palette file anywhere
    import palette
    return palette.cmd(a)


def cmd_verify(a):
    s = setup_run(a)
    if not s.godot():   # it used to start Godot anyway
        raise fcore.ToolError("verify loads the assets inside Godot; with --engine none there is no Godot resource to "
                              "check (the PNGs, sheets + JSON and .fnt fonts are the output)")
    import glob
    import verify
    rows = []
    for p in glob.glob(os.path.join(s.src, "dotwork", "manifest_*.json")):
        with open(p, encoding="utf-8") as f:
            rows += [r["file"] for r in json.load(f)["assets"]]
    if not rows:
        raise fcore.ToolError("nothing to verify: no Dotwork manifests in this game yet")
    r = verify.verify(s, rows)
    for line in r["load_lines"]:
        print(" ", line)
    if not r["ok"]:
        raise fcore.JobError("verify failed (see verify_report.json in the Dotwork work folder)")
    print(f"[ OK ] {len(r['resources'])} resources load in the game")
    return 0


def cmd_aseprite(a):
    s = setup_run(a)
    import aseprite
    if a.reexport:
        r = aseprite.reexport(s.project, s.conf)
        if r and not r["ok"]:
            raise fcore.JobError("re-exported files failed verify")
        print("[ OK ] re-exported and verified")
        return 0
    files = aseprite.build(s.project, s.conf)
    print(f"[ OK ] {len(files)} .aseprite files under {os.path.join(s.src, 'aseprite')}")
    return 0


PREVIEWS = {"battle": ("battle_mock", "a battle screen from a party character, enemies and a background"),
            "title": ("title_mock", "the title screen over a scene"),
            "attack": ("demo_attack", "an animated attack: character, projectile, impact")}


def cmd_preview(a, rest):
    wants_help = any(x in ("-h", "--help") for x in rest)
    if not a.kind:   # `preview --help` used to exit 2 with "the following arguments are required: kind"
        print("usage: dotwork.py preview KIND [options]   (KIND --help lists its options)\n\nkinds:")
        for k, (_, what) in PREVIEWS.items():
            print(f"  {k:<8} {what}")
        if wants_help:
            return 0
        raise fcore.ToolError("preview needs a kind: " + ", ".join(PREVIEWS))
    mod = PREVIEWS[a.kind][0]
    if wants_help:   # a module's help needs no game folder
        return __import__(mod).main(rest)
    setup_run(a)
    try:
        return __import__(mod).main(rest)
    except FileNotFoundError as exc:   # the defaults name the example assets; a game without them needs its own
        raise fcore.ToolError(f"preview {a.kind}: {exc.filename or exc} not found; pass this game's art instead "
                              f"(dotwork.py preview {a.kind} --help)")


def cmd_setup(a):
    s = setup_run(a, game=False)   # reports a wrong folder instead of refusing
    import setup_check
    return setup_check.run(s, a)


def cmd_log(a):
    s = setup_run(a)
    import asset_log
    return asset_log.run(s, a)


def cmd_config(a):
    s = setup_run(a, game=False)
    print(json.dumps({k: v for k, v in s.conf.items() if k != "fixed"}, indent=1, ensure_ascii=False))
    return 0


# ---- arguments --------------------------------------------------------------------------
def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=".", help="the game's folder (default: current folder)")
    common.add_argument("--config", help="Dotwork config JSON (default <project>/art_src/dotwork/dotwork.config.json)")
    common.add_argument("--engine", choices=["godot", "none"], help="godot (default): write .tres/.tscn; none: "
                        "PNGs, sheets and JSON only (web, Bevy, other engines)")
    common.add_argument("--debug", action="store_true", help="tracebacks and request logs")
    ap = argparse.ArgumentParser(description="Dotwork: local pixel-art assets for a game, made with ComfyUI on your GPU. "
                                             "Global options, before or after the command: --project GAME, "
                                             "--config FILE, --engine godot|none, --debug. `dotwork.py COMMAND --help` "
                                             "lists a command's own options.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Exit: 0 ok, 1 a task failed, 2 environment or usage. README.md: setup, lanes, "
                                        "limits.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", parents=[common], help="check ComfyUI, node packs, models, SpriteKiln and Godot")
    p.add_argument("--check", action="store_true", help="check only (the default; Dotwork never downloads models)")
    p.add_argument("--tier", choices=["sprites", "rotate", "animate", "all"], default="all",
                   help="check only the models one tier needs (sprites 15 GB, rotate 29 GB, animate 33 GB)")
    p.add_argument("--hash", action="store_true", help="also SHA-256 every model file (slow: tens of GB)")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("pack", parents=[common], help="build everything in a pack spec (README: Pack spec)")
    p.add_argument("--spec", required=True, help="the pack spec JSON (examples/ has one per capability)")
    p.add_argument("--no-verify", action="store_true", help="skip the in-game Godot proof")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("character", parents=[common], help="one animated character")
    p.add_argument("--name", required=True, help="character name (file and folder names)")
    p.add_argument("--prompt", help="describe the character (Dotwork draws the south sprite)")
    p.add_argument("--source", help="an existing south-facing sprite PNG instead")
    p.add_argument("--asymmetric", action="store_true", help="generate west instead of mirroring east")
    p.add_argument("--actions", nargs="+", help="default: design.character.actions (idle walk attack)")
    p.add_argument("--directions", nargs="+", choices=["s", "e", "n", "w"], help="default: all four")
    p.add_argument("--seeds", type=int, default=3, help="south-sprite candidates when generating")
    p.add_argument("--east-edit", help="edit instruction applied to the east sprite before animating")
    p.add_argument("--subject", help='animation subject wording, e.g. "the pixel art guard with a halberd"')
    p.add_argument("--motion", nargs="*", default=[], metavar="ACTION=TEXT", help="per-character motion wording")
    p.add_argument("--fix", nargs="*", default=[], metavar="CLIP:KEY=VAL",
                   help='per-clip fixes: walk_n:seed=5151 punch_w:keep=4 "punch_w:motion=TEXT"')
    p.add_argument("--poses", choices=["battle", "field"], help="add still poses (battle: facing left; field: emotes)")
    p.add_argument("--pose-dirs", nargs="+", default=None, help="directions for --poses (battle w, field s)")
    p.add_argument("--no-verify", action="store_true", help="skip the in-game Godot proof")
    p.set_defaults(fn=cmd_character)

    p = sub.add_parser("audition", parents=[common], help="extra takes of one clip on one sheet (shipped clip untouched)")
    p.add_argument("--name", required=True, help="a character Dotwork already made (its rotations are reused)")
    p.add_argument("--clip", required=True, help="action_direction, e.g. walk_e")
    p.add_argument("--seeds", nargs="+", type=int, help="one take per seed, e.g. 8101 8102 8103")
    p.add_argument("--promote", metavar="TAG", help="make take TAG (e.g. m1_s8101) the shipped clip, no render")
    p.add_argument("--motion", nargs="*", default=[""], metavar="TEXT", help='wordings to try; "" = the default')
    p.add_argument("--char-motion", nargs="*", default=[], metavar="ACTION=TEXT",
                   help="the character's per-action motion wording, as in its spec")
    p.add_argument("--feature-hue", metavar="LO-HI", help="signature colour hue range to track, e.g. brass 30-56")
    p.add_argument("--asymmetric", action="store_true", help="as in the character's spec (west not mirrored)")
    p.add_argument("--subject", help="as in the character's spec")
    p.set_defaults(fn=cmd_audition)

    p = sub.add_parser("materials", parents=[common], help="render the material catalog for review / grow the env palette")
    p.add_argument("--only", nargs="+", help="material names from catalog/materials.json (default: all)")
    p.add_argument("--extend-palette", action="store_true", help="grow the environment palette from the renders")
    p.add_argument("--add", type=int, default=32, help="--extend-palette: colours to add")
    p.add_argument("--out", help="palette file for --extend-palette")
    p.set_defaults(fn=cmd_materials)

    p = sub.add_parser("palette", parents=[common], help="build a palette from your own art")
    p.add_argument("action", choices=["extract", "extend"], help="extract: a new palette; extend: add to --base")
    p.add_argument("sources", nargs="+", help="PNG globs")
    p.add_argument("--colors", type=int, default=64, help="extract: palette size")
    p.add_argument("--base", help="extend: the palette to keep")
    p.add_argument("--add", type=int, default=32, help="extend: colours to add")
    p.add_argument("--gap", type=float, default=0.04, help="extend: OKLab distance that counts as missing")
    p.add_argument("--out", required=True, help=".hex file to write")
    p.set_defaults(fn=cmd_palette)

    p = sub.add_parser("verify", parents=[common], help="prove this game's Dotwork assets load (Godot)")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("aseprite", parents=[common], help="editable .aseprite sources / re-export after hand polish")
    p.add_argument("--reexport", action="store_true", help="push hand-polished .aseprite files back into the game")
    p.set_defaults(fn=cmd_aseprite)

    # add_help=False: "preview battle --help" reaches the battle module, which lists its own flags (--char, --bg ...)
    p = sub.add_parser("preview", parents=[common], add_help=False,
                       help="mock screens from the game's art (battle, title, attack); "
                            "`preview KIND --help` lists each one's options")
    p.add_argument("kind", nargs="?", choices=["battle", "title", "attack"], help="battle, title or attack")
    p.set_defaults(fn=None)

    p = sub.add_parser("log", parents=[common], help="add docs/ASSET_LOG.md rows for a pack's manifest")
    p.add_argument("--pack", required=True, help="the pack name (spec \"name\")")
    p.add_argument("--dry-run", action="store_true", help="print the row, write nothing")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("config", parents=[common], help="print the merged settings")
    p.set_defaults(fn=cmd_config)
    return ap


GLOBAL_OPTS = {"--project": True, "--config": True, "--engine": True, "--debug": False}   # option: takes a value


def sink_global_options(argv, commands):
    """The kit's rule: global options work before or after the subcommand. They live on each subcommand here, so
    `dotwork.py --debug setup --check` becomes `dotwork.py setup --debug --check`. Anything else before the subcommand
    is left alone for argparse to report."""
    front, i = [], 0
    while i < len(argv) and argv[i] not in commands:
        name = argv[i].split("=", 1)[0]
        if name not in GLOBAL_OPTS:
            return argv
        front.append(argv[i])
        if GLOBAL_OPTS[name] and "=" not in argv[i] and i + 1 < len(argv):
            front.append(argv[i + 1])
            i += 1
        i += 1
    return argv if i >= len(argv) else [argv[i]] + front + argv[i + 1:]


def main(argv=None):
    fcore.utf8_stdio()
    ap = build_parser()
    sub = next(x for x in ap._actions if isinstance(x, argparse._SubParsersAction))
    argv = sink_global_options(list(sys.argv[1:] if argv is None else argv), sub.choices)
    a, rest = ap.parse_known_args(argv)
    fcore.DEBUG = a.debug
    if rest and a.cmd != "preview":
        ap.error(f"unrecognized arguments: {' '.join(rest)}")
    try:
        return cmd_preview(a, rest) if a.cmd == "preview" else a.fn(a)
    except fcore.ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except fcore.JobError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[abort] interrupted (a queued ComfyUI job keeps running; cancel it in ComfyUI)", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if fcore.DEBUG:
            traceback.print_exc()
        return 2
    finally:
        fcore.stop_comfy()


if __name__ == "__main__":
    sys.exit(main())
