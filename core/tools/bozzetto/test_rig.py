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
#           one bone, one with vertices only on glTF's placeholder bone, and a four-legged one fail with exit 1; a
#           clip whose hips stand off their rest spot in every key is re-centred (wobble and bob kept), one in place
#           and one that travels are left as they are, also under a still root above the hips; a clip keyed at
#           30 fps comes out looping and as long as it was (#292). The builder and the probes run under Blender
#           and under the bpy module alike (their own arguments after Blender's "--" or without it; the module's
#           process ended by hand on Windows).
# Usage   : python tools/bozzetto/test_rig.py
#           BOZZETTO_TEST_BLENDER=skip|bpy|<path to blender>  picks part 2's Blender (skip: part 1 only)
#           uv run --python 3.11 --with "bpy==4.2.*" python tools/bozzetto/test_rig.py   # part 2 on the bpy 4.2 module
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): part 2 under the bpy module, the 30 fps clip and
#           the root-above-the-hips cases (#292)
# ---------------------------------------------------------------------------
import ast
import contextlib
import io
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.error
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bozzetto as bz  # noqa: E402
import rig  # noqa: E402
import tripo  # noqa: E402

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
    print("stand-in", STEP, "reading", args.get("--input", ""))   # the real UniRig prints absolute paths too
    if Path("FAIL_" + STEP).exists():
        sys.exit(3)
    if Path("SILENT_" + STEP).exists():
        sys.exit(0)                     # exit 0 without writing its output (#212)
    out = args.get("--output")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"glTF-stand-in " + STEP.encode() + Path(args.get("--input", "x")).name.encode())
    if args.get("--output_dir"):
        # as UniRig's extract.py does: os.path.join(output_dir, <input without suffix>), which an absolute input
        # path turns into a folder next to the input itself
        import os
        dest = os.path.join(args["--output_dir"], os.path.splitext(args["--input"])[0])
        os.makedirs(dest, exist_ok=True)
        Path(dest, "raw_data.npz").write_bytes(b"npz")
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
    # the patched text sits in a string, so --check sees it but this exam's Python never imports torch or python-box
    patched = (root / "run.py").read_text(encoding="utf-8")
    (root / "run.py").write_text('PATCHED = """\n' + patched + '"""\n' + task_step + STUB_STEP, encoding="utf-8")
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
        self.saved = (bz.run_bpy, bz.find_blender, bz.SLEEP, rig.PROBE, tripo.OPENER, os.getcwd(), dict(os.environ))
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
        bz.run_bpy, bz.find_blender, bz.SLEEP, rig.PROBE, tripo.OPENER, cwd, env = self.saved
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

    def test_a_marker_without_the_patched_code_is_not_patched(self):
        """#215: the marker comment alone (the code reverted by hand) must not pass --check."""
        d = Path(self.tmp.name) / "reverted"
        for rel_path, text in UNIRIG_ORIGINALS.items():
            (d / rel_path).parent.mkdir(parents=True, exist_ok=True)
            (d / rel_path).write_text(text, encoding="utf-8")
        subprocess.run([sys.executable, str(PATCHER), str(d)], capture_output=True, check=True)
        skin = d / "src/model/unirig_skin.py"
        skin.write_text("# kit patch (#199)\n" + UNIRIG_ORIGINALS["src/model/unirig_skin.py"], encoding="utf-8")
        p = subprocess.run([sys.executable, str(PATCHER), str(d), "--check"], capture_output=True, encoding="utf-8")
        self.assertEqual(p.returncode, 1)
        self.assertIn("patched code is not", p.stdout)


