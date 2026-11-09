// ---------------------------------------------------------------------------
// SubtitleBar.cs
// Purpose : Subtitles and sound captions at the bottom of the screen, read from a dialogue.built.json file and
//           styled by the player's settings (on/off, size, background opacity, speaker names, barks, captions,
//           subtitles that wait for the player).
// Usage   : var bar = new SubtitleBar(); hud.Add(bar.Root);  bar.Tick(dt) once a frame (game time)
//           bar.Play("guide.intro")               // a line id from data/dialogue/sample.built.json
//           bar.Caption("box_hit")                // an SFX caption ("[box thuds]"), only with captions_sfx on
//           bar.Caption("growl", dx, dy, halfW, halfH)   // "← [growl]" from off screen, left
// Notes   : Shows the file's cues (at most two lines of about 40 characters each) or the whole text. Barks (kind
//           "bark") appear only with subtitle_barks on. Time runs on the delta given, so pausing the game pauses the
//           line. Text from the file goes through Shell.Content(), so the pseudo locale marks it too. Not colour
//           alone: the speaker name is text. With access.subtitle_hold a finished line stays until ui_accept
//           (#167). Every line shown is recorded for "Dialogue history". Same rules as the Godot, LÖVE and web bars.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public sealed class SubtitleBar
    {
        // ---- Tunables ------------------------------------------------------------
        public static readonly Dictionary<string, float> SIZE_FONT = new Dictionary<string, float>
        {
            { "small", 0.85f }, { "medium", 1.0f }, { "large", 1.35f }, { "xl", 1.7f },     // multiples of the body size
        };
        public const float SIDE_MARGIN = 96f;
        public const float BOTTOM_MARGIN = 28f;
        public const float CAPTION_MIN_S = 1.0f;
        public const float HOLD_BEFORE_END_S = 0.01f;   // subtitle_hold parks a line this far before its end

        public readonly VisualElement Root;
        private readonly VisualElement _panel;
        private readonly Label _speaker;
        private readonly Label _text;
        private readonly Label _caption;
        private Dictionary<string, object> _dialogue;
        private Dictionary<string, object> _line;
        private double _t;
        private float _captionLeft;
        private bool _held;

        public SubtitleBar()
        {
            Root = new VisualElement { name = "SubtitleBar", pickingMode = PickingMode.Ignore };
            Root.style.position = Position.Absolute;
            Root.style.left = SIDE_MARGIN;
            Root.style.right = SIDE_MARGIN;
            Root.style.bottom = BOTTOM_MARGIN;
            Root.style.flexDirection = FlexDirection.Column;
            Root.style.alignItems = Align.Center;
            _caption = MakeLabel("Caption");
            Root.Add(_caption);
            _panel = new VisualElement { name = "Panel", pickingMode = PickingMode.Ignore };
            _panel.style.flexDirection = FlexDirection.Column;
            _panel.style.alignItems = Align.Center;
            UiTheme.Panel(_panel, new Color(0, 0, 0, 0.6f), 6f);
            _panel.style.paddingLeft = 16f;
            _panel.style.paddingRight = 16f;
            Root.Add(_panel);
            _speaker = MakeLabel("Speaker");
            _panel.Add(_speaker);
            _text = MakeLabel("Text");
            _panel.Add(_text);
            _panel.style.display = DisplayStyle.None;
            _caption.style.display = DisplayStyle.None;
            _dialogue = DialogueData.Parse(ShellFiles.ReadOrNull(Shell.DIALOGUE_FILE));
            if (_dialogue == null)
            {
                Debug.LogWarning($"[WARN][subtitles] {Shell.DIALOGUE_FILE} is missing or not a built dialogue file");
            }
            Restyle();
        }

        /// <summary>Starts a line; false when it does not exist or the settings hide it.</summary>
        public bool Play(string id)
        {
            Dictionary<string, object> entry = DialogueData.Line(_dialogue, id);
            if (!DialogueData.ShouldShow(entry, Shell.I.Settings["access"] as Dictionary<string, object>))
            {
                return false;
            }
            _line = entry;
            _t = 0.0;
            _held = false;
            Shell.I.RecordLine(Str(entry, "name"), Str(entry, "text"));
            Restyle();
            Update();
            _panel.style.display = DisplayStyle.Flex;
            return true;
        }

        /// <summary>A sound caption for an audio event id; the offset (dx, dy, halfW, halfH) adds the arrow for a directional one.</summary>
        public bool Caption(string eventId, double? dx = null, double? dy = null, double? halfW = null, double? halfH = null)
        {
            if (!Shell.I.AccessOn("captions_sfx"))
            {
                return false;
            }
            Dictionary<string, object> entry = DialogueData.Caption(_dialogue, eventId);
            if (entry == null)
            {
                return false;
            }
            string arrow = "";
            bool directional = entry.TryGetValue("directional", out object d) && d is bool b && b;
            if (directional && dx.HasValue && dy.HasValue && halfW.HasValue && halfH.HasValue)
            {
                arrow = AudioAccess.CaptionArrow(dx.Value, dy.Value, halfW.Value, halfH.Value);
            }
            _caption.text = AudioAccess.WithArrow(Shell.I.Content(Str(entry, "text")), arrow);
            double minS = entry.TryGetValue("min_s", out object m) && Json.IsNumber(m) ? Json.ToNumber(m) : CAPTION_MIN_S;
            _captionLeft = Mathf.Max(CAPTION_MIN_S, (float)minS);
            _caption.style.display = DisplayStyle.Flex;
            return true;
        }

        public bool IsPlaying => _line != null;

        public bool IsFullyShown => _line != null && DialogueData.Revealed(_line, _t) >= DialogueData.Text(_line).Length;

        /// <summary>What the bar shows now: visible, speaker, text, id (the access sweep checks it against the line).</summary>
        public Dictionary<string, object> Shown()
        {
            bool visible = _panel.resolvedStyle.display != DisplayStyle.None && _line != null;
            return new Dictionary<string, object>
            {
                { "visible", visible },
                { "speaker", _speaker.resolvedStyle.display != DisplayStyle.None ? _speaker.text : "" },
                { "text", _text.text },
                { "id", _line != null ? Str(_line, "id") : "" },
            };
        }

        /// <summary>Once a frame with the game's delta (0 while paused).</summary>
        public void Tick(float dt)
        {
            if (_captionLeft > 0f)
            {
                _captionLeft -= dt;
                if (_captionLeft <= 0f)
                {
                    _caption.style.display = DisplayStyle.None;
                }
            }
            if (_line == null)
            {
                return;
            }
            if (_held)
            {
                // access.subtitle_hold (#167): a finished line waits on its last words until accept
                if (ShellInput.JustPressed("ui_accept") || !Shell.I.AccessOn("subtitle_hold"))
                {
                    Clear();
                }
                return;
            }
            _t += dt;
            if (DialogueData.Finished(_line, _t))
            {
                if (Shell.I.AccessOn("subtitle_hold"))
                {
                    _held = true;
                    _t = Mathf.Max(0f, (float)(DialogueData.Duration(_line) - HOLD_BEFORE_END_S));
                    Update();
                    return;
                }
                Clear();
                return;
            }
            Update();
        }

        public void OnSettingsChanged(string section, string key)
        {
            if (section == "access")
            {
                Restyle();
            }
        }

        private void Clear()
        {
            _held = false;
            _line = null;
            _panel.style.display = DisplayStyle.None;
        }

        private void Update()
        {
            string speaker = Str(_line, "name");
            bool showSpeaker = Shell.I.AccessOn("speaker_names") && speaker != "";
            _speaker.style.display = showSpeaker ? DisplayStyle.Flex : DisplayStyle.None;
            _speaker.text = Shell.I.Content(speaker);
            Color colour = UiTheme.FOCUS;
            if (_line.TryGetValue("color", out object c) && c is string hex && ColorUtility.TryParseHtmlString(hex, out Color parsed))
            {
                colour = parsed;
            }
            _speaker.style.color = colour;
            _text.text = Shell.I.Content(string.Join("\n", DialogueData.CueLines(_line, _t)));
        }

        private void Restyle()
        {
            string size = GameSettings.Text(Shell.I.Settings, "access", "subtitle_size");
            float mult = SIZE_FONT.TryGetValue(size, out float m) ? m : 1.0f;
            foreach (Label l in new[] { _speaker, _text, _caption })
            {
                UiTheme.Text(l, mult, UiTheme.TEXT);
                UiTheme.Outline(l);
                l.style.unityTextAlign = TextAnchor.MiddleCenter;
                l.style.marginBottom = 0;
            }
            _panel.style.backgroundColor = new Color(0, 0, 0, (float)GameSettings.Number(Shell.I.Settings, "access", "subtitle_background"));
            if (!Shell.I.AccessOn("subtitles") && _line != null)
            {
                Clear();
            }
        }

        private static Label MakeLabel(string name)
        {
            var l = new Label("") { name = name, pickingMode = PickingMode.Ignore };
            UiTheme.Text(l, 1.0f, UiTheme.TEXT);
            UiTheme.Outline(l);
            l.style.unityTextAlign = TextAnchor.MiddleCenter;
            return l;
        }

        private static string Str(Dictionary<string, object> entry, string key)
        {
            return entry != null && entry.TryGetValue(key, out object v) ? v as string ?? "" : "";
        }
    }
}

// {{FOOTER}}
