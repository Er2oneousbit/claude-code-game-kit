// ---------------------------------------------------------------------------
// DisplayApplyTests.cs
// Purpose : The Display tab's Apply (#308, Core's DisplayStaging) and a game HUD's text size (#309, Core's HudScale),
//           with values worked out by hand (the golden cases in ShellVectorTests come from the reference).
// Usage   : python tools/dev.py test     (or --filter DisplayApply)
// Notes   : The settings screen itself is driven by `dev.py smoke --drive display` (SmokeDrive.Display): Back's
//           warning, the confirm overlay and the real-time countdown on a running front end.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public class DisplayApplyTests
    {
        private static DisplayStaging Fresh()
        {
            return new DisplayStaging((Dictionary<string, object>)GameSettings.Defaults()["display"]);
        }

        private static List<object> Res(double w, double h)
        {
            return new List<object> { w, h };
        }

        [Test]
        public void DisplayApply_ModeGoesBeforeResolutionAndOpensTheConfirm()
        {
            DisplayStaging st = Fresh();
            st.Stage("resolution", Res(1280, 720));
            st.Stage("mode", "fullscreen");
            Assert.AreEqual("fullscreen", st.Value("mode"));            // the row shows the staged value
            Assert.AreEqual("windowed", st.Applied["mode"]);            // nothing applied yet
            List<(string Field, object Value)> calls = st.Apply();
            Assert.AreEqual(2, calls.Count);
            Assert.AreEqual("mode", calls[0].Field);
            Assert.AreEqual("resolution", calls[1].Field);
            Assert.AreEqual(15, st.Seconds());
        }

        [Test]
        public void DisplayApply_VsyncAloneNeedsNoConfirm()
        {
            DisplayStaging st = Fresh();
            st.Stage("vsync", false);
            Assert.AreEqual(1, st.Apply().Count);
            Assert.IsNull(st.Seconds());
        }

        [Test]
        public void DisplayApply_TheCountdownRevertsExactlyWhatTheApplyReplaced()
        {
            DisplayStaging st = Fresh();
            st.Stage("mode", "borderless");
            st.Stage("frame_cap", 60.0);
            st.Apply();
            Assert.IsEmpty(st.Tick(14.5));
            Assert.AreEqual(1, st.Seconds());
            List<(string Field, object Value)> back = st.Tick(0.5);
            Assert.AreEqual(2, back.Count);
            Assert.AreEqual(("mode", (object)"windowed"), back[0]);
            Assert.AreEqual(0.0, Json.ToNumber(back[1].Value));
            Assert.IsNull(st.Seconds());
        }

        [Test]
        public void DisplayApply_BackDuringTheConfirmRevertsAndStageIsRefused()
        {
            DisplayStaging st = Fresh();
            st.Stage("mode", "fullscreen");
            st.Apply();
            Assert.AreEqual("busy", st.Stage("vsync", false));
            (string what, List<(string Field, object Value)> calls) = st.Back();
            Assert.AreEqual("revert", what);
            Assert.AreEqual("windowed", calls[0].Value);
        }

        [Test]
        public void DisplayApply_BackWarnsOnceThenDiscards()
        {
            DisplayStaging st = Fresh();
            st.Stage("ui_scale", 1.5);
            st.Stage("ui_scale", 1);                                     // the applied value (1.0) by value: dropped
            Assert.IsFalse(st.HasPending);
            st.Stage("resolution", Res(1920, 1080));                     // the applied size, a new list: dropped
            Assert.IsFalse(st.HasPending);
            st.Stage("vsync", false);
            Assert.AreEqual("warn", st.Back().What);
            Assert.AreEqual("leave", st.Back().What);
            Assert.IsFalse(st.HasPending);
            Assert.AreEqual(true, st.Applied["vsync"]);
        }

        [Test]
        public void HudScale_IsUiScaleTimesTextScaleAndTheWatchHearsItChange()
        {
            Dictionary<string, object> s = GameSettings.Defaults();
            Assert.AreEqual(1.0, HudScale.Factor(s), 1e-9);
            Assert.AreEqual(24, HudScale.FontSize(24, s));
            var watch = new HudScale.Watch();
            Assert.IsTrue(watch.Update(s));                              // the first frame: lay out once
            Assert.IsFalse(watch.Update(s));
            ((Dictionary<string, object>)s["access"])["text_scale"] = 1.5;   // live, from the Accessibility tab
            Assert.IsTrue(watch.Update(s));
            Assert.AreEqual(1.5, watch.Scale, 1e-9);
            ((Dictionary<string, object>)s["display"])["ui_scale"] = 2.0;    // on the Display tab's Apply
            Assert.IsTrue(watch.Update(s));
            Assert.AreEqual(72, HudScale.FontSize(24, s));
            ((Dictionary<string, object>)s["audio"])["master"] = 0.2;        // anything else: no change
            Assert.IsFalse(watch.Update(s));
            Assert.AreEqual(1.0, HudScale.Factor(new Dictionary<string, object>()), 1e-9);   // missing: 1.0 each
            Assert.AreEqual(HudScale.MIN_PX, HudScale.FontSize(2, s));
        }
    }
}

// {{FOOTER}}
