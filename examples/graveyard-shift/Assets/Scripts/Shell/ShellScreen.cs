// ---------------------------------------------------------------------------
// ShellScreen.cs
// Purpose : The base of every front-end screen (title, menu, settings, pause, ...): builds a UI Toolkit tree, keeps
//           its focusable controls in a grid (rows top to bottom, cells left to right) and moves focus with the
//           menu actions, so keyboard, gamepad and the smoke drive all walk the same explicit neighbours.
// Usage   : class MainMenu : ShellScreen { protected override void BuildContent() { Button(...); } }
//           front.Push(new MainMenu(front));   screen.HandleAction("ui_down")
// Notes   : Controls are plain VisualElements (focusable) with a Control record in userData: kind, label, value,
//           what accept and left/right do. Up and down walk the rows (same column, clamped) and wrap; left and
//           right step a slider or choice, or move along a row of buttons; accept activates; cancel calls
//           OnCancel (Back by default). Focus is also set on the UI Toolkit panel (Focus()), so the panel's
//           focusedElement and the access audit agree. The look comes from UiTheme; hover is not styled.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using graveyard_shift.Core;

namespace graveyard_shift.Shell
{
    /// <summary>One focusable control: what it is, what it says, what the menu actions do to it.</summary>
    public sealed class Control
    {
        public string Kind;             // button, toggle, slider, choice, binding
        public string Label;            // the row's name (settings) or the button's own text
        public Func<string> Value;      // "On", "70%", the chosen option; null for a plain button
        public Action Activate;         // ui_accept
        public Action<int> Step;        // ui_left (-1) / ui_right (+1); null: left and right move along the row
        public VisualElement Element;

        public string Name => Element != null ? Element.name : "";
    }

    public abstract class ShellScreen
    {
        // ---- Tunables ------------------------------------------------------------
        public const float MARGIN = 32f;         // screen margin in reference pixels
        public const float ROW_GAP = 6f;
        public const float BUTTON_PAD_X = 18f;
        public const float BUTTON_PAD_Y = 6f;
        public const float CONTROL_WIDTH = 220f; // a slider or choice control's width
        public const float VALUE_WIDTH = 80f;
        public const float TRACK_HEIGHT = 10f;

        public readonly string Name;
        public bool Opaque = true;               // draws the backdrop (a see-through screen shows the game: pause)
        public VisualElement Root;
        public readonly List<List<Control>> Grid = new List<List<Control>>();
        public Control Focused { get; private set; }
        protected readonly FrontEnd Front;
        protected Shell S => Shell.I;

        protected ShellScreen(FrontEnd front, string name)
        {
            Front = front;
            Name = name;
        }

        /// <summary>Builds the tree (a full-screen root) and returns it; the front end adds it to the panel.</summary>
        public VisualElement Build()
        {
            Grid.Clear();
            Focused = null;
            Root = new VisualElement { name = Name };
            Root.style.position = Position.Absolute;
            Root.style.left = 0;
            Root.style.top = 0;
            Root.style.right = 0;
            Root.style.bottom = 0;
            if (Opaque)
            {
                Root.style.backgroundColor = UiTheme.BG;
            }
            BuildContent();
            return Root;
        }

        protected abstract void BuildContent();

        /// <summary>Focus the first control (the top left of the grid); screens override to start elsewhere.</summary>
        public virtual void FocusFirst()
        {
            if (Grid.Count > 0 && Grid[0].Count > 0)
            {
                Focus(Grid[0][0]);
            }
        }

        public virtual void OnCancel()
        {
            Front.Back();
        }

        /// <summary>Once a frame while on top (rebinding timers, scrolling); dt is unscaled.</summary>
        public virtual void Tick(float dt)
        {
        }

        /// <summary>A menu action for this screen. True when it was used.</summary>
        public virtual bool HandleAction(string action)
        {
            switch (action)
            {
                case "ui_up": return MoveRow(-1);
                case "ui_down": return MoveRow(1);
                case "ui_left": return Sideways(-1);
                case "ui_right": return Sideways(1);
                case "ui_accept":
                    Focused?.Activate?.Invoke();
                    return Focused != null;
                case "ui_cancel":
                    OnCancel();
                    return true;
            }
            return false;
        }

        public void Focus(Control c)
        {
            if (c == null || c.Element == null)
            {
                return;
            }
            if (Focused != null && Focused.Element != null)
            {
                UiTheme.ButtonLook(Focused.Element, false);
            }
            Focused = c;
            UiTheme.ButtonLook(c.Element, true);
            c.Element.Focus();
            ScrollView scroll = Enclosing<ScrollView>(c.Element);
            scroll?.ScrollTo(c.Element);
            Front.OnFocusChanged(this, c);
        }

        /// <summary>The control with this element name, or null.</summary>
        public Control Find(string name)
        {
            foreach (List<Control> row in Grid)
            {
                foreach (Control c in row)
                {
                    if (c.Name == name)
                    {
                        return c;
                    }
                }
            }
            return null;
        }

        /// <summary>Every control of the grid, rows top to bottom.</summary>
        public IEnumerable<Control> Controls()
        {
            foreach (List<Control> row in Grid)
            {
                foreach (Control c in row)
                {
                    yield return c;
                }
            }
        }

