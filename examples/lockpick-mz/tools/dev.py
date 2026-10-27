#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# dev.py  (RPG Maker MZ edition: JavaScript plugins, Node tests, headless Chromium smoke)
# Purpose : The ONE command wrapper for this project. Same subcommands on every
#           engine in the Claude Code Game Kit, so humans and Claude never guess flags.
# Usage   : python tools/dev.py <command> [options]
#             setup    npm install + the headless browser; --from <MZ project> copies RPG Maker MZ's own files
#                      into game/ (never over yours) and registers the game's plugins
#             check    syntax of every plugin, the game's plugin annotations against its commands, the
#                      database JSON, and js/plugins.js (registered, ordered, files present)
#             test     unit tests (Node's test runner: tests/**/*.test.js)
#             smoke    boot game/ in headless Chromium; fail on errors (--query, --until, --fail-on,
#                      --screenshot, --record as on the web overlay)
#             build    a web-browser copy of the game in build/web/ (a plain copy: see ENGINE_FLOW "Packaging")
#             run      serve game/ on localhost and open the browser (--editor opens RPG Maker MZ instead)
#             clean    remove build/ (--deep also removes node_modules/)
#             doctor   verify the local environment
# Env     : RPGMZ_EXE  optional, the editor (RPGMZ.exe) for `run --editor` and `doctor`.
# Exit    : 0 ok, 1 task failed, 2 environment/usage problem
# Notes   : The MZ project lives in game/ (open game/game.rmmzproject in the editor), so the editor's Deployment
#           exports the game and nothing else. A project at the root (an adopted one) works too. RPG Maker MZ's own
#           files (core scripts, default assets) come from your MZ install, never from the kit. Python 3.8+,
#           standard library only. Not yet run against a real MZ install: engine-specific steps say (verify).
#
# Pseudocode:
#   find the MZ project (game/ or the root) -> run the command:
#   check: node --check each plugin; parse each own plugin's /*: block, compare @command with registerCommand;
#          json.load every data file (database arrays start with null); read $plugins from js/plugins.js
#   test: node --test over tests/**/*.test.js, parse the TAP totals
#   smoke: node tools/smoke.mjs (serve, Chromium, wait for BOOT_OK)
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- Tunables / constants ----------------------------------------------------
MIN_NODE = (22, 12)
GAME_DIR = "game"                          # where the MZ project lives
OWN_PLUGINS = ("GameCore", "GameMain")     # the game's plugins, in load order (setup registers them)
CORE_FILES = ("index.html", "js/main.js", "js/rmmz_core.js", "js/rmmz_managers.js", "js/rmmz_objects.js",
              "js/rmmz_scenes.js", "js/rmmz_sprites.js", "js/rmmz_windows.js", "data/System.json")
DATABASE = ("Actors", "Animations", "Armors", "Classes", "CommonEvents", "Enemies", "Items", "MapInfos",
            "Skills", "States", "Tilesets", "Troops", "Weapons")   # JSON arrays whose entry 0 is null (ids start at 1)
NOT_COPIED = {"save"}                      # setup --from never copies these top-level folders
NOT_SHIPPED = {"save"}                     # build leaves these out
NOT_SHIPPED_SUFFIX = (".rmmzproject",)
SHIPPED_AT_ROOT = ("index.html", "package.json", "js", "data", "img", "audio", "effects", "fonts", "css", "icon")
SMOKE_FRAMES = 120
BOOT_MARKER = "BOOT_OK"                    # logged by game/js/plugins/GameMain.js
SMOKE_TIMEOUT_S = 240                      # MZ loads its whole database before the title: software WebGL is slow
SMOKE_MIN_FPS = 20
TEST_TIMEOUT_S = 600
INSTALL_TIMEOUT_S = 900
PLAYWRIGHT_CLI = "node_modules/playwright/cli.js"
NO_EXEC = (126, 127)
DEBUG = False


def dbg(msg):
    """Verbose output, only with --debug."""
    if DEBUG:
        print(f"[debug] {msg}")


