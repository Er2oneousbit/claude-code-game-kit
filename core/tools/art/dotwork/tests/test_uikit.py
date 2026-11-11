#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# test_uikit.py
# Purpose : exam for the UI kit lane (lane_uikit): the Theme holds every state of every menu Control (parsed from the
#           .tres, every texture it names exists), focus looks different from hover on every focusable control
#           (composited from the shipped textures and compared pixel by pixel), every prompt glyph name exists as a
#           16 px tall PNG that matches glyphs.json, keycaps carry ink, gamepad glyphs light the right part, the
#           cursors and the preview scene's focus chain, --engine none, and spec errors exit 2. No Godot, no models.
# Usage   : python -I -B tools/art/dotwork/tests/test_uikit.py
#           (DOTWORK_TEST_DIR=<another dotwork folder> runs the same exam against that copy)
# Exit    : 0 all pass, 1 a case failed
# Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
# ---------------------------------------------------------------------------
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTWORK = os.environ.get("DOTWORK_TEST_DIR") or os.path.dirname(HERE)
sys.path.insert(0, DOTWORK)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

# Every Theme item the kit's menus need, written out here on purpose (not imported from the lane), per type.
REQUIRED = {
    "Button": {"styles": ["normal", "hover", "pressed", "disabled", "focus"],
               "colors": ["font_color", "font_hover_color", "font_pressed_color", "font_focus_color",
                          "font_disabled_color"]},
    "CheckBox": {"styles": ["normal", "hover", "pressed", "disabled", "focus"],
                 "icons": ["checked", "unchecked", "checked_disabled", "unchecked_disabled", "radio_checked",
                           "radio_unchecked", "radio_checked_disabled", "radio_unchecked_disabled"],
                 "colors": ["font_color", "font_hover_color", "font_pressed_color", "font_focus_color",
                            "font_disabled_color"]},
    "CheckButton": {"styles": ["normal", "hover", "pressed", "disabled", "focus"],
                    "icons": ["checked", "unchecked", "checked_disabled", "unchecked_disabled"],
                    "colors": ["font_color", "font_hover_color", "font_pressed_color", "font_focus_color",
                               "font_disabled_color"]},
    "HSlider": {"styles": ["slider", "grabber_area", "grabber_area_highlight"],
                "icons": ["grabber", "grabber_highlight", "grabber_disabled"]},
    "VSlider": {"styles": ["slider", "grabber_area", "grabber_area_highlight"],
                "icons": ["grabber", "grabber_highlight", "grabber_disabled"]},
    "OptionButton": {"styles": ["normal", "hover", "pressed", "disabled", "focus"], "icons": ["arrow"],
                     "colors": ["font_color", "font_hover_color", "font_focus_color", "font_disabled_color"]},
    "PopupMenu": {"styles": ["panel", "hover", "separator"],
                  "icons": ["checked", "unchecked", "radio_checked", "radio_unchecked", "submenu"],
                  "colors": ["font_color", "font_hover_color", "font_disabled_color"]},
    "HScrollBar": {"styles": ["scroll", "scroll_focus", "grabber", "grabber_highlight", "grabber_pressed"]},
    "VScrollBar": {"styles": ["scroll", "scroll_focus", "grabber", "grabber_highlight", "grabber_pressed"]},
    "TabContainer": {"styles": ["tab_selected", "tab_unselected", "tab_hovered", "tab_disabled", "tab_focus", "panel"],
                     "colors": ["font_selected_color", "font_hovered_color", "font_unselected_color",
                                "font_disabled_color"]},
    "TabBar": {"styles": ["tab_selected", "tab_unselected", "tab_hovered", "tab_disabled", "tab_focus"],
               "colors": ["font_selected_color", "font_hovered_color", "font_unselected_color", "font_disabled_color"]},
    "LineEdit": {"styles": ["normal", "focus", "read_only"],
                 "colors": ["caret_color", "selection_color", "font_color", "font_uneditable_color"]},
    "SpinBox": {"icons": ["updown"]},
    "TooltipPanel": {"styles": ["panel"]},
    "TooltipLabel": {"colors": ["font_color"]},
    "ItemList": {"styles": ["panel", "focus", "selected", "selected_focus", "hovered", "cursor"],
                 "colors": ["font_color", "font_hovered_color", "font_selected_color"]},
    "ProgressBar": {"styles": ["background", "fill"]},
    "Label": {"colors": ["font_color"]},
    "Panel": {"styles": ["panel"]},
    "PanelContainer": {"styles": ["panel"]},
    "HSeparator": {"styles": ["separator"]},
    "VSeparator": {"styles": ["separator"]},
}

