// ---------------------------------------------------------------------------
// AccessAudit.cs
// Purpose : What a player sees on one screen, as data for tools/access/sweep.py (#91, #85): every visible text with
//           its size, colour, the colour behind it and whether it fits; which controls the menu actions can reach,
//           and what each says when focused (#165).
// Usage   : Dictionary<string, object> report = AccessAudit.Screen(front, "settings/audio");  // logged as JSON
//           (python tools/dev.py smoke --drive access runs it on every screen; sweep.py checks the result)
// Notes   : Nothing is read from pixels: colours come from the resolved styles, a text's background is the nearest
//           thing behind it in the tree (its control box, a panel, the screen's backdrop) blended down to the
//           first opaque layer. A text over the game (HUD, subtitles) has no opaque layer: it is reported with
//           what lies between it and the game (its panel layers), and its outline counts as its background. Sizes
//           are in the panel's reference resolution (FrontEnd.REF_W x REF_H); sweep.py scales them to the window the
//           way "scaling" says ("fractional": min(w/W, h/H), which is PanelScreenMatchMode.Shrink). Reach is the
//           screen's own grid (the shell moves focus along it): a focusable element outside the grid is unreached.
//           Hover is not styled by the shell, so no control can look the same focused as hovered.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

namespace graveyard_shift.Shell
{
    public static class AccessAudit
    {
        public static readonly string[] BUTTON_STATES = { "normal", "focus" };   // the states a player reads a control in
        public const float COVER_ALPHA = 0.9f;        // a panel this opaque hides the text under it (a dialog over a screen)
        private const float SLACK = 0.5f;

        private sealed class Panel
        {
            public int Order;
            public Rect Rect;
            public VisualElement Element;
        }

        private sealed class Found
        {
            public Dictionary<string, object> Row;
            public int Order;
            public Vector2 Centre;
            public List<VisualElement> Chain;
        }

        /// <summary>The report for the screens on the panel: {"screen", "design", "window", "texts": [...], "focus": {...}}.</summary>
        public static Dictionary<string, object> Screen(FrontEnd front, string where)
        {
            var texts = new List<Found>();
            var focusable = new List<VisualElement>();
            var panels = new List<Panel>();
            int order = 0;
            Walk(front.Root, texts, focusable, panels, ref order);
            var rows = new List<object>();
            foreach (Found f in texts)
            {
                f.Row["covered"] = Covered(f, panels);
                f.Row["card"] = Card(f, panels);
                rows.Add(f.Row);
            }
            Rect root = front.Root.worldBound;
            Vector2Int window = front.WindowSize();
            return new Dictionary<string, object>
            {
                { "screen", where },
                { "visible", new List<object> { (double)root.width, (double)root.height } },
                { "window", new List<object> { (double)window.x, (double)window.y } },
                { "design", new List<object> { (double)FrontEnd.REF_W, (double)FrontEnd.REF_H } },
                { "scaling", "fractional" },
                { "texts", rows },
                { "focus", Focus(front, focusable) },
            };
        }

        /// <summary>Which actions have a gamepad binding and which a keyboard one (the shell's navigation must have both).</summary>
        public static Dictionary<string, object> InputReport(string[] actions)
        {
            var output = new Dictionary<string, object>();
            foreach (string action in actions)
            {
                output[action] = new Dictionary<string, object>
                {
                    { "gamepad", ShellInput.HasGamepad(action) }, { "keyboard", ShellInput.HasKeyboard(action) },
                };
            }
            return output;
        }

        // ---- texts ------------------------------------------------------------------------

        private static void Walk(VisualElement e, List<Found> texts, List<VisualElement> focusable, List<Panel> panels, ref int order)
        {
            if (e.resolvedStyle.display == DisplayStyle.None || e.resolvedStyle.visibility == Visibility.Hidden
                || e.resolvedStyle.opacity <= 0f)
            {
                return;
            }
            order++;
            Color bg = e.resolvedStyle.backgroundColor;
            if (bg.a >= COVER_ALPHA && !(e.userData is Control) && e.worldBound.width > 0 && e.worldBound.height > 0)
            {
                panels.Add(new Panel { Order = order, Rect = e.worldBound, Element = e });
            }
            if (e.focusable && e.userData is Control)
            {
                focusable.Add(e);
            }
            if (e is TextElement t && !string.IsNullOrWhiteSpace(t.text))
            {
                Control control = ControlOf(e);
                if (control != null)
                {
                    foreach (string state in BUTTON_STATES)
                    {
                        texts.Add(Tag(Text(t, control, state), e, order));
                    }
                }
                else
                {
                    texts.Add(Tag(Text(t, null, ""), e, order));
                }
            }
            foreach (VisualElement child in e.Children())
            {
                Walk(child, texts, focusable, panels, ref order);
            }
        }

