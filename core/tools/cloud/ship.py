#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# ship.py
# Purpose : Put a game online with OpenTofu, the same way on five providers: a web build as a static site, or one
#           container image (a game server, a save-sync or leaderboard backend) behind HTTPS. Plan first, apply that
#           exact plan, destroy everything it made.
# Usage   : python tools/cloud/ship.py --target aws|azure|gcp|linode|do --kind static|container --plan [options]
#           python tools/cloud/ship.py --target aws --kind static --check ...   (offline: write and validate, no login)
#           python tools/cloud/ship.py --target aws --kind static --apply --yes
#           python tools/cloud/ship.py --target aws --kind static --destroy --yes
#           (python tools/dev.py ship ... forwards here, with the engine's web build folder as --site)
#             --site DIR          static: the web build to publish (must hold index.html)
#             --image REF --port N   container: a public image and the port it listens on
#             --domain NAME       linode container: the domain Caddy gets a certificate for (point its A record at the VM)
#             --region R          provider region (defaults below)
#             --budget USD        monthly budget alert, 80 % actual spend (default 10); AWS, Azure and GCP only
#             --alert-email E     who gets the budget alert (required on AWS, Azure, GCP)
#             --project P --billing-account B   GCP: the project and the billing account for the budget
#             --yes               confirm --apply / --destroy without a prompt (needed when not run in a terminal)
#             --tofu PATH         the OpenTofu executable (default: tofu on PATH, or TOFU_BIN)
#             --debug             show tofu's full output
# Env     : Each provider's own login, never a file of the kit's: AWS (aws configure / AWS_PROFILE), Azure (az login,
#           ARM_SUBSCRIPTION_ID), GCP (gcloud auth application-default login), Linode (LINODE_TOKEN), DigitalOcean
#           (DIGITALOCEAN_TOKEN, and SPACES_ACCESS_KEY_ID / SPACES_SECRET_ACCESS_KEY for a static site). TOFU_BIN.
# Exit    : 0 ok, 1 the step failed or a guardrail refused it, 2 usage or environment (no OpenTofu, bad options)
# Notes   : Pseudocode
#             --check: the --plan steps up to `tofu validate`, which needs no account (offline)
#             --plan: check options and the site (index.html, no secret-type files, no tokens) -> write
#                     deploy/<target>-<kind>/ (main.tf calling tools/cloud/modules/<target>/<kind>, terraform.tfvars.json,
#                     ship.json, and site/: a copy of the web build, scanned and published from there, so a build
#                     running alongside cannot change what was checked) -> tofu init, tofu plan -out=plan.tfplan ->
#                     list what it would make (a plan that cannot be read is refused) -> record the plan's and the
#                     copy's digests
#             --apply: the plan exists and nothing changed since (plan file, site copy) -> confirm -> tofu apply
#                      plan.tfplan -> keep main.tf and terraform.tfvars.json as applied.* -> print the URL (and the
#                      address a Linode server's domain must point at)
#             --destroy: confirm -> put the applied main.tf and terraform.tfvars.json back (a later --check or --plan
#                        with other options must not point destroy at another region or project) -> tofu destroy ->
#                        tofu state list must be empty
#           The state (terraform.tfstate) stays in deploy/<target>-<kind>/ on this machine: it can hold generated
#           secrets, so deploy/ is git-ignored. Lose it and destroy cannot find what it made (every resource the
#           provider can tag carries game-kit=<slug> for finding it by hand). No provider was used for real yet: the
#           modules are validated offline (tofu validate) and this tool is tested with a stand-in tofu (verify).
#
#           itch.io is its own path, not OpenTofu: butler uploads a build folder to a channel (#86).
#             python tools/cloud/ship.py --target itch --project user/game --site DIR [--channel C]
#                                        [--userversion V] (--dry-run | --yes | --status)
#             --dry-run: butler found (--butler, BUTLER_BIN, then butler on PATH), the folder exists, is not empty and
#                        holds no secret-type file or token, the project is user/game, the channel is valid, the
#                        version is known -> print the exact butler command and whether a login is there. Runs
#                        nothing, uploads nothing, needs no login.
#             push: the same checks -> a login must be there (BUTLER_API_KEY set, or the credentials file `butler
#                   login` saves exists; neither is ever opened, printed or written) -> confirm (the slug in a
#                   terminal, --yes elsewhere) -> butler push <folder> user/game:channel --userversion V
#             --status: butler status user/game:channel (what itch.io did with the upload)
#           The channel defaults to html5 when the folder holds index.html (a web build); any other build names its
#           channel (windows, linux, mac, android: butler tags platforms from those words). The version comes from
#           the engine's one version source (SOP-06) unless --userversion is given. Steam is not here yet (#84).
#           Tested with a stand-in butler only: a real upload is still to come (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): --target itch pushes a build with butler (#86):
#           dry run, version from the engine's version source, login checked by presence only, confirm like --apply
# ---------------------------------------------------------------------------
import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the game (tools/cloud/ship.py)
HERE = Path(__file__).resolve().parent
MODULES = HERE / "modules"
sys.path.insert(0, str(HERE.parent))
import publish_check  # noqa: E402  (the secret-file and token rules, one copy)

