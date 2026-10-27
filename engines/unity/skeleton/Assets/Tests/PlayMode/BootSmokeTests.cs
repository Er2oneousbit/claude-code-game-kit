// ---------------------------------------------------------------------------
// BootSmokeTests.cs
// Purpose : The boot smoke test behind `dev.py smoke`: load the first scene in
//           Build Settings, run SMOKE_FRAMES frames, fail on any logged error.
// Usage   : python tools/dev.py smoke   (PlayMode, filter "Smoke")
// Notes   : Unity Test Framework fails a test on any unexpected Error or Exception
//           log, so no explicit assert is needed. Ignored (not passed) until the
//           project has a scene in Build Settings. Add more Smoke_* tests here for
//           other scenes or flows. Same role as the BOOT_OK marker on Godot.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections;
using NUnit.Framework;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace {{GAME_SLUG}}.Tests
{
    // A namespace keeps these from colliding with an adopted project's own test classes
    public class BootSmokeTests
    {
        private const int SMOKE_FRAMES = 120;

        // The test runner adds its own Assets/InitTestScene<guid>.unity to Build Settings
        // during PlayMode runs, so "scene 0" is not necessarily the game's first scene.
        private const string RUNNER_SCENE_MARKER = "/InitTestScene";

        [UnityTest]
        public IEnumerator Smoke_FirstSceneBootsWithoutErrors()
        {
            int first = FirstGameSceneIndex();
            if (first < 0)
            {
                Assert.Ignore("No scenes in Build Settings yet. Run python tools/dev.py exec GameKitScenes.CreateStarterScene (or add one in File > Build Profiles) to enable the boot smoke test.");
            }
            yield return SceneManager.LoadSceneAsync(first);
            GameKitCapture.Attach();  // only captures when dev.py smoke asks (--screenshot, --record)
            for (int i = 0; i < SMOKE_FRAMES; i++)
            {
                yield return null;
            }
            GameKitCapture.Finish();
        }

        // Build index of the first scene that is not the test runner's, or -1.
        private static int FirstGameSceneIndex()
        {
            for (int i = 0; i < SceneManager.sceneCountInBuildSettings; i++)
            {
                if (!SceneUtility.GetScenePathByBuildIndex(i).Contains(RUNNER_SCENE_MARKER))
                {
                    return i;
                }
            }
            return -1;
        }
    }
}

// {{FOOTER}}
