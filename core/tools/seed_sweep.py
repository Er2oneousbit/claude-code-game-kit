#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# seed_sweep.py
# Purpose : Tune a game with its bots: run `dev.py smoke` many times over seeds and settings (difficulty, bot modes,
#           any game option), in parallel, collect the markers each run prints (RUN_WON, CAUGHT, RACE_OVER ...) and
#           the numbers on those lines (score=120 time=41.5), and print one row per run and the pass rate per
#           setting. Replaces the throwaway loop scripts each game wrote for its bot pairs (#183).
# Usage   : python tools/seed_sweep.py --seeds 1-8 --set bot=skilled,reckless --collect RUN_WON,PLAYER_DESTROYED \
#               -- --frames 30000 --timeout 900 --until RUN_WON -- --autoplay {bot} --seed {seed}
#           python tools/seed_sweep.py --seeds 1-8 --set difficulty=easy,normal,hard --collect ESCAPED,CAUGHT \
#               -- --query "autoplay&seed={seed}&difficulty={difficulty}" --until ESCAPED      # web, web-3d, MZ
#           python tools/seed_sweep.py --spec sweeps/bots.json --jobs 4 --json captures/sweep/bots.json
#           python tools/seed_sweep.py ... --dry-run           # print the runs, run nothing
# Options : --seeds SPEC         seeds for {seed}: 1-8, 1,3,5 or 1-4,10 (none: one run per setting)
#           --set NAME=V1,V2     a setting and its values for {NAME} (repeat for more; every combination runs)
#           --collect M1,M2      markers to look for in each run's output; the first one seen is the run's outcome,
#                                and key=value numbers on their lines become columns
#           --jobs N             runs at the same time (default: half the CPUs, at most 4; Unity and Unreal: 1)
#           --run-timeout S      a run that takes longer is stopped and counted as "timeout" (default 1800)
#           --min-pass RATE      exit 0 when every setting passes at least this share of its runs (0.0 to 1.0);
#                                without it any failed run exits 1
#           --spec FILE.json     the same options from a file (keys: seeds, set, collect, jobs, run_timeout,
#                                min_pass, smoke); the command line wins over the file
#           --json FILE          also write every run and the summary as JSON
#           --out DIR            where each run's output and data folder go (default captures/sweep)
#           --root DIR           the game folder (default: the folder above tools/)
#           everything after the first `--` is passed to `dev.py smoke` (a second `--` there starts the game's own
#           options, as on C++, Bevy and LOVE), with {seed} and {NAME} filled in per run
# Exit    : 0 every run passed (or --min-pass met), 1 a run failed (or a setting is under --min-pass),
#           2 usage or environment problem (bad options, unknown placeholder, the first run could not start)
# Notes   : Standard library only, Python 3.8+. A run passes when `dev.py smoke` exits 0, so its own --until and
#           --fail-on decide; --collect only reads. Runs use `dev.py --debug smoke`, so the game's own lines are in
#           the output. The first run goes alone (it builds); the others follow in parallel with `--no-build` where
#           the engine's smoke has it (web, web-3d, C++), so one build serves every run. Each run gets its own
#           --data-dir (captures/sweep/runs/NNN/data) where smoke takes one, since the default data folder is shared
#           and wiped by every run; Unity and Unreal run one at a time (the editor locks the project). Each run's
#           output is kept in captures/sweep/runs/NNN/smoke.log. A FRAME_TIMES line (#90) adds a p95_ms column.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   options (spec file, then the command line) -> cases = seeds x every combination of the --set values
#   check every {placeholder} in the smoke arguments names a seed or setting
#   smoke -h once: does smoke take --no-build and --data-dir?
#   run case 1 alone (it builds); exit 2 -> stop with exit 2
#   run the rest in a thread pool (--jobs), each `dev.py --debug smoke [--no-build] [--data-dir D] <args filled in>`
#   per run: status from the exit code, outcome = first --collect marker in the output, key=value numbers on the
#     marker lines, p95 from FRAME_TIMES; keep the output in runs/NNN/smoke.log
#   print the run table, then per setting (and per value when there are several settings): runs, pass rate,
#     outcome counts, mean of each number; --json writes the same; exit code from the pass rates
import argparse
import concurrent.futures
import itertools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---- Tunables / constants ------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]     # the game folder (tools/ is inside it)
KIT_FILE = ".game-kit.json"                    # names the engine
SERIAL_ENGINES = ("unity", "unreal")           # the editor locks the project: one run at a time
DEFAULT_JOBS = max(1, min(4, (os.cpu_count() or 2) // 2))
RUN_TIMEOUT_S = 1800                           # one smoke run, build included
HELP_TIMEOUT_S = 120                           # `dev.py smoke -h`
OUT_DIR = "captures/sweep"                     # captures/ is gitignored in every game
MARK_FILE = ".seed_sweep"                      # marks a runs/ folder this tool made (and may clear)
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# key=value on a marker line; a unit glued to the number is dropped (time=40s -> time 40, hp=50% -> hp 50)
NUMBER_PAIR = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=(-?\d+(?:\.\d+)?)(?:[A-Za-z%]+)?(?![\w.])")
FRAME_P95 = re.compile(r"\bFRAME_TIMES\b.*?\bp95=(\d+(?:\.\d+)?)")
STATUS = {0: "pass", 1: "fail", 2: "error", 124: "timeout"}
# Lines dev.py and smoke.mjs print about the run (the command with --until X, "marker X not seen"): never the game's
OWN_LINES = ("[debug]", "[ OK ]", "[FAIL]", "[info]", "[WARN]", "[error]", "[fail-on", "[smoke]", "[seed_sweep]")
KILL_TIMEOUT_S = 10
DEBUG = False


class UsageError(Exception):
    """A problem with the options or the environment: exit 2."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# ---- Options -------------------------------------------------------------------------------------------------
def parse_seeds(text):
    """'1-8', '1,3,5', '1-4,10' -> [1, 2, ...]. Raises UsageError."""
    seeds = []
    for part in str(text).split(","):
        part = part.strip()
        m = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi < lo or hi - lo > 100000:
                raise UsageError(f"--seeds {text!r}: a range must go up, by at most 100000")
            seeds.extend(range(lo, hi + 1))
        elif re.fullmatch(r"-?\d+", part):
            seeds.append(int(part))
        else:
            raise UsageError(f"--seeds {text!r}: use numbers and ranges, e.g. 1-8 or 1,3,5")
    return seeds


def parse_set(text):
    """'bot=skilled,reckless' -> ('bot', ['skilled', 'reckless']). Raises UsageError."""
    name, sep, values = str(text).partition("=")
    name = name.strip()
    if not sep or not NAME_RE.match(name):
        raise UsageError(f"--set {text!r}: use NAME=V1,V2 (NAME is letters, digits and _)")
    if name == "seed":
        raise UsageError("--set seed=...: use --seeds for seeds")
    vals = [v.strip() for v in values.split(",") if v.strip()]
    if not vals:
        raise UsageError(f"--set {text!r}: no values")
    return name, vals


def from_spec(path):
    """The spec file's options as a dict (keys as in the Usage). Raises UsageError."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"--spec {path}: {exc.strerror or exc}")
    except ValueError as exc:
        raise UsageError(f"--spec {path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise UsageError(f"--spec {path}: the file must hold one JSON object")
    known = {"seeds", "set", "collect", "jobs", "run_timeout", "min_pass", "smoke"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise UsageError(f"--spec {path}: unknown key(s) {', '.join(unknown)} (known: {', '.join(sorted(known))})")
    return data


def as_list(value):
    """A comma string or a list -> a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def options(argv):
    """argparse namespace with the spec merged in and the smoke arguments in .smoke. Raises UsageError."""
    if "--" in argv:
        cut = argv.index("--")
        own, smoke = argv[:cut], argv[cut + 1:]
    else:
        own, smoke = argv, None
    args = build_parser().parse_args(own)
    spec = from_spec(args.spec) if args.spec else {}
    seeds = args.seeds if args.seeds is not None else spec.get("seeds")
    if isinstance(seeds, list):
        seeds = ",".join(str(s) for s in seeds)
    args.seed_list = parse_seeds(seeds) if seeds not in (None, "") else []
    sets = [parse_set(s) for s in args.set] if args.set else []
    if not sets and isinstance(spec.get("set"), dict):
        sets = [parse_set(f"{k}={','.join(as_list(v))}") for k, v in spec["set"].items()]
    names = [n for n, _ in sets]
    if len(set(names)) != len(names):
        raise UsageError("a --set name is given twice")
    args.sets = sets
    args.collect_list = as_list(args.collect if args.collect is not None else spec.get("collect"))
    args.jobs = args.jobs if args.jobs is not None else int(spec.get("jobs", DEFAULT_JOBS))
    args.run_timeout = args.run_timeout if args.run_timeout is not None else int(spec.get("run_timeout", RUN_TIMEOUT_S))
    args.min_pass = args.min_pass if args.min_pass is not None else spec.get("min_pass")
    if args.min_pass is not None and not 0.0 <= float(args.min_pass) <= 1.0:
        raise UsageError("--min-pass is a share of runs, 0.0 to 1.0 (0.9 = nine in ten)")
    args.smoke = smoke if smoke is not None else as_list(spec.get("smoke")) if isinstance(spec.get("smoke"), list) else []
    if not 1 <= args.jobs <= 64:
        raise UsageError("--jobs must be 1 to 64")
    if args.run_timeout < 1:
        raise UsageError("--run-timeout must be 1 second or more")
    return args


def cases(seeds, sets):
    """Every run as a dict of placeholder -> value: seeds x each combination of the settings, seed varying fastest
    within a setting, so a setting's runs sit together in the table."""
    names = [n for n, _ in sets]
    out = []
    for combo in itertools.product(*[vals for _, vals in sets]) if sets else [()]:
        for seed in seeds or [None]:
            case = dict(zip(names, combo))
            if seed is not None:
                case = {"seed": str(seed), **case}
            out.append(case)
    return out


def check_placeholders(smoke, keys):
    """Raises UsageError for a {name} that is no seed or setting; returns the settings no argument uses."""
    used = set()
    for arg in smoke:
        for name in PLACEHOLDER.findall(arg):
            if name not in keys:
                hint = "--seeds" if name == "seed" else f"--set {name}=..."
                raise UsageError(f"{{{name}}} in the smoke arguments has no values: add {hint}")
            used.add(name)
    return [k for k in keys if k not in used]


def fill(smoke, case):
    """The smoke arguments with this case's values in place of {name}."""
    return [PLACEHOLDER.sub(lambda m: case.get(m.group(1), m.group(0)), arg) for arg in smoke]


# ---- Running -------------------------------------------------------------------------------------------------
def engine_of(root):
    """The engine id from .game-kit.json ("" when it is missing or unreadable)."""
    try:
        return str(json.loads((Path(root) / KIT_FILE).read_text(encoding="utf-8")).get("engine", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def smoke_options(root):
    """The options this game's `dev.py smoke -h` lists that the sweep uses: {"--no-build": bool, "--data-dir": bool}.
    Raises UsageError when dev.py cannot run."""
    dev = Path(root) / "tools" / "dev.py"
    if not dev.is_file():
        raise UsageError(f"no tools/dev.py in {root}: run this from a game made with the kit (or pass --root)")
    try:
        r = subprocess.run([sys.executable, str(dev), "smoke", "-h"], cwd=str(root), capture_output=True,
                           encoding="utf-8", errors="replace", timeout=HELP_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UsageError(f"cannot run tools/dev.py smoke -h: {exc}")
    if r.returncode != 0:
        raise UsageError("tools/dev.py smoke -h failed:\n  " + "\n  ".join((r.stdout + r.stderr).strip().splitlines()[-5:]))
    return {flag: flag in r.stdout for flag in ("--no-build", "--data-dir")}


def kill_tree(proc):
    """Stop proc and everything it started (the engine, the browser): a timeout must not leave them running."""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           timeout=KILL_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            dbg(f"taskkill: {exc}")
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)       # the run leads its own process group
        except OSError as exc:
            dbg(f"killpg: {exc}")
    try:
        proc.kill()
    except OSError:
        pass


def run_one(root, cmd, timeout):
    """Run one smoke. Returns (exit code, output, seconds); 124 when it ran over timeout."""
    start = time.monotonic()
    dbg("run: " + " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                                start_new_session=sys.platform != "win32")
    except OSError as exc:
        return 2, f"[error] cannot start {cmd[0]}: {exc}", 0.0
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=KILL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            out = ""
        out = (out or "") + f"\n[seed_sweep] stopped after {timeout} s (--run-timeout)\n"
        rc = 124
    return rc, out or "", time.monotonic() - start


def read_run(out, collect):
    """What a run printed: (outcome, {marker: count}, {number name: value}, p95 or None). The outcome is the first
    --collect marker in the output; numbers are the key=value pairs on the marker lines (the last one wins)."""
    outcome, counts, numbers = "", {m: 0 for m in collect}, {}
    for line in out.splitlines():
        if line.strip().startswith(OWN_LINES):
            continue                                  # dev.py's own lines name the markers too (--until X, "X not seen")
        hits = [m for m in collect if m in line]
        for m in hits:
            counts[m] += 1
        if hits and not outcome:
            outcome = min(hits, key=line.find)        # two on one line: the one printed first
        for key, value in NUMBER_PAIR.findall(line) if hits else ():
            numbers[key] = float(value)
    p95 = None
    for m in FRAME_P95.finditer(out):
        p95 = float(m.group(1))
    return outcome, counts, numbers, p95


def prepare_out(out_dir):
    """A fresh <out>/runs folder. One made by this tool is cleared; any other existing, non-empty one is refused."""
    runs = out_dir / "runs"
    if runs.exists():
        if not (runs / MARK_FILE).is_file() and any(runs.iterdir()):
            raise UsageError(f"{runs} exists and was not made by seed_sweep.py: pick another --out")
        shutil.rmtree(runs)
    runs.mkdir(parents=True)
    (runs / MARK_FILE).write_text("made by tools/seed_sweep.py: cleared at the start of every sweep\n", encoding="utf-8")
    return runs


def sweep(args, root):
    """Run every case. Returns the list of run records (dicts), in case order."""
    engine = engine_of(root)
    jobs = args.jobs
    if engine in SERIAL_ENGINES and jobs > 1:
        print(f"[info] {engine}: one run at a time (the editor locks the project), not {jobs}")
        jobs = 1
    flags = smoke_options(root)
    all_cases = cases(args.seed_list, args.sets)
    keys = (["seed"] if args.seed_list else []) + [n for n, _ in args.sets]
    for name in check_placeholders(args.smoke, keys):
        print(f"[WARN] no smoke argument uses {{{name}}}: its runs differ only in name")
    if any(a == "--data-dir" or a.startswith("--data-dir=") for a in args.smoke):
        own_data = False                              # the user chose the folder: every run shares it
    else:
        own_data = flags["--data-dir"] and engine not in SERIAL_ENGINES
    out_dir = (root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    runs_dir = prepare_out(out_dir) if not args.dry_run else out_dir / "runs"
    width = len(str(len(all_cases)))
    records = [None] * len(all_cases)
    lock = threading.Lock()
    done = [0]

    def command(i, case, later):
        smoke = fill(args.smoke, case)
        cut = smoke.index("--") if "--" in smoke else len(smoke)
        extra = []
        if later and flags["--no-build"]:
            extra.append("--no-build")
        if own_data:
            data = runs_dir / f"{i + 1:0{width}d}" / "data"
            extra += ["--data-dir", os.path.relpath(str(data), str(root)).replace("\\", "/")]
        return [sys.executable, "tools/dev.py", "--debug", "smoke"] + smoke[:cut] + extra + smoke[cut:]

    def one(i, later):
        case = all_cases[i]
        cmd = command(i, case, later)
        rc, out, secs = run_one(root, cmd, args.run_timeout)
        folder = runs_dir / f"{i + 1:0{width}d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "smoke.log").write_text(out, encoding="utf-8")
        outcome, counts, numbers, p95 = read_run(out, args.collect_list)
        rec = {"run": i + 1, "case": case, "status": STATUS.get(rc, "fail"), "exit": rc, "outcome": outcome,
               "markers": counts, "numbers": numbers, "p95_ms": p95, "seconds": round(secs, 1),
               "log": os.path.relpath(str(folder / "smoke.log"), str(root)).replace("\\", "/"),
               "command": cmd[1:]}
        records[i] = rec
        with lock:
            done[0] += 1
            label = " ".join(f"{k}={v}" for k, v in case.items()) or "(one run)"
            print(f"[{done[0]:>{width}}/{len(all_cases)}] {label}: {rec['status']}"
                  f"{' ' + outcome if outcome else ''} ({secs:.1f} s)", flush=True)
        return rec

    if args.dry_run:
        for i, case in enumerate(all_cases):
            print(" ".join(command(i, case, i > 0)[1:]))
        return []
    print(f"[info] {len(all_cases)} run(s), {jobs} at a time; output in "
          f"{os.path.relpath(str(runs_dir), str(root)).replace(chr(92), '/')}", flush=True)
    first = one(0, False)                             # alone: it builds what the others reuse
    if first["exit"] == 2:
        tail = "\n  ".join(Path(root, first["log"]).read_text(encoding="utf-8").strip().splitlines()[-6:])
        raise UsageError(f"the first run could not start (exit 2: an environment or usage problem), so the sweep "
                         f"stops:\n  {tail}\n  (whole output: {first['log']})")
    if len(all_cases) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(lambda i: one(i, True), range(1, len(all_cases))))
    return records


# ---- Report --------------------------------------------------------------------------------------------------
def number_names(records):
    names = []
    for r in records:
        for k in r["numbers"]:
            if k not in names:
                names.append(k)
    return names


def fmt(v):
    return "-" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def table(header, rows):
    """Plain columns, left-aligned, two spaces apart."""
    widths = [max(len(str(c)) for c in col) for col in zip(header, *rows)] if rows else [len(h) for h in header]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(header, widths)).rstrip()]
    lines += ["  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip() for row in rows]
    return "\n".join(lines)


def run_table(records, keys, collect):
    nums = number_names(records)
    has_p95 = any(r["p95_ms"] is not None for r in records)
    header = ["run"] + keys + ["result"] + (["outcome"] if collect else []) + nums + (["p95_ms"] if has_p95 else []) + ["secs"]
    rows = []
    for r in records:
        rows.append([r["run"]] + [r["case"].get(k, "") for k in keys] + [r["status"]]
                    + ([r["outcome"] or "-"] if collect else []) + [fmt(r["numbers"].get(n)) for n in nums]
                    + ([fmt(r["p95_ms"])] if has_p95 else []) + [f"{r['seconds']:.1f}"])
    return table(header, rows)


def group(records, names):
    """Records grouped by their values of `names` (in first-seen order): [(label dict, records)]."""
    groups = {}
    for r in records:
        key = tuple((n, r["case"].get(n, "")) for n in names)
        groups.setdefault(key, []).append(r)
    return [(dict(k), rs) for k, rs in groups.items()]


def summarize(records, names, collect):
    """Per group: runs, passed, rate, outcome counts, mean of each number and of p95."""
    out = []
    nums = number_names(records)
    for label, rs in group(records, names):
        passed = sum(1 for r in rs if r["status"] == "pass")
        means = {}
        for n in nums + ["p95_ms"]:
            vals = [r["p95_ms"] if n == "p95_ms" else r["numbers"].get(n) for r in rs]
            vals = [v for v in vals if v is not None]
            if vals:
                means[n] = round(sum(vals) / len(vals), 3)
        outcomes = {m: sum(1 for r in rs if r["outcome"] == m) for m in collect}
        none = sum(1 for r in rs if not r["outcome"])
        if collect and none:
            outcomes["(none)"] = none
        out.append({"setting": label, "runs": len(rs), "passed": passed, "rate": passed / len(rs),
                    "outcomes": outcomes, "means": means})
    return out


def summary_table(summary):
    names = list(summary[0]["setting"]) if summary else []
    header = (names or ["all runs"]) + ["runs", "pass", "rate"]
    outcome_names = list(summary[0]["outcomes"]) if summary else []
    for s in summary:
        for k in s["outcomes"]:
            if k not in outcome_names:
                outcome_names.append(k)
    mean_names = []
    for s in summary:
        for k in s["means"]:
            if k not in mean_names:
                mean_names.append(k)
    header += outcome_names + [f"mean {n}" for n in mean_names]
    rows = []
    for s in summary:
        rows.append([s["setting"][n] for n in names] + ([""] if not names else [])
                    + [s["runs"], f"{s['passed']}/{s['runs']}", f"{s['rate'] * 100:.0f}%"]
                    + [s["outcomes"].get(k, 0) for k in outcome_names] + [fmt(s["means"].get(n)) for n in mean_names])
    return table(header, rows)


def report(args, records):
    """Print the tables; returns (summary per setting combination, per single setting value)."""
    keys = (["seed"] if args.seed_list else []) + [n for n, _ in args.sets]
    names = [n for n, _ in args.sets]
    print()
    print(run_table(records, keys, args.collect_list))
    combos = summarize(records, names, args.collect_list)
    print()
    print("Per setting:" if names else "All runs:")
    print(summary_table(combos))
    singles = []
    if len(names) > 1:
        for n in names:
            singles += summarize(records, [n], args.collect_list)
            print()
            print(f"Per {n}:")
            print(summary_table(summarize(records, [n], args.collect_list)))
    return combos, singles


def exit_code(records, combos, min_pass):
    if any(r["status"] == "error" for r in records):
        return 2 if all(r["status"] == "error" for r in records) else 1
    if min_pass is None:
        return 0 if all(r["status"] == "pass" for r in records) else 1
    low = [c for c in combos if c["rate"] < float(min_pass)]
    for c in low:
        label = " ".join(f"{k}={v}" for k, v in c["setting"].items()) or "all runs"
        print(f"[FAIL] {label}: {c['passed']}/{c['runs']} passed, under --min-pass {float(min_pass):g}")
    return 1 if low else 0


# ---- Front door ----------------------------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        prog="seed_sweep.py",
        description="Run `dev.py smoke` over seeds and settings in parallel and report pass rates per setting (#183). "
                    "Everything after `--` goes to dev.py smoke, with {seed} and {NAME} filled in per run.",
        epilog="Example: python tools/seed_sweep.py --seeds 1-8 --set bot=skilled,reckless --collect RUN_WON,"
               "PLAYER_DESTROYED -- --frames 30000 --until RUN_WON -- --autoplay {bot} --seed {seed}. "
               "Exit codes: 0 every run passed (or --min-pass met), 1 a run failed, 2 usage or environment problem.")
    ap.add_argument("--seeds", default=None, metavar="SPEC", help="seeds for {seed}: 1-8, 1,3,5 or 1-4,10")
    ap.add_argument("--set", action="append", metavar="NAME=V1,V2",
                    help="a setting and its values for {NAME}; repeat for more (every combination runs)")
    ap.add_argument("--collect", default=None, metavar="M1,M2",
                    help="markers to read from each run (the first seen is its outcome; key=value numbers on their "
                         "lines become columns)")
    ap.add_argument("--jobs", type=int, default=None, help=f"runs at the same time (default {DEFAULT_JOBS}; Unity and Unreal: 1)")
    ap.add_argument("--run-timeout", type=int, default=None, metavar="S",
                    help=f"stop a run after S seconds and count it as timeout (default {RUN_TIMEOUT_S})")
    ap.add_argument("--min-pass", type=float, default=None, metavar="RATE",
                    help="exit 0 when every setting passes at least this share of its runs, 0.0 to 1.0")
    ap.add_argument("--spec", default="", metavar="FILE", help="read the options from a JSON file (the command line wins)")
    ap.add_argument("--json", default="", metavar="FILE", help="also write the runs and the summary as JSON")
    ap.add_argument("--out", default=OUT_DIR, metavar="DIR", help=f"run output folder (default {OUT_DIR})")
    ap.add_argument("--root", default="", metavar="DIR", help="the game folder (default: the folder above tools/)")
    ap.add_argument("--dry-run", action="store_true", help="print each run's dev.py command and run nothing")
    ap.add_argument("--debug", action="store_true", help="print each command as it starts, and tracebacks")
    return ap


def main(argv=None):
    global DEBUG
    argv = sys.argv[1:] if argv is None else list(argv)
    DEBUG = "--debug" in argv[:argv.index("--")] if "--" in argv else "--debug" in argv
    try:
        args = options(argv)
        root = Path(args.root).resolve() if args.root else ROOT
        if not args.smoke and not args.seed_list and not args.sets:
            raise UsageError("nothing to sweep: give --seeds and/or --set, and the smoke arguments after `--`")
        records = sweep(args, root)
        if args.dry_run:
            return 0
        combos, singles = report(args, records)
        code = exit_code(records, combos, args.min_pass)
        if args.json:
            path = Path(args.json) if Path(args.json).is_absolute() else root / args.json
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"engine": engine_of(root), "smoke": args.smoke, "collect": args.collect_list,
                                        "runs": records, "per_setting": combos, "per_value": singles,
                                        "exit": code}, indent=2) + "\n", encoding="utf-8")
            print(f"\n[info] JSON: {path}")
        passed = sum(1 for r in records if r["status"] == "pass")
        print(f"\n[{' OK ' if code == 0 else 'FAIL'}] {passed}/{len(records)} run(s) passed")
        return code
    except UsageError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[abort] interrupted", file=sys.stderr)
        return 1
    except Exception as exc:                          # a bug in this tool: say so plainly
        print(f"[error] unexpected failure: {exc!r}. Re-run with --debug.", file=sys.stderr)
        if DEBUG:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