class UniRigExam(Base):
    def test_unirig_route_end_to_end(self):
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 0, out)
        calls = [json.loads(l) for l in (self.unirig / "calls.log").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([c[0] for c in calls], ["extract", "skeleton", "extract", "skin", "merge"])
        self.assertIn("quick_inference_unirig_skin", json.dumps(calls[3]))
        self.assertTrue(calls[4][1]["--target"].endswith("input.glb"))
        # UniRig writes next to its input: it must work on a copy, so nothing lands in the game's models folder
        models = self.root / "assets/models"
        self.assertEqual(sorted(p.name for p in models.iterdir()), ["npc_guard.glb", "npc_guard_rigged.glb"])
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
        work = self.root / "assets_src/bozzetto/npc_guard/rig/unirig"
        for f in [self.root / "docs/ASSET_LOG.md", self.root / "docs/licenses/A-0002.txt", work / "rig.json",
                  work / "unirig.log"]:     # #211: the UniRig log, with UniRig's own output in it, too
            text = f.read_text(encoding="utf-8")
            for local in (str(self.root.parent), str(self.root.parent).replace("\\", "/"), str(self.unirig)):
                self.assertNotIn(local, text, f"local path in {f.name}")
        self.assertIn("<project>", (work / "unirig.log").read_text(encoding="utf-8"))
        # #291 live run: the next step told Unity users to set the rig to Humanoid, which #290 found plays none of
        # the glTF's own clips (glTFast imports them Generic); point at the engine's recipe and the chain instead
        nxt = [l for l in out.splitlines() if l.startswith("[next]")]
        self.assertEqual(len(nxt), 1, out)
        self.assertNotIn("Humanoid (Mixamo", nxt[0])
        self.assertIn("rig chain npc_guard", nxt[0])
        self.assertIn("Rigged characters", nxt[0])

    def test_a_step_that_writes_nothing_never_ships_an_older_rig(self):
        """#212: after a good run, a re-run whose merge exits 0 without output must fail, not reuse the old file."""
        self.assertEqual(run_main(["rig", "make", "npc_guard"])[0], 0)
        (self.unirig / "SILENT_merge").touch()
        code, out = run_main(["rig", "make", "npc_guard", "--overwrite"])
        self.assertEqual(code, 1, out)
        self.assertIn("no rigged.glb written", out)
        self.assertEqual(len(self.finish_calls), 1, "rig_finish ran on a stale file")

    def test_options_are_checked_before_any_gpu_step(self):
        """#213: a bad --animate or --wait, or an --out outside the project, stops before UniRig runs."""
        for argv, says in ((["--animate", "dance"], "no clip 'dance'"), (["--wait", "0"], "--wait"),
                           (["--input", "assets/models/npc_guard.glb", "--out", str(Path(self.tmp.name) / "elsewhere")],
                            "outside the project")):
            code, out = run_main(["rig", "make", "npc_guard"] + argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(says, out)
        self.assertFalse((self.unirig / "calls.log").exists(), "UniRig ran before the options were checked")
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--input", "assets/models/npc_guard.glb", "--no-log",
                                   "--out", str(Path(self.tmp.name) / "elsewhere")])[0], 0)

    def test_a_relative_unirig_dir_works(self):
        """#213: UNIRIG_DIR given relative to the current folder."""
        os.environ[rig.UNIRIG_ENV] = os.path.relpath(self.unirig, self.root)
        os.environ.pop(rig.UNIRIG_PY_ENV)
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.unirig / ".venv")], check=True)
        code, out = run_main(["rig", "make", "npc_guard"])
        self.assertEqual(code, 0, out)

    def test_log_rows_name_the_source_and_the_naming(self):
        """#214: --names keep is logged as such; re-rigging an unlogged input never names its own row as source."""
        (self.root / "assets/models/odd.glb").write_bytes(b"glTF-odd")
        self.assertEqual(run_main(["rig", "make", "odd", "--names", "keep"])[0], 0)
        self.assertEqual(run_main(["rig", "make", "odd", "--names", "keep", "--overwrite"])[0], 0)
        row = [l for l in (self.root / "docs/ASSET_LOG.md").read_text(encoding="utf-8").splitlines()
               if "odd_rigged" in l][0]
        aid = row.split("|")[1].strip()
        self.assertIn("rig of `assets/models/odd.glb`", row)
        self.assertNotIn(f"rig of {aid}", row)
        self.assertIn("bone names kept", row)

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

    def test_wait_reaches_the_unirig_steps(self):
        """#222: rig make --wait is each UniRig step's limit too, not only Tripo's."""
        real = subprocess.run
        seen = []

        def spy(*a, **k):
            if "timeout" in k and any("src.data.extract" in str(x) or "run.py" in str(x) for x in (a[0] if a else [])):
                seen.append(k["timeout"])
            return real(*a, **k)
        with mock.patch.object(rig.subprocess, "run", spy):
            self.assertEqual(run_main(["rig", "make", "npc_guard", "--wait", "77"])[0], 0)
        self.assertEqual(seen, [77] * 4)          # extract, skeleton, extract, skin (merge runs src.inference)

    def test_unpatched_checkout_is_named(self):
        (self.unirig / "src/model/unirig_skin.py").write_text(UNIRIG_ORIGINALS["src/model/unirig_skin.py"],
                                                              encoding="utf-8")
        code, out = run_main(["rig", "check"])
        self.assertIn("not patched", out)


