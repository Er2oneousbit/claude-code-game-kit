// ---------------------------------------------------------------------------
// OutlineFace.cs
// Purpose : Outlined text that keeps its colour (#283). UI Toolkit centres -unity-text-outline-width on the glyph's
//           edge, so half the outline lies on the letter: at the shell's body size a 2 px outline leaves almost no
//           face (measured on Unity 6000.6 at 24 px: the HUD's red 232 came out 88, at 1 px 197). An un-outlined
//           copy of the text (the face) is drawn right on top of the outlined one, so the letter shows its own colour
//           and the outline only shows around it.
// Usage   : OutlineFace.Attach(label);            // UiTheme.Outline does it; call once per text
//           TextElement face = OutlineFace.Of(label);   // the copy (null when none); OutlineFace.IsFace(element)
// Notes   : The face is the label's next sibling, absolutely placed over the label's box: a child would draw on top
//           too, but UI Toolkit stops measuring a text element that has children (it shrinks to its padding). The
//           face copies the label's text, the text styles it draws with (colour, size, font, wrapping, alignment,
//           spacing), its visibility and its box, once a frame and whenever the label's layout or text changes, so
//           the label stays the one a game sets. Everything that lists texts (AccessAudit, the pseudo-locale check,
//           UiTheme.ButtonLook) skips faces (IsFace), so a label counts once and is reported with the face's colour.
//           The face ignores the pointer and never takes focus. Transforms (translate, scale, rotate) on the label
//           itself are copied; on an ancestor they apply to both.
//
// Pseudocode:
//   Attach(label): face = new TextElement (class FACE_CLASS) ; label: every frame, on geometry and text change -> Sync
//   Sync: label off a panel -> face hidden ; face not right after label -> insert it there
//         copy text, text styles, display/visibility/opacity, transform ; place over label.layout
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Runtime.CompilerServices;
using UnityEngine;
using UnityEngine.UIElements;

namespace {{GAME_SLUG}}.Shell
{
    public static class OutlineFace
    {
        public const string FACE_CLASS = "gamekit-outline-face";   // marks the copy; lists of texts skip it
        public const string FACE_NAME = "OutlineFace";

        private static readonly ConditionalWeakTable<TextElement, TextElement> Faces = new ConditionalWeakTable<TextElement, TextElement>();

        /// <summary>Gives the text an un-outlined copy drawn on top of it (once; a second call does nothing).</summary>
        public static TextElement Attach(TextElement label)
        {
            if (label == null || IsFace(label))
            {
                return null;
            }
            if (Faces.TryGetValue(label, out TextElement existing))
            {
                return existing;
            }
            var face = new TextElement { name = FACE_NAME, pickingMode = PickingMode.Ignore, focusable = false };
            face.AddToClassList(FACE_CLASS);
            face.style.position = Position.Absolute;
            face.style.unityTextOutlineWidth = 0f;           // the whole point: the face has no outline
            face.style.textShadow = new TextShadow();
            Margins(face, 0f);
            Faces.Add(label, face);
            label.RegisterCallback<GeometryChangedEvent>(_ => Sync(label, face));
            label.RegisterCallback<ChangeEvent<string>>(e =>
            {
                if (e.target == label)
                {
                    face.text = e.newValue;
                }
            });
            label.RegisterCallback<AttachToPanelEvent>(_ => label.schedule.Execute(() => Sync(label, face)));   // not mid-attach
            label.RegisterCallback<DetachFromPanelEvent>(_ => face.style.display = DisplayStyle.None);
            label.schedule.Execute(() => Sync(label, face)).Every(0);   // styles a game sets (colour, display) have no event
            face.schedule.Execute(() => Orphan(label, face)).Every(0);
            Sync(label, face);
            return face;
        }

        /// <summary>The text's face copy, or null when it has none.</summary>
        public static TextElement Of(TextElement label)
        {
            return label != null && Faces.TryGetValue(label, out TextElement face) ? face : null;
        }

        /// <summary>True for a face copy (lists of texts skip it: it is part of the text it copies).</summary>
        public static bool IsFace(VisualElement e)
        {
            return e != null && e.ClassListContains(FACE_CLASS);
        }

        /// <summary>The face copies the label (text, text styles, visibility, box) and sits right after it.</summary>
        public static void Sync(TextElement label, TextElement face)
        {
            VisualElement parent = label.parent;
            if (parent == null || label.panel == null)
            {
                face.style.display = DisplayStyle.None;
                return;
            }
            if (face.parent != parent || parent.IndexOf(face) != parent.IndexOf(label) + 1)
            {
                parent.Insert(parent.IndexOf(label) + 1, face);   // Insert moves it from wherever it was
            }
            if (face.text != label.text)
            {
                face.text = label.text;
            }
            face.enableRichText = label.enableRichText;
            face.parseEscapeSequences = label.parseEscapeSequences;
            IResolvedStyle r = label.resolvedStyle;
            IStyle s = face.style;
            s.display = r.display;
            s.visibility = r.visibility;
            s.opacity = r.opacity;
            s.color = r.color;
            s.fontSize = r.fontSize;
            s.unityFontDefinition = r.unityFontDefinition;
            s.unityFont = r.unityFont;
            s.unityFontStyleAndWeight = r.unityFontStyleAndWeight;
            s.whiteSpace = r.whiteSpace;
            s.unityTextAlign = r.unityTextAlign;
            s.letterSpacing = r.letterSpacing;
            s.wordSpacing = r.wordSpacing;
            s.unityParagraphSpacing = r.unityParagraphSpacing;
            s.textOverflow = r.textOverflow;
            s.unityTextOverflowPosition = r.unityTextOverflowPosition;
            s.translate = new Translate(r.translate.x, r.translate.y, r.translate.z);
            s.scale = r.scale;
            s.rotate = r.rotate;
            s.transformOrigin = new TransformOrigin(r.transformOrigin.x, r.transformOrigin.y, r.transformOrigin.z);
            // The box: the label's border box, in the parent's padding box (where an absolute child's left/top start),
            // with the label's padding and border as the face's padding, so the text lands on the same pixels
            Rect box = label.layout;
            s.left = box.x - parent.resolvedStyle.borderLeftWidth;
            s.top = box.y - parent.resolvedStyle.borderTopWidth;
            s.width = box.width;
            s.height = box.height;
            s.paddingLeft = r.paddingLeft + r.borderLeftWidth;
            s.paddingRight = r.paddingRight + r.borderRightWidth;
            s.paddingTop = r.paddingTop + r.borderTopWidth;
            s.paddingBottom = r.paddingBottom + r.borderBottomWidth;
        }

        // A face whose label left its parent (removed on its own): it goes too, unless the label comes back
        private static void Orphan(TextElement label, TextElement face)
        {
            if (face.parent != null && (label.panel == null || label.parent != face.parent))
            {
                face.RemoveFromHierarchy();
            }
        }

        private static void Margins(VisualElement v, float all)
        {
            v.style.marginLeft = all;
            v.style.marginRight = all;
            v.style.marginTop = all;
            v.style.marginBottom = all;
        }
    }
}

// {{FOOTER}}