# The prompt art names the kit's glyph_name() can return for its bindings (ui_glyph_spec, 2026-11-01), plus unknown
# and the extras this lane promises.
KEY_NAMES = (["space", "escape", "enter", "up", "down", "left", "right", "shift", "tab", "backspace", "ctrl", "alt"]
             + list("abcdefghijklmnopqrstuvwxyz") + list("0123456789") + [f"f{n}" for n in range(1, 13)])
EXPECTED = (["key_" + k for k in KEY_NAMES] + ["mouse_left", "mouse_right", "mouse_middle", "unknown"]
            + ["xbox_" + n for n in ("a", "b", "x", "y", "lb", "rb", "lt", "rt", "menu", "view", "dpad_up",
                                      "dpad_down", "dpad_left", "dpad_right", "lstick", "rstick")]
            + ["ps_" + n for n in ("cross", "circle", "square", "triangle", "l1", "r1", "l2", "r2", "options", "share",
                                    "dpad_up", "dpad_down", "dpad_left", "dpad_right", "lstick", "rstick")]
            + ["pad_" + n for n in ("south", "east", "west", "north", "l1", "r1", "l2", "r2", "start", "select",
                                     "dpad_up", "dpad_down", "dpad_left", "dpad_right", "lstick", "rstick")])
LIT = (255, 204, 64)        # the lane's highlight colour for the lit part of a glyph
FOCUSABLE_BUTTONS = ("Button", "OptionButton", "CheckBox", "CheckButton")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def make_project(tmp):
    os.makedirs(os.path.join(tmp, "art_src", "dotwork"), exist_ok=True)
    with open(os.path.join(tmp, "project.godot"), "w") as f:
        f.write("config_version=5\n")


def run_dotwork(*argv):
    import dotwork
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dotwork.main(list(argv))
    return code, out.getvalue() + err.getvalue()


