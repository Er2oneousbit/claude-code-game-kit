#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_pixellab.py
# Purpose : Exam for pixellab.py, offline: the HTTP call is replaced by canned responses shaped like PixelLab's
#           OpenAPI spec (v2, read 2026-10-24), so no account, token or generations are used. Checks requests,
#           job polling, saving (PNG check, safe zip extraction), tileset layout, ASSET_LOG rows, error mapping,
#           and that the token never lands in any output. The redirect cases run the real HTTP call against
#           stand-in servers on 127.0.0.1 (still offline); the https -> http case tests the handler directly.
# Usage   : python tools/art/test_pixellab.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import base64
import contextlib
import http.server
import io
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pixellab as pl  # noqa: E402

KEY = "pl_exam_DO_NOT_LEAK_5678"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG = PNG_SIG + b"fake-png-body"
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""


CDN = "https://cdn.pixellab.example"                  # stands in for PixelLab's storage host (not the API host)
TTF = b"\x00\x01\x00\x00" + b"fake-font-body"
CDN_FILES = {"png": PNG, "gif": b"GIF89a fake", "json": b'{"frames": 6}'}


def real_png(w, h):
    """A valid w x h transparent PNG (the tools that read a PNG's size need a real header)."""
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * w for _ in range(h))
    chunk = lambda tag, data: (struct.pack(">I", len(data)) + tag + data  # noqa: E731
                               + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def b64img(data=PNG):
    if data is None:                                   # broken base64, as a misbehaving service might send
        return {"type": "base64", "base64": "not*base64!", "format": "png"}
    return {"type": "base64", "base64": base64.b64encode(data).decode(), "format": "png"}


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class Fake:
    """Stands in for pixellab.http: records calls, answers by path. `jobs` is how many polls say processing."""

    def __init__(self, polls=1, job_status="completed", status=None, body=b'{"detail": "nope"}', zip_members=None,
                 images=2, tiles=3, image_bytes=PNG, object_id="o1"):
        self.calls, self.polls, self.job_status = [], polls, job_status
        self.object_id = object_id
        self.status, self.body = status, body
        self.zip_members = zip_members or {"rotations/south.png": PNG, "rotations/north.png": PNG,
                                           "metadata.json": b"{}"}
        self.images, self.tiles, self.image_bytes = images, tiles, image_bytes

    def __call__(self, method, url, key, body=None):
        self.calls.append((method, url, key, body))
        ok = lambda obj: (200, {}, json.dumps(obj).encode())  # noqa: E731
        if url.startswith(CDN):                                # PixelLab's storage links: no token expected
            return 200, {}, CDN_FILES.get(url.rsplit(".", 1)[-1], PNG)
        path = url[len(pl.API):]
        sync = {"/image-to-pixelart": {"image": b64img(), "usage": {"type": "generations", "generations": 1}},
                "/reduce-colors": {"images": [b64img()], "palette": [], "n_colors": 8},
                "/create-isometric-tile": {"image": b64img(), "usage": {"type": "usd", "usd": 0.01}}}
        if path in sync and not self.status:
            return ok(sync[path])
        queued = {"/vfx": {"background_job_id": "job-vfx", "quoted_generations": 1, "status": "processing"},
                  "/generate-font-pro": {"background_job_id": "job-font", "status": "processing"},
                  "/edit-image-pixen": {"background_job_id": "job-edit", "status": "processing"},
                  "/normal-map": {"background_job_id": "job-nm", "status": "processing"},
                  "/transfer-outfit-v2": {"background_job_id": "job-outfit", "status": "processing"},
                  "/create-tileset-sidescroller": {"background_job_id": "job-3", "tileset_id": "ts-1", "status": "processing"},
                  "/create-tiles-pro": {"background_job_id": "job-tp", "tile_id": "tp1", "status": "processing"},
                  "/create-ui-asset": {"background_job_id": "job-ui", "ui_asset_id": "ui1", "status": "processing"},
                  "/create-1-direction-object": {"background_job_id": "job-o1", "object_id": self.object_id, "status": "processing"},
                  "/create-8-direction-object": {"background_job_id": "job-o8", "object_id": "o8", "status": "processing"},
                  "/map-objects": {"background_job_id": "job-m", "object_id": "m1", "status": "processing"},
                  "/characters/animations": {"background_job_ids": ["job-a1", "job-a2"], "directions": ["south", "east"],
                                             "animation_group_id": "g1", "status": "processing"}}
        if path in queued and not self.status:
            return ok(queued[path])
        resources = {"/ui-assets/ui1": {"id": "ui1", "prompt": "x", "created_at": "x", "status": "completed",
                                        "image_url": f"{CDN}/ui/panel.png"},
                     "/map-objects/m1": {"status": "completed", "object_id": "m1", "download_url": f"{CDN}/m/pie.png"},
                     "/objects/o1": {"id": "o1", "status": "completed", "frame_urls": [f"{CDN}/o/a.png", f"{CDN}/o/b.png"]},
                     "/objects/o-review": {"id": "o-review", "status": "review", "frame_urls": []},
                     "/objects/o-evil": {"id": "o-evil", "status": "completed",
                                         "rotation_urls": {"south": f"{CDN}/o/s.png", "../escaped": f"{CDN}/o/e.png"}},
                     "/objects/o8": {"id": "o8", "status": "completed",
                                     "rotation_urls": {"south": f"{CDN}/o/s.png", "east": f"{CDN}/o/e.png", "north": None}},
                     "/tiles-pro/tp1": {"kind": "roads", "tile_rules": {"pieces": 18},
                                        "storage_urls": {"tiles": [f"{CDN}/t/road_0.png", f"{CDN}/t/road_1.png"]}}}
        if path in resources:
            return ok(resources[path])
        if path == "/balance":
            return ok({"credits": {"type": "usd", "usd": 0.0},
                       "subscription": {"type": "generations", "status": "trial", "plan": "Free trial",
                                        "generations": 37, "total": 40}})
        if self.status:
            return self.status, {}, self.body
        if path == "/create-image-pixflux":
            return ok({"usage": {"type": "generations", "generations": 1}, "image": b64img(self.image_bytes)})
        if path == "/create-character-v3":
            return ok({"usage": {"type": "generations", "generations": 1}, "background_job_id": "job-1",
                       "character_id": "char-1", "status": "processing"})
        if path == "/create-character-with-4-directions":
            return ok({"usage": {"type": "generations", "generations": 1}, "background_job_id": "job-1",
                       "character_id": "char-1", "status": "processing"})
        if path == "/animate-with-text-v3":
            return ok({"background_job_id": "job-2", "status": "processing"})
        if path == "/create-tileset":
            return 202, {}, json.dumps({"background_job_id": "job-3", "tileset_id": "ts-1",
                                        "status": "processing"}).encode()
        if path.startswith("/background-jobs/"):
            if self.polls > 0:
                self.polls -= 1
                return ok({"id": "job", "status": "processing", "created_at": "x", "last_response": {"queue_position": 2}})
            job_last = {
                "job-2": {"images": [b64img() for _ in range(self.images)]},
                "job-vfx": {"files": {"gif": f"{CDN}/fx/boom.gif", "sheet": f"{CDN}/fx/boom.png", "meta": f"{CDN}/fx/boom.json"},
                            "effect_id": "fx1", "name": "boom", "fps": 12, "edit_url": "https://www.pixellab.ai/fx/fx1"},
                "job-font": {"images": [b64img()], "ttf_base64": base64.b64encode(TTF).decode()},
                "job-edit": {"images": [b64img()]},
                "job-nm": {"image": b64img(), "look": {}},
                "job-outfit": {"images": [b64img(), b64img()]},
            }
            last = job_last.get(path.rsplit("/", 1)[-1], {"detail": "boom"}) if self.job_status == "completed" else {"detail": "boom"}
            return ok({"id": "job", "status": self.job_status, "created_at": "x", "last_response": last,
                       "usage": {"type": "generations", "generations": 2}})
        if path == "/characters/char-1/zip":
            return 200, {}, zip_bytes(self.zip_members)
        if path == "/tilesets/ts-1":
            return ok({"tileset": {"total_tiles": self.tiles, "tile_size": {"width": 16, "height": 16},
                                   "tiles": [{"id": f"t{i}", "name": f"tile {i}", "image": b64img(),
                                              "corners": {"NW": "lower", "NE": "upper", "SW": "lower", "SE": "upper"},
                                              "pattern_4x4": {"row_1": [0, 1], "row_2": [0, 1]}} for i in range(self.tiles)]}})
        return 404, {}, b'{"detail": "no such path in the exam"}'


class PixelLabExam(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (self.root / "south.png").write_bytes(PNG)
        self.real = (pl.http, pl.get_key, pl.SLEEP)
        pl.get_key = lambda: KEY
        pl.SLEEP = lambda s: None
        self.cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)
        pl.http, pl.get_key, pl.SLEEP = self.real
        self.tmp.cleanup()

    def run_tool(self, *argv, fake=None):
        pl.http = fake or Fake()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pl.main(list(argv))
        text = out.getvalue() + err.getvalue()
        self.assertNotIn(KEY, text, "the token leaked into the output")
        return rc, text

    def no_key_anywhere(self):
        for f in self.root.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".md", ".txt"):
                self.assertNotIn(KEY, f.read_text(encoding="utf-8", errors="replace"), f"token in {f}")

    def test_check_shows_plan_and_generations_left(self):
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 0)
        self.assertIn("Free trial (trial): 37 of 40 generations left", out)

    def test_missing_token_is_usage_error(self):
        pl.get_key = lambda: None
        rc, out = self.run_tool("check")
        self.assertEqual(rc, 2)
        self.assertIn("PIXELLAB_API_KEY", out)

    def test_dry_run_sends_nothing(self):
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "rusty key", "--size", "32", "--out", "key.png", "--dry-run", fake=fake)
        self.assertEqual(rc, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn('"description": "rusty key"', out)

    def test_image_saves_png_sidecar_and_log_row(self):
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "rusty key", "--size", "32x24", "--no-background",
                                "--out", "assets/key.png", "--log", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "assets/key.png").read_bytes(), PNG)
        sent = [c for c in fake.calls if c[1].endswith("/create-image-pixflux")][0][3]
        self.assertEqual(sent["image_size"], {"width": 32, "height": 24})
        self.assertTrue(sent["no_background"])
        self.assertEqual([c[2] for c in fake.calls], [KEY] * len(fake.calls), "the token goes in every request")
        side = json.loads((self.root / "assets/key.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(side["cost"], "1 generation")
        self.assertEqual(side["plan"], "Free trial (trial)")
        log = (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | art | `assets/key.png` | PixelLab API (/create-image-pixflux)", log)
        self.assertIn("prompt: rusty key", log)
        self.assertIn("commercial use allowed", log)
        evidence = (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("SHA-256", evidence)
        self.no_key_anywhere()

    def test_variants_are_capped_and_numbered(self):
        rc, _ = self.run_tool("image", "--text", "x", "--out", "a.png", "--variants", "9")
        self.assertEqual(rc, 2)
        fake = Fake()
        rc, _ = self.run_tool("image", "--text", "x", "--out", "a.png", "--variants", "2", fake=fake)
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "a_1.png").exists() and (self.root / "a_2.png").exists())

    def test_not_a_png_is_a_service_failure(self):
        rc, out = self.run_tool("image", "--text", "x", "--out", "a.png", fake=Fake(image_bytes=b"<html>oops"))
        self.assertEqual(rc, 1)
        self.assertIn("not a PNG", out)

    def test_existing_output_needs_overwrite(self):
        (self.root / "a.png").write_bytes(PNG)
        rc, out = self.run_tool("image", "--text", "x", "--out", "a.png")
        self.assertEqual(rc, 2)
        self.assertIn("--overwrite", out)

    def test_output_problems_stop_before_spending(self):
        # A folder where one PNG goes, even with --overwrite, and a log without a table: both used to fail after
        # the paid request
        (self.root / "shots.png").mkdir()
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "x", "--out", "shots.png", "--overwrite", fake=fake)
        self.assertEqual(rc, 2, out)
        self.assertIn("is a folder", out)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [], "nothing spent")
        (self.root / "docs/ASSET_LOG.md").write_text("# Asset Log\n", encoding="utf-8")
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "x", "--out", "b.png", "--log", fake=fake)
        self.assertEqual(rc, 2, out)
        self.assertIn("no table", out)
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [], "nothing spent")

    def test_character_polls_then_extracts_the_zip(self):
        fake = Fake(polls=2)
        rc, out = self.run_tool("character", "--text", "old gravekeeper", "--size", "64", "--directions", "4",
                                "--out", "assets/keeper", "--log", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "assets/keeper/rotations/south.png").exists())
        polls = [c for c in fake.calls if "/background-jobs/" in c[1]]
        self.assertEqual(len(polls), 3, "two 'processing' answers, then 'completed'")
        sent = [c for c in fake.calls if c[1].endswith("/create-character-v3")][0][3]
        self.assertEqual(sent["n_directions"], 4)
        side = json.loads((self.root / "assets/keeper/pixellab.gen.json").read_text(encoding="utf-8"))
        self.assertIn("rotations/south.png", side["files"])
        self.assertIn("| A-0001 | sprite | ", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))

    def test_legacy_character_goes_down_to_16_pixels_in_4_directions(self):
        fake = Fake()
        rc, out = self.run_tool("character", "--text", "tiny wizard", "--size", "16", "--directions", "4", "--legacy",
                                "--out", "wiz", fake=fake)
        self.assertEqual(rc, 0, out)
        sent = [c for c in fake.calls if c[1].endswith("/create-character-with-4-directions")][0][3]
        self.assertEqual(sent["image_size"], {"width": 16, "height": 16})
        self.assertTrue((self.root / "wiz/rotations/south.png").exists())
        rc, out = self.run_tool("character", "--text", "x", "--size", "16", "--out", "w2", fake=Fake())
        self.assertEqual(rc, 2, "v3 starts at 32 px")
        rc, out = self.run_tool("character", "--text", "x", "--size", "16", "--legacy", "--directions", "8",
                                "--out", "w3", fake=Fake())
        self.assertEqual(rc, 2, "legacy is 4 directions only")

    def test_zip_member_outside_the_folder_is_refused(self):
        fake = Fake(zip_members={"../../escape.png": PNG})
        rc, out = self.run_tool("character", "--text", "x", "--out", "c", fake=fake)
        self.assertEqual(rc, 1)
        self.assertIn("refusing zip member", out)
        self.assertFalse((self.root.parent / "escape.png").exists())

    def test_failed_job_is_a_service_failure_with_the_reason(self):
        rc, out = self.run_tool("character", "--text", "x", "--out", "c", fake=Fake(job_status="failed"))
        self.assertEqual(rc, 1)
        self.assertIn("boom", out)

    def test_job_that_never_finishes_times_out(self):
        rc, out = self.run_tool("character", "--text", "x", "--out", "c", "--wait", "0", fake=Fake(polls=99))
        self.assertEqual(rc, 1)
        self.assertIn("still processing", out)

    def test_animate_sends_the_frame_and_saves_each_frame(self):
        fake = Fake(images=3)
        rc, out = self.run_tool("animate", "--frame", "south.png", "--action", "walking", "--frames", "8",
                                "--out", "walk", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "walk").glob("*.png")),
                         ["frame_00.png", "frame_01.png", "frame_02.png"])
        sent = [c for c in fake.calls if c[1].endswith("/animate-with-text-v3")][0][3]
        self.assertEqual(base64.b64decode(sent["first_frame"]["base64"]), PNG)
        side = (self.root / "walk/pixellab.gen.json").read_text(encoding="utf-8")
        self.assertNotIn(sent["first_frame"]["base64"], side, "the sidecar records the frame's path, not its bytes")

    def test_animate_checks_its_frame(self):
        (self.root / "notpng.png").write_bytes(b"GIF89a")
        rc, out = self.run_tool("animate", "--frame", "notpng.png", "--action", "x", "--out", "w")
        self.assertEqual(rc, 2)
        self.assertIn("not a PNG", out)

    def test_tileset_saves_tiles_and_their_corners(self):
        rc, out = self.run_tool("tileset", "--lower", "water", "--upper", "sand", "--tile-size", "16",
                                "--out", "tiles", "--log", fake=Fake(tiles=3))
        self.assertEqual(rc, 0, out)
        layout = json.loads((self.root / "tiles/tileset.json").read_text(encoding="utf-8"))
        self.assertEqual(len(layout["tiles"]), 3)
        self.assertEqual(layout["tiles"][0]["corners"]["NE"], "upper")
        self.assertIn("prompt: water / sand", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))

    def test_service_errors_map_to_exit_codes(self):
        for status, code, words in ((401, 2, "rejected the token"), (402, 2, "cannot pay"),
                                    (422, 2, "rejected the request"), (429, 2, "limiting requests"),
                                    (500, 1, "PixelLab failed")):
            rc, out = self.run_tool("image", "--text", "x", "--out", f"e{status}.png", "--overwrite",
                                    fake=Fake(status=status, body=b'{"detail": [{"loc": ["body", "image_size"], "msg": "too big"}]}'))
            self.assertEqual(rc, code, f"{status}: {out}")
            self.assertIn(words, out)
        _, out = self.run_tool("image", "--text", "x", "--out", "v.png", fake=Fake(status=422,
                               body=b'{"detail": [{"loc": ["body", "image_size"], "msg": "too big"}]}'))
        self.assertIn("image_size: too big", out)

    def test_sizes_are_checked_before_spending(self):
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "x", "--size", "800", "--out", "big.png", fake=fake)
        self.assertEqual(rc, 2)
        self.assertEqual(fake.calls, [])

    # ---- the commands added for the paid-plan feature set ------------------------------------------------------
    def cdn_calls(self, fake):
        return [c for c in fake.calls if c[1].startswith(CDN)]

    def test_vfx_downloads_its_files_without_the_token(self):
        fake = Fake()
        rc, out = self.run_tool("vfx", "--text", "piston punch impact", "--out", "fx/punch", "--log", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "fx/punch").iterdir()),
                         ["boom.gif", "boom.json", "boom.png", "pixellab.gen.json", "vfx.json"])
        self.assertTrue(self.cdn_calls(fake))
        self.assertTrue(all(c[2] is None for c in self.cdn_calls(fake)), "the token must never go to a storage link")
        sent = [c for c in fake.calls if c[1].endswith("/vfx")][0][3]
        self.assertEqual(sent["artist"], "lite")
        self.assertEqual(json.loads((self.root / "fx/punch/vfx.json").read_text(encoding="utf-8"))["effect_id"], "fx1")
        self.assertIn("| A-0001 | vfx | ", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))
        self.no_key_anywhere()

    def test_download_link_must_be_https_and_match_its_type(self):
        with self.assertRaises(pl.ServiceError):
            pl.fetch_url("http://cdn.pixellab.example/a.png", KEY, self.root / "a.png")
        pl.http = lambda m, u, k, b=None: (200, {}, b"<html>not a gif</html>")
        with self.assertRaises(pl.ServiceError):
            pl.fetch_url(f"{CDN}/a.gif", KEY, self.root / "a.gif")
        self.assertEqual(pl.safe_name(f"{CDN}/x/..%2F..%2Fevil.png?sig=1", "f.png"), "f.png", "a hostile name falls back")
        self.assertEqual(pl.safe_name(f"{CDN}/x/boom.png?sig=1", "f.png"), "boom.png")

    def test_ui_polls_its_asset_and_saves_one_png(self):
        fake = Fake()
        rc, out = self.run_tool("ui", "--text", "wooden dialog box", "--out", "ui/dialog.png", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "ui/dialog.png").read_bytes(), PNG)
        self.assertTrue((self.root / "ui/dialog.gen.json").exists())
        rc, out = self.run_tool("ui", "--text", "x", "--size", "100", "--out", "ui/small.png", fake=Fake())
        self.assertEqual(rc, 2, "UI panels are 192 to 688 per side")
        rc, out = self.run_tool("ui", "--text", "x", "--out", "ui/folder", fake=Fake())
        self.assertEqual(rc, 2)
        self.assertIn("must be a .png file", out)

    def test_font_writes_a_ttf_and_its_atlas(self):
        rc, out = self.run_tool("font", "--text", "circus poster", "--name", "circus", "--out", "fonts/circus", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "fonts/circus/circus.ttf").read_bytes(), TTF)
        self.assertTrue((self.root / "fonts/circus/circus.png").exists())

    def test_objects_one_and_eight_directions_and_review(self):
        rc, out = self.run_tool("object", "--text", "circus cannon", "--out", "obj/cannon", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "obj/cannon").glob("*.png")), ["frame_00.png", "frame_01.png"])
        rc, out = self.run_tool("object", "--text", "barrel", "--directions", "8", "--size", "48", "--out", "obj/barrel", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "obj/barrel").glob("*.png")), ["east.png", "south.png"])
        rc, out = self.run_tool("object", "--text", "x", "--out", "obj/rev", fake=Fake(object_id="o-review"))
        self.assertEqual(rc, 2)
        self.assertIn("several candidates", out)
        rc, out = self.run_tool("object", "--text", "x", "--directions", "8", "--size", "200", "--out", "obj/big", fake=Fake())
        self.assertEqual(rc, 2, "8-direction objects stop at 168")

    def test_prop_downloads_the_map_object(self):
        fake = Fake()
        rc, out = self.run_tool("prop", "--text", "cream pie", "--out", "props/pie.png", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "props/pie.png").read_bytes(), PNG)
        sent = [c for c in fake.calls if c[1].endswith("/map-objects")][0][3]
        self.assertEqual(sent["view"], "high top-down")

    def test_edit_checks_the_multiple_of_4_rule_first(self):
        (self.root / "ok.png").write_bytes(real_png(32, 32))
        (self.root / "odd.png").write_bytes(real_png(30, 32))
        fake = Fake()
        rc, out = self.run_tool("edit", "--image", "odd.png", "--text", "fist", "--out", "e.png", fake=fake)
        self.assertEqual(rc, 2)
        self.assertIn("multiple of 4", out)
        self.assertEqual(fake.calls, [], "nothing spent on a size PixelLab would reject")
        rc, out = self.run_tool("edit", "--image", "ok.png", "--text", "make the hand a fist", "--out", "e.png", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "e.png").read_bytes(), PNG)
        self.assertFalse((self.root / "e_job").exists(), "the temporary job folder is cleaned up")

    def test_pixelate_sends_both_sizes(self):
        (self.root / "concept.png").write_bytes(real_png(300, 200))
        fake = Fake()
        rc, out = self.run_tool("pixelate", "--image", "concept.png", "--size", "64x48", "--out", "px.png", fake=fake)
        self.assertEqual(rc, 0, out)
        sent = [c for c in fake.calls if c[1].endswith("/image-to-pixelart")][0][3]
        self.assertEqual((sent["image_size"], sent["output_size"]), ({"width": 300, "height": 200}, {"width": 64, "height": 48}))

    def test_fix_runs_sync_and_job_operations(self):
        (self.root / "src.png").write_bytes(real_png(32, 32))
        rc, out = self.run_tool("fix", "--op", "reduce-colors", "--colors", "8", "--image", "src.png", "--out", "f1.png", fake=Fake())
        self.assertEqual(rc, 0, out)
        rc, out = self.run_tool("fix", "--op", "normal-map", "--image", "src.png", "--out", "f2.png", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "f2.png").read_bytes(), PNG)

    def test_sidescroller_tileset_and_topdown_needs_upper(self):
        fake = Fake()
        rc, out = self.run_tool("tileset", "--kind", "sidescroller", "--lower", "stone bricks", "--transition", "moss",
                                "--out", "side", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertTrue([c for c in fake.calls if c[1].endswith("/create-tileset-sidescroller")])
        self.assertIn("Sidescroller", (self.root / "side/tileset.json").read_text(encoding="utf-8"))
        rc, out = self.run_tool("tileset", "--lower", "water", "--out", "td", fake=Fake())
        self.assertEqual(rc, 2)
        self.assertIn("--upper", out)

    def test_iso_tile_and_tiles_pro(self):
        rc, out = self.run_tool("iso-tile", "--text", "mossy block", "--out", "iso", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "iso/tile.png").exists())
        rc, out = self.run_tool("tiles-pro", "--text", "dirt road", "--feature", "roads", "--out", "roads", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "roads").glob("*.png")), ["road_0.png", "road_1.png"])
        self.assertEqual(json.loads((self.root / "roads/tiles_pro.json").read_text(encoding="utf-8"))["kind"], "roads")

    def test_outfit_needs_a_frame_folder_and_hides_images_in_dry_run(self):
        (self.root / "ref.png").write_bytes(real_png(64, 64))
        (self.root / "walk").mkdir()
        for i in range(3):
            (self.root / "walk" / f"f{i}.png").write_bytes(real_png(64, 64))
        rc, out = self.run_tool("outfit", "--reference", "ref.png", "--frames", "walk", "--out", "o", "--dry-run", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertIn("<png image,", out)
        self.assertNotIn("base64", out.replace("<png image", ""), "no raw image data in the dry run")
        rc, out = self.run_tool("outfit", "--reference", "ref.png", "--frames", "walk", "--out", "o", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(list((self.root / "o").glob("frame_*.png"))), 2)
        (self.root / "empty").mkdir()
        rc, out = self.run_tool("outfit", "--reference", "ref.png", "--frames", "empty", "--out", "o2", fake=Fake())
        self.assertEqual(rc, 2)

    def test_animate_character_finds_the_id_and_waits_for_every_direction(self):
        rc, out = self.run_tool("character", "--text", "clown", "--out", "clown", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads((self.root / "clown/pixellab.gen.json").read_text(encoding="utf-8"))["character_id"], "char-1")
        rc, out = self.run_tool("animate-character", "--from", "clown", "--mode", "skeleton-v3", "--out", "x", fake=Fake())
        self.assertEqual(rc, 2)
        self.assertIn("--template", out)
        fake = Fake()
        rc, out = self.run_tool("animate-character", "--from", "clown", "--mode", "skeleton-v3", "--template", "cross-punch",
                                "--directions", "south,east", "--out", "clown_punch", fake=fake)
        self.assertEqual(rc, 0, out)
        sent = [c for c in fake.calls if c[1].endswith("/characters/animations")][0][3]
        self.assertEqual((sent["character_id"], sent["template_animation_id"], sent["directions"]),
                         ("char-1", "cross-punch", ["south", "east"]))
        polled = {c[1].rsplit("/", 1)[-1] for c in fake.calls if "/background-jobs/" in c[1]}
        self.assertEqual(polled, {"job-a1", "job-a2"})
        self.assertTrue((self.root / "clown_punch/rotations/south.png").exists())
        rc, out = self.run_tool("animate-character", "--from", "nowhere", "--template", "walk", "--out", "y", fake=Fake())
        self.assertEqual(rc, 2)
        self.assertIn("--character-id", out)


    # ---- regressions from an adversarial review (Fable, 2026-10-26) ---------------------------------------------
    def test_a_redirect_to_another_host_does_not_carry_the_token(self):
        seen = {}

        class Storage(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"zipdata")

            def log_message(self, *a):
                pass

        storage = http.server.HTTPServer(("127.0.0.1", 0), Storage)

        class Api(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{storage.server_port}/blob")  # another host name
                self.end_headers()

            def log_message(self, *a):
                pass

        api = http.server.HTTPServer(("127.0.0.1", 0), Api)
        for srv in (storage, api):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            status, _, data = pl.http("GET", f"http://127.0.0.1:{api.server_port}/characters/x/zip", KEY)
        finally:
            for srv in (api, storage):
                srv.shutdown()
                srv.server_close()
        self.assertEqual((status, data), (200, b"zipdata"))
        self.assertIsNone(seen.get("auth"), "the token must not follow a redirect to another host")

    def test_a_redirect_to_another_port_on_the_same_host_drops_the_token(self):
        seen = {}

        class Other(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen["auth"] = self.headers.get("Authorization")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"zipdata")

            def log_message(self, *a):
                pass

        other = http.server.HTTPServer(("127.0.0.1", 0), Other)

        class Api(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{other.server_port}/blob")   # same host, other port
                self.end_headers()

            def log_message(self, *a):
                pass

        api = http.server.HTTPServer(("127.0.0.1", 0), Api)
        for srv in (other, api):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            status, _, data = pl.http("GET", f"http://127.0.0.1:{api.server_port}/characters/x/zip", KEY)
        finally:
            for srv in (api, other):
                srv.shutdown()
                srv.server_close()
        self.assertEqual((status, data), (200, b"zipdata"))
        self.assertIsNone(seen.get("auth"), "the token must not follow a redirect to another port")

    def test_a_redirect_from_https_to_http_on_the_same_host_is_refused(self):
        # Met in review: the host-only check kept the token on https -> http (plaintext) to api.pixellab.ai
        for new, rule in ((f"{pl.API}/other", "keep"), ("https://api.pixellab.ai:443/v2/x", "keep"),
                          ("https://api.pixellab.ai:8443/v2/x", "strip"), (f"{CDN}/blob.zip", "strip"),
                          ("http://api.pixellab.ai/v2/x", "refuse"), ("http://api.pixellab.ai:443/v2/x", "refuse")):
            self.assertEqual(pl.redirect_rule(f"{pl.API}/characters/x/zip", new), rule, new)
        req = urllib.request.Request(f"{pl.API}/characters/x/zip", headers={"Authorization": f"Bearer {KEY}"})
        with self.assertRaises(pl.ServiceError):
            pl.KeepKeyOnHost().redirect_request(req, io.BytesIO(), 302, "Found", {}, "http://api.pixellab.ai/v2/y")

    def test_object_direction_names_cannot_leave_the_out_folder(self):
        rc, out = self.run_tool("object", "--text", "x", "--out", "obj/evil", fake=Fake(object_id="o-evil"))
        self.assertEqual(rc, 1, out)
        self.assertIn("not a plain name", out)
        self.assertFalse((self.root / "obj/escaped.png").exists(), "nothing written outside --out")
        self.assertEqual(list((self.root / "obj/evil").glob("*.png")), [], "refused before any download")

    def test_zip_size_and_member_names_are_limited(self):
        bomb = zip_bytes({"rotations/south.png": PNG})
        real_max = pl.MAX_DOWNLOAD
        pl.MAX_DOWNLOAD = 4
        try:
            with self.assertRaises(pl.ServiceError):
                pl.extract_zip(bomb, self.root / "z1")
        finally:
            pl.MAX_DOWNLOAD = real_max
        for bad in ("desktop.ini", "evil.exe", "a.png:stream", ".gitattributes"):
            with self.assertRaises(pl.ServiceError, msg=bad):
                pl.extract_zip(zip_bytes({bad: b"x"}), self.root / "z2")
        self.assertFalse((self.root / "z2" / "desktop.ini").exists())
        with self.assertRaises(pl.ServiceError):
            pl.fetch_url(f"{CDN}/x/desktop.ini", None, self.root / "desktop.ini")

    def test_edit_never_touches_a_folder_named_like_its_temp(self):
        (self.root / "hero.png").write_bytes(real_png(32, 32))
        (self.root / "hero_job").mkdir()
        (self.root / "hero_job" / "my_notes.txt").write_text("keep me", encoding="utf-8")
        rc, out = self.run_tool("edit", "--image", "hero.png", "--text", "fist", "--out", "hero2.png", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "hero_job" / "my_notes.txt").exists())

    def test_zip_still_423_is_waited_for_and_then_fetch_is_offered(self):
        class Busy(Fake):
            def __init__(self, busy, **kw):
                super().__init__(**kw)
                self.busy = busy

            def __call__(self, method, url, key, body=None):
                if url.endswith("/zip") and self.busy > 0:
                    self.busy -= 1
                    self.calls.append((method, url, key, body))
                    return 423, {}, b'{"detail": "Character or animations still being generated"}'
                return super().__call__(method, url, key, body)

        rc, out = self.run_tool("character", "--text", "clown", "--out", "c1", fake=Busy(2))
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "c1/rotations/south.png").exists())
        rc, out = self.run_tool("character", "--text", "clown", "--out", "c2", "--wait", "0", fake=Busy(99, polls=0))
        self.assertEqual(rc, 1)
        self.assertIn("fetch --character-id char-1", out)
        rc, out = self.run_tool("fetch", "--character-id", "char-1", "--out", "c2", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "c2/rotations/south.png").exists())

    def test_several_direction_jobs_add_up_their_cost(self):
        self.run_tool("character", "--text", "clown", "--out", "clown", fake=Fake())
        rc, out = self.run_tool("animate-character", "--from", "clown", "--template", "walk", "--out", "walk", fake=Fake())
        self.assertEqual(rc, 0, out)
        side = json.loads((self.root / "walk/pixellab.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(side["cost"], "4 generations (2 jobs)")

    def test_overwrite_clears_the_previous_run(self):
        self.run_tool("animate", "--frame", "south.png", "--action", "walk", "--out", "w", fake=Fake(images=3))
        rc, out = self.run_tool("animate", "--frame", "south.png", "--action", "walk", "--out", "w", "--overwrite",
                                fake=Fake(images=2))
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "w").glob("*.png")), ["frame_00.png", "frame_01.png"])

    def test_refusals_happen_before_spending(self):
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "x", "--out", "../outside.png", "--log", fake=fake)
        self.assertEqual(rc, 2)
        self.assertIn("outside the project", out)
        self.assertEqual([c for c in fake.calls if "/create-" in c[1]], [], "nothing generated")
        (self.root / "afile").write_text("x", encoding="utf-8")
        fake = Fake()
        rc, out = self.run_tool("character", "--text", "x", "--out", "afile", fake=fake)
        self.assertEqual(rc, 2)
        self.assertEqual([c for c in fake.calls if "/create-" in c[1]], [])
        rc, out = self.run_tool("prop", "--text", "x", "--size", "16", "--out", "p.png", fake=Fake())
        self.assertEqual(rc, 2, "map objects start at 32 px")

    def test_broken_base64_is_a_service_failure(self):
        rc, out = self.run_tool("image", "--text", "x", "--out", "b.png", fake=Fake(image_bytes=None))
        self.assertEqual(rc, 1, out)
        self.assertIn("broken base64", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
