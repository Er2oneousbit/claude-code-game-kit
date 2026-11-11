#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_publish_check.py
# Purpose : Exam for publish_check.py: a clean repo passes, a missing LICENSE,
#           a secret file, a token, a personal path and a non-noreply email are caught,
#           ignored files and doc mentions of token prefixes are not. snake_case secret names (client_secret)
#           and UTF-16 text with a BOM are caught. Unreal's Android File Server token warns
#           only while network connections are on. POSIX home paths warn with or without a
#           trailing slash; text files over the scan cap are listed, media and binaries are not. A .pxo
#           holding an absolute export folder (Pixelorama) warns; a blank or relative one does not.
#           #157: --range scans only the lines a range adds and its commit messages, groups findings per commit,
#           catches local-only, scratch and secret files a commit adds (renames too, not deletions), warns on a
#           missing --trailer and a personal email once; --terms (plain whole words or re: lines, from the option
#           or PUBLISH_CHECK_TERMS) hits text, file names and commit messages without printing the term, and FAILs
#           when the list itself would be published; --style catches em dashes; bad ranges and lists exit 2.
# Usage   : python tools/test_publish_check.py
# Exit    : 0 all pass, 1 a case failed (skips when git is not installed)
# Notes   : Fake secrets are built by concatenation so this file never matches itself.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_check  # noqa: E402

FAKE_GH = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_KEY_BLOCK = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"


class RepoCase(unittest.TestCase):
    """A fresh git repo with a LICENSE, a README and a .gitignore, per test."""

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


