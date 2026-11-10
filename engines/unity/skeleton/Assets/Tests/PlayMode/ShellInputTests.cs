// ---------------------------------------------------------------------------
// ShellInputTests.cs
// Purpose : ShellInput reads rebound bindings on the input backend this project compiles (#266): the Input System
//           package when it is installed and active, else the old Input Manager.
// Usage   : python tools/dev.py test --mode PlayMode --filter ShellInput
// Notes   : On the Input System a virtual gamepad and keyboard are added and fed state events (what a real device
//           sends, processed with InputSystem.Update), so a rebound pad trigger, a rebound key and pad capture are read back through the real
//           polling path. The Input Manager cannot be fed fake presses, so there the test rebinds a pad slot and
//           checks the backend can read it (its trigger axis exists: run GameKitScenes.CreateShellScene or
//           AddInputAxes first) and that nothing fires while no device is touched. Tests on the other backend are
//           ignored, not failed.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;
using {{GAME_SLUG}}.Shell;
#if GAMEKIT_INPUT_SYSTEM && ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
#endif

namespace {{GAME_SLUG}}.Tests
{
    public class ShellInputTests
    {
        private const float DT = 1f / 60f;

        // The defaults with one slot rebound (a fresh map each time)
        private static Dictionary<string, object> Rebound(string action, int slot, string binding)
        {
            return Bindings.Rebind(Bindings.Defaults(), action, slot, binding).Bindings;
        }

        [TearDown]
        public void Reset()
        {
            ShellInput.Configure(Bindings.Defaults(), false);
        }

        [Test]
        public void Backend_MatchesTheActiveInputHandler()
        {
#if GAMEKIT_INPUT_SYSTEM && ENABLE_INPUT_SYSTEM
            Assert.AreEqual("input_system", ShellInput.Backend);
#elif ENABLE_LEGACY_INPUT_MANAGER
            Assert.AreEqual("input_manager", ShellInput.Backend);
#else
            Assert.AreEqual("ui_events", ShellInput.Backend, "the Input System is active without its package");
#endif
            Assert.AreEqual(ShellInput.Backend != "ui_events", ShellInput.Polls);
        }

        [Test]
        public void ReboundPadSlot_IsReadableOnThisBackend()
        {
            if (!ShellInput.Polls)
            {
                Assert.Ignore("ui_events backend: install the Input System package to read pad bindings");
            }
            ShellInput.Configure(Rebound("ui_accept", Bindings.PAD_SLOT, "pad:r2"), false);
            Assert.IsTrue(ShellInput.HasGamepad("ui_accept"));
            Assert.IsTrue(ShellInput.CanRead("pad:r2"),
                $"{ShellInput.Backend} cannot read pad:r2 (Input Manager: run python tools/dev.py exec GameKitScenes.AddInputAxes)");
            Assert.IsTrue(ShellInput.CanRead("pad:l2"));
            Assert.IsTrue(ShellInput.CanRead("pad:west"));
            Assert.IsTrue(ShellInput.CanRead("pad:dpad_up"));
            Assert.IsTrue(ShellInput.CanRead("pad_axis:leftx-"));
            Assert.IsTrue(ShellInput.CanRead("key:k"));
            Assert.IsFalse(ShellInput.CanRead("pad:nonsense"));
            Assert.IsFalse(ShellInput.CanRead("key:nonsense"));
        }

#if GAMEKIT_INPUT_SYSTEM && ENABLE_INPUT_SYSTEM
        private Gamepad _pad;
        private Keyboard _keyboard;
        private InputSettings.BackgroundBehavior _background;
        private InputSettings.EditorInputBehaviorInPlayMode _editorInput;

        [SetUp]
        public void AddDevices()
        {
            // batchmode has no focused game view: let the test devices' events through anyway
            _background = InputSystem.settings.backgroundBehavior;
            _editorInput = InputSystem.settings.editorInputBehaviorInPlayMode;
            InputSystem.settings.backgroundBehavior = InputSettings.BackgroundBehavior.IgnoreFocus;
            InputSystem.settings.editorInputBehaviorInPlayMode = InputSettings.EditorInputBehaviorInPlayMode.AllDeviceInputAlwaysGoesToGameView;
            _pad = InputSystem.AddDevice<Gamepad>("GameKitTestPad");
            _keyboard = InputSystem.AddDevice<Keyboard>("GameKitTestKeyboard");
            _pad.MakeCurrent();
            _keyboard.MakeCurrent();
        }

