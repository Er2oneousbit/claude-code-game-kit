// ---------------------------------------------------------------------------
// Bindings.cs
// Purpose : Input bindings as data: the default map, rebinding with conflict swaps, and which button art
//           (glyphs) to show for a prompt. Checked against data/golden/shell.json ("rebind", "glyph_set",
//           "glyph_name", "prompt_binding").
// Usage   : var bindings = Bindings.Defaults();                    // or the "bindings" object of the settings
//           var r = Bindings.Rebind(bindings, "jump", 0, "key:k");  // r.Bindings, r.Conflicts (the swapped slots)
//           string set = Bindings.GlyphSet(glyphSetting, lastDevice);          // "auto" follows the last device
//           string art = Bindings.GlyphName(set, Bindings.PromptBinding(bindings, "jump", set));  // "xbox_a"
// Notes   : No UnityEngine types (EditMode tests run it). A binding is "kind:name": key:space, mouse:left,
//           pad:south (the face button at the bottom, whatever the brand), pad_axis:leftx-. Slot 0 is the
//           keyboard binding, slot 1 the pad one, more slots are extras. Bindings live in the settings JSON
//           tree (Dictionary<string, object> of List<object>), so unknown actions survive a load and a save;
//           Bindings.Of(bindings, action) gives a typed copy. Mapping these names to the Input System (or the
//           old Input Manager) is glue in Assets/Scripts/Game. Rebinding swaps only inside one group: ui_*
//           actions and game actions may share a key (Enter can confirm in menus and jump in play).
//
// Pseudocode (rebind):
//   copy the map ; old = the slot's current binding ("" when the slot is new)
//   conflicts = every other (action, slot) of the same group holding the new binding, in sorted order
//   put the binding in the slot ; every conflict gets old (a swap), or "" (unbound) when there was none
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public sealed class RebindResult
    {
        public Dictionary<string, object> Bindings;
        public List<(string Action, int Slot)> Conflicts;
    }

    public static class Bindings
    {
        // ---- Tunables ------------------------------------------------------------
        public const string UNBOUND = "";
        public const int KEYBOARD_SLOT = 0;
        public const int PAD_SLOT = 1;
        public static readonly string[] GLYPH_SETS = { "auto", "keyboard", "xbox", "playstation", "generic" };

        // action, keyboard binding, pad binding
        private static readonly string[][] DEFAULTS =
        {
            new[] { "ui_up", "key:up", "pad:dpad_up" },
            new[] { "ui_down", "key:down", "pad:dpad_down" },
            new[] { "ui_left", "key:left", "pad:dpad_left" },
            new[] { "ui_right", "key:right", "pad:dpad_right" },
            new[] { "ui_accept", "key:enter", "pad:south" },
            new[] { "ui_cancel", "key:escape", "pad:east" },
            new[] { "move_left", "key:a", "pad:dpad_left" },
            new[] { "move_right", "key:d", "pad:dpad_right" },
            new[] { "move_up", "key:w", "pad:dpad_up" },
            new[] { "move_down", "key:s", "pad:dpad_down" },
            new[] { "jump", "key:space", "pad:south" },
            new[] { "attack", "key:j", "pad:west" },
            new[] { "interact", "key:e", "pad:north" },
            new[] { "pause", "key:escape", "pad:start" },
        };

        // last device -> glyph set, for the "auto" setting; anything else is "generic"
        private static readonly Dictionary<string, string> DEVICE_GLYPHS = new Dictionary<string, string>
        {
            { "keyboard", "keyboard" }, { "mouse", "keyboard" }, { "pad_xbox", "xbox" },
            { "pad_playstation", "playstation" },
        };

        private static readonly Dictionary<string, string> XBOX = new Dictionary<string, string>
        {
            { "south", "a" }, { "east", "b" }, { "west", "x" }, { "north", "y" }, { "l1", "lb" }, { "r1", "rb" },
            { "l2", "lt" }, { "r2", "rt" }, { "start", "menu" }, { "select", "view" },
        };

        private static readonly Dictionary<string, string> PLAYSTATION = new Dictionary<string, string>
        {
            { "south", "cross" }, { "east", "circle" }, { "west", "square" }, { "north", "triangle" },
            { "start", "options" }, { "select", "share" },
        };

        /// <summary>A fresh copy of the default bindings (action -> list of binding strings).</summary>
        public static Dictionary<string, object> Defaults()
        {
            var map = new Dictionary<string, object>();
            foreach (string[] row in DEFAULTS)
            {
                map[row[0]] = new List<object> { row[1], row[2] };
            }
            return map;
        }

        /// <summary>"ui" for ui_* actions, "game" for the rest: conflicts only count inside one group.</summary>
        public static string GroupOf(string action)
        {
            return action.StartsWith("ui_", StringComparison.Ordinal) ? "ui" : "game";
        }

        /// <summary>The action's bindings as strings (a copy; empty when the action is unknown).</summary>
        public static List<string> Of(Dictionary<string, object> bindings, string action)
        {
            var result = new List<string>();
            if (bindings != null && bindings.TryGetValue(action, out object value) && value is List<object> list)
            {
                foreach (object item in list)
                {
                    result.Add(item as string ?? UNBOUND);
                }
            }
            return result;
        }

        /// <summary>Puts binding in action's slot (slot == count appends one). Another action of the same group
        /// that used it gets this slot's old binding (a swap), or "" when there was none.</summary>
        public static RebindResult Rebind(Dictionary<string, object> bindings, string action, int slot, string binding)
        {
            var map = (Dictionary<string, object>)Json.DeepCopy(bindings);
            if (!map.TryGetValue(action, out object value) || !(value is List<object> list))
            {
                list = new List<object>();
                map[action] = list;
            }
            if (slot < 0 || slot > list.Count)
            {
                throw new ArgumentOutOfRangeException(nameof(slot), $"slot {slot} is past the end of {action}");
            }
            object old = slot < list.Count ? list[slot] : UNBOUND;
            var conflicts = new List<(string Action, int Slot)>();
            var actions = new List<string>(map.Keys);
            actions.Sort(StringComparer.Ordinal);
            string group = GroupOf(action);
            foreach (string other in actions)
            {
                if (GroupOf(other) != group || !(map[other] is List<object> slots))
                {
                    continue;
                }
                for (int s = 0; s < slots.Count; s++)
                {
                    bool same = other == action && s == slot;
                    if (!same && binding != UNBOUND && slots[s] is string name && name == binding)
                    {
                        conflicts.Add((other, s));
                    }
                }
            }
            if (slot == list.Count)
            {
                list.Add(binding);
            }
            else
            {
                list[slot] = binding;
            }
            foreach ((string other, int s) in conflicts)
            {
                ((List<object>)map[other])[s] = old;
            }
            return new RebindResult { Bindings = map, Conflicts = conflicts };
        }

        /// <summary>Which prompt art to show: the player's choice, or (auto) the last device used.</summary>
        public static string GlyphSet(string setting, string lastDevice)
        {
            if (setting != "auto")
            {
                return setting;
            }
            return lastDevice != null && DEVICE_GLYPHS.TryGetValue(lastDevice, out string set) ? set : "generic";
        }

        /// <summary>The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south,
        /// xbox_lstick... "unknown" for a binding kind it does not know.</summary>
        public static string GlyphName(string glyphSet, string binding)
        {
            int colon = binding.IndexOf(':');
            string kind = colon < 0 ? binding : binding.Substring(0, colon);
            string name = colon < 0 ? "" : binding.Substring(colon + 1);
            if (kind == "key")
            {
                return "key_" + name;
            }
            if (kind == "mouse")
            {
                return "mouse_" + name;
            }
            if (kind == "pad_axis")
            {
                name = name.StartsWith("left", StringComparison.Ordinal) ? "lstick" : "rstick";
            }
            else if (kind != "pad")
            {
                return "unknown";
            }
            if (glyphSet == "xbox")
            {
                return "xbox_" + (XBOX.TryGetValue(name, out string x) ? x : name);
            }
            if (glyphSet == "playstation")
            {
                return "ps_" + (PLAYSTATION.TryGetValue(name, out string p) ? p : name);
            }
            return "pad_" + name;
        }

        /// <summary>The binding to show for an action: slot 0 for the keyboard set, slot 1 (pad) otherwise;
        /// "" when the action has no such slot.</summary>
        public static string PromptBinding(Dictionary<string, object> bindings, string action, string glyphSet)
        {
            List<string> slots = Of(bindings, action);
            int slot = glyphSet == "keyboard" ? KEYBOARD_SLOT : PAD_SLOT;
            return slot < slots.Count ? slots[slot] : UNBOUND;
        }

        /// <summary>What the narration says for one control (#165): "Music volume, slider, 70 percent"; no label says "unlabelled".</summary>
        public static string NarrationLine(string label, string role, string value = "")
        {
            var parts = new List<string> { OneLine(label) != "" ? OneLine(label) : "unlabelled" };
            if (OneLine(role) != "") parts.Add(OneLine(role));
            if (OneLine(value) != "") parts.Add(OneLine(value));
            return string.Join(", ", parts);
        }

        static string OneLine(string text) =>
            string.Join(" ", (text ?? "").Split((char[])null, System.StringSplitOptions.RemoveEmptyEntries));
    }
}
