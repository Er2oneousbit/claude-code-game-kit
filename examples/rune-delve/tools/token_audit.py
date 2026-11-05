#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# token_audit.py
# Purpose : A read-only audit of what makes Claude Code sessions in this project use tokens: memory files loaded at
#           the start (CLAUDE.md, CLAUDE.local.md, @imports, the auto-memory index), model and effort settings, hooks,
#           proxy or gateway variables, MCP servers named in files, subagent models, skills, and the cache numbers of
#           the newest session log. Backs the /token-audit skill.
# Usage   : python tools/token_audit.py                       # this project, the newest session log
#           python tools/token_audit.py --root "D:\Games\Other" # another project (or the kit root)
#           python tools/token_audit.py --log path\to\session.jsonl   # a log the tool did not find by itself
#           python tools/token_audit.py --json                # everything as JSON (for scripts and the skill)
#           python tools/token_audit.py --debug               # tracebacks and skipped-line counts
# Exit    : 0 report printed, 2 usage or environment problem (no such --root, --log missing or unreadable)
# Notes   : Changes no file and no setting, and never touches the network. Token counts for files are ESTIMATES at
#           about CHARS_PER_TOKEN characters per token; the exact figure is /context. Session-log numbers are
#           measured (the usage fields the API returned). From the log only usage numbers, model and effort are
#           read: message text is never printed. Environment variables are reported by NAME only, never by value.
#           @imports are followed one level deep (Claude Code follows them further: /context lists every file).
#           Claude Code names a project's log folder after its absolute path with every character that is not a
#           letter or digit replaced by "-" (D:\Games\My Game -> D--Games-My-Game), matched here without case.
#           CLAUDE_CONFIG_DIR, when set, replaces ~/.claude (unless --home is given).
#           What it cannot see (MCP tool counts, tool deferral, scheduled tasks Claude Code holds, /usage) is
#           printed as UNKNOWN with the command to run instead. The 5k and 10k memory thresholds and the proxy
#           claim are tips from one video (E154 in docs/EVIDENCE.md, grade D), not rules. Standard library only.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
#
# Pseudocode
#   claude dir = --home/.claude, else CLAUDE_CONFIG_DIR, else ~/.claude
#   memory   = user CLAUDE.md + every parent's CLAUDE.md / CLAUDE.local.md / .claude/CLAUDE.md (top down) + the
#              project's + its auto-memory MEMORY.md; for each: bytes, chars -> est tokens; @imports one level deep
#   settings = project settings.json, settings.local.json, user settings.json: model, effortLevel, hooks by event
#              and matcher, env NAMES (proxy / gateway names flagged), enabledMcpjsonServers; .mcp.json server names;
#              the proxy names in this process's environment
#   agents   = .claude/agents/*.md (project, user): frontmatter model or "inherits"
#   skills   = .claude/skills/*/SKILL.md (project, user): count and description size (est tokens)
#   log      = --log, else newest *.jsonl in <claude>/projects/<folder named after the root>/
#              per assistant line with usage: key = message.id (last line wins: one response is written as several
#              lines that repeat its usage) -> sum the four fields, first/last turn context, models (and switches,
#              with the cache written on the turn after each), effort, 5 m / 1 h cache writes; subagent logs apart
#   findings = one row each (RED / AMBER / GREEN / UNKNOWN), sorted RED, AMBER, UNKNOWN, GREEN, then by tokens
import argparse
import json
import math
import os
import re
import sys
import traceback
from pathlib import Path