def run(cmd, capture=False, timeout=None):
    """Run a command in the project root. Returns (returncode, output_or_empty).

    124 = timed out (output so far is returned), 126 = not executable, 127 = not found.
    """
    dbg("run: " + " ".join(str(c) for c in cmd))
    sys.stdout.flush()
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
    except FileNotFoundError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc}", file=sys.stderr)
        return 127, ""
    except OSError as exc:
        print(f"[error] cannot execute {cmd[0]}: {exc.strerror or exc}", file=sys.stderr)
        return 126, ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        proc.kill()
        out, _ = proc.communicate()
        if isinstance(exc, KeyboardInterrupt):
            print("\n".join((out or "").splitlines()[-20:]))
            raise
        return 124, out or ""
    return proc.returncode, (out or "")


def node_problem():
    """Return an error string if node is missing or too old, else None."""
    node = shutil.which("node")
    if not node:
        return "node not found on PATH. Install Node.js 22 LTS or newer from nodejs.org (it includes npm)."
    rc, out = run([node, "--version"], capture=True, timeout=30)
    m = re.match(r"v(\d+)\.(\d+)", out.strip())
    if rc != 0 or not m:
        return f"could not read the node version ({out.strip() or rc})"
    if (int(m.group(1)), int(m.group(2))) < MIN_NODE:
        return f"node {out.strip()} is too old: this project needs {MIN_NODE[0]}.{MIN_NODE[1]} or newer"
    return None


def deps_stale():
    """True when node_modules is missing or older than package.json / package-lock.json."""
    marker = ROOT / "node_modules" / ".package-lock.json"
    if not marker.exists():
        return True
    newest = max((ROOT / f).stat().st_mtime for f in ("package.json", "package-lock.json") if (ROOT / f).exists())
    return marker.stat().st_mtime < newest


def npm_install():
    """npm ci when a lockfile exists, else npm install. Returns 0, 1 or 2."""
    npm = shutil.which("npm")
    if not npm:
        print("[error] npm not found on PATH (it ships with Node.js)", file=sys.stderr)
        return 2
    verb = "ci" if (ROOT / "package-lock.json").exists() else "install"
    print(f"[info] installing dependencies (npm {verb}) ...")
    rc, out = run([npm, verb, "--no-audit", "--no-fund"], capture=True, timeout=INSTALL_TIMEOUT_S)
    if rc != 0:
        print(out[-4000:])
        print(f"[FAIL] npm {verb} failed" + (" (timed out)" if rc == 124 else ""))
        return 2 if rc in NO_EXEC + (124,) else 1
    print(f"[ OK ] dependencies installed (npm {verb})")
    return 0


# ---- The MZ project ------------------------------------------------------------
def game_dir():
    """game/ when it holds (or will hold) the MZ project; the root for an adopted project kept in place."""
    g = ROOT / GAME_DIR
    if any(g.glob("*.rmmzproject")) or (g / "index.html").exists():
        return g
    if any(ROOT.glob("*.rmmzproject")) and (ROOT / "js" / "rmmz_core.js").exists():
        return ROOT
    return g


def missing_core(g):
    """The MZ files a project needs to run, missing from g (empty list: it can run)."""
    return [f for f in CORE_FILES if not (g / f).exists()]


def rel(p):
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


ANNOTATION = re.compile(r"/\*:(?![a-z]{2}\b)(.*?)\*/", re.S)   # the English block (/*:ja is the Japanese one)
REGISTER = re.compile(r"registerCommand\(\s*[^,]+,\s*[\"']([^\"']+)[\"']")


def annotation(text):
    """The plugin's English annotation block as {tag: [values]} plus the ordered @command and @param names."""
    m = ANNOTATION.search(text)
    if not m:
        return None
    tags, commands, params = {}, [], []
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("*").strip()
        t = re.match(r"@(\w+)\s*(.*)$", line)
        if not t:
            continue
        name, value = t.group(1), t.group(2).strip()
        tags.setdefault(name, []).append(value)
        if name == "command":
            commands.append(value)
        elif name == "param":
            params.append(value)
    return {"tags": tags, "commands": commands, "params": params, "body": m.group(1)}


def param_defaults(block):
    """@param name ... @default value pairs of the plugin (top level, before the first @command)."""
    head = block.split("@command", 1)[0]
    out, current = {}, None
    for line in head.splitlines():
        line = line.strip().lstrip("*").strip()
        if line.startswith("@param "):
            current = line[len("@param "):].strip()
            out[current] = ""
        elif line.startswith("@default") and current is not None:
            out[current] = line[len("@default"):].strip()
    return out