# ---- Tunables -----------------------------------------------------------------
TARGETS = ("aws", "azure", "gcp", "linode", "do")
KINDS = ("static", "container")
DEFAULT_REGION = {"aws": "us-east-1", "azure": "eastus", "gcp": "us-central1", "linode": "us-east", "do": "nyc3"}
# DigitalOcean names regions per product: Spaces "nyc3", App Platform "nyc" (verify the list on DigitalOcean's docs)
DEFAULT_REGION_BY_KIND = {("do", "container"): "nyc"}
APPLIED = ("main.tf", "terraform.tfvars.json")      # kept as applied.<name> after an apply, for destroy
BUDGET_TARGETS = ("aws", "azure", "gcp")              # the others have no budget API: the user sets one by hand
DEFAULT_BUDGET_USD = 10
PRICING = {                                           # where the real prices are (estimates are not guessed here)
    "aws": "https://aws.amazon.com/cloudfront/pricing/ and https://aws.amazon.com/lightsail/pricing/",
    "azure": "https://azure.microsoft.com/pricing/calculator/",
    "gcp": "https://cloud.google.com/products/calculator",
    "linode": "https://www.linode.com/pricing/",
    "do": "https://www.digitalocean.com/pricing",
}
LOGIN_HINT = {
    "aws": "aws configure (or AWS_PROFILE)",
    "azure": "az login, and ARM_SUBSCRIPTION_ID",
    "gcp": "gcloud auth application-default login",
    "linode": "LINODE_TOKEN (a personal access token)",
    "do": "DIGITALOCEAN_TOKEN, plus SPACES_ACCESS_KEY_ID / SPACES_SECRET_ACCESS_KEY for a static site",
}
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}[a-z0-9]$")
TOFU_TIMEOUT_S = 3600
DEBUG = False

# itch.io (butler, https://itch.io/docs/butler/, read 2026-11-13: E84)
ITCH = "itch"
BUTLER_KEY_ENV = "BUTLER_API_KEY"                     # butler reads it itself; this tool only checks it is set
BUTLER_CREDS = (Path.home() / ".config" / "itch" / "butler_creds",                         # Linux, Windows
                Path.home() / "Library" / "Application Support" / "itch" / "butler_creds")  # macOS
BUTLER_INSTALL = ("install butler from https://itchio.itch.io/butler (or the itch app, which bundles it), then put it "
                  "on PATH, set BUTLER_BIN or pass --butler")
BUTLER_LOGIN = (f"run `butler login` once on this machine, or set {BUTLER_KEY_ENV} to a key from "
                "https://itch.io/user/settings/api-keys (CI: a repository secret); never put the key in a file here")
ITCH_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_-]*$")   # user/game, lower case
ITCH_CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")                 # lower case, dash-separated by convention
ITCH_WEB_CHANNEL = "html5"                            # the default for a folder holding index.html
ITCH_PLATFORM_WORDS = (("windows", ("win", "windows")), ("linux", ("linux",)), ("mac", ("mac", "osx")),
                       ("android", ("android",)))     # butler tags a channel by these words in its name
USERVERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
# The engine's one version source (SOP-06 "Versioning"): engine id -> (file, regex whose group 1 is the version)
VERSION_SOURCES = {
    "godot": ("project.godot", r'(?m)^config/version="([^"]+)"'),
    "web": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    "web-3d": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    "rpgmaker-mz": ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    "bevy": ("Cargo.toml", r'(?m)^version\s*=\s*"([^"]+)"'),
    "cpp-sdl2": ("CMakeLists.txt", r"project\s*\([^)]*?\bVERSION\s+([0-9][0-9A-Za-z.]*)"),
    "love2d": ("src/version.lua", r'\bversion\s*=\s*"([^"]+)"'),
    "unity": ("ProjectSettings/ProjectSettings.asset", r"(?m)^\s*bundleVersion:\s*(\S+)"),   # (verify)
    "unreal": ("Config/DefaultGame.ini", r"(?m)^ProjectVersion=(\S+)"),                    # (verify)
}
BUTLER_TIMEOUT_S = 6 * 3600                           # a big first upload on a slow line


class ToolError(Exception):
    """A usage or environment problem: one [error] line, exit 2."""


