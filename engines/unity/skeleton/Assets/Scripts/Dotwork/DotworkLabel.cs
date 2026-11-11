// ---------------------------------------------------------------------------
// DotworkLabel.cs
// Purpose : World-space text in a Dotwork bitmap font: one SpriteRenderer per glyph, placed by the BMFont metrics
//           (offsets, advance, kerning, line height), so the font looks exactly as drawn at whole-pixel steps.
// Usage   : var label = go.AddComponent<DotworkLabel>(); label.font = pack.Font("tiny"); label.Text = "HELLO";
//           label.color = Color.yellow (taken only by a tint font: white ink)
// Notes   : The transform is the top-left corner of the first line (y down from there, as in the .fnt). The
//           glyph objects are rebuilt from the text and hidden, never saved (HideAndDontSave), so a scene stores
//           only the label's fields. [ExecuteAlways] shows the text in the editor too; edits from the Inspector
//           rebuild on the next editor update (OnValidate must not create objects). Unknown characters are
//           skipped, a newline starts a new line.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;

namespace {{GAME_SLUG}}.Dotwork
{
    [ExecuteAlways]
    public sealed class DotworkLabel : MonoBehaviour
    {
        public DotworkFont font;
        [SerializeField] private string text = "";
        public Color color = Color.white;
        public int sortingOrder = 100;

        private readonly List<GameObject> _glyphs = new List<GameObject>();
        private bool _dirty = true;

        public string Text
        {
            get => text;
            set
            {
                text = value ?? "";
                Rebuild();
            }
        }

        private void OnEnable() => Rebuild();
        private void OnDisable() => Clear();
        private void OnValidate() => _dirty = true;

        private void Update()
        {
            if (_dirty)
            {
                Rebuild();
            }
        }

        /// <summary>Lays the glyphs out again (after changing the font, colour or sorting order from code).</summary>
        public void Rebuild()
        {
            _dirty = false;
            Clear();
            if (font == null || !isActiveAndEnabled)
            {
                return;
            }
            // 1:1: the pages, rects and metrics are already at the font's scale (Dotwork upscales them)
            float unit = 1f / Mathf.Max(1f, font.pixelsPerUnit);
            Color ink = font.tint ? color : Color.white;
            int line = 0;
            foreach (string row in text.Split('\n'))
            {
                int pen = 0, prev = -1;
                foreach (int cp in DotworkFont.CodePoints(row))
                {
                    if (!font.TryGlyph(cp, out DotworkGlyph g))
                    {
                        continue;
                    }
                    pen += prev >= 0 ? font.Kerning(prev, cp) : 0;
                    if (g.sprite != null)
                    {
                        var go = new GameObject("glyph") { hideFlags = HideFlags.HideAndDontSave };
                        go.transform.SetParent(transform, false);
                        go.transform.localPosition = new Vector3((pen + g.xoffset) * unit,
                                                                 -(line * font.lineHeight + g.yoffset) * unit, 0f);
                        var sr = go.AddComponent<SpriteRenderer>();
                        sr.sprite = g.sprite;
                        sr.color = ink;
                        sr.sortingOrder = sortingOrder;
                        _glyphs.Add(go);
                    }
                    pen += g.xadvance;
                    prev = cp;
                }
                line++;
            }
        }

        private void Clear()
        {
            foreach (GameObject go in _glyphs)
            {
                if (go == null)
                {
                    continue;
                }
                if (Application.isPlaying)
                {
                    Destroy(go);
                }
                else
                {
                    DestroyImmediate(go);
                }
            }
            _glyphs.Clear();
        }
    }
}

// {{FOOTER}}
