#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# fcore.py
# Purpose : Dotwork's foundation: settings (config.example.json, the game's dotwork.config.json, environment), the
#           paths Dotwork writes to inside a game project, errors and exit codes, the log, the asset manifest,
#           metadata-free PNG saving, a cross-platform free-RAM check, and starting / stopping a ComfyUI that
#           Dotwork launched itself.
# Usage   : imported by dotwork.py and every lane (not run directly)
# Notes   : Settings, lowest to highest priority: config.example.json (next to this file) -> the game's
#           art_src/dotwork/dotwork.config.json (or --config) -> environment: COMFYUI_URL, COMFYUI_ROOT, COMFYUI_PYTHON,
#           SPRITEKILN_ROOT, GODOT_BIN, ASEPRITE_BIN, DOTWORK_WORK.
#           Output goes into the game: <assets_dir>/art/... (shipped), <src_dir>/... (editable sources),
#           <work_dir>/ (caches, ComfyUI downloads, log; keep it gitignored).
#           ComfyUI is reached over HTTP only (127.0.0.1 unless comfyui.allow_remote); Dotwork never writes into
#           ComfyUI's folders. If COMFYUI_ROOT is set and no server answers, Dotwork starts one on 127.0.0.1 and stops
#           it when done; a server it did not start is never stopped.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import ctypes
import datetime
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEBUG = False
ENV_KEYS = {"COMFYUI_URL": ("comfyui", "url"), "COMFYUI_ROOT": ("comfyui", "root"),
            "COMFYUI_PYTHON": ("comfyui", "python"), "SPRITEKILN_ROOT": ("spritekiln_root",),
            "GODOT_BIN": ("godot_bin",), "ASEPRITE_BIN": ("aseprite_bin",), "DOTWORK_WORK": ("project", "work_dir")}


class ToolError(Exception):
    """Exit 2: environment or usage (missing setup, bad spec, server not running). The message says how to fix it."""


class JobError(Exception):
    """Exit 1: the task itself failed (ComfyUI ran a job and it failed, a lane could not produce its asset)."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def utf8_stdio():
    """UTF-8 out on every console; line-buffered like the kit's scripts, so an [error] on stderr cannot overtake the
    [ OK ] lines before it when both are piped."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass


# ---- settings ---------------------------------------------------------------------
def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ToolError(f"{what} {path} not found")
    except ValueError as exc:
        raise ToolError(f"{what} {path} is not valid JSON: {exc}")


class Settings:
    """Everything a lane needs to know about this machine and this game. `conf` is the merged dict; the old
    `conf["fixed"]` view the lanes read is rebuilt from it so lane code stays small."""

    def __init__(self, project=".", config=None, engine=None, spec=None):
        self.project = os.path.abspath(project)
        base = _read_json(os.path.join(HERE, "config.example.json"), "Dotwork default config")
        user_path = config or os.path.join(self.project, base["project"]["work_dir"], "dotwork.config.json")
        if os.path.exists(user_path):
            base = _merge(base, _read_json(user_path, "Dotwork config"))
        elif config:
            raise ToolError(f"--config {config} not found")
        for env, keys in ENV_KEYS.items():
            v = os.environ.get(env, "").strip()
            if v:
                d = base
                for k in keys[:-1]:
                    d = d.setdefault(k, {})
                d[keys[-1]] = v
        if spec and "design" in spec:
            base["design"] = _merge(base["design"], spec["design"])
        if engine:
            base["engine"] = engine
        if base["engine"] not in ("godot", "none"):
            raise ToolError(f"engine {base['engine']!r}: Dotwork writes Godot 4 resources ('godot') or plain sheets ('none')")
        if base["design"].get("tile_px", 32) not in (16, 32, 64):   # ground/tile textures are cut from 128 px tiles
            raise ToolError(f"design.tile_px {base['design'].get('tile_px')!r}: use 16, 32 or 64")
        self.conf = base
        p = base["project"]
        norm = os.path.normpath   # config paths use "/" ("public/assets"); keep one separator style per OS
        self.assets = norm(os.path.join(self.project, p["assets_dir"]))
        self.src = norm(os.path.join(self.project, p["src_dir"]))
        self.work = norm(p["work_dir"] if os.path.isabs(p["work_dir"]) else os.path.join(self.project, p["work_dir"]))
        base["fixed"] = {
            "engine": base["engine"], "art_dir": p.get("art_dir", "art"), "res_root": p["res_root"],
            "src_dir": p["src_dir"], "assets_dir": p["assets_dir"],
            "palette": self.palette_path(base.get("palette"), "dotwork_default.hex"),
            "env_palette": self.palette_path(base.get("env_palette"), "dotwork_default_env.hex"),
            "godot_bin": base.get("godot_bin"), "aseprite_bin": base.get("aseprite_bin")}
        global LOG_PATH
        LOG_PATH = os.path.join(self.work, "dotwork.log")

    def palette_path(self, value, default_name):
        if not value:
            return os.path.join(HERE, "palettes", default_name)
        path = value if os.path.isabs(value) else os.path.join(self.project, value)
        if not os.path.exists(path):
            raise ToolError(f"palette {path} not found (config 'palette' / 'env_palette'; `dotwork.py palette` builds one "
                            "from your own art)")
        return path

    def godot(self):
        """True when Godot resources (.tres / .tscn) should be written."""
        return self.conf["engine"] == "godot"

    def is_game(self):
        """A game folder: project.godot, or for --engine none a kit game's .game-kit.json / CLAUDE.md."""
        marks = ["project.godot"] + ([] if self.godot() else [".game-kit.json", "CLAUDE.md"])
        return any(os.path.exists(os.path.join(self.project, m)) for m in marks)

    def require_game(self):
        """Commands that write into the game refuse a folder that is not one. Run from the game's tools/ by mistake, a
        pack used to write ~100 files into tools/assets* and exit 0 (2026-10-30 stranger run-through)."""
        if not self.is_game():
            want = "project.godot" if self.godot() else "project.godot, .game-kit.json or CLAUDE.md"
            raise ToolError(f"{self.project} is not a game folder (no {want}): run Dotwork from the game's root folder "
                            "or pass --project GAME")

    def ensure_work(self):
        """Create the work folder with its .gitignore / .gdignore, on the first command that writes into the game;
        setup --check, config and palette never create it."""
        os.makedirs(self.work, exist_ok=True)
        ignore_work(self.work)


