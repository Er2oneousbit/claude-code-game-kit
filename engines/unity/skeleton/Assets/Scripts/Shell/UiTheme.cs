// ---------------------------------------------------------------------------
// UiTheme.cs
// Purpose : The one place the shell's look comes from: colours, text sizes and the live accessibility look (text
//           scale, the readable font, line spacing), applied to UI Toolkit elements in code so a setting change
//           shows at once (FrontEnd rebuilds the screens).
// Usage   : UiTheme.Apply(settings);  UiTheme.Text(label, 1.0f, UiTheme.TEXT);  UiTheme.ButtonLook(box, focused)
// Notes   : Sizes are in the panel's reference resolution (FrontEnd.REF_W x REF_H, 1280x720): BODY_PX 24 there is 36 px
//           at 1080p and 24 px at 1280x800 (SOP-20 asks 18 and 9, F36). Text scale multiplies every size. The
//           readable font is Atkinson Hyperlegible (OFL, Assets/Resources/GameKit/Fonts). Line spacing: UI Toolkit
//           has no line-height style, so it adds space between the menus' lines and between paragraphs
//           (-unity-paragraph-spacing); lines inside one wrapped paragraph keep the font's own spacing (verify:
//           a later Unity may add line-height). Focus looks different from hover on purpose: hover is not styled.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class UiTheme
    {
        // ---- Tunables ------------------------------------------------------------
        public const int BODY_PX = 24;              // body text at the reference resolution
        public const float HEADING = 1.5f;          // heading size as a multiple of the body
        public const float TITLE = 2.5f;
        public const int MIN_PX = 8;
        public const int OUTLINE_PX = 2;            // text drawn over the game gets this outline
        public const int FOCUS_BORDER = 3;
        public const string READABLE_FONT = "GameKit/Fonts/AtkinsonHyperlegible-Regular";   // Resources path

        public static readonly Color BG = new Color(0.08f, 0.09f, 0.15f);
        public static readonly Color PANEL = new Color(0.12f, 0.14f, 0.22f, 0.96f);
        public static readonly Color BUTTON = new Color(0.17f, 0.19f, 0.31f);
        public static readonly Color BORDER = new Color(0.32f, 0.36f, 0.52f);
        public static readonly Color TEXT = new Color(0.91f, 0.93f, 0.97f);
        public static readonly Color TEXT_DIM = new Color(0.62f, 0.66f, 0.78f);
        public static readonly Color FOCUS = new Color(1.0f, 0.82f, 0.40f);      // the focused control's fill
        public static readonly Color TEXT_ON_FOCUS = new Color(0.08f, 0.09f, 0.15f);
        public static readonly Color OUTLINE = Color.black;
        public static readonly Color BACKDROP = new Color(0f, 0f, 0f, 0.6f);     // the pause shade over the game

        public static float TextScale { get; private set; } = 1.0f;
        public static float LineSpacing { get; private set; } = 1.0f;
        public static bool Readable { get; private set; }

        private static Font _readable;
        private static bool _fontLooked;

        /// <summary>Reads the look from the settings (access.text_scale, readable_font, line_spacing).</summary>
        public static void Apply(Dictionary<string, object> settings)
        {
            TextScale = (float)GameSettings.Number(settings, "access", "text_scale");
            LineSpacing = (float)GameSettings.Number(settings, "access", "line_spacing");
            Readable = GameSettings.Bool(settings, "access", "readable_font");
        }

        /// <summary>A font size in reference pixels: the body size times mult times the player's text scale.</summary>
        public static int Px(float mult = 1.0f)
        {
            return Mathf.Max(MIN_PX, Mathf.RoundToInt(BODY_PX * mult * TextScale));
        }

        /// <summary>Extra space under a line of body text from the line spacing setting (0 at 1.0).</summary>
        public static float Gap(float mult = 1.0f)
        {
            return Mathf.Max(0f, (LineSpacing - 1.0f) * Px(mult));
        }

        /// <summary>The readable font, or null when the setting is off or the asset is missing (logged once).</summary>
        public static Font ReadableFont()
        {
            if (!Readable)
            {
                return null;
            }
            if (!_fontLooked)
            {
                _fontLooked = true;
                _readable = Resources.Load<Font>(READABLE_FONT);
                if (_readable == null)
                {
                    Debug.LogWarning($"[WARN][shell] readable font missing at Resources/{READABLE_FONT}: using the theme's");
                }
            }
            return _readable;
        }

        /// <summary>Styles a text: size (mult of the body), colour, wrapping, the readable font and line spacing.</summary>
        public static void Text(TextElement e, float mult, Color color, bool wrap = true)
        {
            e.style.fontSize = Px(mult);
            e.style.color = color;
            e.style.whiteSpace = wrap ? WhiteSpace.Normal : WhiteSpace.NoWrap;
            e.style.marginBottom = Gap(mult);
            e.style.unityParagraphSpacing = Gap(mult);
            Font font = ReadableFont();
            e.style.unityFontDefinition = font != null ? new StyleFontDefinition(FontDefinition.FromFont(font))
                                                       : new StyleFontDefinition(StyleKeyword.Null);
        }

        /// <summary>Text drawn over the game (HUD, subtitles): a black outline so it reads on any background.</summary>
        public static void Outline(TextElement e)
        {
            e.style.unityTextOutlineWidth = OUTLINE_PX;
            e.style.unityTextOutlineColor = OUTLINE;
        }

        /// <summary>A panel: a solid colour, rounded corners and padding (in reference pixels).</summary>
        public static void Panel(VisualElement v, Color bg, float padding)
        {
            v.style.backgroundColor = bg;
            v.style.paddingLeft = padding;
            v.style.paddingRight = padding;
            v.style.paddingTop = padding;
            v.style.paddingBottom = padding;
            Radius(v, 4f);
        }

        /// <summary>A control's box: the normal look, or the focus look (a filled highlight and dark text).</summary>
        public static void ButtonLook(VisualElement box, bool focused)
        {
            box.style.backgroundColor = focused ? FOCUS : BUTTON;
            Border(box, focused ? FOCUS : BORDER, focused ? FOCUS_BORDER : 1);
            Radius(box, 4f);
            Color text = focused ? TEXT_ON_FOCUS : TEXT;
            foreach (TextElement t in box.Query<TextElement>().ToList())
            {
                t.style.color = text;
            }
        }

        /// <summary>The colours a control's text is drawn in for the state ("normal" or "focus"): (text, box).</summary>
        public static (Color fg, Color bg) StateColours(string state)
        {
            return state == "focus" ? (TEXT_ON_FOCUS, FOCUS) : (TEXT, BUTTON);
        }

        public static void Border(VisualElement v, Color color, float width)
        {
            v.style.borderLeftColor = color;
            v.style.borderRightColor = color;
            v.style.borderTopColor = color;
            v.style.borderBottomColor = color;
            v.style.borderLeftWidth = width;
            v.style.borderRightWidth = width;
            v.style.borderTopWidth = width;
            v.style.borderBottomWidth = width;
        }

        public static void Radius(VisualElement v, float r)
        {
            v.style.borderTopLeftRadius = r;
            v.style.borderTopRightRadius = r;
            v.style.borderBottomLeftRadius = r;
            v.style.borderBottomRightRadius = r;
        }

        public static void Margin(VisualElement v, float all)
        {
            v.style.marginLeft = all;
            v.style.marginRight = all;
            v.style.marginTop = all;
            v.style.marginBottom = all;
        }

        /// <summary>"#rrggbb" of a colour (no alpha), for the access report.</summary>
        public static string Hex(Color c)
        {
            return "#" + ColorUtility.ToHtmlStringRGB(c).ToLowerInvariant();
        }
    }
}

// {{FOOTER}}
