#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_tripo.py
# Purpose : The exam for `bozzetto.py make --with tripo` (tripo.py), offline: a stand-in Tripo v3 API on 127.0.0.1 (a
#           random port) answers /account/balance, /files (multipart), /generation/image-to-model,
#           /generation/multiview-to-model, /generation/text-to-model and /tasks/{id}, and serves the result file
#           from its own "CDN" path. It checks the key on every API call and records every request.
#           Part 1 (standard library, any Python 3.8+), the Blender steps replaced by test_bozzetto's stand-in:
#           - image, multiview and text routes end to end: what is uploaded (metadata removed), what each task gets,
#             no ComfyUI touched, the download without the key, raw.glb without extras, the same cleanup, budget
#             check, LODs, turntable, record (route, task ids, model, credits, terms) and asset log row as the local
#             route, and the key in no written file
#           - a quote over --max-credits or over the balance stops before any upload; a cost over the quote warns
#           - a failed task (Tripo's reason shown, nothing charged) and a new one on the re-run
#           - an expired download link, then a fresh link on the re-run with no new paid task
#           - reuse of a finished or a still-running task; --no-reuse and changed inputs pay again
#           - facing and scale: --turn -90 by default (Tripo faces +X), --turn and --height override, the class height
#           - usage: views without --with tripo, multiview without --front, --material vertex, --reference-only,
#             a .webp, no key
#           Part 2 (when Blender or the bpy module is found): the real cleanup.py turns a mesh that faces +X, as Tripo's
#           do, to face glTF's +Z with the route's default turn, and scales it to the class height.
# Usage   : python tools/bozzetto/test_tripo.py
#           BOZZETTO_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import http.server
import io
import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import tripo  # noqa: E402
from test_bozzetto import FakeBlender, LOG, PNG_SIG, canned_glb, chunk, part2_blender, png  # noqa: E402

cl = bz.cl
KEY = "tsk_exam_secret_7f3a"
GPS = b"GPSLatitude 51.4779 N"


# ---- stand-in Tripo --------------------------------------------------------------------------------------------
class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.balance, self.cost = 500.0, 110.0
        self.tasks = {}            # id -> {"path", "body", "polls"}
        self.uploads = []          # (filename, content type, bytes)
        self.requests = []         # (method, path, had the key)
        self.downloads = []        # (url path, Authorization header or None)
        self.status = {}           # task id -> status reported instead of success
        self.fail = None           # (code, message): every new task fails with it
        self.expire = False        # links handed out while set are dead from the start
        self.dead = set()
        self.urls = 0
        self.mesh = canned_glb(16, 4)

    def posts(self, kind=""):
        return [t for t in self.tasks.values() if t["path"].endswith(kind)]


STATE = State()


def multipart_file(body, ctype):
    """(filename, content type, data) of the "file" part of a multipart/form-data body."""
    boundary = ctype.split("boundary=", 1)[1].encode()
    for part in body.split(b"--" + boundary):
        head, _, data = part.partition(b"\r\n\r\n")
        if b'name="file"' in head:
            text = head.decode("utf-8", "replace")
            name = text.split('filename="', 1)[1].split('"', 1)[0]
            ptype = text.split("Content-Type:", 1)[1].strip().split("\r\n")[0].strip()
            return name, ptype, data[:-2] if data.endswith(b"\r\n") else data
    return None


