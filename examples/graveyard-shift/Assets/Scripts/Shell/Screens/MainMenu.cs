// ---------------------------------------------------------------------------
// MainMenu.cs
// Purpose : The main menu: Play, Settings, Credits, Quit.
// Usage   : front.OpenMainMenu()
// Notes   : Cancel on the main menu goes back to the title. Quit asks the front end (a player quits; in the editor
//           and in a PlayMode test it only records the wish).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using UnityEngine.UIElements;

namespace graveyard_shift.Shell.Screens
{
    public sealed class MainMenu : ShellScreen
    {
        public MainMenu(FrontEnd front) : base(front, "main_menu")
        {
        }

        protected override void BuildContent()
        {
            VisualElement col = Column(true);
            Heading(col, S.T("game.title"), "Heading", UiTheme.TITLE);
            AddRow(Button(col, S.T("menu.play"), "Play", Front.StartPlay));
            AddRow(Button(col, S.T("menu.settings"), "Settings", Front.OpenSettings));
            AddRow(Button(col, S.T("menu.credits"), "Credits", Front.OpenCredits));
            AddRow(Button(col, S.T("menu.quit"), "Quit", Front.QuitGame));
        }

        public override void OnCancel()
        {
            Front.ShowTitle();
        }
    }
}
