// ---------------------------------------------------------------------------
// ShellSmokeTests.cs
// Purpose : The shell's smoke tests behind `dev.py smoke`: boot the kit's front end to the title, and with
//           `--drive <scenario>` run that scripted path (SmokeDrive) and fail when it does.
// Usage   : python tools/dev.py smoke                       (PlayMode, filter "Smoke": this and BootSmokeTests)
//           python tools/dev.py smoke --drive menus         (filter "Smoke_ShellDrive"; GAMEKIT_DRIVE is set)
// Notes   : Ignored (not passed) until the shell scene is in Build Settings: python tools/dev.py exec
//           GameKitScenes.CreateShellScene. dev.py reads the drive's markers from the Unity log (DRIVE_DONE,
//           DRIVE_FAIL, ACCESS_*). The drive runs only when this test arms it (FrontEnd.DriveArmed), so the boot
//           smoke test loading the same scene does not run it a second time. A show: drive ends on the screen it
//           opened, and GameKitCapture.Finish() then takes the --screenshot.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System;
using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
using {{GAME_SLUG}}.Shell;

namespace {{GAME_SLUG}}.Tests
{
    public class ShellSmokeTests
    {
        private const int BOOT_FRAMES = 120;
        private const float DRIVE_TIMEOUT_S = 180f;     // real seconds a drive gets (dev.py has its own, longer limit)
        private const float BOOT_TIMEOUT_S = 20f;

        [UnityTest]
        public IEnumerator Smoke_ShellDrive()
        {
            int index = SceneUtility.GetBuildIndexByScenePath(FrontEnd.SCENE_PATH);
            if (index < 0)
            {
                Assert.Ignore($"No shell scene in Build Settings yet. Run python tools/dev.py exec GameKitScenes.CreateShellScene "
                              + $"to add {FrontEnd.SCENE_PATH} (the kit's title, settings, pause and credits screens).");
            }
            string drive = Environment.GetEnvironmentVariable("GAMEKIT_DRIVE") ?? "";
            FrontEnd.DriveArmed = drive != "";
            yield return SceneManager.LoadSceneAsync(index);
            GameKitCapture.Attach();    // only captures when dev.py smoke asks (--screenshot, --record)
            FrontEnd front = UnityEngine.Object.FindFirstObjectByType<FrontEnd>();
            Assert.IsNotNull(front, $"{FrontEnd.SCENE_PATH} has no FrontEnd component");
            float start = Time.realtimeSinceStartup;
            while (front.CurrentName() != "title" && Time.realtimeSinceStartup - start < BOOT_TIMEOUT_S)
            {
                yield return null;
            }
            Assert.AreEqual("title", front.CurrentName(), "the title screen did not come up");
            Debug.Log("BOOT_OK title");
            if (drive == "")
            {
                for (int i = 0; i < BOOT_FRAMES; i++)
                {
                    yield return null;
                }
            }
            else
            {
                Assert.IsNotNull(front.Drive, "the drive did not start (FrontEnd.DriveArmed and GAMEKIT_DRIVE)");
                start = Time.realtimeSinceStartup;
                while (!front.Drive.Finished && Time.realtimeSinceStartup - start < DRIVE_TIMEOUT_S)
                {
                    yield return null;
                }
                Assert.IsTrue(front.Drive.Finished, $"drive {drive} did not finish within {DRIVE_TIMEOUT_S} s");
                Assert.IsFalse(front.Drive.Failed, $"drive {drive} failed: {front.Drive.Why}");
            }
            GameKitCapture.Finish();
            FrontEnd.DriveArmed = false;
        }
    }
}

// {{FOOTER}}