PLUGINS_JS = re.compile(r"var\s+\$plugins\s*=\s*(\[.*\])\s*;?\s*$", re.S)


def read_plugins_js(path):
    """The $plugins list from js/plugins.js, or raise ValueError."""
    m = PLUGINS_JS.search(path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError("no `var $plugins = [...]` in it")
    return json.loads(m.group(1))


def write_plugins_js(path, plugins):
    """Write js/plugins.js the way the editor does: one plugin per line. (verify the editor's exact format)"""
    lines = ",\n".join(json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in plugins)
    path.write_text("// Generated by RPG Maker.\n// Do not edit this file directly.\nvar $plugins =\n[\n" + lines + "\n];\n",
                    encoding="utf-8")


def register_own_plugins(g):
    """Add the game's plugins to js/plugins.js (enabled, in OWN_PLUGINS order, after any others). Returns a message."""
    pj = g / "js" / "plugins.js"
    plugins = read_plugins_js(pj) if pj.exists() else []
    names = [p.get("name") for p in plugins]
    added = []
    for name in OWN_PLUGINS:
        if name in names:
            continue
        text = (g / "js" / "plugins" / f"{name}.js").read_text(encoding="utf-8")
        ann = annotation(text) or {"tags": {}, "body": ""}
        desc = (ann["tags"].get("plugindesc") or [""])[0]
        plugins.append({"name": name, "status": True, "description": desc, "parameters": param_defaults(ann["body"])})
        added.append(name)
    if added:
        write_plugins_js(pj, plugins)
        return f"registered {', '.join(added)} in {rel(pj)}"
    return f"{', '.join(OWN_PLUGINS)} already in {rel(pj)}"


# ---- Commands -----------------------------------------------------------------
def cmd_setup(args):
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    g = game_dir()
    if args.source:
        src = Path(args.source).expanduser().resolve()
        if not (any(src.glob("*.rmmzproject")) and (src / "js" / "rmmz_core.js").exists()):
            print(f"[error] {src} is not an RPG Maker MZ project (no *.rmmzproject and js/rmmz_core.js). "
                  "Make one in the editor (File > New Project) and pass its folder.", file=sys.stderr)
            return 2
        if src == g.resolve():
            print("[error] --from is the game folder itself", file=sys.stderr)
            return 2
        copied = kept = 0
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            r = f.relative_to(src)
            if r.parts[0] in NOT_COPIED:
                continue
            dest = g / r
            if dest.exists():
                kept += 1         # yours wins: plugins, data and art you already have stay as they are
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            copied += 1
        print(f"[ OK ] copied {copied} file(s) from {src} into {rel(g)}/ (kept {kept} you already had)")
    if not missing_core(g):
        try:
            print(f"[ OK ] {register_own_plugins(g)}")
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[FAIL] {rel(g)}/js/plugins.js: {exc}")
            return 1
    else:
        print(f"[info] no RPG Maker MZ project in {rel(g)}/ yet: make one in the editor (File > New Project, anywhere), "
              "then run: python tools/dev.py setup --from <that folder>")
    rc = npm_install() if deps_stale() else 0
    if rc:
        return rc
    print("[info] installing the headless Chromium used by `smoke` (Playwright, about 150 MB, once per machine) ...")
    rc, out = run([shutil.which("node") or "node", ROOT / PLAYWRIGHT_CLI, "install", "chromium"], capture=True,
                  timeout=INSTALL_TIMEOUT_S)
    if rc != 0:
        print(out[-3000:])
        print("[FAIL] browser install failed")
        return 2
    print("[ OK ] setup done" + ("" if missing_core(g) else ": open game/game.rmmzproject in RPG Maker MZ, or `python tools/dev.py run`"))
    return 0


def check_plugins(g, problems):
    """node --check every plugin; the game's own plugins also get their annotation checked. Returns the count."""
    node = shutil.which("node") or "node"
    plugin_dir = g / "js" / "plugins"
    files = sorted(plugin_dir.glob("*.js")) if plugin_dir.exists() else []
    for f in files:
        rc, out = run([node, "--check", f], capture=True, timeout=60)
        if rc in NO_EXEC:
            return -1
        if rc != 0:
            problems.append(f"{rel(f)}: syntax error\n{out.strip()}")
    for name in OWN_PLUGINS:
        f = plugin_dir / f"{name}.js"
        if not f.exists():
            problems.append(f"{rel(f)} is missing (one of the game's own plugins)")
            continue
        text = f.read_text(encoding="utf-8")
        ann = annotation(text)
        if ann is None:
            problems.append(f"{rel(f)}: no /*: annotation block (the Plugin Manager would show no name or help)")
            continue
        if (ann["tags"].get("target") or [""])[0] != "MZ":
            problems.append(f"{rel(f)}: missing `@target MZ`")
        if not ann["tags"].get("plugindesc"):
            problems.append(f"{rel(f)}: missing `@plugindesc`")
        registered = REGISTER.findall(text)
        for c in registered:
            if c not in ann["commands"]:
                problems.append(f"{rel(f)}: registerCommand \"{c}\" has no `@command {c}` in the annotation "
                                "(it will not appear in the event editor)")
        for c in ann["commands"]:
            if c not in registered:
                problems.append(f"{rel(f)}: `@command {c}` is never registered (choosing it in an event does nothing)")
    return len(files)


def check_data(g, problems):
    """json.load every data file; database arrays start with null. Returns the count."""
    data = g / "data"
    files = sorted(data.glob("*.json")) if data.exists() else []
    for f in files:
        try:
            value = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"{rel(f)}: not valid JSON ({exc})")
            continue
        if f.stem in DATABASE and not (isinstance(value, list) and value and value[0] is None):
            problems.append(f"{rel(f)}: a database file must be a list starting with null (entry ids start at 1)")
    return len(files)