@unittest.skipUnless(shutil.which("git"), "git not installed")
class PublishCheckExam(RepoCase):
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

    def test_cloud_key_shapes_caught(self):
        # #252: Azure and GCP keys (built from parts here, so this file itself holds none)
        b64 = "Ab0+/" * 17 + "x"                       # 86 base64 characters
        cases = {
            "az1.txt": ("abc" + "7Q~" + "d" * 32, "Azure client secret"),
            "az2.txt": ("DefaultEndpointsProtocol=https;AccountName=game;AccountKey=" + b64 + "==;", "Azure storage account key"),
            "az3.txt": ("https://g.blob.core.windows.net/c?sv=2024-11-04&ss=b&srt=o&sp=r&sig=" + "aB3%2F" * 8, "Azure SAS token"),
            "gc1.json": ('{"type": "service_account", "private_key_id": "' + "0a" * 20 + '"}', "GCP service account key"),
            "gc2.json": ('{"client_secret": "' + "GOCSPX" + "-" + "Ab_9" * 7 + '"}', "Google OAuth client secret"),
        }
        for name, (text, _) in cases.items():
            (self.root / name).write_text(text + "\n", encoding="utf-8")
        fails = self.results()[0]
        for name, (_, label) in cases.items():
            with self.subTest(name=name):
                self.assertIn(f"{name} line 1: looks like a {label}", fails)

    def test_cloud_shapes_spare_prose(self):
        (self.root / "notes.md").write_text("Azure secrets contain Q~ and Google ones start GOCSPX-; set AccountKey= "
                                            "in the portal, never here.\n", encoding="utf-8")
        self.assertNotIn("notes.md", self.results()[0])

    def test_hard_coded_secret_caught_but_placeholder_not(self):
        (self.root / "a.py").write_text('api_key = "' + "q" * 24 + '"\n', encoding="utf-8")
        (self.root / "b.py").write_text('api_key = "<your key here>"\n', encoding="utf-8")
        fails = self.results()[0]
        self.assertIn("a.py line 1", fails)
        self.assertNotIn("b.py", fails)

    def test_snake_case_secret_names_caught(self):
        value = '"' + "Zq9" * 8 + '"'
        lines = {"c.py": "client_secret = " + value, "d.py": "AWS_SECRET_ACCESS_KEY = " + value,
                 "e.py": "access_token = " + value, "f.py": "db_password = " + value,
                 "g.gd": "const API_KEY_PROD := " + value}
        for name, line in lines.items():
            (self.root / name).write_text(line + "\n", encoding="utf-8")
        fails = self.results()[0]
        for name in lines:
            self.assertIn(f"{name} line 1: looks like a hard-coded secret", fails)

    def test_secret_word_in_ordinary_code_not_caught(self):
        (self.root / "ui.gd").write_text('var password_field_label = "Password"\n'
                                         'var secretary_name = "' + "Q" * 20 + '"\n'
                                         'const TOKEN_URL = "https://auth.example.com/oauth/token"\n'
                                         'var secret_door = "res://scenes/secret_door.tscn"\n', encoding="utf-8")
        self.assertNotIn("ui.gd", self.results()[0])

    def test_utf16_text_is_scanned(self):
        # Windows PowerShell 5 writes UTF-16LE with a BOM; the NUL bytes must not make it look binary
        (self.root / "key16.txt").write_bytes(b"\xff\xfe" + (FAKE_KEY_BLOCK + "\r\n").encode("utf-16-le"))
        (self.root / "key16be.txt").write_bytes(b"\xfe\xff" + (FAKE_KEY_BLOCK + "\n").encode("utf-16-be"))
        (self.root / "key8.txt").write_bytes(b"\xef\xbb\xbf" + (FAKE_KEY_BLOCK + "\n").encode("utf-8"))
        (self.root / "blob.bin").write_bytes(b"\x00\x01" + FAKE_KEY_BLOCK.encode("utf-8"))   # no BOM: still binary
        fails = self.results()[0]
        for name in ("key16.txt", "key16be.txt", "key8.txt"):
            self.assertIn(f"{name} line 1: looks like a private key block", fails)
        self.assertNotIn("blob.bin", fails)

    def test_home_path_warns(self):
        home = "C:" + "\\Users\\alex"
        (self.root / "notes.md").write_text(f"built in {home}\\proj\n", encoding="utf-8")
        # the placeholder on its own line: one search per line stopped at alex, so it was never tested (#239)
        (self.root / "howto.md").write_text("see C:\\Users\\<you>\\x\n", encoding="utf-8")
        warns = self.results()[1]
        self.assertIn("notes.md line 1", warns)
        self.assertIn("alex", warns)
        self.assertNotIn("howto.md", warns)

    def test_posix_home_path_warns_without_a_trailing_slash(self):
        lines = {"a.sh": "cd /home/" + "alice", "b.md": "see `/Users/" + "alice` here", "c.txt": "x='/home/" + "alice'",
                 "d.sh": "cd /home/" + "alice/proj", "e.txt": "/Users/" + "alice and more"}
        for name, line in lines.items():
            (self.root / name).write_text(line + "\n", encoding="utf-8")
        (self.root / "f.txt").write_text("homes live under /home/ and /Users/<you>/ or /home/{name}\n", encoding="utf-8")
        warns = self.results()[1]
        for name in lines:
            self.assertIn(f"{name} line 1", warns)
        self.assertNotIn("f.txt", warns)

    def test_large_text_file_reported_as_not_scanned(self):
        big = publish_check.MAX_TEXT_SCAN + 10
        (self.root / "dump.log").write_bytes(b"a" * big)
        (self.root / "big16.txt").write_bytes(b"\xff\xfe" + b"a\x00" * (big // 2))     # UTF-16 text: NULs, a BOM
        (self.root / "hero.png").write_bytes(b"b" * big)                              # media: expected to be big
        (self.root / "blob.data").write_bytes(b"\x00\x01" * (big // 2))               # binary: NUL near the start
        (self.root / "small.log").write_bytes(b"a" * 100)
        warns = self.results()[1]
        self.assertIn("not content-scanned (over 2 MB): dump.log", warns)
        self.assertIn("not content-scanned (over 2 MB): big16.txt", warns)
        for name in ("hero.png", "blob.data", "small.log"):
            self.assertNotIn(name, warns)

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

    def test_pixelorama_export_folder_warns(self):
        # Pixelorama keeps the folder you last exported to inside each .pxo, in a zip the text scan cannot read (#69)
        art = self.root / "art"
        art.mkdir()
        folders = {"home.pxo": '"C:/' + 'Users/alex/Desktop/out"', "posix.pxo": '"/home/' + 'alex/out"',
                   "blank.pxo": '""', "relative.pxo": '"exports"', "none.pxo": None}
        for name, folder in folders.items():
            data = {"pxo_version": 7, "export_profile": {"file_name": '"x"'}}
            if folder is None:
                data.pop("export_profile")
            else:
                data["export_profile"]["directory_path"] = folder
            with zipfile.ZipFile(art / name, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("data.json", json.dumps(data))
                z.writestr("image_data/frames/1/layer_1", bytes(64))
        (art / "broken.pxo").write_bytes(b"not a zip")
        warns = self.results()[1]
        self.assertIn("art/home.pxo: Pixelorama saved the folder you last exported to in it, C:/" + "Users/alex", warns)
        self.assertIn("art/posix.pxo: Pixelorama saved", warns)
        for name in ("blank.pxo", "relative.pxo", "none.pxo", "broken.pxo"):
            self.assertNotIn(name, warns)

    def test_not_a_repo_exits_2(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(publish_check.main(["--root", plain]), 2)

    # ---- review fixes (#238, #239) --------------------------------------------------------------------------
    def test_an_unquoted_secret_in_a_config_file_fails(self):
        """#238: the secret rule needed a quoted value; an AWS credentials file passed."""
        aws = (self.root / ".aws")
        aws.mkdir()
        (aws / "credentials").write_text("[default]\naws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCY"
                                         "EXAMPLEKEY\n", encoding="utf-8")
        (self.root / "app.ini").write_text("token = ${TOKEN_FROM_THE_ENVIRONMENT}\npassword = changeme\n",
                                           encoding="utf-8")
        (self.root / "main.py").write_text("api_key = API_KEY_V2_SETTINGS_NAME\n", encoding="utf-8")
        fails = self.results()[0]
        self.assertIn(".aws/credentials line 2: looks like a hard-coded secret (unquoted)", fails)
        self.assertNotIn("app.ini", fails)
        self.assertNotIn("main.py", fails)

    def test_a_home_path_before_punctuation_warns(self):
        """#238: the user name had to end at /, a space or a quote: [x](/home/<name>) and /home/<name>, passed."""
        (self.root / "a.md").write_text("[built](/home/" + "alice)\n", encoding="utf-8")
        (self.root / "b.md").write_text("from /home/" + "alice, then\n", encoding="utf-8")
        warns = self.results()[1]
        self.assertIn("a.md line 1", warns)
        self.assertIn("b.md line 1", warns)

    def test_a_symlinks_own_text_is_checked(self):
        """#238: a dangling symlink was skipped, yet git publishes the path it points at."""
        import os
        link = self.root / "notes.md"
        try:
            os.symlink("/home/" + "alice/private/notes.md", str(link))
        except (OSError, NotImplementedError):
            self.skipTest("cannot make a symlink here")
        warns = self.results()[1]
        self.assertIn("notes.md (symlink)", warns)

    @unittest.skipIf(sys.platform == "win32", "file names are UTF-16 on Windows")
    def test_a_file_name_that_is_not_utf8_is_still_checked(self):
        """#238: names were decoded with "replace", so .env.\\xff became a path that does not exist."""
        import os
        name = os.fsdecode(b".env.\xff")
        try:
            (self.root / name).write_text("X=1\n", encoding="utf-8")
        except OSError:
            self.skipTest("the file system refuses the name")
        self.assertIn("secret-type file", self.results()[0])

    def test_lfs_without_git_lfs_is_size_checked(self):
        """#239: filter=lfs alone waived the 100 MB check; without Git LFS the raw file is committed."""
        (self.root / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
        with open(self.root / "big.bin", "wb") as fh:
            fh.truncate(publish_check.GITHUB_HARD_LIMIT + 1024)
        self.git("config", "filter.lfs.clean", "")
        fails, warns, _ = self.results()
        self.assertIn("big.bin: 100 MB and not in LFS", fails)
        self.assertIn("Git LFS is not set up", warns)
        self.git("config", "filter.lfs.clean", "git-lfs clean -- %f")
        self.assertNotIn("big.bin", self.results()[0])

    def test_an_unreadable_file_is_reported_not_passed(self):
        """#239: a file that could not be read scanned as clean."""
        (self.root / "config.ini").write_text('api_key = "' + 'abcdefghijklmnop"\n', encoding="utf-8")
        real = Path.read_bytes

        def deny(path):
            if path.name == "config.ini":
                raise PermissionError(13, "Permission denied")
            return real(path)
        Path.read_bytes = deny
        try:
            warns = self.results()[1]
        finally:
            Path.read_bytes = real
        self.assertIn("config.ini: could not be read", warns)

    def test_an_encrypted_pxo_is_a_warning_not_exit_2(self):
        """#239: an encrypted data.json raised RuntimeError, and main() said "not a usable git repository", exit 2."""
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("data.json", json.dumps({"export_profile": {"directory_path": '"exports"'}}))
        raw = bytearray(buf.getvalue())
        for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):   # set the "encrypted" bit in both headers
            i = raw.index(sig)
            raw[i + off] |= 1
        (self.root / "art.pxo").write_bytes(bytes(raw))
        self.assertIn("art.pxo: its data.json cannot be read", self.results()[1])
        self.assertIn(publish_check.main(["--root", str(self.root)]), (0, 1))


EM = "\u2014"     # written as an escape: the kit's own files carry no em dash


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RangeAndTermsExam(RepoCase):
    """#157: --range A..B (added lines, messages, files a commit must not add), --terms, --style, --trailer."""

    def setUp(self):
        super().setUp()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.private = tempfile.TemporaryDirectory()           # the term list lives outside the repo
        self.terms = Path(self.private.name) / "private-terms.txt"
        self.terms.write_text("# private names\n\nKraken\nre:proj(ect)?[-_ ]?nebula\n", encoding="utf-8")

    def tearDown(self):
        self.private.cleanup()
        super().tearDown()

    def commit(self, files, message, email="dev@users.noreply.github.com", force=()):
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if text is None:
                path.unlink()
            else:
                path.write_bytes(text.encode("utf-8"))
        self.git("add", "-A")
        for name in force:
            self.git("add", "-f", name)
        self.git("commit", "-q", "-m", message, email=email)

    def main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = publish_check.main(["--root", str(self.root)] + list(argv))
        return code, out.getvalue()

    # ---- --range ----
    def test_only_lines_the_range_adds_are_scanned(self):
        self.commit({"old.gd": f'var t = "{FAKE_GH}"\n'}, "old token, before the range")
        self.git("tag", "start")
        self.commit({"new.gd": "var a = 1\n" + f'var t = "{FAKE_GH}"\n', "old.gd": f'var t = "{FAKE_GH}"\nvar b = 2\n'},
                    "add new.gd")
        code, out = self.main("--range", "start..HEAD")
        self.assertEqual(code, 1, out)
        self.assertIn("new.gd line 2: looks like a GitHub token", out)
        self.assertNotIn("old.gd", out)                    # its token came before the range; only "var b" is new
        self.assertIn("1 commit(s) in start..HEAD", out)
        self.assertIn("add new.gd: 1 FAIL, 0 WARN", out)

    def test_findings_are_grouped_per_commit_with_hash_and_subject(self):
        self.git("tag", "start")
        self.commit({"a.txt": "fine\n"}, "first clean commit")
        self.commit({"b.md": "built in /home/" + "alice/proj\n"}, "second adds a path")
        code, out = self.main("--range", "start..HEAD")
        self.assertEqual(code, 0, out)                     # a home path WARNs, it does not FAIL
        short = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"], capture_output=True,
                               encoding="utf-8").stdout.strip()
        self.assertIn(f"  {short} second adds a path: 0 FAIL, 1 WARN", out)
        self.assertIn("first clean commit: 0 FAIL, 0 WARN", out)
        self.assertIn("b.md line 1: /home/" + "alice", out)

    def test_commit_messages_are_scanned(self):
        self.git("tag", "start")
        self.commit({"a.txt": "x\n"}, "fix login\n\nused token " + FAKE_GH + " from C:\\Users\\" + "alex\\keys")
        code, out = self.main("--range", "start..HEAD")
        self.assertEqual(code, 1, out)
        self.assertIn("commit message line 3: looks like a GitHub token", out)
        self.assertIn("commit message line 3: C:\\Users\\" + "alex", out)

    def test_files_a_commit_must_not_add(self):
        self.git("tag", "start")
        self.commit({"CLAUDE.local.md": "my machine\n", "captures/progress/01.png": "png", ".env": "X=1\n",
                     "tools/notes.log": "log\n", "src/ok.gd": "var a = 1\n"}, "oops", force=(".env", "CLAUDE.local.md"))
        code, out = self.main("--range", "start..HEAD")
        self.assertEqual(code, 1, out)
        self.assertIn("CLAUDE.local.md: a local-only or scratch file", out)
        self.assertIn("captures/progress/01.png: a local-only or scratch file", out)
        self.assertIn("tools/notes.log: a local-only or scratch file", out)
        self.assertIn(".env: secret-type file in the commit", out)
        self.assertNotIn("src/ok.gd", out)
        self.git("tag", "mid")
        self.commit({"CLAUDE.local.md": None}, "remove it")          # a deletion publishes nothing new
        self.assertEqual(self.main("--range", "mid..HEAD")[0], 0)

    def test_a_rename_onto_a_local_only_name_is_caught(self):
        self.commit({"notes.md": "a\nb\nc\nd\n"}, "notes")
        self.git("tag", "start")
        self.git("mv", "notes.md", "CLAUDE.local.md")
        self.git("commit", "-q", "-m", "rename")
        code, out = self.main("--range", "start..HEAD")
        self.assertIn("CLAUDE.local.md: a local-only or scratch file", out)

    def test_trailer_and_email_warnings(self):
        self.git("tag", "start")
        self.commit({"a.txt": "1\n"}, "with trailer\n\nCo-Authored-By: Helper <noreply@example.com>")
        self.commit({"b.txt": "2\n"}, "without trailer", email="alex@example.com")
        self.commit({"c.txt": "3\n"}, "again without\n\nCo-Authored-By: Helper <noreply@example.com>",
                    email="alex@example.com")
        code, out = self.main("--range", "start..HEAD", "--trailer", "co-authored-by:")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("no 'co-authored-by:' trailer"), 1, out)
        self.assertEqual(out.count("email alex@example.com"), 1, out)      # reported once, at its first commit

    def test_bad_ranges_and_options_exit_2(self):
        for argv in (["--range", "HEAD"], ["--range", "nope..HEAD"], ["--trailer", "X"], ["--range=-x..HEAD"]):
            code, out = self.main(*argv)
            self.assertEqual(code, 2, (argv, out))
            self.assertNotIn("Traceback", out)
        code, out = self.main("--commits", "HEAD..HEAD")                    # the issue's spelling works too
        self.assertEqual(code, 0, out)
        self.assertIn("0 commit(s)", out)

    def test_added_lines_parser(self):
        patch = ("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,0 +1,2 @@\n+++ not a header\n+second\n"
                 "diff --git \"a/sp\\303\\251c\\tial\" \"b/sp\\303\\251c\\tial\"\nnew file mode 100644\n--- /dev/null\n"
                 "+++ \"b/sp\\303\\251c\\tial\"\n@@ -0,0 +1 @@\n+only\n\\ No newline at end of file\n"
                 "diff --git a/gone b/gone\ndeleted file mode 100644\n--- a/gone\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
                 "diff --git a/y b/y\n--- a/y\n+++ b/y\n@@ -5,2 +5 @@\n-a\n-b\n+c\r\n")
        self.assertEqual(list(publish_check.added_lines(patch)),
                         [("x", 1, "++ not a header"), ("x", 2, "second"), ("sp\u00e9c\tial", 1, "only"), ("y", 5, "c")])

    # ---- --terms ----
    def test_private_terms_in_text_names_and_history(self):
        self.commit({"a.txt": "x\n"}, "wip on the kraken boss")
        (self.root / "story.md").write_text("The KRAKEN rises.\nkrakens are fine\n", encoding="utf-8")
        (self.root / "coral_kraken.gd").write_text("var a = 1\n", encoding="utf-8")
        (self.root / "b.txt").write_text("see Project-Nebula and projnebula\n", encoding="utf-8")
        code, out = self.main("--terms", str(self.terms))
        self.assertEqual(code, 1, out)
        self.assertIn("story.md line 1: private term (terms file line 3)", out)
        self.assertNotIn("story.md line 2", out)                      # whole words only
        self.assertIn("coral_kraken.gd: its path contains a private term (terms file line 3)", out)
        self.assertIn("b.txt line 1: private term (terms file line 4)", out)
        self.assertIn("message: private term (terms file line 3)", out)
        self.assertIn("2 private term(s) checked", out)
        for line in out.splitlines():                                  # the terms are never printed
            if "private term" in line:
                self.assertNotRegex(line.lower(), r"kraken\b(?!\.gd)|nebula")

    def test_terms_from_the_environment_and_in_a_range(self):
        self.git("tag", "start")
        self.commit({"lore.md": "the kraken\n"}, "lore")
        os.environ[publish_check.TERMS_ENV] = str(self.terms)
        try:
            code, out = self.main("--range", "start..HEAD")
        finally:
            del os.environ[publish_check.TERMS_ENV]
        self.assertEqual(code, 1, out)
        self.assertIn("lore.md line 1: private term (terms file line 3)", out)

    def test_the_term_list_itself_must_not_be_published(self):
        inside = self.root / ".private-terms.txt"
        inside.write_text("Kraken\n", encoding="utf-8")
        code, out = self.main("--terms", str(inside))
        self.assertIn(".private-terms.txt: the private term list itself would be published", out)
        self.assertEqual(out.count("private term (terms file line 1)"), 0, out)      # the list is not scanned
        (self.root / ".gitignore").write_text(".env\n.private-terms.txt\n", encoding="utf-8")
        code, out = self.main("--terms", str(inside))
        self.assertEqual(code, 0, out)
        self.git("tag", "start")
        self.git("add", "-f", ".private-terms.txt")
        self.git("commit", "-q", "-m", "oops")
        code, out = self.main("--range", "start..HEAD", "--terms", str(inside))
        self.assertIn(".private-terms.txt: commits the private term list itself", out)

    def test_bad_terms_files_exit_2(self):
        bad = Path(self.private.name) / "bad.txt"
        for text, words in (("re:(unclosed\n", "line 1: not a valid regular expression"),
                            ("ok\nre:x*\n", "line 2: the regular expression matches empty text")):
            bad.write_text(text, encoding="utf-8")
            code, out = self.main("--terms", str(bad))
            self.assertEqual(code, 2, out)
            self.assertIn(words, out)
        code, out = self.main("--terms", str(Path(self.private.name) / "missing.txt"))
        self.assertEqual(code, 2, out)
        self.assertIn("cannot read the terms file", out)

    # ---- --style ----
    def test_style_flags_em_dashes_only_when_asked(self):
        (self.root / "notes.md").write_text(f"fast {EM} and loud\n", encoding="utf-8")
        self.assertEqual(self.main()[0], 0)
        code, out = self.main("--style")
        self.assertEqual(code, 1, out)
        self.assertIn("notes.md line 1: an em dash", out)
        self.git("tag", "start")
        self.commit({"x.md": "ok\n"}, f"subject {EM} with a dash")
        code, out = self.main("--range", "start..HEAD", "--style")
        self.assertIn("commit message line 1: an em dash", out)
        self.assertIn("notes.md line 1: an em dash", out)               # notes.md is added in that commit too


if __name__ == "__main__":
    unittest.main(verbosity=1)
