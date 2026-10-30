#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# fetch_asset.py
# Purpose : Bring a third-party asset pack into the project the SOP-04 way, in one step:
#           download (cached, outside git), copy only the files you pick into the
#           project, save the license text as evidence, and add the docs/ASSET_LOG.md row.
# Usage   : python tools/fetch_asset.py --url URL --list                  # what is in the pack
#           python tools/fetch_asset.py --url URL --page PAGE --author NAME --license CC0 \
#               --type art --take "Tilemap/tilemap_packed.png" --to assets/art/pixel_platformer
#           Example (Kenney, CC0):
#             --url https://kenney.nl/media/pages/assets/<...>/kenney_pixel-platformer.zip
#             --page https://kenney.nl/assets/pixel-platformer --author Kenney --license CC0
# Exit    : 0 done, 1 download/pack problem or refused license, 2 usage problem (missing options, no
#           docs/ASSET_LOG.md under --root, a log without its table, --to outside the project, a --license-file
#           the pack does not list) or an unsafe pack (an entry with a ".." part or an absolute or drive path)
# Notes   : --page is the asset's own page where YOU read the license (SOP-04 step 2); this tool
#           records what you tell it, it cannot judge a license. NC/ND and unknown licenses are
#           refused unless --placeholder (logged as PLACEHOLDER, replace before release). Weak copyleft
#           (EUPL, MPL, LGPL) is accepted for plugins and libraries: share changes you make to them.
#           --type model is for AI model weights (SOP-15): big files, keep them out of git (.gitignore).
#           --take accepts globs relative to the pack root and may repeat. Files land flat in --to, unless
#           --base DIR is given: then each file keeps its path relative to DIR (models that reference
#           Textures/colormap.png next to them keep working).
#           Downloads are cached in .asset_cache/ (gitignored). A pack with an entry that has a ".." part, an
#           absolute path or a drive letter is refused whole, before anything is extracted. Every destination must
#           stay inside --to, and --to inside the project. Picked names that Windows cannot store (<>:"|?* or control
#           characters) and picks that differ only in case are refused. The URL is recorded and printed without
#           user:password@ and without its query string or fragment (signed links carry keys there); the full URL
#           is used only to download and to name the cache folder. --page is recorded without user:password@ but with
#           its query string (a license page may need it). Standard library only, Python 3.8+.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   check license text -> allowed / placeholder / refused
#   download URL into .asset_cache/<name> (retry, browser-like agent), unzip safely
#   --list: print the pack's files, stop
#   copy each --take match into --to (refuse to overwrite)
#   license evidence -> docs/licenses/A-NNNN.txt (pack license file + URL, page, date, sha256)
#   ASSET_LOG row A-NNNN (fill the empty template row if it is still there)
import argparse
import datetime
import fnmatch
import hashlib
import re
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

CACHE_DIR = ".asset_cache"
ASSET_LOG = Path("docs/ASSET_LOG.md")
LICENSE_DIR = Path("docs/licenses")
USER_AGENT = "Mozilla/5.0 (compatible; claude-code-game-kit fetch_asset.py)"  # some hosts reject the urllib default
RETRIES = 3
TIMEOUT = 120
ALLOWED = ("CC0", "PUBLIC DOMAIN", "CC BY", "CC-BY", "OFL", "SIL OPEN FONT", "MIT", "APACHE", "BSD", "ZLIB", "UNLICENSE",
           "EUPL", "MPL", "LGPL")   # weak copyleft (plugins, libraries): changes to THAT component must be shared
REFUSED = ("NC", "ND", "NONCOMMERCIAL", "NON-COMMERCIAL", "NODERIVATIVES", "UNKNOWN", "?")
LICENSE_FILE_GLOBS = ("license*", "licence*", "copying*", "info.txt", "readme*", "credits*")
LICENSE_TEXT_SUFFIXES = ("", ".txt", ".md", ".rst", ".html", ".htm")   # not license_plate.png
TYPES = ("art", "sprite", "tileset", "ui", "font", "music", "sfx", "voice", "3d", "vfx", "tool", "plugin", "model", "other")
WINDOWS_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')   # cannot be stored on Windows (":" also opens an NTFS stream)
WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10)}
URL_LOGIN = re.compile(r"^(\s*[A-Za-z][A-Za-z0-9+.-]*://)[^/?#]*@")   # scheme:// then user:password@ (last @ wins)
ROW_ID = re.compile(r"^\|\s*A-(\d{4})\s*\|", re.M)
EMPTY_TEMPLATE_ROW = re.compile(r"^\|\s*A-0001\s*\|\s*\|\s*\|.*$", re.M)


class FetchError(Exception):
    """Expected failure with a user-facing message (exit 1)."""


