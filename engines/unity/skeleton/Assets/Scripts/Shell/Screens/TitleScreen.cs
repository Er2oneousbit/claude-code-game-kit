// ---------------------------------------------------------------------------
// TitleScreen.cs
// Purpose : The title: the game's name, "press any key or button", the version, and on the first launch the
//           telemetry question: Yes / No / Later.
// Usage   : front.ShowTitle()
// Notes   : The consent question shows while the setting is "unset", once per launch: Later keeps it unset, so the
//           next launch asks again; Yes or No is saved at once. Focus starts on Later, the choice that changes
//           nothing. Any menu action (not only accept) leaves the title once the question is answered.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine.UIElements;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell.Screens
{
    public sealed class TitleScreen : ShellScreen
    {
        private const float DIALOG_WIDTH = 560f;
        private VisualElement _dialog;

        public TitleScreen(FrontEnd front) : base(front, "title")
        {
        }

        public bool ConsentOpen => _dialog != null;

        protected override void BuildContent()
        {
            VisualElement col = Column(true);
            Label title = Heading(col, S.GameTitle(), "Title", UiTheme.TITLE);
            title.style.unityTextAlign = UnityEngine.TextAnchor.MiddleCenter;
            Label press = Text(col, S.T("title.press_any"), "PressAny");
            press.style.unityTextAlign = UnityEngine.TextAnchor.MiddleCenter;
            Label version = Text(col, S.T("title.version", new Dictionary<string, object> { { "version", S.Version } }), "Version", 0.8f, true);
            version.style.position = Position.Absolute;
            version.style.right = 0;
            version.style.bottom = 0;
            if (GameSettings.Text(S.Settings, "telemetry", "consent") == "unset" && !Front.ConsentAsked)
            {
                BuildConsent();
            }
        }

        public override void FocusFirst()
        {
            Control later = Find("Later");
            if (later != null)
            {
                Focus(later);
            }
        }

        public override bool HandleAction(string action)
        {
            if (ConsentOpen)
            {
                return base.HandleAction(action);
            }
            if (action.StartsWith("ui_") || action == "pause")
            {
                Front.OpenMainMenu();          // "press any key or button"
                return true;
            }
            return false;
        }

        public override void OnCancel()
        {
            if (ConsentOpen)
            {
                Answer("unset");
            }
            else
            {
                Front.OpenMainMenu();
            }
        }

        private void BuildConsent()
        {
            _dialog = new VisualElement { name = "Consent" };
            _dialog.style.position = Position.Absolute;
            _dialog.style.left = Length.Percent(50);
            _dialog.style.top = Length.Percent(50);
            _dialog.style.translate = new Translate(Length.Percent(-50), Length.Percent(-50));
            _dialog.style.width = DIALOG_WIDTH * UnityEngine.Mathf.Max(1f, UiTheme.TextScale * 0.8f);
            _dialog.style.maxWidth = Length.Percent(92);
            UiTheme.Panel(_dialog, UiTheme.PANEL, 20f);
            UiTheme.Border(_dialog, UiTheme.BORDER, 1);
            Root.Add(_dialog);
            Heading(_dialog, S.T("consent.title"), "ConsentTitle");
            Text(_dialog, S.T("consent.body"), "ConsentBody");
            var row = new VisualElement { name = "Choices" };
            row.style.flexDirection = FlexDirection.Row;
            row.style.flexWrap = Wrap.Wrap;
            row.style.marginTop = 12f;
            _dialog.Add(row);
            var cells = new List<Control>();
            foreach ((string choice, string name) in new[] { ("yes", "ConsentYes"), ("no", "ConsentNo"), ("unset", "Later") })
            {
                cells.Add(Button(row, S.T("consent." + choice), name, () => Answer(choice)));
            }
            AddRow(cells.ToArray());
        }

        private void Answer(string choice)
        {
            Front.ConsentAsked = true;
            if (choice != "unset")
            {
                S.SetValue("telemetry", "consent", choice);
                S.SaveSettings();
            }
            UnityEngine.Debug.Log($"[INFO][shell] telemetry consent: {choice}");
            _dialog.RemoveFromHierarchy();
            _dialog = null;
            Grid.Clear();
            Front.OnFocusChanged(this, null);
        }
    }
}

// {{FOOTER}}
