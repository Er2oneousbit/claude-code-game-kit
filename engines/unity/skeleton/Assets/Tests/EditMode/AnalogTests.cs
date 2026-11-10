// ---------------------------------------------------------------------------
// AnalogTests.cs
// Purpose : The analog shaping rules (Core/Analog.cs, #274): radial deadzone rescaled from 0, invert_y, triggers past
//           their own deadzone, the stick's move_* holds and the move vector. The same cases as Bevy's logic/analog.rs.
// Usage   : python tools/dev.py test --filter Analog
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public class AnalogTests
    {
        private const double EPS = 1e-5;

        private static void Close((double X, double Y) got, double x, double y)
        {
            Assert.AreEqual(x, got.X, EPS, $"x of {got}");
            Assert.AreEqual(y, got.Y, EPS, $"y of {got}");
        }

        [Test]
        public void Analog_InsideTheDeadzoneIsStillAndPastItRescalesFromZero()
        {
            Close(Analog.Stick(0.15, 0.1, 0.2, false), 0, 0);
            double x = Analog.Stick(0.21, 0.0, 0.2, false).X;       // just past: a small push, never a jump to 0.2
            Assert.That(x > 0.0 && x < 0.02, x.ToString());
            Close(Analog.Stick(0.6, 0.0, 0.2, false), 0.5, 0.0);
            Close(Analog.Stick(1.0, 0.0, 0.2, false), 1.0, 0.0);
            (double dx, double dy) = Analog.Stick(1.0, 1.0, 0.2, false);   // past full deflection: length 1, direction kept
            Assert.AreEqual(1.0, Math.Sqrt(dx * dx + dy * dy), EPS);
            Assert.AreEqual(dx, dy, 1e-6);
            Close(Analog.Stick(-0.3, 0.4, 0.0, false), -0.3, 0.4);   // no deadzone: the raw value
        }

        [Test]
        public void Analog_InvertYFlipsOnlyTheVerticalAxis()
        {
            Close(Analog.Stick(0.0, 1.0, 0.2, true), 0.0, -1.0);
            Close(Analog.Stick(1.0, 0.0, 0.2, true), 1.0, 0.0);
        }

        [Test]
        public void Analog_TriggersRescalePastTheirDeadzoneAndIgnoreBadValues()
        {
            Assert.AreEqual(0.0, Analog.Trigger(0.04, Analog.TRIGGER_DEADZONE));
            Assert.AreEqual(1.0, Analog.Trigger(1.0, Analog.TRIGGER_DEADZONE));
            Assert.AreEqual(0.5, Analog.Trigger(0.525, Analog.TRIGGER_DEADZONE), EPS);
            Assert.AreEqual(0.0, Analog.Trigger(-0.5, 0.0), "a trigger never goes negative");
            Assert.AreEqual(0.0, Analog.Trigger(double.NaN, 0.0));
            Close(Analog.Stick(double.NaN, 1.0, 0.0, false), 0.0, 1.0);
            Close(Analog.Stick(0.5, 0.0, 5.0, false), 0.0, 0.0);      // a deadzone past MAX_DEADZONE is clamped, not a division by 0
        }

        [Test]
        public void Analog_TheStickHoldsMoveActionsPastTheDeadzone()
        {
            CollectionAssert.AreEqual(new[] { "move_right" }, Analog.StickActions(0.6, 0.1, 0.2, false));
            CollectionAssert.AreEqual(new[] { "move_left", "move_up" }, Analog.StickActions(-0.7, 0.7, 0.2, false));
            CollectionAssert.AreEqual(new[] { "move_down" }, Analog.StickActions(0.0, 0.7, 0.2, true), "invert_y");
            CollectionAssert.IsEmpty(Analog.StickActions(0.15, 0.0, 0.0, false), "never below STICK_HOLD_MIN");
            CollectionAssert.IsEmpty(Analog.StickActions(0.45, 0.0, 0.5, false), "never below the player's deadzone");
        }

        [Test]
        public void Analog_MoveVectorAddsKeysAndTheStickUpToLengthOne()
        {
            Close(Analog.MoveVector(false, true, false, false, 0, 0), 1, 0);
            Close(Analog.MoveVector(false, true, true, false, 0, 0), Math.Sqrt(0.5), Math.Sqrt(0.5));
            Close(Analog.MoveVector(false, false, false, false, 0.5, 0), 0.5, 0);    // a half-leaned stick: half speed
            Close(Analog.MoveVector(false, true, false, false, 0.5, 0), 1, 0);       // key plus stick: never past 1
        }
    }
}

// {{FOOTER}}
