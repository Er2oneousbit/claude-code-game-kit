#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# asset_log.py
# Purpose : `dotwork.py log --pack NAME`: turn one pack's manifest into a docs/ASSET_LOG.md row plus a
#           docs/licenses/A-NNNN.txt evidence file (every file with its SHA-256, kind, prompt, seed and the models
#           that made it, with their licences), using the kit's fetch_asset helpers.
# Usage   : python dotwork.py log --pack town [--dry-run]
# Notes   : One row per pack: the files are listed as their common folder + count when there are many. The licence
#           cell names each model's licence from models.lock.json; check them before shipping (README: Licences).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import datetime
import json
import os

import fcore


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
    licenses = sorted({lock[m]["license"] for m in models if m in lock}) or ["no model (drawn in code)"]
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
    # the kit's AI-assisted values: "pre-generated" when model output ships, "no" for a pack drawn wholly in code
    ai = "pre-generated" if models else "no"
    modified = "yes" if any(r.get("note") == "hand-polished in Aseprite" for r in rows) else "no"
    row = (f"| {aid} | art | {shown} | Dotwork (local ComfyUI), manifest `{rel}` "
           f"| generated locally | {fetch_asset.md_cell(', '.join(licenses))} |  | {ai} | {modified} | {date} | "
           f"{fetch_asset.md_cell(notes)} |")
    ev = [f"{aid}  art  generated {date} with tools/art/dotwork (pack {a.pack})",
          "Models   : " + (", ".join(f"{m} ({lock[m]['repo']} @ {lock[m]['commit'][:12]}, {lock[m]['license']})"
                                     for m in models if m in lock) or "none (drawn in code)")]
    for r in rows:
        extra = {k: r[k] for k in ("prompt", "seed", "workflow") if r.get(k) is not None}
        ev.append(f"File     : {r['file']}  SHA-256 {r['sha256']}  {r['kind']}  {json.dumps(extra, ensure_ascii=False)}")
    if a.dry_run:
        print(row)
        print("\n".join(ev[:12]) + (f"\n... {len(ev) - 12} more lines" if len(ev) > 12 else ""))
        return 0
    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.replace(existing[0], row, 1) if existing else fetch_asset.add_log_row(text, row, fill))
    lic = os.path.join(settings.project, fetch_asset.LICENSE_DIR)
    os.makedirs(lic, exist_ok=True)
    fcore.write_text(os.path.join(lic, f"{aid}.txt"), "\n".join(ev) + "\n")
    print(f"[ OK ] {aid} {'updated in' if existing else 'added to'} {fetch_asset.ASSET_LOG.as_posix()} "
          f"({len(files)} files), evidence {(fetch_asset.LICENSE_DIR / (aid + '.txt')).as_posix()}")
    return 0