def check_plugins_js(g, problems):
    """js/plugins.js: readable, the game's plugins registered and enabled in order, every listed file present."""
    pj = g / "js" / "plugins.js"
    if not pj.exists():
        problems.append(f"{rel(pj)} is missing (run `python tools/dev.py setup`)")
        return
    try:
        plugins = read_plugins_js(pj)
    except (ValueError, json.JSONDecodeError) as exc:
        problems.append(f"{rel(pj)}: {exc}")
        return
    names = [p.get("name") for p in plugins]
    for p in plugins:
        if not (g / "js" / "plugins" / f"{p.get('name')}.js").exists():
            problems.append(f"{rel(pj)}: lists {p.get('name')}, but js/plugins/{p.get('name')}.js does not exist")
    for name in OWN_PLUGINS:
        if name not in names:
            problems.append(f"{rel(pj)}: {name} is not registered (run `python tools/dev.py setup`)")
        elif not plugins[names.index(name)].get("status"):
            problems.append(f"{rel(pj)}: {name} is turned off in the Plugin Manager")
    present = [n for n in OWN_PLUGINS if n in names]
    if present != sorted(present, key=names.index):
        problems.append(f"{rel(pj)}: the game's plugins must load in this order: {', '.join(OWN_PLUGINS)}")


def cmd_check(args):
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    g = game_dir()
    problems = []
    n_plugins = check_plugins(g, problems)
    if n_plugins < 0:
        return 2
    n_data = check_data(g, problems)
    project = not missing_core(g)
    if project:
        check_plugins_js(g, problems)
    for p in problems:
        print(f"[FAIL] {p}")
    if problems:
        if g == ROOT and (ROOT / GAME_DIR / "js" / "plugins" / f"{OWN_PLUGINS[0]}.js").exists():
            print(f"[info] the kit put the game's plugins in {GAME_DIR}/js/plugins/ and your MZ project is at the root: "
                  f"move the project into {GAME_DIR}/ (docs/ENGINE_FLOW.md > Adopting an existing project)")
        print(f"[FAIL] check: {len(problems)} problem(s)")
        return 1
    print(f"[ OK ] checked {n_plugins} plugin(s) and {n_data} data file(s)")
    if not project:
        print(f"[WARN] no RPG Maker MZ project in {rel(g)}/ yet (only the game's plugins were checked): "
              "python tools/dev.py setup --from <a new MZ project>")
    return 0