        /// <summary>The row and column of a control in the grid, or (-1, -1).</summary>
        public (int row, int col) GridPosition(Control c)
        {
            for (int r = 0; r < Grid.Count; r++)
            {
                int col = Grid[r].IndexOf(c);
                if (col >= 0)
                {
                    return (r, col);
                }
            }
            return (-1, -1);
        }

        protected bool MoveRow(int dir)
        {
            if (Grid.Count == 0)
            {
                return false;
            }
            (int row, int col) = GridPosition(Focused);
            if (row < 0)
            {
                FocusFirst();
                return true;
            }
            int next = (row + dir + Grid.Count) % Grid.Count;
            List<Control> cells = Grid[next];
            Focus(cells[Mathf.Min(Mathf.Max(col, 0), cells.Count - 1)]);
            return true;
        }

        protected bool Sideways(int dir)
        {
            if (Focused == null)
            {
                return false;
            }
            if (Focused.Step != null)
            {
                Focused.Step(dir);
                Front.OnValueChanged(this, Focused);
                return true;
            }
            (int row, int col) = GridPosition(Focused);
            if (row < 0 || Grid[row].Count < 2)
            {
                return false;
            }
            int next = (col + dir + Grid[row].Count) % Grid[row].Count;
            Focus(Grid[row][next]);
            return true;
        }

        protected void AddRow(params Control[] cells)
        {
            Grid.Add(new List<Control>(cells));
        }

        // ---- building blocks ------------------------------------------------------------

        /// <summary>A column filling the screen with the standard margin (top-aligned), or centred.</summary>
        protected VisualElement Column(bool centered = false)
        {
            var col = new VisualElement { name = "Column" };
            col.style.position = Position.Absolute;
            col.style.left = MARGIN;
            col.style.top = MARGIN;
            col.style.right = MARGIN;
            col.style.bottom = MARGIN;
            col.style.flexDirection = FlexDirection.Column;
            if (centered)
            {
                col.style.justifyContent = Justify.Center;
                col.style.alignItems = Align.Center;
            }
            Root.Add(col);
            return col;
        }

        protected Label Heading(VisualElement parent, string text, string name = "Heading", float mult = UiTheme.HEADING)
        {
            var l = new Label(text) { name = name };
            UiTheme.Text(l, mult, UiTheme.TEXT);
            l.style.marginBottom = 12f + UiTheme.Gap(mult);
            parent.Add(l);
            return l;
        }

        protected Label Text(VisualElement parent, string text, string name, float mult = 1.0f, bool dim = false, bool wrap = true)
        {
            var l = new Label(text) { name = name };
            UiTheme.Text(l, mult, dim ? UiTheme.TEXT_DIM : UiTheme.TEXT, wrap);
            parent.Add(l);
            return l;
        }

        protected ScrollView Scroll(VisualElement parent, string name = "Scroll")
        {
            var sv = new ScrollView(ScrollViewMode.Vertical) { name = name };
            sv.style.flexGrow = 1;
            sv.style.flexShrink = 1;
            sv.horizontalScrollerVisibility = ScrollerVisibility.Hidden;
            sv.verticalScrollerVisibility = ScrollerVisibility.Auto;
            parent.Add(sv);
            return sv;
        }

        /// <summary>A focusable box holding a label: the shape every control shares.</summary>
        protected VisualElement Box(string name, string text, out Label label)
        {
            var box = new VisualElement { name = name, focusable = true };
            box.style.flexDirection = FlexDirection.Row;
            box.style.alignItems = Align.Center;
            box.style.paddingLeft = BUTTON_PAD_X;
            box.style.paddingRight = BUTTON_PAD_X;
            box.style.paddingTop = BUTTON_PAD_Y;
            box.style.paddingBottom = BUTTON_PAD_Y;
            box.style.marginBottom = ROW_GAP;
            box.style.marginRight = ROW_GAP;
            box.style.alignSelf = Align.FlexStart;
            label = new Label(text) { name = "Text", pickingMode = PickingMode.Ignore };
            UiTheme.Text(label, 1.0f, UiTheme.TEXT, false);
            label.style.marginBottom = 0;
            box.Add(label);
            UiTheme.ButtonLook(box, false);
            return box;
        }

        protected Control Register(VisualElement parent, VisualElement box, Control c)
        {
            c.Element = box;
            box.userData = c;
            box.RegisterCallback<ClickEvent>(_ =>
            {
                Focus(c);
                c.Activate?.Invoke();
                Front.OnValueChanged(this, c);
            });
            parent.Add(box);
            return c;
        }

        protected Control Button(VisualElement parent, string text, string name, Action onPress)
        {
            VisualElement box = Box(name, text, out Label _);
            return Register(parent, box, new Control { Kind = "button", Label = text, Activate = onPress });
        }