        private static Dictionary<string, object> Text(TextElement t, Control control, string state)
        {
            Color fg = control != null ? UiTheme.StateColours(state).fg : t.resolvedStyle.color;
            List<Color> layers = Layers(t, control, state);
            Color? bg = Background(layers);
            float outline = t.resolvedStyle.unityTextOutlineWidth;
            string text = t.text.Trim();
            var row = new Dictionary<string, object>
            {
                { "node", PathOf(t) },
                { "text", text.Length > 60 ? text.Substring(0, 60) : text },
                { "state", state },
                { "px", (double)t.resolvedStyle.fontSize },
                { "fg", UiTheme.Hex(fg) },
                { "bg", bg.HasValue ? UiTheme.Hex(bg.Value) : null },
                { "outline", outline > 0f ? UiTheme.Hex(t.resolvedStyle.unityTextOutlineColor) : null },
                { "fits", Fits(t) },
                { "ink", state == "focus" ? new List<object>() : Ink(t) },
            };
            if (!bg.HasValue)
            {
                var over = new List<object>();
                foreach (Color c in layers)
                {
                    over.Add(new List<object> { UiTheme.Hex(c), System.Math.Round((double)c.a, 3) });
                }
                row["over_game"] = over;
            }
            return row;
        }

        /// <summary>The background colours from the text outward until one is opaque (top first).</summary>
        private static List<Color> Layers(VisualElement e, Control control, string state)
        {
            var layers = new List<Color>();
            VisualElement node = e;
            while (node != null)
            {
                Color c = node.resolvedStyle.backgroundColor;
                if (control != null && node == control.Element)
                {
                    c = UiTheme.StateColours(state).bg;    // the box's fill in that state, whatever it shows now
                }
                if (c.a > 0f)
                {
                    layers.Add(c);
                    if (c.a >= 0.999f)
                    {
                        break;
                    }
                }
                node = node.parent;
            }
            return layers;
        }

        /// <summary>The opaque colour behind the text, or null over the game (no opaque layer under it).</summary>
        private static Color? Background(List<Color> layers)
        {
            if (layers.Count == 0 || layers[layers.Count - 1].a < 0.999f)
            {
                return null;
            }
            Color output = layers[layers.Count - 1];
            for (int i = layers.Count - 2; i >= 0; i--)
            {
                output = Color.Lerp(output, new Color(layers[i].r, layers[i].g, layers[i].b, 1f), layers[i].a);
            }
            output.a = 1f;
            return output;
        }

        private static Vector2 Measure(TextElement t, bool wrapped)
        {
            if (wrapped)
            {
                return t.MeasureTextSize(t.text, t.resolvedStyle.width, VisualElement.MeasureMode.AtMost, 0, VisualElement.MeasureMode.Undefined);
            }
            return t.MeasureTextSize(t.text, 0, VisualElement.MeasureMode.Undefined, 0, VisualElement.MeasureMode.Undefined);
        }

        /// <summary>Where the text's glyphs land, in panel pixels: its box narrowed to the text (aligned as drawn).</summary>
        private static List<object> Ink(TextElement t)
        {
            Rect box = t.worldBound;
            ScrollView scroll = ShellScreen.Enclosing<ScrollView>(t);
            if (scroll != null)
            {
                Rect area = scroll.contentViewport.worldBound;
                if (!Encloses(Grow(area, SLACK), box))
                {
                    return new List<object>();   // scrolled out of its list: not drawn, so it runs into nothing
                }
            }
            bool wrapped = t.resolvedStyle.whiteSpace == WhiteSpace.Normal;
            if (wrapped)
            {
                return new List<object> { (double)box.x, (double)box.y, (double)box.width, (double)box.height };
            }
            Vector2 size = Measure(t, false);
            float w = Mathf.Min(size.x, box.width);
            float h = Mathf.Min(size.y, box.height);
            float x = box.x;
            TextAnchor align = t.resolvedStyle.unityTextAlign;
            if (align == TextAnchor.MiddleCenter || align == TextAnchor.UpperCenter || align == TextAnchor.LowerCenter)
            {
                x += (box.width - w) / 2f;
            }
            else if (align == TextAnchor.MiddleRight || align == TextAnchor.UpperRight || align == TextAnchor.LowerRight)
            {
                x += box.width - w;
            }
            float y = box.y + (box.height - h) / 2f;
            return new List<object> { (double)x, (double)y, (double)w, (double)h };
        }