def cmd_test(args):
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    files = sorted((ROOT / "tests").rglob("*.test.js")) if (ROOT / "tests").exists() else []
    if not files:
        print("[FAIL] no tests ran (nothing matches tests/**/*.test.js)")
        return 2
    rc, out = run([shutil.which("node") or "node", "--test", "--test-reporter=tap", *files], capture=True,
                  timeout=TEST_TIMEOUT_S)
    if DEBUG or rc != 0:
        print(out.rstrip())
    if rc in NO_EXEC:
        return 2
    if rc == 124:
        print(f"[FAIL] tests did not finish within {TEST_TIMEOUT_S} s")
        return 1
    passed = re.search(r"^# pass (\d+)", out, re.M)
    failed = re.search(r"^# fail (\d+)", out, re.M)
    if rc != 0 or not passed or (failed and int(failed.group(1))):
        print(f"[FAIL] tests failed ({failed.group(1) if failed else '?'} failed)")
        return 1
    if int(passed.group(1)) == 0:
        print("[FAIL] no tests ran")
        return 2
    print(f"[ OK ] {passed.group(1)} test(s) passed")
    return 0


def need_project():
    """The MZ project to run, or None after printing why (exit 2: setup, not the code)."""
    g = game_dir()
    gone = missing_core(g)
    if gone:
        print(f"[error] no runnable RPG Maker MZ project in {rel(g)}/ (missing {', '.join(gone[:3])}"
              f"{' ...' if len(gone) > 3 else ''}): python tools/dev.py setup --from <a new MZ project>", file=sys.stderr)
        return None
    return g


def cmd_smoke(args):
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    g = need_project()
    if g is None:
        return 2
    if deps_stale():
        rc = npm_install()
        if rc:
            return rc
    cmd = [shutil.which("node") or "node", ROOT / "tools" / "smoke.mjs", "--root", g, "--frames", str(args.frames),
           "--marker", BOOT_MARKER, "--timeout-ms", str(args.timeout * 1000)] + (["--verbose"] if DEBUG else [])
    for flag, value in (("--query", args.query), ("--until", args.until), ("--fail-on", args.fail_on),
                        ("--screenshot", args.screenshot), ("--record", args.record),
                        ("--record-every", str(args.record_every) if args.record else "")):
        if value:
            cmd += [flag, value]
    cmd += ["--headed"] if args.headed else []
    limit = SMOKE_TIMEOUT_S + args.timeout + args.frames // SMOKE_MIN_FPS
    rc, out = run(cmd, capture=True, timeout=limit)
    print(out.rstrip())
    if rc == 124:
        print(f"[FAIL] smoke did not finish within {limit} s")
        return 1
    if rc == 2 or rc in NO_EXEC:
        return 2
    if rc != 0 or "[ OK ]" not in out:
        return 1
    return 0


def cmd_build(args):
    g = need_project()
    if g is None:
        return 2
    out_dir = ROOT / "build" / "web"
    if out_dir.exists():
        why = remove_tree(out_dir)
        if why:
            print(f"[FAIL] build/web/ not replaced: {why}")
            return 1
    count = size = 0
    for f in sorted(p for p in g.rglob("*") if p.is_file()):
        r = f.relative_to(g)
        if r.parts[0] in NOT_SHIPPED or f.name.endswith(NOT_SHIPPED_SUFFIX):
            continue
        if g == ROOT and r.parts[0] not in SHIPPED_AT_ROOT:   # a project kept at the root: leave the kit's files out
            continue
        dest = out_dir / r
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        count += 1
        size += f.stat().st_size
    if not (out_dir / "index.html").exists():
        print("[FAIL] build/web/index.html was not written")
        return 1
    print(f"[ OK ] build/web/: {count} files, {size // 1024} KB. Upload the folder (zip its contents for itch.io).")
    print("[info] a plain copy: for unused-file removal, encryption or desktop builds use the editor's "
          "File > Deployment (docs/ENGINE_FLOW.md > Packaging)")
    return 0