        /// <summary>An On/Off switch; accept flips it.</summary>
        protected Control Toggle(VisualElement parent, string rowLabel, string name, bool value, Action<bool> onChange)
        {
            bool on = value;
            VisualElement box = Box(name, S.T(on ? "value.on" : "value.off"), out Label text);
            box.style.minWidth = VALUE_WIDTH + 2 * BUTTON_PAD_X;
            var c = new Control { Kind = "toggle", Label = rowLabel, Value = () => S.T(on ? "value.on" : "value.off") };
            c.Activate = () =>
            {
                on = !on;
                text.text = c.Value();
                onChange(on);
            };
            return Register(parent, box, c);
        }

        /// <summary>A slider: a track with a fill and the value as text; left and right step it.</summary>
        protected Control Slider(VisualElement parent, string rowLabel, string name, double value, double lo, double hi,
                                 double step, Func<double, string> format, Action<double> onChange)
        {
            double now = value;
            var box = new VisualElement { name = name, focusable = true };
            box.style.flexDirection = FlexDirection.Row;
            box.style.alignItems = Align.Center;
            box.style.paddingLeft = BUTTON_PAD_X;
            box.style.paddingRight = BUTTON_PAD_X;
            box.style.paddingTop = BUTTON_PAD_Y;
            box.style.paddingBottom = BUTTON_PAD_Y;
            box.style.marginBottom = ROW_GAP;
            box.style.alignSelf = Align.FlexStart;
            var track = new VisualElement { name = "Track", pickingMode = PickingMode.Ignore };
            track.style.width = CONTROL_WIDTH * Mathf.Max(1f, UiTheme.TextScale * 0.75f);
            track.style.height = TRACK_HEIGHT;
            track.style.backgroundColor = UiTheme.BG;
            UiTheme.Radius(track, 3f);
            var fill = new VisualElement { name = "Fill", pickingMode = PickingMode.Ignore };
            fill.style.height = Length.Percent(100);
            fill.style.backgroundColor = UiTheme.TEXT_DIM;
            UiTheme.Radius(fill, 3f);
            track.Add(fill);
            box.Add(track);
            var text = new Label(format(now)) { name = "Value", pickingMode = PickingMode.Ignore };
            UiTheme.Text(text, 1.0f, UiTheme.TEXT, false);
            text.style.marginBottom = 0;
            text.style.marginLeft = 12f;
            text.style.minWidth = VALUE_WIDTH;
            text.style.unityTextAlign = TextAnchor.MiddleRight;
            box.Add(text);
            UiTheme.ButtonLook(box, false);
            void Refresh()
            {
                fill.style.width = Length.Percent(hi > lo ? (float)((now - lo) / (hi - lo) * 100.0) : 0f);
                text.text = format(now);
            }
            Refresh();
            var c = new Control { Kind = "slider", Label = rowLabel, Value = () => format(now) };
            c.Step = dir =>
            {
                double next = Math.Round((now + dir * step) / step) * step;
                next = Math.Min(Math.Max(next, lo), hi);
                if (Math.Abs(next - now) < 1e-9)
                {
                    return;
                }
                now = next;
                Refresh();
                onChange(now);
            };
            return Register(parent, box, c);
        }

        /// <summary>A choice among options shown as "< name >"; left and right step through them (wrapping).</summary>
        protected Control Stepper(VisualElement parent, string rowLabel, string name, List<object> choices, List<string> names,
                                  object current, Action<object> onChange)
        {
            int index = Mathf.Max(0, IndexOfChoice(choices, current));
            VisualElement box = Box(name, "", out Label text);
            box.style.minWidth = CONTROL_WIDTH;
            text.style.flexGrow = 1;
            text.style.unityTextAlign = TextAnchor.MiddleCenter;
            void Refresh()
            {
                text.text = "<  " + (index < names.Count ? names[index] : "") + "  >";
            }
            Refresh();
            var c = new Control { Kind = "choice", Label = rowLabel, Value = () => index < names.Count ? names[index] : "" };
            c.Step = dir =>
            {
                if (choices.Count == 0)
                {
                    return;
                }
                index = (index + dir + choices.Count) % choices.Count;
                Refresh();
                onChange(choices[index]);
            };
            c.Activate = () => c.Step(1);
            return Register(parent, box, c);
        }

        private static int IndexOfChoice(List<object> choices, object current)
        {
            for (int i = 0; i < choices.Count; i++)
            {
                if (SameChoice(choices[i], current))
                {
                    return i;
                }
            }
            return -1;
        }

        private static bool SameChoice(object a, object b)
        {
            if (a is List<object> la && b is List<object> lb)
            {
                return la.Count == lb.Count && la.Count == 2 && Json.ToNumber(la[0]) == Json.ToNumber(lb[0])
                       && Json.ToNumber(la[1]) == Json.ToNumber(lb[1]);
            }
            if (Json.IsNumber(a) && Json.IsNumber(b))
            {
                return Json.ToNumber(a) == Json.ToNumber(b);
            }
            return Equals(a, b);
        }

        /// <summary>The nearest ancestor of a type (or null).</summary>
        public static T Enclosing<T>(VisualElement e) where T : VisualElement
        {
            VisualElement node = e?.parent;
            while (node != null)
            {
                if (node is T found)
                {
                    return found;
                }
                node = node.parent;
            }
            return null;
        }
    }
}
