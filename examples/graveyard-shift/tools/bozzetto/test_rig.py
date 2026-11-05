#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_rig.py
# Purpose : The exam for `bozzetto.py rig` (rig.py, rig_finish.py, rig/patch_unirig.py), offline.
#           Part 1 (standard library, any Python 3.8+):
#           - patch_unirig.py on a fake UniRig checkout: --check reports, patching, a second run changes nothing, a
#             checkout whose lines moved is refused
#           - the UniRig route with a stand-in checkout (its run.py and modules are small scripts that write the
#             files UniRig would): the five steps run in order with UniRig's arguments, the record, the asset log row
#             ("rig of A-0001", the UniRig and Articulation-XL2.0 credit, the licence texts), a re-run needs
#             --overwrite and updates the same row, a failed step and a failed rig check ship nothing
#           - the Tripo route against canned API answers (no network): the quote is checked against --max-credits and
#             the balance before anything is uploaded, a model Tripo cannot rig stops before a paid call, the paid
#             path uploads, rigs with Mixamo bones, retargets, downloads and scales back by 1/normalize_scale
#           Blender is replaced by a stand-in here.
#           Part 2 (when Blender or the bpy module is found): rig_finish.py on rigs built here in Blender: a biped
#           passes, gets Mixamo names on the right sides and three clips that move the mesh; a rig with everything on
#           one bone, one with vertices only on glTF's placeholder bone, and a four-legged one fail with exit 1.
# Usage   : python tools/bozzetto/test_rig.py
#           BOZZETTO_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import rig  # noqa: E402

rig.bind(bz)
PATCHER = HERE / "rig" / "patch_unirig.py"
LOG = """# Asset log

| ID | Type | Path | Source | Author | License | Attribution | AI | Edited | Date | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| A-0001 | model | `assets/models/npc_guard.glb` | Bozzetto | generated locally | mit | Built with DINOv3. | pre-generated | no | 2026-01-01 | |
"""
UNIRIG_ORIGINALS = {   # the lines patch_unirig.py looks for, in files shaped like UniRig's
    "src/model/unirig_skin.py": "import torch\nfrom flash_attn.modules.mha import MHA\n",
    "configs/model/unirig_ar_350m_1024_81920_float32.yaml": "llm:\n  _attn_implementation: flash_attention_2\n",
    "configs/model/unirig_skin.yaml": "mesh_encoder:\n  upcast_attention: False\n",
    "run.py": "import argparse\nimport yaml\n",
}
# stand-in UniRig: each "step" records its arguments and writes the file the real one would
STUB_STEP = textwrap.dedent('''
    import json, sys
    from pathlib import Path
    args = dict(a.split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    Path("calls.log").open("a", encoding="utf-8").write(json.dumps([STEP, args]) + "\\n")
    if Path("FAIL_" + STEP).exists():
        sys.exit(3)
    out = args.get("--output")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"glTF-stand-in " + STEP.encode())
''')


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bz.main(argv)
    return code, out.getvalue() + err.getvalue()


