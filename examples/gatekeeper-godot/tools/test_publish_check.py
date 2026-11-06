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
# Usage   : python tools/test_publish_check.py
# Exit    : 0 all pass, 1 a case failed (skips when git is not installed)
# Notes   : Fake secrets are built by concatenation so this file never matches itself.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
