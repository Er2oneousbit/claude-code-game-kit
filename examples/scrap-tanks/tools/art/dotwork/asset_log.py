#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# asset_log.py
# Purpose : `dotwork.py log --pack NAME`: turn one pack's manifest into a docs/ASSET_LOG.md row plus a
#           docs/licenses/A-NNNN.txt evidence file (every file with its SHA-256, kind, prompt, seed and the models
#           that made it, with their licences), using the kit's fetch_asset helpers.
# Usage   : python dotwork.py log --pack town [--dry-run]
# Notes   : One row per pack: the files are listed as their common folder + count when there are many. The licence
#           cell names each model's licence from models.lock.json; check them before shipping (README: Licences).
#           A file's origin comes from its manifest row: model output (models listed), drawn by hand (no model and a
#           Pixelorama or Aseprite source or hand workflow, or a polish note on a row with no workflow: a tilemap you
#           drew, a frame you added) or drawn in code (no model, nothing else). The Source, Author, Licence and
#           AI-assisted cells name only the origins the pack holds, so a hand-drawn pack is never logged as AI output.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-04 with Claude (Opus 5.5, claude-opus-5-5): hand-drawn rows are logged as hand work, not as
#           AI output
# ---------------------------------------------------------------------------
import datetime
import json
import os

import fcore

# the note handpolish.write_back puts on a re-exported file's row ("hand-polished in Aseprite" or "... Pixelorama"),
# appended after "; " when the row already had a note: any row holding it makes the pack "modified"
POLISH_NOTE = "hand-polished in "
HAND_SOURCES = (".pxo", ".aseprite", ".ase")   # a row whose "source" is an editor file was drawn there
HAND_WORKFLOW = "drawn by hand"                # pxo_tiles.OWN_WORKFLOW and any later hand-made workflow say this
# per origin: the Source / URL, Author and Licence cell wording
ORIGIN = {"ai": ("Dotwork (local ComfyUI)", "generated locally", None),
          "code": ("Dotwork (drawn in code)", "drawn in code", "no model (drawn in code)"),
          "hand": ("drawn by hand in {tools}", "the game's artist (drawn by hand)", "own work (drawn by hand)")}


def origin(r):
    """'ai', 'hand' or 'code' for one manifest row (see the header)."""
    if r.get("models"):
        return "ai"
    src, flow, note = (r.get("source") or "").lower(), r.get("workflow") or "", r.get("note") or ""
    # a polish note alone marks a file the editor made (no workflow of its own); a code-drawn frame touched up there
    # keeps its workflow and stays "drawn in code", its polish shown by the Modified? column
    if src.endswith(HAND_SOURCES) or HAND_WORKFLOW in flow or (POLISH_NOTE in note and not flow):
        return "hand"
    return "code"


def hand_tools(rows):
    """The editors the hand-made rows name, for the Source cell ("Pixelorama", "Aseprite" or both)."""
    found = set()
    for r in rows:
        text = " ".join(str(r.get(k) or "") for k in ("source", "workflow", "note")).lower()
        src = (r.get("source") or "").lower()
        if "aseprite" in text or src.endswith(".ase"):
            found.add("Aseprite")
        if "pixelorama" in text or src.endswith(".pxo"):
            found.add("Pixelorama")
    return ", ".join(sorted(found)) or "an editor"


