// ---------------------------------------------------------------------------
// AudioDirector.cs
// Purpose : Decides how each game sound plays: which file of the event (no back-to-back repeats), its pitch and
//           volume within the event's ranges, voice limits (steal the oldest or refuse), cooldowns, and how far
//           a trigger bus (dialogue) ducks its target buses (music, ambience). Data comes from
//           data/audio_events.json. Checked against data/golden/audio.json ("audio_director").
// Usage   : var dir = AudioDirector.FromJson(File.ReadAllText(eventsPath));   // { seed?, events, ducking? }
//           AudioPlayResult r = dir.Play("step_stone", nowMs);            // r.Result: "played" | "cooldown" | "capped"
//           if (r.Played) { if (r.Stolen != null) StopVoice(r.Stolen.Value);
//                           StartVoice(r.Voice, dir.FileOf("step_stone", r.Variant), r.PitchRatio, r.GainDb); }
//           each frame: foreach (var kv in dir.Duck(nowMs)) SetBusDuckDb(kv.Key, kv.Value);
// Notes   : No UnityEngine types (EditMode tests run it): this class only decides, an AudioSource wrapper plays.
//           The spec is tools/audio/wavesmith/audio_events.py; every step of data/golden/audio.json must come out the same.
//           Parity rules: Park-Miller random source in long arithmetic (products stay below 2^53, no bit
//           operations), one generator per event seeded from its ASCII id, a fixed draw order (variant, pitch,
//           volume) and a rejected play (cooldown, voice cap) draws nothing. Times are milliseconds as double
//           and calls must come in time order. lengths_ms per file: from the imported clips' lengths.
//           The reference keeps every voice ever started for the ducking envelopes; this port only keeps
//           voices on a trigger bus that can still matter (ends after the last Duck time), which gives the
//           same numbers with memory that stays flat over a long session.
//
// Pseudocode:
//   Play(e, t): drop finished voices -> cooldown? "cooldown" -> at max_voices: steal oldest or "capped"
//               -> variant (sequence | random | random_no_repeat | shuffle) -> pitch -> volume
//               -> new voice that ends at t + length / pitch ratio
//   Duck(t):    per ducking rule: walk the trigger bus's voice edges since the last call, ramp in dB
//               (towards depth_db over attack_ms while a voice plays, back to 0 over release_ms when none does)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Globalization;

namespace graveyard_shift.Core
{
    /// <summary>What one Play call decided. Only Result is set unless Played is true.</summary>
    public sealed class AudioPlayResult
    {
        public string Result;              // AudioDirector.PLAYED | COOLDOWN | CAPPED
        public int Variant;                // index into the event's files
        public double PitchSemitones;
        public double PitchRatio;          // playback rate: 2^(semitones / 12)
        public double GainDb;
        public int Voice;                  // the new voice's id (1, 2, 3, ... per director)
        public int? Stolen;                // the voice to stop right now, null when nothing was stolen
        public double EndsMs;              // when the new voice finishes (its length divided by the pitch ratio)

        public bool Played => Result == AudioDirector.PLAYED;
    }

    /// <summary>Park-Miller minimal standard generator: exact in long arithmetic, so every language agrees.</summary>
    public sealed class ParkMiller
    {
        public const long M = 2147483647;      // 2^31 - 1
        public const long A = 16807;

        public long State { get; private set; }

        public ParkMiller(long seed)
        {
            long s = AudioDirector.PyMod(seed, M);
            State = s == 0 ? 1 : s;
        }

        /// <summary>A double in [0, 1).</summary>
        public double Next()
        {
            State = State * A % M;              // State < 2^31, so the product stays below 2^46
            return (State - 1) / (double)(M - 1);
        }
    }

    public sealed class AudioDirector
    {
        // ---- Tunables ------------------------------------------------------------
        public const int DEFAULT_MAX_VOICES = 8;
        public const double MAX_SEED = 9007199254740991.0;   // 2^53 - 1: Json.cs reads numbers as doubles, exact up to here
        public const string DEFAULT_PICK = PICK_RANDOM_NO_REPEAT;
        public const string DEFAULT_STEAL = STEAL_OLDEST;
        public const long DEFAULT_SEED = 1;
        public const long SEED_MIX = 7919;                 // the global seed's weight in each event's seed

        public const string PLAYED = "played";
        public const string COOLDOWN = "cooldown";
        public const string CAPPED = "capped";

