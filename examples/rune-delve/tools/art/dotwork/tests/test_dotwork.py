#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_dotwork.py
# Purpose : offline exam for Dotwork: a stand-in ComfyUI on 127.0.0.1 (random port) answers the endpoints Dotwork uses
#           (/system_stats, /object_info, /upload/image, /prompt, /history, /view, /free), so no GPU, models, ComfyUI
#           or Godot are needed. Covers settings layering, spec parsing and exit codes, the manifest, naming, PNG
#           metadata stripping on download, the numpy connected components, blob atlas layout and seam exactness,
#           the .tres / .tscn writers (and --engine none), mapbuild's text-to-cells, glyph parsing and font build,
#           connector masks, and SpriteKiln workflow loading.
# Usage   : python tools/art/dotwork/tests/test_dotwork.py
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import http.server
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import zlib
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fcore  # noqa: E402

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png_with_text(w=4, h=4):
    raw = b"".join(b"\x00" + b"\x10\x20\x30\xff" * w for _ in range(h))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"tEXt", b"prompt\x00" + json.dumps({"path": "C:/Users/you/secret.safetensors"}).encode())
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class State:
    uploads, prompts = [], []


class FakeComfy(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        if path.path == "/system_stats":
            return self._send(200, {"system": {"comfyui_version": "0.0-test", "python_version": "3.12"},
                                    "devices": [{"name": "Fake GPU", "vram_free": 8 << 30, "vram_total": 16 << 30}]})
        if path.path == "/object_info":
            return self._send(200, {"UNETLoader": {"input": {"required": {"unet_name": [["flux-2-klein-4b.safetensors"]]}}}})
        if path.path.startswith("/history/"):
            pid = path.path.rsplit("/", 1)[-1]
            prefix = next(n["inputs"]["filename_prefix"] for n in State.prompts[int(pid)].values()
                          if n["class_type"] == "SaveImage")
            sub, _, stem = prefix.rpartition("/")
            return self._send(200, {pid: {"status": {"completed": True, "status_str": "success"},
                                          "outputs": {"9": {"images": [{"filename": f"{stem}_00001_.png",
                                                                        "subfolder": sub, "type": "output"}]}}}})
        if path.path == "/view":
            return self._send(200, png_with_text(), "image/png")
        return self._send(404, {"error": "no route"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        if self.path == "/upload/image":
            name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            State.uploads.append(name)
            return self._send(200, {"name": name, "subfolder": "", "type": "input"})
        if self.path == "/prompt":
            State.prompts.append(json.loads(body)["prompt"])
            return self._send(200, {"prompt_id": str(len(State.prompts) - 1)})
        if self.path == "/free":
            return self._send(200, {})
        return self._send(404, {})


def make_project(tmp, extra_conf=None):
    os.makedirs(os.path.join(tmp, "art_src", "dotwork"), exist_ok=True)
    with open(os.path.join(tmp, "project.godot"), "w") as f:
        f.write("config_version=5\n")
    if extra_conf:
        with open(os.path.join(tmp, "art_src", "dotwork", "dotwork.config.json"), "w", encoding="utf-8") as f:
            json.dump(extra_conf, f)
    return tmp


class DotworkExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_exam_")
        os.environ.pop("COMFYUI_URL", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bind(self, conf=None, engine=None):
        make_project(self.tmp, dict({"comfyui": {"url": self.url}}, **(conf or {})))
        import engine as eng
        import godot
        s = fcore.Settings(self.tmp, engine=engine)
        fcore.bind(s)
        fcore.load_lock()
        eng.bind(s.conf)
        godot.ENABLED = s.godot()
        return s

    # ---- settings, spec, exit codes
    def test_settings_layering_and_env(self):
        s = self.bind({"project": {"assets_dir": "public/assets"}, "style_refs": ["a.png"]})
        self.assertEqual(s.conf["project"]["assets_dir"], "public/assets")
        self.assertEqual(s.conf["project"]["src_dir"], "assets_src")       # example default kept
        self.assertTrue(s.assets.endswith(os.path.join("public", "assets")))
        os.environ["COMFYUI_URL"] = "http://127.0.0.1:9999"
        try:
            self.assertEqual(fcore.Settings(self.tmp).conf["comfyui"]["url"], "http://127.0.0.1:9999")
        finally:
            del os.environ["COMFYUI_URL"]
        with self.assertRaises(fcore.ToolError):
            fcore.Settings(self.tmp, engine="unity")
        with self.assertRaises(fcore.ToolError):
            fcore.Settings(self.tmp, config=os.path.join(self.tmp, "missing.json"))

    def test_spec_errors_exit_2(self):
        import dotwork
        make_project(self.tmp)
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"name": "x", "propz": []}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = dotwork.main(["pack", "--spec", bad, "--project", self.tmp])
        self.assertEqual(code, 2)
        self.assertIn("unknown keys propz", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(dotwork.main(["pack", "--spec", bad, "--project", self.tmp]), 2)
        # entry level: no name = a usage error, a missing key the lane needs = a usage error naming it, a key no lane
        # reads = a warning (it used to build the default silently)
        cases = [({"name": "x", "windows": [{"style": "classic"}]}, 2, "windows entry 1 needs a \"name\""),
                 ({"name": "x", "fonts": [{"name": "f", "glyph": "glyphs/dialogue.txt"}]}, 2, "missing the key 'glyphs'"),
                 ({"name": "x", "windows": [{"name": "w", "styl": "iron"}]}, 0, "key 'styl' is not read")]
        for spec, want, text in cases:
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(spec, f)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = dotwork.main(["pack", "--spec", bad, "--project", self.tmp, "--engine", "none"])
            self.assertEqual(code, want, err.getvalue())
            self.assertIn(text, err.getvalue())
            self.assertNotIn("unexpected failure", err.getvalue())
        # global options work before the subcommand too (the kit's dev.py rule)
        self.assertEqual(dotwork.sink_global_options(["--debug", "--project", "g", "setup", "--check"],
                                                   ["setup"]), ["setup", "--debug", "--project", "g", "--check"])

    def test_spec_utf8(self):
        import dotwork
        p = os.path.join(self.tmp, "u.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"name": "u", "fonts": [{"name": "s", "export": {"\u261e": "cursor"}}]}, f, ensure_ascii=False)
        self.assertIn("\u261e", dotwork.load_spec(p)["fonts"][0]["export"])

    # ---- manifest, naming
    def test_manifest_rows_and_drop(self):
        s = self.bind()
        man = fcore.Manifest(s, "Town Pack")
        f = os.path.join(s.assets, "art", "props", "spr_barrel.png")
        fcore.save_clean(Image.new("RGBA", (4, 4)), f)
        man.add(f, "prop", routes=("klein",), prompt="a barrel", seed=4)
        man.add(f, "prop", routes=("klein",), prompt="a barrel", seed=5)   # same file: one row, updated
        self.assertEqual(len(man.data["assets"]), 1)
        self.assertEqual(man.data["assets"][0]["seed"], 5)
        self.assertIn("flux-2-klein-4b.safetensors", man.data["assets"][0]["models"])
        self.assertIsNone(man.add(None, "tileset"))
        man.drop_dir(os.path.dirname(f))
        self.assertFalse(os.path.exists(f))
        self.assertEqual(man.data["assets"], [])
        self.assertTrue(man.path.endswith("manifest_town_pack.json"))
        self.assertEqual(fcore.snake("Brass Golem #2"), "brass_golem_2")
        with self.assertRaises(fcore.ToolError):
            fcore.snake("!!!")

    # ---- retakes: a changed prompt / seed / palette / style reference must re-render, an unchanged entry must not
    def test_cache_keys_and_request_stamp(self):
        import engine
        s = self.bind()
        man = fcore.Manifest(s, "retake")
        f = os.path.join(s.assets, "art", "props", "spr_lamp.png")
        fcore.save_clean(Image.new("RGBA", (4, 4)), f)
        req = fcore.key("a lamp", 4100, 56)
        man.add(f, "prop", request=req)
        self.assertTrue(man.current(f, req))
        self.assertFalse(man.current(f, fcore.key("a lamp", 4101, 56)))       # new seed: render again
        self.assertFalse(man.current(f + ".missing", req))                     # never shipped
        self.assertNotEqual(fcore.key("a", 1), fcore.key("a", 2))
        self.assertEqual(engine.ref_key(s.conf), "none")                       # portable default: no reference
        conf = dict(s.conf, style_refs=["assets_src/ref/sprite_a.png"])
        self.assertNotEqual(engine.ref_key(conf), "none")
        off = dict(conf, design=dict(conf["design"], character=dict(conf["design"]["character"], style_ref="")))
        self.assertEqual(engine.ref_key(off), "none")                          # a spec switched it off
        pal = os.path.join(self.tmp, "p.hex")
        fcore.write_text(pal, "112233\n")
        k1 = fcore.palette_key(pal)
        fcore.write_text(pal, "112234\n")
        self.assertNotEqual(k1, fcore.palette_key(pal))                       # edited palette: re-snap

    def test_character_design_stamp(self):
        s = self.bind()
        import lane_character
        man = fcore.Manifest(s, "cast")
        c = lane_character.Character({"name": "guard", "prompt": "a town guard"}, s.project, man, s.conf)
        self.assertTrue(c.out.startswith(s.assets))                            # configured assets_dir, not "assets"
        south = os.path.join(c.work, "south.png")
        fcore.save_clean(Image.new("RGBA", (4, 4)), south)
        lane_character.Character({"name": "guard", "prompt": "a town guard"}, s.project, man, s.conf)
        self.assertTrue(os.path.exists(south))                                  # same design: renders kept
        with contextlib.redirect_stdout(io.StringIO()):
            lane_character.Character({"name": "guard", "prompt": "a palace guard"}, s.project, man, s.conf)
        self.assertFalse(os.path.exists(south))                                 # new design: retired...
        self.assertEqual(len([d for d in os.listdir(c.work) if d.startswith("_old_")]), 1)   # ...not deleted
        # audition / --promote pass no prompt or source: they reuse the renders and keep the stamp (they used to
        # retire everything and rewrite it, so one audition cost the next run every render)
        fcore.save_clean(Image.new("RGBA", (4, 4)), south)
        with open(os.path.join(c.work, "stamp.json"), encoding="utf-8") as f:
            stamp = f.read()
        lane_character.Character({"name": "guard", "asymmetric": False}, s.project, man, s.conf)
        self.assertTrue(os.path.exists(south))
        with open(os.path.join(c.work, "stamp.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), stamp)
        # spec names that become paths: actions are snaked, only s/e/n/w are directions, pose names are snaked
        c2 = lane_character.Character({"name": "guard", "prompt": "a palace guard", "actions": ["../../../evil"]},
                                      s.project, man, s.conf)
        self.assertEqual(c2.actions, ["evil"])
        with self.assertRaises(fcore.ToolError):
            lane_character.Character({"name": "guard", "prompt": "a palace guard", "directions": ["s", "../x"]},
                                     s.project, man, s.conf)

    def test_spec_names_never_leave_the_game(self):
        # font export file names and map prop names come from specs: they are snaked like every other name
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        spec = os.path.join(self.tmp, "fx.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "fx", "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt",
                                                "export": {"A": "../../../../escaped_a"}}]}, f)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "escaped_a.png")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "assets", "art", "ui", "symbols", "escaped_a.png")))
        import mapbuild
        self.assertEqual(mapbuild.plan_props({"props": [{"prop": "../../x/oak", "at": [0, 0]}]}, 32, "res://a", "art")[0]["name"],
                         "x_oak")
        # a manifest row pointing outside the game (a pull request can carry one) stops the Aseprite round trip
        import aseprite
        man = os.path.join(self.tmp, "assets_src", "dotwork", "manifest_fx.json")
        with open(man, encoding="utf-8") as f:
            data = json.load(f)
        data["assets"].append({"file": "../../outside/frames/spr_x_idle_s_00.png", "kind": "frame", "animation": "idle_s"})
        with open(man, "w", encoding="utf-8") as f:
            json.dump(data, f)
        with self.assertRaises(fcore.ToolError):
            aseprite._Manifests()

    # ---- RAM guard: an unreadable probe (often a sign memory is short) must refuse, never wave a heavy job through
    def test_require_ram(self):
        self.bind()
        fcore.require_ram(18, wait=0, probe=lambda: 30.0)                       # plenty: go
        with self.assertRaises(fcore.JobError):
            fcore.require_ram(18, wait=0, probe=lambda: 5.0)                    # too little: refuse
        with self.assertRaises(fcore.JobError):
            fcore.require_ram(18, wait=0, probe=lambda: -1.0)                   # probe failed: refuse, not "plenty"
        with contextlib.redirect_stdout(io.StringIO()):
            fcore.require_ram(18, wait=0, probe=lambda: None)                   # OS without a probe: logged, skipped
        self.assertIsNotNone(fcore.free_ram_gb())                                # this OS has a probe

    # ---- ComfyUI over HTTP: upload, queue, download stripped
    def test_comfy_roundtrip_strips_metadata(self):
        self.bind()
        import engine
        name = engine.put(Image.new("RGB", (8, 8), (255, 255, 255)), "dotwork_test_up.png")
        self.assertEqual(name, "dotwork_test_up.png")
        path, sec = engine.run(engine.klein("a lamp", 1, 64, 64, "dotwork_work/sprites/t/raw_s1"))
        self.assertTrue(path.replace("\\", "/").endswith("comfy_out/dotwork_work/sprites/t/raw_s1_00001_.png"))
        data = read(path, "rb")
        self.assertTrue(data.startswith(PNG_SIG))
        self.assertNotIn(b"tEXt", data)
        self.assertNotIn(b"secret.safetensors", data)

    def test_remote_server_refused(self):
        make_project(self.tmp, {"comfyui": {"url": "http://10.1.2.3:8188"}})
        import engine
        s = fcore.Settings(self.tmp)
        fcore.bind(s)
        engine.bind(s.conf)
        fcore.comfy_alive = lambda url: True   # pretend it answers; the local-only rule must still refuse it
        try:
            with self.assertRaises(fcore.ToolError):
                engine.base_url()
        finally:
            import importlib
            importlib.reload(fcore)

    # ---- numpy image core
    def test_label_matches_bfs(self):
        import engine
        rng = np.random.default_rng(3)
        for _ in range(25):
            m = rng.random(tuple(rng.integers(1, 30, 2))) < 0.5
            for conn in (4, 8):
                lab, n = engine.label(m, conn)
                self.assertEqual(n, self._bfs_count(m, conn))
                self.assertTrue((lab[~m] == 0).all())

    @staticmethod
    def _bfs_count(m, conn):
        seen, n = np.zeros_like(m), 0
        nb = [(-1, 0), (1, 0), (0, -1), (0, 1)] + ([(-1, -1), (-1, 1), (1, -1), (1, 1)] if conn == 8 else [])
        for y, x in zip(*np.nonzero(m)):
            if seen[y, x]:
                continue
            n += 1
            q = deque([(y, x)])
            seen[y, x] = True
            while q:
                cy, cx = q.popleft()
                for dy, dx in nb:
                    yy, xx = cy + dy, cx + dx
                    if 0 <= yy < m.shape[0] and 0 <= xx < m.shape[1] and m[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
        return n

    def test_key_and_palette(self):
        import engine
        rgb = np.full((20, 20, 3), 255, np.uint8)
        rgb[5:15, 5:15] = (200, 30, 30)
        rgb[8:12, 8:12] = 255                      # white detail inside the figure survives keying
        a = engine.key_bg(rgb)
        self.assertTrue(a[9, 9] and a[5, 5] and not a[0, 0])
        arr = np.dstack([rgb, np.where(a, 255, 0).astype(np.uint8)])
        pal = np.array([[0, 0, 0], [255, 255, 255], [210, 20, 20]], np.uint8)
        q = engine.quantize(arr, pal)
        self.assertEqual(tuple(q[6, 6, :3]), (210, 20, 20))

    # ---- blob atlas
    def test_blob_layout_and_seams(self):
        self.bind()
        import lane_ground as lg
        self.assertEqual(len(lg.BLOB), 47)
        self.assertIn(255, lg.BLOB)
        T = 32
        A = (np.random.default_rng(1).random((T, T, 3)) * 255).astype(np.uint8)
        atlas = lg.blob_atlas(A, T, "raised", 7, (A, A))
        self.assertEqual(atlas.shape, (((47 * 3) + 11) // 12 * T, 12 * T, 4))
        rows = lg.blob_rows(0, T, "dirt", True, 2)
        self.assertEqual(len(rows), 47 * 3)
        self.assertTrue(all(r["peers"][0] in (0, -1) for r in rows))
        self.assertEqual({r["probability"] for r in rows}, {1.0, 0.5})
        wob = lg._wobble(T, 5, 3.0)
        P = np.zeros((6, 6), bool)
        P[1:5, 1:5] = True
        P[2, 2] = False
        asm = np.zeros((6 * T, 6 * T), bool)
        for y in range(1, 5):
            for x in range(1, 5):
                if P[y, x]:
                    m = sum(1 << b for b, (dx, dy) in enumerate(lg.NB8) if P[y + dy, x + dx])
                    asm[y * T:(y + 1) * T, x * T:(x + 1) * T] = lg.blob_canvas(lg.canon(m), T, 5, 4, wob)[T:2 * T, T:2 * T]
        # every tile is a crop of its own 3x3 neighbourhood, so the assembled map must equal one coverage computed over
        # the whole map: then no seam can step (this used to assert a | ~a, which can never fail; 2026-10-30 Kimi
        # audit). Same rule as blob_canvas: inset from unpainted cells, T-periodic wobble, convex corners rounded.
        ys, xs = np.mgrid[0:6 * T, 0:6 * T] + 0.5
        d = np.full(xs.shape, 1e9)
        for cy in range(6):
            for cx in range(6):
                if not P[cy, cx]:
                    x0, x1, y0, y1 = cx * T, (cx + 1) * T, cy * T, (cy + 1) * T
                    d = np.minimum(d, np.hypot(np.maximum(0, np.maximum(x0 - xs, xs - x1)),
                                               np.maximum(0, np.maximum(y0 - ys, ys - y1))))
        core_ = d >= 5 + 4 + np.tile(wob[T:2 * T, T:2 * T], (6, 6))
        ref, H = np.zeros_like(core_), core_.shape[0]
        for dy, dx in lg._disk(4):
            ref[max(0, dy):H + min(0, dy), max(0, dx):H + min(0, dx)] |= \
                core_[max(0, -dy):H + min(0, -dy), max(0, -dx):H + min(0, -dx)]
        np.testing.assert_array_equal(asm, ref & np.kron(P, np.ones((T, T), bool)))
        self.assertTrue(asm.any() and not asm.all())   # a real shape: painted area with a hole and an outside edge

    # ---- Godot writers
    def test_tres_writers(self):
        s = self.bind()
        import godot
        d = os.path.join(s.assets, "art", "t")
        sf = godot.sprite_frames(os.path.join(d, "f.tres"), "res://assets/art/t", {"walk_s": (["a.png", "b.png"], 8, True)})
        t = read(sf)
        self.assertIn('[gd_resource type="SpriteFrames"', t)
        self.assertIn('"name": &"walk_s"', t)
        ts = godot.tileset_layers(os.path.join(d, "ts.tres"), 32, [{"atlas_res": "res://assets/art/t/o.png", "tiles": [
            {"x": 0, "y": 0, "terrain": 0, "peers": (0, -1, 0, -1, 0, -1, 0, -1), "probability": 0.5,
             "solid_rects": [(-16, -16, 16, 16)], "anim": {"frames": 4, "fps": 6}}]}], [("dirt", (120, 80, 40))],
            physics=True, overlays=[0], mode="match_corners_and_sides")
        t = read(ts)
        for key in ("terrain_set_0/mode = 0", "0:0/0/terrains_peering_bit/top_side = 0", "0:0/0/probability = 0.500",
                    "physics_layer_0/polygon_0/points", "0:0/animation_columns = 4", "dotwork_overlays"):
            self.assertIn(key, t)
        scn, fp = godot.prop_scene(os.path.join(d, "p.tscn"), "res://assets/art/t/p.png", (64, 64), (20, 10, 44, 60),
                                   footprint="trunk")
        self.assertIn('type="StaticBody2D"', read(scn))
        godot.ENABLED = False
        self.assertIsNone(godot.sprite_frames(os.path.join(d, "g.tres"), "res://x", {"a": (["a.png"], 8, False)}))
        godot.ENABLED = True

    # ---- mapbuild text -> cells
    def test_mapbuild_plan(self):
        self.bind()
        import mapbuild
        ground = {"tile_px": 32, "sources": [
            {"name": "grass", "kind": "base", "tiles": [{"x": 0, "terrain": None, "probability": 1.0}]},
            {"name": "dirt", "kind": "overlay", "tiles": [{"x": 0, "y": 0, "terrain": 1}]},
            {"name": "fixtures", "kind": "fixtures", "cols": 12,
             "fixtures": {"door": {"w": 1, "h": 2, "first": 0, "solid": True}}, "tiles": []}]}
        m = {"rows": ["gd ", "dd "], "legend": {"g": [], "d": ["dirt"], " ": ["none"]},
             "objects": [{"fixture": "door", "at": [0, 0]}]}
        layers, w, h = mapbuild.plan(m, ground)
        self.assertEqual((w, h), (3, 2))
        base = next(L for L in layers if L["name"] == "Base")
        self.assertEqual(len(base["cells"]), 4)                     # two "none" cells get no base
        dirt = next(L for L in layers if L["name"] == "Dirt")
        self.assertEqual(sorted(map(tuple, dirt["cells"])), [(0, 1), (1, 0), (1, 1)])
        fx = next(L for L in layers if L["name"] == "Fixtures")
        self.assertEqual([c[:2] for c in fx["cells"]], [[0, 0], [0, 1]])
        props = mapbuild.plan_props({"props": [{"prop": "oak", "at": [2, 3]}]}, 32, "res://assets", "art")
        self.assertEqual(props[0]["x"], 2 * 32 + 16)
        self.assertEqual(props[0]["y"], 4 * 32)

    # ---- glyphs and fonts
    def test_glyphs(self):
        s = self.bind()
        import lane_fonts
        meta, g = lane_fonts.parse(os.path.join(DOTWORK, "glyphs", "dialogue.txt"))
        self.assertEqual(len(g), 94)
        self.assertEqual(g["A"].shape[0], meta["height"])
        bad = os.path.join(self.tmp, "bad.txt")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("height 3\nchar A\n#x#\n")
        with self.assertRaises(ValueError):
            lane_fonts.parse(bad)
        fnt, png, meta, rendered, line_h, gl = lane_fonts.build("dlg", os.path.join(DOTWORK, "glyphs", "damage.txt"),
                                                                os.path.join(s.assets, "art", "ui", "fonts"), 2, "outline")
        t = read(fnt)
        self.assertIn("chars count=16", t)                      # 15 glyphs + space
        self.assertIn(f"lineHeight={line_h}", t)
        with Image.open(png) as im:
            self.assertEqual(im.mode, "RGBA")

    # ---- connectors
    def test_connectors(self):
        import connectors
        T = 32
        horiz = connectors.tile(4 | 64, T, "pipe")             # E + W
        self.assertTrue(horiz[T // 2, 0, 3] > 0 and horiz[T // 2, T - 1, 3] > 0)
        self.assertEqual(horiz[0, T // 2, 3], 0)                # nothing toward N
        elbow = connectors.tile(1 | 4, T, "rail")               # N + E curve
        self.assertTrue(elbow[..., 3].any())
        rects = connectors.solid_rects(1 | 16, T, "fence_wood")
        self.assertEqual(len(rects), 3)
        self.assertIsNone(connectors.solid_rects(4, T, "rail"))

    # ---- SpriteKiln loading
    def test_spritekiln_loader(self):
        import spritekiln
        clone = os.path.join(self.tmp, "spritekiln")
        os.makedirs(os.path.join(clone, "workflows", "api"))
        with open(os.path.join(clone, "workflows", "api", "04_edit_pixel_art.api.json"), "w", encoding="utf-8") as f:
            json.dump({"7": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}}}, f)
        spritekiln.bind({"spritekiln_root": clone})
        g = spritekiln.load("04_edit_pixel_art")
        self.assertEqual(g["7"]["inputs"]["vae_name"], "flux2-vae-klein.safetensors")
        with self.assertRaises(fcore.ToolError):
            spritekiln.load("99_missing")
        spritekiln.bind({"spritekiln_root": os.path.join(self.tmp, "nowhere")})
        with self.assertRaises(fcore.ToolError):
            spritekiln.root()

    # ---- --engine none: model-free lanes end to end, and no Godot file may leak into a non-Godot game
    def test_engine_none_pack(self):
        import dotwork
        make_project(self.tmp, {"comfyui": {"url": self.url}, "project": {"assets_dir": "public/assets"}})
        spec = os.path.join(self.tmp, "ui.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "ui", "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt"}],
                       "windows": [{"name": "classic", "style": "classic"}],
                       "balloons": [{"name": "exclaim", "symbol": "!", "color": "d83a3a"}],
                       "hitfx": [{"name": "spark", "kind": "spark"}, {"name": "flash", "kind": "flash"}]}, f)
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = dotwork.main(["pack", "--spec", spec, "--project", self.tmp, "--engine", "none"])
        self.assertEqual(code, 0)
        made = [os.path.join(r, n) for r, _, ns in os.walk(os.path.join(self.tmp, "public")) for n in ns]
        self.assertTrue(any(m.endswith(".png") for m in made) and any(m.endswith(".fnt") for m in made))
        self.assertEqual([m for m in made if m.endswith((".tres", ".tscn", ".gdshader", ".gd"))], [])
        with open(os.path.join(self.tmp, "art_src", "dotwork", ".gitignore"), encoding="utf-8") as f:
            self.assertIn("!dotwork.config.json", f.read())   # the work folder keeps itself out of git
        # ... and out of Godot's import (raw ComfyUI .webp clips there broke verify)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "art_src", "dotwork", ".gdignore")))
        # everything in this pack is drawn in code: no row may claim a model (the asset log reads these)
        with open(os.path.join(self.tmp, "assets_src", "dotwork", "manifest_ui.json"), encoding="utf-8") as f:
            self.assertEqual([r["file"] for r in json.load(f)["assets"] if r.get("models")], [])

    # ---- Godot crash vs import errors (a crash is retried once, errors never)
    def test_godot_crash_detect(self):
        import godotrun
        self.assertTrue(godotrun.crashed(1, "[FAIL] import failed (exit 3221225477)\n"))   # dev.py relaying a crash
        self.assertTrue(godotrun.crashed(-11, ""))                                         # killed by a signal
        self.assertTrue(godotrun.crashed(3221225477, ""))                                  # direct Windows crash
        self.assertFalse(godotrun.crashed(1, "[FAIL] import failed (exit 1)\nERROR: bad resource\n"))
        self.assertFalse(godotrun.crashed(0, "ERROR: Cannot get keys from nonexistent section\n"))

    # ---- 2026-10-30 audit regressions
    def test_tileset_anim_keeps_all_sources(self):
        s = self.bind()
        import godot
        def src(name, anim):
            tile = {"x": 0, "y": 0, "terrain": None}
            if anim:
                tile["anim"] = {"frames": 3, "fps": 4}
            return {"atlas_res": f"res://{name}.png", "tiles": [tile]}
        t = read(godot.tileset_layers(os.path.join(s.assets, "art", "t", "five.tres"), 32,
                                      [src("a", True)] + [src(n, False) for n in "bcde"], [("dirt", (1, 2, 3))]))
        self.assertIn("load_steps=11", t)
        for i in range(5):   # the animated tile's frame count (3) used to cut the list to 3 sources
            self.assertIn(f'sources/{i} = SubResource("TileSetAtlasSource_{i + 1}")', t)

    def test_shrink_keeps_big_figures_whole(self):
        import engine
        raw = os.path.join(self.tmp, "raw.png")
        im = Image.new("RGB", (1008, 1008), (255, 255, 255))
        im.paste((40, 30, 20), (54, 54, 954, 954))            # a 900 px figure on the white background
        im.save(raw)
        init, small = engine.shrink(raw, 192, fit="longest")  # a boss: 192 px longest side
        self.assertEqual(max(small.size), 192)
        self.assertEqual(init.size, (198 * 8, 198 * 8))       # the canvas grew (it used to stay 126 cells and crop)
        cells = np.array(init.resize((198, 198), Image.NEAREST))
        dark = np.nonzero(cells.min(2) < 128)
        self.assertEqual((dark[0].max() - dark[0].min() + 1, dark[1].max() - dark[1].min() + 1), (192, 192))
        init, _ = engine.shrink(raw, 66)                       # a normal sprite keeps the 1008 px refine
        self.assertEqual(init.size, (1008, 1008))

    def test_sample_grid_alignment(self):
        import engine
        pat = np.random.default_rng(3).integers(0, 255, (16, 16, 3), dtype=np.uint8)
        big = np.repeat(np.repeat(pat, 8, axis=0), 8, axis=1)
        out = engine.sample(big, np.ones(big.shape[:2], bool), 8, 0, 8, 0, 0.5)
        self.assertEqual(out.shape[:2], (16, 16))          # no extra off-image cell before column/row 0
        self.assertTrue((out[..., :3] == pat).all())

    def test_job_files_only_this_job(self):
        import engine
        r = {"files": ["w/rot/r_00003_.png", "w/rot/r_00004_.png", "w/rot/r_raw_00001_.webp"]}
        self.assertEqual([os.path.basename(p) for p in engine.job_files(r, "r_*.png")], ["r_00003_.png", "r_00004_.png"])

    def test_spec_paths_stay_in_the_game(self):
        self.bind()
        self.assertEqual(fcore.project_path("assets_src/x.png"),
                         os.path.normpath(os.path.join(fcore.PROJECT, "assets_src", "x.png")))
        for bad in ("../outside.png", "assets_src/../../outside.png", os.path.abspath(os.sep + "etc"),
                    "\\\\host\\share\\x.png", "//host/share/x.png"):
            with self.assertRaises(fcore.ToolError, msg=bad):
                fcore.project_path(bad)
        cli = os.path.normpath(os.path.join(tempfile.gettempdir(), "dotwork_cli_source.png"))
        fcore.TRUSTED.add(cli)    # an absolute --source typed on the command line is the user's choice
        try:
            self.assertEqual(fcore.project_path(cli), cli)
        finally:
            fcore.TRUSTED.discard(cli)
        self.assertTrue(fcore.contained("glyphs/damage.txt", fcore.HERE, fcore.PROJECT).endswith("damage.txt"))

    def test_seed_from_name(self):
        self.assertEqual(fcore.seed_of({"name": "Old Lamp"}, 4000), fcore.seed_of({"name": "old_lamp"}, 4000))
        self.assertTrue(4000 <= fcore.seed_of({"name": "crate"}, 4000) < 5000)
        self.assertEqual(fcore.seed_of({"name": "crate", "seed": 7}, 4000), 7)

    def test_settings_refuse_odd_tile_px(self):
        self.bind()
        with self.assertRaises(fcore.ToolError):
            fcore.Settings(self.tmp, spec={"design": {"tile_px": 48}})

    def test_tool_timeout_is_a_job_failure(self):
        # the tool starts a child of its own (as the kit's dev.py starts Godot): both must go, or the pipes stay open
        code = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
                " time.sleep(60)")
        t0 = time.time()
        with self.assertRaises(fcore.JobError):
            fcore.run([sys.executable, "-c", code], timeout=2)
        self.assertLess(time.time() - t0, 9)

    def test_verify_error_markers(self):
        import verify
        self.assertTrue(verify.ERROR_LINE.search("ERROR: Error loading image: 'res://x.webp'."))
        self.assertTrue(verify.ERROR_LINE.search("SCRIPT ERROR: Parse Error: bad"))
        self.assertFalse(verify.ERROR_LINE.search("imported res://maps/terror_bridge.tscn"))
        self.assertFalse(verify.ERROR_LINE.search("import done, 0 errors"))

    # ---- 2026-10-30 stranger run-through
    def run_dotwork(self, *argv):
        import dotwork
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dotwork.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def ui_spec(self, folder):
        spec = os.path.join(folder, "ui.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "ui", "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt"}],
                       "windows": [{"name": "classic", "style": "classic"}]}, f)
        return spec

    def test_wrong_folder_refused_and_untouched(self):
        tools = os.path.join(self.tmp, "tools")          # run from a game's tools/ by mistake: no project.godot
        os.makedirs(tools)
        spec = self.ui_spec(self.tmp)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", tools, "--engine", "none")
        self.assertEqual(code, 2)
        self.assertIn("is not a game folder", out)
        self.assertEqual(self.run_dotwork("config", "--project", tools)[0], 0)
        self.assertEqual(os.listdir(tools), [])           # it used to write ~100 files there and exit 0
        with open(os.path.join(tools, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# a kit game without Godot\n")
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", tools, "--engine", "none")
        self.assertEqual(code, 0, out)

    def test_log_twice_updates_one_row(self):
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        os.makedirs(os.path.join(self.tmp, "docs"))
        with open(os.path.join(self.tmp, "docs", "ASSET_LOG.md"), "w", encoding="utf-8") as f:
            f.write("| ID | Type | File(s) in repo | Source / URL | Author | License | Attribution text (if required) | "
                    "AI-assisted? | Modified? | Date added | Notes |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
                    "| A-0001 | | | | | | | no | no | 2026-10-22 | |\n")
        spec = self.ui_spec(self.tmp)
        self.assertEqual(self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--engine", "none")[0], 0)
        for _ in range(2):
            code, out = self.run_dotwork("log", "--pack", "ui", "--project", self.tmp)
            self.assertEqual(code, 0, out)
        self.assertIn("A-0001 updated in", out)
        with open(os.path.join(self.tmp, "docs", "ASSET_LOG.md"), encoding="utf-8") as f:
            self.assertEqual(len([r for r in f.read().splitlines() if r.startswith("| A-")]), 1)

    def test_engine_none_drops_godot_rows(self):
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        spec = self.ui_spec(self.tmp)
        self.assertEqual(self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")[0], 0)
        man = os.path.join(self.tmp, "assets_src", "dotwork", "manifest_ui.json")
        with open(man, encoding="utf-8") as f:
            self.assertTrue(any(r["file"].endswith(".tscn") for r in json.load(f)["assets"]))
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 0, out)
        self.assertIn("left the manifest", out)
        with open(man, encoding="utf-8") as f:
            self.assertFalse(any(r["file"].endswith((".tres", ".tscn", ".gdshader")) for r in json.load(f)["assets"]))

    def test_preview_help_verify_none_and_spec_paths(self):
        code, out = self.run_dotwork("preview", "--help")
        self.assertEqual(code, 0)
        self.assertIn("battle", out)
        self.assertEqual(self.run_dotwork("preview")[0], 2)
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        code, out = self.run_dotwork("verify", "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 2)
        self.assertIn("--engine none", out)
        self.ui_spec(self.tmp)                            # a relative --spec also resolves against --project
        code, out = self.run_dotwork("pack", "--spec", "ui.json", "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 0, out)
        code, out = self.run_dotwork("pack", "--spec", "nope.json", "--project", self.tmp)
        self.assertEqual(code, 2)
        self.assertIn(os.path.abspath(os.path.join(self.tmp, "nope.json")), out)

    def test_vehicle_rotation_plan(self):
        # the rotation treats its source as the front, so a source facing sw shifts every label one step, and only an
        # s or n source may mirror its east half onto the west (2026-10-30: the airship came back one step round)
        self.bind()
        import lane_vehicles as v
        self.assertEqual(v.rotation_plan({"name": "a"})[:2], (None, False))   # auto: all 8 generated, labelled later
        order, mirror, extra = v.rotation_plan({"name": "a", "source_facing": "SW"})
        self.assertEqual(order[:3], ["sw", "w", "nw"])
        self.assertEqual(sorted(order), sorted(v.ROT8))
        self.assertFalse(mirror)                                  # a three-quarter source cannot be mirrored
        self.assertEqual(v.rotation_plan({"name": "a", "source_facing": "n"})[:2],
                         (["n", "ne", "e", "se", "s", "sw", "w", "nw"], True))
        self.assertFalse(v.rotation_plan({"name": "a", "source_facing": "s", "asymmetric": True})[1])
        with self.assertRaises(fcore.ToolError):
            v.rotation_plan({"name": "a", "source_facing": "up"})
        with self.assertRaises(fcore.ToolError):
            v.rotation_plan({"name": "a", "rot_order": ["s"] * 8})
        # auto: a true turn has e/w, ne/nw, se/sw as mirror pairs and symmetric s and n; the mirror test finds the
        # source facing from the 8 views alone, whichever way the source was drawn
        def blob(cells):
            im = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
            for x, y in cells:
                im.putpixel((x, y), (200, 90, 40, 255))
            return im
        box = [(x, y) for x in range(2, 10) for y in range(6, 12)]
        side = [(x, y) for x in range(0, 12) for y in range(9, 12)] + [(x, y) for x in range(0, 4) for y in range(3, 9)]
        q1 = [(x, y) for x in range(0, 9) for y in range(7, 12)] + [(x, y) for x in range(0, 3) for y in range(1, 7)]
        q2 = [(x, y) for x in range(0, 10) for y in range(8, 12)] + [(x, y) for x in range(5, 8) for y in range(2, 8)]
        true = {"s": blob(box), "n": blob(box[:30]), "e": blob(side), "ne": blob(q1), "se": blob(q2)}
        true.update(w=true["e"].transpose(Image.FLIP_LEFT_RIGHT), nw=true["ne"].transpose(Image.FLIP_LEFT_RIGHT),
                    sw=true["se"].transpose(Image.FLIP_LEFT_RIGHT))
        for src in ("sw", "se", "s"):
            got, scores = v.pick_facing([true[d] for d in v.ring(src)])
            self.assertEqual(got, src, scores)
        self.assertAlmostEqual(v.mirror_fit(true["e"], true["w"]), 1.0)

    def test_palette_swap(self):
        # a swap turns the coloured ramps, keeps outline and greys, stays in the palette, keeps a ramp's steps apart,
        # and one map serves every frame (an animation must not flicker between two recolours)
        s = self.bind()
        import recolor
        from engine import load_hex
        pal = load_hex(s.conf["fixed"]["env_palette"])
        palset = {tuple(int(v) for v in c) for c in pal}
        reds = [c for c in pal if int(c[0]) > int(c[1]) + 60 and int(c[0]) > int(c[2]) + 60][:4]   # reds (no uint8 wrap)
        self.assertGreaterEqual(len(reds), 3)
        grey = min(pal, key=lambda c: abs(int(c[0]) - int(c[1])) + abs(int(c[1]) - int(c[2])) + abs(int(c[0]) - 40))
        im = Image.new("RGBA", (len(reds) + 1, 2), (0, 0, 0, 0))
        for x, c in enumerate(reds):
            im.putpixel((x, 0), tuple(int(v) for v in c) + (255,))
        im.putpixel((len(reds), 0), tuple(int(v) for v in grey) + (255,))
        frame2 = im.copy()
        frame2.putpixel((0, 1), tuple(int(v) for v in reds[0]) + (255,))
        (a, b), mapping = recolor.recolor([im, frame2], pal, hue=180)
        got = [a.getpixel((x, 0))[:3] for x in range(len(reds))]
        self.assertTrue(all(g in palset for g in got))
        self.assertEqual(len(set(got)), len(reds))                             # the ramp keeps its steps
        self.assertTrue(all(g[2] > g[0] for g in got))                          # red turned to a blue-green
        self.assertEqual(a.getpixel((len(reds), 0))[:3], tuple(int(v) for v in grey))   # the grey stays
        self.assertEqual(b.getpixel((0, 1)), a.getpixel((0, 0)))               # same map on every frame
        self.assertEqual(a.getpixel((0, 1))[3], 0)                              # alpha untouched
        # a hue range limits the swap; "to" turns the main hue to a colour's
        self.assertEqual(recolor.plan(np.array(reds), np.ones(len(reds)), pal, hue=180, hues=[100, 200]), {})
        to = recolor.plan(np.array(reds), np.ones(len(reds)), pal, to="#3a6ea5")
        self.assertTrue(all(d[2] > d[0] for d in to.values()))
        with self.assertRaises(fcore.ToolError):
            recolor.options({"name": "x"})                                      # a swap that changes nothing
        with self.assertRaises(fcore.ToolError):
            recolor.options({"name": "x", "hue": 30, "hues": [1]})
        # the enemies lane refuses a swap of an enemy the spec does not have, before any render
        spec = os.path.join(self.tmp, "foes.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "foes", "enemies": [{"name": "frost_hound", "recolor_of": "hound", "hue": 150}]}, f)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 2, out)
        self.assertIn("recolor_of 'hound'", out)
        self.assertNotIn("is not read by Dotwork", out)                         # hue is a known enemy key
        # the recolor command: a frame set in, one map, copies out inside the game; out of the game is refused
        src = os.path.join(self.tmp, "assets", "art", "props", "lamp")
        os.makedirs(src)
        im.save(os.path.join(src, "spr_lamp_00.png"))
        frame2.save(os.path.join(src, "spr_lamp_01.png"))
        code, out = self.run_dotwork("recolor", "--source", "assets/art/props/lamp/*.png", "--hue", "180", "--out",
                                     "assets/art/props/lamp_blue", "--palette", "env", "--project", self.tmp)
        self.assertEqual(code, 0, out)
        done = os.path.join(self.tmp, "assets", "art", "props", "lamp_blue", "spr_lamp_01.png")
        self.assertEqual(Image.open(done).getpixel((0, 1)), b.getpixel((0, 1)))
        code, out = self.run_dotwork("recolor", "--source", "assets/art/props/lamp/*.png", "--hue", "180", "--out",
                                     "../escaped", "--project", self.tmp)
        self.assertEqual(code, 2, out)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "escaped")))

    def test_clean_finds_the_grid(self):
        # an upscaled sprite (any cell size, any offset, a little noise) comes back pixel for pixel; a smooth image
        # has no grid; a grid the two axes disagree on is refused instead of guessed
        s = self.bind()
        import pxclean
        from engine import load_hex
        from engine import oklab
        pal = load_hex(s.conf["fixed"]["palette"])
        picks = []   # darker colours with no near twin in the palette: noise must not flip a pixel to its twin
        labs = oklab(pal)
        for c, lab in zip(pal, labs):
            twins = np.sqrt(((labs - lab) ** 2).sum(-1))
            if 0.2 < lab[0] < 0.7 and np.sort(twins)[1] > 0.03:   # near-black spreads out in OKLab
                picks.append(c)
        picks = np.array(picks)
        rng = np.random.default_rng(7)
        src = np.zeros((12, 15, 4), np.uint8)
        src[2:11, 3:13, :3] = picks[rng.integers(0, len(picks), (9, 10))]
        src[2:11, 3:13, 3] = 255
        for cell, ox, oy in ((4, 3, 1), (5, 0, 2), (8, 6, 7), (3, 2, 0)):
            big = np.repeat(np.repeat(src, cell, 0), cell, 1)
            can = np.full((big.shape[0] + oy + 5, big.shape[1] + ox + 4, 3), 255, np.uint8)
            region = can[oy:oy + big.shape[0], ox:ox + big.shape[1]]
            region[big[..., 3] == 255] = big[big[..., 3] == 255, :3]
            noisy = np.clip(can.astype(int) + rng.integers(-3, 4, can.shape), 0, 255).astype(np.uint8)
            arr, rep = pxclean.clean(Image.fromarray(noisy), palette=s.conf["fixed"]["palette"])
            self.assertEqual(rep["grid"], [cell, ox % cell, cell, oy % cell], rep)
            got = Image.fromarray(arr)
            got = np.array(got.crop(got.getbbox()))
            self.assertTrue(np.array_equal(got, src[2:11, 3:13]), (cell, ox, oy))
        smooth = Image.radial_gradient("L").resize((48, 48)).convert("RGB")
        self.assertEqual(pxclean.find_grid(np.array(smooth)), ((1, 0), (1, 0)))
        stripes = np.zeros((40, 40, 3), np.uint8)
        stripes[:, ::6] = 255                                                   # edges along x only
        with self.assertRaises(fcore.ToolError):
            pxclean.clean(Image.fromarray(stripes), bg="none", palette=None)
        # the command: a folder in, cleaned PNGs out inside the game, no metadata; out of the game is refused
        raw = os.path.join(self.tmp, "assets_src", "raw")
        os.makedirs(raw)
        Image.fromarray(noisy).save(os.path.join(raw, "lamp_4x.jpg"), quality=95)
        with open(os.path.join(raw, "meta.png"), "wb") as f:
            f.write(png_with_text(8, 8))
        code, out = self.run_dotwork("clean", "--source", "assets_src/raw/*", "--out", "assets/art/props/clean",
                                     "--cell", "3", "--project", self.tmp)
        self.assertEqual(code, 0, out)
        done = os.path.join(self.tmp, "assets", "art", "props", "clean")
        self.assertEqual(sorted(os.listdir(done)), ["lamp_4x.png", "meta.png"])
        self.assertNotIn(b"secret", read(os.path.join(done, "meta.png"), "rb"))
        code, out = self.run_dotwork("clean", "--source", "assets_src/raw/*", "--out", "../escaped", "--project",
                                     self.tmp)
        self.assertEqual(code, 2, out)
        code, out = self.run_dotwork("clean", "--source", "../*", "--out", "assets/x", "--project", self.tmp)
        self.assertEqual(code, 2, out)

    def test_widgets(self):
        # gauges: the fill shows only inside the frame, the over texture leaves the bar clear; buttons: five states
        # that read differently; one Theme wires the buttons and the panel; a typo'd style or a colourless custom
        # gauge stops the run
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        spec = os.path.join(self.tmp, "hud.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "hud", "widgets": [{"name": "hud", "style": "brass",
                                                   "gauges": ["hp", {"name": "rage", "color": ["ffb080", "f05a30",
                                                                                               "a02010"], "ticks": 4}]}]}, f)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 0, out)
        d = os.path.join(self.tmp, "assets", "art", "ui", "widgets", "hud")
        px = lambda n: np.array(Image.open(os.path.join(d, n)))
        fill, over = px("ui_gauge_hp_fill.png"), px("ui_gauge_hp_over.png")
        self.assertEqual(fill.shape, (16, 112, 4))                              # 56 x 8 at scale 2
        self.assertEqual(int(fill[0, 10, 3]), 0)                                # no fill on the frame
        self.assertEqual(int(fill[8, 56, 3]), 255)                              # the bar itself
        self.assertEqual(int(over[8, 56, 3]), 0)                                # over leaves the bar clear
        self.assertEqual(int(px("ui_gauge_rage_over.png")[8, 4 + round(1 * 52 / 4) * 2, 3]), 255)   # a tick
        mid = lambda st: px(f"ui_button_hud_{st}.png")[16, 16, :3].astype(int)
        self.assertGreater(mid("hover").sum(), mid("normal").sum())
        self.assertLess(mid("pressed").sum(), mid("normal").sum())
        dis = mid("disabled")
        self.assertLess(dis.max() - dis.min(), 12)                              # greyed out
        self.assertEqual(int(px("ui_button_hud_focus.png")[16, 16, 3]), 0)      # focus is a ring only
        th = read(os.path.join(d, "theme_hud.tres"))
        for st in ("normal", "hover", "pressed", "disabled", "focus"):
            self.assertIn(f'Button/styles/{st} = SubResource("StyleBoxTexture_{st}")', th)
        self.assertIn("PanelContainer/styles/panel", th)
        self.assertIn('[gd_resource type="Theme" load_steps=13 format=3]', th)   # 6 textures + 6 styles + 1
        self.assertIn("nine_patch_stretch = true", read(os.path.join(d, "gauge_rage.tscn")))
        for bad in ({"name": "x", "style": "bras"}, {"name": "x", "gauges": ["rage"]}):
            with open(spec, "w", encoding="utf-8") as f:
                json.dump({"name": "hud", "widgets": [bad]}, f)
            code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
            self.assertEqual(code, 2, out)

    def test_transitions_and_weather(self):
        # rule images: black is covered first, white last, in the order each kind promises; weather tiles wrap
        # seamlessly and use only palette colours; the scenes wire one material per layer; a bad kind stops the run
        s = self.bind()
        import lane_transitions as tr
        import lane_weather as wx
        from engine import load_hex
        f = tr.rule("iris", 64, 36)
        self.assertGreater(f[18, 32], f[0, 0])                                  # iris closes on the centre last
        f = tr.rule("wipe_right", 64, 36)
        self.assertTrue((np.diff(f, axis=1) >= 0).all() and f[0, 0] == 0 and f[0, -1] == 1)
        self.assertTrue((tr.rule("fade", 8, 8) == 0).all())                     # the shader's linear fade
        for kind in tr.KINDS[:-1]:
            g = tr.rule(kind, 64, 36)
            self.assertTrue(g.min() >= 0 and g.max() <= 1, kind)
        self.assertEqual(len(np.unique(np.asarray(tr.to_png(tr.rule("iris", 64, 36), 8)))), 8)   # 8 flat steps
        b = tr.bayer(4)
        self.assertEqual(sorted((b * 16 - 0.5).round().astype(int).ravel()), list(range(16)))
        pal = load_hex(s.conf["fixed"]["env_palette"])
        palset = {tuple(int(v) for v in c) for c in pal}
        p = wx.Painter(16, pal)
        p.dot(17, -1, (1, 2, 3))
        self.assertEqual(tuple(p.a[15, 1, :3]), (1, 2, 3))                      # dots wrap round the tile
        v = wx.value_noise(64, 4, np.random.default_rng(1))
        seam = np.abs(v[:, 0] - v[:, -1]).max()
        inner = np.abs(np.diff(v, axis=1)).max()
        self.assertLessEqual(seam, inner + 1e-9)                                # no step at the seam
        for kind in wx.KINDS:
            for lname, a, vel, wob in wx.layers(kind, 64, pal, 0.8, 3):
                op = a[..., 3] > 0
                self.assertTrue(op.any(), (kind, lname))
                self.assertTrue({tuple(int(x) for x in c) for c in a[op][:, :3]} <= palset, (kind, lname))
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        spec = os.path.join(self.tmp, "screen.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"name": "screen", "transitions": [{"name": "swirl", "kind": "spiral"},
                                                         {"name": "mosaic", "kind": "mosaic"}],
                       "weather": [{"name": "storm", "kind": "rain"}]}, fh)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 0, out)
        art = os.path.join(self.tmp, "assets", "art")
        scn = read(os.path.join(art, "ui", "transitions", "transition_swirl.tscn"))
        self.assertIn('shader_parameter/rule = ExtResource("2_rule")', scn)
        self.assertIn("mouse_filter = 2", scn)                                  # never eats clicks
        self.assertIn("hint_screen_texture", read(os.path.join(art, "ui", "transitions", "shaders", "mosaic.gdshader")))
        w = read(os.path.join(art, "fx", "weather", "weather_storm.tscn"))
        self.assertEqual(w.count('type="ColorRect"'), 2)                        # far and near rain
        self.assertIn("[gd_scene load_steps=6 format=3]", w)                    # shader + 2 tiles + 2 materials + 1
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 0, out)                                          # PNGs still ship without Godot
        self.assertTrue(os.path.exists(os.path.join(art, "fx", "weather", "weather_storm_near.png")))
        for bad in ({"transitions": [{"name": "x", "kind": "swril"}]}, {"weather": [{"name": "x", "kind": "hail"}]}):
            with open(spec, "w", encoding="utf-8") as fh:
                json.dump(dict({"name": "screen"}, **bad), fh)
            code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
            self.assertEqual(code, 2, out)

    def test_status_loops(self):
        # every kind animates, stays in the palette (plus the shared outline), and is outlined; the lane writes
        # frames, a sheet + JSON, SpriteFrames and an autoplaying scene; an unknown kind stops the run
        s = self.bind()
        import lane_status as st
        from engine import load_hex
        pal = load_hex(s.conf["fixed"]["palette"])
        ok = {tuple(int(v) for v in c) for c in pal} | {st.OUTLINE}
        for kind, (main, _) in st.KINDS.items():
            frames = [st.frame(kind, i / 8, 32, pal, main) for i in range(8)]
            self.assertTrue(all((f[..., 3] == 255).any() for f in frames), kind)
            self.assertGreater(len({f.tobytes() for f in frames}), 1, kind)          # it moves
            for f in frames:
                op = f[..., 3] == 255
                self.assertTrue({tuple(int(v) for v in c) for c in f[op][:, :3]} <= ok, kind)
                self.assertIn(st.OUTLINE, {tuple(int(v) for v in c) for c in f[op][:, :3]}, kind)
        ys = [np.nonzero(st.frame("poison", t, 32, pal, "8ad048")[..., 3])[0].mean() for t in (0.0, 0.1)]
        self.assertLess(ys[1], ys[0])                                               # bubbles rise
        make_project(self.tmp, {"comfyui": {"url": self.url}})
        spec = os.path.join(self.tmp, "st.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"name": "st", "status": [{"name": "zzz", "kind": "sleep", "fps": 6}]}, fh)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 0, out)
        d = os.path.join(self.tmp, "assets", "art", "fx", "status", "zzz")
        self.assertEqual(len([f for f in os.listdir(d) if f.startswith("spr_status_zzz_")]), 8)
        self.assertEqual(json.loads(read(os.path.join(d, "status_zzz_sheet.json")))["fps"], 6)
        with Image.open(os.path.join(d, "status_zzz_sheet.png")) as im:
            self.assertEqual(im.size, (256, 32))
        self.assertIn('autoplay = "zzz"', read(os.path.join(d, "status_zzz.tscn")))
        self.assertIn('"loop": true', read(os.path.join(d, "status_zzz_frames.tres")))
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"name": "st", "status": [{"name": "frog"}]}, fh)                # not a kind (yet)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 2, out)

    def test_portrait_expressions(self):
        # which expressions an entry asks for; the face-only merge keeps hair / clothes / framing pixel-identical and
        # reports edits that moved more than the face; a typo'd expression stops the run before anything renders
        self.bind()
        import lane_portraits as lp
        self.assertEqual(list(lp.wanted({"name": "a", "expressions": True})), list(lp.DEFAULT_SET))
        self.assertEqual(lp.wanted({"name": "a", "expressions": ["talk"]}), {"talk": lp.EXPRESSIONS["talk"]})
        self.assertEqual(lp.wanted({"name": "a", "expressions": {"Smug Grin": "a smug grin"}}), {"smug_grin": "a smug grin"})
        self.assertEqual(lp.wanted({"name": "a"}), {})
        with self.assertRaises(fcore.ToolError):
            lp.wanted({"name": "a", "expressions": ["hapy"]})
        base = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        for y in range(4, 40):
            for x in range(6, 34):
                base.putpixel((x, y), (120, 80, 60, 255))
        x0, y0, x1, y1 = lp.face_box(base)
        self.assertEqual((x0, y0, x1, y1), (6 + round(28 * 0.2), 4 + round(36 * 0.15), 6 + round(28 * 0.8),
                                            4 + round(36 * 0.82)))   # below the hair top, down to the chin
        edit = base.copy()
        edit.putpixel((20, 15), (250, 250, 250, 255))                            # a change in the face: kept
        edit.putpixel((8, 38), (250, 0, 0, 255))                                 # on the shoulder: dropped
        merged, outside = lp.keep_face(base, edit)
        self.assertEqual(merged.getpixel((20, 15)), (250, 250, 250, 255))
        self.assertEqual(merged.getpixel((8, 38)), base.getpixel((8, 38)))
        self.assertAlmostEqual(outside, 0.5)
        spec = os.path.join(self.tmp, "p.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"name": "p", "portraits": [{"name": "x", "prompt": "a knight", "expressions": ["grumpy"]}]}, fh)
        before = len(State.prompts)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--engine", "none")
        self.assertEqual(code, 2, out)
        self.assertIn("unknown expression 'grumpy'", out)
        self.assertEqual(len(State.prompts), before)                             # nothing was queued

    def test_small_icons_derived(self):
        # only the largest icon is rendered; the 16 px one is derived from it: same colours, a fresh outline, a 1 px
        # margin on every side, and every size exists after the run (D10: blob 16 px icons, half sets)
        s = self.bind()
        import lane_props
        big = np.zeros((32, 32, 4), np.uint8)
        big[3:29, 8:24] = (5, 4, 7, 255)                                         # outline
        big[4:28, 9:23] = (200, 40, 40, 255)                                     # a red bottle
        big[4:10, 13:19] = (230, 220, 200, 255)                                  # its cork
        src = os.path.join(self.tmp, "big.png")
        Image.fromarray(big).save(src)
        calls = []

        def fake_fit(prompt, seed, tag, fig, canvas, **kw):
            calls.append(canvas)
            return {"path": src, "seconds": 0}
        saved = lane_props.fit_sprite
        lane_props.fit_sprite = fake_fit
        try:
            man = fcore.Manifest(s, "icons")
            lane_props.run_icons([{"name": "potion", "prompt": "a red potion"}], "icons", man, s.conf)
        finally:
            lane_props.fit_sprite = saved
        self.assertEqual(calls, [32])                                            # one render, the largest size
        d = os.path.join(self.tmp, "assets", "art", "ui", "icons")
        small = np.array(Image.open(os.path.join(d, "ui_icon_potion_16.png")))
        self.assertEqual(small.shape, (16, 16, 4))
        edge = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]])
        self.assertTrue((edge[:, 3] == 0).all())                                 # 1 px margin all round
        cols = {tuple(int(v) for v in c) for c in small[small[..., 3] == 255][:, :3]}
        self.assertEqual(cols, {(5, 4, 7), (200, 40, 40), (230, 220, 200)})      # the big icon's own colours
        rows = {r["file"].rsplit("/", 1)[-1]: r for r in man.data["assets"]}
        self.assertEqual(rows["ui_icon_potion_16.png"]["derived_from"], "ui_icon_potion_32.png")
        s.conf["comfyui"].update(url="http://127.0.0.1:1", root=None)              # nothing answers, nothing starts
        lane_props.run_icons([{"name": "potion", "prompt": "a red potion"}], "icons", man, s.conf)   # up to date: no start
        flat = np.zeros((32, 32, 4), np.uint8)
        flat[0, 0] = (1, 2, 3, 255)                                              # nothing inside an outline
        with self.assertRaises(fcore.JobError):
            lane_props.derive_small(Image.fromarray(flat), 16)

    def test_ground_slabs_and_shadows(self):
        # a light-grey slab under the feet (split by them) goes, with the outline ring that framed it; white feet with
        # leg above them stay; a light subject is never stripped; enemies get a dark code-drawn shadow under the feet
        s = self.bind()
        import qa

        def figure(foot_colour):
            a = np.zeros((40, 40, 4), np.uint8)
            a[4:30, 12:28] = (90, 50, 30, 255)                                   # body
            a[30:36, 13:18] = a[30:36, 22:27] = foot_colour + (255,)             # two legs / feet
            return a
        a = figure((40, 30, 20))
        slab = np.zeros((40, 40), bool)
        slab[33:37, 6:34] = True
        slab[30:36, 13:18] = slab[30:36, 22:27] = False                          # the feet cut it into pieces
        a[slab] = (211, 215, 213, 255)
        import engine
        ring = engine.dilate(slab, 8) & (a[..., 3] == 0)
        a[ring] = (5, 4, 7, 255)                                                 # the outline around the slab
        out, k, note = qa.deslab(Image.fromarray(a))
        o = np.array(out)
        self.assertTrue(k > 0 and note.startswith("ground slab removed"))
        self.assertEqual(int(o[slab, 3].max()), 0)                               # slab gone
        self.assertEqual(int(o[ring & ~engine.dilate((o[..., 3] == 255) & ~ring, 4), 3].max()), 0)   # no ghost ring
        self.assertTrue((o[4:30, 12:28, 3] == 255).all() and (o[30:36, 13:18, 3] == 255).all())  # body and feet stay
        white = figure((220, 222, 224))                                          # white feet, the leg above them
        out, k, _ = qa.deslab(Image.fromarray(white))
        self.assertEqual(k, 0)
        snow = np.zeros((40, 40, 4), np.uint8)
        snow[28:38, 2:38] = (225, 228, 230, 255)                                 # a snow bank: more snow above
        self.assertEqual(qa.deslab(Image.fromarray(snow))[1], 0)
        bar = np.zeros((40, 40, 4), np.uint8)
        bar[30:34, 18:22] = (90, 50, 30, 255)                                    # a small dark figure on ...
        bar[34:36, 2:38] = (225, 228, 230, 255)                                  # ... a light bar much bigger than it
        out, k, note = qa.deslab(Image.fromarray(bar))
        self.assertEqual(k, 0)
        self.assertIn("light subject", note)                                     # the size guard, not a strip
        sh, dx = qa.contact_shadow(Image.fromarray(o))
        feet = np.nonzero((o[31:36, :, 3] == 255).any(0))[0]                     # the lowest band: the feet
        self.assertEqual(sh.size[0], int((feet.max() - feet.min() + 1) * 0.8))   # 80 % of the feet span
        self.assertEqual(dx, round((feet.min() + feet.max()) / 2 - 19.5))
        px = np.array(sh)
        self.assertTrue((px[..., :3][px[..., 3] > 0] == 12).all())               # dark, never light grey (#26)
        self.assertEqual(qa.pocket_report(Image.fromarray(o)), [])
        box = np.zeros((20, 20, 4), np.uint8)
        box[2:18, 2:18] = (60, 40, 30, 255)
        box[6:12, 6:12] = (250, 250, 250, 255)                                   # a flat white pocket: flagged only
        self.assertEqual(qa.pocket_report(Image.fromarray(box)), [(6, 6, 6, 6, 36)])
        # the enemies lane: slab stripped, shadow PNG + a Shadow child behind the sprite, swaps get theirs too
        import lane_enemies
        src = os.path.join(self.tmp, "foe.png")
        Image.fromarray(a).save(src)
        saved = lane_enemies.fit_sprite
        lane_enemies.fit_sprite = lambda *x, **k: {"path": src, "seconds": 0}
        try:
            man = fcore.Manifest(s, "foes")
            lane_enemies.run([{"name": "brute", "prompt": "a brute"},
                              {"name": "ice_brute", "recolor_of": "brute", "hue": 150}], "foes", man, s.conf)
        finally:
            lane_enemies.fit_sprite = saved
        d = os.path.join(self.tmp, "assets", "art", "battle", "enemies")
        self.assertEqual(int(np.array(Image.open(os.path.join(d, "spr_enemy_brute.png")))[slab, 3].max()), 0)
        for n in ("brute", "ice_brute"):
            self.assertTrue(os.path.exists(os.path.join(d, f"spr_enemy_{n}_shadow.png")))
            scn = read(os.path.join(d, f"enemy_{n}.tscn"))
            self.assertIn("[gd_scene load_steps=3 format=3]", scn)
            self.assertIn("show_behind_parent = true", scn)
        rows = [r for r in man.data["assets"] if r["file"].endswith("spr_enemy_brute.png")]
        self.assertTrue(any("ground slab removed" in q for q in rows[0]["qa"]))

    def test_npc_variants(self):
        # NPCs: spec errors before any render, the code-drawn idle in every direction, and palette variants that are
        # whole characters of their own, recoloured with one map so every frame matches
        s = self.bind()
        import lane_character
        import lane_npcs
        with self.assertRaises(fcore.ToolError):
            lane_npcs.check([{"name": "baker", "variants": [{"name": "baker"}]}])           # clashes with an NPC
        with self.assertRaises(fcore.ToolError):
            lane_npcs.check([{"name": "baker", "variants": [{"name": "b2"}]}])              # a swap that changes nothing
        with self.assertRaises(fcore.ToolError):
            lane_npcs.check([{"name": "baker", "idle": "wiggle"}])
        lane_npcs.check([{"name": "baker", "variants": [{"name": "baker_red", "hue": 130}]}])
        self.assertEqual(lane_npcs.npc_conf(s.conf, {})["design"]["character"]["procedural_idle"], ["s", "e", "n", "w"])
        self.assertNotEqual(lane_npcs.npc_conf(s.conf, {"idle": "clip"})["design"]["character"]["procedural_idle"],
                            ["s", "e", "n", "w"])
        man = fcore.Manifest(s, "npcs")
        base = lane_character.Character({"name": "baker", "actions": ["idle", "walk"]}, s.project, man, s.conf)

        def frame(shift):
            im = Image.new("RGBA", (24, 40), (0, 0, 0, 0))
            for y in range(4 + shift, 38):
                for x in range(6, 18):
                    im.putpixel((x, y), (200, 40, 40, 255) if y < 20 else (5, 4, 7, 255))   # red coat, dark legs
            return im
        rot = {}
        for d in "senw":
            rot[d] = os.path.join(base.work, f"rot_{d}.png")
            frame(0).save(rot[d])
        clips = {(a, d): ([frame(0), frame(1)], []) for a in ("idle", "walk") for d in "senw"}
        pal = __import__("engine").load_hex(s.conf["fixed"]["palette"])
        v = lane_npcs.variant(base, clips, rot, {"name": "baker_teal", "hue": 150}, s.project, man, s.conf, pal)
        fr = os.path.join(s.project, "assets", "art", "characters", "baker_teal", "frames")
        self.assertEqual(len([f for f in os.listdir(fr) if f.startswith("spr_baker_teal_")]), 16)   # 2 x 4 x 2
        a = Image.open(os.path.join(fr, "spr_baker_teal_walk_e_00.png")).convert("RGBA")
        b = Image.open(os.path.join(fr, "spr_baker_teal_idle_n_01.png")).convert("RGBA")
        coat_a = a.getpixel((a.width // 2, a.height - 30))
        self.assertNotEqual(coat_a[:3], (200, 40, 40))                                    # the coat turned
        self.assertEqual(coat_a, b.getpixel((b.width // 2, b.height - 29)))               # one map, every frame
        self.assertEqual(a.getpixel((a.width // 2, a.height - 5))[:3], (5, 4, 7))         # dark legs stay
        self.assertIn("baker_teal_frames.tres", " ".join(os.listdir(os.path.dirname(fr))))
        self.assertTrue(any("palette variant of baker" in x for x in man.data["assumptions"]))
        import recolor
        skin, coat = np.array([[248, 194, 172]], np.uint8), np.array([[200, 40, 40]], np.uint8)
        both = np.concatenate([skin, coat])
        kept = recolor.plan(both, np.ones(2), pal, hue=150, keep_skin=True)
        self.assertNotIn((248, 194, 172), kept)                                          # a face stays a face
        self.assertIn((200, 40, 40), kept)                                               # the coat still turns
        self.assertIn((248, 194, 172), recolor.plan(both, np.ones(2), pal, hue=150))      # off by default elsewhere
        twins = np.array([[110, 70, 40], [112, 71, 41], [109, 70, 42]], np.uint8)          # one cap, three frames
        self.assertEqual(len(set(recolor.plan(twins, np.array([30, 20, 10]), pal, hue=150).values())), 1)

    def _link_dir(self, target, link):
        """A directory link: a junction on Windows (no admin needed), a symlink elsewhere; None if neither works."""
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(target, link)
            else:
                os.symlink(target, link, target_is_directory=True)
            return link
        except (OSError, AttributeError, ImportError):
            return None

    def test_no_writes_or_deletes_through_links(self):
        # a link under assets/ pointing out of the game: drop_dir refuses it, a write through it is refused, and a
        # link inside a folder being cleared is removed as a link with its target untouched (Kimi audit 2, #1 #2)
        s = self.bind()
        outside = tempfile.mkdtemp(prefix="dotwork_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        with open(os.path.join(outside, "keep.txt"), "w") as f:
            f.write("mine")
        art = os.path.join(self.tmp, "assets", "art", "fx", "status")
        os.makedirs(art)
        if not self._link_dir(outside, os.path.join(art, "poison")):
            self.skipTest("cannot create a directory link here")
        man = fcore.Manifest(s, "links")
        with self.assertRaises(fcore.ToolError):
            man.drop_dir(os.path.join(art, "poison"))
        with self.assertRaises(fcore.ToolError):
            fcore.save_clean(Image.new("RGBA", (2, 2)), os.path.join(art, "poison", "evil.png"))
        with self.assertRaises(fcore.ToolError):
            fcore.write_text(os.path.join(art, "poison", "evil.txt"), "x")
        self.assertEqual(os.listdir(outside), ["keep.txt"])
        man.drop_dir(art)                                                      # the link inside goes as a link
        self.assertFalse(os.path.exists(art))
        self.assertEqual(os.listdir(outside), ["keep.txt"])

    def test_shared_folders_keep_other_packs(self):
        # two packs share assets/art/battle/enemies: re-exporting B removes only B's own stale files (Kimi audit 2 #3)
        s = self.bind()
        import lane_enemies
        src = os.path.join(self.tmp, "foe.png")
        im = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        for y in range(4, 22):
            for x in range(6, 18):
                im.putpixel((x, y), (120, 60, 40, 255))
        im.save(src)
        saved = lane_enemies.fit_sprite
        lane_enemies.fit_sprite = lambda *x, **k: {"path": src, "seconds": 0}
        try:
            a = fcore.Manifest(s, "pack_a")
            lane_enemies.run([{"name": "hound", "prompt": "a hound"}], "pack_a", a, s.conf)
            b = fcore.Manifest(s, "pack_b")
            lane_enemies.run([{"name": "slime", "prompt": "a slime"}, {"name": "rat", "prompt": "a rat"}], "pack_b", b,
                             s.conf)
            lane_enemies.run([{"name": "slime", "prompt": "a slime"}], "pack_b", b, s.conf)   # rat removed from B
        finally:
            lane_enemies.fit_sprite = saved
        d = os.path.join(self.tmp, "assets", "art", "battle", "enemies")
        files = os.listdir(d)
        self.assertIn("spr_enemy_hound.png", files)                            # pack A's enemy survives B
        self.assertIn("spr_enemy_slime.png", files)
        self.assertNotIn("spr_enemy_rat.png", files)                           # B's own stale enemy goes
        self.assertFalse(any("rat" in r["file"] for r in b.data["assets"]))
        # the feet (content bottom) sit on the node origin, where the shadow is (Kimi audit 2 #6)
        scn = read(os.path.join(d, "enemy_hound.tscn"))
        self.assertIn(f"offset = Vector2(0, {round(24 / 2 - 22)})", scn)

    def test_kimi_audit2_fixes(self):
        s = self.bind()
        import godot
        import lane_portraits
        import lane_vehicles as v
        import qa
        # 5: a white region touching transparency is the figure's edge, not a trapped pocket
        a = np.zeros((20, 20, 4), np.uint8)
        a[2:18, 2:18] = (60, 40, 30, 255)
        a[6:12, 6:12] = (250, 250, 250, 255)                                   # enclosed: a pocket
        a[14:18, 2:8] = (250, 250, 250, 255)                                   # touches the outside: an edge
        m = qa._pockets(a)
        self.assertTrue(m[8, 8] and not m[15, 4])
        # 7, 8: rot_order is in the cache key, and a three-quarter order does not mirror
        sw = ["sw", "w", "nw", "n", "ne", "e", "se", "s"]
        order, mirror, extra = v.rotation_plan({"name": "x", "rot_order": sw})
        self.assertFalse(mirror)
        self.assertNotEqual(extra, v.rotation_plan({"name": "x", "rot_order": v.ROT8})[2])
        self.assertTrue(v.rotation_plan({"name": "x", "rot_order": v.ROT8})[1])
        # 9: Godot strings are escaped
        self.assertEqual(godot.q('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')
        tres = os.path.join(self.tmp, "t.tres")
        godot.tileset(tres, "res://a.png", 16, 1, [{"index": 0, "corners": (0, 0, 0, 0), "terrain": 0,
                                                     "custom": 'mud"\nx = 1'}], [('bad"name', (1, 2, 3))], custom="surface")
        text = read(tres)
        self.assertIn('terrain_set_0/terrain_0/name = "bad\\"name"', text)
        self.assertNotIn("\nx = 1", text)                                       # no injected line
        # 4: the Theme's font path is res:// + the path in the game, once
        os.makedirs(os.path.join(self.tmp, "assets", "art", "ui", "fonts"))
        with open(os.path.join(self.tmp, "assets", "art", "ui", "fonts", "dialogue.fnt"), "w") as f:
            f.write("info face=x\n")
        spec = os.path.join(self.tmp, "w.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "w", "widgets": [{"name": "hud", "font": "assets/art/ui/fonts/dialogue.fnt"}]}, f)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 0, out)
        th = read(os.path.join(self.tmp, "assets", "art", "ui", "widgets", "hud", "theme_hud.tres"))
        self.assertIn('path="res://assets/art/ui/fonts/dialogue.fnt"', th)
        # 12: degenerate transition sizes stop the run
        with open(spec, "w", encoding="utf-8") as f:
            json.dump({"name": "w", "transitions": [{"name": "x", "kind": "wipe_right", "size": [1, 180]}]}, f)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 2, out)
        # 10: Lamp.png and lamp.png are one file on Windows
        if os.name == "nt":
            for dname in ("a", "b"):
                os.makedirs(os.path.join(self.tmp, "raw", dname))
            Image.new("RGBA", (8, 8), (9, 9, 9, 255)).save(os.path.join(self.tmp, "raw", "a", "Lamp.png"))
            Image.new("RGBA", (8, 8), (9, 9, 9, 255)).save(os.path.join(self.tmp, "raw", "b", "lamp.png"))
            code, out = self.run_dotwork("clean", "--source", "raw/a/*.png", "raw/b/*.png", "--out", "assets/x",
                                         "--cell", "1", "--project", self.tmp)
            self.assertEqual(code, 2, out)
        # 11: a new object palette re-edits the expressions (the settle step snaps to it)
        base = os.path.join(self.tmp, "assets", "art", "portraits", "spr_p_portrait.png")
        os.makedirs(os.path.dirname(base))
        Image.new("RGBA", (16, 16), (200, 120, 90, 255)).save(base)
        calls = []

        def fake_edit(src, instr, seed, tag):
            calls.append(tag)
            return base, 0
        saved = lane_portraits.edit
        lane_portraits.edit = fake_edit
        try:
            man = fcore.Manifest(s, "p")
            lane_portraits.expressions({"name": "p", "expressions": ["happy"]}, man, s.conf)
            lane_portraits.expressions({"name": "p", "expressions": ["happy"]}, man, s.conf)   # cached
            pal2 = os.path.join(self.tmp, "p2.hex")
            with open(pal2, "w") as f:
                f.write("000000\nffffff\nc87850\n")
            s.conf["fixed"]["palette"] = pal2
            lane_portraits.expressions({"name": "p", "expressions": ["happy"]}, man, s.conf)   # new palette
        finally:
            lane_portraits.edit = saved
        self.assertEqual(len(calls), 2)

    def test_clip_matte_shadow_and_drift(self):
        s = self.bind()
        import lane_character
        import qa
        brown, boot, shadow, gold = (120, 70, 40), (60, 30, 20), (78, 80, 92), (230, 190, 40)   # Wan-like grey-blue

        def body(h=48, w=32):
            a = np.zeros((h, w, 4), np.uint8)
            a[4:38, 8:24] = brown + (255,)                                         # body
            a[38:44, 9:14] = a[38:44, 18:23] = boot + (255,)                      # boots
            return a
        # #22: flat generator white touching the outside is matte; a shaded white sleeve is clothing
        raw = body()
        raw[20:30, 24:30] = (254, 254, 254, 255)                                  # matte between arm and body
        raw[10:16, 2:8] = (250, 250, 251, 255)                                    # sleeve: three shades
        raw[12, 2:8] = (244, 244, 246, 255)
        raw[14, 2:8] = (238, 238, 240, 255)
        locked = raw.copy()
        locked[20:30, 24:30] = locked[10:16, 2:8] = (248, 248, 248, 255)          # the lock maps both to one white
        ref = Image.fromarray(body())
        (out,), n, note = qa.dematte([Image.fromarray(locked)], ref, raw=[Image.fromarray(raw)])
        o = np.array(out)
        self.assertEqual(int(o[20:30, 24:30, 3].max()), 0)                        # matte gone
        self.assertTrue((o[10:16, 2:8, 3] == 255).all())                          # sleeve kept
        white = body()
        white[6:30, 9:23] = (250, 250, 250, 255)                                  # a white-clothed design
        self.assertIn("white", qa.dematte([Image.fromarray(locked)], Image.fromarray(white), raw=[Image.fromarray(raw)])[2])
        # #25: one shadow decision for the whole clip; trousers in the shadow's colour stay
        f1 = body()
        f1[43:47, 2:30] = shadow + (255,)                                         # wide and flat: the per-frame pass sees it
        f1[30:38, 8:24] = shadow + (255,)                                         # trousers, same blue-grey, above the feet
        f2 = body()
        f2[43:47, 4:9] = f2[43:47, 23:28] = shadow + (255,)                       # split by the feet: too narrow alone
        f2[30:38, 8:24] = shadow + (255,)
        self.assertEqual(qa.deshadow_blob(Image.fromarray(f2))[1], 0)             # the blink, before this fix
        frames, removed = qa.clip_deshadow([Image.fromarray(f1), Image.fromarray(f2)])
        for f in frames:
            a = np.array(f)
            self.assertEqual(int(a[44:47, :, 3].max()), 0)                        # no shadow under the feet in any frame
            self.assertTrue((a[30:38, 8:24, 3] == 255).all())                     # trousers kept
            self.assertTrue((a[38:43, 9:14, 3] == 255).all())                     # boots kept
        # #24: colours another direction has and this one lacks, over 4 % of the figure, two frames running
        e_ref = body()
        s_ref = body()
        s_ref[2:30, 26:29] = gold + (255,)                                        # the front view shows a staff
        refs = {"e": Image.fromarray(e_ref), "w": Image.fromarray(e_ref[:, ::-1].copy()), "s": Image.fromarray(s_ref),
                "n": Image.fromarray(body())}
        clip = [body() for _ in range(6)]
        for f in clip[3:]:
            f[2:30, 26:29] = gold + (255,)
        self.assertEqual(qa.drifted([Image.fromarray(f) for f in clip], "e", refs), 3)
        self.assertIsNone(qa.drifted([Image.fromarray(body()) for _ in range(6)], "e", refs))
        # the lane: drift from frame 4 trims to 3 frames played back and forth; from frame 2 it stops the character
        man = fcore.Manifest(s, "drift")
        rot = {}
        c = lane_character.Character({"name": "mage", "actions": ["idle"]}, s.project, man, s.conf)
        for d, im in refs.items():
            rot[d] = os.path.join(c.work, f"rot_{d}.png")
            im.save(rot[d])

        def clip_dir(frames):
            d = os.path.join(c.work, "clips", "cast_e")
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            for i, f in enumerate(frames):
                Image.fromarray(f).save(os.path.join(d, f"f_00001_{i:02d}.png"))
            with open(os.path.join(d, "meta.json"), "w") as fh:
                json.dump({"seed": 4242, "palette_lock": "dotwork"}, fh)
        clip_dir(clip)
        fr, notes = c.frames("cast", "e", rot)
        self.assertEqual(len(fr), 3 + 1)                                          # frames 0-2, then 1 back
        self.assertTrue(any("trimmed" in n for n in notes))
        early = [body() for _ in range(6)]
        for f in early[1:]:
            f[2:30, 26:29] = gold + (255,)
        clip_dir(early)
        with self.assertRaises(fcore.JobError):
            c.frames("cast", "e", rot)
        c.e["clip_fix"] = {"cast_e": {"allow_drift": True}}
        self.assertEqual(len(c.frames("cast", "e", rot)[0]), 6)                   # the user's call: kept whole

    def test_state_props_and_ambient_loops(self):
        s = self.bind()
        import lane_animprops as ap
        d = self.tmp
        # #27: a state keeps the closed render outside the moving part, so the chest opens instead of morphing
        closed = np.zeros((32, 32, 4), np.uint8)
        closed[12:30, 6:26] = (120, 70, 40, 255)                                  # body
        closed[12:18, 6:26] = (150, 90, 50, 255)                                  # lid
        opened = closed.copy()
        opened[4:18, 6:26] = (90, 50, 30, 255)                                    # the lid swings up, past the old top
        opened[24:30, 6:26] = (200, 10, 10, 255)                                  # the edit also redrew the base: dropped
        Image.fromarray(closed).save(os.path.join(d, "c.png"))
        Image.fromarray(opened).save(os.path.join(d, "o.png"))
        dropped = ap.keep_moving(os.path.join(d, "c.png"), os.path.join(d, "o.png"), "chest", os.path.join(d, "k.png"))
        k = np.array(Image.open(os.path.join(d, "k.png")))
        self.assertTrue((k[4:12, 6:26] == opened[4:12, 6:26]).all())             # the raised lid is kept
        self.assertTrue((k[21:30] == closed[21:30]).all())                        # the body is the closed render's
        self.assertAlmostEqual(dropped, 120 / 400)                                # the redrawn base: reported
        door = np.zeros((64, 32, 4), np.uint8)
        door[2:64, 2:30] = (90, 60, 40, 255)
        m = ap.moving_part(Image.fromarray(door), "door")
        self.assertFalse(m[2:11, :].any() or m[:, 2:6].any() or m[:, 26:30].any())   # lintel and jambs stay
        self.assertTrue(m[30, 16])                                                # the panel moves
        # ambient loops: each one moves and loops on the same canvas (smoke grows it on top)
        src = os.path.join(d, "torch.png")
        t = np.zeros((40, 24, 4), np.uint8)
        t[20:38, 10:14] = (90, 60, 40, 255)                                       # a pole
        t[8:20, 7:17] = (250, 170, 40, 255)                                       # fire
        t[12:18, 9:15] = (255, 230, 120, 255)
        Image.fromarray(t).save(src)
        for kind, fn in ap.AMBIENT_FN.items():
            frames = fn(src, n=6)
            self.assertEqual(len(frames), 6, kind)
            self.assertGreater(len({f.tobytes() for f in frames}), 1, kind)          # it moves
            self.assertEqual(len({f.size for f in frames}), 1, kind)
        self.assertEqual(ap.smoke_frames(src, n=4)[0].size, (24, 40 + 28))
        f0 = np.array(ap.flag_frames(src, n=6)[1])
        self.assertTrue((f0[:, 10] == t[:, 10]).all())                            # the pole side stays pinned
        fire_cols = {tuple(c) for c in np.array(ap.flame_frames(src)[2])[..., :3].reshape(-1, 3)}
        self.assertTrue(fire_cols <= {tuple(c) for c in t[..., :3].reshape(-1, 3)})   # flicker stays in the colours
        with self.assertRaises(fcore.JobError):
            plain = os.path.join(d, "plain.png")
            Image.fromarray(np.dstack([np.full((16, 16, 3), 60, np.uint8), np.full((16, 16), 255, np.uint8)])).save(plain)
            ap.flame_frames(plain)                                                # no fire colours: say so
        spec = os.path.join(d, "a.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"name": "a", "animprops": [{"name": "x", "kind": "flamme", "prompt": "a torch"}]}, fh)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 2, out)                                            # a typo'd kind stops the run

    def test_eight_directions_and_variants(self):
        s = self.bind()
        import lane_character as lc
        with self.assertRaises(fcore.ToolError):
            lc.Character({"name": "x", "directions": ["s", "up"]}, s.project, fcore.Manifest(s, "x"), s.conf)

        def sprite(colour, mark=None):
            im = np.zeros((40, 24, 4), np.uint8)
            im[4:38, 6:18] = colour + (255,)
            if mark:
                im[6:10, 14:18] = mark + (255,)                                     # a detail on one side: shows a mirror
            return Image.fromarray(im)
        man = fcore.Manifest(s, "eight")
        c = lc.Character({"name": "scout", "actions": ["idle", "walk"], "directions": list(lc.DIRS8)}, s.project, man,
                         s.conf)
        self.assertTrue(c.eight)
        self.assertTrue(set(lc.VIEW.values()) <= set(lc.VIEWS))                    # the node refuses anything else
        self.assertEqual(set(lc.VIEW), set(lc.DIRS8))
        rot = {}
        os.makedirs(os.path.join(c.work, "rot8"))
        for d in lc.ROT_ORDER8:
            rot[d] = os.path.join(c.work, "rot8", f"{d}.png")
            sprite((120, 70, 40), (230, 200, 60) if d in ("se", "e", "ne") else None).save(rot[d])
        sprite((120, 70, 40)).save(os.path.join(c.work, "south.png"))
        self.assertEqual(c.rotate(os.path.join(c.work, "south.png")), rot)      # the 8-way ring, from rot8/
        rendered = []

        def fake_clip(action, direction, spr, seed=4242):
            rendered.append(f"{action}_{direction}")
            d = os.path.join(c.work, "clips", f"{action}_{direction}")
            os.makedirs(d, exist_ok=True)
            for i in range(4):
                Image.open(spr).save(os.path.join(d, f"f_00001_{i:02d}.png"))
            return d
        c.clip = fake_clip
        clips, rot2 = c.build()
        # symmetric: the west-facing views are mirrored, back idles (n, ne, nw) are the code bob
        self.assertEqual(sorted(rendered), sorted(["idle_s", "idle_se", "idle_e",
                                                   "walk_s", "walk_se", "walk_e", "walk_ne", "walk_n"]))
        self.assertEqual(len(clips), 16)
        sw0 = np.array(clips[("walk", "sw")][0][0])
        se0 = np.array(clips[("walk", "se")][0][0])
        self.assertTrue(np.array_equal(sw0, se0[:, ::-1]))                        # sw is se mirrored
        self.assertIn("procedural", " ".join(clips[("idle", "nw")][1]))
        # variants: a palette swap (no render) and an outfit (the south sprite edited once, a full character from it)
        edits = []

        def fake_edit(self_, path, instr):
            edits.append(instr)
            im = Image.open(path).convert("RGBA")
            im.putpixel((10, 20), (250, 250, 250, 255))                            # the "winter cloak"
            im.save(path)
        built = {}
        real_build = lc.Character.build

        def fake_build(self_):
            built[self_.name] = dict(self_.e)
            if self_.name == "scout":
                return clips, rot2
            return {("walk", "s"): ([sprite((90, 90, 120))], [])}, {"s": rot2["s"]}
        saved = lc.Character.edit, lc.Character.build
        lc.Character.edit, lc.Character.build = fake_edit, fake_build
        try:
            c.e["variants"] = [{"name": "scout_crimson", "hue": 150},
                               {"name": "scout_winter", "edit": "a white fur cloak", "actions": ["walk"]}]
            c.run()
        finally:
            lc.Character.edit, lc.Character.build = saved
        art = os.path.join(s.project, "assets", "art", "characters")
        self.assertTrue(os.path.exists(os.path.join(art, "scout_crimson", "frames", "spr_scout_crimson_walk_sw_00.png")))
        self.assertEqual(edits, ["a white fur cloak"])
        w = built["scout_winter"]
        self.assertTrue(w["source"].endswith("outfits/scout_winter_south.png"))
        self.assertEqual(w["actions"], ["walk"])                                  # a per-variant override
        self.assertNotIn("variants", w)                                           # a variant has none of its own
        src = os.path.join(s.project, *w["source"].split("/"))
        self.assertEqual(Image.open(src).getpixel((10, 20)), (250, 250, 250, 255))   # the edited south sprite
        self.assertTrue(any("outfit variant of scout" in a for a in man.data["assumptions"]))
        # which way a view faces: the face patch's side of the head; a bow's tan tip is not a face. A cached rotation
        # whose east view faces left is swapped once, the clips / poses made from it move aside, rot_swap undoes it
        import qa

        def head(face_x=None):
            im = np.zeros((40, 24, 4), np.uint8)
            im[4:38, 6:18] = (40, 110, 50, 255)                                     # hood and body
            for k in range(12):
                im[2 + k, 1 + k // 3] = (162, 138, 99, 255)                          # a bow, measured wood colour
            if face_x is not None:
                im[8:13, face_x:face_x + 3] = (250, 210, 180, 255)
            return Image.fromarray(im)
        self.assertEqual(qa.face_side(head(14))[0], "right")
        self.assertEqual(qa.face_side(head(7))[0], "left")
        self.assertIsNone(qa.face_side(head())[0])                                 # a back view: no verdict
        with self.assertRaises(fcore.ToolError):                                    # 4 directions have one pair
            lc.Character({"name": "y", "rot_swap": ["ne"]}, s.project, fcore.Manifest(s, "y"), s.conf)
        man = fcore.Manifest(s, "facing")
        r = lc.Character({"name": "ranger", "actions": ["walk"], "directions": ["s", "e", "n", "w"]}, s.project, man,
                         s.conf)
        os.makedirs(os.path.join(r.work, "rot"))
        files = {d: os.path.join(r.work, "rot", f"{d}.png") for d in lc.ROT_ORDER}
        for d, im in (("s", head(10)), ("n", head()), ("e", head(7)), ("w", head(14))):
            im.save(files[d])
        for p in ("clips/walk_e/f_00001_00.png", "clips/walk_s/f_00001_00.png", "poses/ko_w.png"):
            os.makedirs(os.path.dirname(os.path.join(r.work, p)), exist_ok=True)
            head(10).save(os.path.join(r.work, p))
        self.assertEqual(r.rotate(files["s"]), files)
        self.assertEqual(qa.face_side(Image.open(files["e"]))[0], "right")         # swapped
        old = os.path.join(r.work, "_old_facing", "0")
        self.assertEqual(sorted(os.listdir(old)), ["ko_w.png", "walk_e"])          # walk_s stays
        self.assertTrue(os.path.isdir(os.path.join(r.work, "clips", "walk_s")))
        self.assertEqual(r.orient(files), [])                                       # judged once
        r.rot_swap = ["e"]
        self.assertEqual(r.orient(files), ["e"])                                    # by hand: back the other way
        self.assertEqual(qa.face_side(Image.open(files["e"]))[0], "left")
        n = lc.Character({"name": "knight", "directions": ["s", "e", "n", "w"]}, s.project, man, s.conf)
        os.makedirs(os.path.join(n.work, "rot"))
        for d in lc.ROT_ORDER:
            head().save(os.path.join(n.work, "rot", f"{d}.png"))                    # a helmet: no face anywhere
        n.rotate(os.path.join(n.work, "rot", "s.png"))
        self.assertTrue(any("knight: could not tell which way the e views" in a for a in man.data["assumptions"]))

    def test_prompts_take_the_games_setting(self):
        # no built-in template assumes a setting; the spec's or config's design fills style / genre / setting, and a new
        # setting re-renders (cache keys and the character design stamp see the filled-in prompt)
        s = self.bind()
        import glob as globmod
        import re as remod
        import lane_character
        import lane_enemies
        import lane_props
        for f in globmod.glob(os.path.join(DOTWORK, "*.py")):
            src = read(f)
            for m in remod.finditer(r'^([A-Z_]*(?:TPL|PROMPT)) = [({].*?[)}]\n', src, remod.M | remod.S):
                self.assertNotIn("steampunk", m.group(0).lower(), f"{os.path.basename(f)} {m.group(1)}")
        self.assertEqual(s.conf["design"]["setting"], "")                          # none assumed by default
        plain = fcore.prompt(lane_props.PROP_TPL, s.conf, s="a barrel")
        self.assertNotIn(", ,", plain)
        self.assertTrue(plain.endswith("crisp dark outline") and "RPG game asset" in plain)
        farm = dict(s.conf, design=dict(s.conf["design"], setting="cozy farm village", genre="farming sim"))
        self.assertIn("image 1, cozy farm village, crisp dark outline", fcore.prompt(lane_props.PROP_TPL, farm, s="a barrel"))
        self.assertIn("farming sim game asset", fcore.prompt(lane_props.PROP_TPL, farm, s="a barrel"))
        # a new setting is a new design for a character: its renders are retired, not reused
        man = fcore.Manifest(s, "set")
        c = lane_character.Character({"name": "guard", "prompt": "a guard"}, s.project, man, s.conf)
        south = os.path.join(c.work, "south.png")
        fcore.save_clean(Image.new("RGBA", (4, 4)), south)
        with contextlib.redirect_stdout(io.StringIO()):
            lane_character.Character({"name": "guard", "prompt": "a guard"}, s.project, man, farm)
        self.assertFalse(os.path.exists(south))
        # the enemies' cache key reads the filled-in prompt
        self.assertNotEqual(fcore.prompt(lane_enemies.TPL, s.conf, s="a hound"), fcore.prompt(lane_enemies.TPL, farm, s="a hound"))
        # the sample specs that render keep their steampunk look explicitly
        for f in ("battle.json", "town.json", "props_icons.json", "party_member.json"):
            with open(os.path.join(DOTWORK, "examples", f), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["design"]["setting"], "steampunk", f)

    def test_talking_portraits(self):
        # talking adds talk + blink; their edits stay inside the mouth / eye band, so the loop flickers nothing else;
        # the SpriteFrames hold idle, an uneven talk flap and a one-shot blink, with a scene and a sheet + JSON
        s = self.bind()
        import lane_portraits as lp
        self.assertEqual(set(lp.wanted({"name": "a", "talking": True})), {"talk", "blink"})
        self.assertIn("happy", lp.wanted({"name": "a", "talking": True, "expressions": ["happy"]}))
        base = Image.new("RGBA", (40, 50), (0, 0, 0, 0))
        for y in range(0, 50):
            for x in range(4, 36):
                base.putpixel((x, y), (180, 120, 90, 255))
        edit = base.copy()
        for x in range(12, 28):
            edit.putpixel((x, 2), (10, 10, 10, 255))                                  # hair churn at the top
            edit.putpixel((x, 33), (60, 20, 20, 255))                                 # the open mouth (0.66)
            edit.putpixel((x, 18), (40, 40, 40, 255))                                 # a closed eye (0.36)
        talk, _ = lp.keep_face(base, edit, lp.REGION_ROWS["talk"])
        self.assertEqual(talk.getpixel((20, 33)), (60, 20, 20, 255))                  # mouth kept
        self.assertEqual(talk.getpixel((20, 18)), base.getpixel((20, 18)))            # eyes untouched
        self.assertEqual(talk.getpixel((20, 2)), base.getpixel((20, 2)))              # no hair churn
        blink, _ = lp.keep_face(base, edit, lp.REGION_ROWS["blink"])
        self.assertEqual(blink.getpixel((20, 18)), (40, 40, 40, 255))
        self.assertEqual(blink.getpixel((20, 33)), base.getpixel((20, 33)))
        art = os.path.join(self.tmp, "assets", "art", "portraits")
        os.makedirs(art)
        for suffix, im in (("", base), ("_talk", talk), ("_blink", blink)):
            im.save(os.path.join(art, f"spr_mage_portrait{suffix}.png"))
        man = fcore.Manifest(s, "talk")
        lp.talking("mage", man, s.conf)
        tres = read(os.path.join(art, "portrait_mage_frames.tres"))
        self.assertEqual(tres.count("spr_mage_portrait_talk.png"), lp.TALK.count("talk"))   # one entry per frame use
        self.assertIn('"name": &"talk"', tres)
        self.assertIn('autoplay = "idle"', read(os.path.join(art, "portrait_mage.tscn")))
        meta = json.loads(read(os.path.join(art, "portrait_mage_talk_sheet.json")))
        self.assertEqual(len(meta["talk"]), len(lp.TALK))
        with Image.open(os.path.join(art, "portrait_mage_talk_sheet.png")) as sh:
            self.assertEqual(sh.size, (40 * (len(lp.TALK) + 3), 50))

    def test_platform_and_iso_tilesets(self):
        s = self.bind()
        import lane_iso as li
        import lane_platforms as lp
        rng = np.random.default_rng(4)

        def tex(rgb, N):
            t = np.clip(np.array(rgb) + rng.integers(-15, 16, (N, N, 3)), 0, 255).astype(np.uint8)
            return t
        T = 32
        fill, surf = tex((110, 75, 45), T), tex((70, 140, 60), T)
        at, tiles = lp.atlas(fill, surf, T, 0.35, 7)
        self.assertEqual(len(tiles), 19)                                          # 16 side masks + 3 one-way pieces
        self.assertTrue((tiles[0][..., 3] == 255).all())                          # mask 0: fully surrounded, solid fill
        self.assertTrue(np.array_equal(tiles[0][..., :3], fill))
        top = tiles[1]                                                            # only the top exposed: the grass lip
        self.assertTrue((top[2:6, :, :3] != fill[2:6]).any(axis=-1).mean() > 0.8)
        self.assertTrue((top[T - 1, :, :3] == fill[T - 1]).all())                 # bottom untouched (not exposed)
        cap = tiles[17]                                                           # one-way middle: transparent below
        self.assertEqual(int(cap[T - 1, :, 3].max()), 0)
        self.assertEqual(lp.mask_at(["#.", "##"], 0, 1), 4 | 8)                   # neighbours: top and right are platform
        self.assertEqual(lp.mask_at(["#.", "##"], 1, 1), 1 | 2 | 4)
        # the lip's wavy edge wraps: a tile's last column meets the next tile's first within a pixel
        wave = lp._noise(T, 7, max(1, T // 16))
        self.assertLessEqual(abs(int(wave[0]) - int(wave[-1])), 1)
        ts = os.path.join(self.tmp, "p.tres")
        lp.tileset(ts, "res://a.png", T, 8)
        text = read(ts)
        self.assertIn("terrain_set_0/mode = 2", text)                             # Match Sides
        self.assertIn("0:0/0/terrains_peering_bit/top_side = 0", text)            # mask 0 peers on every side
        self.assertIn("1:0/0/terrains_peering_bit/top_side = -1", text)           # mask 1: top exposed
        self.assertIn("one_way = true", text)
        self.assertIn("metadata/dotwork_sides", text)                             # verify paints and checks the sides
        # the background wraps, and the repainted seam band fades in: no new seam at either band edge
        raw = np.zeros((180, 320, 3), np.uint8)
        raw[..., 0] = np.linspace(0, 255, 320).astype(np.uint8)                   # red ramp: a hard step at the wrap
        raw[:20] = (100, 150, 220)                                                # a flat sky
        rep = np.full((180, 320, 3), 128, np.uint8)                               # a repaint unlike its surroundings,
        rep[:20] = (80, 125, 190)                                                 # its sky a shade darker
        renders = [os.path.join(self.tmp, "bg_raw.png"), os.path.join(self.tmp, "bg_rep.png")]
        Image.fromarray(raw).save(renders[0])
        Image.fromarray(rep).save(renders[1])
        saved = lp.lib.run, lp.lib.klein, lp.lib.put, lp.lib.finish, fcore.ensure_comfy
        lp.lib.run = lambda g, *a, **k: (renders.pop(0), {})
        lp.lib.klein = lambda *a, **k: {}
        lp.lib.put = lambda im, name: name
        lp.lib.finish = lambda arr, **k: arr
        fcore.ensure_comfy = lambda *a, **k: None
        try:
            bg = np.array(lp.background({"name": "m", "background": {"prompt": "hills"}}, s.conf, self.tmp, "m"))
        finally:
            lp.lib.run, lp.lib.klein, lp.lib.put, lp.lib.finish, fcore.ensure_comfy = saved
        rgb = bg[..., :3].astype(int)
        self.assertLessEqual(np.abs(rgb[:, 0] - rgb[:, -1]).max(), 2)             # the wrap
        self.assertLessEqual(np.abs(np.diff(rgb, axis=1)).max(), 8)               # every column step stays small
        self.assertLessEqual(np.abs(rgb[:20] - np.array((100, 150, 220))).max(), 1)   # the sky keeps its tone
        # iso: the projection is exact and seamless: two diamonds side by side continue one texture
        W = 32
        t = tex((90, 120, 70), W // 2)
        d = li.project(t, W)
        self.assertEqual(d.shape, (16, 32, 4))
        self.assertEqual(int(d[0, 0, 3]), 0)                                      # outside the diamond: transparent
        self.assertEqual(int(d[8, 16, 3]), 255)                                   # the centre: opaque
        sy, sx = 8, 16                                                            # the centre shows world point (N/2, N/2)
        self.assertTrue(np.array_equal(d[sy, sx, :3], t[int(sy + 0.5 - (sx + 0.5 - 16) / 2), int(sy + 0.5 + (sx + 0.5 - 16) / 2)]))
        b = li.block(t, t, W, 8)
        self.assertEqual(b.shape, (16 + 8, 32, 4))
        self.assertIn(tuple(li.OUTLINE), {tuple(int(v) for v in c) for c in b[b[..., 3] == 255][:, :3]})
        ts2 = os.path.join(self.tmp, "i.tres")
        li.tileset(ts2, "res://f.png", 3, "res://b.png", 1, W, 8)
        text = read(ts2)
        self.assertIn("tile_shape = 1", text)
        self.assertIn("texture_origin = Vector2i(0, 4)", text)
        self.assertIn('[gd_resource type="TileSet" load_steps=5 format=3]', text)
        spec = os.path.join(self.tmp, "iso.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump({"name": "iso", "iso": [{"name": "x", "tile": 30, "floors": [{"material": "dirt"}]}]}, fh)
        code, out = self.run_dotwork("pack", "--spec", spec, "--project", self.tmp, "--no-verify")
        self.assertEqual(code, 2, out)                                            # 30 is not a multiple of 4
        # every example spec loads without an unknown-key warning (platforms' "fill" warned as a typo: the lane read
        # it as e.get(key), and the checker learns keys from literal reads)
        import dotwork
        for f in sorted(os.listdir(os.path.join(DOTWORK, "examples"))):
            if f.endswith(".json"):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    dotwork.load_spec(os.path.join(DOTWORK, "examples", f))
                self.assertNotIn("is not read by Dotwork", err.getvalue(), f)

    def test_pose_skeleton_and_graph(self):
        s = self.bind()
        import lane_character
        import pose
        for a in pose.ACTIONS:
            for view in ("side", "front"):
                kp = pose.keypoints(a, 0.3, view)
                self.assertEqual(len(kp), 18, (a, view))
                self.assertTrue(all(-0.6 < x < 0.6 and -0.05 < y < 1.3 for x, y in kp), (a, view))
        # SK_ToCanvas puts a 72 px sprite (padding 8) at scale 7 on 640 px: the skeleton's feet land on the sprite's
        sprite = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        sprite.paste((200, 100, 60, 255), (24, 6, 48, 70))
        sc, ox, oy = pose.canvas_map(72, 72)
        self.assertEqual(sc, 640 // (72 + 16))
        fr = pose.frames("walk", "e", sprite, n=9)
        self.assertEqual((len(fr), fr[0].size), (9, (640, 640)))
        a = np.array(fr[0])
        ys = np.nonzero(a.any(-1).any(1))[0]
        feet = 70 * sc + oy
        self.assertLessEqual(abs(int(ys.max()) - feet), 2 * sc + 6)              # the ankles sit on the feet line
        self.assertTrue(np.array_equal(np.array(fr[0]), np.array(fr[-1])))       # the loop closes
        self.assertFalse(np.array_equal(np.array(fr[0]), np.array(fr[2])))       # and moves (t 0.5 is the other passing pose)
        back = np.array(pose.frames("idle", "n", sprite, n=3)[0])
        self.assertFalse((back == np.array(pose.COLOURS[0])).all(-1).any())     # no nose drawn from behind
        # the face is fitted to the sprite: a chibi face at 0.6 of the height, not the default's guess; the skeleton
        # centres on the head, not on a bbox a bow widens
        chibi = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        chibi.paste((40, 110, 50, 255), (26, 6, 46, 70))                          # body and hood, 64 px tall
        chibi.paste((250, 210, 180, 255), (30, 22, 42, 34))                       # the face: rows 22-33
        for k in range(30):
            chibi.putpixel((4 + k // 3, 10 + k), (162, 138, 99, 255))              # a bow out to the left
        f = pose.fit(chibi)
        self.assertAlmostEqual(f["face"], (69 - 27.5) / 64, delta=0.02)           # the face's middle row
        self.assertLess(f["neck"], f["face"])
        self.assertAlmostEqual(f["x"], (35.5 - (4 + 45) / 2) / 64, delta=0.01)   # head middle vs bbox middle
        self.assertEqual(set(pose.fit(sprite)), {"x"})                            # no face showing: defaults
        nose = np.array(pose.frames("walk", "s", chibi, n=3)[0])
        ny = np.nonzero((nose == np.array(pose.COLOURS[0])).all(-1))[0].mean()
        self.assertAlmostEqual((ny - oy) / sc, 27.5, delta=2)                      # the nose lands on the face
        # the animate graph becomes a pose-driven one
        g = {"4": {"class_type": "SK_ToCanvas", "inputs": {}},
             "9": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "i2v_high.gguf"}},
             "13": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "i2v_low.gguf"}},
             "19": {"class_type": "WanImageToVideo", "inputs": {"positive": ["17", 0], "negative": ["18", 0],
                                                                "vae": ["8", 0], "width": ["4", 2], "height": ["4", 3],
                                                                "length": ["6", 0], "batch_size": 1,
                                                                "start_image": ["4", 0]}}}
        out = pose.control_graph(g, ["a.png", "b.png", "c.png"], *pose.MODELS)
        self.assertEqual(out["9"]["inputs"]["unet_name"], pose.MODELS[0])
        self.assertEqual(out["13"]["inputs"]["unet_name"], pose.MODELS[1])
        node = out["19"]
        self.assertEqual(node["class_type"], "Wan22FunControlToVideo")
        self.assertEqual(node["inputs"]["ref_image"], ["4", 0])
        self.assertNotIn("start_image", node["inputs"])
        self.assertEqual(node["inputs"]["length"], 3)
        chain = node["inputs"]["control_video"]
        self.assertEqual(out[chain[0]]["class_type"], "ImageBatch")             # three frames, two batch nodes
        self.assertEqual(sum(1 for n in out.values() if n["class_type"] == "LoadImage"), 3)
        with self.assertRaises(fcore.ToolError):
            lane_character.Character({"name": "x", "actions": ["walk"], "skeleton": ["dance"]}, s.project,
                                     fcore.Manifest(s, "x"), s.conf)
        c = lane_character.Character({"name": "x", "actions": ["walk", "idle"], "skeleton": ["walk"]}, s.project,
                                     fcore.Manifest(s, "x"), s.conf)
        self.assertNotEqual(c.motion_key("walk"), lane_character.Character(
            {"name": "y", "actions": ["walk"]}, s.project, fcore.Manifest(s, "y"), s.conf).motion_key("walk"))

    def test_setup_lists_models_offline(self):
        nogame = os.path.join(self.tmp, "nogame")
        os.makedirs(nogame)
        saved = {k: os.environ.pop(k, None) for k in ("COMFYUI_ROOT", "COMFYUI_URL")}
        os.environ["COMFYUI_URL"] = "http://127.0.0.1:1"   # nothing answers there
        try:
            code, out = self.run_dotwork("setup", "--check", "--project", nogame)
        finally:
            os.environ.pop("COMFYUI_URL", None)
            os.environ.update({k: v for k, v in saved.items() if v is not None})
        self.assertEqual(code, 2)
        self.assertIn("NOT checked against ComfyUI", out)  # the download list shows without a server
        self.assertIn("flux-2-klein-4b.safetensors", out)
        self.assertIn("is not a game folder", out)
        self.assertNotIn("[ OK ] game project", out)
        self.assertEqual(os.listdir(nogame), [])           # setup --check creates nothing


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