class UsageError(FetchError):
    """Wrong place or broken project files: the user fixes the call, not the pack (exit 2)."""


def judge_license(text, placeholder):
    """Return 'ok' or 'placeholder'; raise FetchError when the license is refused."""
    words = set(re.split(r"[\s/,()-]+", text.upper()))
    if words & {"NC", "ND", "NONCOMMERCIAL", "NODERIVATIVES"} or any(r in text.upper() for r in REFUSED[2:]):
        if placeholder:
            return "placeholder"
        raise FetchError(f"license '{text}' does not allow a release (NC/ND or unknown). Use --placeholder "
                         "to import it as a PLACEHOLDER you replace before release.")
    # Whole words in order, not substrings: "MIT" must not match "perMITted", nor "MPL" "siMPLe"
    tokens = re.findall(r"[A-Z0-9.]+", text.upper())
    for allowed in ALLOWED:
        want = re.findall(r"[A-Z0-9.]+", allowed)
        if any(tokens[i:i + len(want)] == want for i in range(len(tokens) - len(want) + 1)):
            return "ok"
    if placeholder:
        return "placeholder"
    raise FetchError(f"license '{text}' is not one this tool recognises (CC0, CC BY, OFL, MIT, ...). "
                     "Check it by hand, then pass the plain name, or --placeholder.")


def redact_url(url):
    """url as it may be written down: no user:password@, no query string, no fragment (signed links put keys there)."""
    parts = urllib.parse.urlsplit(url)
    netloc = parts.netloc.rpartition("@")[2]
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def redact_page(page):
    """--page as it may be written down: no user:password@, query string and fragment kept (a license page may need
    them to show the right license). Everything else stays exactly as typed, text that is not a URL included."""
    return URL_LOGIN.sub(r"\1", page or "")