        [TearDown]
        public void RemoveDevices()
        {
            if (_pad != null) InputSystem.RemoveDevice(_pad);
            if (_keyboard != null) InputSystem.RemoveDevice(_keyboard);
            InputSystem.settings.backgroundBehavior = _background;
            InputSystem.settings.editorInputBehaviorInPlayMode = _editorInput;
        }

        // The whole pad (or keyboard) state as one event, processed now: what a real device sends
        private void Pad(GamepadState state)
        {
            InputSystem.QueueStateEvent(_pad, state);
            InputSystem.Update();
        }

        private void Keys(params Key[] down)
        {
            InputSystem.QueueStateEvent(_keyboard, new KeyboardState(down));
            InputSystem.Update();
        }

        private static void Settle()
        {
            ShellInput.Begin(DT);
            ShellInput.Begin(DT);
        }

        [Test]
        public void InputSystem_ReboundTriggerFiresAndTheOldButtonDoesNot()
        {
            ShellInput.Configure(Rebound("ui_accept", Bindings.PAD_SLOT, "pad:r2"), false);
            Settle();
            Pad(new GamepadState(GamepadButton.South));            // the default pad:south, no longer ui_accept's
            ShellInput.Begin(DT);
            Assert.IsFalse(ShellInput.JustPressed("ui_accept"), "pad:south still fires ui_accept after the rebind");
            Pad(new GamepadState { rightTrigger = 0.3f });        // under AXIS_PRESS: not a press
            ShellInput.Begin(DT);
            Assert.IsFalse(ShellInput.JustPressed("ui_accept"));
            Pad(new GamepadState { rightTrigger = 1f });
            ShellInput.Begin(DT);
            Assert.IsTrue(ShellInput.JustPressed("ui_accept"), "the rebound trigger did not fire ui_accept");
            Assert.IsTrue(ShellInput.LastDevice.StartsWith("pad_"), ShellInput.LastDevice);
            ShellInput.Begin(DT);
            Assert.IsFalse(ShellInput.JustPressed("ui_accept"), "a held trigger pressed twice");
            Assert.IsTrue(ShellInput.IsHeld("ui_accept"));
            Pad(new GamepadState());
            ShellInput.Begin(DT);
            Assert.IsFalse(ShellInput.IsHeld("ui_accept"));
        }

        [Test]
        public void InputSystem_ReboundKeyAndDpadFire()
        {
            ShellInput.Configure(Rebound("jump", Bindings.KEYBOARD_SLOT, "key:k"), false);
            Settle();
            Keys(Key.K);
            ShellInput.Begin(DT);
            Assert.IsTrue(ShellInput.JustPressed("jump"), "the rebound key did not fire jump");
            Assert.AreEqual("keyboard", ShellInput.LastDevice);
            Keys();
            Pad(new GamepadState(GamepadButton.DpadUp));
            ShellInput.Begin(DT);
            Assert.IsTrue(ShellInput.JustPressed("ui_up"), "dpad up did not fire ui_up");
        }

        [Test]
        public void InputSystem_CaptureReadsPadButtonsAndTriggers()
        {
            Settle();
            Assert.IsNull(ShellInput.CaptureBinding(Bindings.PAD_SLOT), "the first capture call must skip its frame");
            Pad(new GamepadState { leftTrigger = 1f });
            ShellInput.Begin(DT);
            Assert.AreEqual("pad:l2", ShellInput.CaptureBinding(Bindings.PAD_SLOT));
            Pad(new GamepadState(GamepadButton.West));
            ShellInput.Begin(DT);
            Assert.AreEqual("pad:west", ShellInput.CaptureBinding(Bindings.PAD_SLOT));
            Pad(new GamepadState());
            Keys(Key.Q);
            ShellInput.Begin(DT);
            Assert.AreEqual("key:q", ShellInput.CaptureBinding(Bindings.KEYBOARD_SLOT));
            Keys();
        }
#endif
    }
}

// {{FOOTER}}
