// ---------------------------------------------------------------------------
// DialogueData.cs
// Purpose : Reads the audio pipeline's dialogue.built.json (format v0, "version": 1) for subtitles (engine-free):
//           which line to show, which subtitle chunk (cue) is on screen at time t, and how many characters a
//           typewriter has revealed. Checked against data/golden/dialogue.json ("reveal_count").
// Usage   : var dlg = DialogueData.Parse(text);                  // null when the file is not a built dialogue file
//           Dictionary<string, object> line = DialogueData.Line(dlg, "guide.intro");
//           if (DialogueData.ShouldShow(line, access)) ...       // access = the settings' "access" section
//           DialogueData.CueLines(line, t)    // ["Welcome, traveler.", "The bakery opens at dawn."]
//           DialogueData.Revealed(line, t)    // characters of line.text visible at t (typewriter)
// Notes   : No UnityEngine types (EditMode tests run it). Fields this reader does not know are ignored (the format
//           only ever adds fields). A line is "line" (story: always subtitled when subtitles are on) or "bark"
//           (ambient: only with subtitle_barks). The reveal list counts only when it has one entry per character
//           of the shown text; otherwise the typewriter runs at DEFAULT_CPS, faster when that would not finish
//           within duration_s, as in every engine (Wavesmith's dialogue.py reveal_count). The same rules as the
//           Godot, LÖVE and web ports.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public static class DialogueData
    {
        // ---- Tunables ------------------------------------------------------------
        public const int FORMAT_VERSION = 1;
        public const double DEFAULT_CPS = 30.0;    // characters per second when a line has no reveal data
        public const double HOLD_S = 1.0;          // a line stays this long after its last cue or character
        private const double REVEAL_EPS = 1e-9;    // t * cps lands on a whole character count despite rounding

        /// <summary>{"lines", "captions", "style", "locale"} from the file's text, or null when it is not a built dialogue file.</summary>
        public static Dictionary<string, object> Parse(string text)
        {
            if (text == null || !Json.TryParse(text, out object parsed) || !(parsed is Dictionary<string, object> d))
            {
                return null;
            }
            if (!(d.TryGetValue("version", out object v) && Json.IsNumber(v) && (int)Json.ToNumber(v) == FORMAT_VERSION))
            {
                return null;
            }
            if (!(d.TryGetValue("lines", out object lines) && lines is Dictionary<string, object>))
            {
                return null;
            }
            return new Dictionary<string, object>
            {
                { "lines", lines },
                { "captions", d.TryGetValue("captions", out object c) && c is Dictionary<string, object> ? c : new Dictionary<string, object>() },
                { "style", d.TryGetValue("style", out object s) && s is Dictionary<string, object> ? s : new Dictionary<string, object>() },
                { "locale", d.TryGetValue("locale", out object l) && l is string ls ? ls : "en" },
            };
        }

        /// <summary>A copy of one line with its "id" filled in, or null when the file has no such line.</summary>
        public static Dictionary<string, object> Line(Dictionary<string, object> dlg, string id)
        {
            if (dlg != null && dlg.TryGetValue("lines", out object lines) && lines is Dictionary<string, object> all
                && all.TryGetValue(id, out object entry) && entry is Dictionary<string, object> line)
            {
                var output = (Dictionary<string, object>)Json.DeepCopy(line);
                output["id"] = id;
                return output;
            }
            return null;
        }

        /// <summary>The caption entry for an audio event id, or null.</summary>
        public static Dictionary<string, object> Caption(Dictionary<string, object> dlg, string eventId)
        {
            if (dlg != null && dlg.TryGetValue("captions", out object caps) && caps is Dictionary<string, object> all
                && all.TryGetValue(eventId, out object entry) && entry is Dictionary<string, object> cap)
            {
                return cap;
            }
            return null;
        }

        /// <summary>Whether the settings let this line be subtitled (subtitles on; a bark needs subtitle_barks).</summary>
        public static bool ShouldShow(Dictionary<string, object> entry, Dictionary<string, object> access)
        {
            if (entry == null || !Flag(access, "subtitles", true))
            {
                return false;
            }
            if (entry.TryGetValue("kind", out object kind) && kind is string k && k == "bark")
            {
                return Flag(access, "subtitle_barks", false);
            }
            return true;
        }

        /// <summary>How long the line plays: duration_s, or its length at DEFAULT_CPS.</summary>
        public static double Duration(Dictionary<string, object> entry)
        {
            if (entry.TryGetValue("duration_s", out object d) && Json.IsNumber(d))
            {
                return Json.ToNumber(d);
            }
            return Text(entry).Length / DEFAULT_CPS;
        }

        /// <summary>Characters of the shown text visible at t; length is the shown text's length when it is not entry.text.</summary>
        public static int Revealed(Dictionary<string, object> entry, double t, int length = -1)
        {
            int n = length < 0 ? Text(entry).Length : length;
            if (entry.TryGetValue("reveal", out object r) && r is List<object> reveal && reveal.Count == n)
            {
                int count = 0;
                foreach (object item in reveal)
                {
                    if (item is Dictionary<string, object> row && row.TryGetValue("t", out object rt) && Json.IsNumber(rt)
                        && Json.ToNumber(rt) <= t)
                    {
                        count++;
                    }
                }
                return count;
            }
            // no reveal list that fits: all of it by duration_s, never slower than DEFAULT_CPS
            double dur = entry.TryGetValue("duration_s", out object d) && Json.IsNumber(d) ? Json.ToNumber(d) : n / DEFAULT_CPS;
            if (dur <= 0.0)
            {
                return n;
            }
            double cps = Math.Max(DEFAULT_CPS, n / dur);
            return Math.Min(Math.Max((int)Math.Floor(t * cps + REVEAL_EPS), 0), n);
        }

        /// <summary>The subtitle chunk on screen at t; the whole text when the line has no cues; empty when it is over.</summary>
        public static List<string> CueLines(Dictionary<string, object> entry, double t)
        {
            var output = new List<string>();
            if (!(entry.TryGetValue("cues", out object c) && c is List<object> cues && cues.Count > 0))
            {
                if (t <= Duration(entry))
                {
                    output.Add(Text(entry));
                }
                return output;
            }
            foreach (object item in cues)
            {
                if (!(item is Dictionary<string, object> cue))
                {
                    continue;
                }
                double start = cue.TryGetValue("start", out object s) && Json.IsNumber(s) ? Json.ToNumber(s) : 0.0;
                double end = cue.TryGetValue("end", out object e) && Json.IsNumber(e) ? Json.ToNumber(e) : 0.0;
                if (t >= start && t < end && cue.TryGetValue("lines", out object lines) && lines is List<object> list)
                {
                    foreach (object line in list)
                    {
                        output.Add(line as string ?? "");
                    }
                    return output;
                }
            }
            return output;
        }

        /// <summary>True once the line has played out and its hold is over.</summary>
        public static bool Finished(Dictionary<string, object> entry, double t)
        {
            return t > Duration(entry) + HOLD_S;
        }

        /// <summary>The line's text ("" when missing).</summary>
        public static string Text(Dictionary<string, object> entry)
        {
            return entry != null && entry.TryGetValue("text", out object t) ? t as string ?? "" : "";
        }

        private static bool Flag(Dictionary<string, object> access, string key, bool fallback)
        {
            return access != null && access.TryGetValue(key, out object v) && v is bool b ? b : fallback;
        }
    }
}