class FakeTripo:
    """Canned Tripo v3 answers keyed by path; records every call."""

    def __init__(self, balance=500.0, riggable=True, rig_type="biped", rig_cost=25, no_url=False):
        self.calls, self.balance, self.riggable, self.rig_type = [], balance, riggable, rig_type
        self.rig_cost, self.no_url = rig_cost, no_url      # Tripo charging more than its table; a lost URL
        self.tasks = {}
        self.status = {}          # task id -> status reported instead of success (a task still running, failed)
        self.bad_key = False

    def posts(self, kind):
        return [k for k, _ in self.tasks.values() if k == kind]

    def __call__(self, req, timeout=0):
        url = req.full_url
        path = url.split("/v3", 1)[-1] if "/v3" in url else url
        self.calls.append((req.get_method(), path))
        if url.startswith("https://dl.example/"):
            return io.BytesIO(b"glTF-tripo")
        body = json.loads(req.data) if req.data and req.headers.get("Content-type") == "application/json" else {}
        if self.bad_key:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))
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
                out, cost = {"model_url": "https://dl.example/rig.glb", "normalize_scale": 0.5}, self.rig_cost
            else:
                out = {} if self.no_url else {"model_url": "https://dl.example/anim.glb"}
                cost = 10 * len(sent["animations"])
            tid_ = path.rsplit("/", 1)[1]
            data = {"status": self.status.get(tid_, "success"), "output": out, "credits_consumed": cost}
        return io.BytesIO(json.dumps({"code": 0, "data": data}).encode())


class TripoExam(Base):
    def setUp(self):
        super().setUp()
        os.environ[rig.TRIPO_ENV] = "tsk_exam"

    def test_quote_over_limit_or_balance_stops_before_upload(self):
        tripo.OPENER = fake = FakeTripo()
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk,run",
                              "--max-credits", "40"])
        self.assertEqual(code, 2)
        self.assertIn("over --max-credits", out)
        self.assertNotIn(("POST", "/files"), fake.calls)
        tripo.OPENER = fake = FakeTripo(balance=20)
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo"])
        self.assertEqual(code, 2)
        self.assertIn("under the next step", out)
        self.assertNotIn(("POST", "/files"), fake.calls)

    def test_not_a_biped_stops_before_a_paid_call(self):
        tripo.OPENER = fake = FakeTripo(rig_type="quadruped")
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo"])
        self.assertEqual(code, 1)
        self.assertIn("not a riggable biped", out)
        self.assertEqual([k for k, _ in fake.tasks.values()], ["/animations/rig-check"])

    def test_paid_route_end_to_end(self):
        tripo.OPENER = fake = FakeTripo()
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

    def test_actual_cost_is_checked_before_the_next_paid_call(self):
        """#209: the rig costs more than the table; the clips step must not push spend past --max-credits. A re-run
        with a higher limit reuses the paid rig and pays only for the clips (#210)."""
        tripo.OPENER = fake = FakeTripo(rig_cost=70)
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk",
                              "--max-credits", "80"])
        self.assertEqual(code, 2, out)
        self.assertIn("over --max-credits 80", out)
        self.assertEqual(fake.posts("/animations/retarget"), [])
        journal = json.loads((self.root / "assets_src/bozzetto/npc_guard/rig/tripo/tasks.json").read_text(encoding="utf-8"))
        self.assertEqual(journal["tasks"]["rig"]["status"], "success")
        tripo.OPENER = fake2 = FakeTripo()
        fake2.tasks.update(fake.tasks)          # the same server still knows the paid rig task
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk",
                              "--max-credits", "200"])
        self.assertEqual(code, 0, out)
        self.assertIn("reusing paid Tripo work", out)
        self.assertEqual(len(fake2.posts("/animations/rig")), 1, "the rig was paid for twice")   # the old one only
        self.assertEqual(len(fake2.posts("/animations/retarget")), 1)

    def test_a_lost_result_is_fetched_again_without_paying(self):
        """#210: rig and clips succeed but the model URL is missing: the run fails, the journal keeps the paid
        tasks, and a re-run downloads the result with no new paid call."""
        tripo.OPENER = fake = FakeTripo(no_url=True)
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk"])
        self.assertEqual(code, 1, out)
        self.assertIn("a re-run fetches it again without paying", out)
        fake.no_url = False
        paid = len(fake.posts("/animations/rig")) + len(fake.posts("/animations/retarget"))
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk"])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(fake.posts("/animations/rig")) + len(fake.posts("/animations/retarget")), paid)
        self.assertTrue((self.root / "assets/models/npc_guard_rigged.glb").is_file())

    def journal(self, tasks):
        j = self.root / "assets_src/bozzetto/npc_guard/rig/tripo/tasks.json"
        j.parent.mkdir(parents=True, exist_ok=True)
        sha = bz.sha256_bytes((self.root / "assets/models/npc_guard.glb").read_bytes())
        j.write_text(json.dumps({"input_sha256": sha, "clips": ["idle", "walk"], "rig_model": rig.TRIPO_RIG_MODEL,
                                 "tasks": tasks}), encoding="utf-8")

    def test_a_task_left_running_is_adopted_not_paid_again(self):
        """#221: the journal says a paid rig task was running when the last run stopped; it finished since."""
        tripo.OPENER = fake = FakeTripo()
        fake.tasks["t99"] = ("/animations/rig", {})
        self.journal({"rig": {"id": "t99", "status": "running"}})
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk"])
        self.assertEqual(code, 0, out)
        self.assertEqual(fake.posts("/animations/rig"), ["/animations/rig"], "a second rig was paid for")
        self.assertEqual(len(fake.posts("/animations/retarget")), 1)

    def test_a_task_still_running_stops_the_run_without_paying(self):
        """#221: a journalled task still running after --wait must not be replaced by a new paid one."""
        tripo.OPENER = fake = FakeTripo()
        fake.tasks["t99"] = ("/animations/rig", {})
        fake.status["t99"] = "running"
        self.journal({"rig": {"id": "t99", "status": "running"}})
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk", "--wait", "1"])
        self.assertEqual(code, 2, out)
        self.assertIn("still running", out)
        self.assertEqual(len(fake.posts("/animations/rig")), 1)          # only the journalled one, nothing new
        fake.status["t99"] = "failed"                                     # it failed after all: a new one is made
        code, out = run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "idle,walk"])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(fake.posts("/animations/rig")), 2)

    def test_a_bad_key_is_not_ready(self):
        """#222: with no UniRig and a Tripo key that is refused, rig check exits 2."""
        os.environ.pop(rig.UNIRIG_ENV)
        tripo.OPENER = fake = FakeTripo()
        fake.bad_key = True
        code, out = run_main(["rig", "check"])
        self.assertEqual(code, 2, out)
        self.assertIn("not ready", out)
        fake.bad_key = False
        self.assertEqual(run_main(["rig", "check"])[0], 0)

    def test_unknown_or_too_many_clips_exit_2(self):
        tripo.OPENER = FakeTripo()
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--with", "tripo", "--clips", "moonwalk"])[0], 2)
        self.assertEqual(run_main(["rig", "make", "npc_guard", "--with", "tripo",
                                   "--clips", "idle,walk,run,jump,turn,fall"])[0], 2)


