#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# pxo_panel.py
# Purpose : the Python half of the Dotwork panel inside Pixelorama (pixelorama_extension/): install the extension
#           where Pixelorama loads it, write the small config it reads (which Python runs Dotwork, where dotwork.py
#           and the game are), and answer the panel's question "which game asset is this .pxo?" (its game files, the
#           QA notes Dotwork made for it, whether a re-export would refuse it, the next .pxo to polish).
# Usage   : python dotwork.py pixelorama --install-extension [--pixelorama-user DIR]   (once per game)
#           python dotwork.py pixelorama --info assets_src/pixelorama/characters/knight.pxo   (the panel runs this)
# Notes   : Pixelorama loads extensions from user://extensions (HandleExtensions.gd, v1.2.4): a zip whose entries
#           sit at src/Extensions/<name>/ with an extension.json naming the scene to add. Its user folder is
#           %APPDATA%/pixelorama on Windows, $XDG_DATA_HOME/pixelorama (~/.local/share) on Linux and
#           ~/Library/Application Support/pixelorama on macOS; --pixelorama-user picks another (a portable
#           Pixelorama, or the exams' own folder). Installing writes the zip and dotwork_panel.json there and never
#           touches Pixelorama's settings (config.ini): you enable the extension once in Edit > Preferences >
#           Extensions, which is Pixelorama's own switch. The config holds full paths on your machine; it lives in
#           Pixelorama's user folder, never in the game.
#           --info prints one line "DOTWORK_PANEL <JSON>" (other lines may come before it), so the panel reads the
#           answer without parsing Dotwork's log lines.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import glob
import io
import json
import os
import sys
import zipfile

import fcore as core
import handpolish

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION = "DotworkPanel"                      # the extension's name: the zip, its folder, its config switch
EXTENSION_SRC = os.path.join(HERE, "pixelorama_extension")
EXTENSION_FILES = ("extension.json", "Main.tscn", "Main.gd", "panel_logic.gd")
CONFIG_NAME = "dotwork_panel.json"              # beside the extensions folder: user://dotwork_panel.json
MARKER = "DOTWORK_PANEL "                       # the --info answer line
ZIP_TIME = (1980, 1, 1, 0, 0, 0)                # a fixed date: the same sources always give the same zip bytes
MAX_FILES_SHOWN = 40                            # game files listed in an --info answer (the count is always given)


