// ---------------------------------------------------------------------------
// AccessColours.cs
// Purpose : The game's important colours per colour-blind setting, from data/access/colours.json: the palette your
//           game draws with, and whether the kit's full-screen colour-blind filter (Kit/colorblind) should run.
// Usage   : var data = AccessColours.LoadData();                     // once (Shell does it)
//           Dictionary<string, Color> pal = AccessColours.Palette(data, "deuteranopia");   // {"player": Color, ...}
//           Shell.I.Palette()                                       // the palette for the current setting
// Notes   : python tools/access/colour_check.py pairs checks the same file: every declared pair must stay apart as a
//           protanope, deuteranope or tritanope sees it (SOP-20). A mode with no palette there falls back to "none",
//           through the colour-blind filter when "filter" is true. The filter is off in the kit's own file: on the
//           demo's colours it made the player and the box harder to tell apart, not easier (#169). The shell itself
//           never carries meaning by colour (text and focus outlines), so it swaps nothing of its own.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Shell
{
    public static class AccessColours
    {
        public const string DATA_FILE = "data/access/colours.json";

        /// <summary>The colour data ({"filter": bool, "palettes": {mode: {name: "#rrggbb"}}}), or an empty palette
        /// set when the file is missing or broken (logged).</summary>
        public static Dictionary<string, object> LoadData(string relative = DATA_FILE)
        {
            string text = ShellFiles.ReadOrNull(relative);
            if (text == null)
            {
                return Empty();
            }
            if (!Json.TryParse(text, out object parsed) || !(parsed is Dictionary<string, object> data)
                || !(data.TryGetValue("palettes", out object p) && p is Dictionary<string, object>))
            {
                Debug.LogWarning($"[WARN][access] {relative} is not a colour data file (palettes missing): no palette");
                return Empty();
            }
            return data;
        }

        /// <summary>{name: Color} for a colour-blind mode; a mode without its own palette uses "none".</summary>
        public static Dictionary<string, Color> Palette(Dictionary<string, object> data, string mode)
        {
            var output = new Dictionary<string, Color>();
            var palettes = data["palettes"] as Dictionary<string, object>;
            if (palettes == null)
            {
                return output;
            }
            object src = palettes.TryGetValue(mode, out object own) ? own : palettes.TryGetValue("none", out object none) ? none : null;
            if (src is Dictionary<string, object> table)
            {
                foreach (KeyValuePair<string, object> entry in table)
                {
                    if (entry.Value is string hex && ColorUtility.TryParseHtmlString(hex, out Color c))
                    {
                        output[entry.Key] = c;
                    }
                }
            }
            return output;
        }

        /// <summary>The mode the full-screen filter should run in: the setting's mode only when the file asks for
        /// the filter and has no palette for that mode; "none" otherwise.</summary>
        public static string FilterMode(Dictionary<string, object> data, string mode)
        {
            bool filter = data.TryGetValue("filter", out object f) && f is bool b && b;
            var palettes = data["palettes"] as Dictionary<string, object>;
            if (!filter || (palettes != null && palettes.ContainsKey(mode)))
            {
                return "none";
            }
            return mode;
        }

        private static Dictionary<string, object> Empty()
        {
            return new Dictionary<string, object>
            {
                { "filter", false },
                { "palettes", new Dictionary<string, object> { { "none", new Dictionary<string, object>() } } },
            };
        }
    }
}

// {{FOOTER}}