# ---- part 2: rig_finish.py in Blender ------------------------------------------------------------------------
END = textwrap.dedent('''
    if not bpy.app.binary_path and sys.platform == "win32":
        # the bpy module crashes while the process ends on Windows (bpy_common.py says more): end it here (#292)
        import ctypes
        sys.stdout.flush()
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.TerminateProcess(k.GetCurrentProcess(), 0)
''')

# a script's own arguments: after Blender's "--", or all of them under the bpy module (#292)
ARGV = 'ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]\n'

BUILD = textwrap.dedent('''
    import sys, bpy
    from mathutils import Vector
    ''') + ARGV + textwrap.dedent('''
    out, kind = ARGV[:2]
    ground = kind in ("ground", "offset_root")        # a ground-level root above the pelvis (#216)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm_data = bpy.data.armatures.new("rig"); arm = bpy.data.objects.new("rig", arm_data)
    bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    def bone(name, head, tail, parent=None):
        b = arm_data.edit_bones.new(name); b.head, b.tail = Vector(head), Vector(tail)
        if parent: b.parent = arm_data.edit_bones[parent]
        return name
    if ground:
        bone("g", (0, 0, 0), (0, 0, 0.1))
    bone("b0", (0, 0, 0.9), (0, 0, 1.1), "g" if ground else None); bone("b1", (0, 0, 1.1), (0, 0, 1.35), "b0")
    bone("b2", (0, 0, 1.35), (0, 0, 1.5), "b1"); bone("b3", (0, 0, 1.5), (0, 0, 1.8), "b2")
    legs = [("L", 0.12), ("R", -0.12)] + ([("BL", 0.12), ("BR", -0.12)] if kind == "quad" else [])
    toe = 0.15 if kind == "backward" else -0.15           # toes point -Y (front) unless the model faces backward
    for s, x in legs:
        y = 0.3 if s.startswith("B") else 0.0
        bone("t" + s, (x, y, 0.9), (x, y, 0.5), "b0"); bone("s" + s, (x, y, 0.5), (x, y, 0.08), "t" + s)
        bone("f" + s, (x, y, 0.08), (x, y + toe, 0.0), "s" + s)
    if kind != "quad":
        for s, x in (("L", 1), ("R", -1)):
            P = (lambda a, z: (0, a, z)) if kind == "sideways" else (lambda a, z: (a, 0, z))   # arms along Y or X
            if kind == "short":           # a 2-bone arm: upper arm and hand only (#216)
                bone("u" + s, P(0.05 * x, 1.45), P(0.45 * x, 1.25), "b2"); bone("h" + s, P(0.45 * x, 1.25), P(0.8 * x, 0.98), "u" + s)
                continue
            bone("c" + s, P(0.05 * x, 1.45), P(0.18 * x, 1.45), "b2"); bone("u" + s, P(0.18 * x, 1.45), P(0.45 * x, 1.25), "c" + s)
            bone("o" + s, P(0.45 * x, 1.25), P(0.7 * x, 1.05), "u" + s); bone("h" + s, P(0.7 * x, 1.05), P(0.8 * x, 0.98), "o" + s)
    if kind == "neutral":
        bone("neutral_bone", (0, 0, 0), (0, 0, 0.1))
    if kind == "partial":                 # one Mixamo name, the rest generic (#216)
        arm_data.edit_bones["b0"].name = "mixamorig:Hips"
    if kind in ("offset", "offset_root"):   # the hips' axes turned, as bone axes vary between rigs
        arm_data.edit_bones["b0"].roll = 0.9
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
    import math
    if kind in ("offset", "offset_root"):   # Tripo's in-place clips with an offset root (live run, 2026-11-11)
        to_local = arm_data.bones["b0"].matrix_local.to_3x3().inverted()
        pb = arm.pose.bones["b0"]
        arm.animation_data_create()
        def clip(name, at, n=24):         # at(t, u) -> the hips' offset from rest in armature space, per key
            act = bpy.data.actions.new(name); arm.animation_data.action = act
            for f in range(n + 1):
                pb.location = to_local @ Vector(at(2 * math.pi * f / n, f / n))
                pb.keyframe_insert("location", frame=f + 1)
                if ground:                # the root above the hips sampled on every frame, never moved (as an
                    g = arm.pose.bones["g"]; g.rotation_mode = "QUATERNION"      # exporter writes every bone)
                    g.keyframe_insert("rotation_quaternion", frame=f + 1)
            act.use_fake_user = True; arm.animation_data.action = None
        # walk: 0.4 m to the side and 1.3 m back in every key, plus a wobble (whole periods: mean 0) and a bob
        clip("walk", lambda t, u: (0.4 + 0.03 * math.sin(t), 1.3 + 0.02 * math.sin(2 * t), 0.05 * abs(math.cos(t))))
        clip("idle", lambda t, u: (0.003 * math.sin(t), 0.0, 0.01 * abs(math.cos(t))))     # in place
        clip("run", lambda t, u: (0.0, -1.5 * u, 0.03 * abs(math.cos(t))))                  # travels: root motion
    if kind == "thirty":                  # a looping clip keyed at 30 fps, as Tripo's come (#292)
        from mathutils import Quaternion
        bpy.context.scene.render.fps = 30
        arm.animation_data_create()
        act = bpy.data.actions.new("walk"); arm.animation_data.action = act
        for f in range(THIRTY_FRAMES + 1):           # keys 1 .. THIRTY_FRAMES + 1; the last equals the first
            t = 2 * math.pi * f / THIRTY_FRAMES
            for n, sgn in (("tL", 1), ("tR", -1)):
                pb = arm.pose.bones[n]; pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = Quaternion((1, 0, 0), math.radians(sgn * 25 * math.sin(t)))
                pb.keyframe_insert("rotation_quaternion", frame=f + 1)
            pb = arm.pose.bones["b0"]; pb.location = (0, 0.03 * abs(math.cos(t)), 0)
            pb.keyframe_insert("location", frame=f + 1)
        act.use_fake_user = True; arm.animation_data.action = None
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True)
''')
THIRTY_FRAMES = 56                        # the 30 fps fixture's loop length in frames (Tripo's walk had 56 at 30 fps)
BUILD = BUILD.replace("THIRTY_FRAMES", str(THIRTY_FRAMES))


