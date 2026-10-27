#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_publish_check.py
# Purpose : Exam for publish_check.py: a clean repo passes, a missing LICENSE,
#           a secret file, a token, a personal path and a non-noreply email are caught,
#           ignored files and doc mentions of token prefixes are not. Unreal's Android File Server token warns
#           only while network connections are on.
# Usage   : python tools/test_publish_check.py
# Exit    : 0 all pass, 1 a case failed (skips when git is not installed)
# Notes   : Fake secrets are built by concatenation so this file never matches itself.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_check  # noqa: E402

FAKE_GH = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_KEY_BLOCK = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"


@unittest.skipUnless(shutil.which("git"), "git not installed")
class PublishCheckExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        (self.root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Game\nTokens look like ghp_... and sk-ant-...\n", encoding="utf-8")
        (self.root / ".gitignore").write_text(".env\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, email="dev@users.noreply.github.com"):
        subprocess.run(["git", "-C", str(self.root), "-c", f"user.email={email}", "-c", "user.name=Dev",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)

    def results(self):
        _, fails, warns = publish_check.run(self.root)
        return " | ".join(fails), " | ".join(warns), fails

    def test_clean_repo_passes(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        fails, warns, raw = self.results()
        self.assertEqual(raw, [], fails)
        self.assertEqual(warns, "")

    def test_missing_license_fails(self):
        (self.root / "LICENSE").unlink()
        self.assertIn("no LICENSE", self.results()[0])

    def test_secret_file_fails_unless_ignored(self):
        (self.root / ".env").write_text("X=1\n", encoding="utf-8")          # ignored: fine
        self.assertNotIn(".env", self.results()[0])
        (self.root / "deploy.pem").write_text("x\n", encoding="utf-8")      # not ignored: caught
        self.assertIn("deploy.pem: secret-type file", self.results()[0])

    def test_example_env_allowed(self):
        (self.root / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
        self.assertNotIn(".env.example", self.results()[0])

    def test_tokens_caught(self):
        (self.root / "config.gd").write_text(f'var t = "{FAKE_GH}"\n', encoding="utf-8")
        (self.root / "id.txt").write_text(FAKE_KEY_BLOCK + "\n", encoding="utf-8")
        fails = self.results()[0]
        self.assertIn("config.gd line 1: looks like a GitHub token", fails)
        self.assertIn("id.txt line 1: looks like a private key block", fails)

    def test_hard_coded_secret_caught_but_placeholder_not(self):
        (self.root / "a.py").write_text('api_key = "' + "q" * 24 + '"\n', encoding="utf-8")
        (self.root / "b.py").write_text('api_key = "<your key here>"\n', encoding="utf-8")
        fails = self.results()[0]
        self.assertIn("a.py line 1", fails)
        self.assertNotIn("b.py", fails)

    def test_home_path_warns(self):
        home = "C:" + "\\Users\\alex"
        (self.root / "notes.md").write_text(f"built in {home}\\proj, see C:\\Users\\<you>\\x\n", encoding="utf-8")
        warns = self.results()[1]
        self.assertIn("notes.md line 1", warns)
        self.assertIn("alex", warns)
        self.assertNotIn("<you>", warns)

    def test_personal_email_in_history_warns(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init", email="alex@example.com")
        self.assertIn("alex@example.com", self.results()[1])

    def test_placeholder_asset_row_warns(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text("| hero.png | PLACEHOLDER | ? |\n", encoding="utf-8")
        self.assertIn("PLACEHOLDER asset row", self.results()[1])

    def test_unreal_android_file_server_token_warns_while_networked(self):
        ini = self.root / "Config" / "DefaultEngine.ini"
        ini.parent.mkdir()
        section = "[/Script/AndroidFileServerEditor.AndroidFileServerRuntimeSettings]\nbEnablePlugin=True\n"
        token = "SecurityToken=" + "77BA" * 8
        ini.write_text(section + "bAllowNetworkConnection=True\n" + token + "\n", encoding="utf-8")
        self.assertIn("Android File Server SecurityToken", self.results()[1])
        ini.write_text(section + "bAllowNetworkConnection=False\n" + token + "\n", encoding="utf-8")
        self.assertNotIn("Android File Server", self.results()[1])
        ini.write_text("[/Script/Other.Settings]\nbAllowNetworkConnection=True\n" + token + "\n", encoding="utf-8")
        self.assertNotIn("Android File Server", self.results()[1])

    def test_not_a_repo_exits_2(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(publish_check.main(["--root", plain]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
