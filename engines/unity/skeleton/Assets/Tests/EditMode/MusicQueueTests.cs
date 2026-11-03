// ---------------------------------------------------------------------------
// MusicQueueTests.cs
// Purpose : The music player's decisions (Core MusicQueue): a change asked back before its switch is undone, so
//           the old track plays on from where it was instead of restarting; one asked after the switch is a new
//           change; a track still in a stinger's gap is planned from where it enters.
// Usage   : python tools/dev.py test              (or --filter MusicQueue)
// Notes   : 120 bpm in 4/4 at 48 kHz: one bar is 96000 samples. The plans are compared with MusicDirector.Plan
//           (checked against data/golden/music.json by MusicVectorTests), so only the queue's choice of "from
//           which track, since when" is tested here.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public class MusicQueueTests
    {
        private const long BAR = 96000;
        private const string MUSIC = @"{
            ""sample_rate"": 48000,
            ""tracks"": {
                ""explore"": { ""bpm"": 120, ""beats_per_bar"": 4, ""bars"": 4, ""stems"": { ""a"": ""e.ogg"" } },
                ""combat"": { ""bpm"": 120, ""beats_per_bar"": 4, ""bars"": 4, ""stems"": { ""a"": ""c.ogg"" } },
                ""boss"": { ""bpm"": 120, ""beats_per_bar"": 4, ""bars"": 4, ""stems"": { ""a"": ""b.ogg"" } }
            },
            ""stingers"": { ""hit"": { ""file"": ""s.ogg"", ""bars"": 1 } },
            ""transitions"": [ { ""from"": ""*"", ""to"": ""boss"", ""quantize"": ""bar"", ""stinger"": ""hit"" } ],
            ""default_transition"": { ""quantize"": ""bar"", ""fade_ms"": 0 }
        }";

        private MusicDirector _director;
        private MusicQueue _queue;

        [SetUp]
        public void SetUp()
        {
            _director = MusicDirector.FromJson(MUSIC);
            _queue = new MusicQueue(_director);
            _queue.Start("explore", 0);
        }

        private static void SamePlan(MusicPlan want, MusicPlan got)
        {
            Assert.IsNotNull(got);
            Assert.AreEqual(want.SwitchAt, got.SwitchAt, "switch_at");
            Assert.AreEqual(want.FromStopAt, got.FromStopAt, "from_stop_at");
            Assert.AreEqual(want.ToStartAt, got.ToStartAt, "to_start_at");
            Assert.AreEqual(want.ToOffset, got.ToOffset, "to_offset");
            Assert.AreEqual(want.Stinger, got.Stinger, "stinger");
            Assert.AreEqual(want.StingerAt, got.StingerAt, "stinger_at");
        }

        private void IsCurrent(string name, long since, long entry)
        {
            Assert.AreEqual(name, _queue.Current.Name);
            Assert.AreEqual(since, _queue.Current.Since, "since");
            Assert.AreEqual(entry, _queue.Current.Entry, "entry");
        }

        [Test]
        public void MusicQueue_AskedBackBeforeTheSwitch_KeepsTheOldTrackPlaying()
        {
            MusicQueue.Step s = _queue.Request("combat", 1000);
            Assert.AreEqual(BAR, s.Plan.SwitchAt);
            s = _queue.Request("explore", 50000);              // before the bar line: combat never starts
            Assert.IsTrue(s.Undone);
            Assert.IsNull(s.Plan, "explore is not planned again (no restart from its top)");
            Assert.IsNull(_queue.Pending);
            IsCurrent("explore", 0, 0);
            // a later change is planned from explore's own start, as if combat had never been asked
            SamePlan(_director.Plan("explore", 0, 0, "combat", 100000), _queue.Request("combat", 100000).Plan);
        }

        [Test]
        public void MusicQueue_OnTheSwitchSample_StillUndoes()
        {
            _queue.Request("combat", 1000);
            Assert.IsTrue(_queue.Request("explore", BAR).Undone);   // the switch sample itself has not played yet
            IsCurrent("explore", 0, 0);
        }

        [Test]
        public void MusicQueue_AfterTheSwitch_IsANewChange()
        {
            _queue.Request("combat", 1000);
            MusicQueue.Step s = _queue.Request("explore", BAR + 1);
            Assert.IsFalse(s.Undone);
            SamePlan(_director.Plan("combat", BAR, 0, "explore", BAR + 1), s.Plan);
            IsCurrent("explore", s.Plan.ToStartAt, s.Plan.ToOffset);
        }

        [Test]
        public void MusicQueue_ANewTargetBeforeTheSwitch_ReplacesThePendingOne()
        {
            _queue.Request("combat", 1000);
            MusicQueue.Step s = _queue.Request("boss", 2000);
            Assert.IsTrue(s.Undone);
            SamePlan(_director.Plan("explore", 0, 0, "boss", 2000), s.Plan);
            IsCurrent("boss", s.Plan.ToStartAt, 0);
        }

        [Test]
        public void MusicQueue_InAStingersGap_PlansFromTheEntry()
        {
            MusicQueue.Step s = _queue.Request("boss", 1000);
            Assert.AreEqual(BAR, s.Plan.StingerAt);
            Assert.AreEqual(2 * BAR, s.Plan.ToStartAt, "boss enters one stinger bar after the switch");
            s = _queue.Request("explore", BAR + 10);           // the stinger plays, boss has not entered yet
            Assert.IsFalse(s.Undone);
            SamePlan(_director.Plan("boss", 2 * BAR, 0, "explore", 2 * BAR), s.Plan);
        }

        [Test]
        public void MusicQueue_StartAndClear_ForgetThePendingChange()
        {
            _queue.Request("combat", 1000);
            _queue.Start("boss", 5000);
            Assert.IsNull(_queue.Pending);
            Assert.IsFalse(_queue.Request("explore", 6000).Undone);
            _queue.Clear();
            Assert.IsNull(_queue.Current);
            Assert.IsTrue(_queue.Request("combat", 7000).Started);
            IsCurrent("combat", 7000, 0);
        }
    }
}

// {{FOOTER}}