        private static bool Fits(TextElement t)
        {
            Rect box = t.worldBound;
            bool wrapped = t.resolvedStyle.whiteSpace == WhiteSpace.Normal;
            Vector2 size = Measure(t, wrapped);
            if (!wrapped && size.x > box.width + SLACK)
            {
                return false;                     // the line is longer than its box
            }
            ScrollView scroll = ShellScreen.Enclosing<ScrollView>(t);
            if (wrapped && scroll == null && size.y > box.height + SLACK)
            {
                return false;                     // more lines than the box holds, and no scrolling
            }
            if (t.parent != null && t.parent.userData is Control && !Encloses(Grow(t.parent.worldBound, SLACK), box))
            {
                return false;                     // spills out of its control's box
            }
            if (scroll != null)
            {
                // scrolled out of view vertically is what scrolling is for; sideways it must fit
                Rect area = scroll.contentViewport.worldBound;
                return box.xMin >= area.xMin - SLACK && box.xMax <= area.xMax + SLACK;
            }
            Rect root = RootOf(t).worldBound;
            return Encloses(Grow(root, SLACK), box);
        }

        // ---- what covers what ----------------------------------------------------------------

        private static Found Tag(Dictionary<string, object> row, VisualElement e, int order)
        {
            var chain = new List<VisualElement>();
            VisualElement node = e;
            while (node != null)
            {
                chain.Add(node);
                node = node.parent;
            }
            return new Found { Row = row, Order = order, Centre = e.worldBound.center, Chain = chain };
        }

        /// <summary>The panel the text sits on (its nearest opaque ancestor): {"order", "rect"}; {} on nothing.</summary>
        private static Dictionary<string, object> Card(Found f, List<Panel> panels)
        {
            Panel best = null;
            foreach (Panel p in panels)
            {
                if (f.Chain.Contains(p.Element) && (best == null || p.Order > best.Order))
                {
                    best = p;
                }
            }
            if (best == null)
            {
                return new Dictionary<string, object>();
            }
            return new Dictionary<string, object>
            {
                { "order", (double)best.Order },
                { "rect", new List<object> { (double)best.Rect.x, (double)best.Rect.y, (double)best.Rect.width, (double)best.Rect.height } },
            };
        }

        /// <summary>True when an opaque panel drawn after the text, not its own, covers its centre (a dialog over it).</summary>
        private static bool Covered(Found f, List<Panel> panels)
        {
            foreach (Panel p in panels)
            {
                if (p.Order > f.Order && !f.Chain.Contains(p.Element) && p.Rect.Contains(f.Centre))
                {
                    return true;
                }
            }
            return false;
        }

        // ---- focus ---------------------------------------------------------------------------

        private static Dictionary<string, object> Focus(FrontEnd front, List<VisualElement> focusable)
        {
            ShellScreen top = front.Top();
            var reached = new HashSet<VisualElement>();
            if (top != null)
            {
                foreach (Control c in top.Controls())
                {
                    if (c.Element != null && c.Element.resolvedStyle.display != DisplayStyle.None)
                    {
                        reached.Add(c.Element);
                    }
                }
            }
            var missed = new List<object>();
            var lines = new Dictionary<string, object>();
            foreach (VisualElement e in focusable)
            {
                if (!reached.Contains(e))
                {
                    missed.Add(PathOf(e));
                }
                lines[PathOf(e)] = Narrator.Describe(e.userData as Control);
            }
            Focusable focused = front.Root.panel?.focusController?.focusedElement;
            string start = focused is VisualElement fe ? PathOf(fe) : top?.Focused?.Element != null ? PathOf(top.Focused.Element) : "";
            return new Dictionary<string, object>
            {
                { "start", start },
                { "controls", (double)focusable.Count },
                { "reached", (double)reached.Count },
                { "unreached", missed },
                { "focus_like_hover", new List<object>() },   // hover is not styled: focus never looks like it
                { "narration", lines },
            };
        }

        // ---- helpers -------------------------------------------------------------------------

        private static Control ControlOf(VisualElement e)
        {
            VisualElement node = e;
            while (node != null)
            {
                if (node.userData is Control c)
                {
                    return c;
                }
                node = node.parent;
            }
            return null;
        }

        private static VisualElement RootOf(VisualElement e)
        {
            VisualElement node = e;
            while (node.parent != null && node.name != "Root")
            {
                node = node.parent;
            }
            return node;
        }

        /// <summary>The element's path from the root: /Root/ScreenLayer/settings/Column/Rows/Row_x/Setting_x.</summary>
        public static string PathOf(VisualElement e)
        {
            var names = new List<string>();
            VisualElement node = e;
            while (node != null && node.name != "Root")
            {
                names.Insert(0, string.IsNullOrEmpty(node.name) ? node.GetType().Name : node.name);
                node = node.parent;
            }
            return "/Root/" + string.Join("/", names);
        }

        private static Rect Grow(Rect r, float by)
        {
            return new Rect(r.x - by, r.y - by, r.width + 2 * by, r.height + 2 * by);
        }

        private static bool Encloses(Rect outer, Rect inner)
        {
            return inner.xMin >= outer.xMin && inner.yMin >= outer.yMin && inner.xMax <= outer.xMax && inner.yMax <= outer.yMax;
        }
    }
}