        public const string PICK_SEQUENCE = "sequence";
        public const string PICK_RANDOM = "random";
        public const string PICK_RANDOM_NO_REPEAT = "random_no_repeat";
        public const string PICK_SHUFFLE = "shuffle";       // the reference treats any other pick name as shuffle
        public const string STEAL_OLDEST = "oldest";
        public const string STEAL_NONE = "none";

        // ---- State ---------------------------------------------------------------

        private sealed class EventDef
        {
            public string Bus;
            public string[] Files;
            public double[] LengthsMs;
            public string Pick;
            public double PitchLo, PitchHi;
            public double VolumeLo, VolumeHi;
            public double MaxVoices;                       // a number like the reference (8, or 2.0 from JSON)
            public string Steal;
            public double CooldownMs;
        }

        private sealed class DuckRule
        {
            public string Trigger;
            public string[] Targets;
            public double DepthDb;
            public double AttackMs;
            public double ReleaseMs;
        }

        private sealed class DuckState
        {
            public double Gain;
            public double T;
        }

        // A class on purpose: the same voice sits in _voices and _history, and stealing shortens its End in both
        private sealed class Voice
        {
            public int Id;
            public string Event;
            public string Bus;
            public double Start;
            public double End;
        }

        private readonly Dictionary<string, EventDef> _events = new Dictionary<string, EventDef>();
        private readonly List<DuckRule> _ducking = new List<DuckRule>();
        private readonly List<DuckState> _duckState = new List<DuckState>();
        private readonly HashSet<string> _triggerBuses = new HashSet<string>();
        private readonly Dictionary<string, ParkMiller> _rng = new Dictionary<string, ParkMiller>();
        private readonly List<Voice> _voices = new List<Voice>();      // playing (finished ones drop out on Play)
        private readonly List<Voice> _history = new List<Voice>();     // trigger-bus voices the envelopes still need
        private readonly Dictionary<string, double> _lastPlay = new Dictionary<string, double>();
        private readonly Dictionary<string, int> _lastVariant = new Dictionary<string, int>();
        private readonly Dictionary<string, List<int>> _bags = new Dictionary<string, List<int>>();
        private int _nextId = 1;
        private double _now;

        public long Seed { get; }

        // ---- Construction ----------------------------------------------------------

        /// <summary>A director from the events file's text. Throws FormatException on bad JSON and
        /// ArgumentException (naming the field) on a malformed event or ducking rule.</summary>
        public static AudioDirector FromJson(string text)
        {
            if (!(Json.Parse(text) is Dictionary<string, object> root))
            {
                throw new ArgumentException("audio events: the file must be a JSON object");
            }
            return new AudioDirector(root);
        }

        /// <summary>A director from the parsed value tree (Json.cs): { "seed"?, "events", "ducking"? }.</summary>
        public AudioDirector(Dictionary<string, object> parameters)
        {
            if (parameters == null)
            {
                throw new ArgumentNullException(nameof(parameters));
            }
            Seed = DEFAULT_SEED;
            if (parameters.TryGetValue("seed", out object seed))
            {
                double s = Json.IsNumber(seed) ? Json.ToNumber(seed) : double.NaN;
                if (double.IsNaN(s) || double.IsInfinity(s) || s != Math.Floor(s) || Math.Abs(s) > MAX_SEED)
                {
                    throw new ArgumentException("audio events: seed must be a whole number");
                }
                Seed = (long)s;
            }
            if (!(parameters.TryGetValue("events", out object events) && events is Dictionary<string, object> eventMap))
            {
                throw new ArgumentException("audio events: \"events\" must be an object of event id -> event");
            }
            foreach (KeyValuePair<string, object> entry in eventMap)
            {
                _events[entry.Key] = ParseEvent(entry.Key, entry.Value);
                _rng[entry.Key] = new ParkMiller(EventSeed(entry.Key, Seed));
            }
            if (parameters.TryGetValue("ducking", out object ducking) && ducking != null)
            {
                if (!(ducking is List<object> rules))
                {
                    throw new ArgumentException("audio events: \"ducking\" must be a list of rules");
                }
                for (int i = 0; i < rules.Count; i++)
                {
                    DuckRule rule = ParseDuckRule(i, rules[i]);
                    _ducking.Add(rule);
                    _duckState.Add(new DuckState());
                    _triggerBuses.Add(rule.Trigger);
                }
            }
        }