# --- constants -------------------------------------------------------------------------------------------------
CHARS_PER_TOKEN = 4                 # rough English average; an estimate, /context has the real number
MAX_LINE_BYTES = 64 * 2**20         # a session-log record over this is skipped unread (a huge tool output, #220)
FILE_FLAG_TOKENS = 5000             # E154 tip: flag one memory file over this many tokens
TOTAL_FLAG_TOKENS = 10000           # E154 tip: flag a memory total over this many tokens
CACHE_GREEN_PCT = 80.0              # kit heuristic: cache reads at least this share of the input side is healthy
CACHE_AMBER_PCT = 50.0              # kit heuristic: below this share the cache is mostly being rebuilt
HIGH_EFFORTS = ("xhigh", "max")     # E62 (grade C): tokens and cost rise steeply with effort
USAGE_FIELDS = ("cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens", "output_tokens")
# E154 tip: either of these turns tool deferral off, so every MCP tool definition loads up front
PROXY_VARS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")
# other routes to the model; whether deferral works through them is not known here
GATEWAY_VARS = ("ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX")
AUTO_SWITCH_MODELS = ("opusplan",)  # model aliases that switch models by mode (verify in the Claude Code docs)
MEMORY_NAMES = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"))
SEVERITY_ORDER = {"RED": 0, "AMBER": 1, "UNKNOWN": 2, "GREEN": 3}
# what this tool cannot read from files, and where the user finds it
UNKNOWNS = [
    ("MCP tool count and tool deferral", "run /context (deferred tools are listed apart) and /mcp, or "
                                         "`claude mcp list` in a terminal; user-level servers live in ~/.claude.json, "
                                         "which this tool does not open (it can hold secrets)"),
    ("Exact context size of this session", "run /context"),
    ("Usage against your plan's limits", "run /usage"),
    ("Scheduled tasks, loops and background jobs Claude Code holds",
     "ask Claude to list them (it sees its own scheduled tasks), check /loop and cron jobs; compare each interval "
     "with the cache lifetime (SESSION LOG: cache writes by lifetime)"),
]
# @path imports: an @ at the start of a line or after a space, then a path; code spans and blocks are not imports
IMPORT_RE = re.compile(r"(?:^|(?<=\s))@(~?[^\s`'\"<>()\[\]{}|,;]+)", re.MULTILINE)
FENCE_RE = re.compile(r"^\s*(```|~~~).*?^\s*\1", re.MULTILINE | re.DOTALL)
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")

DEBUG = False


class ToolError(Exception):
    pass


def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


# --- small helpers ---------------------------------------------------------------------------------------------
def count(v):
    """A usage number, or None when the field is not a non-negative number (missing counts as 0). Never int() on a
    string: its error message would print the value (#217)."""
    if v is None:
        return 0
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0 or v == float("inf"):
        return None
    return int(v)


def est_tokens(chars):
    return int(math.ceil(chars / float(CHARS_PER_TOKEN)))


def pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def claude_home(home, env):
    """The ~/.claude folder: --home wins, then CLAUDE_CONFIG_DIR, then the user's home."""
    if home is not None:
        return Path(home) / ".claude"
    if env.get("CLAUDE_CONFIG_DIR"):
        return Path(env["CLAUDE_CONFIG_DIR"])
    return Path.home() / ".claude"


def read_json(path):
    """(data, error): a missing file is (None, None), a broken one (None, 'why')."""
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, str(exc)[:160]


def project_log_folder(root, claude):
    """<claude>/projects/<root with non-alphanumerics as '-'>, matched without case (drive letters differ)."""
    want = re.sub(r"[^A-Za-z0-9]", "-", str(root)).lower()
    projects = claude / "projects"
    if not projects.is_dir():
        return None
    for child in projects.iterdir():
        if child.is_dir() and child.name.lower() == want:
            return child
    return None


# --- memory ----------------------------------------------------------------------------------------------------
def find_imports(text):
    """@path imports outside code blocks and code spans, as written (one level: the caller does not recurse)."""
    text = CODE_SPAN_RE.sub(" ", FENCE_RE.sub(" ", text))
    out = []
    for m in IMPORT_RE.finditer(text):
        target = m.group(1).rstrip(".:!?")
        if target and target not in out:
            out.append(target)
    return out


def resolve_import(target, base_dir, home):
    if target.startswith("~"):
        return Path(home) / target[1:].lstrip("/\\")
    p = Path(target)
    return p if p.is_absolute() else base_dir / p


def measure_file(path, kind):
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return {"path": str(path), "kind": kind, "bytes": len(raw), "chars": len(text), "est_tokens": est_tokens(len(text)),
            "imports_missing": []}


