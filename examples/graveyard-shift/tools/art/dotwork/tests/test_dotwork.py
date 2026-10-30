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
        conf = dict(s.conf, style_refs=["assets_src/ref/hero.png"])
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
                    "| A-0001 | | | | | | | no | no | 2026-10-21 | |\n")
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
