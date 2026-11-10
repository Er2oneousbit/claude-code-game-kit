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
//           ignored, not failed. Analog (#274): on the Input System the virtual pad's stick and triggers reach the
//           game shaped (deadzone, invert_y) with its held buttons; on the Input Manager the stick and trigger axes must
//           exist and rest at 0, and the shaping path is fed through InjectAnalog (both backends run that one).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): analog stick, triggers and held game actions (#274)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a drive (Scripted) reads no real device (#276), the
//           hardware stood in for by ShellInput.DeviceSnapshot
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
using graveyard_shift.Core;
using graveyard_shift.Shell;
#if GAMEKIT_INPUT_SYSTEM && ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
#endif

namespace graveyard_shift.Tests
{
    public class ShellInputTests
    {
        private const float DT = 1f / 60f;
        private const float EPS = 1e-4f;

        // The defaults with one slot rebound (a fresh map each time)
        private static Dictionary<string, object> Rebound(string action, int slot, string binding)
        {
            return Bindings.Rebind(Bindings.Defaults(), action, slot, binding).Bindings;
        }

        [TearDown]
        public void Reset()
        {
            ShellInput.Configure(Bindings.Defaults(), false);
            ShellInput.ConfigureAnalog(0.2, false);
            ShellInput.ClearAnalog();
            ShellInput.Scripted = false;
            ShellInput.DeviceSnapshot = null;
            ShellInput.Begin(DT);                               // nothing held over into the next test
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
        public void Scripted_ADriveReadsNoRealDeviceButNormalPlayDoes()
        {
            // #276: a stray key or a virtual pad on a shared machine opened screens during a windowed drive. The
            // stand-in snapshot is what the backend reads from the hardware: D (move_right) and pad south (ui_accept)
            // held down, as a player or a stray device holds them.
            ShellInput.Configure(Bindings.Defaults(), false);
            ShellInput.DeviceSnapshot = held => { held.Add("key:d"); held.Add("pad:south"); };
            ShellInput.Inject("ui_down", "pad_xbox");          // the drive's own press: the prompts on a pad
            ShellInput.Scripted = true;
            ShellInput.Begin(DT);
            Assert.IsTrue(ShellInput.JustPressed("ui_down"), "the drive's press counts");
            Assert.IsFalse(ShellInput.IsHeld("move_right"), "the real D key holds nothing during a drive");
            Assert.IsFalse(ShellInput.JustPressed("ui_accept"), "the real pad button presses nothing");
            Assert.AreEqual("pad_xbox", ShellInput.LastDevice, "the prompts stay on the drive's device");
            ShellInput.Begin(DT);
            Assert.IsFalse(ShellInput.IsHeld("move_right"));
            ShellInput.Scripted = false;                         // normal play: the same hardware is read
            ShellInput.Begin(DT);
            Assert.IsTrue(ShellInput.IsHeld("move_right"));
            Assert.IsTrue(ShellInput.JustPressed("ui_accept"));
            Assert.AreEqual("keyboard", ShellInput.LastDevice);
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

        [Test]
        public void Analog_HeldStickAndTriggersAreShapedForTheGame()
        {
            if (!ShellInput.Polls)
            {
                Assert.Ignore("ui_events backend: no analog values (install the Input System package)");
            }
            ShellInput.Configure(Bindings.Defaults(), false);
            ShellInput.ConfigureAnalog(0.2, false);
            ShellInput.InjectAnalog(new Vector2(0.6f, 0f), 0.525f, 1f);
            ShellInput.Begin(DT);
            Assert.AreEqual(0.5f, ShellInput.Stick.x, EPS, "radial deadzone 0.2, rescaled from 0");
            Assert.AreEqual(0f, ShellInput.Stick.y, EPS);
            Assert.AreEqual(0.5f, ShellInput.LeftTrigger, EPS);
            Assert.AreEqual(1f, ShellInput.RightTrigger, EPS);
            Assert.IsTrue(ShellInput.IsGameHeld("move_right"), "the stick past the deadzone holds move_right");
            Assert.AreEqual(0.5f, ShellInput.MoveVector().x, EPS, "a half-leaned stick: half speed");
            ShellInput.InjectAnalog(new Vector2(0.1f, 0.1f), 0.04f, 0f);
            ShellInput.Begin(DT);
            Assert.AreEqual(Vector2.zero, ShellInput.Stick, "inside the deadzone");
            Assert.AreEqual(0f, ShellInput.LeftTrigger, "inside the trigger's own deadzone");
            CollectionAssert.IsEmpty(ShellInput.HeldGameActions);
            ShellInput.ConfigureAnalog(0.2, true);
            ShellInput.InjectAnalog(new Vector2(0f, 1f), 0f, 0f);
            ShellInput.Begin(DT);
            Assert.AreEqual(-1f, ShellInput.Stick.y, EPS, "invert_y");
            Assert.IsTrue(ShellInput.IsGameHeld("move_down"));
            Assert.IsFalse(ShellInput.IsGameHeld("move_up"));
        }

#if !(GAMEKIT_INPUT_SYSTEM && ENABLE_INPUT_SYSTEM) && ENABLE_LEGACY_INPUT_MANAGER
        [Test]
        public void InputManager_StickAndTriggerAxesExistAndRestAtZero()
        {
            Assert.IsTrue(ShellInput.AnalogReadable,
                "the Input Manager lacks the GameKit stick or trigger axes: run python tools/dev.py exec GameKitScenes.AddInputAxes");
            ShellInput.Begin(DT);
            ShellInput.Begin(DT);
            Assert.AreEqual(Vector2.zero, ShellInput.Stick, "the stick moved with no pad touched");
            Assert.AreEqual(0f, ShellInput.LeftTrigger);
            Assert.AreEqual(0f, ShellInput.RightTrigger);
            CollectionAssert.IsEmpty(ShellInput.HeldGameActions);
        }
#endif

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
        public void InputSystem_StickTriggersAndHeldActionsReachTheGame()
        {
            ShellInput.Configure(Bindings.Defaults(), false);
            ShellInput.ConfigureAnalog(0.2, false);
            Assert.IsTrue(ShellInput.AnalogReadable);
            Settle();
            Pad(new GamepadState(GamepadButton.West) { leftStick = new Vector2(0.6f, 0f), rightTrigger = 0.525f });
            ShellInput.Begin(DT);
            Assert.AreEqual(0.6f, ShellInput.RawStick.x, EPS, "the unprocessed stick (no Input System deadzone on top)");
            Assert.AreEqual(0.5f, ShellInput.Stick.x, EPS);
            Assert.AreEqual(0.5f, ShellInput.RightTrigger, EPS);
            Assert.AreEqual(0f, ShellInput.LeftTrigger, EPS);
            Assert.IsTrue(ShellInput.IsGameHeld("attack"), "pad west (attack) held");
            Assert.IsTrue(ShellInput.IsGameHeld("move_right"), "the stick holds move_right");
            foreach (string action in ShellInput.HeldGameActions)
            {
                Assert.IsFalse(action.StartsWith("ui_"), $"{action} is a menu action");
            }
            ShellInput.ConfigureAnalog(0.2, true);
            Pad(new GamepadState { leftStick = new Vector2(0f, 1f) });
            ShellInput.Begin(DT);
            Assert.AreEqual(-1f, ShellInput.Stick.y, EPS, "invert_y");
            Assert.IsTrue(ShellInput.IsGameHeld("move_down"));
            Assert.IsFalse(ShellInput.IsGameHeld("attack"), "released");
            Pad(new GamepadState());
            Keys(Key.D);
            ShellInput.Begin(DT);
            Assert.AreEqual(1f, ShellInput.MoveVector().x, EPS, "a held move key gives a unit direction");
            Assert.AreEqual(Vector2.zero, ShellInput.Stick);
            Keys();
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