class FakeTripo(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def ok(self, data):
        self.send(200, {"code": 0, "data": data})

    def keyed(self):
        good = self.headers.get("Authorization") == f"Bearer {KEY}"
        STATE.requests.append((self.command, self.path, good))
        if not good:
            self.send(401, {"code": 1002, "message": "invalid api key"})
        return good

    def do_GET(self):
        if self.path.startswith("/cdn/"):
            STATE.downloads.append((self.path, self.headers.get("Authorization")))
            if self.path in STATE.dead:
                return self.send(403, b"<Error>Request has expired</Error>", "application/xml")
            return self.send(200, STATE.mesh, "model/gltf-binary")
        if not self.keyed():
            return
        if self.path == "/v3/account/balance":
            return self.ok({"balance": STATE.balance, "frozen": 0.0})
        if self.path.startswith("/v3/tasks/"):
            tid = self.path.rsplit("/", 1)[1]
            task = STATE.tasks.get(tid)
            if task is None:
                return self.send(404, {"code": 2001, "message": "task not found"})
            task["polls"] += 1
            st = STATE.status.get(tid) or ("failed" if task.get("fail") else "success")
            data = {"task_id": tid, "type": task["path"].rsplit("/", 1)[1].replace("-", "_"), "status": st,
                    "progress": 100 if st == "success" else 40, "created_at": "2026-11-11T12:00:00Z"}
            if st == "success":
                STATE.urls += 1
                url = f"/cdn/{tid}/model_{STATE.urls}.glb"
                if STATE.expire:
                    STATE.dead.add(url)
                host = f"http://{self.headers.get('Host')}"
                data.update(output={"model_url": host + url, "rendered_image_url": host + "/cdn/preview.png"},
                            credits_consumed=STATE.cost, completed_at="2026-11-11T12:01:30Z")
            elif st == "failed" and task.get("fail"):
                data.update(error_code=task["fail"][0], error_message=task["fail"][1])
            return self.ok(data)
        self.send(404, {"code": 404, "message": "no such path in the exam"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not self.keyed():
            return
        if self.path == "/v3/files":
            got = multipart_file(body, self.headers.get("Content-Type", ""))
            if not got:
                return self.send(400, {"code": 1001, "message": "no file part"})
            STATE.uploads.append(got)
            return self.ok({"file_token": f"file_{len(STATE.uploads)}"})
        if self.path.startswith("/v3/generation/"):
            tid = f"task-{len(STATE.tasks) + 1}"
            STATE.tasks[tid] = {"path": self.path[3:], "body": json.loads(body), "polls": 0, "fail": STATE.fail}
            return self.ok({"task_id": tid})
        self.send(404, {"code": 404, "message": "no such path"})


# ---- helpers -----------------------------------------------------------------------------------------------------
def jpeg_with_gps():
    seg = lambda m, b: bytes((0xFF, m)) + len(b + b"..").to_bytes(2, "big") + b  # noqa: E731
    return (b"\xff\xd8" + seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
            + seg(0xE1, b"Exif\x00\x00MM\x00\x2a" + GPS) + seg(0xDB, bytes(65))
            + seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\xff\x00\x34\xff\xd9")


def png_with_gps(w=8, h=8, rgb=(150, 90, 40)):
    whole = png(w, h, rgb)
    return whole[:33] + chunk(b"eXIf", b"MM\x00\x2a" + GPS) + whole[33:]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeTripo)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        STATE.reset()
        self.tmp = tempfile.TemporaryDirectory(prefix="bz_tripo_exam_")
        self.root = Path(self.tmp.name).resolve()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        art = self.root / "art_src"
        art.mkdir()
        (art / "crate.png").write_bytes(png_with_gps(32, 32))
        (art / "front.png").write_bytes(png_with_gps(16, 16, (200, 40, 40)))
        (art / "back.jpg").write_bytes(jpeg_with_gps())
        (art / "left.png").write_bytes(png(16, 16, (40, 200, 40)))
        self.saved = (bz.SLEEP, bz.run_bpy, bz.find_blender, bz.blender_version, tripo.BASE, os.getcwd(),
                      dict(os.environ))
        bz.SLEEP = lambda s: None
        self.fake = FakeBlender()
        bz.run_bpy = self.fake
        bz.find_blender = lambda choice=None: ("blender", "fake-blender")
        bz.blender_version = lambda b: "Blender 9.9 (stand-in)"
        tripo.BASE = self.url + "/v3"
        os.environ[tripo.TRIPO_ENV] = KEY
        os.environ["COMFYUI_URL"] = "http://127.0.0.1:9"       # nothing there: the Tripo route must not need it
        os.chdir(self.root)

    def tearDown(self):
        bz.SLEEP, bz.run_bpy, bz.find_blender, bz.blender_version, tripo.BASE, cwd, env = self.saved
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(env)
        self.tmp.cleanup()

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bz.main(list(argv))
        return rc, out.getvalue() + err.getvalue()

    def make(self, *extra, name="prop_crate"):
        return self.run_tool("make", name, "--with", "tripo", *(extra or ("--image", "art_src/crate.png")))

    def src(self, name="prop_crate"):
        return self.root / "assets_src" / "bozzetto" / name

    def record(self, name="prop_crate"):
        return json.loads((self.src(name) / "bozzetto.json").read_text(encoding="utf-8"))

    def row(self, path):
        return [l for l in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
                if f"`{path}`" in l][0]

    def cleanup_argv(self):
        return [a for s, a in self.fake.calls if s == "cleanup.py"][-1]

    def nothing_secret_written(self):
        """No written file holds the key, the temp folder or the user's home."""
        needles = [KEY.encode(), str(self.root).encode(), self.root.as_posix().encode(),
                   str(Path.home()).encode(), Path.home().as_posix().encode()]
        for p in self.root.rglob("*"):
            if p.is_file() and p.parts[len(self.root.parts)] != "art_src":
                data = p.read_bytes()
                for n in needles:
                    self.assertNotIn(n, data, f"{p.relative_to(self.root)} holds {n[:20]!r}")


# ---- part 1 ------------------------------------------------------------------------------------------------------
class Routes(Base):
    def test_image_route_end_to_end(self):
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("Tripo quote: 110 credits", out)
        # one picture uploaded, without its metadata, as the kept reference
        self.assertEqual(len(STATE.uploads), 1)
        name, ctype, data = STATE.uploads[0]
        self.assertEqual((name, ctype), ("reference.png", "image/png"))
        self.assertTrue(data.startswith(PNG_SIG))
        self.assertNotIn(GPS, data, "the GPS position went to Tripo")
        self.assertEqual(data, (self.src() / "reference.png").read_bytes())
        # one task with the documented body
        (task,) = STATE.posts()
        self.assertEqual(task["path"], "/generation/image-to-model")
        self.assertEqual(task["body"]["input"], "file_1")
        self.assertEqual(task["body"]["model"], "P2-20260801")
        self.assertEqual(task["body"]["face_limit"], 2700, "prop: 90% of 3000")
        self.assertEqual((task["body"]["model_seed"], task["body"]["texture_seed"]), (7, 7))
        self.assertTrue(task["body"]["pbr"])
        self.assertTrue(all(good for _, _, good in STATE.requests), "an API call went without the key")
        self.assertEqual([a for _, a in STATE.downloads], [None], "the key went to the download host")
        raw = (self.src() / "raw.glb").read_bytes()
        self.assertNotIn(b"extras", raw)
        # the same downstream steps as the local route
        self.assertEqual([c[0] for c in self.fake.calls],
                         ["cleanup.py", "prep_export.py", "validate_asset.py", "turntable.py"])
        self.assertTrue((self.root / "assets/models/prop_crate.glb").is_file())
        rec = self.record()
        self.assertEqual(rec["route"], "tripo")
        self.assertEqual(rec["job"]["task_id"], "task-1")
        self.assertEqual(rec["job"]["tasks"], {"model": "task-1"})
        self.assertEqual(rec["job"]["model"], "P2-20260801")
        self.assertEqual(rec["credits"], 110)
        self.assertIn("5.2.2", rec["terms"])
        self.assertIn("Studio", rec["terms"])
        self.assertEqual(rec["reference"]["kind"], "image")
        row = self.row("assets/models/prop_crate.glb")
        for cell in ("Tripo3D API: P2-20260801 image-to-model", "paid service", "Tripo3D terms (paid output, 5.2.2)",
                     "110 Tripo credits", "task-1", "pre-generated"):
            self.assertIn(cell, row)
        self.assertNotIn("DINOv3", row)
        ev = (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8")
        self.assertIn("--with tripo", ev)
        self.assertIn("5.2.2", ev)
        self.assertFalse(list((self.root / "docs/licenses").glob("bozzetto-*")), "local model licences copied")
        journal = json.loads((self.src() / "tripo" / "tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(journal["tasks"]["model"], {"id": "task-1", "status": "success", "credits": 110.0})
        self.nothing_secret_written()

    def test_multiview_route(self):
        rc, out = self.make("--front", "art_src/front.png", "--back", "art_src/back.jpg", "--left",
                            "art_src/left.png", "--class", "npc", name="npc_guard")
        self.assertEqual(rc, 0, out)
        self.assertEqual([(n, t) for n, t, _ in STATE.uploads],
                         [("view_front.png", "image/png"), ("view_left.png", "image/png"),
                          ("view_back.jpg", "image/jpeg")])
        for _, _, data in STATE.uploads:
            self.assertNotIn(GPS, data)
        (task,) = STATE.posts()
        self.assertEqual(task["path"], "/generation/multiview-to-model")
        self.assertEqual(task["body"]["inputs"], [{"front": "file_1"}, {"left": "file_2"}, {"back": "file_3"}])
        self.assertNotIn("input", task["body"])
        self.assertEqual(task["body"]["face_limit"], 13500, "npc: 90% of 15,000")
        rec = self.record("npc_guard")
        self.assertEqual(sorted(rec["reference"]["views"]), ["back", "front", "left"])
        self.assertIn("views: front, left, back", self.row("assets/models/npc_guard.glb"))
        self.assertIn("multiview-to-model", self.row("assets/models/npc_guard.glb"))

    def test_text_route(self):
        rc, out = self.make("--prompt", "a friendly round robot", "--class", "npc", "--seed", "3", name="npc_robot")
        self.assertEqual(rc, 0, out)
        self.assertEqual(STATE.uploads, [], "text-to-model uploads nothing")
        (task,) = STATE.posts()
        self.assertEqual(task["path"], "/generation/text-to-model")
        self.assertTrue(task["body"]["prompt"].startswith("a friendly round robot, full body"))
        self.assertIn("A-pose", task["body"]["prompt"])
        self.assertEqual(task["body"]["image_seed"], 3)
        self.assertIn("prompt: a friendly round robot", self.row("assets/models/npc_robot.glb"))
        # a prop, or --raw-prompt, goes as written
        rc, out = self.make("--prompt", "a brass lantern", "--raw-prompt", name="prop_lamp")
        self.assertEqual(rc, 0, out)
        self.assertEqual(STATE.posts()[-1]["body"]["prompt"], "a brass lantern")

    def test_hero_faces_are_clamped_to_the_model_limit(self):
        rc, out = self.make("--image", "art_src/crate.png", "--class", "hero", "--no-preview", name="chr_hero")
        self.assertEqual(rc, 0, out)
        self.assertEqual(STATE.posts()[0]["body"]["face_limit"], 50000, "hero 54,000 is over P2's 50,000")
        self.assertEqual(self.cleanup_argv()[self.cleanup_argv().index("--max-tris") + 1], "54000",
                         "cleanup still decimates to the class target")


class Money(Base):
    def test_quote_over_the_cap_or_the_balance_stops_before_upload(self):
        rc, out = self.make("--image", "art_src/crate.png", "--max-credits", "100")
        self.assertEqual(rc, 2, out)
        self.assertIn("over --max-credits 100", out)
        self.assertEqual((STATE.uploads, STATE.posts()), ([], []))
        rc, out = self.make("--image", "art_src/crate.png", "--quality", "high", "--max-credits", "120")
        self.assertEqual(rc, 2, out)
        self.assertIn("over --max-credits 120", out, "detailed textures cost more than the base quote")
        STATE.balance = 50
        rc, out = self.make("--image", "art_src/crate.png")
        self.assertEqual(rc, 2, out)
        self.assertIn("under the next step", out)
        self.assertIn("Studio plan adds none", out)
        self.assertEqual((STATE.uploads, STATE.posts()), ([], []))
        self.assertFalse((self.root / "assets").exists())

    def test_a_charge_over_the_quote_warns(self):
        STATE.cost = 140
        rc, out = self.make("--image", "art_src/crate.png", "--max-credits", "200")
        self.assertEqual(rc, 0, out)
        self.assertIn("more than the quote", out)
        self.assertEqual(self.record()["credits"], 140)

    def test_no_key_stops_first(self):
        os.environ.pop(tripo.TRIPO_ENV)
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("TRIPO_API_KEY", out)
        self.assertEqual(STATE.requests, [])

    def test_a_client_id_in_place_of_the_key_stops_before_any_call(self):
        os.environ[tripo.TRIPO_ENV] = "tcli_exam_client_id"
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("client ID", out)
        self.assertIn("tsk_", out, "names the key the user needs")
        self.assertEqual(STATE.requests, [])

    def test_a_refused_key_shows_tripos_own_words(self):
        os.environ[tripo.TRIPO_ENV] = "tsk_wrong"
        rc, out = self.make()
        self.assertEqual(rc, 2, out)
        self.assertIn("Tripo refused the key", out)
        self.assertIn("invalid api key", out, "the stand-in's message reaches the user")
        self.assertNotIn("tsk_wrong", out, "the key is never printed")
        self.assertEqual(STATE.uploads, [])


class Recovery(Base):
    def test_a_failed_task_shows_why_and_the_rerun_makes_a_new_one(self):
        STATE.fail = (2010, "the image has no recognisable object")
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("failed", out)
        self.assertIn("no recognisable object", out)
        self.assertIn("costs no credits", out)
        self.assertFalse((self.root / "assets").exists())
        self.assertNotIn("| model |", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))
        STATE.fail = None
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertIn("ended failed; a new one will be made", out)
        self.assertEqual(len(STATE.posts()), 2)
        self.assertEqual(self.record()["job"]["task_id"], "task-2")

    def test_an_expired_link_is_fetched_fresh_on_the_rerun_without_paying(self):
        STATE.expire = True
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("links expire", out)
        self.assertIn("without paying", out)
        STATE.expire = False
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.posts()), 1, "the re-run paid for a second model")
        self.assertEqual(len(STATE.uploads), 1, "the re-run uploaded again")
        first, second = STATE.downloads[0][0], STATE.downloads[-1][0]
        self.assertNotEqual(first, second, "the re-run used the expired link")
        self.assertIn("reusing paid Tripo work", out)

    def test_reuse_no_reuse_and_changed_inputs(self):
        self.assertEqual(self.make("--image", "art_src/crate.png", "--seed", "5")[0], 0)
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "5", "--overwrite", "--turn", "180")
        self.assertEqual(rc, 0, out)
        self.assertIn("Tripo quote: 0 credits", out)
        self.assertEqual(len(STATE.posts()), 1, "a re-run with the same inputs paid again")
        self.assertEqual(self.cleanup_argv()[self.cleanup_argv().index("--turn") + 1], "180.0")
        log = (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("`assets/models/prop_crate.glb`"), 1, "a re-run updates its row")
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "6", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.posts()), 2, "another seed is another model")
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "6", "--overwrite", "--no-reuse")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.posts()), 3, "--no-reuse pays for a new one")
        (self.root / "art_src" / "crate.png").write_bytes(png(32, 32, (10, 10, 200)))
        rc, out = self.make("--image", "art_src/crate.png", "--seed", "6", "--overwrite")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.posts()), 4, "a changed picture is another model")

    def test_a_task_left_running_is_adopted_or_stops_the_run(self):
        bz.SLEEP = lambda s: time.sleep(0.05)       # --wait 1 is real time: poll gently
        STATE.status["task-1"] = "running"
        rc, out = self.make("--image", "art_src/crate.png", "--wait", "1")
        self.assertEqual(rc, 1, out)
        self.assertIn("did not finish", out)
        rc, out = self.make("--image", "art_src/crate.png", "--wait", "1")
        self.assertEqual(rc, 2, out)
        self.assertIn("still running", out)
        self.assertEqual(len(STATE.posts()), 1, "a second task was paid for while the first ran")
        del STATE.status["task-1"]
        rc, out = self.make()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.posts()), 1)
        self.assertEqual(self.record()["job"]["task_id"], "task-1")

    def test_a_budget_failure_ships_nothing_but_keeps_the_paid_task(self):
        self.fake.validate_rc = 1
        rc, out = self.make()
        self.assertEqual(rc, 1, out)
        self.assertIn("fails the prop budget", out)
        self.assertFalse((self.root / "assets/models/prop_crate.glb").exists())
        self.fake.validate_rc = 0
        rc, out = self.make("--image", "art_src/crate.png", "--height", "0.6")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(STATE.posts()), 1, "fixing the size must not pay for a new model")