        /// <summary>The seed of one event's generator: a polynomial hash of its ASCII id mixed with the global seed.</summary>
        public static long EventSeed(string eventId, long globalSeed)
        {
            long h = 0;
            foreach (char ch in eventId)            // ids are ASCII (the validator checks), so code unit = code point
            {
                h = (h * 31 + ch) % ParkMiller.M;
            }
            long s = (h + PyMod(globalSeed, ParkMiller.M) * SEED_MIX) % ParkMiller.M;
            return s == 0 ? 1 : s;
        }

        // ---- Lookups for the player --------------------------------------------------

        public bool HasEvent(string eventName)
        {
            return eventName != null && _events.ContainsKey(eventName);
        }

        /// <summary>The file a Play result's Variant points at.</summary>
        public string FileOf(string eventName, int variant)
        {
            return Event(eventName).Files[variant];
        }

        public string BusOf(string eventName)
        {
            return Event(eventName).Bus;
        }

        // ---- Play ---------------------------------------------------------------------

        /// <summary>Decides one play of eventName at tMs. Throws KeyNotFoundException for an unknown event and
        /// ArgumentException when tMs is earlier than the previous call.</summary>
        public AudioPlayResult Play(string eventName, double tMs)
        {
            Clock(tMs);
            EventDef ev = Event(eventName);
            _voices.RemoveAll(v => !(v.End > tMs));
            if (ev.CooldownMs != 0 && _lastPlay.TryGetValue(eventName, out double last) && tMs - last < ev.CooldownMs)
            {
                return new AudioPlayResult { Result = COOLDOWN };
            }
            int? stolen = null;
            Voice victim = null;
            int mine = 0;
            foreach (Voice v in _voices)
            {
                if (v.Event != eventName)
                {
                    continue;
                }
                mine++;
                if (victim == null || v.Start < victim.Start || (v.Start == victim.Start && v.Id < victim.Id))
                {
                    victim = v;                    // the oldest: earliest start, then lowest id
                }
            }
            if (mine >= ev.MaxVoices)
            {
                if (ev.Steal == STEAL_NONE)
                {
                    return new AudioPlayResult { Result = CAPPED };
                }
                if (victim == null)                // max_voices below 1: the reference fails here too (min of nothing)
                {
                    throw new InvalidOperationException($"audio director: event {eventName}: max_voices must be 1 or more");
                }
                victim.End = tMs;                 // it stops now (the ducking envelope sees that)
                _voices.Remove(victim);
                stolen = victim.Id;
            }
            // Draw order is part of the spec: variant, then pitch, then volume
            ParkMiller rng = _rng[eventName];
            int idx = PickVariant(eventName, ev, rng);
            double semis = ev.PitchLo == ev.PitchHi ? ev.PitchLo : ev.PitchLo + (ev.PitchHi - ev.PitchLo) * rng.Next();
            double gain = ev.VolumeLo == ev.VolumeHi ? ev.VolumeLo : ev.VolumeLo + (ev.VolumeHi - ev.VolumeLo) * rng.Next();
            double ratio = Math.Pow(2.0, semis / 12.0);
            var voice = new Voice
            {
                Id = _nextId++, Event = eventName, Bus = ev.Bus, Start = tMs, End = tMs + ev.LengthsMs[idx] / ratio,
            };
            _voices.Add(voice);
            if (_triggerBuses.Contains(ev.Bus))
            {
                _history.Add(voice);               // only trigger-bus voices ever shape an envelope
            }
            _lastPlay[eventName] = tMs;
            _lastVariant[eventName] = idx;
            return new AudioPlayResult
            {
                Result = PLAYED, Variant = idx, PitchSemitones = semis, PitchRatio = ratio, GainDb = gain,
                Voice = voice.Id, Stolen = stolen, EndsMs = voice.End,
            };
        }

        // ---- Duck ---------------------------------------------------------------------