def pick_blender():
    choice = os.environ.get("BOZZETTO_TEST_BLENDER", "")
    if choice == "skip":
        return None
    return bz.find_blender(choice or None)


BLENDER = pick_blender()


def finish_constants():
    """rig_finish.py's clip constants (FPS, IDLE_FRAMES ...), read from its source: it imports bpy, so it cannot
    be imported here."""
    out = {}
    for node in ast.parse((HERE / "rig_finish.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Constant, ast.Tuple)):
            names = node.targets[0].elts if isinstance(node.targets[0], ast.Tuple) else node.targets
            values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            for n, v in zip(names, values):
                if isinstance(n, ast.Name) and isinstance(v, ast.Constant):
                    out[n.id] = v.value
    return out


FINISH_CONST = finish_constants()


def blender_run(script, argv):
    kind, path = BLENDER
    cmd = ([path, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--"] if kind == "blender"
           else [path, str(script)]) + [str(a) for a in argv]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=900)


def read_glb(path):
    """(json dict, bin bytes) of a .glb, with the standard library."""
    data = Path(path).read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + jlen].decode("utf-8"))
    blen = struct.unpack_from("<I", data, 20 + jlen)[0]
    return doc, data[28 + jlen:28 + jlen + blen]


def accessor_floats(doc, binary, index):
    """A float32 accessor as a list of tuples (numbers for SCALAR)."""
    acc = doc["accessors"][index]
    n = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[acc["type"]]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride", 4 * n)
    out = []
    for i in range(acc["count"]):
        vals = struct.unpack_from(f"<{n}f", binary, start + i * stride)
        out.append(vals[0] if n == 1 else vals)
    return out


