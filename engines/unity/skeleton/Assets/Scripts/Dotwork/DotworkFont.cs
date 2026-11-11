// ---------------------------------------------------------------------------
// DotworkFont.cs
// Purpose : A Dotwork bitmap font (an AngelCode BMFont: the manifest's `font` kind) as a Unity asset: one sprite
//           per glyph sliced from the page textures, the BMFont metrics (line height, base, per-glyph offsets and
//           advance) and the kerning pairs. DotworkLabel draws text with it.
// Usage   : font.TryGlyph('A', out DotworkGlyph g); font.Kerning('A', 'B'); font.Measure("HELLO") (pixels)
// Notes   : Pixels of the page images, y DOWN like the .fnt file: a glyph's top-left sits at pen + (xoffset,
//           yoffset), the pen moves by xadvance plus the pair's kerning. `scale` only records the scale Dotwork
//           already drew the font at: the pages, rects and metrics are upscaled by it, so draw them 1:1 and never
//           multiply by it again. `tint` true means white ink that takes a colour.
//           A glyph with no pixels (space) has no sprite. Why not a TextMeshPro font asset: TMP needs the uGUI
//           package and its Essential Resources (shaders) imported, which an adopt-first project has not, and
//           its bitmap path for a coloured page is untested here; sprites draw the same everywhere.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;

namespace {{GAME_SLUG}}.Dotwork
{
    [Serializable]
    public struct DotworkGlyph
    {
        public int id;                 // Unicode code point
        public Sprite sprite;          // null for an empty glyph (space)
        public int x, y, w, h;         // the rect in its page, y down (the .fnt's)
        public int xoffset, yoffset, xadvance, page;
    }

    [Serializable]
    public struct DotworkKerning
    {
        public int first, second, amount;
    }

    public sealed class DotworkFont : ScriptableObject
    {
        public string fontName = "";
        public int lineHeight;
        public int baseline;                       // the manifest's `base`: pixels from a line's top to the baseline
        public float scale = 1f;                   // already applied to the pages: informational, do not scale again
        public bool tint = true;
        public float pixelsPerUnit = 16f;
        public Texture2D[] pages = new Texture2D[0];
        public DotworkGlyph[] glyphs = new DotworkGlyph[0];
        public DotworkKerning[] kerning = new DotworkKerning[0];

        [NonSerialized] private Dictionary<int, int> _byId;
        [NonSerialized] private Dictionary<long, int> _kern;

        public bool TryGlyph(int id, out DotworkGlyph glyph)
        {
            Index();
            if (_byId.TryGetValue(id, out int i))
            {
                glyph = glyphs[i];
                return true;
            }
            glyph = default;
            return false;
        }

        public int Kerning(int first, int second)
        {
            Index();
            return _kern.TryGetValue(((long)first << 32) | (uint)second, out int k) ? k : 0;
        }

        /// <summary>Width of one line of text in art pixels (unknown characters advance nothing).</summary>
        public int Measure(string line)
        {
            int pen = 0, prev = -1;
            foreach (int cp in CodePoints(line))
            {
                if (TryGlyph(cp, out DotworkGlyph g))
                {
                    pen += (prev >= 0 ? Kerning(prev, cp) : 0) + g.xadvance;
                    prev = cp;
                }
            }
            return pen;
        }

        /// <summary>Code points of a string (surrogate pairs joined).</summary>
        public static IEnumerable<int> CodePoints(string text)
        {
            for (int i = 0; i < (text ?? "").Length; i++)
            {
                if (char.IsHighSurrogate(text[i]) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
                {
                    yield return char.ConvertToUtf32(text[i], text[i + 1]);
                    i++;
                }
                else
                {
                    yield return text[i];
                }
            }
        }

        private void Index()
        {
            if (_byId != null)
            {
                return;
            }
            _byId = new Dictionary<int, int>();
            for (int i = 0; i < glyphs.Length; i++)
            {
                _byId[glyphs[i].id] = i;
            }
            _kern = new Dictionary<long, int>();
            foreach (DotworkKerning k in kerning)
            {
                _kern[((long)k.first << 32) | (uint)k.second] = k.amount;
            }
        }

        private void OnValidate()
        {
            _byId = null;
            _kern = null;
        }
    }
}

// {{FOOTER}}
