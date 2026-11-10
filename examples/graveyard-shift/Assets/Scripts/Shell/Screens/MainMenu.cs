// ---------------------------------------------------------------------------
// MainMenu.cs
// Purpose : The main menu: Play, Juice demo (editor and development builds), Settings, Credits, Quit.
// Usage   : front.OpenMainMenu()
// Notes   : Cancel on the main menu goes back to the title. Quit asks the front end (a player quits; in the editor
//           and in a PlayMode test it only records the wish).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the juice demo entry (#275)
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
            Heading(col, S.GameTitle(), "Heading", UiTheme.TITLE);
            AddRow(Button(col, S.T("menu.play"), "Play", Front.StartPlay));
            if (JuiceWorld.Available)
            {
                AddRow(Button(col, S.T("menu.juice"), "JuiceDemo", Front.StartJuice));
            }
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
