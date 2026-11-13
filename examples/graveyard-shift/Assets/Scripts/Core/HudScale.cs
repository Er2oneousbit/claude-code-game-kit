// ---------------------------------------------------------------------------
// HudScale.cs
// Purpose : The player's text size for a game HUD (#309): display.ui_scale times access.text_scale, a font size
//           from a base size, and a watch that says when it changed, so a HUD sized by hand follows the settings.
//           Engine-free (no UnityEngine).
// Usage   : label.style.fontSize = HudScale.FontSize(24, Shell.I.Settings);   // 24 px at the defaults
//           Shell.I.HudScaleChanged += k => label.style.fontSize = HudScale.FontSize(24, Shell.I.Settings);
//           or poll: var watch = new HudScale.Watch(); if (watch.Update(settings)) Relayout(watch.Scale);
// Notes   : ui_scale changes on the Display tab's Apply (#308), text_scale at once (Accessibility tab). The shell's
//           own menus size their text with UiTheme.Px (text_scale); a HUD in your world uses this. SOP-20: text size
//           reaches all text. Sizes are in the panel's reference pixels (FrontEnd.REF_W x REF_H).
//
// Pseudocode:
//   Factor(s)       = number(s.display.ui_scale, 1) * number(s.access.text_scale, 1)
//   FontSize(b, s)  = max(MIN_PX, round(b * Factor(s)))
//   Watch.Update(s) : k = Factor(s); changed = first call or k != last; last = k; return changed
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class HudScale
    {
        // ---- Tunables ------------------------------------------------------------
        public const int MIN_PX = 8;     // the smallest font size FontSize returns (UiTheme.MIN_PX)

        /// <summary>display.ui_scale * access.text_scale (1.0 each when missing or not a number).</summary>
        public static double Factor(Dictionary<string, object> settings)
        {
            return Number(settings, "display", "ui_scale") * Number(settings, "access", "text_scale");
        }

        /// <summary>A HUD font size: basePx (at the defaults) times the player's factor, at least MIN_PX.</summary>
        public static int FontSize(int basePx, Dictionary<string, object> settings)
        {
            return Math.Max(MIN_PX, (int)Math.Round(basePx * Factor(settings), MidpointRounding.AwayFromZero));
        }

        private static double Number(Dictionary<string, object> settings, string section, string key)
        {
            if (settings != null && settings.TryGetValue(section, out object s) && s is Dictionary<string, object> sec
                && sec.TryGetValue(key, out object v) && Json.IsNumber(v))
            {
                return Json.ToNumber(v);
            }
            return 1.0;
        }

        /// <summary>Says when the factor changed: true on the first Update (the HUD's first layout) and on a change.</summary>
        public sealed class Watch
        {
            private double? _last;

            public double Scale => _last ?? 1.0;

            public bool Update(Dictionary<string, object> settings)
            {
                double k = Factor(settings);
                bool changed = !_last.HasValue || _last.Value != k;
                _last = k;
                return changed;
            }
        }
    }
}