def cmd_run(args):
    if args.editor:
        exe = os.environ.get("RPGMZ_EXE", "")
        if not exe or not Path(exe).is_file():
            print("[error] set RPGMZ_EXE to the editor (e.g. ...\\steamapps\\common\\RPG Maker MZ\\RPGMZ.exe)", file=sys.stderr)
            return 2
        project = next(iter(game_dir().glob("*.rmmzproject")), None)
        if project is None:
            print("[error] no *.rmmzproject in the game folder: run setup --from first", file=sys.stderr)
            return 2
        subprocess.Popen([exe, str(project)], cwd=ROOT)   # (verify: does RPGMZ.exe open a project given on the command line?)
        print(f"[ OK ] opening {rel(project)} in RPG Maker MZ")
        return 0
    err = node_problem()
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return 2
    g = need_project()
    if g is None:
        return 2
    print("[info] serving the game for your browser; Ctrl+C to stop. In the editor, Playtest (Ctrl+R) runs it too.")
    rc, _ = run([shutil.which("node") or "node", ROOT / "tools" / "serve.mjs", "--root", g, "--port", str(args.port),
                 "--open"])
    return 0 if rc in (0, 130) else 1


def remove_tree(path):
    """Delete a folder for real. Returns None on success, else a reason."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return "it is a link/junction; remove the link by hand if that is what you want"
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        left = sum(1 for _ in path.rglob("*"))
        return f"{left} item(s) could not be deleted (close the browser or program holding them)"
    return None


def cmd_clean(args):
    targets = [ROOT / "build"] + ([ROOT / "node_modules"] if args.deep else [])
    failed, removed = 0, []
    for t in targets:
        if not t.exists():
            continue
        why = remove_tree(t)
        if why:
            print(f"[FAIL] {t.relative_to(ROOT).as_posix()}/ not removed: {why}")
            failed += 1
        else:
            removed.append(t.relative_to(ROOT).as_posix() + "/")
    print(f"[ OK ] removed {', '.join(removed)}" if removed else "[info] nothing to clean")
    if args.deep and not failed:
        print("[info] node_modules/ is gone: python tools/dev.py setup reinstalls it")
    return 1 if failed else 0


def cmd_doctor(args):
    problems = 0
    print(f"[info] python {sys.version.split()[0]}")
    err = node_problem()
    if err:
        print(f"[FAIL] node: {err}")
        problems += 1
    else:
        _, out = run([shutil.which("node"), "--version"], capture=True, timeout=30)
        print(f"[ OK ] node {out.strip()}")
    npm = shutil.which("npm")
    print(f"[{' OK ' if npm else 'FAIL'}] npm: {npm or 'not found'}")
    problems += 0 if npm else 1
    g = game_dir()
    gone = missing_core(g)
    if gone:
        print(f"[FAIL] no RPG Maker MZ project in {rel(g)}/ (missing {', '.join(gone[:3])}...): "
              "python tools/dev.py setup --from <a new MZ project>")
        problems += 1
    else:
        print(f"[ OK ] RPG Maker MZ project in {rel(g)}/")
    if not (ROOT / "node_modules").exists():
        print("[FAIL] node_modules/ missing: run `python tools/dev.py setup`")
        problems += 1
    else:
        rc, out = run([shutil.which("node") or "node", "-e",
                       "const p=require('playwright').chromium.executablePath();"
                       "console.log(require('fs').existsSync(p)?'ok '+p:'missing '+p)"], capture=True, timeout=60)
        if out.startswith("ok "):
            print(f"[ OK ] headless Chromium for smoke: {out[3:].strip()}")
        else:
            print("[FAIL] headless Chromium for smoke not installed: run `python tools/dev.py setup`")
            problems += 1
    exe = os.environ.get("RPGMZ_EXE", "")
    if exe:
        ok = Path(exe).is_file()
        print(f"[{' OK ' if ok else 'FAIL'}] RPGMZ_EXE: {exe}{'' if ok else ' (not a file)'}")
        problems += 0 if ok else 1
    else:
        print("[info] RPGMZ_EXE not set (optional: only `run --editor` needs it)")
    doctor = ROOT / "tools" / "doctor.py"
    if doctor.exists():
        rc, _ = run([sys.executable, doctor])
        problems += 1 if rc else 0
    return 1 if problems else 0


def positive_int(text):
    """argparse type: 1..100000, so a typo cannot ask for a smoke run that never ends."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if not 1 <= n <= 100000:
        raise argparse.ArgumentTypeError("must be between 1 and 100000")
    return n


