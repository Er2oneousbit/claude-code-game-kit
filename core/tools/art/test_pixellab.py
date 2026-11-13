#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_pixellab.py
# Purpose : Exam for pixellab.py, offline: the HTTP call is replaced by canned responses shaped like PixelLab's
#           OpenAPI spec (v2, read 2026-10-24), so no account, token or generations are used. Checks requests,
#           job polling, saving (PNG check, safe zip extraction), tileset layout, ASSET_LOG rows, error mapping,
#           and that the token never lands in any output. The redirect cases run the real HTTP call against
#           stand-in servers on 127.0.0.1 (still offline); the https -> http case tests the handler directly.
#           The Pro Flash, style image, quote and last-frame cases follow the spec as read 2026-11-13.
# Usage   : python tools/art/test_pixellab.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): Pro Flash, style images, --quote, pinned last
#           and end frames (#16)
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
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pixellab as pl  # noqa: E402
import image_diff  # noqa: E402  (tools/, on the path once pixellab is imported: reads the saved PNGs)

KEY = "pl_exam_DO_NOT_LEAK_5678"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def real_png(w, h, px=None):
    """A valid w x h RGBA PNG (the tools that read a PNG's size need a real header): transparent, or px(x, y) gives
    each pixel's (r, g, b, a)."""
    px = px or (lambda x, y: (0, 0, 0, 0))
    raw = b"".join(b"\x00" + b"".join(bytes(px(x, y)) for x in range(w)) for y in range(h))
    chunk = lambda tag, data: (struct.pack(">I", len(data)) + tag + data  # noqa: E731
                               + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = real_png(1, 1)   # a whole PNG: the tool refuses a bare signature or a cut download (#31)
LOG = """# Asset Log

| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | AI-assisted? | Modified? | Date added | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | | | | | | | no | no | 2026-01-01 | |

## Rules
"""


CDN = "https://cdn.pixellab.example"                  # stands in for PixelLab's storage host (not the API host)
TTF = b"\x00\x01\x00\x00" + b"fake-font-body"
CDN_FILES = {"png": PNG, "gif": b"GIF89a fake", "json": b'{"frames": 6}'}


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
                 images=2, tiles=3, image_bytes=PNG, object_id="o1", fix_bytes=PNG,
                 job_usage=(("type", "generations"), ("generations", 2)), pf_object="o8"):
        self.calls, self.polls, self.job_status = [], polls, job_status
        self.job_usage = dict(job_usage) if job_usage else None
        self.object_id, self.pf_object = object_id, pf_object
        self.status, self.body = status, body
        self.zip_members = zip_members or {"rotations/south.png": PNG, "rotations/north.png": PNG,
                                           "metadata.json": b"{}"}
        self.images, self.tiles, self.image_bytes = images, tiles, image_bytes
        self.fix_bytes = fix_bytes

    def __call__(self, method, url, key, body=None):
        self.calls.append((method, url, key, body))
        ok = lambda obj: (200, {}, json.dumps(obj).encode())  # noqa: E731
        if url.startswith(CDN):                                # PixelLab's storage links: no token expected
            return 200, {}, CDN_FILES.get(url.rsplit(".", 1)[-1], PNG)
        path = url[len(pl.API):]
        sync = {"/image-to-pixelart": {"image": b64img(), "usage": {"type": "generations", "generations": 1}},
                "/reduce-colors": {"images": [b64img()], "palette": [], "n_colors": 8},
                "/create-isometric-tile": {"image": b64img(), "usage": {"type": "usd", "usd": 0.01}},
                # unzoom and correct as seen live 2026-11-04: both answer at once
                "/unzoom": {"usage": {"type": "generations", "generations": 0.1}, "image": b64img(self.fix_bytes),
                            "original_size": {"width": 256, "height": 256}, "unzoomed_size": {"width": 32, "height": 32},
                            "zoom_factor_detected": 8.0},
                "/correct-pixelart": {"usage": {"type": "generations", "generations": 0.1},
                                      "images": [b64img(self.fix_bytes)]}}
        if path in sync and not self.status:
            return ok(sync[path])
        queued = {"/vfx": {"background_job_id": "job-vfx", "quoted_generations": 1, "status": "processing"},
                  "/generate-font-pro": {"background_job_id": "job-font", "status": "processing"},
                  "/edit-image-pixen": {"background_job_id": "job-edit", "status": "processing"},
                  "/normal-map": {"background_job_id": "job-nm", "status": "processing"},
                  "/transfer-outfit-v2": {"background_job_id": "job-outfit", "status": "processing"},
                  "/create-tileset-sidescroller": {"background_job_id": "job-3", "tileset_id": "ts-1", "status": "processing"},
                  "/create-tiles-pro": {"background_job_id": "job-tp", "tile_id": "tp1", "status": "processing"},
                  # ui and objects as seen live 2026-11-04: "usage" is null here, only their job reports the cost
                  "/create-ui-asset": {"usage": None, "background_job_id": "job-ui", "ui_asset_id": "ui1",
                                       "status": "processing"},
                  "/create-1-direction-object": {"usage": None, "background_job_id": "job-o1", "object_id": self.object_id,
                                                 "status": "queued", "n_frames": 16},
                  "/create-8-direction-object": {"background_job_id": "job-o8", "object_id": "o8", "status": "processing"},
                  "/map-objects": {"usage": None, "background_job_id": "job-m", "object_id": "m1", "status": "processing"},
                  "/characters/animations": {"background_job_ids": ["job-a1", "job-a2"], "directions": ["south", "east"],
                                             "animation_group_id": "g1", "status": "processing"},
                  # Pro Flash, shaped like PixelLab's API spec (read 2026-11-13): every one answers 202 with a job
                  "/create-image-pro-flash": {"usage": None, "background_job_id": "job-pf", "image_id": "img1",
                                              "source_image_id": "src1", "status": "processing",
                                              "image_size": {"width": 32, "height": 32}, "estimated_generations": 5,
                                              "pricing_provisional": True},
                  "/edit-image-pro-flash": {"usage": None, "background_job_id": "job-pf-url", "image_id": "img2",
                                            "source_image_id": "src2", "status": "processing",
                                            "image_size": {"width": 32, "height": 32}, "estimated_generations": 5},
                  "/image-to-pixelart-pro-flash": {"usage": None, "background_job_id": "job-pf", "image_id": "img3",
                                                   "source_image_id": "src3", "status": "processing",
                                                   "estimated_generations": 6},
                  "/create-character-pro-flash": {"usage": None, "background_job_id": "job-1", "character_id": "char-1",
                                                  "status": "processing", "estimated_generations": 6,
                                                  "first_direction_generated": True},
                  "/create-object-pro-flash": {"usage": None, "background_job_id": "job-opf", "object_id": self.pf_object,
                                               "status": "processing", "estimated_generations": 6,
                                               "first_direction_generated": True}}
        if path in queued and not self.status:
            return ok(queued[path])
        resources = {"/ui-assets/ui1": {"id": "ui1", "prompt": "x", "created_at": "x", "status": "completed",
                                        "image_url": f"{CDN}/ui/panel.png"},
                     "/map-objects/m1": {"status": "completed", "object_id": "m1", "download_url": f"{CDN}/m/pie.png"},
                     "/objects/o1": {"id": "o1", "status": "completed", "frame_urls": [f"{CDN}/o/a.png", f"{CDN}/o/b.png"]},
                     # a 1-direction object of 85 px or less, as seen live 2026-11-04: candidates in "review"
                     "/objects/o-review": {"id": "o-review", "status": "review", "directions": 1,
                                           "rotation_urls": {"south": None, "north": None},
                                           "storage_urls": {f"frame_{i}": f"{CDN}/o/rotations/frame_{i}.png" for i in range(3)},
                                           "frame_urls": [f"{CDN}/o/rotations/frame_{i}.png" for i in range(3)]},
                     "/objects/o-review-empty": {"id": "o-review-empty", "status": "review", "storage_urls": {},
                                                 "frame_urls": None},
                     "/objects/o-evil": {"id": "o-evil", "status": "completed",
                                         "rotation_urls": {"south": f"{CDN}/o/s.png", "../escaped": f"{CDN}/o/e.png"}},
                     # a 1-direction Pro Flash object as seen live 2026-11-13: null rotations, one "unknown" link
                     "/objects/o-pf1": {"id": "o-pf1", "status": "completed", "directions": 1,
                                        "rotation_urls": {"south": None, "east": None},
                                        "storage_urls": {"unknown": f"{CDN}/o/rotations/unknown.png"}, "frame_urls": None,
                                        "style_settings": {"generation_mode": "pro_flash", "source_image_id": "src-o"}},
                     "/objects/o8": {"id": "o8", "status": "completed",
                                     "rotation_urls": {"south": f"{CDN}/o/s.png", "east": f"{CDN}/o/e.png", "north": None}},
                     "/tiles-pro/tp1": {"kind": "roads", "tile_rules": {"pieces": 18},
                                        "storage_urls": {"tiles": [f"{CDN}/t/road_0.png", f"{CDN}/t/road_1.png"]}}}
        if path in resources:
            return ok(resources[path])
        if path.startswith("/pro-flash/cost?"):              # PixelLab's free price check, as seen live 2026-11-13
            q = dict(p.split("=", 1) for p in path.split("?", 1)[1].split("&"))
            rot = 1 if q.get("operation") in ("character", "object") and q.get("n_directions", "8") == "8" else 0
            return ok({"image": 5, "rotations": rot, "total": 5 + rot, "provisional": True})
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
                "job-pf": {"images": [b64img(self.image_bytes)], "image_id": "img1", "source_image_id": "src1"},
                "job-pf-url": {"image_url": f"{CDN}/pf/edited.png", "source_image_id": "src2"},
                "job-opf": {"object_id": "o8"},
            }
            last = job_last.get(path.rsplit("/", 1)[-1], {"detail": "boom"}) if self.job_status == "completed" else {"detail": "boom"}
            return ok({"id": "job", "status": self.job_status, "created_at": "x", "last_response": last,
                       "usage": self.job_usage})
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

    def test_a_bare_signature_or_cut_png_is_refused(self):
        # #31: a file that was only the 8-byte PNG signature was saved as an image
        for data in (PNG_SIG, PNG[:-12], PNG_SIG + PNG[33:]):
            rc, out = self.run_tool("image", "--text", "x", "--out", "sig.png", fake=Fake(image_bytes=data))
            self.assertEqual(rc, 1, out)
            self.assertIn("not a PNG", out)
            self.assertFalse((self.root / "sig.png").exists())
        with self.assertRaises(pl.ServiceError):          # a storage-link download
            pl.check_bytes(PNG_SIG, "tile.png")
        with self.assertRaises(pl.ServiceError):          # a zip member
            pl.extract_zip(zip_bytes({"rotations/south.png": PNG_SIG}), self.root / "z")
        self.assertFalse((self.root / "z" / "rotations" / "south.png").exists())

    def test_not_a_png_is_a_service_failure(self):
        rc, out = self.run_tool("image", "--text", "x", "--out", "a.png", fake=Fake(image_bytes=b"<html>oops"))
        self.assertEqual(rc, 1)
        self.assertIn("not a PNG", out)

    def test_existing_output_needs_overwrite(self):
        (self.root / "a.png").write_bytes(PNG)
        rc, out = self.run_tool("image", "--text", "x", "--out", "a.png")
        self.assertEqual(rc, 2)
        self.assertIn("--overwrite", out)

    def test_existing_record_needs_overwrite(self):
        # #30: the .gen.json beside a new PNG was replaced silently
        (self.root / "c.gen.json").write_bytes(b"keep")
        fake = Fake()
        rc, out = self.run_tool("image", "--text", "x", "--out", "c.png", fake=fake)
        self.assertEqual(rc, 2, out)
        self.assertIn("c.gen.json already exists", out)
        self.assertEqual((self.root / "c.gen.json").read_bytes(), b"keep")
        self.assertEqual([c for c in fake.calls if c[0] == "POST"], [], "nothing spent")

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
        rc, out = self.run_tool("character", "--text", "old gravekeeper", "--size", "64", "--directions", "8",
                                "--out", "assets/keeper", "--log", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "assets/keeper/rotations/south.png").exists())
        polls = [c for c in fake.calls if "/background-jobs/" in c[1]]
        self.assertEqual(len(polls), 3, "two 'processing' answers, then 'completed'")
        sent = [c for c in fake.calls if c[1].endswith("/create-character-v3")][0][3]
        self.assertEqual(sent["n_directions"], 8)
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

    def test_v3_character_refuses_4_directions_and_shading_before_spending(self):
        # Live 2026-11-04: PixelLab answers 422 to both (n_directions 4 needs a reference image; v3 has no shading)
        for extra, why in ((["--directions", "4"], "--legacy"), (["--shading", "basic shading"], "--shading")):
            fake = Fake()
            rc, out = self.run_tool("character", "--text", "wizard", "--size", "32", *extra, "--out", "c", fake=fake)
            self.assertEqual(rc, 2, out)
            self.assertIn(why, out)
            self.assertEqual([c for c in fake.calls if c[0] == "POST"], [], "nothing spent")
        fake = Fake()
        rc, out = self.run_tool("character", "--text", "wizard", "--size", "16", "--legacy", "--directions", "4",
                                "--shading", "basic shading", "--out", "leg", fake=fake)
        self.assertEqual(rc, 0, out)
        sent = [c for c in fake.calls if c[1].endswith("/create-character-with-4-directions")][0][3]
        self.assertEqual(sent["shading"], "basic shading", "the legacy endpoint takes shading")

    def test_animate_keeps_a_transparent_frame_transparent(self):
        # Live 2026-11-04: without no_background PixelLab filled a transparent ghost's frames with flat grey
        fake = Fake(images=1)
        rc, out = self.run_tool("animate", "--frame", "south.png", "--action", "float", "--out", "a", fake=fake)
        self.assertEqual(rc, 0, out)
        sent = [c for c in fake.calls if c[1].endswith("/animate-with-text-v3")][0][3]
        self.assertIs(sent.get("no_background"), True, "an RGBA frame asks for transparent frames")
        raw = b"\x00" + b"\x00\x00\x00"
        chunk = lambda tag, data: (struct.pack(">I", len(data)) + tag + data  # noqa: E731
                                   + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
        rgb = (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        (self.root / "scene.png").write_bytes(rgb)
        (self.root / "keyed.png").write_bytes(rgb[:33] + chunk(b"tRNS", b"\x00\x00\x00\x00\x00\x00") + rgb[33:])
        for frame, want in (("scene.png", None), ("keyed.png", True)):
            fake = Fake(images=1)
            rc, out = self.run_tool("animate", "--frame", frame, "--action", "x", "--out", "o_" + frame, fake=fake)
            self.assertEqual(rc, 0, out)
            sent = [c for c in fake.calls if c[1].endswith("/animate-with-text-v3")][0][3]
            self.assertIs(sent.get("no_background"), want, frame)

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

    def test_files_with_one_base_name_in_a_job_all_survive(self):
        # #32: two result links with the same base name (and the job's own image) overwrote each other
        links = {f"{CDN}/x/boom.png": real_png(2, 1), f"{CDN}/y/BOOM.png": real_png(3, 1), f"{CDN}/z/boom.png": real_png(4, 1)}
        pl.http = lambda m, u, k, b=None: (200, {}, links[u])               # each link sends a different PNG
        out = self.root / "same"
        files = pl.save_last({"image": b64img(), "files": dict(zip("abc", links))}, out, KEY, stem="boom")
        self.assertEqual(len({f.name.lower() for f in files}), 4, [f.name for f in files])
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(f.name for f in files))
        self.assertEqual((out / "boom.png").read_bytes(), PNG, "the job's image is kept")
        self.assertEqual(sorted(f.read_bytes() for f in files[1:]), sorted(links.values()), "every link has its own file")

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
        rc, out = self.run_tool("font", "--text", "wooden sign", "--name", "sign", "--out", "fonts/sign", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "fonts/sign/sign.ttf").read_bytes(), TTF)
        self.assertTrue((self.root / "fonts/sign/sign.png").exists())

    def test_objects_one_and_eight_directions_and_review(self):
        rc, out = self.run_tool("object", "--text", "iron cannon", "--out", "obj/cannon", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "obj/cannon").glob("*.png")), ["frame_00.png", "frame_01.png"])
        rc, out = self.run_tool("object", "--text", "barrel", "--directions", "8", "--size", "48", "--out", "obj/barrel", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "obj/barrel").glob("*.png")), ["east.png", "south.png"])
        # Live 2026-11-04: a 64 px crate came back as 16 paid candidates in "review"; the tool exited 2 and saved none
        rc, out = self.run_tool("object", "--text", "x", "--out", "obj/rev", fake=Fake(object_id="o-review"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(p.name for p in (self.root / "obj/rev").glob("*.png")),
                         ["candidate_00.png", "candidate_01.png", "candidate_02.png"])
        side = json.loads((self.root / "obj/rev/pixellab.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(side["review"], 3)
        self.assertIn("3 candidates", out)
        rc, out = self.run_tool("object", "--text", "x", "--out", "obj/rev0", fake=Fake(object_id="o-review-empty"))
        self.assertEqual(rc, 1, out)
        self.assertIn("no candidate links", out)
        rc, out = self.run_tool("object", "--text", "x", "--directions", "8", "--size", "200", "--out", "obj/big", fake=Fake())
        self.assertEqual(rc, 2, "8-direction objects stop at 168")

    def test_prop_downloads_the_map_object(self):
        fake = Fake()
        rc, out = self.run_tool("prop", "--text", "apple pie", "--out", "props/pie.png", fake=fake)
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

    def test_unzoom_puts_the_source_transparency_back(self):
        # Live 2026-11-04: a 32 px crate with clear corners, at 8x, came back from /unzoom opaque (near-white) (#184)
        crate = lambda x, y: (150, 100, 55, 255) if 4 <= x < 28 and 6 <= y < 30 else (0, 0, 0, 0)  # noqa: E731
        (self.root / "big.png").write_bytes(real_png(256, 256, lambda x, y: crate(x // 8, y // 8)))
        opaque = real_png(32, 32, lambda x, y: crate(x, y) if crate(x, y)[3] else (254, 254, 255, 255))
        rc, out = self.run_tool("fix", "--op", "unzoom", "--image", "big.png", "--out", "u.png", fake=Fake(fix_bytes=opaque))
        self.assertEqual(rc, 0, out)
        w, h, rows = image_diff.read_png(self.root / "u.png")
        self.assertEqual((w, h), (32, 32))
        got = lambda x, y: tuple(rows[y][x * 4:x * 4 + 4])  # noqa: E731
        self.assertEqual(got(0, 0), (0, 0, 0, 0), "a clear source corner is clear in the result")
        self.assertEqual(got(16, 16), (150, 100, 55, 255), "the crate keeps its colour")
        self.assertEqual(sum(got(x, y)[3] == 0 for x in range(32) for y in range(32)), 32 * 32 - 24 * 24)
        self.assertIn("transparency", out)
        side = json.loads((self.root / "u.gen.json").read_text(encoding="utf-8"))
        self.assertEqual(side["sha256"], [pl.sha256(self.root / "u.png")], "the record hashes the file as saved")
        # an opaque source: PixelLab's answer is saved as it came
        (self.root / "flat.png").write_bytes(real_png(256, 256, lambda x, y: (9, 9, 9, 255)))
        rc, out = self.run_tool("fix", "--op", "unzoom", "--image", "flat.png", "--out", "u2.png", fake=Fake(fix_bytes=opaque))
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.root / "u2.png").read_bytes(), opaque)

    def test_correct_prints_the_colour_count_and_a_way_back(self):
        # Live 2026-11-04: 11 colours in, 302 out, nothing said (#184). Clear pixels with stray RGB are not colours.
        rgb = ((10, 20, 30, 255), (40, 50, 60, 255), (70, 80, 90, 255))
        three = lambda x, y: (0, 0, 0, 0) if x < 4 else rgb[y % 3]  # noqa: E731
        (self.root / "src.png").write_bytes(real_png(32, 32, three))
        many = real_png(32, 32, lambda x, y: (x, y, 7, 0) if x < 4 else (x * 8, 1, 5, 255))
        rc, out = self.run_tool("fix", "--op", "correct", "--image", "src.png", "--out", "c.png", fake=Fake(fix_bytes=many))
        self.assertEqual(rc, 0, out)
        self.assertIn("colours: 3 before, 28 after", out)
        self.assertIn("--op reduce-colors --colors 3", out)
        rc, out = self.run_tool("fix", "--op", "correct", "--image", "src.png", "--out", "c2.png",
                                fake=Fake(fix_bytes=real_png(32, 32, three)))
        self.assertEqual(rc, 0, out)
        self.assertIn("colours: 3 before, 3 after", out)
        self.assertNotIn("reduce-colors", out)

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
        rc, out = self.run_tool("character", "--text", "knight", "--out", "knight", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads((self.root / "knight/pixellab.gen.json").read_text(encoding="utf-8"))["character_id"], "char-1")
        rc, out = self.run_tool("animate-character", "--from", "knight", "--mode", "skeleton-v3", "--out", "x", fake=Fake())
        self.assertEqual(rc, 2)
        self.assertIn("--template", out)
        fake = Fake()
        rc, out = self.run_tool("animate-character", "--from", "knight", "--mode", "skeleton-v3", "--template", "cross-punch",
                                "--directions", "south,east", "--out", "knight_punch", fake=fake)
        self.assertEqual(rc, 0, out)
        sent = [c for c in fake.calls if c[1].endswith("/characters/animations")][0][3]
        self.assertEqual((sent["character_id"], sent["template_animation_id"], sent["directions"]),
                         ("char-1", "cross-punch", ["south", "east"]))
        polled = {c[1].rsplit("/", 1)[-1] for c in fake.calls if "/background-jobs/" in c[1]}
        self.assertEqual(polled, {"job-a1", "job-a2"})
        self.assertTrue((self.root / "knight_punch/rotations/south.png").exists())
        rc, out = self.run_tool("animate-character", "--from", "nowhere", "--template", "walk", "--out", "y", fake=Fake())
        self.assertEqual(rc, 2)
        self.assertIn("--character-id", out)

    # ---- Pro Flash, style images and pinned last frames (#16; PixelLab's API spec read 2026-11-13) ---------------
    def sent(self, fake, endpoint):
        posts = [c for c in fake.calls if c[0] == "POST" and c[1] == pl.API + endpoint]
        self.assertEqual(len(posts), 1, f"one POST to {endpoint}: {[c[1] for c in fake.calls]}")
        return posts[0][3]

    def no_post(self, fake):
        self.assertEqual([c[1] for c in fake.calls if c[0] == "POST"], [], "nothing may be spent")

    def test_pro_flash_image_waits_for_its_job_and_keeps_the_source_image_id(self):
        fake = Fake()
        rc, out = self.run_tool("image", "--pro-flash", "--text", "green slime", "--size", "32", "--no-background",
                                "--seed", "7", "--out", "art/slime.png", "--log", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sent(fake, "/create-image-pro-flash"),
                         {"description": "green slime", "image_size": {"width": 32, "height": 32},
                          "no_background": True, "seed": 7})
        self.assertEqual((self.root / "art/slime.png").read_bytes(), PNG)
        side = json.loads((self.root / "art/slime.gen.json").read_text(encoding="utf-8"))
        self.assertEqual((side["endpoint"], side["source_image_id"]), ("/create-image-pro-flash", "src1"))
        self.assertEqual(side["cost"], "2 generations", "the job's real charge beats the POST's estimate")
        self.assertIn("/create-image-pro-flash", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))
        # no charge in the job: the estimate is shown, marked as such
        rc, out = self.run_tool("image", "--pro-flash", "--text", "x", "--size", "32", "--out", "q.png",
                                fake=Fake(job_usage=None))
        self.assertEqual(rc, 0, out)
        self.assertIn("5 generations (quoted)", out)
        # sizes and options PixelLab's Pro Flash refuses (422 after sending) stop here, before anything is spent
        for extra, words in ((["--size", "30"], "multiple of 4"), (["--size", "300"], "outside 16 to 256"),
                             (["--size", "32", "--outline", "lineless"], "--outline"),
                             (["--size", "32", "--negative", "blur"], "--negative"),
                             (["--size", "32", "--style-traits", "outline"], "needs --style-image")):
            fake = Fake()
            rc, out = self.run_tool("image", "--pro-flash", "--text", "x", *extra, "--out", "n.png", fake=fake)
            self.assertEqual(rc, 2, f"{extra}: {out}")
            self.assertIn(words, out)
            self.no_post(fake)

    def test_style_image_goes_with_its_size_and_the_traits_to_copy(self):
        (self.root / "anchor.png").write_bytes(real_png(16, 24))
        fake = Fake()
        rc, out = self.run_tool("image", "--pro-flash", "--text", "blue slime", "--size", "32",
                                "--style-image", "anchor.png", "--style-traits", "outline,shading", "--out", "s.png",
                                fake=fake)
        self.assertEqual(rc, 0, out)
        body = self.sent(fake, "/create-image-pro-flash")
        self.assertEqual(base64.b64decode(body["style_image"]["image"]["base64"]), real_png(16, 24))
        self.assertEqual(body["style_image"]["size"], {"width": 16, "height": 24})
        self.assertEqual(body["style_options"], {"color_palette": False, "outline": True, "detail": False,
                                                 "shading": True})
        side = (self.root / "s.gen.json").read_text(encoding="utf-8")
        self.assertNotIn(body["style_image"]["image"]["base64"], side, "the record holds no image bytes")
        # without --style-traits every trait is copied (PixelLab's default): no style_options sent
        fake = Fake()
        rc, out = self.run_tool("image", "--pro-flash", "--text", "x", "--size", "32", "--style-image", "anchor.png",
                                "--out", "s2.png", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("style_options", self.sent(fake, "/create-image-pro-flash"))
        # refused before spending: bigger than the canvas, an unknown trait, no --pro-flash
        (self.root / "big.png").write_bytes(real_png(48, 48))
        for argv, words in ((["--pro-flash", "--size", "32", "--style-image", "big.png"], "bigger than the 32x32"),
                            (["--pro-flash", "--size", "32", "--style-image", "anchor.png", "--style-traits", "glow"],
                             "--style-traits takes"),
                            (["--size", "32", "--style-image", "anchor.png"], "needs --pro-flash")):
            fake = Fake()
            rc, out = self.run_tool("image", "--text", "x", *argv, "--out", "r.png", fake=fake)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(words, out)
            self.no_post(fake)
        # ui takes a plain style image of its own (no --pro-flash there)
        fake = Fake()
        rc, out = self.run_tool("ui", "--text", "wooden panel", "--style-image", "anchor.png", "--out", "ui.png",
                                fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(base64.b64decode(self.sent(fake, "/create-ui-asset")["style_image"]["base64"]),
                         real_png(16, 24))

    def test_pro_flash_character_and_object(self):
        (self.root / "anchor.png").write_bytes(real_png(32, 32))
        fake = Fake()
        rc, out = self.run_tool("character", "--pro-flash", "--text", "knight", "--size", "48", "--view", "side",
                                "--name", "Sir", "--style-image", "anchor.png", "--out", "pfk", fake=fake)
        self.assertEqual(rc, 0, out)
        body = self.sent(fake, "/create-character-pro-flash")
        self.assertEqual({k: v for k, v in body.items() if k != "style_image"},
                         {"description": "knight", "image_size": {"width": 48, "height": 48}, "view": "side",
                          "n_directions": 8, "name": "Sir"})
        self.assertTrue((self.root / "pfk/rotations/south.png").exists())
        self.assertEqual(json.loads((self.root / "pfk/pixellab.gen.json").read_text(encoding="utf-8"))["character_id"],
                         "char-1")
        fake = Fake()
        rc, out = self.run_tool("object", "--pro-flash", "--text", "barrel", "--directions", "8", "--size", "32",
                                "--source-image-id", "src1", "--out", "pfo", fake=fake)
        self.assertEqual(rc, 0, out)
        # live 2026-11-13: image_size next to source_image_id is a 422 ("only for text creation"), so none is sent
        self.assertEqual(self.sent(fake, "/create-object-pro-flash"),
                         {"description": "barrel", "view": "low top-down", "n_directions": 8, "source_image_id": "src1"})
        self.assertEqual(sorted(p.name for p in (self.root / "pfo").glob("*.png")), ["east.png", "south.png"])
        # one direction: its single storage link is the south view; its source_image_id is kept for 8 directions later
        fake = Fake(pf_object="o-pf1")
        rc, out = self.run_tool("object", "--pro-flash", "--text", "chest", "--size", "32", "--style-image",
                                "anchor.png", "--out", "pf1", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sent(fake, "/create-object-pro-flash")["n_directions"], 1)
        self.assertEqual(sorted(p.name for p in (self.root / "pf1").glob("*.png")), ["south.png"])
        self.assertEqual(json.loads((self.root / "pf1/pixellab.gen.json").read_text(encoding="utf-8"))["source_image_id"],
                         "src-o")
        for kind, argv, words in (("character", ["--legacy"], "8 directions only"),
                                  ("character", ["--size", "64", "--shading", "flat"], "--shading"),
                                  ("object", ["--size", "64", "--view", "top-down"], "--view is"),
                                  ("object", ["--size", "64", "--source-image-id", "src1", "--style-image",
                                              "anchor.png"], "drop --style-image"),
                                  ("object", ["--size", "66"], "multiple of 4")):
            fake = Fake()
            rc, out = self.run_tool(kind, "--pro-flash", "--text", "x", *argv, "--out", f"bad_{kind}", fake=fake)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(words, out)
            self.no_post(fake)
        for kind, argv in (("character", ["--source-image-id", "src1"]), ("object", ["--name", "Barrel"])):
            fake = Fake()
            rc, out = self.run_tool(kind, "--text", "x", *argv, "--out", f"plain_{kind}", fake=fake)
            self.assertEqual(rc, 2, f"{argv} without --pro-flash: {out}")
            self.no_post(fake)

    def test_pro_flash_edit_and_pixelate(self):
        (self.root / "hero.png").write_bytes(real_png(32, 32))
        (self.root / "hat.png").write_bytes(real_png(16, 8))
        fake = Fake()
        rc, out = self.run_tool("edit", "--pro-flash", "--image", "hero.png", "--reference", "hat.png",
                                "--text", "put this hat on him", "--out", "e.png", fake=fake)
        self.assertEqual(rc, 0, out)
        body = self.sent(fake, "/edit-image-pro-flash")
        self.assertEqual((body["method"], body["description"], body["no_background"]),
                         ("reference", "put this hat on him", True))
        self.assertEqual(base64.b64decode(body["reference_image"]["base64"]), real_png(16, 8))
        self.assertEqual((self.root / "e.png").read_bytes(), PNG, "the result behind image_url is downloaded")
        self.assertTrue(self.cdn_calls(fake) and all(c[2] is None for c in self.cdn_calls(fake)),
                        "no token to the storage link")
        self.assertEqual(json.loads((self.root / "e.gen.json").read_text(encoding="utf-8"))["source_image_id"], "src2")
        fake = Fake()
        rc, out = self.run_tool("edit", "--pro-flash", "--image", "hero.png", "--text", "red cape", "--out", "e2.png",
                                fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sent(fake, "/edit-image-pro-flash")["method"], "text")
        (self.root / "small.png").write_bytes(real_png(28, 28))
        for argv, words in ((["--pro-flash", "--image", "small.png"], "outside 32 to 256"),
                            (["--image", "hero.png", "--reference", "hat.png"], "needs --pro-flash"),
                            (["--pro-flash", "--image", "hat.png", "--reference", "hero.png"], "outside 32 to 256")):
            fake = Fake()
            rc, out = self.run_tool("edit", *argv, "--text", "x", "--out", "bad.png", fake=fake)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(words, out)
            self.no_post(fake)
        (self.root / "concept.png").write_bytes(real_png(300, 200))
        fake = Fake()
        rc, out = self.run_tool("pixelate", "--pro-flash", "--image", "concept.png", "--text", "light dithering",
                                "--out", "px.png", fake=fake)
        self.assertEqual(rc, 0, out)
        body = self.sent(fake, "/image-to-pixelart-pro-flash")
        self.assertEqual(sorted(body), ["description", "image"], "Pro Flash picks the size itself")
        self.assertTrue((self.root / "px.png").exists())
        for argv, words in ((["--pro-flash", "--size", "64"], "no --size"), (["--text", "dither"], "needs --pro-flash")):
            fake = Fake()
            rc, out = self.run_tool("pixelate", "--image", "concept.png", *argv, "--out", "bad.png", fake=fake)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(words, out)
            self.no_post(fake)
        fake = Fake()                                     # the plain endpoint still gets its default size
        rc, out = self.run_tool("pixelate", "--image", "concept.png", "--out", "plain.png", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sent(fake, "/image-to-pixelart")["output_size"], {"width": 64, "height": 64})

    def test_quote_asks_the_free_price_check_and_makes_nothing(self):
        for argv, query, words in (
                (["image", "--size", "64"], "operation=create&width=64&height=64", "quote: 5 generations (image 5, rotations 0)"),
                (["object", "--directions", "8", "--size", "32"], "operation=object&width=32&height=32&n_directions=8",
                 "quote: 6 generations (image 5, rotations 1)"),
                (["character", "--size", "64"], "operation=character&width=64&height=64&n_directions=8", "6 generations")):
            fake = Fake()
            dest = "qq.png" if argv[0] == "image" else "qq"
            rc, out = self.run_tool(*argv[:1], "--pro-flash", "--quote", "--text", "x", *argv[1:], "--out", dest,
                                    fake=fake)
            self.assertEqual(rc, 0, out)
            self.assertEqual([(c[0], c[1]) for c in fake.calls], [("GET", f"{pl.API}/pro-flash/cost?{query}")])
            self.assertEqual(fake.calls[0][2], KEY)
            self.assertIn(words, out)
            self.assertIn("provisional", out)
            self.assertFalse((self.root / dest).exists(), "a quote writes nothing")
        # reusing a paid image: the quote is the rotations alone (live 2026-11-13: 8 directions at 32 px charged 1)
        for directions, words in (("8", "quote: 1 generation (rotations only"), ("1", "quote: 0 generations (rotations only")):
            fake = Fake()
            rc, out = self.run_tool("object", "--pro-flash", "--quote", "--text", "x", "--directions", directions,
                                    "--size", "32", "--source-image-id", "src1", "--out", "qs", fake=fake)
            self.assertEqual(rc, 0, out)
            self.assertIn(words, out)
            self.assertIn(f"n_directions={directions}", fake.calls[0][1])
        (self.root / "concept.png").write_bytes(real_png(64, 64))
        fake = Fake()
        rc, out = self.run_tool("pixelate", "--pro-flash", "--quote", "--image", "concept.png", "--out", "p.png", fake=fake)
        self.assertEqual((rc, fake.calls), (0, []), out)
        self.assertIn("6 generations", out)
        fake = Fake()
        rc, out = self.run_tool("image", "--quote", "--text", "x", "--out", "i.png", fake=fake)
        self.assertEqual(rc, 2, out)
        self.assertIn("needs --pro-flash", out)
        self.assertEqual(fake.calls, [])
        fake = Fake()
        rc, out = self.run_tool("image", "--pro-flash", "--text", "x", "--size", "32", "--out", "d.png", "--dry-run",
                                fake=fake)
        self.assertEqual((rc, fake.calls), (0, []), out)
        self.assertIn("/create-image-pro-flash", out)
        self.assertIn("--quote", out)

    def test_animate_pins_a_last_frame_of_the_same_size(self):
        (self.root / "end.png").write_bytes(real_png(1, 1, lambda x, y: (9, 9, 9, 255)))
        fake = Fake(images=2)
        rc, out = self.run_tool("animate", "--frame", "south.png", "--last-frame", "end.png", "--action", "bob",
                                "--frames", "4", "--out", "loop", fake=fake)
        self.assertEqual(rc, 0, out)
        body = self.sent(fake, "/animate-with-text-v3")
        self.assertEqual(base64.b64decode(body["last_frame"]["base64"]), (self.root / "end.png").read_bytes())
        self.assertEqual(base64.b64decode(body["first_frame"]["base64"]), PNG)
        side = (self.root / "loop/pixellab.gen.json").read_text(encoding="utf-8")
        self.assertNotIn(body["last_frame"]["base64"], side, "the record holds the path, not the bytes")
        rc, out = self.run_tool("animate", "--frame", "south.png", "--last-frame", "end.png", "--action", "bob",
                                "--out", "dry", "--dry-run", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertIn('"last_frame": "<end.png,', out)
        (self.root / "wide.png").write_bytes(real_png(2, 1))
        fake = Fake()
        rc, out = self.run_tool("animate", "--frame", "south.png", "--last-frame", "wide.png", "--action", "bob",
                                "--out", "bad", fake=fake)
        self.assertEqual(rc, 2, out)
        self.assertIn("one size", out)
        self.no_post(fake)

    def test_animate_character_end_frame_is_one_direction_v3_or_pixminimax(self):
        rc, out = self.run_tool("character", "--text", "knight", "--out", "knight", fake=Fake())
        self.assertEqual(rc, 0, out)
        (self.root / "pose.png").write_bytes(PNG)                  # 1x1, the size of the zip's rotations/south.png
        fake = Fake()
        rc, out = self.run_tool("animate-character", "--from", "knight", "--mode", "pixminimax", "--action", "wave",
                                "--directions", "south", "--end-frame", "pose.png", "--out", "kw", fake=fake)
        self.assertEqual(rc, 0, out)
        body = self.sent(fake, "/characters/animations")
        self.assertEqual((body["mode"], body["directions"]), ("pixminimax", ["south"]))
        self.assertEqual(base64.b64decode(body["end_frame"]["base64"]), PNG)
        (self.root / "big.png").write_bytes(real_png(4, 4))
        for argv, words in ((["--mode", "template", "--template", "walk", "--directions", "south"], "--mode v3 or"),
                            (["--mode", "v3", "--action", "wave", "--directions", "south,east"], "exactly one"),
                            (["--mode", "v3", "--action", "wave"], "exactly one"),
                            (["--mode", "v3", "--action", "wave", "--directions", "south", "--end-frame", "big.png"],
                             "one size")):
            if "--end-frame" not in argv:
                argv = argv + ["--end-frame", "pose.png"]
            fake = Fake()
            rc, out = self.run_tool("animate-character", "--from", "knight", *argv, "--out", "kb", fake=fake)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(words, out)
            self.no_post(fake)


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

        rc, out = self.run_tool("character", "--text", "knight", "--out", "c1", fake=Busy(2))
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "c1/rotations/south.png").exists())
        rc, out = self.run_tool("character", "--text", "knight", "--out", "c2", "--wait", "0", fake=Busy(99, polls=0))
        self.assertEqual(rc, 1)
        self.assertIn("fetch --character-id char-1", out)
        rc, out = self.run_tool("fetch", "--character-id", "char-1", "--out", "c2", fake=Fake())
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "c2/rotations/south.png").exists())

    def test_ui_object_and_prop_report_the_cost_their_job_holds(self):
        # Live 2026-11-04: a 192 px UI panel cost 10 generations but printed none and saved "cost": "" (the POST
        # says usage null, the finished /ui-assets resource has no usage; GET /background-jobs/{id} has it)
        for argv, side in ((("ui", "--text", "health bar", "--out", "ui/bar.png"), "ui/bar.gen.json"),
                           (("object", "--text", "crate", "--out", "obj/crate"), "obj/crate/pixellab.gen.json"),
                           (("prop", "--text", "crate", "--out", "props/crate.png"), "props/crate.gen.json")):
            rc, out = self.run_tool(*argv, fake=Fake())
            self.assertEqual(rc, 0, out)
            self.assertIn("cost 2 generations", out, argv[0])
            self.assertEqual(json.loads((self.root / side).read_text(encoding="utf-8"))["cost"], "2 generations", argv[0])
        fake = Fake(polls=10**6)                     # a job that never says done: the saved files still count
        rc, out = self.run_tool("ui", "--text", "x", "--out", "ui/slow.png", "--wait", "0", fake=fake)
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads((self.root / "ui/slow.gen.json").read_text(encoding="utf-8"))["cost"], "")

    def test_several_direction_jobs_add_up_their_cost(self):
        self.run_tool("character", "--text", "knight", "--out", "knight", fake=Fake())
        rc, out = self.run_tool("animate-character", "--from", "knight", "--template", "walk", "--out", "walk", fake=Fake())
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


# ---- review fixes (#234, #237) --------------------------------------------------------------------------------
class ReviewFixesExam(unittest.TestCase):
    setUp, tearDown, run_tool = PixelLabExam.setUp, PixelLabExam.tearDown, PixelLabExam.run_tool

    @staticmethod
    def posts(fake):
        return [c for c in fake.calls if c[0] == "POST"]

    def test_a_timed_out_job_is_picked_up_not_paid_again(self):
        """#234: a slow job said "Rerun with a longer --wait", and the rerun paid for a second generation."""
        rc, out = self.run_tool("character", "--text", "x", "--out", "c", "--wait", "0", fake=Fake(polls=99))
        self.assertEqual(rc, 1, out)
        self.assertNotIn("Rerun with a longer", out)
        self.assertIn("instead of paying again", out)
        again = Fake(polls=0)
        rc, out = self.run_tool("character", "--text", "x", "--out", "c", fake=again)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.posts(again), [], "the rerun paid again")
        self.assertIn("not paid again", out)
        self.assertFalse(pl.job_journal(Path("c")).exists(), "the kept job outlived its saved files")
        third = Fake(polls=0)                         # done: the same request now is a new generation
        rc, out = self.run_tool("character", "--text", "x", "--out", "c", "--overwrite", fake=third)
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.posts(third)), 1)

    def test_a_dropped_paid_request_says_it_may_be_charged(self):
        """#234: a timeout after the POST read "could not reach ...", as if nothing had happened."""
        import socket
        real_opener = pl.OPENER

        class Opener:
            def open(self, req, timeout=None):
                if req.get_method() == "POST":
                    raise socket.timeout("timed out")
                balance = json.dumps({"subscription": {"plan": "Apprentice", "status": "active"}}).encode()

                class Resp:                           # GET /balance answers, so the run reaches the paid POST
                    status, headers = 200, {}

                    def read(self, n=-1):
                        return balance

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                return Resp()
        rc, out = self._run_real("image", "--text", "x", "--out", "d.png", opener=Opener())
        self.assertIs(pl.OPENER, real_opener)
        self.assertEqual(rc, 1, out)
        self.assertIn("may have started it and charged it", out)

    def _run_real(self, *argv, opener):
        real_http, real_opener = pl.http, pl.OPENER
        pl.http, pl.OPENER = self.real[0], opener
        try:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = pl.main(list(argv))
            return rc, out.getvalue() + err.getvalue()
        finally:
            pl.http, pl.OPENER = real_http, real_opener

    def test_summed_cost_never_hides_a_known_charge(self):
        """#237: one job without a cost made the known 3 generations disappear; mixed units showed the last only."""
        g = lambda n: {"type": "generations", "generations": n}  # noqa: E731
        self.assertEqual(pl.summed_cost([g(3), g(2)]), "5 generations (2 jobs)")
        self.assertIn("3 generations", pl.summed_cost([g(3), None]))
        self.assertIn("1 of 2 jobs reported no cost", pl.summed_cost([g(3), None]))
        self.assertEqual(pl.summed_cost([g(3), {"type": "usd", "usd": 0.5}]), "3 generations + $0.50")
        self.assertEqual(pl.summed_cost([None, None]), "")

    def test_odd_success_json_does_not_lose_the_paid_image(self):
        """#237: "generations": "1" (text) crashed in the cost line before the image was saved; [] crashed too."""
        class TextCount(Fake):
            def __call__(self, method, url, key, body=None):
                if url.endswith("/create-image-pixflux"):
                    self.calls.append((method, url, key, body))
                    return 200, {}, json.dumps({"usage": {"type": "generations", "generations": "1"},
                                                "image": b64img()}).encode()
                return super().__call__(method, url, key, body)
        rc, out = self.run_tool("image", "--text", "x", "--out", "t.png", fake=TextCount())
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.root / "t.png").is_file())

        class ListAnswer(Fake):
            def __call__(self, method, url, key, body=None):
                if url.endswith("/create-image-pixflux"):
                    return 200, {}, b"[]"
                return super().__call__(method, url, key, body)
        rc, out = self.run_tool("image", "--text", "x", "--out", "l.png", fake=ListAnswer())
        self.assertEqual(rc, 1, out)
        self.assertIn("unexpected shape", out)

    def test_a_token_echoed_by_the_server_is_not_printed(self):
        """#237: the server's error text went into the message as it was (run_tool also checks the token)."""
        body = json.dumps({"detail": f"bad token {KEY}"}).encode()
        rc, out = self.run_tool("image", "--text", "x", "--out", "k.png", fake=Fake(status=422, body=body))
        self.assertEqual(rc, 2, out)
        self.assertIn("<key>", out)

    def test_windows_device_names_and_case_twins_are_refused(self):
        """#237: CON.png passed the name check; south.png and SOUTH.png overwrote each other on Windows."""
        for members in ({"rotations/CON.png": PNG}, {"rotations/south.png": PNG, "rotations/SOUTH.png": PNG},
                        {"aux/south.png": PNG}):
            rc, out = self.run_tool("character", "--text", "x", "--out", "w", "--overwrite",
                                    fake=Fake(polls=0, zip_members=members))
            self.assertEqual(rc, 1, (members, out))
            self.assertIn("refusing zip", out)
            pl.job_journal(Path("w")).unlink()        # each case is a fresh request

    def test_an_existing_evidence_file_is_never_overwritten(self):
        """#237: the evidence file was written over whatever had the same ID."""
        (self.root / "docs" / "licenses").mkdir()
        evidence = self.root / "docs" / "licenses" / "A-0001.txt"
        evidence.write_bytes(b"someone else's")
        before = (self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8")
        rc, out = self.run_tool("image", "--text", "x", "--out", "assets/e.png", "--log")
        self.assertEqual(rc, 2, out)
        self.assertEqual(evidence.read_bytes(), b"someone else's")
        self.assertEqual((self.root / "docs" / "ASSET_LOG.md").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main(verbosity=1)