# ---- paths --------------------------------------------------------------------------
def art(conf, *parts):
    """<project>/<assets_dir>/<art_dir>/... (what ships)."""
    return os.path.normpath(os.path.join(PROJECT, conf["fixed"]["assets_dir"], conf["fixed"]["art_dir"], *parts))


def asset(conf, *parts):
    """<project>/<assets_dir>/... (maps and other non-art game files)."""
    return os.path.normpath(os.path.join(PROJECT, conf["fixed"]["assets_dir"], *parts))


TRUSTED = set()   # absolute paths the user typed on the command line (theirs to choose); spec paths stay inside


def _within(full, root):
    try:
        root = os.path.normcase(root)
        return os.path.commonpath([os.path.normcase(full), root]) == root
    except ValueError:   # another drive
        return False


def contained(p, *roots, what="path"):
    """p resolved against roots[0], refusing anything that ends up outside every root. Spec files can come from anyone
    (a teammate, a PR, the internet), so "source": "../../.ssh/id_rsa" must not read outside the game, and a
    \\\\host\\share path must never be opened: Windows would connect out and send the user's NTLM hash
    (2026-10-30 security audit). Symlinks are resolved before the check."""
    s = str(p)
    if os.path.isabs(s) and os.path.normpath(s) in TRUSTED:
        return os.path.normpath(s)
    if s.startswith(("\\\\", "//")):
        raise ToolError(f"{what} {s!r}: network paths are refused")
    if os.path.isabs(s):
        raise ToolError(f"{what} {s!r}: use a path relative to the game folder (specs may not name absolute paths; "
                        "pass one on the command line instead)")
    full = os.path.normpath(os.path.join(roots[0], s))
    if not (any(_within(full, r) for r in roots)
            and any(_within(os.path.realpath(full), os.path.realpath(r)) for r in roots)):
        raise ToolError(f"{what} {s!r} points outside the game folder")
    return full


def project_path(p):
    """A path from a spec ("source": "assets_src/concept/tower.png"): relative to the game, not to the folder Dotwork was
    started from (--project), and never outside it."""
    return contained(p, PROJECT, what="spec path")


def source_path(p):
    """project_path for an input image that must already exist (character / tools / img2px "source")."""
    full = project_path(p)
    if not os.path.isfile(full):
        raise ToolError(f"source image {p!r} not found (paths in a spec are relative to the game folder)")
    return full


def src(conf, *parts):
    """<project>/<src_dir>/... (editable sources, previews, review sheets)."""
    return os.path.normpath(os.path.join(PROJECT, conf["fixed"]["src_dir"], *parts))


def res(conf, *parts):
    """res:// path of an art file (Godot)."""
    return "/".join([conf["fixed"]["res_root"].rstrip("/"), conf["fixed"]["art_dir"], *parts])


