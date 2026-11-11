// ---------------------------------------------------------------------------
// ShellReports.cs
// Purpose : Crash files and the F8 bug report (#275, as Godot, LÖVE and web have them): an unhandled exception writes
//           crashes/crash_<time>.txt into the user-data folder (version, error, stack, settings, log tail) and logs
//           CRASH_WRITTEN <path>; F8 in the editor and in development builds saves bug_<time>/ (info.txt,
//           log_tail.txt, settings.json, screenshot.png) for a tester to attach, and logs BUG_REPORT <dir>.
// Usage   : ShellReports.Install(dataDir);         // Shell.Boot does it (as early as it can)
//           ShellReports.Tick();                   // once a frame (Shell.Update): logs the marker, ends a smoke player
//           string dir = ShellReports.BugReport(front);   // FrontEnd calls it on F8
// Notes   : Unity keeps running after an unhandled exception (the frame's script stops, the next frame comes), so
//           a crash file is written for the first exception of a launch only: later ones are in the log. The log
//           hook is Application.logMessageReceivedThreaded, so everything the crash file needs from Unity's API
//           (version, OS, data folder) is read once on the main thread; the marker line is logged on the next frame
//           (logging inside the hook would feed the hook). A player started with --smoke quits with exit code 1
//           after a crash; in a PlayMode test the logged exception already fails the test. The screenshot needs a
//           graphics device: in batchmode or a capture the panel's texture is laid over the camera's picture (as
//           GameKitCapture does), in a windowed player the screen is read at the end of the frame (and its alpha
//           dropped: the back buffer's alpha is not what the screen shows). Nothing leaves
//           the machine.
//
// Pseudocode:
//   hook(line, stack, type): tail += line ; type Exception and no crash file yet -> CrashText.Text -> AtomicFile
//   Tick: a crash file written since the last frame -> CRASH_WRITTEN <path> ; smoke player -> quit(1)
//   BugReport: bug_<stamp>/ -> info, log tail, settings -> screenshot (graphics device only) -> BUG_REPORT <dir>
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the composed screenshot blends as the screen does
//           (UiCapture, #277)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): a windowed player's screenshot is saved opaque (#283)
// ---------------------------------------------------------------------------
using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;
using graveyard_shift.Core;

namespace graveyard_shift.Shell
{
    public static class ShellReports
    {
        // ---- Tunables ------------------------------------------------------------
        public const string BUG_REPORT_KEY = "f8";         // a key binding name (ShellInput.KeyDown)
        public const string BUG_PREFIX = "bug_";
        public const int SHOT_W = 1280;                    // the screenshot's size when it is composed (batchmode, capture)
        public const int SHOT_H = 720;

        public static readonly LogTail Tail = new LogTail(CrashText.BUG_LOG_LINES);
        /// <summary>The crash file written this launch ("" until one is).</summary>
        public static string CrashFile { get; private set; } = "";
        /// <summary>The last bug report folder ("" until one is saved).</summary>
        public static string LastBugReport { get; private set; } = "";
        /// <summary>The screen on top (FrontEnd keeps it current), for the crash file and the bug report.</summary>
        public static volatile string CurrentScreen = "";
        /// <summary>The editor and development builds have the F8 key; a release build does not.</summary>
        public static bool BugKeyEnabled => Debug.isDebugBuild || Application.isEditor;

        private static readonly object _lock = new object();
        private static bool _installed;
        private static volatile string _dataDir = "";
        private static string _game = "", _version = "", _engine = "";
        private static string _pendingMarker;

        /// <summary>Hooks the log (once) and remembers the data folder; call again when the folder changes.</summary>
        public static void Install(string dataDir)
        {
            _dataDir = dataDir ?? "";
            _game = Shell.GAME_NAME;
            _version = Application.version;
            _engine = $"Unity {Application.unityVersion} ({(Debug.isDebugBuild ? "debug" : "release")} build), {SystemInfo.operatingSystem}";
            if (_installed)
            {
                return;
            }
            _installed = true;
            Application.logMessageReceivedThreaded += OnLog;
        }

        /// <summary>Once a frame on the main thread: the CRASH_WRITTEN line, and a smoke player's exit.</summary>
        public static void Tick()
        {
            string marker;
            lock (_lock)
            {
                marker = _pendingMarker;
                _pendingMarker = null;
            }
            if (marker == null)
            {
                return;
            }
            Shell.Raw("CRASH_WRITTEN " + marker);
            Debug.LogWarning($"[WARN][shell] unhandled exception, crash file written: {marker}");
            if (Shell.I != null && Shell.I.Smoke && !Application.isEditor)
            {
                Application.Quit(1);
            }
        }

        // ---- crash files ---------------------------------------------------------------------

        private static void OnLog(string condition, string stack, LogType type)
        {
            Tail.Add(type == LogType.Log ? condition : $"{type}: {condition}");
            if (type == LogType.Exception)
            {
                WriteCrash(condition, stack);
            }
        }