def build_parser():
    ap = argparse.ArgumentParser(
        prog="dev.py",
        description="Project command wrapper (RPG Maker MZ). Same commands on every engine in the Claude Code Game Kit.",
        epilog="Needs Node.js 22.12+ (with npm) and your own RPG Maker MZ (setup --from copies its files into game/). "
               "Env: RPGMZ_EXE (optional, the editor). Exit codes: 0 ok, 1 failed, 2 environment/usage problem.",
    )
    ap.add_argument("--debug", action="store_true", help="verbose output (full tool output, every console line in smoke)")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    sub.required = True
    p = sub.add_parser("setup", help="install dependencies and the headless browser; --from copies MZ's files in")
    p.add_argument("--from", dest="source", default="", help="a new RPG Maker MZ project folder to copy MZ's own files from")
    p.set_defaults(fn=cmd_setup)
    sub.add_parser("check", help="plugin syntax and annotations, database JSON, js/plugins.js").set_defaults(fn=cmd_check)
    sub.add_parser("test", help="unit tests (node --test)").set_defaults(fn=cmd_test)
    p = sub.add_parser("smoke", help="boot the game in headless Chromium for N frames; fail on errors")
    p.add_argument("--frames", type=positive_int, default=SMOKE_FRAMES,
                   help=f"animation frames to run after boot, 1 to 100000 (default {SMOKE_FRAMES})")
    p.add_argument("--query", default="", help="URL query for the page, e.g. autoplay (scenario runs)")
    p.add_argument("--until", default="", help="wait for this console marker instead of --frames")
    p.add_argument("--fail-on", default="", help="comma-separated console markers that fail the run")
    p.add_argument("--timeout", type=positive_int, default=60, help="seconds to wait for each marker (default 60)")
    p.add_argument("--screenshot", default="", help="save a PNG of the final frame (path relative to the project)")
    p.add_argument("--record", default="", help="save PNG frames to this folder (GIF: tools/art/frames_to_gif.py)")
    p.add_argument("--record-every", type=positive_int, default=66, help="milliseconds between recorded frames (default 66)")
    p.add_argument("--headed", action="store_true", help="visible browser window (real GPU)")
    p.set_defaults(fn=cmd_smoke)
    sub.add_parser("build", help="a web-browser copy of the game in build/web/").set_defaults(fn=cmd_build)
    p = sub.add_parser("run", help="serve the game and open your browser (--editor: open RPG Maker MZ)")
    p.add_argument("--port", type=positive_int, default=8080, help="local port (default 8080)")
    p.add_argument("--editor", action="store_true", help="open the project in RPG Maker MZ (needs RPGMZ_EXE)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("clean", help="remove build/")
    p.add_argument("--deep", action="store_true", help="also remove node_modules/ (reinstalled by setup)")
    p.add_argument("--yes", action="store_true", help="accepted on every engine; this clean never asks")
    p.set_defaults(fn=cmd_clean)
    sub.add_parser("doctor", help="verify the local environment").set_defaults(fn=cmd_doctor)
    return ap


def hoist_global_options(parser, argv):
    """
    Let global options sit anywhere: `dev.py build --debug` works like `dev.py --debug build`.
    Pseudocode: collect the top-level option names (and whether they take a value) from the
    parser, then move every occurrence in argv (plus its value) to the front, keeping order.
    Uses argparse's _actions list (stable for years, but private), so failures fall back to argv.
    """
    try:
        takes_value = {}
        for action in parser._actions:
            if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
                continue
            for opt in action.option_strings:
                takes_value[opt] = action.nargs != 0
    except AttributeError:
        return argv
    front, rest, i = [], [], 0
    while i < len(argv):
        tok = argv[i]
        name = tok.split("=", 1)[0]
        if name in takes_value:
            front.append(tok)
            if takes_value[name] and "=" not in tok and i + 1 < len(argv):
                front.append(argv[i + 1])
                i += 1
        else:
            rest.append(tok)
        i += 1
    return front + rest


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(hoist_global_options(parser, argv))
    DEBUG = args.debug
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\n[abort] interrupted")
        return 1
    except OSError as exc:
        where = f" {exc.filename}" if exc.filename else ""
        print(f"[error] {exc.strerror or exc}{where} (close any program holding it and retry)", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2
    except Exception as exc:
        print(f"[error] unexpected failure in '{args.command}': {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