def ignore_work(path):
    """The work folder ignores itself in git (art_src/ is tracked in kit games): caches, ComfyUI downloads and the log
    stay out of commits, the user's dotwork.config.json stays in. Never overwrites an existing .gitignore.
    It also holds an empty .gdignore so Godot never imports it: ComfyUI's raw animated .webp clips cannot be loaded by
    Godot and failed verify with import errors (2026-10-29, effects and character examples). Godot still runs Dotwork's
    scripts from here by res:// path; .gdignore only stops the editor scan and import."""
    gi = os.path.join(path, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Dotwork work folder: regenerated caches, renders fetched from ComfyUI, the log. Only your config is tracked.\n"
                    "*\n!.gitignore\n!dotwork.config.json\n")
    gd = os.path.join(path, ".gdignore")
    if not os.path.exists(gd):
        open(gd, "w").close()


def work(*parts):
    p = os.path.join(WORK, *parts)
    os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
    return p


PROJECT = os.getcwd()
WORK = os.path.join(PROJECT, "art_src", "dotwork")
LOG_PATH = os.path.join(WORK, "dotwork.log")


SETTINGS = None


def bind(settings):
    """Point the module-level paths at one game project (dotwork.py calls this once per run, before any lane is
    imported, so lane-level paths such as COMFY_WORK resolve inside this game's work folder)."""
    global PROJECT, WORK, LOG_PATH, SETTINGS
    SETTINGS = settings
    PROJECT, WORK = settings.project, settings.work
    LOG_PATH = os.path.join(WORK, "dotwork.log")


# ---- log, names, files --------------------------------------------------------------
def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    if not LOG_PATH or not os.path.isdir(os.path.dirname(LOG_PATH)):
        return   # no work folder (setup --check, config): the console is the log
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def snake(name):
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name)).strip("_").lower()
    if not s:
        raise ToolError(f"name {name!r} has no letters or digits")
    return s


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(s):
    """Stable short key for cache file names (Python's hash() is salted per process)."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def key(*parts):
    """10-hex cache key over everything that shapes a render (prompt, seed, size, palette...): a changed spec entry
    gets a new cache file, an unchanged one is reused."""
    return sha256_text("|".join(str(p) for p in parts))[:10]


def seed_of(e, base):
    """An entry's seed: its own "seed", else base + a number from its name. Adding, removing or reordering entries never
    changes (and re-renders) the others, as list-position defaults did (2026-10-30 audit)."""
    if e.get("seed") is not None:
        return int(e["seed"])
    return base + int(key(snake(str(e.get("name", "")))), 16) % 1000


def palette_key(path):
    """Cache-key part for a palette: its content, so editing the .hex re-snaps what used it."""
    return sha256_file(path)[:8] if path and os.path.exists(path) else "none"


def save_clean(img, path):
    """PNG with no text chunks: PIL writes none unless pnginfo is passed, so ComfyUI metadata never ships."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, format="PNG", optimize=True)
    return path


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


