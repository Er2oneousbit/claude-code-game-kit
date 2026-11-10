// ---------------------------------------------------------------------------
// PauseMenu.cs
// Purpose : The pause menu over the running game: Resume, What now?, Dialogue history, Settings, Quit to title.
// Usage   : front.Pause()   (the pause action, or when the window loses focus)
// Notes   : The game is paused (Time.timeScale 0) while this is open; the menus run on unscaled time. Cancel or the
//           pause action again resumes. The column sits on an opaque panel over a see-through shade, so its text
//           reads whatever the game behind it shows (#167 put What now? and the history here: both reachable from
//           any point of play).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using UnityEngine.UIElements;

namespace {{GAME_SLUG}}.Shell.Screens
{
    public sealed class PauseMenu : ShellScreen
    {
        public PauseMenu(FrontEnd front) : base(front, "pause")
        {
            Opaque = false;    // the paused game stays visible behind the shade
        }

        protected override void BuildContent()
        {
            var shade = new VisualElement { name = "Backdrop" };
            shade.style.position = Position.Absolute;
            shade.style.left = 0;
            shade.style.top = 0;
            shade.style.right = 0;
            shade.style.bottom = 0;
            shade.style.backgroundColor = UiTheme.BACKDROP;
            Root.Add(shade);
            VisualElement col = Column(true);
            var panel = new VisualElement { name = "Panel" };
            panel.style.flexDirection = FlexDirection.Column;
            panel.style.alignItems = Align.Center;
            UiTheme.Panel(panel, UiTheme.PANEL, 24f);
            UiTheme.Border(panel, UiTheme.BORDER, 1);
            panel.style.maxWidth = Length.Percent(96);
            col.Add(panel);
            Heading(panel, S.T("pause.title"), "Heading");
            AddRow(Button(panel, S.T("pause.resume"), "Resume", Front.Resume));
            AddRow(Button(panel, S.T("pause.help"), "Help", Front.OpenHelp));           // #167: what now, and what was said
            AddRow(Button(panel, S.T("pause.history"), "History", Front.OpenHistory));
            AddRow(Button(panel, S.T("menu.settings"), "Settings", Front.OpenSettings));
            AddRow(Button(panel, S.T("pause.quit_to_title"), "QuitToTitle", Front.QuitToTitle));
        }

        public override void OnCancel()
        {
            Front.Resume();
        }

        public override bool HandleAction(string action)
        {
            if (action == "pause")
            {
                Front.Resume();
                return true;
            }
            return base.HandleAction(action);
        }
    }
}

// {{FOOTER}}