@unittest.skipUnless(BLENDER, "no Blender or bpy found (part 2 skipped)")
class FinishExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bz_rig_bpy_")
        cls.d = Path(cls.tmp.name)
        builder = cls.d / "build.py"
        builder.write_text(BUILD + END, encoding="utf-8")
        for kind in ("biped", "one_bone", "neutral", "quad", "ground", "backward", "sideways", "short", "partial",
                     "offset", "offset_root", "thirty"):
            p = blender_run(builder, [cls.d / f"{kind}.glb", kind])
            assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def probe(self, name, body, argv):
        """Run a probe script in Blender (its own arguments through ARGV, the module's exit handled) and return the
        line starting with `name` as parsed JSON."""
        script = self.d / f"{name.lower()}.py"
        script.write_text("import sys, json, bpy\n" + ARGV + textwrap.dedent(body) + END, encoding="utf-8")
        q = blender_run(script, argv)
        line = next((l for l in q.stdout.splitlines() if l.startswith(name)), None)
        self.assertIsNotNone(line, q.stdout[-3000:] + q.stderr[-2000:])
        return json.loads(line[len(name):])

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
        # the clips keyed here are in place by construction: the walk's hips only bob, idle and wave keep them still
        self.assertEqual(rep["recentred"]["walk"]["action"], "in place", rep["recentred"])
        self.assertEqual(rep["recentred"]["idle"]["action"], "no location keys", rep["recentred"])
        data = self.probe("PROBE", '''
            src = ARGV[0]
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
        ''', [self.d / "biped_out.glb"])
        names = data["names"]
        for n in ("Hips", "Spine", "Neck", "Head", "LeftUpLeg", "RightUpLeg", "LeftForeArm", "RightHand"):
            self.assertIn("mixamorig:" + n, names)
        self.assertGreater(names["mixamorig:LeftUpLeg"][0], 0)      # left is +X (the character faces -Y)
        self.assertLess(names["mixamorig:RightArm"][0], 0)
        for clip, moved in data["moves"].items():
            self.assertGreater(moved, 0.01, f"{clip} does not move the mesh")
        self.assertGreater(data["height"], 3.0)                     # --scale 2 on a 1.8 m figure

    def test_clips_start_at_zero_seconds(self):
        """#290: keys start at frame 1 (1/24 s); exported without slide-to-zero, an engine looping the clip over
        0..length held the first pose an extra frame every cycle. Read from the .glb itself, not through Blender."""
        p, rep = self.finish("biped", "--animate", "idle,walk")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        doc, _ = read_glb(self.d / "biped_out.glb")
        self.assertEqual(sorted(a["name"] for a in doc["animations"]), ["idle", "walk"])
        for a in doc["animations"]:
            for s in a["samplers"]:
                acc = doc["accessors"][s["input"]]
                self.assertAlmostEqual(acc["min"][0], 0.0, places=5, msg=f"{a['name']} starts at {acc['min'][0]} s")
            seconds = max(doc["accessors"][s["input"]]["max"][0] for s in a["samplers"])
            frames = FINISH_CONST[a["name"].upper() + "_FRAMES"]
            self.assertAlmostEqual(seconds, frames / FINISH_CONST["FPS"], places=4, msg=f"{a['name']} lasts {seconds} s")

    def hips_track(self, glb, bone):
        """{clip: [[x, y, z] world position of the bone's head per frame]} and the rest head, read back in Blender."""
        return self.probe("HIPS", '''
            src, bone = ARGV[:2]
            bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=src)
            arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
            ad = arm.animation_data or arm.animation_data_create()
            for t in ad.nla_tracks:
                for st in t.strips:        # Blender 4.2 names actions "<clip>_<armature>"; the track keeps the clip
                    if st.action is not None and t.name not in bpy.data.actions:
                        st.action.name = t.name
                t.mute = True
            out = {}
            for act in bpy.data.actions:
                ad.action = act
                if hasattr(ad, "action_slot") and ad.action_slot is None:
                    slots = list(getattr(ad, "action_suitable_slots", [])) or list(getattr(act, "slots", []))
                    if slots:
                        ad.action_slot = slots[0]
                f0, f1 = (int(round(f)) for f in act.frame_range)
                track = []
                for f in range(f0, f1 + 1):
                    bpy.context.scene.frame_set(f)
                    track.append(list(arm.matrix_world @ arm.pose.bones[bone].head))
                out[act.name] = track
            rest = list(arm.matrix_world @ arm.data.bones[bone].head_local)
            print("HIPS" + json.dumps({"clips": out, "rest": rest}))
        ''', [glb, bone])

    def test_an_offset_in_place_clip_is_recentred(self):
        """Live Tripo run (2026-11-11): animate_in_place clips came back with mixamorig:Hips 1.4 m (walk) and 2.8 m
        (run) sideways in every key, idle at 0. rig_finish removes the mean horizontal offset and keeps the wobble
        and the bob; a clip already in place and a clip that travels (root motion) are left as they are."""
        p, rep = self.finish("offset", "--names", "keep")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        before = self.hips_track(self.d / "offset.glb", "b0")
        after = self.hips_track(self.d / "offset_out.glb", "b0")
        rest = after["rest"]
        for clip in ("walk", "idle", "run"):
            self.assertIn(clip, after["clips"], sorted(after["clips"]))
            a, b = after["clips"][clip], before["clips"][clip]
            self.assertEqual(len(a), len(b), clip)
            mean_a = [sum(p[i] for p in a) / len(a) for i in range(3)]
            mean_b = [sum(p[i] for p in b) / len(b) for i in range(3)]
            for pa, pb in zip(a, b):
                for i in range(2):     # the wobble around the mean is unchanged
                    self.assertAlmostEqual(pa[i] - mean_a[i], pb[i] - mean_b[i], delta=1e-4, msg=clip)
                self.assertAlmostEqual(pa[2], pb[2], delta=1e-4, msg=f"{clip}: the bob changed")
            if clip == "walk":
                off = math.hypot(mean_a[0] - rest[0], mean_a[1] - rest[1])
                self.assertLess(off, 1e-3, f"walk still stands {off:.4f} m from its rest spot")
            else:                      # untouched
                for pa, pb in zip(a, b):
                    for i in range(3):
                        self.assertAlmostEqual(pa[i], pb[i], delta=1e-4, msg=f"{clip} was changed")
        self.assertIn("walk: re-centred 1.36 m", p.stdout)                   # |(0.4, 1.3)|
        rc = rep.get("recentred", {})
        self.assertEqual(rc.get("walk", {}).get("action"), "recentred", rep)
        self.assertEqual(rc.get("idle", {}).get("action"), "in place", rep)
        self.assertTrue(rc.get("run", {}).get("action", "").startswith("left (travels"), rep)
        self.assertIn("run: b0 travels 1.50 m", p.stdout)

    def test_a_root_sampled_above_the_hips_does_not_hide_them(self):
        """A glTF round trip gives every bone location keys (all 0 for one that never moves). With a ground-level root
        above the hips, that root was taken for the hips and found "in place" while the hips stood 1.4 m off; and a
        parent with keys that never change counted as animated. The hips are the root-most bone whose keys move."""
        p, rep = self.finish("offset_root", "--names", "keep")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        rc = rep.get("recentred", {})
        self.assertEqual(rc.get("walk", {}).get("action"), "recentred", rc)
        self.assertEqual(rc.get("walk", {}).get("bone"), "b0", rc)
        self.assertEqual(rc.get("idle", {}).get("action"), "in place", rc)
        after = self.hips_track(self.d / "offset_root_out.glb", "b0")
        a, rest = after["clips"]["walk"], after["rest"]
        mean = [sum(p[i] for p in a) / len(a) for i in range(2)]
        self.assertLess(math.hypot(mean[0] - rest[0], mean[1] - rest[1]), 1e-3, "walk still stands off its rest spot")

    def test_a_clip_keyed_at_30_fps_keeps_its_loop_and_its_length(self):
        """#292: Tripo keys at 30 fps. In Blender's 24 fps scene those keys sit every 0.8 frames and the exporter,
        sampling whole frames, wrote the last frame 0.8 frames short of the key that closed the loop (and a length
        rounded to 24ths). The finished clip must end where it starts and last exactly as long as it did."""
        p, rep = self.finish("thirty", "--names", "keep")
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        self.assertEqual(rep.get("fps"), 30, rep)
        self.assertIn("clips keyed at 30 fps", p.stdout)
        doc, binary = read_glb(self.d / "thirty_out.glb")
        walk = next(a for a in doc["animations"] if a["name"] == "walk")
        seconds = THIRTY_FRAMES / 30
        for s in walk["samplers"]:
            times = accessor_floats(doc, binary, s["input"])
            self.assertAlmostEqual(times[0], 0.0, places=5)
            self.assertAlmostEqual(times[-1], seconds, places=4, msg=f"the clip lasts {times[-1]} s, not {seconds}")
            vals = accessor_floats(doc, binary, s["output"])
            seam = max(abs(x - y) for x, y in zip(vals[0], vals[-1]))
            self.assertLess(seam, 1e-4, f"a channel ends {seam} away from where it starts: the loop does not close")

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

    def names_of(self, glb):
        return self.probe("NAMES", '''
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=ARGV[0])
            arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
            print("NAMES" + json.dumps({b.name: round(b.head_local.z, 2) for b in arm.data.bones}))
        ''', [glb])

    def test_hips_are_the_pelvis_not_a_ground_root(self):
        """#216: the bone both legs hang from is Hips; a ground-level root above it keeps its own name."""
        p, rep = self.finish("ground")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        names = self.names_of(self.d / "ground_out.glb")
        self.assertEqual(names["mixamorig:Hips"], 0.9)          # the pelvis bone's head, not the ground root's
        self.assertIn("g", names)

    def test_backward_or_sideways_models_are_refused(self):
        """#216: a model facing backward would swap left and right; one facing sideways spreads its arms along Y."""
        p, rep = self.finish("backward")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("feet point +Y" in f for f in rep["failures"]), rep)
        p, rep = self.finish("sideways")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("spread along Y" in f for f in rep["failures"]), rep)

    def test_a_short_arm_is_refused_for_mixamo_names_only(self):
        """#216: a 2-bone arm gets no guessed Mixamo roles; --names keep still rigs it."""
        p, rep = self.finish("short")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("upper arm, forearm and hand" in f for f in rep["failures"]), rep)
        p, rep = self.finish("short", "--names", "keep")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])

    def test_a_partly_mixamo_named_rig_is_refused(self):
        """#216: one mixamorig: bone does not make the rig Mixamo-named."""
        p, rep = self.finish("partial")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(any("partly Mixamo-named" in f for f in rep["failures"]), rep)

    def test_the_rig_is_bent_and_must_move_the_mesh(self):
        """#223: rig_finish poses the rig; a skinned mesh that does not follow the bones fails."""
        p, rep_ = self.finish("biped")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:])
        self.assertGreater(rep_["deform_max_share"], 0.02)
        on, off = self.probe("DEFORM", f'''
            sys.path.insert(0, {str(HERE)!r})
            import rig_finish as rf
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath={str(self.d / "biped.glb")!r})
            arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
            meshes = [o for o in bpy.data.objects if o.type == "MESH"]
            on = rf.deform_check(arm, meshes)
            for o in meshes:
                for md in o.modifiers:
                    md.show_viewport = False          # the armature no longer moves the mesh
            off = rf.deform_check(arm, meshes)
            print("DEFORM" + json.dumps([on, off]))
        ''', [])
        self.assertGreater(on, 0.02)
        self.assertLess(off, 0.001)

    def test_nan_and_negative_weights_fail(self):
        """#208: NaN, infinite and negative weights fail (Blender clamps weights it stores, so the check is driven
        with stand-in mesh data in Blender's Python)."""
        res = self.probe("WEIGHTS", f'''
            sys.path.insert(0, {str(HERE)!r})
            import rig_finish as rf
            class G:
                def __init__(s, i, w): s.group, s.weight = i, w
            class V:
                def __init__(s, gs): s.groups = gs
            class VG:
                def __init__(s, i, n): s.index, s.name = i, n
            class Mesh:
                def __init__(s, verts): s.vertex_groups = [VG(i, f"b{{i}}") for i in range(5)]; s.data = type("D", (), {{"vertices": verts}})
            class Bone:
                def __init__(s, n): s.name = n
            arm = type("A", (), {{"data": type("AD", (), {{"bones": [Bone(f"b{{i}}") for i in range(5)]}})}})
            out = {{}}
            for label, extra in (("nan", float("nan")), ("neg", -0.5), ("inf", float("inf")), ("ok", None)):
                verts = [V([G(i % 5, 1.0)] + ([G((i + 1) % 5, extra)] if extra is not None else [])) for i in range(50)]
                rep = rf.check_weights(arm, [Mesh(verts)])
                out[label] = [rep["nan"], rep["failures"]]
            print("WEIGHTS" + json.dumps(out))
        ''', [])
        for label in ("nan", "neg", "inf"):
            self.assertEqual(res[label][0], 50, label)
            self.assertTrue(any("NaN, infinite or negative" in f for f in res[label][1]), (label, res[label]))
        self.assertEqual(res["ok"][0], 0)
        self.assertEqual(res["ok"][1], [])


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=1)