def memory_files(root, home, claude, stop_at=None):
    """Every memory file loaded at session start that can be found, with its @imports (one level)."""
    candidates = [(claude / "CLAUDE.md", "user")]
    parents = []
    for parent in root.parents:
        parents.append(parent)
        if stop_at is not None and parent == stop_at:
            break
    for parent in reversed(parents):                   # top down, the order Claude Code reads them
        candidates += [(parent / n, "parent") for n in MEMORY_NAMES]
    candidates += [(root / n, "project") for n in MEMORY_NAMES]
    folder = project_log_folder(root, claude)
    if folder is not None:
        candidates.append((folder / "memory" / "MEMORY.md", "auto memory"))
    seen, files = set(), []
    for path, kind in candidates:
        key = os.path.normcase(str(path.resolve())) if path.exists() else None
        if not path.is_file() or key in seen:
            continue
        seen.add(key)
        entry = measure_file(path, kind)
        files.append(entry)
        if kind == "auto memory":
            continue                                   # its links are read on demand, not imported
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in find_imports(text):
            ipath = resolve_import(target, path.parent, home)
            if ipath.is_file():
                ikey = os.path.normcase(str(ipath.resolve()))
                if ikey not in seen:
                    seen.add(ikey)
                    files.append(measure_file(ipath, f"import from {path.name}"))
            elif "/" in target or "\\" in target or re.search(r"\.\w{1,5}$", target):
                entry["imports_missing"].append(target)  # looks like a path; a bare @name is a mention, skipped
    return files


# --- settings, MCP, hooks --------------------------------------------------------------------------------------
def summarize_settings(path, scope):
    data, error = read_json(path)
    if data is None:
        return {"path": str(path), "scope": scope, "exists": path.is_file(), "error": error}
    if not isinstance(data, dict):   # valid JSON of the wrong shape is a per-file error, never an abort (#218)
        return {"path": str(path), "scope": scope, "exists": True,
                "error": f"not a JSON object (a {type(data).__name__})"}

    def obj(key):
        v = data.get(key)
        return v if isinstance(v, dict) else {}

    def scalar(key):
        v = data.get(key)
        return v if isinstance(v, (str, int, float, bool)) or v is None else None
    hooks = []
    for event, groups in obj("hooks").items():
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            inner = group.get("hooks")
            matcher = group.get("matcher")
            hooks.append({"event": str(event), "matcher": matcher if isinstance(matcher, str) and matcher else "(any)",
                          "count": len(inner) if isinstance(inner, list) else 0})
    per_model = {}
    for model, cfg in obj("modelSettings").items():
        if isinstance(cfg, dict) and isinstance(cfg.get("effortLevel"), str):
            per_model[str(model)] = cfg["effortLevel"]
    servers = data.get("enabledMcpjsonServers")
    return {"path": str(path), "scope": scope, "exists": True, "error": None,
            "model": scalar("model"), "effortLevel": scalar("effortLevel"), "modelEffort": per_model,
            "hooks": hooks, "env_names": sorted(str(k) for k in obj("env")),
            "enabledMcpjsonServers": [s for s in servers if isinstance(s, str)] if isinstance(servers, list) else [],
            "enabledPlugins": sorted(str(k) for k, v in obj("enabledPlugins").items() if v),
            "enableAllProjectMcpServers": scalar("enableAllProjectMcpServers")}


def settings_report(root, claude, env):
    files = [summarize_settings(root / ".claude" / "settings.json", "project"),
             summarize_settings(root / ".claude" / "settings.local.json", "project local"),
             summarize_settings(claude / "settings.json", "user")]
    mcp, mcp_error = read_json(root / ".mcp.json")
    mcp_servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    servers = sorted(str(k) for k in mcp_servers) if isinstance(mcp_servers, dict) else []
    if mcp is not None and not isinstance(mcp, dict):
        mcp_error = f"not a JSON object (a {type(mcp).__name__})"
    watched = PROXY_VARS + GATEWAY_VARS
    flagged = []
    for f in files:
        for name in f.get("env_names") or []:
            if name in watched:
                flagged.append({"name": name, "where": f["path"], "proxy": name in PROXY_VARS})
    for name in watched:
        if env.get(name):
            flagged.append({"name": name, "where": "this shell's environment", "proxy": name in PROXY_VARS})
    return {"files": files, "mcp_json": str(root / ".mcp.json") if (root / ".mcp.json").is_file() else None,
            "mcp_json_error": mcp_error, "mcp_servers": servers, "proxy_vars": flagged,
            "checked_var_names": list(watched)}


