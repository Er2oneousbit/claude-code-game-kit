// ---------------------------------------------------------------------------
// GameKitCaptureTests.cs
// Purpose : A capture shows what a player sees (#277): the shell's panel (FrontEnd.NewPanel) with known HUD labels and
//           translucent panels, laid over a camera's picture on the CPU (UiCapture, as GameKitCapture and the F8 report
//           do), must match the same panel drawn by the GPU over the same picture, the way it draws on the screen.
// Usage   : python tools/dev.py smoke --graphics --filter Capture      (also part of every smoke run with a device)
// Notes   : Needs a graphics device: ignored under -nographics (dev.py test, smoke without --graphics or a capture).
//           The GPU's picture: the camera renders into a texture, then the panel draws into that same texture
//           without clearing for exactly one frame (one paint, read on the next update), as it draws on the back buffer. Works in Gamma and Linear projects
//           (the blend differs, the test compares against whatever the GPU does). The outlined HUD line is compared
//           pixel for pixel like the rest. Smoke_OutlinedTextKeepsItsColour (#283): an outlined label's letters show
//           UiTheme.TEXT over a white and a black game (UI Toolkit centres its outline on the glyph's edge, so
//           without the face copy they came out dark grey), the outline shows around them, and the access report
//           and the pseudo-locale check see each label once, in the colour on its letters. Opaque_*: the F8
//           screenshot of a windowed player drops the back buffer's alpha.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): outlined text keeps its colour, opaque screenshots (#283)
// ---------------------------------------------------------------------------
using System.Collections;
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.TestTools;
using UnityEngine.UIElements;
using graveyard_shift.Shell;

namespace graveyard_shift.Tests
{
    public class GameKitCaptureTests
    {
        private const int W = FrontEnd.REF_W;
        private const int H = FrontEnd.REF_H;
        private const int TOLERANCE = 2;            // the GPU and the CPU each round once
        private const int SETTLE_FRAMES = 10;       // layout and the first paint of the panel
        private static readonly Color CAMERA = new Color(0.2f, 0.4f, 0.6f);
        private static readonly Color HIT_FLASH = new Color(1.0f, 0.95f, 0.75f, 0.5f);   // JuiceWorld's "hit" at half
        private const int DARK = 40;                // an outline pixel over a white game: every channel at most this

        private GameObject _camera, _doc;
        private PanelSettings _panel;
        private RenderTexture _ui, _screen;

        [TearDown]
        public void TearDown()
        {
            if (_camera != null) Object.Destroy(_camera);
            if (_doc != null) Object.Destroy(_doc);
            if (_panel != null) Object.Destroy(_panel);
            if (_ui != null) _ui.Release();
            if (_screen != null) RenderTexture.ReleaseTemporary(_screen);
            _ui = null;
            _screen = null;
        }

        [Test]
        public void Panel_OnTheScreenKeepsTheCamerasPicture()
        {
            PanelSettings panel = FrontEnd.NewPanel();
            Assert.IsFalse(panel.clearColor, "a panel that clears the back buffer blacks out the game under the menus");
            Assert.IsNull(panel.targetTexture);
            Object.Destroy(panel);
        }