        /// <summary>Writes the launch's crash file (the first call only) and returns its path, or "" when one was
        /// already written or it could not be. Never throws.</summary>
        public static string WriteCrash(string error, string stack)
        {
            lock (_lock)
            {
                if (CrashFile != "")
                {
                    return "";
                }
                try
                {
                    string dir = Path.Combine(DataDir(), CrashText.DIR);
                    Directory.CreateDirectory(dir);
                    string name = CrashText.FileName(Stamp(), n => File.Exists(Path.Combine(dir, n)));
                    string file = Path.Combine(dir, name);
                    var info = new CrashInfo
                    {
                        Game = _game, Version = _version, Engine = _engine, Time = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        Screen = CurrentScreen, Error = error, Stack = stack, Settings = SettingsText(),
                        LogTail = Tail.Text(CrashText.CRASH_LOG_LINES),
                    };
                    AtomicFile.Write(file, CrashText.Text(info), false);
                    CrashFile = file;
                    _pendingMarker = file;
                    return file;
                }
                catch (Exception)
                {
                    return "";          // a crash report must not hide the crash: the log still has it
                }
            }
        }

        // ---- the bug report (F8) -----------------------------------------------------------

        /// <summary>Saves bug_<stamp>/ in the data folder and returns its path ("" when the key is off or it failed).
        /// The screenshot is written now (composed) or at the end of this frame (a windowed player).</summary>
        public static string BugReport(MonoBehaviour host)
        {
            if (!BugKeyEnabled)
            {
                return "";
            }
            string dir = Path.Combine(DataDir(), BUG_PREFIX + Stamp());
            for (int n = 2; Directory.Exists(dir) && n <= CrashText.MAX_SAME_SECOND; n++)
            {
                dir = Path.Combine(DataDir(), $"{BUG_PREFIX}{Stamp()}_{n}");
            }
            try
            {
                Directory.CreateDirectory(dir);
                Shell s = Shell.I;
                AtomicFile.Write(Path.Combine(dir, "info.txt"), CrashText.Info(_game, _version, _engine,
                    DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"), CurrentScreen, null, s != null ? s.Locale : null), false);
                AtomicFile.Write(Path.Combine(dir, "log_tail.txt"), Tail.Text(CrashText.BUG_LOG_LINES) + "\n", false);
                AtomicFile.Write(Path.Combine(dir, "settings.json"), SettingsText(), false);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                Debug.LogWarning($"[WARN][bug] report not saved: {e.Message}");
                return "";
            }
            string shot = Path.Combine(dir, "screenshot.png");
            if (SystemInfo.graphicsDeviceType != GraphicsDeviceType.Null)
            {
                FrontEnd front = host as FrontEnd;
                if ((front != null && front.UiTexture != null) || Application.isBatchMode || host == null)
                {
                    SaveComposed(shot, front != null ? front.UiTexture : null);
                }
                else
                {
                    host.StartCoroutine(SaveAtEndOfFrame(shot));
                }
            }
            LastBugReport = dir;
            Debug.Log($"[INFO][bug] report saved to {dir}");
            Shell.Raw("BUG_REPORT " + dir);
            return dir;
        }

        // The camera's picture with the UI panel's texture laid over it as the screen shows it (UiCapture)
        private static void SaveComposed(string path, RenderTexture ui)
        {
            var rt = RenderTexture.GetTemporary(SHOT_W, SHOT_H, 24);
            var active = RenderTexture.active;
            Camera cam = Camera.main;
            if (cam != null)
            {
                var previous = cam.targetTexture;
                cam.targetTexture = rt;
                cam.Render();
                cam.targetTexture = previous;
            }
            else
            {
                RenderTexture.active = rt;
                GL.Clear(true, true, Color.black);
            }
            RenderTexture.active = rt;
            var picture = new Texture2D(SHOT_W, SHOT_H, TextureFormat.RGB24, false);
            picture.ReadPixels(new Rect(0, 0, SHOT_W, SHOT_H), 0, 0);
            picture.Apply();
            RenderTexture.active = active;
            RenderTexture.ReleaseTemporary(rt);
            UiCapture.LayOver(picture, ui);
            WritePng(path, picture);
        }

        private static IEnumerator SaveAtEndOfFrame(string path)
        {
            yield return new WaitForEndOfFrame();
            WritePng(path, Opaque(ScreenCapture.CaptureScreenshotAsTexture()));
        }

        /// <summary>The texture with every alpha at 255 (an RGBA32 screen capture holds the back buffer's alpha, so a
        /// game that clears to alpha below 1 would save a see-through PNG, #283); other formats as they are.</summary>
        public static Texture2D Opaque(Texture2D tex)
        {
            if (tex != null && tex.format == TextureFormat.RGBA32)
            {
                byte[] raw = tex.GetRawTextureData();
                UiComposite.Opaque(raw);
                tex.LoadRawTextureData(raw);
                tex.Apply();
            }
            return tex;
        }

        private static void WritePng(string path, Texture2D tex)
        {
            try
            {
                File.WriteAllBytes(path, tex.EncodeToPNG());
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                Debug.LogWarning($"[WARN][bug] no screenshot: {e.Message}");
            }
            finally
            {
                UnityEngine.Object.Destroy(tex);
            }
        }

        // ---- helpers -------------------------------------------------------------------------

        private static string DataDir()
        {
            return _dataDir != "" ? _dataDir : Directory.GetCurrentDirectory();
        }

        private static string SettingsText()
        {
            try
            {
                Shell s = Shell.I;           // a plain reference test: UnityEngine.Object's == is main-thread only
                return !ReferenceEquals(s, null) ? GameSettings.ToText(s.Settings) : "";
            }
            catch (Exception)
            {
                return "";              // the settings were being changed on another thread
            }
        }

        private static string Stamp()
        {
            return DateTime.Now.ToString("yyyyMMdd_HHmmss");
        }
    }
}
