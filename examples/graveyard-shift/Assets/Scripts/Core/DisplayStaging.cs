// ---------------------------------------------------------------------------
// DisplayStaging.cs
// Purpose : The settings screen's Display tab with an Apply button (#308): Display changes wait for Apply, every
//           other tab applies at once. Engine-free (no UnityEngine): it never touches the window, it returns the
//           (field, value) calls the shell makes through Shell.SetValue.
// Usage   : var st = new DisplayStaging((Dictionary<string, object>)settings["display"]);
//           st.Stage("resolution", new List<object> { 1280.0, 720.0 });   // the row shows st.Value("resolution")
//           foreach (var (field, v) in st.Apply()) shell.SetValue("display", field, v);   // then save
//           each frame: st.Tick(realDt)  (REAL seconds: Time.unscaledDeltaTime, never Time.deltaTime)
//           st.Keep() / st.Revert() / st.Back()
// Notes   : tools/golden_vectors.py DisplayStaging is the spec, data/golden/shell.json's display_staging cases the
//           test (Tests/EditMode/ShellVectorTests.cs). Values compare by value (1 equals 1.0, [w, h] item by item).
//           Rules:
//           - Stage(field, v): a pending change; staging the applied value drops it. "busy" while the confirm is
//             open (the screen takes no row input then).
//           - Apply(): the pending fields that differ, in APPLY_ORDER (mode before resolution); remembers the values
//             they replace; a change to mode or resolution opens the confirm (CONFIRM_S).
//           - Tick(dt): the countdown; reaching 0 reverts. Seconds() is ceil(left) for "Reverting in N s".
//           - Keep(): closes the confirm. Revert(): puts back exactly what the last Apply replaced.
//           - Back(): during the confirm it reverts (a screen the player cannot see must never stick); with pending
//             changes the first Back warns, the second discards them; else it leaves.
//
// Pseudocode:
//   Apply : changed = pending fields != applied; replaced = their applied values; pending = {}; Set(changed);
//           changed has mode or resolution -> left = CONFIRM_S
//   Set(v): for field in APPLY_ORDER: if in v -> applied[field] = v[field], call (field, v[field])
//   Tick  : left -= dt; left <= 0 -> Revert()
//   Back  : confirm open -> ("revert", Revert()) ; pending and not warned -> warned, "warn" ; else discard, "leave"
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace graveyard_shift.Core
{
    public sealed class DisplayStaging
    {
        // ---- Tunables ------------------------------------------------------------
        /// <summary>The Display fields in the order Apply sets them: mode before resolution.</summary>
        public static readonly string[] APPLY_ORDER = { "mode", "resolution", "vsync", "frame_cap", "ui_scale" };
        /// <summary>Fields that can black out the screen: Apply asks "keep these?".</summary>
        public static readonly string[] CONFIRM_FIELDS = { "mode", "resolution" };
        public const double CONFIRM_S = 15.0;       // real seconds before an unanswered confirm reverts

        private readonly Dictionary<string, object> _applied;
        private readonly Dictionary<string, object> _pending = new Dictionary<string, object>();
        private Dictionary<string, object> _replaced = new Dictionary<string, object>();
        private double? _left;
        private bool _warned;

        /// <summary>applied: the Display section as it is now (copied).</summary>
        public DisplayStaging(Dictionary<string, object> applied)
        {
            _applied = (Dictionary<string, object>)Json.DeepCopy(applied ?? new Dictionary<string, object>());
        }

        public Dictionary<string, object> Applied => _applied;
        public Dictionary<string, object> Pending => _pending;
        public bool Confirming => _left.HasValue;
        public bool HasPending => _pending.Count > 0;

        /// <summary>What a Display row shows: the pending value, else the applied one (null for an unknown field).</summary>
        public object Value(string field)
        {
            if (_pending.TryGetValue(field, out object p))
            {
                return p;
            }
            return _applied.TryGetValue(field, out object a) ? a : null;
        }

        /// <summary>"staged", or "busy" while the confirm is open.</summary>
        public string Stage(string field, object v)
        {
            if (_left.HasValue)
            {
                return "busy";
            }
            if (_applied.TryGetValue(field, out object a) && Same(a, v))
            {
                _pending.Remove(field);
            }
            else
            {
                _pending[field] = Json.DeepCopy(v);
            }
            _warned = false;
            return "staged";
        }

        public List<(string Field, object Value)> Apply()
        {
            var changed = new Dictionary<string, object>();
            foreach (KeyValuePair<string, object> p in _pending)
            {
                if (!_applied.TryGetValue(p.Key, out object a) || !Same(a, p.Value))
                {
                    changed[p.Key] = p.Value;
                }
            }
            _replaced = new Dictionary<string, object>();
            foreach (string field in changed.Keys)
            {
                _replaced[field] = _applied.TryGetValue(field, out object a) ? Json.DeepCopy(a) : null;
            }
            _pending.Clear();
            _warned = false;
            List<(string, object)> calls = Set(changed);
            foreach (string f in CONFIRM_FIELDS)
            {
                if (changed.ContainsKey(f))
                {
                    _left = CONFIRM_S;
                }
            }
            return calls;
        }

        /// <summary>ceil(seconds left) while the confirm is open, else null.</summary>
        public int? Seconds()
        {
            return _left.HasValue ? (int?)(int)Math.Ceiling(_left.Value) : null;
        }

        /// <summary>dt in REAL seconds. Returns the revert's calls on the frame the countdown runs out.</summary>
        public List<(string Field, object Value)> Tick(double dt)
        {
            if (!_left.HasValue)
            {
                return new List<(string, object)>();
            }
            _left -= dt;
            return _left.Value <= 0.0 ? Revert() : new List<(string, object)>();
        }

        public void Keep()
        {
            _left = null;
            _replaced = new Dictionary<string, object>();
        }

        public List<(string Field, object Value)> Revert()
        {
            List<(string, object)> calls = Set(_replaced);
            _left = null;
            _replaced = new Dictionary<string, object>();
            return calls;
        }

        /// <summary>("revert", calls) during the confirm, ("warn", none) the first time with pending changes, else
        /// ("leave", none).</summary>
        public (string What, List<(string Field, object Value)> Calls) Back()
        {
            if (_left.HasValue)
            {
                return ("revert", Revert());
            }
            if (_pending.Count > 0 && !_warned)
            {
                _warned = true;
                return ("warn", new List<(string, object)>());
            }
            _pending.Clear();
            _warned = false;
            return ("leave", new List<(string, object)>());
        }

        private List<(string, object)> Set(Dictionary<string, object> values)
        {
            var calls = new List<(string, object)>();
            foreach (string field in APPLY_ORDER)
            {
                if (values.TryGetValue(field, out object v))
                {
                    _applied[field] = Json.DeepCopy(v);
                    calls.Add((field, Json.DeepCopy(v)));
                }
            }
            return calls;
        }

        /// <summary>JSON equality by value: numbers by value (1 == 1.0), lists item by item, objects key by key.</summary>
        public static bool Same(object a, object b)
        {
            if (Json.IsNumber(a) && Json.IsNumber(b))
            {
                return Json.ToNumber(a) == Json.ToNumber(b);
            }
            if (a is List<object> la && b is List<object> lb)
            {
                if (la.Count != lb.Count)
                {
                    return false;
                }
                for (int i = 0; i < la.Count; i++)
                {
                    if (!Same(la[i], lb[i]))
                    {
                        return false;
                    }
                }
                return true;
            }
            if (a is Dictionary<string, object> da && b is Dictionary<string, object> db)
            {
                if (da.Count != db.Count)
                {
                    return false;
                }
                foreach (KeyValuePair<string, object> e in da)
                {
                    if (!db.TryGetValue(e.Key, out object other) || !Same(e.Value, other))
                    {
                        return false;
                    }
                }
                return true;
            }
            return Equals(a, b);
        }
    }
}
