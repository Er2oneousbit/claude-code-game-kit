// ---------------------------------------------------------------------------
// PlayWorld.cs
// Purpose : The placeholder "game" behind the shell: a dark field, the control hints on the device in use, and the
//           subtitle bar playing the sample line, so the pause menu, "What now?", the history and the access sweep
//           have a world to sit on. Replace it with your game: FrontEnd.StartPlay() builds the world you give it.
// Usage   : FrontEnd calls new PlayWorld(front).Build(layer), Tick(dt) each frame, Dispose() on quit to title
// Notes   : The HUD text is outlined (UiTheme.Outline) so it reads over any game. The sample line (guide.intro) plays
//           after INTRO_DELAY_S; the goal for "What now?" is set on entry (Shell.SetObjective). The world layer is
//           drawn under the screens; the camera's own picture is behind it (the layer is see-through).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a ShellWorld (the juice demo is the other one, #275)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

namespace {{GAME_SLUG}}.Shell
{
    public sealed class PlayWorld : ShellWorld
    {
        // ---- Tunables ------------------------------------------------------------
        public const float INTRO_DELAY_S = 0.5f;       // game seconds before the sample line plays
        public const string INTRO_LINE = "guide.intro";
        public static readonly string[] HINT_ACTIONS = { "move_left", "move_right", "jump", "attack", "interact", "pause" };

        private readonly FrontEnd _front;
        private VisualElement _root;
        private Label _hint;
        private float _t;
        private bool _introPlayed;

        public PlayWorld(FrontEnd front)
        {
            _front = front;
        }

        public override string Name => "play";

        public override void Build(VisualElement layer)
        {
            Shell s = Shell.I;
            _root = new VisualElement { name = "World", pickingMode = PickingMode.Ignore };
            _root.style.position = Position.Absolute;
            _root.style.left = 0;
            _root.style.top = 0;
            _root.style.right = 0;
            _root.style.bottom = 0;
            layer.Add(_root);
            var centre = new Label(s.T("play.placeholder", new Dictionary<string, object> { { "pause", s.BindingText(s.PromptFor("pause")) } }))
                { name = "Placeholder", pickingMode = PickingMode.Ignore };
            UiTheme.Text(centre, 1.0f, UiTheme.TEXT_DIM);
            UiTheme.Outline(centre);
            centre.style.position = Position.Absolute;
            centre.style.left = Length.Percent(10);
            centre.style.right = Length.Percent(10);
            centre.style.top = Length.Percent(45);
            centre.style.unityTextAlign = TextAnchor.MiddleCenter;
            _root.Add(centre);
            _hint = new Label("") { name = "Hint", pickingMode = PickingMode.Ignore };
            UiTheme.Text(_hint, 1.0f, UiTheme.TEXT);
            UiTheme.Outline(_hint);
            _hint.style.position = Position.Absolute;
            _hint.style.left = 16;
            _hint.style.top = 12;
            _hint.style.right = 16;
            _root.Add(_hint);
            RefreshHint();
            _root.Add(Subtitles.Root);
            s.SetObjective(s.T("demo.objective"));
            s.SettingsChanged += OnSettingsChanged;
            ShellInput.DeviceChanged += OnDevice;
        }

        public override void Dispose()
        {
            Shell.I.SettingsChanged -= OnSettingsChanged;
            ShellInput.DeviceChanged -= OnDevice;
            _root?.RemoveFromHierarchy();
            _root = null;
        }

        public override void Tick(float dt)
        {
            _t += dt;
            if (!_introPlayed && _t >= INTRO_DELAY_S)
            {
                _introPlayed = true;
                Subtitles.Play(INTRO_LINE);
            }
            Subtitles.Tick(dt);
        }

        /// <summary>The hint line: every play action with its binding on the device in use.</summary>
        public void RefreshHint()
        {
            Shell s = Shell.I;
            var args = new Dictionary<string, object>();
            foreach (string action in HINT_ACTIONS)
            {
                args[action.Replace("move_", "")] = s.BindingText(s.PromptFor(action));
            }
            _hint.text = s.T("play.hint", args);
        }

        private void OnSettingsChanged(string section, string key)
        {
            Subtitles.OnSettingsChanged(section, key);
            if (section == "input" || section == "access" || section == "language")
            {
                RefreshHint();
            }
        }

        private void OnDevice(string device)
        {
            RefreshHint();
        }
    }
}

// {{FOOTER}}
