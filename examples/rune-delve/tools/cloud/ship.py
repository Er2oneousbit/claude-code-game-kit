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
#                     ship.json) -> tofu init, tofu plan -out=plan.tfplan -> list what it would make -> record the plan
#                     file's and the site's digests
#             --apply: the plan exists and nothing changed since (plan file, site, options) -> confirm -> tofu apply
#                      plan.tfplan -> print the URL
#             --destroy: confirm -> tofu destroy -> tofu state list must be empty
#           The state (terraform.tfstate) stays in deploy/<target>-<kind>/ on this machine: it can hold generated
#           secrets, so deploy/ is git-ignored. Lose it and destroy cannot find what it made (every resource the
#           provider can tag carries game-kit=<slug> for finding it by hand). No provider was used for real yet: the
#           modules are validated offline (tofu validate) and this tool is tested with a stand-in tofu (verify).
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import argparse
import datetime
import hashlib
import json
import os
import re
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


def site_problems(site):
    """Reasons not to publish a folder: no index.html, secret-type files, tokens in text files."""
    problems = []
    if not (site / "index.html").is_file():
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
        v["site_dir"] = Path(a.site).resolve().as_posix()
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
            'output "url" {\n  value = module.deploy.url\n}\n')


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
    """Options and site checked, deploy/<target>-<kind>/ written, tofu init and validate run. Returns the inputs."""
    check_options(a)
    if a.kind == "static":
        problems = site_problems(Path(a.site))
        if problems:
            raise Refused("the site folder is not safe to publish:\n  " + "\n  ".join(problems[:20]))
    inputs = module_inputs(a, slug)
    deploy.mkdir(parents=True, exist_ok=True)
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
        changes = json.loads(shown).get("resource_changes", []) if rc == 0 else []
    except ValueError:
        changes = []
    made = [c["address"] for c in changes if "create" in c.get("change", {}).get("actions", [])]
    gone = [c["address"] for c in changes if "delete" in c.get("change", {}).get("actions", [])]
    state = {"target": a.target, "kind": a.kind, "inputs": inputs, "plan": file_digest(deploy / "plan.tfplan"),
             "site": site_digest(Path(a.site)) if a.kind == "static" else None,
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
            raise Refused(f"the site folder changed since the plan ({site}): plan again, so you apply what you read")
    confirm(a, "apply", slug)
    rc, out = tofu(exe, deploy, "apply", "-input=false", "-no-color", "plan.tfplan")
    if plan.exists():
        plan.unlink()                       # a plan is applied once: the next apply needs a fresh --plan
    if rc != 0:
        raise failed("apply", out, a.target)
    rc, out = tofu(exe, deploy, "output", "-json")
    try:
        url = json.loads(out)["url"]["value"] if rc == 0 else "?"
    except (ValueError, KeyError, TypeError):
        url = "?"
    print(f"[ OK ] {a.target} {a.kind} is up: {url}")
    print(f"[info] the state is {deploy.relative_to(ROOT).as_posix()}/terraform.tfstate: keep it (destroy needs it), "
          "never commit it (deploy/ is git-ignored)")
    return 0


def cmd_destroy(a, slug, deploy, exe):
    if not (deploy / "terraform.tfstate").is_file():
        raise Refused(f"no state in {deploy.relative_to(ROOT).as_posix()}: nothing this tool made is known here "
                      f"(find leftovers by the game-kit={slug} tag in the {a.target} console)")
    confirm(a, "destroy", slug)
    rc, out = tofu(exe, deploy, "destroy", "-input=false", "-no-color", "-auto-approve")
    if rc != 0:
        raise failed("destroy", out, a.target)
    rc, out = tofu(exe, deploy, "state", "list")
    left = [l for l in out.splitlines() if l.strip()] if rc == 0 else ["(tofu state list failed)"]
    if left:
        raise Refused("destroy finished but the state still lists:\n  " + "\n  ".join(left[:20]))
    print(f"[ OK ] destroyed everything ship.py made on {a.target} for {slug} (the state is empty)")
    if a.target not in BUDGET_TARGETS:
        print(f"[info] remove the billing alert you set by hand in the {a.target} control panel, if you no longer want it")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="ship.py", description="Put a game online with OpenTofu: a static web build, or one container image.",
        epilog="Exit codes: 0 ok, 1 failed or refused, 2 usage or environment. Every provider keeps its own login.")
    ap.add_argument("--target", required=True, choices=TARGETS, help="aws, azure, gcp, linode or do (DigitalOcean)")
    ap.add_argument("--kind", required=True, choices=KINDS, help="static (a web build) or container (one image)")
    step = ap.add_mutually_exclusive_group(required=True)
    step.add_argument("--check", action="store_true", help="write the deployment and validate it offline (no login)")
    step.add_argument("--plan", action="store_true", help="write the deployment and show what it would make")
    step.add_argument("--apply", action="store_true", help="apply the saved plan, unchanged")
    step.add_argument("--destroy", action="store_true", help="remove everything this tool made there")
    ap.add_argument("--site", help="static: the web build folder (holds index.html)")
    ap.add_argument("--image", help="container: a public image reference")
    ap.add_argument("--port", type=int, help="container: the port the image listens on")
    ap.add_argument("--domain", help="linode container: the domain for the HTTPS certificate")
    ap.add_argument("--region", help="provider region (default: " +
                    ", ".join(f"{t} {r}" for t, r in DEFAULT_REGION.items()) + ")")
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD,
                    help=f"monthly budget alert in USD at 80 %% of actual spend (default {DEFAULT_BUDGET_USD})")
    ap.add_argument("--alert-email", help="who gets the budget alert (AWS, Azure, GCP)")
    ap.add_argument("--project", help="gcp: the project id")
    ap.add_argument("--billing-account", help="gcp: the billing account id for the budget")
    ap.add_argument("--yes", action="store_true", help="confirm --apply / --destroy without a prompt")
    ap.add_argument("--tofu", help="the OpenTofu executable (default: TOFU_BIN, then tofu on PATH)")
    ap.add_argument("--debug", action="store_true", help="show tofu's full output")
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
    a.region = a.region or DEFAULT_REGION[a.target]
    try:
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