def run(settings, a):
    import engine  # noqa: F401  (puts the kit's tools/ on sys.path)
    try:
        import fetch_asset
    except ImportError:
        raise fcore.ToolError("the kit's tools/fetch_asset.py was not found (Dotwork runs from the kit's tools/art/)")
    man = fcore.Manifest(settings, a.pack)
    if not os.path.exists(man.path):
        raise fcore.ToolError(f"no manifest for pack {a.pack!r} ({man.path}); build it with `dotwork.py pack` first")
    rows = man.data["assets"]
    if not rows:
        raise fcore.ToolError(f"manifest {man.path} has no files")
    lock = {m["file"]: m for m in fcore.load_lock()["models"]}
    models = sorted({m for r in rows for m in r.get("models", [])})
    kinds_of = {origin(r) for r in rows}
    order = [o for o in ("ai", "hand", "code") if o in kinds_of]
    licenses = sorted({lock[m]["license"] for m in models if m in lock}) + [ORIGIN[o][2] for o in order if o != "ai"]
    tools = hand_tools([r for r in rows if origin(r) == "hand"])
    source = "; ".join(ORIGIN[o][0].format(tools=tools) for o in order)
    author = "; ".join(ORIGIN[o][1] for o in order)
    files = [r["file"] for r in rows]
    folder = os.path.commonpath(files).replace("\\", "/") if len(files) > 1 else ""
    shown = f"`{folder}/` ({len(files)} files)" if folder and len(files) > 3 else ", ".join(f"`{f}`" for f in files)
    date = datetime.date.today().isoformat()
    kinds = sorted({r["kind"] for r in rows})
    notes = f"Dotwork pack {a.pack}: {', '.join(kinds)}; models: {', '.join(models) or 'none'}"
    log_path = os.path.join(settings.project, fetch_asset.ASSET_LOG)
    if not os.path.exists(log_path):
        raise fcore.ToolError(f"{fetch_asset.ASSET_LOG.as_posix()} not found in {settings.project}")
    with open(log_path, encoding="utf-8") as f:
        text = f.read()
    rel = os.path.relpath(man.path, settings.project).replace(os.sep, "/")
    # logging a pack again updates its row and evidence file (a second run used to add A-0002 for the same files)
    existing = [line for line in text.splitlines() if line.startswith("| A-") and f"manifest `{rel}`" in line]
    if existing:
        aid, fill = existing[0].split("|")[1].strip(), None
    else:
        num, fill = fetch_asset.next_asset_id(text)
        aid = f"A-{num:04d}"
    # the kit's AI-assisted values: "pre-generated" when model output ships, "no" for a pack drawn wholly in code or
    # by hand (a Pixelorama tilemap you drew was logged as "Dotwork (local ComfyUI) ... generated locally")
    ai = "pre-generated" if "ai" in kinds_of else "no"
    modified = "yes" if any(POLISH_NOTE in (r.get("note") or "") for r in rows) else "no"
    row = (f"| {aid} | art | {shown} | {fetch_asset.md_cell(source)}, manifest `{rel}` "
           f"| {fetch_asset.md_cell(author)} | {fetch_asset.md_cell(', '.join(licenses))} |  | {ai} | {modified} "
           f"| {date} | {fetch_asset.md_cell(notes)} |")
    made = {"ai": "generated", "hand": "drawn by hand", "code": "drawn in code"}
    ev = [f"{aid}  art  {' and '.join(made[o] for o in order)}, logged {date} with tools/art/dotwork (pack {a.pack})",
          "Models   : " + (", ".join(f"{m} ({lock[m]['repo']} @ {lock[m]['commit'][:12]}, {lock[m]['license']})"
                                     for m in models if m in lock)
                          or f"none ({' and '.join(made[o] for o in order)})")]
    for r in rows:
        extra = {k: r[k] for k in ("prompt", "seed", "workflow") if r.get(k) is not None}
        if r.get("source"):
            extra["source"] = r["source"]
        ev.append(f"File     : {r['file']}  SHA-256 {r['sha256']}  {r['kind']}  {made[origin(r)]}  "
                  f"{json.dumps(extra, ensure_ascii=False)}")
    if a.dry_run:
        print(row)
        print("\n".join(ev[:12]) + (f"\n... {len(ev) - 12} more lines" if len(ev) > 12 else ""))
        return 0
    with open(fcore.safe_dest(log_path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text.replace(existing[0], row, 1) if existing else fetch_asset.add_log_row(text, row, fill))
    lic = os.path.join(settings.project, fetch_asset.LICENSE_DIR)
    os.makedirs(lic, exist_ok=True)
    fcore.write_text(os.path.join(lic, f"{aid}.txt"), "\n".join(ev) + "\n")
    print(f"[ OK ] {aid} {'updated in' if existing else 'added to'} {fetch_asset.ASSET_LOG.as_posix()} "
          f"({len(files)} files), evidence {(fetch_asset.LICENSE_DIR / (aid + '.txt')).as_posix()}")
    return 0