# ---- manifest -----------------------------------------------------------------------
class Manifest:
    """One row per shipped file (SHA-256, kind, prompt, seed, routes, models), in <src_dir>/dotwork/manifest.json.
    `dotwork.py log` turns rows into docs/ASSET_LOG.md entries; rows survive re-runs (keyed by file)."""

    def __init__(self, settings, name):
        self.s, self.name = settings, name
        self.path = os.path.join(settings.src, "dotwork", f"manifest_{snake(name)}.json")
        self.data = {"pack": name, "tool": "dotwork", "assets": [], "assumptions": []}
        if os.path.exists(self.path):
            self.data = _read_json(self.path, "manifest")
        self.data["updated"] = datetime.date.today().isoformat()

    def _rel(self, path):
        return os.path.relpath(path, self.s.project).replace(os.sep, "/")

    def current(self, path, request):
        """True when `path` exists and its manifest row was made from `request` (fcore.key of the inputs)."""
        if not os.path.exists(path):
            return False
        rel = self._rel(path)
        return any(a["file"] == rel and a.get("request") == request for a in self.data["assets"])

    def add(self, path, kind, routes=(), **meta):
        """One manifest row. routes names the model routes that made the file (("klein",), ("klein", "wan")); the
        default is none, because Godot resources and code-drawn art carry no model and the asset log must not claim
        one (2026-10-30 audit: model-free font and window rows were logged with four klein models)."""
        if path is None:   # --engine none: a Godot resource that was not written
            return None
        rel = self._rel(path)
        row = {"file": rel, "kind": kind, "sha256": sha256_file(path), "date": datetime.date.today().isoformat(),
               "models": [m for r in routes for m in MODELS.get(r, [])]}
        row.update({k: v for k, v in meta.items() if v is not None})
        self.data["assets"] = [a for a in self.data["assets"] if a["file"] != rel] + [row]
        self.save()
        return row

    def assume(self, text):
        if text not in self.data["assumptions"]:
            self.data["assumptions"].append(text)

    GODOT_EXT = (".tres", ".tscn", ".gdshader", ".gd")

    def drop_engine_rows(self):
        """--engine none: Godot resources left from an earlier --engine godot run of this pack are not part of this
        run's output, and the asset log counted them (49 files instead of 43, 2026-10-30). Returns how many rows went;
        the files stay on disk."""
        if self.s.godot():
            return 0
        keep = [a for a in self.data["assets"] if not a["file"].endswith(self.GODOT_EXT)]
        n, self.data["assets"] = len(self.data["assets"]) - len(keep), keep
        if n:
            print(f"[info] {n} Godot files from an earlier --engine godot run of this pack left the manifest "
                  "(they are still on disk; delete them if this game is not Godot)")
        return n

    def drop_dir(self, dir_abs):
        """Forget rows under dir_abs and delete that folder (clean re-export: no stale frames or rows)."""
        import shutil
        rel = self._rel(dir_abs).rstrip("/") + "/"
        self.data["assets"] = [a for a in self.data["assets"] if not a["file"].startswith(rel)]
        if os.path.commonpath([os.path.abspath(dir_abs), self.s.project]) == self.s.project:
            shutil.rmtree(dir_abs, ignore_errors=True)   # never outside the game project
        self.save()

    def save(self):
        write_text(self.path, json.dumps(self.data, indent=1, ensure_ascii=False))


# model files each route uses (names as in models.lock.json); filled from the lock at import
MODELS = {}


def load_lock():
    lock = _read_json(os.path.join(HERE, "models.lock.json"), "model lock")
    MODELS.clear()
    for m in lock["models"]:
        for r in m.get("routes", []):
            MODELS.setdefault(r, []).append(m["file"])
    return lock


# ---- machine --------------------------------------------------------------------------
def free_ram_gb():
    """Free physical RAM in GB; -1 when the probe failed this time (often because memory is short: treat as a
    warning sign, not as plenty); None on an OS Dotwork has no probe for (Windows, Linux, macOS are covered)."""
    try:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):   # 0 = the call failed
                return -1.0
            return round(st.ullAvailPhys / 1024 ** 3, 1)
        if platform.system() == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                info = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
            return round(info.get("MemAvailable", info.get("MemFree", 0)) / 1024 ** 2, 1)
        if platform.system() == "Darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
            page = 4096
            m = re.search(r"page size of (\d+)", out)
            if m:
                page = int(m.group(1))
            free = sum(int(re.search(rf"{k}:\s+(\d+)", out).group(1)) for k in ("Pages free", "Pages inactive"))
            return round(free * page / 1024 ** 3, 1)
        return None
    except Exception as exc:  # noqa: BLE001  (a failed probe is reported as -1, require_ram decides)
        dbg(f"free RAM probe failed: {exc!r}")
    return -1.0


def require_ram(gb=None, wait=90, probe=None):
    """Refuse to start a heavy job below `gb` free (instead of being killed mid-run, or taking the machine down with
    it). ComfyUI frees models asynchronously, so poll up to `wait` seconds first. A failed probe (-1) is not "plenty":
    it is polled like a low reading, and a run that never gets a reading refuses. probe: injectable for tests."""
    probe = probe or free_ram_gb
    gb = gb if gb is not None else float(SETTINGS.conf.get("min_free_ram_gb", 18))
    t0 = time.time()
    f = probe()
    if f is None:
        log("free RAM cannot be measured on this OS: the RAM check is skipped")
        return
    while f < gb and time.time() - t0 < wait:
        time.sleep(5)
        f = probe()
    if f < 0:
        raise JobError(f"free RAM could not be read for {wait} s (the system may be out of memory); close heavy apps "
                       "and re-run (Dotwork resumes from its cache)")
    if f < gb:
        raise JobError(f"only {f} GB RAM free after {wait} s (this step needs about {gb} GB); close heavy apps and "
                       "re-run (Dotwork resumes from its cache)")


# ---- ComfyUI process (only one Dotwork started) -----------------------------------------
_PROC = None
_PROC_LOG = None


def comfy_url(conf):
    return (conf["comfyui"].get("url") or "http://127.0.0.1:8188").rstrip("/")