# -------------------------------------------------- install
def default_user_dir():
    """Pixelorama's user folder (Godot's custom user dir "pixelorama") on this system."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "pixelorama")


def extension_zip():
    """The extension as Pixelorama loads it: bytes of a zip with every source at src/Extensions/<name>/."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in EXTENSION_FILES:
            p = os.path.join(EXTENSION_SRC, name)
            if not os.path.isfile(p):
                raise core.ToolError(f"the panel's source {p} is missing (Dotwork ships it in pixelorama_extension/)")
            with open(p, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")    # a Windows checkout gives the same zip as any other
            info = zipfile.ZipInfo(f"src/Extensions/{EXTENSION}/{name}", date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            z.writestr(info, data)
    return buf.getvalue()


def game_entry(settings):
    """This game's row of the panel config: full paths, so Pixelorama can start Dotwork from anywhere."""
    godot_bin = settings.conf["fixed"].get("godot_bin") or os.environ.get("GODOT_BIN", "")
    return {"project": os.path.abspath(settings.project).replace(os.sep, "/"),
            "python": os.path.abspath(sys.executable).replace(os.sep, "/"),
            "dotwork": os.path.join(HERE, "dotwork.py").replace(os.sep, "/"),
            "sources": core.src(settings.conf, "pixelorama").replace(os.sep, "/"),
            "godot_bin": godot_bin.replace(os.sep, "/")}


def install(settings, user_dir=None):
    """Write the extension zip into Pixelorama's extensions folder and this game into dotwork_panel.json (other games
    stay). Returns {"zip", "config", "changed", "entry"}."""
    user = os.path.abspath(user_dir or default_user_dir())
    if not sys.executable:
        raise core.ToolError("this Python does not know its own path (sys.executable is empty): run Dotwork with a "
                             "regular python")
    ext_dir = os.path.join(user, "extensions")
    os.makedirs(ext_dir, exist_ok=True)
    zpath = os.path.join(ext_dir, EXTENSION + ".zip")
    data = extension_zip()
    old = None
    if os.path.isfile(zpath):
        with open(zpath, "rb") as f:
            old = f.read()
    if old != data:
        with open(zpath, "wb") as f:
            f.write(data)
    cpath = os.path.join(user, CONFIG_NAME)
    conf = {"games": []}
    if os.path.isfile(cpath):
        try:
            with open(cpath, encoding="utf-8") as f:
                conf = json.load(f)
        except ValueError:
            core.log(f"pixelorama panel: {cpath} was not valid JSON; written again")
        if not isinstance(conf, dict) or not isinstance(conf.get("games"), list):
            conf = {"games": []}
    entry = game_entry(settings)
    conf["games"] = [g for g in conf["games"] if isinstance(g, dict) and g.get("project") != entry["project"]]
    conf["games"].append(entry)
    conf["note"] = ("Written by dotwork.py pixelorama --install-extension for the Dotwork panel (one row per game, "
                    "full paths on this machine). Run it again from a game to add or update that game.")
    with open(cpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(conf, f, indent=1)
    return {"zip": zpath, "config": cpath, "changed": old != data, "entry": entry}


# -------------------------------------------------- which asset is this .pxo?
def _rel(p):
    return os.path.relpath(p, core.PROJECT).replace(os.sep, "/")


def sources(conf):
    """Every Dotwork .pxo of the game, in the order "Next asset" walks them."""
    import pixelorama
    src = core.src(conf, "pixelorama")
    return [p for k in pixelorama.SOURCE_KINDS for p in sorted(glob.glob(os.path.join(src, k, "*.pxo")))]


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def info(pack, conf, path):
    """The panel's answer for one .pxo: {"ok", "file", "kind", "name", "what", "files" (game files, at most
    MAX_FILES_SHOWN), "file_count", "home" (the folder they share, ending in /), "folder" (to show in the file
    manager), "qa" (Dotwork's notes on the asset),
    "notes", "refused" (why a re-export would stop, or ""), "export_folder" (a local path the .pxo holds, or ""),
    "next" (the next .pxo, full path), "position" ("2 of 9")}. A file that is not one of the game's Dotwork
    sources is an "ok": false answer with the reason, not an error: the panel shows it."""
    import pixelorama
    import pxo_tiles
    full = os.path.abspath(path)
    src = core.src(conf, "pixelorama")
    all_src = sources(conf)
    here = next((i for i, p in enumerate(all_src) if _same(p, full)), None)
    if here is None:
        return {"ok": False, "file": full.replace(os.sep, "/"),
                "error": f"not one of this game's Dotwork sources (they are the .pxo files under {_rel(src)}/"
                         f"characters, fx, single and tilemaps; dotwork.py pixelorama builds them)",
                "next": all_src[0].replace(os.sep, "/") if all_src else ""}
    kind = os.path.basename(os.path.dirname(full))
    name = os.path.basename(full)[:-4]
    rows = handpolish.GameManifests().current() if glob.glob(os.path.join(core.SETTINGS.src, "dotwork",
                                                                            "manifest_*.json")) else []
    out = {"ok": True, "file": _rel(full), "kind": kind, "name": name, "refused": "", "qa": [], "notes": []}
    folder = ""
    if kind in ("characters", "fx"):
        folder = core.art(conf, kind, name)
        home = _rel(folder) + "/"
        mine = [r for r in rows if r["file"].startswith(home)]
        out["what"] = f"{'character' if kind == 'characters' else 'effect'} {name}"
    elif kind == "single":
        mine = [r for r in rows if os.path.basename(r["file"])[:-4] == name and r["file"].endswith(".png")]
        out["what"] = f"image {name}"
        if mine:
            folder = os.path.join(core.PROJECT, mine[0]["file"])
    else:   # tilemaps: your own (rows name the .pxo as their source) or one Dotwork built from a map or TileSet
        mine = [r for r in rows if r.get("source") == out["file"]]
        out["what"] = f"tilemap {name}"
        try:
            tm = pxo_tiles.project(full)
        except core.ToolError as e:
            tm, out["refused"] = None, str(e)
        if tm and tm["meta"]:
            want = {x[len("res://"):] for x in (tm["meta"].get("scene"), tm["meta"].get("tileset")) if x}
            mine = [r for r in rows if r["file"] in want] + mine
            out["what"] = f"tilemap {name} (the game's {'map' if tm['meta'].get('scene') else 'TileSet'})"
            try:
                pxo_tiles._edits(tm)
            except core.ToolError as e:
                out["refused"] = str(e)
        elif tm is not None and not tm["layers"]:
            out["refused"] = f"{out['file']}: no visible tilemap layer"
        if mine:
            folder = os.path.dirname(os.path.join(core.PROJECT, mine[0]["file"]))
    if kind != "tilemaps":
        try:
            pj = pixelorama.read_pxo(full)
            if kind == "characters" and not pj["tags"]:
                out["refused"] = (f"{out['file']}: no tags: each animation is one tag named like the animation "
                                  "(walk_s)")
        except core.ToolError as e:
            out["refused"] = str(e)
    for r in mine:
        for q in r.get("qa") or []:
            label = f"{r.get('animation')}: {q}" if r.get("animation") else q
            if label not in out["qa"]:
                out["qa"].append(label)
        note = r.get("note")
        if note and note not in out["notes"]:
            out["notes"].append(note)
    files = sorted({r["file"] for r in mine})
    home = os.path.commonpath(files).replace(os.sep, "/") if files else ""
    if len(files) == 1:
        home = os.path.dirname(home)
    out.update(files=files[:MAX_FILES_SHOWN], file_count=len(files), home=home + "/" if home else "",
               folder=os.path.abspath(folder).replace(os.sep, "/") if folder else "",
               export_folder=pixelorama.export_folder(full),
               next=all_src[(here + 1) % len(all_src)].replace(os.sep, "/"),
               position=f"{here + 1} of {len(all_src)}")
    return out


def print_info(answer):
    print(MARKER + json.dumps(answer, ensure_ascii=False, sort_keys=True), flush=True)