        [UnityTest]
        public IEnumerator Smoke_CaptureMatchesTheScreen()
        {
            if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
            {
                Assert.Ignore("needs a graphics device: python tools/dev.py smoke --graphics --filter Capture");
            }
            Camera cam = MakeCamera();
            PanelSettings panel = _panel = FrontEnd.NewPanel();
            bool onScreenClears = panel.clearColor;
            _ui = new RenderTexture(W, H, 0, RenderTextureFormat.ARGB32) { name = "CaptureTestUi" };
            _ui.Create();
            panel.targetTexture = _ui;               // as FrontEnd.SetWindow does in batchmode and for captures
            panel.clearColor = true;
            _doc = new GameObject("CaptureTestPanel");
            var doc = _doc.AddComponent<UIDocument>();
            doc.panelSettings = panel;
            Fill(doc.rootVisualElement);
            for (int i = 0; i < SETTLE_FRAMES; i++)
            {
                yield return null;
            }

            // The capture: the camera's picture, then the panel's texture laid over it on the CPU (what GameKitCapture
            // and the F8 report do for every panel; only this test's panel here)
            Texture2D captured = Render(cam);
            UiCapture.LayOver(captured, _ui);

            // The screen: the camera's picture in a texture, then the panel draws over it once, without a clear
            _screen = RenderTexture.GetTemporary(W, H, 24);
            cam.targetTexture = _screen;
            cam.Render();
            cam.targetTexture = null;
            panel.targetTexture = _screen;
            panel.clearColor = onScreenClears;
            yield return null;                       // this frame's paint draws the panel over it (no WaitForEndOfFrame
                                                     // in batchmode: the next update reads it)
            Texture2D screen = Read(_screen);
            panel.targetTexture = _ui;

            Color32[] got = captured.GetPixels32(), want = screen.GetPixels32();
            Object.Destroy(captured);
            Object.Destroy(screen);
            AssertPixel(got, want, 340, 70, "the hit flash panel");
            AssertPixel(got, want, 560, 70, "the pause shade");
            AssertPixel(got, want, 780, 70, "the settings panel colour");
            AssertPixel(got, want, 1100, 600, "the camera's picture with no panel over it");
            int worst = 0, wx = 0, wy = 0, off = 0;
            for (int i = 0; i < got.Length; i++)
            {
                int d = Diff(got[i], want[i]);
                if (d > TOLERANCE) off++;
                if (d > worst)
                {
                    worst = d;
                    wx = i % W;
                    wy = H - 1 - i / W;
                }
            }
            Assert.That(worst, Is.LessThanOrEqualTo(TOLERANCE),
                $"{off} pixel(s) differ from the screen by more than {TOLERANCE}; the worst by {worst} at ({wx}, {wy}) "
                + $"(top-left origin): capture {got[(H - 1 - wy) * W + wx]}, screen {want[(H - 1 - wy) * W + wx]}");
            // A known label: its face is the text colour, in the capture as on the screen
            Color32 text = UiTheme.TEXT;
            Assert.IsTrue(HasColour(got, 20, 330, 700, 120, text), $"no pixel of the plain label's face is {text}");
        }