def fake_unirig(root):
    """A UniRig-shaped folder whose run.py, src.data.extract and src.inference.merge are stand-ins (already patched
    by patch_unirig.py, so the route's checks pass)."""
    for rel_path, text in UNIRIG_ORIGINALS.items():
        (root / rel_path).parent.mkdir(parents=True, exist_ok=True)
        (root / rel_path).write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, str(PATCHER), str(root)], capture_output=True, check=True)
    task_step = 'import sys\nSTEP = "skin" if "unirig_skin" in " ".join(sys.argv) else "skeleton"\n'
    # the patch marker only (the real patch imports torch and python-box, which this exam's Python lacks)
    (root / "run.py").write_text("# kit patch (#199)\n" + task_step + STUB_STEP, encoding="utf-8")
    for mod, step in (("src/data/extract.py", "extract"), ("src/inference/merge.py", "merge")):
        (root / mod).parent.mkdir(parents=True, exist_ok=True)
        (root / mod).write_text(f'STEP = "{step}"\n' + STUB_STEP, encoding="utf-8")
        (root / mod).parent.joinpath("__init__.py").touch()
    (root / "src" / "__init__.py").touch()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bz_rig_exam_")
        self.root = Path(self.tmp.name) / "game"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "ASSET_LOG.md").write_text(LOG, encoding="utf-8")
        (self.root / "assets" / "models").mkdir(parents=True)
        (self.root / "assets" / "models" / "npc_guard.glb").write_bytes(b"glTF-model")
        self.unirig = Path(self.tmp.name) / "UniRig"
        fake_unirig(self.unirig)
        self.saved = (bz.run_bpy, bz.find_blender, bz.SLEEP, rig.PROBE, rig.OPENER, os.getcwd(), dict(os.environ))
        bz.find_blender = lambda choice=None: ("blender", "fake-blender")
        bz.SLEEP = lambda s: None
        rig.PROBE = False
        os.environ.update({rig.UNIRIG_ENV: str(self.unirig), rig.UNIRIG_PY_ENV: sys.executable,
                           "COMFYUI_URL": "http://127.0.0.1:9"})     # nothing there: /free is skipped
        os.environ.pop(rig.TRIPO_ENV, None)
        self.finish_calls, self.finish_fail = [], None
        bz.run_bpy = self.fake_finish
        os.chdir(self.root)

    def tearDown(self):
        bz.run_bpy, bz.find_blender, bz.SLEEP, rig.PROBE, rig.OPENER, cwd, env = self.saved
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(env)
        self.tmp.cleanup()

    def fake_finish(self, blender, script, argv, what):
        """rig_finish.py stand-in: writes --out and --report like the real one."""
        argv = [str(a) for a in argv]
        self.finish_calls.append(argv)
        rep = {"vertices": 1000, "unweighted": 0, "nan": 0, "bones": 45, "bones_used": 40, "top_bone_share": 0.2,
               "failures": [self.finish_fail] if self.finish_fail else []}
        if not self.finish_fail:
            Path(argv[argv.index("--out") + 1]).write_bytes(b"glTF-finished")
            anim = argv[argv.index("--animate") + 1]
            rep["clips"] = [] if anim == "none" else anim.split(",")
        Path(argv[argv.index("--report") + 1]).write_text(json.dumps(rep), encoding="utf-8")
        return (1 if self.finish_fail else 0), ""


class PatchExam(Base):
    def test_check_patch_and_rerun(self):
        d = Path(self.tmp.name) / "fresh"
        for rel_path, text in UNIRIG_ORIGINALS.items():
            (d / rel_path).parent.mkdir(parents=True, exist_ok=True)
            (d / rel_path).write_text(text, encoding="utf-8")
        run = lambda *a: subprocess.run([sys.executable, str(PATCHER), str(d), *a], capture_output=True,
                                        encoding="utf-8")
        self.assertEqual(run("--check").returncode, 1)
        self.assertEqual(run().returncode, 0)
        skin = (d / "src/model/unirig_skin.py").read_text(encoding="utf-8")
        self.assertIn("from .mha_sdpa import MHA", skin)
        self.assertTrue((d / "src/model/mha_sdpa.py").is_file())
        self.assertIn("sdpa", (d / "configs/model/unirig_ar_350m_1024_81920_float32.yaml").read_text(encoding="utf-8"))
        self.assertIn("enable_flash: False", (d / "configs/model/unirig_skin.yaml").read_text(encoding="utf-8"))
        self.assertIn("add_safe_globals", (d / "run.py").read_text(encoding="utf-8"))
        before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
        self.assertEqual(run().returncode, 0)
        self.assertEqual(before, {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}, "a second run changed files")
        self.assertEqual(run("--check").returncode, 0)

    def test_moved_lines_are_refused(self):
        d = Path(self.tmp.name) / "moved"
        for rel_path, text in UNIRIG_ORIGINALS.items():
            (d / rel_path).parent.mkdir(parents=True, exist_ok=True)
            (d / rel_path).write_text(text.replace("flash_attention_2", "eager"), encoding="utf-8")
        p = subprocess.run([sys.executable, str(PATCHER), str(d)], capture_output=True, encoding="utf-8")
        self.assertEqual(p.returncode, 1)
        self.assertIn("UniRig changed?", p.stdout)


