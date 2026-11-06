#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_ship.py
# Purpose : Exam for tools/cloud/ship.py and the OpenTofu modules: the plan / apply / destroy guardrails against a
#           stand-in tofu (offline, no account), and, when OpenTofu is installed, every module and every generated
#           deployment through the real `tofu validate` and `tofu fmt -check`.
# Usage   : python tools/cloud/test_ship.py          (TOFU_BIN or tofu on PATH turns on the real-OpenTofu cases;
#                                                      their first run downloads the five providers)
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. Each case copies ship.py, the modules and publish_check.py into a temporary game
#           folder, so the deploy/ folders it writes never land in the project. Nothing here logs in anywhere.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
TOFU = os.environ.get("TOFU_BIN") or shutil.which("tofu")
TARGETS = ("aws", "azure", "gcp", "linode", "do")
ALL_OPTS = ["--alert-email", "me@example.com", "--project", "p1", "--billing-account", "000000-000000-000000"]


class FakeTofu:
    """Stands in for OpenTofu: records each call and acts out init, validate, plan, show, apply, output, destroy and
    state list on the deploy folder, the way the real one leaves files behind."""

    def __init__(self, plan_rc=0, plan_out="", destroy_leaves=(), show_out=None, outputs=None):
        self.calls = []
        self.plan_rc, self.plan_out, self.destroy_leaves = plan_rc, plan_out, list(destroy_leaves)
        self.show_out = show_out
        self.outputs = outputs or {"url": {"value": "https://d111.cloudfront.net/"}}
        self.destroyed_with = None          # the terraform.tfvars.json destroy ran with

    def __call__(self, exe, deploy, *args, capture=True):
        self.calls.append(args[0] if args[0] != "state" else "state list")
        cmd = args[0]
        if cmd == "plan":
            (deploy / "plan.tfplan").write_bytes(b"plan v1")    # the real one writes even when it then fails
            return self.plan_rc, self.plan_out
        if cmd == "show":
            if self.show_out is not None:
                return self.show_out
            return 0, json.dumps({"resource_changes": [
                {"address": "module.deploy.aws_s3_bucket.site", "change": {"actions": ["create"]}},
                {"address": "module.deploy.aws_budgets_budget.deploy", "change": {"actions": ["create"]}}]})
        if cmd == "apply":
            (deploy / "terraform.tfstate").write_text('{"resources": [1]}', encoding="utf-8")
            return 0, "Apply complete!"
        if cmd == "output":
            return 0, json.dumps(self.outputs)
        if cmd == "destroy":
            tfvars = deploy / "terraform.tfvars.json"
            self.destroyed_with = json.loads(tfvars.read_text(encoding="utf-8")) if tfvars.is_file() else None
            return 0, "Destroy complete!"
        if cmd == "state":
            return 0, "\n".join(self.destroy_leaves)
        return 0, ""