class Refused(Exception):
    """A guardrail said no, or a step failed: one [FAIL] line, exit 1."""


def dbg(msg):
    if DEBUG:
        print(f"[debug] {msg}")


# ---- Project facts ---------------------------------------------------------------
def game_slug():
    """The game's slug from .game-kit.json, as a cloud name: lower case, hyphens."""
    try:
        meta = json.loads((ROOT / ".game-kit.json").read_text(encoding="utf-8"))
        raw = meta.get("slug") or meta.get("game_name") or ""
    except (OSError, ValueError):
        raw = ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not SLUG_RE.match(slug):
        raise ToolError(f"no usable game slug in .game-kit.json ({raw!r}): names on every provider come from it")
    return slug


def site_problems(site, need_index=True):
    """Reasons not to publish a folder: no index.html (a web build), secret-type files, tokens in text files."""
    problems = []
    if need_index and not (site / "index.html").is_file():
        problems.append(f"{site} has no index.html (build the web version first)")
    for f in sorted(p for p in site.rglob("*") if p.is_file() or p.is_symlink()):
        rel = f.relative_to(site).as_posix()
        if f.is_symlink():
            problems.append(f"{rel}: a symlink (publish real files only)")
            continue
        if publish_check.is_secret_name(rel):
            problems.append(f"{rel}: a secret-type file")
            continue
        try:
            tokens, _ = publish_check.scan_text(f)
        except publish_check.Unreadable as exc:
            problems.append(f"{rel}: cannot be read ({exc})")
            continue
        problems += [f"{rel} {t}" for t in tokens]
    return problems


def site_digest(site):
    h = hashlib.sha256()
    for f in sorted(p for p in site.rglob("*") if p.is_file()):
        h.update(f.relative_to(site).as_posix().encode("utf-8") + b"\0")
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def split_image(ref):
    """DigitalOcean App Platform's image fields from a reference: (registry_type, registry, repository, tag)."""
    m = re.fullmatch(r"(?:(ghcr\.io|docker\.io)/)?([a-z0-9._-]+)/([a-z0-9._/-]+?)(?::([\w.-]+))?", ref)
    if not m:
        raise ToolError(f"--image {ref!r}: DigitalOcean takes Docker Hub (user/name:tag) or GHCR "
                        "(ghcr.io/owner/name:tag) images")
    host, owner, repo, tag = m.groups()
    return ("GHCR" if host == "ghcr.io" else "DOCKER_HUB"), owner, repo, tag or "latest"


# ---- The root module ---------------------------------------------------------------
PROVIDERS = {
    "aws": ('aws = { source = "hashicorp/aws", version = "~> 6.0" }',
            'provider "aws" {\n  region = "{region}"\n  default_tags {\n    tags = { "game-kit" = "{slug}" }\n  }\n}'),
    "azure": ('azurerm = { source = "hashicorp/azurerm", version = "~> 5.0" }',
              'provider "azurerm" {\n  features {}\n}'),
    "gcp": ('google = { source = "hashicorp/google", version = "~> 8.0" }',
            'provider "google" {\n  project = "{project}"\n  region  = "{region}"\n}'),
    "linode": ('linode = { source = "linode/linode", version = "~> 4.0" }',
               'provider "linode" {\n  obj_use_temp_keys = true # no Object Storage keys stored anywhere\n}'),
    "do": ('digitalocean = { source = "digitalocean/digitalocean", version = "~> 2.0" }',
           'provider "digitalocean" {}'),
}


def module_inputs(a, slug):
    """The values handed to modules/<target>/<kind>, by name. Never a credential."""
    name = f"{slug}"
    t, k = a.target, a.kind
    v = {"name": name}
    tags = {"game-kit": slug}
    region_key = {"azure": "location", "gcp": "location"}.get(t, "region")
    if t != "aws":
        v[region_key] = a.region
    if k == "static":
        v["site_dir"] = a.site_copy.as_posix()
    else:
        if t == "do":
            v["registry_type"], v["registry"], v["repository"], v["tag"] = split_image(a.image)
        else:
            v["image"] = a.image
        v["port"] = a.port
    if t == "azure":
        v["tags"] = tags
        v["budget_start"] = datetime.date.today().replace(day=1).strftime("%Y-%m-01T00:00:00Z")
    if t == "gcp":
        v["labels"] = tags
        v["project"] = a.project
        v["billing_account"] = a.billing_account
    if t == "linode" and k == "container":
        v["tags"] = [f"game-kit:{slug}"]
        v["domain"] = a.domain
    if t in BUDGET_TARGETS:
        v["budget_usd"] = a.budget
        v["alert_email"] = a.alert_email
    return v