        /// <summary>{target bus: duck gain in dB (0 or below)} at tMs, every rule advanced to tMs. A bus named
        /// by several rules gets the deepest one. Throws ArgumentException when tMs is earlier than the last call.</summary>
        public Dictionary<string, double> Duck(double tMs)
        {
            Clock(tMs);
            var output = new Dictionary<string, double>();
            for (int r = 0; r < _ducking.Count; r++)
            {
                DuckRule rule = _ducking[r];
                DuckState st = _duckState[r];
                // Every start or end of a trigger-bus voice strictly between the last call and now, ascending
                var edgeSet = new HashSet<double>();
                foreach (Voice v in _history)
                {
                    if (v.Bus != rule.Trigger)
                    {
                        continue;
                    }
                    if (st.T < v.Start && v.Start < tMs)
                    {
                        edgeSet.Add(v.Start);
                    }
                    if (st.T < v.End && v.End < tMs)
                    {
                        edgeSet.Add(v.End);
                    }
                }
                var edges = new List<double>(edgeSet);
                edges.Sort();
                edges.Add(tMs);
                double gain = st.Gain, at = st.T;
                foreach (double edge in edges)
                {
                    gain = Ramp(gain, AnyPlaying(rule.Trigger, at), rule, edge - at);
                    at = edge;
                }
                st.Gain = gain;
                st.T = tMs;
                foreach (string bus in rule.Targets)
                {
                    output[bus] = Math.Min(output.TryGetValue(bus, out double prev) ? prev : 0.0, gain);
                }
            }
            // Every rule now stands at tMs: a voice that ended by then adds no edge and is never playing at a
            // later segment start, so dropping it keeps the numbers identical to the reference
            if (_ducking.Count > 0)
            {
                _history.RemoveAll(v => v.End <= tMs);
            }
            return output;
        }

        // ---- Internals -------------------------------------------------------------------

        private void Clock(double tMs)
        {
            if (double.IsNaN(tMs))
            {
                throw new ArgumentException("audio director: the time is NaN");
            }
            if (tMs < _now)
            {
                throw new ArgumentException(string.Format(CultureInfo.InvariantCulture,
                    "audio director: calls must come in time order ({0} ms after {1} ms)", tMs, _now));
            }
            _now = tMs;
        }

        private EventDef Event(string eventName)
        {
            if (eventName == null || !_events.TryGetValue(eventName, out EventDef ev))
            {
                throw new KeyNotFoundException($"audio director: unknown event '{eventName}'");
            }
            return ev;
        }

        // The variant index; draws from rng only as the pick rule needs (n == 1 and sequence draw nothing)
        private int PickVariant(string eventName, EventDef ev, ParkMiller rng)
        {
            int n = ev.Files.Length;
            int last = _lastVariant.TryGetValue(eventName, out int lv) ? lv : -1;
            if (n == 1)
            {
                return 0;
            }
            switch (ev.Pick)
            {
                case PICK_SEQUENCE:
                    return (last + 1) % n;
                case PICK_RANDOM:
                    return Draw(rng, n);
                case PICK_RANDOM_NO_REPEAT:
                    if (last < 0)
                    {
                        return Draw(rng, n);
                    }
                    int k = Draw(rng, n - 1);              // one of the other n - 1 files
                    return k >= last ? k + 1 : k;
            }
            // shuffle: a bag of every index; refill with Fisher-Yates when empty, newest choice at the front
            if (!_bags.TryGetValue(eventName, out List<int> bag) || bag.Count == 0)
            {
                bag = new List<int>(n);
                for (int i = 0; i < n; i++)
                {
                    bag.Add(i);
                }
                for (int i = n - 1; i > 0; i--)
                {
                    int j = Draw(rng, i + 1);
                    (bag[i], bag[j]) = (bag[j], bag[i]);
                }
                if (bag[0] == last)                         // never the same file twice across a refill
                {
                    (bag[0], bag[1]) = (bag[1], bag[0]);
                }
                _bags[eventName] = bag;
            }
            int idx = bag[0];
            bag.RemoveAt(0);
            return idx;
        }

        // min(int(u * n), n - 1) as in the reference: u >= 0, so int() is floor
        private static int Draw(ParkMiller rng, int n)
        {
            return (int)Math.Min(Math.Floor(rng.Next() * n), n - 1);
        }

        private bool AnyPlaying(string bus, double at)
        {
            foreach (Voice v in _history)
            {
                if (v.Bus == bus && v.Start <= at && at < v.End)
                {
                    return true;
                }
            }
            return false;
        }

        // One straight segment of the envelope in dB: dt ms with the trigger bus playing (active) or silent
        private static double Ramp(double gain, bool active, DuckRule rule, double dt)
        {
            double depth = rule.DepthDb;
            if (active)
            {
                if (rule.AttackMs <= 0)
                {
                    return depth;
                }
                return Math.Max(depth, gain + depth / rule.AttackMs * dt);
            }
            if (rule.ReleaseMs <= 0)
            {
                return 0.0;
            }
            return Math.Min(0.0, gain - depth / rule.ReleaseMs * dt);
        }

        // Python's a % m for m > 0: never negative (C#'s % keeps the sign of a)
        internal static long PyMod(long a, long m)
        {
            long r = a % m;
            return r < 0 ? r + m : r;
        }

