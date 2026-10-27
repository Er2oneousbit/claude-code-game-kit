// ---------------------------------------------------------------------------
// FixedTimestepTests.cs
// Purpose : EditMode tests for Core.FixedTimestep, and the pattern for new tests.
// Usage   : python tools/dev.py test
// Notes   : Run on Unity 6000.6.6f1 (Windows, 2026-10-20), including a planted failing assert.
// Authored: Written with Claude (Sonnet 5.5, claude-sonnet-5-5)
// ---------------------------------------------------------------------------
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    // A namespace keeps these from colliding with an adopted project's own test classes
    public class FixedTimestepTests
    {
        [Test]
        public void OneStepWhenFrameEqualsStep()
        {
            var ts = new FixedTimestep(0.1);
            Assert.AreEqual(1, ts.Advance(0.1));
        }

        [Test]
        public void HugeFrameIsClampedInsteadOfSpiraling()
        {
            var ts = new FixedTimestep(0.1, 0.25, 8);
            Assert.AreEqual(2, ts.Advance(30.0));
        }

        [Test]
        public void AccumulatesFractionalFramesAcrossCalls()
        {
            var ts = new FixedTimestep(0.1);
            Assert.AreEqual(0, ts.Advance(0.06));
            Assert.AreEqual(1, ts.Advance(0.06));
            Assert.AreEqual(0.2, ts.Alpha, 1e-9);
        }

        [Test]
        public void NegativeFrameTimeIsZero()
        {
            var ts = new FixedTimestep(0.1);
            Assert.AreEqual(0, ts.Advance(-5.0));
            Assert.AreEqual(1, ts.Advance(0.1));     // a negative accumulator would swallow this step
            Assert.AreEqual(0.0, ts.Alpha, 1e-9);
        }

        [Test]
        public void NaNFrameTimeIsIgnored()
        {
            var ts = new FixedTimestep(0.1);
            Assert.AreEqual(0, ts.Advance(double.NaN));
            Assert.AreEqual(1, ts.Advance(0.1));
        }

        [Test]
        public void NonPositiveMaxFrameFallsBack()
        {
            var ts = new FixedTimestep(0.1, -1.0);
            Assert.AreEqual(1, ts.Advance(0.1));
            Assert.AreEqual(2, ts.Advance(30.0));
        }

        [Test]
        public void NonPositiveStepFallsBackTo60Hz()
        {
            Assert.AreEqual(1.0 / 60.0, new FixedTimestep(0.0).Step, 1e-12);
        }

        [Test]
        public void DroppedTimeClearsOnNextAdvance()
        {
            var ts = new FixedTimestep(0.01, 1.0, 4);
            ts.Advance(0.5);
            Assert.IsTrue(ts.DroppedTime);
            ts.Advance(0.01);
            Assert.IsFalse(ts.DroppedTime);
        }

        [Test]
        public void ZeroMaxStepsStillRuns()
        {
            Assert.AreEqual(1, new FixedTimestep(0.1, 1.0, 0).Advance(0.1));
        }

        [Test]
        public void StepCapDropsBacklog()
        {
            var ts = new FixedTimestep(0.01, 1.0, 4);
            Assert.AreEqual(4, ts.Advance(0.5));
            Assert.IsTrue(ts.DroppedTime);
            Assert.AreEqual(0, ts.Advance(0.0));
        }
    }
}

// {{FOOTER}}