def root_module(a, slug, inputs, deploy):
    src = os.path.relpath(MODULES / a.target / a.kind, deploy).replace("\\", "/")
    req, prov = PROVIDERS[a.target]
    prov = prov.replace("{region}", a.region).replace("{slug}", slug).replace("{project}", a.project or "")
    variables = "\n".join(f'variable "{n}" {{}}' for n in inputs)
    args = "\n".join(f"  {n} = var.{n}" for n in inputs)
    return (f"# Written by tools/cloud/ship.py: change the options and plan again rather than editing this file.\n"
            f"terraform {{\n  required_providers {{\n    {req}\n  }}\n}}\n\n{prov}\n\n{variables}\n\n"
            f'module "deploy" {{\n  source = "{src}"\n{args}\n}}\n\n'
            'output "url" {\n  value = module.deploy.url\n}\n'
            + ('\noutput "address" {\n  value = module.deploy.address\n}\n'
               if (a.target, a.kind) == ("linode", "container") else ""))


# ---- Running OpenTofu -----------------------------------------------------------------
def tofu_exe(a):
    exe = a.tofu or os.environ.get("TOFU_BIN") or shutil.which("tofu")
    if not exe:
        raise ToolError("OpenTofu not found: install it (https://opentofu.org/docs/intro/install/), or pass --tofu / "
                        "set TOFU_BIN")
    return exe


def tofu(exe, deploy, *args, capture=True):
    cmd = [str(exe), *args]
    dbg("run: " + " ".join(cmd))
    env = dict(os.environ, TF_IN_AUTOMATION="1", TF_INPUT="0")
    try:
        r = subprocess.run(cmd, cwd=deploy, env=env, capture_output=capture, encoding="utf-8", errors="replace",
                           timeout=TOFU_TIMEOUT_S)
    except FileNotFoundError as exc:
        raise ToolError(f"cannot run OpenTofu ({exe}): {exc}")
    except subprocess.TimeoutExpired:
        raise Refused(f"tofu {args[0]} did not finish within {TOFU_TIMEOUT_S} s")
    out = (r.stdout or "") + (r.stderr or "")
    if DEBUG and capture:
        print(out)
    return r.returncode, out


def failed(step, out, target):
    tail = "\n  ".join(out.strip().splitlines()[-15:])
    hint = (f" Log in for {target} first: {LOGIN_HINT[target]}."
            if re.search(r"(?i)credential|authenticat|unauthori|login|token|forbidden|403|401", out) else "")
    return Refused(f"tofu {step} failed.{hint}\n  {tail}")


def confirm(a, what, slug):
    if a.yes:
        return
    if not sys.stdin or not sys.stdin.isatty():
        raise ToolError(f"{what} changes your {a.target} account: pass --yes (no terminal here to ask)")
    answer = input(f"{what} on {a.target} for {slug}. Type the game's slug to go ahead: ").strip()
    if answer != slug:
        raise Refused("not confirmed")