        // ---- Parsing (defaults as in the reference) -----------------------------------------

        private static EventDef ParseEvent(string name, object value)
        {
            string where = $"audio events: event {name}";
            if (!(value is Dictionary<string, object> ev))
            {
                throw new ArgumentException($"{where}: must be an object");
            }
            var def = new EventDef
            {
                Bus = RequireText(ev, "bus", where),
                Files = TextList(ev, "files", where),
                LengthsMs = NumberList(ev, "lengths_ms", where),
                Pick = OptionalText(ev, "pick", DEFAULT_PICK, where),
                MaxVoices = OptionalNumber(ev, "max_voices", DEFAULT_MAX_VOICES, where),
                Steal = OptionalText(ev, "steal", DEFAULT_STEAL, where),
                CooldownMs = OptionalNumber(ev, "cooldown_ms", 0.0, where),
            };
            if (def.Files.Length == 0)
            {
                throw new ArgumentException($"{where}: files must be a non-empty list");
            }
            if (def.LengthsMs.Length < def.Files.Length)
            {
                throw new ArgumentException($"{where}: lengths_ms needs one length per file");
            }
            Range(ev, "pitch_semitones", where, out def.PitchLo, out def.PitchHi);
            Range(ev, "volume_db", where, out def.VolumeLo, out def.VolumeHi);
            return def;
        }

        private static DuckRule ParseDuckRule(int index, object value)
        {
            string where = $"audio events: ducking[{index}]";
            if (!(value is Dictionary<string, object> rule))
            {
                throw new ArgumentException($"{where}: must be an object");
            }
            return new DuckRule
            {
                Trigger = RequireText(rule, "trigger", where),
                Targets = TextList(rule, "targets", where),
                DepthDb = RequireNumber(rule, "depth_db", where),
                AttackMs = OptionalNumber(rule, "attack_ms", 0.0, where),
                ReleaseMs = OptionalNumber(rule, "release_ms", 0.0, where),
            };
        }

        private static string RequireText(Dictionary<string, object> obj, string key, string where)
        {
            if (!(obj.TryGetValue(key, out object v) && v is string s))
            {
                throw new ArgumentException($"{where}: {key} must be text");
            }
            return s;
        }

        private static string OptionalText(Dictionary<string, object> obj, string key, string fallback, string where)
        {
            return obj.ContainsKey(key) ? RequireText(obj, key, where) : fallback;
        }

        private static double RequireNumber(Dictionary<string, object> obj, string key, string where)
        {
            if (!(obj.TryGetValue(key, out object v) && Json.IsNumber(v)))
            {
                throw new ArgumentException($"{where}: {key} must be a number");
            }
            return Json.ToNumber(v);
        }

        private static double OptionalNumber(Dictionary<string, object> obj, string key, double fallback, string where)
        {
            return obj.ContainsKey(key) ? RequireNumber(obj, key, where) : fallback;
        }

        private static string[] TextList(Dictionary<string, object> obj, string key, string where)
        {
            if (!(obj.TryGetValue(key, out object v) && v is List<object> list))
            {
                throw new ArgumentException($"{where}: {key} must be a list of text");
            }
            var output = new string[list.Count];
            for (int i = 0; i < list.Count; i++)
            {
                output[i] = list[i] as string ?? throw new ArgumentException($"{where}: {key}[{i}] must be text");
            }
            return output;
        }

        private static double[] NumberList(Dictionary<string, object> obj, string key, string where)
        {
            if (!(obj.TryGetValue(key, out object v) && v is List<object> list))
            {
                throw new ArgumentException($"{where}: {key} must be a list of numbers");
            }
            var output = new double[list.Count];
            for (int i = 0; i < list.Count; i++)
            {
                if (!Json.IsNumber(list[i]))
                {
                    throw new ArgumentException($"{where}: {key}[{i}] must be a number");
                }
                output[i] = Json.ToNumber(list[i]);
            }
            return output;
        }

        // [low, high]; missing = [0, 0] (no randomization, nothing drawn)
        private static void Range(Dictionary<string, object> obj, string key, string where, out double lo, out double hi)
        {
            lo = hi = 0.0;
            if (!obj.ContainsKey(key))
            {
                return;
            }
            double[] pair = NumberList(obj, key, where);
            if (pair.Length != 2)
            {
                throw new ArgumentException($"{where}: {key} must be [low, high]");
            }
            lo = pair[0];
            hi = pair[1];
        }
    }
}
