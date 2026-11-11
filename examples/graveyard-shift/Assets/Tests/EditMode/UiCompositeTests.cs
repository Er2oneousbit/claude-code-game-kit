// ---------------------------------------------------------------------------
// UiCompositeTests.cs
// Purpose : The capture's UI composite (Core/UiComposite.cs, #277) against what a windowed player showed: the panel's
//           texture (premultiplied), the camera's picture and the screen, read from the same frame of a Unity 6000.6
//           player on Direct3D 12, in a Gamma and in a Linear colour space project. The camera cleared to
//           (51, 102, 153); the panels were the juice demo's hit flash at 0.5, the pause shade (black at 0.6), the
//           settings panel colour at 0.96, red at 0.25, and opaque text colour. Opaque: the F8 screenshot (#283).
// Usage   : python tools/dev.py test --filter UiComposite
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using NUnit.Framework;
using graveyard_shift.Core;

namespace graveyard_shift.Tests
{
    public class UiCompositeTests
    {
        private const int TOLERANCE = 1;                          // the GPU rounds once, we round once
        private static readonly byte[] CAMERA = { 51, 102, 153 };

        // { panel texture r, g, b, a } -> { screen r, g, b }
        private static readonly byte[][] GAMMA =
        {
            new byte[] { 128, 121, 96, 128 }, new byte[] { 153, 172, 172 },     // hit flash at 0.5
            new byte[] { 0, 0, 0, 153 }, new byte[] { 20, 41, 61 },             // pause shade
            new byte[] { 30, 35, 54, 245 }, new byte[] { 32, 39, 60 },          // panel at 0.96
            new byte[] { 64, 0, 0, 64 }, new byte[] { 102, 76, 115 },           // red at 0.25
            new byte[] { 232, 237, 247, 255 }, new byte[] { 232, 237, 247 },    // opaque text colour
        };

        private static readonly byte[][] LINEAR =
        {
            new byte[] { 188, 178, 140, 128 }, new byte[] { 191, 189, 173 },
            new byte[] { 0, 0, 0, 153 }, new byte[] { 30, 65, 100 },
            new byte[] { 30, 35, 55, 245 }, new byte[] { 32, 41, 64 },
            new byte[] { 137, 0, 0, 64 }, new byte[] { 143, 89, 134 },
            new byte[] { 232, 237, 247, 255 }, new byte[] { 232, 237, 247 },
        };

        private static void Check(byte[][] cases, bool linearLight)
        {
            for (int k = 0; k < cases.Length; k += 2)
            {
                byte[] top = cases[k], want = cases[k + 1];
                for (int c = 0; c < 3; c++)
                {
                    byte got = UiComposite.Over(CAMERA[c], top[c], top[3], linearLight);
                    Assert.That(Math.Abs(got - want[c]), Is.LessThanOrEqualTo(TOLERANCE),
                        $"panel ({string.Join(", ", top)}) channel {c}: {got}, the player showed {want[c]}");
                }
            }
        }

        [Test]
        public void UiComposite_GammaProjectMatchesThePlayersScreen()
        {
            Check(GAMMA, false);
        }

        [Test]
        public void UiComposite_LinearProjectBlendsInLinearLight()
        {
            Check(LINEAR, true);
        }

        [Test]
        public void UiComposite_TransparentLeavesThePictureAndOpaqueReplacesIt()
        {
            foreach (bool linear in new[] { false, true })
            {
                Assert.AreEqual(77, UiComposite.Over(77, 0, 0, linear));
                Assert.AreEqual(200, UiComposite.Over(77, 200, 255, linear));
                Assert.AreEqual(255, UiComposite.Over(255, 255, 128, linear), "an overbright sum is clamped");
            }
        }

        [Test]
        public void UiComposite_LayerIsStretchedOverThePictureAndKeepsItOpaque()
        {
            // A 2x1 RGBA picture under a 1x1 layer (black at 0.6): both pixels are shaded, alpha stays 255
            byte[] picture = { 51, 102, 153, 255, 51, 102, 153, 255 };
            byte[] layer = { 0, 0, 0, 153 };
            UiComposite.Over(picture, 2, 1, 4, layer, 1, 1, false);
            CollectionAssert.AreEqual(new byte[] { 20, 41, 61, 255, 20, 41, 61, 255 }, picture);
            // RGB24 under a 2x1 layer whose left pixel is transparent: only the right one changes
            byte[] rgb = { 10, 20, 30, 10, 20, 30 };
            byte[] half = { 0, 0, 0, 0, 100, 100, 100, 255 };
            UiComposite.Over(rgb, 2, 1, 3, half, 2, 1, true);
            CollectionAssert.AreEqual(new byte[] { 10, 20, 30, 100, 100, 100 }, rgb);
        }

        [Test]
        public void UiComposite_RefusesArraysThatDoNotFit()
        {
            Assert.Throws<ArgumentException>(() => UiComposite.Over(new byte[3], 2, 1, 3, new byte[4], 1, 1, false));
            Assert.Throws<ArgumentException>(() => UiComposite.Over(new byte[8], 2, 1, 4, new byte[4], 2, 1, false));
            Assert.Throws<ArgumentException>(() => UiComposite.Over(new byte[2], 1, 1, 2, new byte[4], 1, 1, false));
            Assert.Throws<ArgumentNullException>(() => UiComposite.Over(null, 1, 1, 3, new byte[4], 1, 1, false));
        }

        [Test]
        public void UiComposite_OpaqueDropsAScreenCapturesAlpha()
        {
            // a windowed player's back buffer, read for the F8 screenshot: the camera cleared to alpha 0 here (#283)
            byte[] rgba = { 10, 20, 30, 0, 40, 50, 60, 128, 70, 80, 90, 255 };
            UiComposite.Opaque(rgba);
            CollectionAssert.AreEqual(new byte[] { 10, 20, 30, 255, 40, 50, 60, 255, 70, 80, 90, 255 }, rgba);
            Assert.Throws<ArgumentNullException>(() => UiComposite.Opaque(null));
        }
    }
}