class Placement(Base):
    def test_facing_and_scale(self):
        rc, out = self.make("--class", "npc", "--image", "art_src/crate.png", name="npc_crate")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertEqual(argv[argv.index("--turn") + 1], "-90.0", "Tripo faces +X: turned to glTF's +Z")
        self.assertEqual(argv[argv.index("--height") + 1], "1.8", "the class height, not Tripo's 1 m")
        self.assertEqual(self.record("npc_crate")["turn_deg"], -90.0)
        self.assertIn("turned -90", (self.root / "docs/licenses/A-0001.txt").read_text(encoding="utf-8"))
        rc, out = self.make("--image", "art_src/crate.png", "--turn", "0", "--height", "2.5", "--no-log", name="prop_b")
        self.assertEqual(rc, 0, out)
        argv = self.cleanup_argv()
        self.assertEqual((argv[argv.index("--turn") + 1], argv[argv.index("--height") + 1]), ("0.0", "2.5"))

    def test_the_local_route_keeps_its_own_facing(self):
        args = bz.build_parser().parse_args(["make", "prop_x", "--image", "art_src/crate.png"])
        self.assertEqual(bz.Plan(args).turn, 0.0)


class Usage(Base):
    def test_usage_errors_exit_2_before_any_call(self):
        (self.root / "art_src" / "pic.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
        cases = [(("--front", "art_src/front.png", "--back", "art_src/back.jpg", "--with", "local"),
                  "Tripo's multiview route (--with tripo)"),
                 (("--back", "art_src/back.jpg", "--left", "art_src/left.png"), "needs --front"),
                 (("--front", "art_src/front.png"), "at least two views"),
                 (("--image", "art_src/crate.png", "--front", "art_src/front.png", "--back", "art_src/back.jpg"),
                  "exactly one of"),
                 (("--image", "art_src/crate.png", "--material", "vertex"), "textured models only"),
                 (("--prompt", "a lamp", "--reference-only"), "local route's picture audition"),
                 (("--image", "art_src/pic.webp"), "PNG and JPEG"),
                 (("--image", "art_src/crate.png", "--max-credits", "0"), "--max-credits must be"),
                 (("--prompt", "x" * 1100), "longer than Tripo takes")]
        for argv, why in cases:
            rc, out = self.make(*argv)
            self.assertEqual(rc, 2, f"{argv}: {out}")
            self.assertIn(why, out, argv)
        self.assertEqual(STATE.requests, [], "a usage error reached Tripo")

    def test_check_names_the_route(self):
        rc, out = self.run_tool("check")
        self.assertIn("make --with tripo (paid): balance 500 credits", out)
        os.environ.pop(tripo.TRIPO_ENV)
        rc, out = self.run_tool("check")
        self.assertIn("TRIPO_API_KEY is not set", out)

    def test_help_lists_the_route(self):
        rc, out = self.run_tool("make", "-h")
        self.assertEqual(rc, 0)
        for opt in ("--with", "--front", "--back", "--max-credits", "--no-reuse", "--tripo-model"):
            self.assertIn(opt, out)


# ---- part 2: the real cleanup.py turns Tripo's +X front to glTF's +Z ------------------------------------------------
def boxes_glb(boxes):
    """Indexed boxes (glTF coordinates, Y up): [(min xyz, max xyz)], one primitive."""
    pos, idx = [], []
    for lo, hi in boxes:
        base = len(pos)
        pos += [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        for a, b, c, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            idx += [base + a, base + b, base + c, base + a, base + c, base + d]
    pbin = b"".join(struct.pack("<3f", *p) for p in pos)
    ibin = b"".join(struct.pack("<I", i) for i in idx)
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(pbin) + len(ibin)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pbin), "target": 34962},
                           {"buffer": 0, "byteOffset": len(pbin), "byteLength": len(ibin), "target": 34963}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": [min(p[i] for p in pos) for i in range(3)],
                          "max": [max(p[i] for p in pos) for i in range(3)]},
                         {"bufferView": 1, "componentType": 5125, "count": len(idx), "type": "SCALAR"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
           "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
    return cl.write_glb(doc, pbin + ibin)


def positions(path):
    doc, binary = cl.read_glb(Path(path).read_bytes())
    out = []
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            acc = doc["accessors"][prim["attributes"]["POSITION"]]
            view = doc["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = view.get("byteStride", 12)
            out += [struct.unpack_from("<3f", binary, start + i * stride) for i in range(acc["count"])]
    return out


BLENDER = part2_blender()


@unittest.skipIf(BLENDER is None, "no Blender or bpy module found (part 2 skipped)")
class RealFacing(unittest.TestCase):
    def test_default_turn_brings_plus_x_to_plus_z(self):
        with tempfile.TemporaryDirectory(prefix="bz_tripo_bpy_") as d:
            d = Path(d)
            # a body 1 m tall and a narrow "nose" sticking out along +X: a model facing +X, as Tripo's do
            (d / "raw.glb").write_bytes(boxes_glb([((-0.2, 0.0, -0.2), (0.2, 1.0, 0.2)),
                                                   ((0.2, 0.45, -0.05), (0.5, 0.55, 0.05))]))
            rc, out = bz.run_bpy(BLENDER, HERE / "cleanup.py",
                                 [d / "raw.glb", "--out", d / "clean.glb", "--turn", tripo.FACING_TURN, "--height",
                                  "1.8", "--min-part", "0"], "cleanup")
            self.assertEqual(rc, 0, out)
            pts = positions(d / "clean.glb")
            ys = [p[1] for p in pts]
            self.assertAlmostEqual(max(ys) - min(ys), 1.8, places=3)

            def width_at(axis, pick):
                edge = pick(p[axis] for p in pts)
                at = [p for p in pts if abs(p[axis] - edge) < 1e-4]
                other = 0 if axis == 2 else 2
                return max(p[other] for p in at) - min(p[other] for p in at)
            # the narrow nose is now the extreme along +Z (glTF's front); the broad body is at -Z
            self.assertLess(width_at(2, max), 0.3)
            self.assertGreater(width_at(2, min), 0.6)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(f"[info] part 2 Blender: {BLENDER[0] + ' ' + Path(BLENDER[1]).name if BLENDER else 'none (skipped)'}")
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