class UniRigExam(Base):
    def test_unirig_route_end_to_end(self):
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 0, out)
        calls = [json.loads(l) for l in (self.unirig / "calls.log").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([c[0] for c in calls], ["extract", "skeleton", "extract", "skin", "merge"])
        self.assertIn("quick_inference_unirig_skin", json.dumps(calls[3]))
        self.assertTrue(calls[4][1]["--target"].endswith("npc_guard.glb"))
        self.assertEqual((self.root / "assets/models/npc_guard_rigged.glb").read_bytes(), b"glTF-finished")
        self.assertEqual(self.finish_calls[0][self.finish_calls[0].index("--animate") + 1], "idle,wave,walk")
        self.assertEqual(self.finish_calls[0][self.finish_calls[0].index("--names") + 1], "mixamo")
        log = (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8")
        row = [l for l in log.splitlines() if l.startswith("| A-0002")][0]
        self.assertIn("rig of A-0001", row)
        self.assertIn("Articulation-XL2.0", row)
        self.assertTrue((self.root / "docs/licenses/bozzetto-rig-UniRig-LICENSE.txt").is_file())
        self.assertTrue((self.root / "docs/licenses/A-0002.txt").is_file())
        rec = json.loads((self.root / "assets_src/bozzetto/npc_guard/rig/unirig/rig.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["route"], "unirig")
        for f in [self.root / "docs/ASSET_LOG.md", self.root / "docs/licenses/A-0002.txt"]:
            self.assertNotIn(str(self.root.parent), f.read_text(encoding="utf-8"), f"local path in {f.name}")

    def test_rerun_needs_overwrite_and_keeps_one_row(self):
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--animate", "none"])[0], 0)
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", out)
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--overwrite"])[0], 0)
        log = (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("npc_guard_rigged.glb"), 1)
        self.assertIn("clips: idle, wave, walk", log)

    def test_failed_step_and_failed_check_ship_nothing(self):
        (self.unirig / "FAIL_skin").touch()
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 1)
        self.assertIn("UniRig skin failed", out)
        (self.unirig / "FAIL_skin").unlink()
        self.finish_fail = "bone bone_3 holds 97% of the vertices"
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 1)
        self.assertIn("97%", out)
        self.assertFalse((self.root / "assets/models/npc_guard_rigged.glb").exists())
        self.assertNotIn("npc_guard_rigged", (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8"))

    def test_not_ready_and_missing_input_exit_2(self):
        os.environ.pop(rig.UNIRIG_ENV)
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 2)
        self.assertIn("UNIRIG_DIR is not set", out)
        os.environ[rig.UNIRIG_ENV] = str(self.unirig)
        code, out = run_main(["rig", "make", "npc_nobody"])
        self.assertEqual(code, 2)
        self.assertIn("not found", out)

    def test_unpatched_checkout_is_named(self):
        (self.unirig / "src/model/unirig_skin.py").write_text(UNIRIG_ORIGINALS["src/model/unirig_skin.py"],
                                                              encoding="utf-8")
        code, out = run_main(["rig", "check"])
        self.assertIn("not patched", out)


class FakeTripo:
    """Canned Tripo v3 answers keyed by path; records every call."""

    def __init__(self, balance=500.0, riggable=True, rig_type="biped"):
        self.calls, self.balance, self.riggable, self.rig_type = [], balance, riggable, rig_type
        self.tasks = {}

    def __call__(self, req, timeout=0):
        url = req.full_url
        path = url.split("/v3", 1)[-1] if "/v3" in url else url
        self.calls.append((req.get_method(), path))
        if url.startswith("https://dl.example/"):
            return io.BytesIO(b"glTF-tripo")
        body = json.loads(req.data) if req.data and req.headers.get("Content-type") == "application/json" else {}
        if path == "/account/balance":
            data = {"balance": self.balance, "frozen": 0}
        elif path == "/files":
            data = {"file_token": "file_1"}
        elif req.get_method() == "POST":
            tid = f"t{len(self.tasks) + 1}"
            self.tasks[tid] = (path, body)
            data = {"task_id": tid}
        else:
            kind, sent = self.tasks[path.rsplit("/", 1)[1]]
            out, cost = {}, 0
            if kind.endswith("rig-check"):
                out = {"riggable": self.riggable, "rig_type": self.rig_type, "normalize_scale": 0.5}
            elif kind.endswith("/rig"):
                out, cost = {"model_url": "https://dl.example/rig.glb", "normalize_scale": 0.5}, 25
            else:
                out, cost = {"model_url": "https://dl.example/anim.glb"}, 10 * len(sent["animations"])
            data = {"status": "success", "output": out, "credits_consumed": cost}
        return io.BytesIO(json.dumps({"code": 0, "data": data}).encode())


class TripoExam(Base):
    def setUp(self):
        super().setUp()
        os.environ[rig.TRIPO_ENV] = "tsk_exam"

    def test_quote_over_limit_or_balance_stops_before_upload(self):
        rig.OPENER = fake = FakeTripo()
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk,run",
                              "--max-credits", "40"])
        self.assertEqual(code, 2)
        self.assertIn("over --max-credits", out)
        self.assertNotIn(("POST", "/files"), fake.calls)
        rig.OPENER = fake = FakeTripo(balance=20)
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo"])
        self.assertEqual(code, 2)
        self.assertIn("under the quote", out)
        self.assertNotIn(("POST", "/files"), fake.calls)

    def test_not_a_biped_stops_before_a_paid_call(self):
        rig.OPENER = fake = FakeTripo(rig_type="quadruped")
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo"])
        self.assertEqual(code, 1)
        self.assertIn("not a riggable biped", out)
        self.assertEqual([k for k, _ in fake.tasks.values()], ["/animations/rig-check"])

    def test_paid_route_end_to_end(self):
        rig.OPENER = fake = FakeTripo()
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk"])
        self.assertEqual(code, 0, out)
        kinds = [(k, b) for k, b in fake.tasks.values()]
        self.assertEqual([k for k, _ in kinds], ["/animations/rig-check", "/animations/rig", "/animations/retarget"])
        self.assertEqual(kinds[1][1]["spec"], "mixamo")
        self.assertEqual(kinds[2][1]["animations"], ["preset:idle", "preset:walk"])
        argv = self.finish_calls[0]
        self.assertAlmostEqual(float(argv[argv.index("--scale") + 1]), 2.0)     # 1 / normalize_scale
        self.assertEqual(argv[argv.index("--animate") + 1], "none")             # Tripo's own clips
        self.assertIn("45 Tripo credits", out)
        row = [l for l in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
               if "npc_guard_rigged" in l][0]
        self.assertIn("paid service", row)
        self.assertIn("45 credits", row)
        self.assertFalse((self.root / "docs/licenses/bozzetto-rig-UniRig-LICENSE.txt").exists())

    def test_unknown_or_too_many_clips_exit_2(self):
        rig.OPENER = FakeTripo()
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "moonwalk"])[0], 2)
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--with", "tripo",
                                   "--clips", "idle,walk,run,jump,turn,fall"])[0], 2)