        [UnityTest]
        public IEnumerator Smoke_OutlinedTextKeepsItsColour()
        {
            if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
            {
                Assert.Ignore("needs a graphics device: python tools/dev.py smoke --graphics --filter Capture");
            }
            Camera cam = MakeCamera();
            PanelSettings panel = _panel = FrontEnd.NewPanel();
            _ui = new RenderTexture(W, H, 0, RenderTextureFormat.ARGB32) { name = "CaptureTestUi" };
            _ui.Create();
            panel.targetTexture = _ui;
            panel.clearColor = true;
            _doc = new GameObject("CaptureTestPanel");
            var doc = _doc.AddComponent<UIDocument>();
            doc.panelSettings = panel;
            VisualElement root = doc.rootVisualElement;
            // the HUD line at body size, as JuiceWorld and PlayWorld make it
            var hud = new Label("Hits 1 trauma 0.53 shake 1.00") { name = "Hud" };
            UiTheme.Text(hud, 1.0f, UiTheme.TEXT);
            UiTheme.Outline(hud);
            Place(hud, 20, 160);
            root.Add(hud);
            // a line whose text and colour change after it is outlined, inside a padded, bordered box (SubtitleBar's
            // speaker name): the face follows both and lands on the same pixels
            var box = new VisualElement { name = "Box" };
            Place(box, 20, 260);
            UiTheme.Border(box, Color.clear, 3f);
            box.style.paddingLeft = 7;
            box.style.paddingTop = 5;
            var late = new Label("") { name = "Late" };
            UiTheme.Text(late, 1.0f, UiTheme.TEXT);
            UiTheme.Outline(late);
            box.Add(late);
            root.Add(box);
            for (int i = 0; i < SETTLE_FRAMES; i++)
            {
                yield return null;
            }
            late.text = "Speaker";
            late.style.color = UiTheme.FOCUS;
            for (int i = 0; i < SETTLE_FRAMES; i++)
            {
                yield return null;
            }

            foreach ((string name, Color world) in new[] { ("white", Color.white), ("black", Color.black) })
            {
                cam.backgroundColor = world;
                Texture2D shot = Render(cam);
                UiCapture.LayOver(shot, _ui);
                Color32[] px = shot.GetPixels32();
                Object.Destroy(shot);
                Assert.IsTrue(HasColour(px, hud.worldBound, UiTheme.TEXT),
                    $"over a {name} game no pixel of the outlined HUD line is the text colour {(Color32)UiTheme.TEXT}: "
                    + $"the outline covers its letters (brightest {Brightest(px, hud.worldBound)})");
                Assert.IsTrue(HasColour(px, late.worldBound, UiTheme.FOCUS),
                    $"over a {name} game the recoloured line does not show {(Color32)UiTheme.FOCUS} "
                    + $"(brightest {Brightest(px, late.worldBound)})");
                if (name == "white")
                {
                    Assert.IsTrue(HasDark(px, hud.worldBound), "over a white game the outline does not show around the letters");
                }
            }

            // The face copy: on its text, with its text
            TextElement face = OutlineFace.Of(late);
            Assert.IsNotNull(face, "UiTheme.Outline gives the text a face copy");
            Assert.AreEqual("Speaker", face.text);
            Assert.That(Vector2.Distance(face.worldBound.position, late.worldBound.position), Is.LessThan(0.01f),
                $"the face copy is not on its text: {face.worldBound} vs {late.worldBound}");
            Assert.That(Vector2.Distance(face.worldBound.size, late.worldBound.size), Is.LessThan(0.01f));

            // The access report and the pseudo-locale check: each label once, in the colour on its letters
            var rows = new List<Dictionary<string, object>>();
            foreach (object o in AccessAudit.Texts(root))
            {
                rows.Add((Dictionary<string, object>)o);
            }
            Assert.AreEqual(2, rows.Count, "one row per label: the face copy is part of its text");
            Dictionary<string, object> row = rows.Find(r => (string)r["text"] == hud.text);
            Assert.AreEqual(UiTheme.Hex(UiTheme.TEXT), row["fg"]);
            Assert.AreEqual("#000000", row["outline"]);
            Assert.AreEqual(UiTheme.Hex(UiTheme.FOCUS), rows.Find(r => (string)r["text"] == "Speaker")["fg"]);
            AccessAudit.PseudoProblems(root, out int labels);
            Assert.AreEqual(2, labels, "the pseudo-locale check counts each label once");
        }

        [Test]
        public void Audit_OutlineWithoutAFaceReportsTheOutlineColour()
        {
            // a game's own outlined label (not through UiTheme.Outline): UI Toolkit's outline covers the letters, so
            // the colour on them is the outline's, not the text colour that does not show (#283)
            var label = new Label("Own HUD");
            label.style.color = UiTheme.TEXT;
            label.style.unityTextOutlineWidth = 2;
            label.style.unityTextOutlineColor = new Color(0.2f, 0.1f, 0.0f);
            var host = new GameObject("AuditTestPanel");
            PanelSettings panel = FrontEnd.NewPanel();
            try
            {
                var doc = host.AddComponent<UIDocument>();
                doc.panelSettings = panel;
                doc.rootVisualElement.Add(label);
                Assert.IsNull(OutlineFace.Of(label));
                Assert.AreEqual(UiTheme.Hex(new Color(0.2f, 0.1f, 0.0f)), UiTheme.Hex(UiTheme.FaceColour(label)));
            }
            finally
            {
                Object.Destroy(host);
                Object.Destroy(panel);
            }
        }

        [Test]
        public void Opaque_TheWindowedScreenshotHasNoAlpha()
        {
            // ScreenCapture.CaptureScreenshotAsTexture keeps the back buffer's alpha (the camera cleared to 0 here)
            var tex = new Texture2D(2, 1, TextureFormat.RGBA32, false);
            tex.SetPixels32(new[] { new Color32(10, 20, 30, 0), new Color32(40, 50, 60, 128) });
            tex.Apply();
            byte[] png = ShellReports.Opaque(tex).EncodeToPNG();
            Object.Destroy(tex);
            var back = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            Assert.IsTrue(back.LoadImage(png));
            Color32[] px = back.GetPixels32();
            Object.Destroy(back);
            Assert.AreEqual(new Color32(10, 20, 30, 255), px[0]);
            Assert.AreEqual(new Color32(40, 50, 60, 255), px[1]);
        }


