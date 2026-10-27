// ---------------------------------------------------------------------------
// EndSequenceTests.cs
// Purpose : EditMode tests for how a night ends (EndSequence.At): dawn shows the sunrise before the screen
//           fades, the escape fades sooner, the end card (and its music) comes only after the fade.
// Usage   : python tools/dev.py test
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using graveyard_shift.Game;
using NUnit.Framework;

namespace graveyard_shift.Tests
{
    public class EndSequenceTests
    {
        [Test]
        public void Dawn_SunriseFirst_ThenFade_ThenCard()
        {
            var start = EndSequence.At(true, 0f);
            Assert.AreEqual(0f, start.Dawn);
            Assert.AreEqual(0f, start.Fade);
            Assert.IsFalse(start.Card);

            var risen = EndSequence.At(true, EndSequence.DawnShow);
            Assert.AreEqual(1f, risen.Dawn, 1e-4, "the sun is up when the fade starts");
            Assert.AreEqual(0f, risen.Fade, 1e-4, "no fade during the sunrise");

            var mid = EndSequence.At(true, EndSequence.DawnShow + EndSequence.ScreenFade / 2f);
            Assert.Greater(mid.Fade, 0f);
            Assert.IsFalse(mid.Card, "no card while the screen is still fading");

            var done = EndSequence.At(true, EndSequence.DawnShow + EndSequence.ScreenFade);
            Assert.IsTrue(done.Card);
            Assert.AreEqual(EndSequence.CardDim, done.Fade, 1e-4);
        }

        [Test]
        public void Escape_NoSunrise_ShorterLead()
        {
            Assert.AreEqual(0f, EndSequence.At(false, 10f).Dawn, "it is still night when you escape");
            Assert.Less(EndSequence.EscapeHold, EndSequence.DawnShow);
            Assert.IsFalse(EndSequence.At(false, EndSequence.EscapeHold + EndSequence.ScreenFade - 0.01f).Card);
            Assert.IsTrue(EndSequence.At(false, EndSequence.EscapeHold + EndSequence.ScreenFade).Card);
        }
    }
}