def write_lf(path, text):
    """UTF-8 with LF line ends on every Python (Path.write_text takes newline= only from 3.10)."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---- Commands ---------------------------------------------------------------------------
def check_options(a):
    if a.kind == "static":
        if not a.site:
            raise ToolError("--kind static needs --site <the web build folder>")
        if not Path(a.site).is_dir():
            raise ToolError(f"--site {a.site}: no such folder")
    else:
        if not a.image or not a.port:
            raise ToolError("--kind container needs --image <public image> and --port <the port it listens on>")
        if not 1 <= a.port <= 65535:
            raise ToolError("--port must be 1-65535")
        if a.target == "linode" and not a.domain:
            raise ToolError("--target linode --kind container needs --domain (HTTPS needs a name; point its A record "
                            "at the VM after apply)")
    if a.target in BUDGET_TARGETS:
        if not a.alert_email or "@" not in a.alert_email:
            raise ToolError(f"--target {a.target} needs --alert-email: every deployment gets a budget alert")
        if a.budget <= 0:
            raise ToolError("--budget must be above 0")
    if a.target == "gcp" and not (a.project and a.billing_account):
        raise ToolError("--target gcp needs --project and --billing-account (the budget lives on the billing account)")


def write_deployment(a, slug, deploy, exe):
    """Options and site checked, deploy/<target>-<kind>/ written, tofu init and validate run. Returns the inputs.
    A static site is copied into deploy/<target>-<kind>/site/ first and everything (the scan, the digest, the upload)
    uses that copy: a build that changes the original meanwhile cannot slip unscanned files in."""
    check_options(a)
    deploy.mkdir(parents=True, exist_ok=True)
    if a.kind == "static":
        a.site_copy = deploy / "site"
        if a.site_copy.exists():
            shutil.rmtree(a.site_copy)
        shutil.copytree(a.site, a.site_copy, symlinks=True)
        problems = site_problems(a.site_copy)
        if problems:
            shutil.rmtree(a.site_copy)
            raise Refused("the site folder is not safe to publish:\n  " + "\n  ".join(problems[:20]))
    inputs = module_inputs(a, slug)
    write_lf(deploy / "main.tf", root_module(a, slug, inputs, deploy))
    write_lf(deploy / "terraform.tfvars.json", json.dumps(inputs, indent=2) + "\n")
    if (deploy / "plan.tfplan").exists():
        (deploy / "plan.tfplan").unlink()   # an old plan must never be applied with new options
    rc, out = tofu(exe, deploy, "init", "-input=false", "-no-color")
    if rc != 0:
        raise failed("init", out, a.target)
    rc, out = tofu(exe, deploy, "validate", "-no-color")
    if rc != 0:
        raise failed("validate", out, a.target)
    return inputs


def cmd_check(a, slug, deploy, exe):
    write_deployment(a, slug, deploy, exe)
    print(f"[ OK ] {a.target} {a.kind}: the deployment is valid ({deploy.relative_to(ROOT).as_posix()}; no account "
          "was used)")
    return 0


def cmd_plan(a, slug, deploy, exe):
    inputs = write_deployment(a, slug, deploy, exe)
    rc, out = tofu(exe, deploy, "plan", "-input=false", "-no-color", "-out=plan.tfplan")
    if rc != 0:
        if (deploy / "plan.tfplan").exists():
            (deploy / "plan.tfplan").unlink()   # a failed plan leaves nothing that could be applied
        raise failed("plan", out, a.target)
    rc, shown = tofu(exe, deploy, "show", "-json", "plan.tfplan")
    try:
        changes = json.loads(shown)["resource_changes"] if rc == 0 else None
    except (ValueError, KeyError, TypeError):
        changes = None
    if changes is None:                     # a plan nobody could read must not be applied
        (deploy / "plan.tfplan").unlink()
        raise Refused(f"tofu show could not read the plan (exit {rc}), so it was deleted: plan again")
    made = [c["address"] for c in changes if "create" in c.get("change", {}).get("actions", [])]
    gone = [c["address"] for c in changes if "delete" in c.get("change", {}).get("actions", [])]
    state = {"target": a.target, "kind": a.kind, "inputs": inputs, "plan": file_digest(deploy / "plan.tfplan"),
             "site": site_digest(a.site_copy) if a.kind == "static" else None,
             "planned": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write_lf(deploy / "ship.json", json.dumps(state, indent=2) + "\n")
    print(f"[ OK ] plan for {a.target} {a.kind}: {len(made)} to make, {len(gone)} to remove "
          f"({deploy.relative_to(ROOT).as_posix()}/plan.tfplan)")
    for addr in made[:40]:
        print(f"  + {addr}")
    for addr in gone[:40]:
        print(f"  - {addr}")
    print(f"[info] cost: not estimated here; price what it makes at {PRICING[a.target]} (verify)")
    if a.target not in BUDGET_TARGETS:
        print(f"[WARN] {a.target} has no budget API: set a billing alert in its control panel before --apply")
    print(f"[info] next: python tools/cloud/ship.py --target {a.target} --kind {a.kind} --apply --yes")
    return 0


def load_state(deploy):
    try:
        return json.loads((deploy / "ship.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cmd_apply(a, slug, deploy, exe):
    state = load_state(deploy)
    plan = deploy / "plan.tfplan"
    if not state or not plan.is_file():
        raise Refused("no plan to apply: run --plan first, read what it makes, then --apply")
    if file_digest(plan) != state["plan"]:
        raise Refused("plan.tfplan changed since --plan wrote it: plan again")
    if state["kind"] == "static":
        site = Path(state["inputs"]["site_dir"])
        if not site.is_dir() or site_digest(site) != state["site"]:
            raise Refused(f"the site copy changed since the plan ({site}): plan again, so you apply what you read")
    confirm(a, "apply", slug)
    rc, out = tofu(exe, deploy, "apply", "-input=false", "-no-color", "plan.tfplan")
    if plan.exists():
        plan.unlink()                       # a plan is applied once: the next apply needs a fresh --plan
    if rc != 0:
        raise failed("apply", out, a.target)
    for name in APPLIED:                    # what destroy must use, whatever --check or --plan writes later
        shutil.copy2(deploy / name, deploy / f"applied.{name}")
    rc, out = tofu(exe, deploy, "output", "-json")
    try:
        outputs = {k: v["value"] for k, v in json.loads(out).items()} if rc == 0 else {}
    except (ValueError, KeyError, TypeError, AttributeError):
        outputs = {}
    print(f"[ OK ] {a.target} {a.kind} is up: {outputs.get('url', '?')}")
    if "address" in outputs:
        print(f"[info] point the domain's DNS A record at {outputs['address']}: HTTPS starts once it resolves there")
    print(f"[info] the state is {deploy.relative_to(ROOT).as_posix()}/terraform.tfstate: keep it (destroy needs it), "
          "never commit it (deploy/ is git-ignored)")
    return 0


def cmd_destroy(a, slug, deploy, exe):
    if not (deploy / "terraform.tfstate").is_file():
        raise Refused(f"no state in {deploy.relative_to(ROOT).as_posix()}: nothing this tool made is known here "
                      f"(find leftovers by the game-kit={slug} tag in the {a.target} console)")
    confirm(a, "destroy", slug)
    for name in APPLIED:
        kept = deploy / f"applied.{name}"
        if kept.is_file() and (not (deploy / name).is_file() or file_digest(kept) != file_digest(deploy / name)):
            shutil.copy2(kept, deploy / name)
            print(f"[info] destroy uses the applied {name} (a later --check or --plan had rewritten it)")
    rc, out = tofu(exe, deploy, "destroy", "-input=false", "-no-color", "-auto-approve")
    if rc != 0:
        raise failed("destroy", out, a.target)
    rc, out = tofu(exe, deploy, "state", "list")
    left = [l for l in out.splitlines() if l.strip()] if rc == 0 else ["(tofu state list failed)"]
    if left:
        raise Refused("destroy finished but the state still lists:\n  " + "\n  ".join(left[:20]))
    for name in APPLIED:
        kept = deploy / f"applied.{name}"
        if kept.is_file():
            kept.unlink()
    print(f"[ OK ] destroyed everything ship.py made on {a.target} for {slug} (the state is empty)")
    if a.target not in BUDGET_TARGETS:
        print(f"[info] remove the billing alert you set by hand in the {a.target} control panel, if you no longer want it")
    return 0


# ---- itch.io with butler (#86) ------------------------------------------------------------
def butler_exe(a):
    """The butler executable: --butler, then BUTLER_BIN, then butler on PATH. Missing is an environment problem."""
    exe = a.butler or os.environ.get("BUTLER_BIN") or shutil.which("butler")
    if not exe:
        raise ToolError("butler not found: " + BUTLER_INSTALL)
    if not Path(exe).is_file():
        raise ToolError(f"butler not found at {exe}: " + BUTLER_INSTALL)
    return exe


def butler(exe, args, capture=False):
    """Run butler with this process's environment (butler reads BUTLER_API_KEY from it: the key never goes on the
    command line). Streams butler's own progress unless capture. Returns (exit code, captured output)."""
    cmd = [str(exe), *args]
    dbg("run: " + shown_command(cmd))
    sys.stdout.flush()                      # our lines first, then butler's own (a pipe buffers ours otherwise)
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=capture, encoding="utf-8", errors="replace",
                           timeout=BUTLER_TIMEOUT_S)
    except FileNotFoundError as exc:
        raise ToolError(f"cannot run butler ({exe}): {exc}")
    except subprocess.TimeoutExpired:
        raise Refused(f"butler {args[0]} did not finish within {BUTLER_TIMEOUT_S} s")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def shown_command(cmd):
    """One command line as a user would type it in this shell (Python 3.8 has no shlex.join)."""
    if os.name == "nt":
        return subprocess.list2cmdline([str(c) for c in cmd])
    return " ".join(shlex.quote(str(c)) for c in cmd)