# ---- part 2: rig_finish.py in Blender ------------------------------------------------------------------------
BUILD = textwrap.dedent('''
    import sys, bpy
    from mathutils import Vector
    out, kind = sys.argv[sys.argv.index("--") + 1:][:2]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm_data = bpy.data.armatures.new("rig"); arm = bpy.data.objects.new("rig", arm_data)
    bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    def bone(name, head, tail, parent=None):
        b = arm_data.edit_bones.new(name); b.head, b.tail = Vector(head), Vector(tail)
        if parent: b.parent = arm_data.edit_bones[parent]
        return name
    bone("b0", (0, 0, 0.9), (0, 0, 1.1)); bone("b1", (0, 0, 1.1), (0, 0, 1.35), "b0")
    bone("b2", (0, 0, 1.35), (0, 0, 1.5), "b1"); bone("b3", (0, 0, 1.5), (0, 0, 1.8), "b2")
    legs = [("L", 0.12), ("R", -0.12)] + ([("BL", 0.12), ("BR", -0.12)] if kind == "quad" else [])
    for s, x in legs:
        y = 0.3 if s.startswith("B") else 0.0
        bone("t" + s, (x, y, 0.9), (x, y, 0.5), "b0"); bone("s" + s, (x, y, 0.5), (x, y, 0.08), "t" + s)
        bone("f" + s, (x, y, 0.08), (x, y - 0.15, 0.0), "s" + s)
    if kind != "quad":
        for s, x in (("L", 1), ("R", -1)):
            bone("c" + s, (0.05 * x, 0, 1.45), (0.18 * x, 0, 1.45), "b2"); bone("u" + s, (0.18 * x, 0, 1.45), (0.45 * x, 0, 1.25), "c" + s)
            bone("o" + s, (0.45 * x, 0, 1.25), (0.7 * x, 0, 1.05), "u" + s); bone("h" + s, (0.7 * x, 0, 1.05), (0.8 * x, 0, 0.98), "o" + s)
    if kind == "neutral":
        bone("neutral_bone", (0, 0, 0), (0, 0, 0.1))
    bpy.ops.object.mode_set(mode="OBJECT")
    names = [b.name for b in arm_data.bones]
    mesh_objs = []
    for i, n in enumerate(names):
        b = arm_data.bones[n]; mid = (b.head_local + b.tail_local) / 2
        bpy.ops.mesh.primitive_cube_add(size=0.06, location=mid)
        o = bpy.context.active_object; o.name = "part_" + n
        target = names[0] if kind == "one_bone" and i % 10 else ("neutral_bone" if kind == "neutral" and i < 6 else n)
        o.vertex_groups.new(name=target).add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
        mesh_objs.append(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in mesh_objs: o.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]; bpy.ops.object.join()
    body = bpy.context.active_object; body.name = "body"
    body.parent = arm; mod = body.modifiers.new("Armature", "ARMATURE"); mod.object = arm
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True)
''')


