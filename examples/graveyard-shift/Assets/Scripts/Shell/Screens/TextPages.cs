// ---------------------------------------------------------------------------
// TextPages.cs
// Purpose : The screens that are a heading, scrolling text and Back: "What now?" (the goal, the last line said,
//           the controls: #167, cognitive access), "Dialogue history" (every line said so far, newest last: #167),
//           Credits (CREDITS.md without its HTML comments, Core/CreditsText.cs; or a placeholder) and Loading.
// Usage   : front.OpenHelp(); front.OpenHistory(); front.OpenCredits(); front.Push(new LoadingScreen(front))
// Notes   : Up and down scroll the text (Back keeps the focus); accept or cancel goes back. The goal is whatever
//           the game last set (Shell.SetObjective; empty: "no goal set yet"); the last line and the history come
//           from Shell.History (the subtitle bar records every line it shows). Controls follow the device in use.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine.UIElements;
using graveyard_shift.Core;

namespace graveyard_shift.Shell.Screens
{
    /// <summary>A heading, a scrolling body and a Back button; subclasses fill the body.</summary>
    public abstract class TextPage : ShellScreen
    {
        public const float SCROLL_STEP_PX = 48f;
        protected ScrollView Body;

        protected TextPage(FrontEnd front, string name) : base(front, name)
        {
        }

        protected abstract string Title { get; }
        protected abstract void Fill(VisualElement body);

        protected override void BuildContent()
        {
            VisualElement col = Column();
            Heading(col, Title);
            Body = Scroll(col);
            var inner = new VisualElement { name = "Body" };
            inner.style.flexDirection = FlexDirection.Column;
            Body.Add(inner);
            Fill(inner);
            var bottom = new VisualElement { name = "Bottom" };
            bottom.style.flexDirection = FlexDirection.Row;
            bottom.style.marginTop = 12f;
            col.Add(bottom);
            AddRow(Button(bottom, S.T("settings.back"), "Back", Front.Back));
        }

        public override bool HandleAction(string action)
        {
            if (action == "ui_up" || action == "ui_down")
            {
                Body.scrollOffset += new UnityEngine.Vector2(0, action == "ui_up" ? -SCROLL_STEP_PX : SCROLL_STEP_PX);
                return true;
            }
            return base.HandleAction(action);
        }

        protected Label Paragraph(VisualElement body, string text, string name, bool dim = false)
        {
            Label l = Text(body, text, name, 1.0f, dim);
            l.style.marginBottom = 8f + UiTheme.Gap();
            return l;
        }
    }

    public sealed class HelpScreen : TextPage
    {
        public static readonly string[] CONTROL_ACTIONS = { "move_left", "move_right", "jump", "attack", "interact", "pause" };

        public HelpScreen(FrontEnd front) : base(front, "help")
        {
        }

        protected override string Title => S.T("help.title");

        protected override void Fill(VisualElement body)
        {
            string goal = S.Objective;
            Paragraph(body, goal != "" ? S.T("help.objective", new Dictionary<string, object> { { "text", goal } })
                                       : S.T("help.no_objective"), "Objective");
            if (S.History.Count > 0)
            {
                (string name, string text) = S.History[S.History.Count - 1];
                Paragraph(body, S.T("help.last_line", new Dictionary<string, object>
                    { { "name", S.Content(name) }, { "text", S.Content(text) } }), "LastLine");
            }
            Paragraph(body, S.T("help.controls"), "ControlsHeading", true);
            foreach (string action in CONTROL_ACTIONS)
            {
                Paragraph(body, S.T("action." + action) + ": " + S.BindingText(S.PromptFor(action)), "Control_" + action);
            }
        }
    }

    public sealed class HistoryScreen : TextPage
    {
        public HistoryScreen(FrontEnd front) : base(front, "history")
        {
        }

        protected override string Title => S.T("history.title");

        protected override void Fill(VisualElement body)
        {
            if (S.History.Count == 0)
            {
                Paragraph(body, S.T("history.empty"), "Empty");
            }
            for (int i = 0; i < S.History.Count; i++)
            {
                (string name, string text) = S.History[i];
                Paragraph(body, S.T("help.last_line", new Dictionary<string, object>
                    { { "name", S.Content(name) }, { "text", S.Content(text) } }), "Line_" + i);
            }
            // newest last: start scrolled to the end once the layout is known
            Body.schedule.Execute(() => Body.scrollOffset = new UnityEngine.Vector2(0, float.MaxValue)).ExecuteLater(1);
        }
    }

    public sealed class CreditsScreen : TextPage
    {
        public CreditsScreen(FrontEnd front) : base(front, "credits")
        {
        }

        protected override string Title => S.T("credits.title");

        protected override void Fill(VisualElement body)
        {
            // HTML comments out (tools/credits.py writes one, #279), one paragraph per block (Core/CreditsText.cs)
            List<string> blocks = CreditsText.Blocks(ShellFiles.ReadOrNull(Shell.CREDITS_FILE));
            if (blocks == null)
            {
                Paragraph(body, S.T("credits.placeholder"), "Placeholder");
                return;
            }
            for (int i = 0; i < blocks.Count; i++)
            {
                Paragraph(body, S.Content(blocks[i]), "Credits_" + i);
            }
        }
    }

    /// <summary>Shown while the game's world is set up: a heading, nothing to press.</summary>
    public sealed class LoadingScreen : ShellScreen
    {
        public LoadingScreen(FrontEnd front) : base(front, "loading")
        {
        }

        protected override void BuildContent()
        {
            VisualElement col = Column(true);
            Heading(col, S.T("loading.title"));
        }

        public override bool HandleAction(string action)
        {
            return true;     // nothing to press while loading
        }
    }
}