        private Camera MakeCamera()
        {
            _camera = new GameObject("CaptureTestCamera");
            var cam = _camera.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = CAMERA;
            cam.orthographic = true;
            cam.enabled = false;                     // renders only when the test asks
            return cam;
        }

        // Known panels across the top, an outlined HUD line (UiTheme, as JuiceWorld and PlayWorld make them) and a
        // big plain label; the rest of the frame is left transparent, so the camera shows through
        private static void Fill(VisualElement root)
        {
            root.Add(Box(240, 20, HIT_FLASH));
            root.Add(Box(460, 20, UiTheme.BACKDROP));
            root.Add(Box(680, 20, UiTheme.PANEL));
            var hud = new Label("Hits 1 trauma 0.53 shake 1.00");
            UiTheme.Text(hud, 1.0f, UiTheme.TEXT);
            UiTheme.Outline(hud);
            Place(hud, 20, 160);
            root.Add(hud);
            var plain = new Label("Known label");
            UiTheme.Text(plain, 4.0f, UiTheme.TEXT);
            Place(plain, 20, 330);
            root.Add(plain);
        }

        private static VisualElement Box(float x, float y, Color colour)
        {
            var v = new VisualElement();
            Place(v, x, y);
            v.style.width = 200;
            v.style.height = 100;
            v.style.backgroundColor = colour;
            return v;
        }

        private static void Place(VisualElement v, float x, float y)
        {
            v.style.position = Position.Absolute;
            v.style.left = x;
            v.style.top = y;
        }

        private static Texture2D Render(Camera cam)
        {
            var rt = RenderTexture.GetTemporary(W, H, 24);
            cam.targetTexture = rt;
            cam.Render();
            cam.targetTexture = null;
            Texture2D tex = Read(rt);
            RenderTexture.ReleaseTemporary(rt);
            return tex;
        }

        private static Texture2D Read(RenderTexture rt)
        {
            var active = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(W, H, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, W, H), 0, 0);
            tex.Apply();
            RenderTexture.active = active;
            return tex;
        }

        private static int Diff(Color32 a, Color32 b)
        {
            return Mathf.Max(Mathf.Abs(a.r - b.r), Mathf.Max(Mathf.Abs(a.g - b.g), Mathf.Abs(a.b - b.b)));
        }

        // x, y from the top-left (UI coordinates); the pixel arrays start at the bottom row
        private static void AssertPixel(Color32[] got, Color32[] want, int x, int y, string what)
        {
            int i = (H - 1 - y) * W + x;
            Assert.That(Diff(got[i], want[i]), Is.LessThanOrEqualTo(TOLERANCE),
                $"{what} at ({x}, {y}): capture {got[i]}, screen {want[i]}");
        }

        private static bool HasColour(Color32[] pixels, Rect r, Color32 c)
        {
            return HasColour(pixels, (int)r.x, (int)r.y, Mathf.CeilToInt(r.width), Mathf.CeilToInt(r.height), c);
        }

        private static bool HasDark(Color32[] pixels, Rect r)
        {
            return HasColour(pixels, (int)r.x, (int)r.y, Mathf.CeilToInt(r.width), Mathf.CeilToInt(r.height),
                             new Color32(0, 0, 0, 255), DARK);
        }

        private static Color32 Brightest(Color32[] pixels, Rect r)
        {
            Color32 best = new Color32(0, 0, 0, 255);
            for (int y = (int)r.y; y < (int)r.yMax && y < H; y++)
            {
                for (int x = (int)r.x; x < (int)r.xMax && x < W; x++)
                {
                    Color32 p = pixels[(H - 1 - y) * W + x];
                    if (p.r + p.g + p.b > best.r + best.g + best.b)
                    {
                        best = p;
                    }
                }
            }
            return best;
        }

        private static bool HasColour(Color32[] pixels, int x0, int y0, int w, int h, Color32 c, int tolerance = TOLERANCE)
        {
            for (int y = y0; y < y0 + h; y++)
            {
                for (int x = x0; x < x0 + w; x++)
                {
                    if (Diff(pixels[(H - 1 - y) * W + x], c) <= tolerance)
                    {
                        return true;
                    }
                }
            }
            return false;
        }
    }
}
