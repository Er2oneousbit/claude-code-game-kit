// ---------------------------------------------------------------------------
// AudioAccess.cs
// Purpose : Audio accessibility rules with no UnityEngine types in them (EditMode tests run them against
//           data/golden/access.json): which settings slider turns which bus of data/audio_events.json up or down,
//           and which arrow a directional caption gets when the sound comes from off screen.
// Usage   : var sliders = (Dictionary<string, object>)settings["audio"];                 // GameSettings
//           Dictionary<string, double> user = AudioAccess.UserBusGains(buses, sliders);   // { music: 0.8, sfx: 1, ... }
//           string arrow = AudioAccess.CaptionArrow(src.x - cam.x, cam.y - src.y, halfW, halfH);   // "" | "<-" ...
// Notes   : The spec is tools/audio/wavesmith/access.py. Sliders are linear 0..1 (settings.audio: master, music,
//           sfx, ui, voice), as the settings screen shows them; a slider multiplies its bus on top of the bus's
//           volume_db and the ducking (AudioEventPlayer.cs does that multiplication). A bus follows the slider named
//           in SLIDER_FOR_BUS; when one of its parent buses already follows the same slider it gets 1, so a slider
//           never counts twice down one branch (ambience under sfx). Buses without a slider get 1. A bad slider
//           value clamps to 0..1, a missing or non-numeric one counts as 1. Parents default to "master" (master has
//           none); a cycle stops after one step per bus.
//           Arrows: screen coordinates, y grows DOWNWARDS (Unity's world y grows upwards: pass cam.y - src.y).
//           Nothing while the source is inside the view (edges included); otherwise
//           k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8, clockwise from the right. Math.Round is not used:
//           floor(x + 0.5) is the rule in every engine (Math.Round rounds halves to even).
//
// Pseudocode:
//   UserBusGains: for each bus: slider = SLIDER_FOR_BUS[bus]; walk the parents; a parent with the same slider -> 1;
//                 no slider -> 1; else clamp(slider value)
//   CaptionDirection: not finite -> -1; inside the half sizes -> -1; else k from atan2, mod 8 (never negative)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class AudioAccess
    {
        // ---- Tunables ------------------------------------------------------------
        public const string MASTER = "master";
        public static readonly string[] SLIDERS = { "master", "music", "sfx", "ui", "voice" };

        // Bus name -> settings slider. Edit it when your audio_events.json uses other bus names.
        public static readonly IReadOnlyDictionary<string, string> SLIDER_FOR_BUS = new Dictionary<string, string>
        {
            { "master", "master" }, { "music", "music" }, { "sfx", "sfx" }, { "ambience", "sfx" }, { "ui", "ui" },
            { "dialogue", "voice" }, { "voice", "voice" },
        };

        // k = 0..7, every 45 degrees clockwise from the right (y down): right, down-right, down, down-left, left,
        // up-left, up, up-right. Escapes keep the file ASCII; the strings are the arrows of access.py ARROWS.
        public static readonly string[] ARROWS =
        {
            "\u2192", "\u2198", "\u2193", "\u2199", "\u2190", "\u2196", "\u2191", "\u2197",
        };

        // ---- Slider gains ------------------------------------------------------------

        /// <summary>A slider value as a linear gain: numbers clamp to 0..1; null, text, bool, NaN or infinity give 1.</summary>
        public static double Clamp01(object value)
        {
            if (!Json.IsNumber(value))
            {
                return 1.0;                                   // a bool is not a number here, as in the reference
            }
            double v = Json.ToNumber(value);
            if (double.IsNaN(v) || double.IsInfinity(v))
            {
                return 1.0;
            }
            return Math.Min(1.0, Math.Max(0.0, v));
        }

        /// <summary>{bus: linear gain} from the player's sliders, a slider never applied twice down one branch.
        /// buses is audio_events.json's "buses" object ({name: {parent?, volume_db?}}); sliders is settings.audio.
        /// mapping defaults to SLIDER_FOR_BUS. Throws ArgumentException when a parent is not text.</summary>
        public static Dictionary<string, double> UserBusGains(IDictionary<string, object> buses,
                                                              IDictionary<string, object> sliders,
                                                              IReadOnlyDictionary<string, string> mapping = null)
        {
            if (buses == null)
            {
                throw new ArgumentNullException(nameof(buses));
            }
            mapping = mapping ?? SLIDER_FOR_BUS;
            var names = new List<string>(buses.Keys);
            var output = new Dictionary<string, double>();
            foreach (string name in names)
            {
                string slider = Lookup(mapping, name);
                bool inherited = false;
                // Walk up the parents, at most one step per bus, so a cycle (a -> b -> a) cannot hang
                string p = ParentOf(buses, name);
                for (int n = 0; p != null && n < names.Count; n++, p = ParentOf(buses, p))
                {
                    if (slider != null && Lookup(mapping, p) == slider)
                    {
                        inherited = true;
                    }
                }
                object raw = null;
                if (slider != null && sliders != null)
                {
                    sliders.TryGetValue(slider, out raw);
                }
                output[name] = slider == null || inherited ? 1.0 : Clamp01(raw);
            }
            return output;
        }

        // The bus's parent: its "parent" field, else "master" (master itself has none). A bus missing from the
        // map, or one whose entry is not an object, has no fields, so it defaults the same way.
        private static string ParentOf(IDictionary<string, object> buses, string bus)
        {
            object parent = null;
            if (buses.TryGetValue(bus, out object def) && def is IDictionary<string, object> fields)
            {
                fields.TryGetValue("parent", out parent);
            }
            if (parent == null)
            {
                return bus == MASTER ? null : MASTER;
            }
            return parent as string ?? throw new ArgumentException($"audio buses: bus {bus}: parent must be text");
        }

        private static string Lookup(IReadOnlyDictionary<string, string> mapping, string bus)
        {
            return mapping.TryGetValue(bus, out string slider) ? slider : null;
        }

        // ---- Caption arrows ------------------------------------------------------------

        /// <summary>-1 while a sound at (dx, dy) from the view's centre is inside the view (edges included) or the
        /// offset is not finite, else the direction 0..7 clockwise from the right (screen y grows downwards).</summary>
        public static int CaptionDirection(double dx, double dy, double halfW, double halfH)
        {
            if (double.IsNaN(dx) || double.IsInfinity(dx) || double.IsNaN(dy) || double.IsInfinity(dy))
            {
                return -1;
            }
            if (Math.Abs(dx) <= halfW && Math.Abs(dy) <= halfH)
            {
                return -1;
            }
            long k = (long)Math.Floor(Math.Atan2(dy, dx) / (Math.PI / 4) + 0.5);   // -4..4
            return (int)(((k % 8) + 8) % 8);                                       // Python's k % 8: never negative
        }

        /// <summary>The arrow for a sound at (dx, dy) from the view's centre, or "" while it is inside the view.</summary>
        public static string CaptionArrow(double dx, double dy, double halfW, double halfH)
        {
            int k = CaptionDirection(dx, dy, halfW, halfH);
            return k < 0 ? "" : ARROWS[k];
        }
    }
}