def itch_login():
    """How butler will log in here, by presence only: 'BUTLER_API_KEY' or 'butler login', else None.
    Neither the variable's value nor the credentials file is ever read."""
    if os.environ.get(BUTLER_KEY_ENV, "").strip():
        return BUTLER_KEY_ENV
    if any(p.is_file() for p in BUTLER_CREDS):
        return "butler login"
    return None


def itch_platforms(channel):
    """The platforms butler tags a channel with, from the words in its name (E84)."""
    return [name for name, words in ITCH_PLATFORM_WORDS if any(w in channel for w in words)]


def game_version():
    """(version, file) from the engine's one version source (SOP-06), or a ToolError naming --userversion."""
    try:
        engine = json.loads((ROOT / ".game-kit.json").read_text(encoding="utf-8")).get("engine", "")
    except (OSError, ValueError):
        engine = ""
    if engine not in VERSION_SOURCES:
        raise ToolError(f"no version source known for engine {engine!r}: pass --userversion <the game's version>")
    rel, pattern = VERSION_SOURCES[engine]
    try:
        m = re.search(pattern, (ROOT / rel).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    if not m or not USERVERSION_RE.match(m.group(1)):
        raise ToolError(f"no version found in {rel} (SOP-06 \"Versioning\"): set it there, or pass --userversion")
    return m.group(1), rel


def itch_check(a):
    """Every check a push needs except the login. Returns (butler, folder, channel, version, version source)."""
    if a.check or a.plan or a.apply or a.destroy:
        raise ToolError("--target itch takes --dry-run, --status, or no step (a push): --check, --plan, --apply and "
                        "--destroy are for the OpenTofu targets")
    if a.kind == "container":
        raise ToolError("--target itch uploads a build folder (--site), not a container image")
    if not a.project:
        raise ToolError("--target itch needs --project <user/game> (the page's address: user.itch.io/game)")
    if ":" in a.project:
        raise ToolError(f"--project {a.project}: give the channel with --channel, not after a colon")
    if not ITCH_PROJECT_RE.match(a.project):
        raise ToolError(f"--project {a.project}: must be user/game, lower case (as in user.itch.io/game)")
    exe = butler_exe(a)
    if a.status:
        if not a.channel:
            raise ToolError("--status needs --channel (the channel whose builds to show)")
        if not ITCH_CHANNEL_RE.match(a.channel):
            raise ToolError(f"--channel {a.channel}: lower case letters, digits, '-', '.', '_' (e.g. windows, html5)")
        return exe, None, a.channel, None, None
    if not a.site:
        raise ToolError("--target itch needs --site <the build folder to push> (dev.py ship adds the engine's web "
                        "build)")
    folder = Path(a.site)
    if not folder.is_dir():
        raise ToolError(f"--site {a.site}: no such folder (build the game first)")
    if not any(folder.iterdir()):
        raise ToolError(f"--site {a.site}: the folder is empty (build the game first)")
    web = (folder / "index.html").is_file()
    channel = a.channel or (ITCH_WEB_CHANNEL if web else None)
    if not channel:
        raise ToolError("--channel is needed for a build that is not a web build: windows, linux, mac or android "
                        "(butler tags the platform from those words; e.g. windows-beta)")
    if not ITCH_CHANNEL_RE.match(channel):
        raise ToolError(f"--channel {channel}: lower case letters, digits, '-', '.', '_' (e.g. windows, html5)")
    if "html" in channel and not web:
        raise ToolError(f"--channel {channel} is for a web build, but {a.site} has no index.html")
    problems = site_problems(folder, need_index=False)
    if problems:
        raise Refused("the build folder is not safe to publish:\n  " + "\n  ".join(problems[:20]))
    if a.userversion:
        if not USERVERSION_RE.match(a.userversion):
            raise ToolError(f"--userversion {a.userversion!r}: letters, digits and . + _ - only (e.g. 1.2.0)")
        version, source = a.userversion, "--userversion"
    else:
        version, source = game_version()
    return exe, folder, channel, version, source


def cmd_itch(a):
    exe, folder, channel, version, source = itch_check(a)
    target = f"{a.project}:{channel}"
    if a.status:
        if not itch_login():
            raise ToolError("no itch.io login: " + BUTLER_LOGIN)
        rc, _ = butler(exe, ["status", target])
        if rc != 0:
            raise Refused(f"butler status failed (exit {rc})")
        return 0
    push = ["push", str(folder), target, "--userversion", version]
    tags = itch_platforms(channel)
    files = sum(1 for p in folder.rglob("*") if p.is_file())
    print(f"[ OK ] butler: {exe}")
    print(f"[ OK ] build: {folder} ({files} files, no secret-type files or tokens)")
    print(f"[ OK ] page: https://{a.project.split('/')[0]}.itch.io/{a.project.split('/')[1]}, channel {channel} ("
          + (f"butler tags it {', '.join(tags)}" if tags else "the web build's channel" if "html" in channel
             else "no platform word: tag it on the itch.io Edit game page") + ")")
    if channel == ITCH_WEB_CHANNEL or "html" in channel:
        print("[info] a web build: after the first push, set the kind of project to HTML and mark this channel's "
              "upload as playable in the browser on the itch.io Edit game page (butler cannot)")
    print(f"[ OK ] version: {version} (from {source})")
    login = itch_login()
    if a.dry_run:
        print(f"[{' OK ' if login else 'WARN'}] login: " + (f"{login} (present; never read here)" if login else
                                                          "none yet; a push needs one: " + BUTLER_LOGIN))
        print("[info] would run: " + shown_command([exe, *push]))
        print("[ OK ] dry run: nothing was uploaded")
        return 0
    if not login:
        raise ToolError("no itch.io login: " + BUTLER_LOGIN)
    confirm(a, f"push {folder.name} to {target}", game_slug())
    print("[info] running: " + shown_command([exe, *push]))
    rc, _ = butler(exe, push)
    if rc != 0:
        raise Refused(f"butler push failed (exit {rc}): read butler's lines above")
    print(f"[ OK ] pushed to {target} as {version}. itch.io processes it before it is live: "
          f"python tools/cloud/ship.py --target itch --project {a.project} --channel {channel} --status")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="ship.py", description="Put a game online with OpenTofu (a static web build, or one container image), "
                                    "or upload a build to itch.io with butler (--target itch).",
        epilog="Exit codes: 0 ok, 1 failed or refused, 2 usage or environment. Every provider keeps its own login. "
               "itch.io: ship.py --target itch --project user/game --site <build folder> [--channel C] "
               "[--userversion V] --dry-run, then the same without --dry-run (and --yes outside a terminal) to push.")
    ap.add_argument("--target", required=True, choices=TARGETS + (ITCH,),
                    help="aws, azure, gcp, linode, do (DigitalOcean) with OpenTofu, or itch (itch.io with butler)")
    ap.add_argument("--kind", choices=KINDS, help="OpenTofu targets (required): static (a web build) or container "
                                                  "(one image)")
    step = ap.add_mutually_exclusive_group()
    step.add_argument("--check", action="store_true", help="write the deployment and validate it offline (no login)")
    step.add_argument("--plan", action="store_true", help="write the deployment and show what it would make")
    step.add_argument("--apply", action="store_true", help="apply the saved plan, unchanged")
    step.add_argument("--destroy", action="store_true", help="remove everything this tool made there")
    step.add_argument("--dry-run", action="store_true",
                      help="itch: check everything and print the exact butler command; uploads nothing, needs no login")
    step.add_argument("--status", action="store_true", help="itch: butler status for --project and --channel")
    ap.add_argument("--site", help="static: the web build folder (holds index.html); itch: the build folder to push")
    ap.add_argument("--image", help="container: a public image reference")
    ap.add_argument("--port", type=int, help="container: the port the image listens on")
    ap.add_argument("--domain", help="linode container: the domain for the HTTPS certificate")
    ap.add_argument("--region", help="provider region (default: " +
                    ", ".join(f"{t} {r}" for t, r in DEFAULT_REGION.items()) + ")")
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD,
                    help=f"monthly budget alert in USD at 80 %% of actual spend (default {DEFAULT_BUDGET_USD})")
    ap.add_argument("--alert-email", help="who gets the budget alert (AWS, Azure, GCP)")
    ap.add_argument("--project", help="gcp: the project id; itch: the page as user/game (lower case)")
    ap.add_argument("--billing-account", help="gcp: the billing account id for the budget")
    ap.add_argument("--channel", help=f"itch: the channel (windows, linux, mac, android name the platform; default "
                                      f"{ITCH_WEB_CHANNEL} for a folder holding index.html)")
    ap.add_argument("--userversion", help="itch: the version butler records (default: the engine's version source, "
                                          "SOP-06)")
    ap.add_argument("--yes", action="store_true", help="confirm --apply / --destroy / an itch push without a prompt")
    ap.add_argument("--tofu", help="the OpenTofu executable (default: TOFU_BIN, then tofu on PATH)")
    ap.add_argument("--butler", help="itch: the butler executable (default: BUTLER_BIN, then butler on PATH)")
    ap.add_argument("--debug", action="store_true", help="show tofu's full output and the commands run")
    return ap


def main(argv=None):
    global DEBUG
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = build_parser().parse_args(argv)
    DEBUG = a.debug
    try:
        if a.target == ITCH:                    # butler, not OpenTofu: never needs tofu
            return cmd_itch(a)
        if not a.kind:
            raise ToolError(f"--target {a.target} needs --kind static or --kind container")
        if a.dry_run or a.status:
            raise ToolError("--dry-run and --status are for --target itch: the OpenTofu targets use --check or --plan")
        if not (a.check or a.plan or a.apply or a.destroy):
            raise ToolError(f"--target {a.target} needs one step: --check, --plan, --apply or --destroy")
        a.region = a.region or DEFAULT_REGION_BY_KIND.get((a.target, a.kind), DEFAULT_REGION[a.target])
        slug = game_slug()
        exe = tofu_exe(a)
        deploy = ROOT / "deploy" / f"{a.target}-{a.kind}"
        fn = cmd_check if a.check else cmd_plan if a.plan else cmd_apply if a.apply else cmd_destroy
        return fn(a, slug, deploy, exe)
    except ToolError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"[FAIL] {exc}")
        return 1
    except OSError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        if DEBUG:
            raise
        return 2


if __name__ == "__main__":
    sys.exit(main())