def pack(tmp, spec, *extra):
    p = os.path.join(tmp, "spec.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    return run_dotwork("pack", "--spec", p, "--project", tmp, "--no-verify", *extra)


class Tres:
    """A Theme .tres read independently of the lane: ext resources (id -> res path), sub resources (id -> type and
    properties) and the theme items {type: {kind: {item: raw value}}}."""

    def __init__(self, text):
        self.ext = dict((m.group(2), m.group(1)) for m in
                        re.finditer(r'\[ext_resource type="\w+" path="([^"]+)" id="([^"]+)"\]', text))
        self.sub = {}
        for m in re.finditer(r'\[sub_resource type="(\w+)" id="([^"]+)"\]\n(.*?)\n\n', text + "\n\n", re.S):
            props = dict(l.split(" = ", 1) for l in m.group(3).splitlines() if " = " in l)
            self.sub[m.group(2)] = (m.group(1), props)
        self.items = {}
        for line in text.split("\n[resource]\n", 1)[1].splitlines():
            m = re.match(r"^(\w+)/(\w+)/(\w+) = (.+)$", line)
            if m:
                self.items.setdefault(m.group(1), {}).setdefault(m.group(2), {})[m.group(3)] = m.group(4)
        self.head = text.splitlines()[0]
        self.text = text


class UikitExam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dotwork_uikit_")
        make_project(cls.tmp)
        cls.code, cls.out = pack(cls.tmp, {
            "name": "menus",
            "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt"}],
            "uikit": [{"name": "menu", "style": "iron", "font": "assets/art/ui/fonts/font_dialogue.fnt",
                       "keys": ["minus", "key_f13", "kp_1", "period"]},
                      {"name": "keep", "style": "brass", "scale": 3},
                      {"name": "own", "fill": ["2a5a30", "163a1c"], "frame": ["0a140c", "d8f0c0", "7ab060"]}]})
        cls.ui = os.path.join(cls.tmp, "assets", "ui")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.assertEqual(self.code, 0, self.out)

    def theme(self, name):
        return Tres(read(os.path.join(self.ui, f"theme_{name}.tres")))

    def res_file(self, res):
        self.assertTrue(res.startswith("res://"), res)
        return os.path.join(self.tmp, *res[len("res://"):].split("/"))

    def tex_of(self, th, value):
        """(1x-agnostic RGBA array, texture margin px, expand px) for a StyleBoxTexture SubResource value, None for
        StyleBoxEmpty; icons (ExtResource) give margin 0."""
        m = re.match(r'(Sub|Ext)Resource\("([^"]+)"\)', value)
        self.assertIsNotNone(m, value)
        if m.group(1) == "Ext":
            return np.array(Image.open(self.res_file(th.ext[m.group(2)])).convert("RGBA")), 0, 0
        kind, props = th.sub[m.group(2)]
        if kind != "StyleBoxTexture":
            return None
        tid = re.match(r'ExtResource\("([^"]+)"\)', props["texture"]).group(1)
        a = np.array(Image.open(self.res_file(th.ext[tid])).convert("RGBA"))
        return a, int(float(props["texture_margin_left"])), int(float(props.get("expand_margin_left", "0")))

    # ---- the Theme
    def test_theme_every_type_every_state(self):
        for name in ("menu", "keep", "own"):
            th = self.theme(name)
            for typ, kinds in REQUIRED.items():
                for kind, items in kinds.items():
                    for item in items:
                        self.assertIn(item, th.items.get(typ, {}).get(kind, {}), f"{name}: {typ}/{kind}/{item}")
            # every resource the theme names exists, every SubResource it uses is defined, load_steps counts them
            for res in th.ext.values():
                self.assertTrue(os.path.isfile(self.res_file(res)), res)
            for typ in th.items.values():
                for kind in typ.values():
                    for v in kind.values():
                        m = re.match(r'(Sub|Ext)Resource\("([^"]+)"\)', v)
                        if m:
                            self.assertIn(m.group(2), th.sub if m.group(1) == "Sub" else th.ext, v)
            self.assertEqual(th.head, f'[gd_resource type="Theme" load_steps={len(th.ext) + len(th.sub) + 1} format=3]')
            # every colour is a real Color() and states read differently
            btn = th.items["Button"]["colors"]
            self.assertTrue(all(v.startswith("Color(") for v in btn.values()))
            self.assertEqual(len({btn["font_color"], btn["font_hover_color"], btn["font_focus_color"],
                                  btn["font_disabled_color"]}), 4)
        menu = self.theme("menu")
        self.assertEqual(menu.ext[re.match(r'ExtResource\("([^"]+)"\)', [l for l in menu.text.splitlines()
                                            if l.startswith("default_font = ")][0][15:]).group(1)],
                         "res://assets/art/ui/fonts/font_dialogue.fnt")
        self.assertIn("default_font_size = 18", menu.text)                     # the .fnt's size (9 rows x 2)
        self.assertNotIn("default_font", self.theme("keep").text)
        # scale 3: the nine-patch margins grow with it
        keep = self.theme("keep")
        _, m3, e3 = self.tex_of(keep, keep.items["Button"]["styles"]["focus"])
        _, m2, e2 = self.tex_of(menu, menu.items["Button"]["styles"]["focus"])
        self.assertEqual((m3, e3, m2, e2), (9, 6, 6, 4))

    def test_textures_drawn_at_scale(self):
        d = os.path.join(self.tmp, "assets", "art", "ui", "uikit")
        for name, s in (("menu", 2), ("keep", 3)):
            a = np.array(Image.open(os.path.join(d, name, "button_normal.png")))
            self.assertEqual(a.shape[:2], (12 * s, 12 * s))                    # 12 px slim button at 1x
            self.assertTrue((a[::s, ::s] == a[s - 1::s, s - 1::s]).all())     # whole-pixel blocks, no smoothing

    # ---- focus vs hover, pixel by pixel
    @staticmethod
    def nine(a, m, w, h):
        H, W = a.shape[:2]
        ys = [y if y < m else (H - (h - y) if y >= h - m else m + (y - m) % max(1, H - 2 * m)) for y in range(h)]
        xs = [x if x < m else (W - (w - x) if x >= w - m else m + (x - m) % max(1, W - 2 * m)) for x in range(w)]
        return a[np.ix_(ys, xs)]

    def draw_box(self, canvas, th, value, rect):
        """Godot's StyleBoxTexture draw: the nine-patch over rect grown by its expand margin, alpha over."""
        t = self.tex_of(th, value)
        if t is None:
            return
        a, m, e = t
        x, y, w, h = rect
        x, y, w, h = x - e, y - e, w + 2 * e, h + 2 * e
        src = self.nine(a, m, w, h).astype(np.float32)
        dst = canvas[y:y + h, x:x + w].astype(np.float32)
        al = src[..., 3:4] / 255
        dst[..., :3] = src[..., :3] * al + dst[..., :3] * (1 - al)
        canvas[y:y + h, x:x + w] = dst.astype(np.uint8)

    def look(self, th, layers, w=120, h=48):
        """Composite (style item value, rect) layers on the panel colour: one control state as Godot draws it."""
        c = np.zeros((h + 40, w + 40, 4), np.uint8)
        c[...] = (40, 44, 52, 255)
        for value, rect in layers:
            self.draw_box(c, th, value, (rect[0] + 20, rect[1] + 20, rect[2], rect[3]))
        return c

    def assert_differs(self, a, b, what):
        diff = (np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 24)
        self.assertGreater(int(diff.sum()), 150, f"{what}: focus and hover look alike ({int(diff.sum())} px differ)")

    def test_focus_differs_from_hover(self):
        for name in ("menu", "keep", "own"):
            th = self.theme(name)
            box = (0, 0, 120, 48)
            st = lambda t, i: th.items[t]["styles"][i]
            for typ in FOCUSABLE_BUTTONS:   # Button: the state box, then the focus box on top when focused
                hover = self.look(th, [(st(typ, "hover"), box)])
                focus = self.look(th, [(st(typ, "normal"), box), (st(typ, "focus"), box)])
                self.assert_differs(hover, focus, f"{name} {typ}")
                # hovered while focused still shows the ring, so a mouse never hides the gamepad's place
                both = self.look(th, [(st(typ, "hover"), box), (st(typ, "focus"), box)])
                self.assert_differs(hover, both, f"{name} {typ} hover+focus")
            # LineEdit (and SpinBox's field): no hover box; focus draws over normal
            self.assert_differs(self.look(th, [(st("LineEdit", "normal"), box)]),
                                self.look(th, [(st("LineEdit", "normal"), box), (st("LineEdit", "focus"), box)]),
                                f"{name} LineEdit")
            for typ in ("TabBar", "TabContainer"):   # a hovered tab vs the current tab with the focus box
                tab = (0, 0, 60, 24)
                self.assert_differs(self.look(th, [(st(typ, "tab_hovered"), tab)]),
                                    self.look(th, [(st(typ, "tab_selected"), tab), (st(typ, "tab_focus"), tab)]),
                                    f"{name} {typ}")
            for typ, grab in (("HScrollBar", (40, 0, 40, 16)), ("VScrollBar", (0, 10, 16, 28))):
                track = (0, 0, 120, 16) if typ[0] == "H" else (0, 0, 16, 48)
                hover = self.look(th, [(st(typ, "scroll"), track), (st(typ, "grabber_highlight"), grab)])
                focus = self.look(th, [(st(typ, "scroll_focus"), track), (st(typ, "grabber"), grab)])
                self.assert_differs(hover, focus, f"{name} {typ}")
            row = (4, 4, 112, 14)
            hover = self.look(th, [(st("ItemList", "panel"), box), (st("ItemList", "hovered"), row)])
            focus = self.look(th, [(st("ItemList", "panel"), box), (st("ItemList", "focus"), box),
                                   (st("ItemList", "selected_focus"), row), (st("ItemList", "cursor"), row)])
            self.assert_differs(hover, focus, f"{name} ItemList")
            # sliders: Godot draws one highlight for hover and focus, so the theme can only make it unmistakable
            for typ in ("HSlider", "VSlider"):
                g = self.tex_of(th, th.items[typ]["icons"]["grabber"])[0]
                ghl = self.tex_of(th, th.items[typ]["icons"]["grabber_highlight"])[0]
                self.assertGreater(int((np.abs(g.astype(int) - ghl.astype(int)).sum(axis=2) > 24).sum()), 20, typ)

    def test_focus_ring_colour_is_its_own(self):
        # the ring's colour appears in no hover texture, so focus never reads as a brighter hover
        th = self.theme("menu")
        ring = self.tex_of(th, th.items["Button"]["styles"]["focus"])[0]
        ring_cols = {tuple(int(v) for v in p[:3]) for p in ring.reshape(-1, 4) if p[3] == 255}
        ring_cols.discard((20, 18, 28))
        self.assertTrue(ring_cols)
        for typ in FOCUSABLE_BUTTONS:
            hv = self.tex_of(th, th.items[typ]["styles"]["hover"])[0]
            hv_cols = {tuple(int(v) for v in p[:3]) for p in hv.reshape(-1, 4) if p[3] == 255}
            self.assertFalse(ring_cols & hv_cols, typ)

    # ---- glyphs
    def test_every_glyph_name(self):
        gdir = os.path.join(self.ui, "glyphs")
        index = json.loads(read(os.path.join(gdir, "glyphs.json")))
        want = set(EXPECTED) | {"key_minus", "key_f13", "key_kp_1", "key_period"}
        names = set(want)
        gv = os.path.join(DOTWORK, "..", "..", "golden_vectors.py")   # in a kit game: tools/golden_vectors.py
        if os.path.exists(gv):
            import importlib.util
            spec = importlib.util.spec_from_file_location("golden_vectors_for_uikit", gv)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "glyph_name"):
                binds = ["key:" + k for k in KEY_NAMES] + ["mouse:left", "mouse:right", "mouse:middle", "weird"]
                binds += ["pad:" + p for p in ("south", "east", "west", "north", "l1", "r1", "l2", "r2", "start",
                                               "select", "dpad_up", "dpad_down", "dpad_left", "dpad_right")]
                binds += ["pad_axis:leftx-", "pad_axis:lefty+", "pad_axis:rightx+", "pad_axis:righty-"]
                for gset in ("keyboard", "xbox", "playstation", "generic"):
                    names |= {mod.glyph_name(gset, b) for b in binds}
        self.assertTrue(names <= set(index), sorted(names - set(index)))
        files = {f[:-4] for f in os.listdir(gdir) if f.endswith(".png")}
        self.assertEqual(files, set(index))                                     # no PNG without a row, and back
        for n in names:
            a = np.array(Image.open(os.path.join(gdir, f"{n}.png")))
            self.assertEqual(a.shape[0], 16, n)
            self.assertEqual({"w": a.shape[1], "h": a.shape[0]}, index[n], n)
            self.assertGreater(int((a[..., 3] == 255).sum()), 40, n)
        w = lambda n: index[n]["w"]
        self.assertEqual(w("key_a"), 16)
        for k in ("space", "enter", "shift", "tab", "backspace"):
            self.assertGreater(w("key_" + k), 24, k)
        self.assertGreater(w("key_space"), w("key_tab"))

    def test_keycaps_carry_ink(self):
        gdir = os.path.join(self.ui, "glyphs")
        ink = lambda n: np.array(Image.open(os.path.join(gdir, f"{n}.png")).convert("RGBA"))
        for n in [x for x in EXPECTED if x.startswith("key_")] + ["unknown", "key_minus", "key_kp_1", "key_period"]:
            a = ink(n)
            face = a[2:11, 2:-2]                                                # the cap's top face, inside its rim
            dark = (face[..., :3].astype(int).sum(axis=2) < 200) & (face[..., 3] == 255)
            self.assertGreaterEqual(int(dark.sum()), 4, f"{n}: no label ink on the keycap")
        self.assertFalse(np.array_equal(ink("key_a"), ink("key_b")))
        self.assertFalse(np.array_equal(ink("key_up"), ink("key_down")))
        for d in ("up", "down"):                                                 # arrows are drawn, symmetric
            a = ink("key_" + d)[2:11, 2:-2]
            m = (a[..., :3].astype(int).sum(axis=2) < 200) & (a[..., 3] == 255)
            ys, xs = np.where(m)
            m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            self.assertTrue(np.array_equal(m, m[:, ::-1]), d)
            self.assertEqual(int((m[0] if d == "up" else m[-1]).sum()), 1, d)   # the tip points the named way

    def test_gamepad_and_mouse_light_the_named_part(self):
        gdir = os.path.join(self.ui, "glyphs")
        lit = lambda n: (np.abs(np.array(Image.open(os.path.join(gdir, f"{n}.png")).convert("RGBA"))[..., :3].astype(int)
                                - LIT).sum(axis=2) < 10)
        for pre in ("xbox", "ps", "pad"):
            for d, (rows, cols) in {"up": (slice(0, 6), slice(4, 11)), "down": (slice(10, 16), slice(4, 11)),
                                    "left": (slice(4, 11), slice(0, 6)), "right": (slice(4, 11), slice(10, 16))}.items():
                m = lit(f"{pre}_dpad_{d}")
                self.assertGreater(int(m[rows, cols].sum()), 5, f"{pre}_dpad_{d}")
                self.assertEqual(int(m.sum()), int(m[rows, cols].sum()), f"{pre}_dpad_{d}: other arms lit")
        for pos, (rows, cols) in {"north": (slice(0, 6), slice(5, 11)), "south": (slice(10, 16), slice(5, 11)),
                                  "west": (slice(5, 11), slice(0, 6)), "east": (slice(5, 11), slice(10, 16))}.items():
            m = lit(f"pad_{pos}")
            self.assertGreater(int(m[rows, cols].sum()), 10, pos)
            self.assertEqual(int(m.sum()), int(m[rows, cols].sum()), pos)
        ml, mr, mm = lit("mouse_left"), lit("mouse_right"), lit("mouse_middle")
        self.assertGreater(int(ml[:, :5].sum()), 8)
        self.assertEqual(int(ml[:, 6:].sum()), 0)
        self.assertGreater(int(mr[:, 6:].sum()), 8)
        self.assertEqual(int(mr[:, :5].sum()), 0)
        self.assertEqual(int(mm.sum()), 3)                                     # only the wheel
        # face buttons: four different drawings per family, and no family reuses another's art
        img = lambda n: np.array(Image.open(os.path.join(gdir, f"{n}.png")))
        for fam in (["xbox_a", "xbox_b", "xbox_x", "xbox_y"], ["ps_cross", "ps_circle", "ps_square", "ps_triangle"],
                    ["xbox_lb", "xbox_lt", "ps_l1", "ps_l2"], ["xbox_menu", "xbox_view", "ps_share", "pad_start",
                                                               "pad_select"], ["pad_lstick", "pad_rstick"]):
            arr = [img(n).tobytes() for n in fam]
            self.assertEqual(len(set(arr)), len(fam), fam)
        self.assertFalse(np.array_equal(img("ps_cross"), img("xbox_x")))

    # ---- cursors, preview scene, review sheet
    def test_cursors(self):
        p, s = (np.array(Image.open(os.path.join(self.ui, f"cursor_{k}.png"))) for k in ("pointer", "select"))
        self.assertEqual(p.shape[:2], (36, 24))                                 # 12 x 18 at the first entry's x2
        self.assertEqual(tuple(p[0, 0, :3]), (20, 18, 28))                      # the tip is the hotspot (0, 0)
        self.assertGreater(s.shape[1], s.shape[0])                              # the hand points sideways
        cols = {tuple(int(v) for v in px[:3]) for px in s.reshape(-1, 4) if px[3] == 255}
        self.assertIn((255, 255, 255), cols)                                    # white glove...
        self.assertTrue(any(sum(c) < 200 for c in cols))                        # ...with a dark outline
        man = json.loads(read(os.path.join(self.tmp, "assets_src", "dotwork", "manifest_menus.json")))
        hot = {r["file"].rsplit("/", 1)[-1]: r["hotspot"] for r in man["assets"] if r["kind"] == "ui_cursor"}
        self.assertEqual(hot["cursor_pointer.png"], [0, 0])
        hx, hy = hot["cursor_select.png"]
        self.assertGreater(s[hy, hx - 1, 3], 0)                                 # the fingertip is inked
        self.assertGreaterEqual(hx, s.shape[1] - 2)

    def test_preview_scene_chain(self):
        text = read(os.path.join(self.ui, "uikit_preview_menu.tscn"))
        self.assertIn('[ext_resource type="Theme" path="res://assets/ui/theme_menu.tres" id="1_theme"]', text)
        types = set(re.findall(r'\[node name="\w+" type="(\w+)"', text))
        for typ in REQUIRED:
            if typ not in ("TooltipPanel", "TooltipLabel"):
                self.assertIn(typ if typ != "PanelContainer" else "PanelContainer", types | {"PanelContainer"}, typ)
        self.assertIn("tooltip_text", text)
        walk = re.search(r"metadata/dotwork_focus_walk = PackedStringArray\((.*)\)", text).group(1)
        walk = [w.strip().strip('"') for w in walk.split(",")]
        self.assertGreaterEqual(len(walk), 8)
        nodes = re.findall(r'\[node name="(\w+)" type="\w+" parent="Cols/Chain"\]\n(.*?)\n\n', text, re.S)
        order = [n for n, body in nodes if "focus_neighbor" in body]
        body = dict(nodes)
        for a, b in zip(order, order[1:]):                                      # chained top to bottom, both ways
            self.assertIn(f'focus_neighbor_bottom = NodePath("../{b}")', body[a])
            self.assertIn(f'focus_neighbor_top = NodePath("../{a}")', body[b])
        self.assertEqual(walk, [f"Cols/Chain/{n}" for n in order[:len(walk)]])
        for n in ("Gain", "Scroll", "Saves"):                                   # they eat ui_up / ui_down: after it
            self.assertGreater(order.index(n), len(walk) - 1)

    def test_review_sheet(self):
        p = os.path.join(self.tmp, "assets_src", "art", "ui", "uikit_menu_review.png")
        a = np.array(Image.open(p))
        self.assertGreater(a.shape[0], 600)
        self.assertGreater(len(np.unique(a.reshape(-1, a.shape[2]), axis=0)), 30)

    # ---- engine none and spec errors
    def test_engine_none_and_spec_errors(self):
        tmp = tempfile.mkdtemp(prefix="dotwork_uikit_none_")
        try:
            make_project(tmp)
            code, out = pack(tmp, {"name": "n", "uikit": [{"name": "menu", "style": "classic"}]}, "--engine", "none")
            self.assertEqual(code, 0, out)
            ui = os.path.join(tmp, "assets", "ui")
            self.assertFalse(os.path.exists(os.path.join(ui, "theme_menu.tres")))
            self.assertTrue(os.path.exists(os.path.join(ui, "glyphs", "key_space.png")))
            for bad, text in (({"name": "x", "style": "bras"}, "style 'bras' is not one of"),
                              ({"name": "x", "scale": 0}, "scale 0"),
                              ({"name": "x", "keys": "minus"}, "is a list of key names"),
                              ({"name": "x", "keys": ["../up"]}, "Godot key names use"),
                              ({"name": "x", "fill": ["zz0000", "000000"], "frame": ["000000", "ffffff"]}, "hex"),
                              ({"name": "x", "font": "assets/missing.fnt"}, "not found")):
                code, out = pack(tmp, {"name": "n", "uikit": [bad]})
                self.assertEqual(code, 2, out)
                self.assertIn(text, out)
                self.assertNotIn("unexpected failure", out)
            import dotwork
            self.assertTrue({"style", "fill", "frame", "focus", "scale", "font", "keys"} <= dotwork.entry_keys("uikit"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FontPathExam(unittest.TestCase):
    """A uikit "font" is found under the game's assets folder first, so the shipped example spec works in every
    layout: a web game keeps its fonts in public/assets/, where the old game-relative "assets/art/..." path missed
    them and the pack stopped with "not found" (exit 2)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dotwork_uikit_font_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def example(self):
        with open(os.path.join(DOTWORK, "examples", "uikit.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_example_spec_in_a_web_game(self):
        # a web game's layout, set the way the web overlay ships it: engine none, assets in public/assets
        os.makedirs(os.path.join(self.tmp, "art_src", "dotwork"))
        with open(os.path.join(self.tmp, "art_src", "dotwork", "dotwork.config.json"), "w", encoding="utf-8") as f:
            json.dump({"engine": "none", "project": {"assets_dir": "public/assets", "res_root": "res://public/assets"}}, f)
        with open(os.path.join(self.tmp, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# a web game\n")
        code, out = pack(self.tmp, self.example())
        self.assertEqual(code, 0, out)
        assets = os.path.join(self.tmp, "public", "assets")
        self.assertTrue(os.path.isfile(os.path.join(assets, "art", "ui", "fonts", "font_dialogue.fnt")))
        self.assertTrue(os.path.isfile(os.path.join(assets, "ui", "glyphs", "key_minus.png")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "assets")))

    def test_example_spec_in_a_godot_game(self):
        make_project(self.tmp)
        code, out = pack(self.tmp, self.example())
        self.assertEqual(code, 0, out)
        th = read(os.path.join(self.tmp, "assets", "ui", "theme_menu.tres"))
        self.assertIn('path="res://assets/art/ui/fonts/font_dialogue.fnt"', th)
        self.assertIn("default_font_size = 9", th)                         # the example's scale 1 font

    def test_game_relative_path_and_escape(self):
        make_project(self.tmp)
        spec = {"name": "f", "fonts": [{"name": "dialogue", "glyphs": "glyphs/dialogue.txt"}],
                "uikit": [{"name": "menu", "font": "assets/art/ui/fonts/font_dialogue.fnt"}]}
        code, out = pack(self.tmp, spec)                                   # older specs: relative to the game
        self.assertEqual(code, 0, out)
        spec["uikit"][0]["font"] = "../../outside.fnt"
        code, out = pack(self.tmp, spec)
        self.assertEqual(code, 2, out)
        self.assertIn("outside the game folder", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