def download(url, cache):
    """Fetch url into cache/<file name> (reused if present). Returns the path."""
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name or "download"
    # One folder per URL: two packs both called pack.zip must not share a cache entry, and the file keeps its own
    # name (a single-file asset is picked with --take <its name>)
    cache = cache / hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    dest = cache / name
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"[info] using cached {dest.as_posix()}")
        return dest
    cache.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                tmp = dest.with_name(dest.name + ".part")
                with open(tmp, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
            tmp.replace(dest)
            print(f"[ OK ] downloaded {dest.name} ({dest.stat().st_size // 1024} KB)")
            return dest
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(2 * attempt)
    raise FetchError(f"download failed after {RETRIES} tries: {redact_url(url)} ({last})")


def unsafe_entry(name):
    """Why a zip entry name is unsafe to extract or pick, or '' when it is fine. Backslashes count as separators
    (Windows extraction treats them as such), so "a\\..\\x" and "\\x" are caught too."""
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        return "absolute path"
    if re.match(r"^[A-Za-z]:", norm):
        return "drive letter"
    if ".." in norm.split("/"):
        return "'..' part"
    return ""


def unpack(archive, cache):
    """Extract a zip next to it (once). Returns the folder to pick files from. Non-zips: their own folder."""
    if not zipfile.is_zipfile(archive):
        return archive.parent, [archive.name]
    root = cache / (archive.stem + "_files")
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        for n in names:
            # zipfile drops ".." while extracting, so "x/../../a" would land at "a" while --base keeps the "..":
            # refuse the pack before anything is written instead of trying to line the two up
            why = unsafe_entry(n)
            if why:
                raise UsageError(f"zip entry has an unsafe path ({why}), refusing the pack: {n!r}")
            target = (root / n).resolve()
            if root.resolve() not in target.parents:
                raise FetchError(f"zip entry escapes the cache folder, refusing the pack: {n}")
        if not root.is_dir():
            # names Windows cannot store would crash the extract there; they are refused at --take anyway
            zf.extractall(root, members=[n for n in names if not windows_unsafe(n)])
    return root, sorted(names)


def find_license_text(root, files, explicit):
    """Text of the pack's license file (explicit name first, else the first likely one), or ''."""
    candidates = [explicit] if explicit else []
    for glob in LICENSE_FILE_GLOBS:   # in priority order: License.txt beats Credits.txt
        candidates += [f for f in files if fnmatch.fnmatch(Path(f).name.lower(), glob)
                       and Path(f).suffix.lower() in LICENSE_TEXT_SUFFIXES and f not in candidates]
    for rel in candidates:
        p = root / rel
        if p.is_file():
            return rel, p.read_text(encoding="utf-8", errors="replace")
    return "", ""


def next_asset_id(log_text):
    ids = [int(m) for m in ROW_ID.findall(log_text)]
    template_only = EMPTY_TEMPLATE_ROW.search(log_text) is not None
    if template_only:
        return 1, True
    return (max(ids) + 1 if ids else 1), False


def md_cell(text):
    return text.replace("|", "\\|").replace("\n", " ").strip()


def windows_unsafe(name):
    """True for a zip entry Windows cannot create: a forbidden character, a device name (CON, nul.txt, COM1)
    as any folder or file, or a folder or file name ending in a space or a dot."""
    if WINDOWS_BAD_CHARS.search(name):
        return True
    for part in name.replace("\\", "/").split("/"):
        if part and (part.split(".")[0].strip().lower() in WINDOWS_DEVICES or part[-1] in " ."):
            return True
    return False


def add_log_row(log_text, row, fill_template):
    """ASSET_LOG text with the row added: in place of the empty template row, or after the last row.
    Also used by tools/audio/eleven_audio.py."""
    if fill_template:
        return EMPTY_TEMPLATE_ROW.sub(lambda _m: row, log_text, count=1)
    lines = log_text.split("\n")
    rows = [i for i, l in enumerate(lines) if ROW_ID.match(l)]
    if rows:
        at = rows[-1] + 1
    else:   # header and separator only (the sample row was deleted): first row goes under the separator
        seps = [i for i, l in enumerate(lines) if re.match(r"^\|\s*:?-{3,}", l)]
        if not seps:
            raise UsageError(f"{ASSET_LOG.as_posix()} has no table to add a row to (restore its header from the kit)")
        at = seps[0] + 1
    lines.insert(at, row)
    return "\n".join(lines)


def run(args):
    status = judge_license(args.license, args.placeholder) if not args.list else "ok"
    root_dir = Path(args.root).resolve()
    log_path = root_dir / ASSET_LOG
    # checked before downloading: a wrong --root is a usage problem and should not cost a download
    if not args.list and not log_path.is_file():
        raise UsageError(f"{ASSET_LOG.as_posix()} not found under {root_dir}: run from the project root (or pass --root)")
    cache = root_dir / CACHE_DIR
    archive = download(args.url, cache)
    pack_root, files = unpack(archive, cache)
    if args.list:
        for f in files:
            print(f"  {f}")
        print(f"{len(files)} file(s). Pick with --take \"<path or glob>\".")
        return 0

    if args.license_file and args.license_file not in files:
        raise UsageError(f"--license-file {args.license_file!r} is not in the pack (run with --list for its entries)")
    taken = []
    for pattern in args.take:
        matches = [f for f in files if fnmatch.fnmatch(f, pattern)]
        if not matches:
            raise FetchError(f"--take '{pattern}' matches nothing in the pack (run with --list)")
        taken += [m for m in matches if m not in taken]
    bad = [f for f in taken if windows_unsafe(f)]
    if bad:
        raise FetchError("picked file names Windows cannot store (<>:\"|?*, control characters, device names such as "
                         "CON or NUL, or a trailing space or dot): " + ", ".join(repr(f) for f in bad))
    to_dir = (root_dir / args.to).resolve()
    if root_dir not in to_dir.parents:
        raise UsageError(f"--to {args.to!r} is not a folder inside the project ({root_dir})")
    def dest(f):
        if not args.base:
            target = to_dir / Path(f).name
        else:
            base = args.base.strip("/") + "/"
            if not f.startswith(base):
                raise FetchError(f"{f} is not inside --base {args.base!r}")
            target = to_dir / f[len(base):]
        # second line of defence behind unsafe_entry(): whatever the name, the copy stays inside --to
        if to_dir not in target.resolve().parents:
            raise FetchError(f"{f} would land outside --to {args.to!r}, refusing")
        return target
    plans = [(pack_root / f, dest(f)) for f in taken]
    clashes = [d for _, d in plans if d.exists()]
    names = [d.relative_to(to_dir).as_posix() for _, d in plans]
    if clashes:
        raise FetchError("already in the project, not overwriting: " + ", ".join(d.relative_to(root_dir).as_posix() for d in clashes))
    # casefold: on Windows and macOS A.png and a.png are one file, the second copy would overwrite the first
    if len({n.casefold() for n in names}) != len(names):
        raise FetchError("two picked files share a name (ignoring case); pick fewer or fetch them into different --to folders")

    log_text = log_path.read_text(encoding="utf-8")
    if not log_text.strip():
        raise UsageError(f"{ASSET_LOG.as_posix()} is empty (restore it from the kit)")
    num, fill_template = next_asset_id(log_text)
    asset_id = f"A-{num:04d}"
    today = datetime.date.today().isoformat()
    lic_rel, lic_text = find_license_text(pack_root, files, args.license_file)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    page = redact_page(args.page)
    evidence = (f"{asset_id}  {args.type}  fetched {today} with tools/fetch_asset.py\n"
                f"Download : {redact_url(args.url)}\nPage     : {page}\nAuthor   : {args.author}\nLicense  : {args.license}\n"
                f"SHA-256  : {sha}\nFiles    : {', '.join(taken)}\n\n"
                + (f"---- {lic_rel} (from the pack) ----\n{lic_text}" if lic_text else
                   "No license file in the pack: the license above was read on the asset page. Save a screenshot too.\n"))
    # names come from the pack: escape them so a "|" or a newline cannot break the table, a backtick the code span
    def code(text):
        return "`" + md_cell(text).replace("`", "'") + "`"
    rel_files = ", ".join(code((Path(args.to) / n).as_posix()) for n in names) if len(names) <= 3 else \
        f"{code(Path(args.to).as_posix() + '/')} ({len(names)} files)"
    notes = "; ".join(x for x in ["PLACEHOLDER" if status == "placeholder" else "", args.notes] if x)
    row = (f"| {asset_id} | {md_cell(args.type)} | {rel_files} | {md_cell(page or redact_url(args.url))} | {md_cell(args.author)} | "
           f"{md_cell(args.license)} | {md_cell(args.attribution)} | {args.ai} | {args.modified} | {today} | {md_cell(notes)} |")

    if args.dry_run:
        print(f"[dry-run] would copy {len(plans)} file(s) to {Path(args.to).as_posix()}, write "
              f"{(LICENSE_DIR / (asset_id + '.txt')).as_posix()} and add:\n{row}")
        return 0
    # Work out the new log first: if it cannot be written, nothing in the project has changed yet
    log_text = add_log_row(log_text, row, fill_template)
    to_dir.mkdir(parents=True, exist_ok=True)
    for src, dst in plans:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    (root_dir / LICENSE_DIR).mkdir(parents=True, exist_ok=True)
    (root_dir / LICENSE_DIR / f"{asset_id}.txt").write_text(evidence, encoding="utf-8", newline="\n")
    log_path.write_text(log_text, encoding="utf-8", newline="\n")
    print(f"[ OK ] {asset_id}: {len(plans)} file(s) into {Path(args.to).as_posix()}, license evidence in "
          f"{(LICENSE_DIR / (asset_id + '.txt')).as_posix()}, row added to {ASSET_LOG.as_posix()}")
    if status == "placeholder":
        print("[warn] logged as PLACEHOLDER: replace it before release (/release-check will flag it)")
    if not lic_text:
        print("[warn] the pack has no license file: save the asset page's license as a screenshot next to the evidence")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="Download an asset pack, copy picked files into the project, "
                                             "and log it in docs/ASSET_LOG.md with license evidence (SOP-04).")
    ap.add_argument("--url", required=True, help="direct download URL (zip or single file)")
    ap.add_argument("--list", action="store_true", help="only list the pack's files")
    ap.add_argument("--page", default="", help="the asset's own page, where you read the license")
    ap.add_argument("--author", default="", help="creator name as the license asks")
    ap.add_argument("--license", default="", help="license as read on the page: CC0, CC BY 4.0, OFL, ...")
    ap.add_argument("--attribution", default="", help="credit text the license requires (empty for CC0)")
    ap.add_argument("--type", choices=TYPES, default="other", help="asset type for the log")
    ap.add_argument("--take", action="append", default=[], help="file or glob inside the pack to copy (repeatable)")
    ap.add_argument("--base", default="", help="keep sub-paths relative to this folder inside the pack (default: copy flat)")
    ap.add_argument("--to", default="", help="project folder for the picked files, e.g. assets/audio/sfx")
    ap.add_argument("--license-file", default="", help="path of the license file inside the pack (default: auto-detect)")
    ap.add_argument("--ai", choices=("no", "dev-only", "pre-generated", "live"), default="no", help="AI-assisted? (SOP-04)")
    ap.add_argument("--modified", choices=("no", "yes"), default="no", help="did you change the files?")
    ap.add_argument("--notes", default="", help="free text for the Notes column")
    ap.add_argument("--placeholder", action="store_true", help="allow NC/unknown licenses, logged as PLACEHOLDER")
    ap.add_argument("--root", default=".", help="project root (default: current folder)")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing in the project")
    ap.add_argument("--debug", action="store_true", help="print a traceback on unexpected errors")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if not args.list:
        missing = [f for f in ("license", "take", "to") if not getattr(args, f)]
        if missing:
            print(f"[error] missing --{', --'.join(missing)} (or use --list to see the pack first)", file=sys.stderr)
            return 2
        if not args.page:
            print("[warn] no --page: the log will point at the download URL, not the license page")
    try:
        return run(args)
    except UsageError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except FetchError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - last-resort message, traceback only with --debug
        if args.debug:
            traceback.print_exc()
        print("[error] unexpected failure (rerun with --debug for details)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