def pick_blender():
    choice = os.environ.get("BOZZETTO_TEST_BLENDER", "")
    if choice == "skip":
        return None
    return bz.find_blender(choice or None)


BLENDER = pick_blender()


def blender_run(script, argv):
    kind, path = BLENDER
    cmd = ([path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--"] if kind == "blender"
           else [path, str(script)]) + [str(a) for a in argv]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=900)


@unittest.skipUnless(BLENDER, "no Blender or bpy found (part 2 skipped)")
class FinishExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bz_rig_bpy_")
        cls.d = Path(cls.tmp.name)
        builder = cls.d / "build.py"
        builder.write_text(BUILD, encoding="utf-8")
        for kind in ("biped", "one_bone", "neutral", "quad"):
            p = blender_run(builder, [cls.d / f"{kind}.glb", kind])
            assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def finish(self, kind, *extra):
        rep = self.d / f"{kind}.json"
        p = blender_run(HERE / "rig_finish.py", [self.d / f"{kind}.glb", "--out", self.d / f"{kind}_out.glb",
                                                 "--report", rep, *extra])
        return p, (json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {})

    def test_biped_passes_with_mixamo_names_and_moving_clips(self):
        p, rep = self.finish("biped", "--animate", "idle,wave,walk", "--scale", "2")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        self.assertEqual(rep["failures"], [])
        self.assertEqual(rep["clips"], ["idle", "wave", "walk"])
        probe = self.d / "probe.py"
        probe.write_text(textwrap.dedent('''
            import sys, json, bpy
            src = sys.argv[sys.argv.index("--") + 1]
            bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=src)
            arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
            mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
            def pts():
                dg = bpy.context.evaluated_depsgraph_get(); ev = mesh.evaluated_get(dg); me = ev.to_mesh()
                c = [mesh.matrix_world @ v.co for v in me.vertices]; ev.to_mesh_clear(); return c
            moves = {}
            for act in bpy.data.actions:
                arm.animation_data.action = act; f0, f1 = (int(f) for f in act.frame_range)
                bpy.context.scene.frame_set(f0); a = pts(); best = 0.0
                for k in range(1, 7):   # sevenths: no clip's beat lands on all of them (sixths hit the wave's zeros)
                    bpy.context.scene.frame_set(f0 + k * (f1 - f0) // 7); b = pts()
                    best = max(best, max((x - y).length for x, y in zip(a, b)))
                moves[act.name] = best
            names = {b.name: [round(b.head_local.x, 2), round(b.head_local.z, 2)] for b in arm.data.bones}
            height = max(v.z for v in pts())
            print("PROBE" + json.dumps({"moves": moves, "names": names, "height": height}))
        '''), encoding="utf-8")
        q = blender_run(probe, [self.d / "biped_out.glb"])
        data = json.loads(next(l for l in q.stdout.splitlines() if l.startswith("PROBE"))[5:])
        names = data["names"]
        for n in ("Hips", "Spine", "Neck", "Head", "LeftUpLeg", "RightUpLeg", "LeftForeArm", "RightHand"):
            self.assertIn("mixamorig:" + n, names)
        self.assertGreater(names["mixamorig:LeftUpLeg"][0], 0)      # left is +X (the character faces -Y)
        self.assertLess(names["mixamorig:RightArm"][0], 0)
        for clip, moved in data["moves"].items():
            self.assertGreater(moved, 0.01, f"{clip} does not move the mesh")
        self.assertGreater(data["height"], 3.0)                     # --scale 2 on a 1.8 m figure

    def test_everything_on_one_bone_fails(self):
        p, rep = self.finish("one_bone")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("holds" in f for f in rep["failures"]), rep)
        self.assertFalse((self.d / "one_bone_out.glb").exists())

    def test_placeholder_bone_fails(self):
        p, rep = self.finish("neutral")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("placeholder" in f for f in rep["failures"]), rep)

    def test_quadruped_is_not_mapped_as_a_biped(self):
        p, rep = self.finish("quad", "--animate", "walk")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("quadruped" in f or "biped" in f for f in rep["failures"]), rep)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
