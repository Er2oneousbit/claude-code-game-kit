#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# setup_ai.py
# Purpose : Install the local AI pieces this game needs but git does not carry (too big):
#           the NobodyWho Godot plugin (EUPL-1.2, A-0001) and the Qwen2.5 1.5B Instruct model
#           (Apache-2.0, A-0002). Downloads are checked against the SHA-256 recorded in
#           docs/licenses/ when they were first logged, so a corrupted or swapped file is refused.
# Usage   : python tools/setup_ai.py [--check] [--debug]
#             --check   only report what is installed, download nothing
# Exit    : 0 ready, 1 a download or checksum failed, 2 usage/environment problem
# Notes   : About 1.5 GB of downloads (cached in .asset_cache/, gitignored). Only the Windows x86_64
#           plugin binary is extracted; for Linux or macOS edit PLUGIN_FILES (the zip has them all).
#           Without these files the game still runs with the scripted guard.
#           Standard library only, Python 3.8+.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   for each piece: read URL and expected SHA-256 from its docs/licenses/A-000N.txt
#   if the installed files exist (and the cached download hashes right): done
#   else download into .asset_cache (resume-free, retries), verify SHA-256, install
#   plugin: extract only PLUGIN_FILES from the zip into addons/nobodywho/
import argparse
import hashlib
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".asset_cache"
USER_AGENT = "Mozilla/5.0 (compatible; claude-code-game-kit setup_ai.py)"
PLUGIN_DIR = ROOT / "addons" / "nobodywho"
PLUGIN_FILES = ["nobodywho.gdextension", "LICENSE", "icon.svg", "libnobodywho-godot-x86_64-pc-windows-msvc-release.dll"]
MODEL = ROOT / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEBUG = False


def evidence(asset_id):
    """(download URL, sha256) from docs/licenses/<id>.txt, written by tools/fetch_asset.py."""
    text = (ROOT / "docs" / "licenses" / f"{asset_id}.txt").read_text(encoding="utf-8")
    url = re.search(r"^Download\s*:\s*(\S+)", text, re.M)
    sha = re.search(r"^SHA-256\s*:\s*([0-9a-f]{64})", text, re.M)
    if not url or not sha:
        raise ValueError(f"docs/licenses/{asset_id}.txt has no Download or SHA-256 line")
    return url.group(1), sha.group(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url, dest, expected):
    """Download url to dest (unless a verified copy is there). Returns True when dest hashes right."""
    if dest.is_file() and sha256(dest) == expected:
        print(f"[ OK ] cached {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done, last = 0, time.time()
                for block in iter(lambda: resp.read(1 << 20), b""):
                    out.write(block)
                    done += len(block)
                    if time.time() - last > 5:
                        print(f"[info] {dest.name}: {done >> 20} / {total >> 20} MB", flush=True)
                        last = time.time()
            part.replace(dest)
            break
        except OSError as exc:
            print(f"[WARN] download attempt {attempt} failed: {exc}")
            time.sleep(3 * attempt)
    else:
        print(f"[FAIL] could not download {url}")
        return False
    got = sha256(dest)
    if got != expected:
        print(f"[FAIL] {dest.name}: SHA-256 {got[:16]}... does not match the logged {expected[:16]}... (refusing it)")
        dest.unlink()
        return False
    print(f"[ OK ] downloaded and verified {dest.name}")
    return True


def plugin_installed():
    return all((PLUGIN_DIR / f).is_file() for f in PLUGIN_FILES)


def install_plugin():
    url, sha = evidence("A-0001")
    zpath = CACHE / Path(url).name
    if not download(url, zpath, sha):
        return False
    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for name in PLUGIN_FILES:
            member = f"bin/addons/nobodywho/{name}"
            with z.open(member) as src, open(PLUGIN_DIR / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print(f"[ OK ] plugin installed in {PLUGIN_DIR.relative_to(ROOT).as_posix()}/")
    return True


def install_model():
    url, sha = evidence("A-0002")
    return download(url, MODEL, sha)


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Download and verify the local AI plugin and model (about 1.5 GB).")
    ap.add_argument("--check", action="store_true", help="report what is installed, download nothing")
    ap.add_argument("--debug", action="store_true", help="show tracebacks")
    args = ap.parse_args(argv)
    DEBUG = args.debug
    if args.check:
        print(f"[{' OK ' if plugin_installed() else 'MISS'}] NobodyWho plugin ({PLUGIN_DIR.relative_to(ROOT).as_posix()}/)")
        print(f"[{' OK ' if MODEL.is_file() else 'MISS'}] model ({MODEL.relative_to(ROOT).as_posix()})")
        return 0 if plugin_installed() and MODEL.is_file() else 1
    try:
        ok = (plugin_installed() or install_plugin()) and install_model()
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        if DEBUG:
            raise
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    if ok:
        print("[ OK ] ready: open the project in Godot once (it imports the plugin), then pick 'Talk to the AI guard'")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
