// ---------------------------------------------------------------------------
// GameKitCapture.cs
// Purpose : Frame capture for `dev.py smoke --screenshot FILE` and `--record DIR`: PNGs of what the
//           main camera sees during a PlayMode smoke or scenario test.
// Usage   : in a Smoke_* test, after the scene loads:  GameKitCapture.Attach();
//           at the end (optional, for the final frame):   GameKitCapture.Finish();
// Notes   : dev.py passes the targets as environment variables (GAMEKIT_SCREENSHOT, GAMEKIT_RECORD_DIR,
//           GAMEKIT_RECORD_EVERY) and drops -nographics, because a camera cannot render without a
//           graphics device. Without the variables Attach() does nothing, so tests stay fast. Renders the
//           camera into its own RenderTexture (batchmode has no game view for ScreenCapture).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

namespace {{GAME_SLUG}}.Tests
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

        // Saves the screenshot now (call it when the scenario ends) and stops recording.
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
                Debug.LogWarning("[WARN][capture] no main camera to capture");
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
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllBytes(path, tex.EncodeToPNG());
            UnityEngine.Object.Destroy(tex);
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