class Game:
    """A temporary game folder holding the kit's cloud tool, with a web build in site/."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        tools = self.root / "tools"
        shutil.copytree(HERE, tools / "cloud", ignore=shutil.ignore_patterns("__pycache__", ".terraform*", "test_*"))
        shutil.copy2(TOOLS / "publish_check.py", tools / "publish_check.py")
        (self.root / ".game-kit.json").write_text(json.dumps({"slug": "ship_test", "game_name": "Ship Test"}),
                                                  encoding="utf-8")
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("<html>hi</html>\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("ship_under_test", tools / "cloud" / "ship.py")
        self.ship = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ship)

    def run(self, *argv, fake=None):
        if fake is not None:
            self.ship.tofu = fake
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.ship.main([*map(str, argv), "--tofu", "tofu-stand-in"])
        return code, out.getvalue()

    def deploy(self, name):
        return self.root / "deploy" / name


class ShipGuardrails(unittest.TestCase):
    def setUp(self):
        self.g = Game()
        self.fake = FakeTofu()

    def tearDown(self):
        self.g.tmp.cleanup()

    def plan(self, *extra, fake=None):
        return self.g.run("--target", "aws", "--kind", "static", "--plan", "--site", self.g.site,
                          "--alert-email", "me@example.com", *extra, fake=fake or self.fake)

    def test_plan_writes_the_deployment_and_lists_what_it_makes(self):
        code, out = self.plan()
        self.assertEqual(code, 0, out)
        d = self.g.deploy("aws-static")
        main = (d / "main.tf").read_text(encoding="utf-8")
        self.assertIn('source = "../../tools/cloud/modules/aws/static"', main)
        self.assertIn('"game-kit" = "ship-test"', main)
        inputs = json.loads((d / "terraform.tfvars.json").read_text(encoding="utf-8"))
        self.assertEqual(inputs["name"], "ship-test")
        self.assertEqual(inputs["budget_usd"], 10)
        self.assertEqual(self.fake.calls, ["init", "validate", "plan", "show"])
        self.assertIn("+ module.deploy.aws_s3_bucket.site", out)
        self.assertIn("cost: not estimated here", out)

    def test_no_credential_ever_reaches_a_written_file(self):
        secret = "wJalrXUtnFEMI-K7MDENG-bPxRfiCYEXAMPLEKEY"
        with unittest.mock.patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": secret, "DIGITALOCEAN_TOKEN": secret,
                                                   "LINODE_TOKEN": secret}):
            self.assertEqual(self.plan()[0], 0)
            self.assertEqual(self.g.run("--target", "do", "--kind", "container", "--plan", "--image",
                                        "me/server:1", "--port", 8080, fake=self.fake)[0], 0)
        for f in (self.g.root / "deploy").rglob("*"):
            if f.is_file():
                self.assertNotIn(secret, f.read_text(encoding="utf-8", errors="replace"), f)

    def test_a_site_holding_secrets_is_refused_before_any_tofu_call(self):
        (self.g.site / ".env").write_text("X=1\n", encoding="utf-8")
        (self.g.site / "config.js").write_text('const k = "ghp_' + "a" * 36 + '";\n', encoding="utf-8")
        code, out = self.plan()
        self.assertEqual(code, 1, out)
        self.assertIn(".env: a secret-type file", out)
        self.assertIn("config.js line 1: looks like a GitHub token", out)
        self.assertEqual(self.fake.calls, [])

    def test_a_site_without_index_html_is_refused(self):
        (self.g.site / "index.html").unlink()
        code, out = self.plan()
        self.assertEqual(code, 1, out)
        self.assertIn("no index.html", out)

    def test_apply_needs_the_unchanged_plan(self):
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 1, out)
        self.assertIn("no plan to apply", out)
        self.assertEqual(self.plan()[0], 0)
        # what goes up is the copy taken at plan time (deploy/<target>-<kind>/site): changing it refuses the apply
        (self.g.deploy("aws-static") / "site" / "index.html").write_text("<html>changed</html>\n", encoding="utf-8")
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 1, out)
        self.assertIn("the site copy changed since the plan", out)
        self.assertEqual(self.plan()[0], 0)
        (self.g.deploy("aws-static") / "plan.tfplan").write_bytes(b"someone else's plan")
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 1, out)
        self.assertIn("plan.tfplan changed", out)
        self.assertNotIn("apply", self.fake.calls)

    def test_apply_runs_the_plan_once_and_prints_the_url(self):
        self.assertEqual(self.plan()[0], 0)
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 0, out)
        self.assertIn("is up: https://d111.cloudfront.net/", out)
        self.assertIn("never commit it", out)
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 1, out)                          # the plan was used up
        self.assertEqual(self.fake.calls.count("apply"), 1)

    def test_apply_and_destroy_never_go_ahead_unasked(self):
        self.assertEqual(self.plan()[0], 0)
        with unittest.mock.patch.object(sys, "stdin", io.StringIO("")):
            code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", fake=self.fake)
            self.assertEqual(code, 2, out)
            self.assertIn("pass --yes", out)
            (self.g.deploy("aws-static") / "terraform.tfstate").write_text("{}", encoding="utf-8")
            code, out = self.g.run("--target", "aws", "--kind", "static", "--destroy", fake=self.fake)
            self.assertEqual(code, 2, out)
        self.assertNotIn("apply", self.fake.calls)
        self.assertNotIn("destroy", self.fake.calls)

    def test_destroy_checks_that_nothing_is_left(self):
        code, out = self.g.run("--target", "aws", "--kind", "static", "--destroy", "--yes", fake=self.fake)
        self.assertEqual(code, 1, out)
        self.assertIn("game-kit=ship-test tag", out)               # no state: say how to find leftovers
        d = self.g.deploy("aws-static")
        d.mkdir(parents=True)
        (d / "terraform.tfstate").write_text("{}", encoding="utf-8")
        code, out = self.g.run("--target", "aws", "--kind", "static", "--destroy", "--yes", fake=self.fake)
        self.assertEqual(code, 0, out)
        self.assertIn("the state is empty", out)
        left = FakeTofu(destroy_leaves=["module.deploy.aws_s3_bucket.site"])
        code, out = self.g.run("--target", "aws", "--kind", "static", "--destroy", "--yes", fake=left)
        self.assertEqual(code, 1, out)
        self.assertIn("still lists", out)

    def test_every_deployment_has_a_budget_or_says_it_cannot(self):
        code, out = self.g.run("--target", "aws", "--kind", "static", "--plan", "--site", self.g.site, fake=self.fake)
        self.assertEqual(code, 2, out)
        self.assertIn("needs --alert-email", out)
        for target in ("linode", "do"):
            with self.subTest(target=target):
                code, out = self.g.run("--target", target, "--kind", "static", "--plan", "--site", self.g.site,
                                       fake=self.fake)
                self.assertEqual(code, 0, out)
                self.assertIn("has no budget API", out)

    def test_target_specific_options_are_required(self):
        code, out = self.g.run("--target", "gcp", "--kind", "static", "--plan", "--site", self.g.site,
                               "--alert-email", "me@example.com", fake=self.fake)
        self.assertEqual(code, 2, out)
        self.assertIn("--project and --billing-account", out)
        code, out = self.g.run("--target", "linode", "--kind", "container", "--plan", "--image", "me/s:1",
                               "--port", 80, fake=self.fake)
        self.assertEqual(code, 2, out)
        self.assertIn("needs --domain", out)
        code, out = self.g.run("--target", "aws", "--kind", "container", "--plan", "--alert-email", "me@example.com",
                               fake=self.fake)
        self.assertEqual(code, 2, out)
        self.assertEqual(self.fake.calls, [])

    def test_image_references_for_digitalocean(self):
        split = self.g.ship.split_image
        self.assertEqual(split("me/server:1.2"), ("DOCKER_HUB", "me", "server", "1.2"))
        self.assertEqual(split("docker.io/me/server"), ("DOCKER_HUB", "me", "server", "latest"))
        self.assertEqual(split("ghcr.io/team/game-server:v3"), ("GHCR", "team", "game-server", "v3"))
        with self.assertRaises(self.g.ship.ToolError):
            split("registry.example.com:5000/x/y:1")

    def test_a_failed_plan_leaves_nothing_to_apply_and_names_the_login(self):
        fake = FakeTofu(plan_rc=1, plan_out="Error: No valid credential sources found")
        code, out = self.plan(fake=fake)
        self.assertEqual(code, 1, out)
        self.assertIn("Log in for aws first", out)
        self.assertFalse((self.g.deploy("aws-static") / "plan.tfplan").exists())
        self.assertFalse((self.g.deploy("aws-static") / "ship.json").exists())

    # ---- second-model review of the cloud lane ----
    def test_a_plan_nobody_can_read_is_not_applied(self):
        for show in ((1, "Error: plan file corrupt"), (0, "not json"), (0, "{}")):
            with self.subTest(show=show):
                code, out = self.plan(fake=FakeTofu(show_out=show))
                self.assertEqual(code, 1, out)
                self.assertIn("could not read the plan", out)
                self.assertFalse((self.g.deploy("aws-static") / "plan.tfplan").exists())

    def test_the_site_is_published_from_the_copy_that_was_scanned(self):
        self.assertEqual(self.plan()[0], 0)
        copy = self.g.deploy("aws-static") / "site"
        self.assertTrue((copy / "index.html").is_file())
        inputs = json.loads((self.g.deploy("aws-static") / "terraform.tfvars.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(inputs["site_dir"]), copy)
        # a build running alongside writes a token into the original: the copy, scanned and planned, is what goes up
        (self.g.site / "config.js").write_text('const k = "ghp_' + "a" * 36 + '";\n', encoding="utf-8")
        self.assertFalse((copy / "config.js").exists())
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 0, out)
        # the copy itself is guarded by its digest
        self.assertEqual(self.plan()[0], 1)                     # the token is in the original now: refused
        (self.g.site / "config.js").unlink()
        self.assertEqual(self.plan()[0], 0)
        (copy / "extra.js").write_text("x\n", encoding="utf-8")
        code, out = self.g.run("--target", "aws", "--kind", "static", "--apply", "--yes", fake=self.fake)
        self.assertEqual(code, 1, out)
        self.assertIn("the site copy changed since the plan", out)

    def test_destroy_uses_the_applied_configuration(self):
        fake = FakeTofu()
        self.assertEqual(self.g.run("--target", "aws", "--kind", "container", "--plan", "--image", "me/s:1",
                                    "--port", 80, "--alert-email", "me@example.com", fake=fake)[0], 0)
        self.assertEqual(self.g.run("--target", "aws", "--kind", "container", "--apply", "--yes", fake=fake)[0], 0)
        # a later check with another budget rewrites the deployment without applying it
        self.assertEqual(self.g.run("--target", "aws", "--kind", "container", "--check", "--image", "me/s:2",
                                    "--port", 80, "--alert-email", "me@example.com", "--budget", 99, fake=fake)[0], 0)
        code, out = self.g.run("--target", "aws", "--kind", "container", "--destroy", "--yes", fake=fake)
        self.assertEqual(code, 0, out)
        self.assertIn("destroy uses the applied", out)
        self.assertEqual(fake.destroyed_with["image"], "me/s:1")
        self.assertEqual(fake.destroyed_with["budget_usd"], 10)

    def test_digitalocean_names_regions_per_product(self):
        self.assertEqual(self.g.run("--target", "do", "--kind", "container", "--check", "--image", "me/s:1",
                                    "--port", 80, fake=self.fake)[0], 0)
        self.assertEqual(json.loads((self.g.deploy("do-container") / "terraform.tfvars.json")
                                    .read_text(encoding="utf-8"))["region"], "nyc")
        self.assertEqual(self.g.run("--target", "do", "--kind", "static", "--check", "--site", self.g.site,
                                    fake=self.fake)[0], 0)
        self.assertEqual(json.loads((self.g.deploy("do-static") / "terraform.tfvars.json")
                                    .read_text(encoding="utf-8"))["region"], "nyc3")

    def test_a_linode_server_prints_the_address_its_domain_needs(self):
        fake = FakeTofu(outputs={"url": {"value": "https://game.example.com/"}, "address": {"value": "192.0.2.7"}})
        args = ("--target", "linode", "--kind", "container")
        self.assertEqual(self.g.run(*args, "--plan", "--image", "me/s:1", "--port", 80, "--domain",
                                    "game.example.com", fake=fake)[0], 0)
        self.assertIn('output "address"', (self.g.deploy("linode-container") / "main.tf").read_text(encoding="utf-8"))
        code, out = self.g.run(*args, "--apply", "--yes", fake=fake)
        self.assertEqual(code, 0, out)
        self.assertIn("A record at 192.0.2.7", out)

    def test_no_opentofu_is_an_environment_problem(self):
        with unittest.mock.patch.dict(os.environ, {"TOFU_BIN": ""}), \
                unittest.mock.patch.object(self.g.ship.shutil, "which", lambda name: None):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = self.g.ship.main(["--target", "aws", "--kind", "static", "--check", "--site", str(self.g.site),
                                         "--alert-email", "me@example.com"])
        self.assertEqual(code, 2, out.getvalue())
        self.assertIn("OpenTofu not found", out.getvalue())


@unittest.skipUnless(TOFU, "OpenTofu is not installed (TOFU_BIN or tofu on PATH)")
class RealOpenTofu(unittest.TestCase):
    """The real OpenTofu, offline apart from fetching the providers once: nothing here needs an account."""

    def test_modules_are_formatted(self):
        r = subprocess.run([TOFU, "fmt", "-check", "-recursive", "-no-color", str(HERE / "modules")],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(r.returncode, 0, "unformatted (tofu fmt -recursive tools/cloud/modules):\n" + r.stdout)

    def test_every_generated_deployment_validates(self):
        g = Game()
        try:
            for target in TARGETS:
                for kind, opts in (("static", ["--site", g.site]),
                                   ("container", ["--image", "ghcr.io/me/server:1.0", "--port", 8080,
                                                  "--domain", "game.example.com"])):
                    with self.subTest(target=target, kind=kind):
                        out = io.StringIO()
                        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                            code = g.ship.main(["--target", target, "--kind", kind, "--check", "--tofu", TOFU,
                                                *map(str, opts), *ALL_OPTS])
                        self.assertEqual(code, 0, out.getvalue())
                        self.assertIn("the deployment is valid", out.getvalue())
        finally:
            g.tmp.cleanup()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
