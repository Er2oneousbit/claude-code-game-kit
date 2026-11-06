#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_shader_ports.py
# Purpose : Exam for the kit's shader ports: every engine skeleton that carries generated shader files has them
#           current with the recipes (tools/shaders/ksl + recipes.json via shader_gen.py), and the generator's
#           translations keep their promises (HLSL and WGSL types and builtins, one-argument vectors, no unbalanced
#           text, no placeholder-looking text the scaffolder would trip on).
# Usage   : python scripts/test_shader_ports.py
# Exit    : 0 all pass, 1 a case failed
# Notes   : Standard library only. Rendering the ports is each engine's `dev.py smoke --shaders` (real toolchains);
#           this exam checks what can be checked without them.
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "core" / "tools" / "shaders"))
import shader_gen as sg  # noqa: E402


class ShaderPortsExam(unittest.TestCase):
    def test_skeleton_ports_are_current(self):
        checked = 0
        for engine, rel in sg.ENGINE_DIRS.items():
            folder = KIT / "engines" / engine / "skeleton" / rel
            if not folder.is_dir():
                continue
            with self.subTest(engine=engine):
                self.assertEqual(sg.write_or_check(engine, folder, True), [], f"run shader_gen.py --engine {engine}")
                checked += 1
        self.assertGreater(checked, 0)

    def test_every_engine_generates(self):
        recipes = sg.load()
        for engine in sg.ENGINE_DIRS:
            with self.subTest(engine=engine):
                files = sg.files_for(engine, recipes)
                self.assertTrue(files)
                for text in files.values():
                    self.assertIsNone(re.search(r"\{\{[A-Z_]+\}\}", text), "placeholder-looking text")
                    self.assertEqual(text.count("("), text.count(")"))

    def test_translations(self):
        self.assertEqual(sg.to_hlsl("vec3 a = vec3(1.0);"), "float3 a = ((float3)(1.0));")
        self.assertEqual(sg.to_hlsl("vec2 p = fract(vec2(u, v));"), "float2 p = frac(float2(u, v));")
        self.assertEqual(sg.to_hlsl("x = mix(a, b, 0.5);"), "x = lerp(a, b, 0.5);")
        self.assertEqual(sg.to_wgsl("vec3 n = vec3(1.0);"), "var n: vec3<f32> = vec3<f32>(1.0);")
        self.assertEqual(sg.to_wgsl("float k = u_amount;"), "var k: f32 = params.amount;")

    def test_mz_plugin_shape(self):
        # RPG Maker MZ's plugin: an MZ annotation, the two JSON blocks tools/shader_render.mjs and
        # tools/shader_compile.mjs read, and every filter scaled by PIXI's padded input
        text = sg.files_for("rpgmaker-mz", sg.load())["KitShaders.js"]
        self.assertIn("@target MZ", text)
        blocks = {}
        for name in ("KIT_SHADERS", "KIT_FRAGMENTS"):
            m = re.search(name + r" = (\{[\s\S]*?\n\});", text)
            self.assertIsNotNone(m, name)
            blocks[name] = json.loads(m.group(1))
        self.assertEqual(sorted(blocks["KIT_SHADERS"]), sorted(blocks["KIT_FRAGMENTS"]))
        for name, src in blocks["KIT_FRAGMENTS"].items():
            with self.subTest(recipe=name):
                self.assertIn("p * outputFrame.zw * inputSize.zw", src)
                self.assertIn("vTextureCoord * inputSize.xy / outputFrame.zw", src)

    def test_bevy_wesl_and_rust_agree(self):
        # Bevy 0.20 has no naga_oil: WESL with its imports first, constants:: for the bind group; the Rust params
        # struct must list the WESL struct's fields in the same order (encase lays it out from the Rust side)
        recipes = sg.load()
        files = sg.files_for("bevy", recipes)
        rust = files["src/kit_shaders.rs"]
        for r in recipes:
            with self.subTest(recipe=r["name"]):
                wesl = files[f"assets/shaders/kit/{r['name']}.wesl"]
                self.assertTrue(wesl.startswith("import bevy_sprite_render::mesh2d::vertex_output::VertexOutput;"))
                self.assertNotIn("#import", wesl)
                self.assertNotIn("#{", wesl)
                wesl_fields = re.findall(r"^    (\w+): ", re.search(r"struct KitParams \{\n(.*?)\n\}", wesl, re.S).group(1),
                                         re.M)
                camel = "".join(part.capitalize() for part in r["name"].split("_"))
                body = re.search(r"pub struct %sParams \{\n(.*?)\n\}" % camel, rust, re.S).group(1)
                self.assertEqual(re.findall(r"pub (\w+): ", body), wesl_fields)
                self.assertIn(f'"shaders/kit/{r["name"]}.wesl".into()', rust)
                self.assertIn(f"Material2dPlugin::<{camel}Material>::default()", rust)
                self.assertEqual("pub aux: Handle<Image>" in re.search(
                    r"pub struct %sMaterial \{(.*?)\n\}" % camel, rust, re.S).group(1), bool(r["aux"]))

    def test_check_reports_stale_files(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            self.assertEqual(sg.write_or_check("godot", out, False), [])
            self.assertEqual(sg.write_or_check("godot", out, True), [])
            (out / "flash.gdshader").write_text("changed", encoding="utf-8")
            self.assertEqual([p.name for p in sg.write_or_check("godot", out, True)], ["flash.gdshader"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
