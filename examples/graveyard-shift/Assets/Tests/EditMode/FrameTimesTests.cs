// ---------------------------------------------------------------------------
// FrameTimesTests.cs
// Purpose : EditMode tests for Core.FrameTimes, the FRAME_TIMES line `dev.py smoke` reads (#90).
// Usage   : python tools/dev.py test
// Notes   : Nearest-rank percentiles, the same rule as every engine's FRAME_TIMES line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using graveyard_shift.Core;

namespace graveyard_shift.Tests
{
    public class FrameTimesTests
    {
        [Test]
        public void SummaryOfOneToHundredInAnyOrder()
        {
            var ms = new List<double>();
            for (int i = 100; i >= 1; i--)
            {
                ms.Add(i);
            }
            FrameTimes.Summary s = FrameTimes.Summarize(ms);
            Assert.AreEqual(100, s.Frames);
            Assert.AreEqual(50.5, s.Mean, 1e-9);
            Assert.AreEqual(95.0, s.P95);
            Assert.AreEqual(99.0, s.P99);
            Assert.AreEqual(100.0, s.Worst);
        }

        [Test]
        public void TheLineDevPyReads()
        {
            var ft = new FrameTimes();
            ft.Add(16);
            ft.Add(17);
            ft.Add(40);
            Assert.AreEqual("FRAME_TIMES frames=3 mean=24.33 p95=40.00 p99=40.00 worst=40.00 mode=logic", ft.Line("logic"));
        }

        [Test]
        public void NoFramesNoLine()
        {
            Assert.AreEqual("", new FrameTimes().Line("logic"));
        }
    }
}