# --- agents and skills -----------------------------------------------------------------------------------------
def frontmatter(text):
    """key: value pairs of a leading --- block (flat, the only shape agents and skills use)."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out, key, block = {}, None, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t")) and key is not None:
            # a continuation line: a folded (>) or literal (|) block, or a plain value wrapped onto the next line;
            # it was dropped before, so a long description was counted as one token (#220)
            part = line.strip()
            if part:
                sep = "\n" if block == "|" else " "
                out[key] = (out[key] + sep + part) if out[key] else part
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            block = value[:1] if value[:1] in (">", "|") and value.strip(">|+-0123456789") == "" else None
            out[key] = "" if block else value.strip("\"'")
    return out


def agents_report(root, claude):
    out = []
    for scope, folder in (("project", root / ".claude" / "agents"), ("user", claude / "agents")):
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            meta = frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            model = meta.get("model", "")
            out.append({"path": str(path), "scope": scope, "name": meta.get("name", path.stem),
                        "model": model if model and model != "inherit" else "inherits"})
    return out


def skills_report(root, claude):
    out = []
    for scope, folder in (("project", root / ".claude" / "skills"), ("user", claude / "skills")):
        for path in sorted(folder.glob("*/SKILL.md")) if folder.is_dir() else []:
            meta = frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            desc = meta.get("description", "")
            out.append({"path": str(path), "scope": scope, "name": meta.get("name", path.parent.name),
                        "description_chars": len(desc), "est_tokens": est_tokens(len(desc))})
    return out


# --- the session log -------------------------------------------------------------------------------------------
def newest_log(folder):
    logs = [p for p in folder.glob("*.jsonl") if p.is_file()] if folder else []
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def parse_log(path):
    """Usage numbers of one session log, one entry per API response (message.id), never any text.

    Pseudocode: for each line that names "assistant": parse -> skip non-assistant, no usage, <synthetic> ->
    turns[id] = usage (a later line with the same id replaces it) -> sum, first/last, models, efforts.
    """
    turns, order, bad, lines, oversized = {}, [], 0, 0, 0
    with open(path, "rb") as fh:
        n = -1
        while True:
            raw = fh.readline(MAX_LINE_BYTES)
            if not raw:
                break
            n += 1
            if not raw.endswith(b"\n") and len(raw) == MAX_LINE_BYTES:
                # one record over the limit (a huge tool output): skip the rest of it unread, never hold it (#220)
                while True:
                    more = fh.readline(MAX_LINE_BYTES)
                    if not more or more.endswith(b"\n"):
                        break
                oversized += 1
                continue
            if b'"assistant"' not in raw:              # cheap pre-filter: the log can be hundreds of MB
                continue
            line = raw.decode("utf-8", errors="replace")
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            usage = msg.get("usage")
            if not isinstance(usage, dict) or msg.get("model") == "<synthetic>":
                continue
            cache = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
            nums = {f: count(usage.get(f)) for f in USAGE_FIELDS}
            nums["ttl_5m"] = count(cache.get("ephemeral_5m_input_tokens"))
            nums["ttl_1h"] = count(cache.get("ephemeral_1h_input_tokens"))
            if None in nums.values():
                # not a number: a malformed line, counted and never shown (int() would print the value, #217)
                bad += 1
                continue
            lines += 1
            key = msg.get("id") if isinstance(msg.get("id"), str) else f"line-{n}"
            if key not in turns:
                order.append(key)
            model = msg.get("model") if isinstance(msg.get("model"), str) else "unknown"
            effort = rec.get("effort") if isinstance(rec.get("effort"), str) else None
            turns[key] = {"usage": {f: nums[f] for f in USAGE_FIELDS}, "ttl_5m": nums["ttl_5m"],
                          "ttl_1h": nums["ttl_1h"], "model": model, "effort": effort}
    debug(f"{path.name}: {lines} usage lines, {len(order)} responses, {bad} unreadable lines, "
          f"{oversized} over {MAX_LINE_BYTES // 2**20} MiB skipped")
    bad += oversized
    totals = {f: 0 for f in USAGE_FIELDS}
    models, efforts, switches, switch_writes, ttl = {}, {}, 0, 0, {"5m": 0, "1h": 0}
    prev = None
    for key in order:
        t = turns[key]
        for f in USAGE_FIELDS:
            totals[f] += t["usage"][f]
        models[t["model"]] = models.get(t["model"], 0) + 1
        if t["effort"]:
            efforts[t["effort"]] = efforts.get(t["effort"], 0) + 1
        ttl["5m"] += t["ttl_5m"]
        ttl["1h"] += t["ttl_1h"]
        if prev is not None and t["model"] != prev:
            switches += 1
            switch_writes += t["usage"]["cache_creation_input_tokens"]
        prev = t["model"]
    total = sum(totals.values())

    def context(key):
        u = turns[key]["usage"]
        return u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]

    return {"path": str(path), "responses": len(order), "usage_lines": lines, "duplicate_lines": lines - len(order),
            "unreadable_lines": bad, "totals": totals, "total": total,
            "percent": {f: pct(totals[f], total) for f in USAGE_FIELDS},
            "first_context": context(order[0]) if order else 0, "last_context": context(order[-1]) if order else 0,
            "models": models, "model_switches": switches, "cache_written_after_switches": switch_writes,
            "efforts": efforts, "cache_writes_by_ttl": ttl}


def subagent_logs(log_path):
    folder = Path(log_path).with_suffix("") / "subagents"
    return sorted(folder.glob("*.jsonl")) if folder.is_dir() else []


def session_report(root, claude, log_arg):
    if log_arg:
        path = Path(log_arg)
        if not path.is_file():
            raise ToolError(f"--log {path} not found")
        where = "--log"
    else:
        folder = project_log_folder(root, claude)
        path = newest_log(folder)
        if path is None:
            looked = claude / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))
            return {"path": None, "looked_in": str(looked)}
        where = "newest in " + str(path.parent)
    try:
        report = parse_log(path)
    except OSError as exc:
        raise ToolError(f"cannot read the session log {path}: {exc}")
    report["found_by"] = where
    subs = subagent_logs(path)
    if subs:
        sub_tot = {f: 0 for f in USAGE_FIELDS}
        responses = 0
        for sp in subs:
            try:
                r = parse_log(sp)
            except OSError as exc:
                debug(f"skip subagent log {sp}: {exc}")
                continue
            responses += r["responses"]
            for f in USAGE_FIELDS:
                sub_tot[f] += r["totals"][f]
        total = sum(sub_tot.values())
        report["subagents"] = {"logs": len(subs), "responses": responses, "totals": sub_tot, "total": total,
                               "percent": {f: pct(sub_tot[f], total) for f in USAGE_FIELDS}}
    return report


# --- findings --------------------------------------------------------------------------------------------------
def finding(name, severity, evidence, cost, tokens=0):
    return {"finding": name, "severity": severity, "evidence": evidence, "cost": cost, "tokens": tokens}


def build_findings(rep):
    out = []
    mem = rep["memory"]
    total = sum(f["est_tokens"] for f in mem)
    out.append(finding("Memory files loaded at start", "RED" if total > TOTAL_FLAG_TOKENS else "GREEN",
                       f"{total:,} est tokens in {len(mem)} file(s) (E154 tip: flag over {TOTAL_FLAG_TOKENS:,})",
                       f"about {total:,} tokens sent with every request (est.; exact: /context)", total))
    for f in mem:
        if f["est_tokens"] > FILE_FLAG_TOKENS:
            out.append(finding("Large memory file", "AMBER", f"{f['path']}: {f['est_tokens']:,} est tokens",
                               f"about {f['est_tokens']:,} tokens per request (E154 tip: over {FILE_FLAG_TOKENS:,})",
                               f["est_tokens"]))
        for miss in f["imports_missing"]:
            out.append(finding("@import not found", "AMBER", f"{f['path']}: @{miss}", "nothing loads; UNKNOWN intent"))

    st = rep["settings"]
    proxies = [v for v in st["proxy_vars"] if v["proxy"]]
    for v in proxies:
        out.append(finding("Proxy or gateway variable set", "RED", f"{v['name']} in {v['where']}",
                           "E154 tip: tool deferral turns off, so every MCP tool definition loads up front "
                           "(check /context)"))
    for v in st["proxy_vars"]:
        if not v["proxy"]:
            out.append(finding("Other model route set", "AMBER", f"{v['name']} in {v['where']}",
                               "UNKNOWN: whether tools are deferred on this route (check /context)"))
    if not st["proxy_vars"]:
        out.append(finding("Proxy or gateway variables", "GREEN",
                           f"0 of {len(st['checked_var_names'])} names set (settings env and this shell)", "none"))

    models = [(f["path"], f["model"]) for f in st["files"] if f.get("model")]
    efforts = [(f["path"], f["effortLevel"]) for f in st["files"] if f.get("effortLevel")]
    efforts += [(f["path"] + f" (modelSettings {m})", e) for f in st["files"] for m, e in (f.get("modelEffort") or {}).items()]
    for path, model in models:
        if str(model).lower() in AUTO_SWITCH_MODELS:
            out.append(finding("Automatic model switching", "AMBER", f"model {model} in {path}",
                               "E154 tip: each switch writes the cache again (measured switches: SESSION LOG)"))
    log = rep["session"]
    if log.get("path"):
        if log["model_switches"]:
            out.append(finding("Model switches in the session log", "AMBER",
                               f"{log['model_switches']} switch(es) in {log['path']}",
                               f"{log['cache_written_after_switches']:,} cache-write tokens on the turns right after",
                               log["cache_written_after_switches"]))
        high = {e: n for e, n in log["efforts"].items() if e in HIGH_EFFORTS}
        if high:
            ev = ", ".join(f"{n} turn(s) at {e}" for e, n in sorted(high.items()))
            out.append(finding("High effort", "AMBER", f"{ev} of {log['responses']} in the log",
                               f"output is {log['percent']['output_tokens']}% of the log's tokens; E62 tip: "
                               "tokens rise steeply per effort level", log["totals"]["output_tokens"]))
    for path, effort in efforts:
        if str(effort).lower() in HIGH_EFFORTS:
            out.append(finding("High effort setting", "AMBER", f"effortLevel {effort} in {path}",
                               "E62 tip: tokens rise steeply per effort level"))
    if not models and not efforts:
        out.append(finding("Model and effort settings", "GREEN", "no model or effortLevel in the 3 settings files",
                           "defaults apply; current values: /model and /status"))

    pre = [(f["path"], h) for f in st["files"] for h in f.get("hooks") or [] if h["event"] == "PreToolUse"]
    if pre:
        out.append(finding("PreToolUse hooks", "GREEN",
                           "; ".join(f"{h['matcher']} x{h['count']} in {p}" for p, h in pre),
                           "check that one of them trims noisy command output"))
    else:
        out.append(finding("No PreToolUse hook", "AMBER", "0 PreToolUse hooks in the 3 settings files",
                           "UNKNOWN: long command output goes into context untrimmed (E154 tip)"))

    servers = st["mcp_servers"]
    out.append(finding("MCP servers named in files", "UNKNOWN" if servers else "GREEN",
                       f"{len(servers)} in .mcp.json" + (f" ({', '.join(servers)})" if servers else ""),
                       "UNKNOWN: tool count and deferral (run /context, /mcp)" if servers else "none from this project"))

    agents = rep["agents"]
    inherit = [a for a in agents if a["model"] == "inherits"]
    if inherit:
        main_model = ", ".join(sorted(log.get("models", {}))) if log.get("path") else "UNKNOWN"
        out.append(finding("Subagents without a model", "AMBER",
                           f"{len(inherit)} of {len(agents)}: " + ", ".join(a["path"] for a in inherit),
                           f"they run on the main model ({main_model})"))
    elif agents:
        out.append(finding("Subagent models", "GREEN", f"{len(agents)} of {len(agents)} set a model", "none"))

    skills = rep["skills"]
    if skills:
        s_tokens = sum(s["est_tokens"] for s in skills)
        out.append(finding("Skill descriptions", "GREEN", f"{len(skills)} skill(s), {s_tokens:,} est tokens",
                           f"about {s_tokens:,} tokens per request (est.)", s_tokens))

    if log.get("path"):
        read_side = log["totals"]["cache_read_input_tokens"] + log["totals"]["cache_creation_input_tokens"] + \
            log["totals"]["input_tokens"]
        share = pct(log["totals"]["cache_read_input_tokens"], read_side)
        sev = "GREEN" if share >= CACHE_GREEN_PCT else ("AMBER" if share >= CACHE_AMBER_PCT else "RED")
        out.append(finding("Prompt cache", sev,
                           f"cache read {share}% of {read_side:,} input-side tokens over {log['responses']} "
                           f"responses; context {log['first_context']:,} -> {log['last_context']:,}",
                           f"{log['totals']['cache_creation_input_tokens']:,} tokens written to cache, "
                           f"{log['totals']['input_tokens']:,} uncached", log["totals"]["cache_creation_input_tokens"]))
    else:
        out.append(finding("Prompt cache", "UNKNOWN", f"no session log in {log.get('looked_in')}",
                           "pass --log <file>.jsonl"))
    for name, hint in UNKNOWNS:
        if name.startswith("Scheduled"):
            out.append(finding(name, "UNKNOWN", "not stored in project files", hint))
    out.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], -f["tokens"]))
    return out


# --- output ----------------------------------------------------------------------------------------------------
def render(rep):
    L = [f"Token audit: {rep['root']}",
         "Read-only: no file or setting was changed. Session-log numbers are measured; file sizes in tokens are",
         f"estimates at {CHARS_PER_TOKEN} characters per token (exact: /context).", ""]
    L.append("MEMORY (loaded at session start; @imports followed one level deep)")
    for f in rep["memory"]:
        L.append(f"  {f['est_tokens']:>8,} est tok {f['bytes']:>9,} B  {f['kind']:<24} {f['path']}")
        for miss in f["imports_missing"]:
            L.append(f"  {'':>8}         {'':>9}    [warn] @{miss} not found")
    if not rep["memory"]:
        L.append("  none found")
    total = sum(f["est_tokens"] for f in rep["memory"])
    L += [f"  total: {total:,} est tokens (E154 tip: flag a file over {FILE_FLAG_TOKENS:,}, a total over "
          f"{TOTAL_FLAG_TOKENS:,})", ""]

    st = rep["settings"]
    L.append("SETTINGS")
    for f in st["files"]:
        if not f["exists"]:
            L.append(f"  {f['scope']:<14} not present  {f['path']}")
            continue
        if f["error"]:
            L.append(f"  {f['scope']:<14} [warn] cannot parse ({f['error']})  {f['path']}")
            continue
        bits = [f"model {f['model'] or '-'}", f"effortLevel {f['effortLevel'] or '-'}"]
        bits += [f"{m} effort {e}" for m, e in sorted(f["modelEffort"].items())]
        L.append(f"  {f['scope']:<14} {', '.join(bits)}  {f['path']}")
        for h in f["hooks"]:
            L.append(f"  {'':<14} hook {h['event']} matcher {h['matcher']} x{h['count']}")
        if f["env_names"]:
            L.append(f"  {'':<14} env names: {', '.join(f['env_names'])}")
        if f["enabledMcpjsonServers"]:
            L.append(f"  {'':<14} enabledMcpjsonServers: {', '.join(f['enabledMcpjsonServers'])}")
        if f["enabledPlugins"]:
            L.append(f"  {'':<14} enabledPlugins: {', '.join(f['enabledPlugins'])} (their skills, agents and MCP "
                     "tools: /context)")
    if st["proxy_vars"]:
        for v in st["proxy_vars"]:
            L.append(f"  [warn] {v['name']} is set in {v['where']} (value not shown)")
    else:
        L.append(f"  proxy / gateway variables: none set ({', '.join(st['checked_var_names'])})")
    if st["mcp_json"]:
        L.append(f"  .mcp.json servers: {', '.join(st['mcp_servers']) or 'none'}"
                 + (f" [warn] cannot parse ({st['mcp_json_error']})" if st["mcp_json_error"] else ""))
    else:
        L.append("  .mcp.json: not present")
    L.append("")

    L.append("SUBAGENTS")
    for a in rep["agents"]:
        L.append(f"  {a['model']:<10} {a['scope']:<8} {a['path']}")
    if not rep["agents"]:
        L.append("  none")
    s_tokens = sum(s["est_tokens"] for s in rep["skills"])
    L += ["", f"SKILLS: {len(rep['skills'])} ({s_tokens:,} est tokens of descriptions, loaded every session)", ""]

    log = rep["session"]
    L.append("SESSION LOG")
    if not log.get("path"):
        L.append(f"  none found in {log.get('looked_in')} (pass --log <file>.jsonl)")
    else:
        L.append(f"  {log['path']} ({log['found_by']})")
        L.append(f"  {log['responses']:,} API responses ({log['usage_lines']:,} log lines; {log['duplicate_lines']:,} "
                 "repeat a response and were counted once)")
        names = {"cache_read_input_tokens": "cache read", "cache_creation_input_tokens": "cache write",
                 "input_tokens": "input (uncached)", "output_tokens": "output"}
        for f in USAGE_FIELDS:
            L.append(f"  {names[f]:<17} {log['totals'][f]:>15,}  {log['percent'][f]:>5}%")
        L.append(f"  {'total':<17} {log['total']:>15,}")
        L.append(f"  context: first turn {log['first_context']:,}, last turn {log['last_context']:,} "
                 "(input + cache read + cache write)")
        ttl = log["cache_writes_by_ttl"]
        L.append(f"  cache writes by lifetime: 5 min {ttl['5m']:,}, 1 hour {ttl['1h']:,}")
        L.append("  models: " + ", ".join(f"{m} x{n}" for m, n in sorted(log["models"].items()))
                 + f"; switches: {log['model_switches']}")
        if log["efforts"]:
            L.append("  effort: " + ", ".join(f"{e} x{n}" for e, n in sorted(log["efforts"].items())))
        sub = log.get("subagents")
        if sub:
            L.append(f"  subagents: {sub['logs']} log(s), {sub['responses']:,} responses, {sub['total']:,} tokens "
                     f"(cache read {sub['percent']['cache_read_input_tokens']}%, output "
                     f"{sub['percent']['output_tokens']}%)")
    L.append("")
    L.append("NOT VISIBLE TO THIS TOOL (UNKNOWN)")
    for name, hint in UNKNOWNS:
        L.append(f"  - {name}: {hint}")
    L += ["", "FINDINGS (RED, AMBER, UNKNOWN, GREEN; then by tokens)",
          "| FINDING | SEVERITY | EVIDENCE | WHAT IT IS COSTING |", "|---|---|---|---|"]
    for f in rep["findings"]:
        L.append(f"| {f['finding']} | {f['severity']} | {f['evidence']} | {f['cost']} |")
    return "\n".join(L)


def audit(root, home=None, env=None, log=None, stop_at=None):
    env = os.environ if env is None else env
    claude = claude_home(home, env)
    # @~/ imports are relative to the user's home, wherever CLAUDE_CONFIG_DIR puts .claude (#219)
    home_dir = Path(home) if home is not None else Path.home()
    rep = {"root": str(root), "claude_dir": str(claude),
           "memory": memory_files(root, home_dir, claude, stop_at),
           "settings": settings_report(root, claude, env),
           "agents": agents_report(root, claude),
           "skills": skills_report(root, claude),
           "session": session_report(root, claude, log),
           "unknown": [{"what": n, "run": h} for n, h in UNKNOWNS],
           "estimate_note": f"file token counts are estimates at {CHARS_PER_TOKEN} chars per token; exact: /context"}
    rep["findings"] = build_findings(rep)
    return rep


def build_parser():
    ap = argparse.ArgumentParser(
        description="Read-only token audit of a Claude Code project: memory files, settings, hooks, proxy "
                    "variables, MCP servers in files, subagent models, skills, and the newest session log's cache "
                    "numbers. Changes nothing, uses no network.",
        epilog="Exit 0 report printed, 2 usage or environment problem. Env: CLAUDE_CONFIG_DIR (replaces ~/.claude). "
               "What it cannot see is printed as UNKNOWN: run /context, /usage and /mcp in Claude Code for those.")
    ap.add_argument("--root", default=os.getcwd(), help="the project folder (default: the current folder)")
    ap.add_argument("--log", default=None, help="a session log (.jsonl) to read instead of the newest one found")
    ap.add_argument("--home", default=None, help="the home folder whose .claude to read (default: yours; tests)")
    ap.add_argument("--stop-at", default=None, help="do not look for parent CLAUDE.md files above this folder")
    ap.add_argument("--json", action="store_true", help="print the whole report as JSON")
    ap.add_argument("--debug", action="store_true", help="tracebacks on errors, skipped-line counts")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows pipes default to cp1252
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    DEBUG = args.debug
    try:
        root = Path(args.root).resolve()
        if not root.is_dir():
            raise ToolError(f"--root {args.root} is not a folder")
        stop_at = Path(args.stop_at).resolve() if args.stop_at else None
        rep = audit(root, home=args.home, log=args.log, stop_at=stop_at)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - last line of defense, traceback only with --debug
        if DEBUG:
            traceback.print_exc()
        # the type only: an exception's text can quote what it failed on, a value from a file (#217)
        print(f"[error] unexpected failure ({type(exc).__name__}); re-run with --debug for the traceback",
              file=sys.stderr)
        return 2
    text = json.dumps(rep, indent=2) if args.json else render(rep)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg and args.home is None:
        # environment variables are reported by name only: the folder it names is shown as $CLAUDE_CONFIG_DIR (#217)
        real = str(claude_home(None, os.environ))
        for form in {real, real.replace("\\", "/"), real.replace("\\", "\\\\"), cfg}:
            text = text.replace(form, "$CLAUDE_CONFIG_DIR")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
