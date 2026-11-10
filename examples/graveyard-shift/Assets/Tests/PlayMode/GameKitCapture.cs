// ---------------------------------------------------------------------------
// GameKitCapture.cs
// Purpose : Frame capture for `dev.py smoke --screenshot FILE` and `--record DIR`: PNGs of what the
//           main camera sees during a PlayMode smoke or scenario test.
// Usage   : in a Smoke_* test, after the scene loads:  GameKitCapture.Attach();
//           at the end (this saves the --screenshot):     GameKitCapture.Finish();
// Notes   : dev.py passes the targets as environment variables (GAMEKIT_SCREENSHOT, GAMEKIT_RECORD_DIR,
//           GAMEKIT_RECORD_EVERY) and drops -nographics, because a camera cannot render without a
//           graphics device. Without the variables Attach() does nothing, so tests stay fast. Renders the
//           camera into its own RenderTexture (batchmode has no game view for ScreenCapture). A capture that
//           cannot be saved (no main camera, a write error) is a Debug.LogError, which fails the test.
//           dev.py smoke fails when an asked-for screenshot or frame folder is empty afterwards. UI Toolkit panels
//           that draw into a RenderTexture (the kit's shell does under a capture: UIDocument.panelSettings
//           .targetTexture) are laid over the camera's picture, alpha-blended on the CPU, so the menus show in
//           the capture; a panel of another size is stretched to the picture.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a failed save is an error, not a warning;
//           Finish() is required for --screenshot (it takes the picture)
// Updated : 2026-11-09 with Claude (Fable 5.1, claude-fable-5-1): UI Toolkit panels with a target texture are
//           composed over the camera's picture (#168: the shell's screens in show: captures)
// ---------------------------------------------------------------------------
using System;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.UIElements;

namespace graveyard_shift.Tests
{
    public static class GameKitCapture
    {
        private const int Width = 1280;
        private const int Height = 720;
        private static Driver _driver;

        public static void Attach()
        {
            string shot = Environment.GetEnvironmentVariable("GAMEKIT_SCREENSHOT");
            string dir = Environment.GetEnvironmentVariable("GAMEKIT_RECORD_DIR");
            if (string.IsNullOrEmpty(shot) && string.IsNullOrEmpty(dir)) return;
            if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
            {
                Debug.LogWarning("[WARN][capture] no graphics device: run smoke with --graphics (or --screenshot/--record)");
                return;
            }
            if (_driver != null) return;
            var go = new GameObject("GameKitCapture");
            UnityEngine.Object.DontDestroyOnLoad(go);
            _driver = go.AddComponent<Driver>();
            _driver.Shot = shot;
            _driver.Dir = dir;
            int.TryParse(Environment.GetEnvironmentVariable("GAMEKIT_RECORD_EVERY"), out _driver.Every);
            if (_driver.Every < 1) _driver.Every = 6;
        }

        // Saves the screenshot now and stops recording. Call it when the scenario ends: without it no
        // --screenshot is written.
        public static void Finish()
        {
            if (_driver == null) return;
            if (!string.IsNullOrEmpty(_driver.Shot)) Save(_driver.Shot);
            UnityEngine.Object.Destroy(_driver.gameObject);
            _driver = null;
        }

        private static void Save(string path)
        {
            Camera cam = Camera.main;
            if (cam == null)
            {
                Debug.LogError($"[ERROR][capture] no main camera to capture for {path}");
                return;
            }
            var rt = RenderTexture.GetTemporary(Width, Height, 24);
            var previous = cam.targetTexture;
            cam.targetTexture = rt;
            cam.Render();
            cam.targetTexture = previous;
            var active = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D(Width, Height, TextureFormat.RGB24, false);
            tex.ReadPixels(new Rect(0, 0, Width, Height), 0, 0);
            tex.Apply();
            RenderTexture.active = active;
            RenderTexture.ReleaseTemporary(rt);
            ComposeUi(tex);
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllBytes(path, tex.EncodeToPNG());
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                Debug.LogError($"[ERROR][capture] could not save {path}: {e.Message}");
            }
            finally
            {
                UnityEngine.Object.Destroy(tex);
            }
        }

        // Every UI Toolkit panel drawing into a texture, laid over the picture (straight alpha, nearest sampling)
        private static void ComposeUi(Texture2D picture)
        {
            foreach (UIDocument doc in UnityEngine.Object.FindObjectsByType<UIDocument>(FindObjectsSortMode.None))
            {
                RenderTexture ui = doc.panelSettings != null ? doc.panelSettings.targetTexture : null;
                if (ui == null || !ui.IsCreated())
                {
                    continue;
                }
                var active = RenderTexture.active;
                RenderTexture.active = ui;
                var layer = new Texture2D(ui.width, ui.height, TextureFormat.RGBA32, false);
                layer.ReadPixels(new Rect(0, 0, ui.width, ui.height), 0, 0);
                layer.Apply();
                RenderTexture.active = active;
                Color32[] bottom = picture.GetPixels32();
                Color32[] top = layer.GetPixels32();
                for (int y = 0; y < picture.height; y++)
                {
                    int sy = y * ui.height / picture.height;
                    for (int x = 0; x < picture.width; x++)
                    {
                        Color32 t = top[sy * ui.width + x * ui.width / picture.width];
                        if (t.a == 0)
                        {
                            continue;
                        }
                        int i = y * picture.width + x;
                        Color32 b = bottom[i];
                        int a = t.a, ia = 255 - a;
                        bottom[i] = new Color32((byte)((t.r * a + b.r * ia) / 255), (byte)((t.g * a + b.g * ia) / 255),
                                                (byte)((t.b * a + b.b * ia) / 255), 255);
                    }
                }
                picture.SetPixels32(bottom);
                picture.Apply();
                UnityEngine.Object.Destroy(layer);
            }
        }

        private sealed class Driver : MonoBehaviour
        {
            public string Shot;
            public string Dir;
            public int Every = 6;
            private int _frame;

            private void LateUpdate()
            {
                if (!string.IsNullOrEmpty(Dir) && _frame % Every == 0)
                {
                    Save(Path.Combine(Dir, $"frame_{_frame:D6}.png"));
                }
                _frame++;
            }
        }
    }
}