def comfy_alive(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + "/system_stats", timeout=3):
            return True
    except Exception:  # noqa: BLE001
        return False


def ensure_comfy(conf=None):
    """Server up? If not and COMFYUI_ROOT is known, start it on 127.0.0.1 (and remember to stop it)."""
    global _PROC, _PROC_LOG
    conf = conf or SETTINGS.conf
    url = comfy_url(conf)
    if comfy_alive(url):
        return url
    root = conf["comfyui"].get("root")
    if not root:
        raise ToolError(f"no ComfyUI answering at {url}. Start ComfyUI yourself, or set COMFYUI_ROOT so Dotwork can "
                        "start it (README: Setup)")
    main_py = os.path.join(root, "main.py")
    if not os.path.exists(main_py):
        raise ToolError(f"COMFYUI_ROOT={root} has no main.py")
    py = conf["comfyui"].get("python") or next(
        (p for p in (os.path.join(root, ".venv", "Scripts", "python.exe"), os.path.join(root, ".venv", "bin", "python"),
                     os.path.join(root, "venv", "Scripts", "python.exe"), os.path.join(root, "venv", "bin", "python"))
         if os.path.exists(p)), sys.executable)
    port = url.rsplit(":", 1)[-1].split("/")[0] if url.count(":") >= 2 else "8188"
    log(f"starting ComfyUI ({py}, 127.0.0.1:{port})")
    # the work folder exists once a command writes into the game; setup --check never creates it, so its server log
    # goes to the system temp folder
    if os.path.isdir(WORK):
        proc_log = os.path.join(WORK, "comfyui.log")
    else:   # a fresh, unpredictable temp file: a fixed name in the shared temp folder could be a planted symlink
        fd, proc_log = tempfile.mkstemp(prefix="dotwork_comfyui_", suffix=".log")
        os.close(fd)
    _PROC_LOG = open(proc_log, "a", encoding="utf-8", errors="replace")   # closed by stop_comfy
    _PROC = subprocess.Popen([py, main_py, "--listen", "127.0.0.1", "--port", port], cwd=root, stdout=_PROC_LOG,
                             stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < int(conf["comfyui"].get("start_timeout_s", 240)):
        if _PROC.poll() is not None:
            raise ToolError(f"ComfyUI exited while starting (see {proc_log})")
        if comfy_alive(url):
            log(f"ComfyUI up after {time.time() - t0:.0f} s")
            return url
        time.sleep(2)
    raise ToolError("ComfyUI did not answer in time (see comfyui.log); start it yourself and retry")


def stop_comfy():
    """Stop ComfyUI only if this Dotwork run started it."""
    global _PROC, _PROC_LOG
    if _PROC is not None and _PROC.poll() is None:
        _PROC.terminate()
        try:
            _PROC.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _PROC.kill()
        log("ComfyUI stopped (Dotwork started it)")
    _PROC = None
    if _PROC_LOG is not None:
        _PROC_LOG.close()
        _PROC_LOG = None


def free_models():
    import engine
    engine.free_models()


def cfg(spec=None):
    """The bound run's merged settings (spec design overrides applied), for lanes that build helpers."""
    conf = SETTINGS.conf
    if spec and "design" in spec:
        conf = dict(conf, design=_merge(conf["design"], spec["design"]))
    return conf


def _kill_tree(p):
    """Stop a tool and everything it started: the game's tools/dev.py runs Godot as its own child, and killing only
    dev.py left a headless Godot running after a timeout (2026-10-30 audit)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            os.killpg(p.pid, signal.SIGKILL)   # run() started it as its own process group
    except OSError:
        pass
    try:
        p.kill()
    except OSError:
        pass


def run(cmd, cwd=None, timeout=None):
    """(exit code, combined output) of a tool such as Godot or Aseprite. UTF-8 in, errors replaced.
    A timeout or Ctrl+C stops the whole process tree; a timeout is a JobError (exit 1)."""
    dbg("run: " + " ".join(map(str, cmd)))
    extra = {} if os.name == "nt" else {"start_new_session": True}
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace", **extra)
    except FileNotFoundError:
        raise ToolError(f"{cmd[0]} not found (set its path in dotwork.config.json or the environment)")
    try:
        out, err = p.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        _kill_tree(p)
        try:
            p.communicate(timeout=10)   # drain the pipes; a survivor holding them must not hang Dotwork
        except subprocess.TimeoutExpired:
            pass
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise JobError(f"{os.path.basename(str(cmd[0]))} did not finish in {timeout} s (stopped it and anything it "
                       "started)")
    return p.returncode, (out or "") + (err or "")
