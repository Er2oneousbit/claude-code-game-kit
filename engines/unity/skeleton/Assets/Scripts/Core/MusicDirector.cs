// ---------------------------------------------------------------------------
// MusicDirector.cs
// Purpose : The adaptive-music rules of data/music.json with no UnityEngine types in them (EditMode tests run
//           them against data/golden/music.json): the sample grid, loop points, where playback is, the next beat /
//           bar / phrase / loop end, which transition rule applies, and the plan for a change (when, fade,
//           stinger, entry point).
// Usage   : var music = MusicDirector.FromJson(File.ReadAllText(musicPath));
//           MusicPlan p = music.Plan("explore", sinceSample, entrySample, "combat", nowSample);
//           p.SwitchAt, p.FromStopAt, p.ToStartAt, p.ToOffset, p.StingerAt   (all in samples at music.SampleRate)
//           MusicDirector.BeatSample(k, bpm, rate); music.LoopPoints("explore")   // the grid, for the player
// Notes   : The spec is tools/audio/wavesmith/music.py; every value is a whole number of samples and must match the
//           golden file exactly. Samples are long: a session of a few hours at 48 kHz passes 2^31. Beat k starts at
//           floor(k * 60 * rate / bpm + 0.5): Math.Round is not used (it rounds halves to even by default, which is
//           not the rule). The double arithmetic matches Python's: every product of whole numbers here stays below
//           2^53, so it is exact, and one IEEE division is correctly rounded in both languages.
//           MusicPlayer.cs (Assets/Scripts/Game) turns a plan into scheduled AudioSources.
//
// Pseudocode:
//   BeatSample(k) = floor(k * 60 * rate / bpm + 0.5); bar b starts at BeatSample(b * beats_per_bar)
//   Position(since, now, entry): p = now - since + entry; past the loop end -> wrap into [loop start, loop end)
//   Plan(from, to, now): rule (exact pair, from *, to *, default) -> next boundary of its quantize at or after p
//                        -> switch_at = now + (boundary - p); stinger? target enters after the stinger's bars
//                        -> target entry offset 0, or the same place in the bar when "sync" and the grids match
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;

namespace {{GAME_SLUG}}.Core
{
    /// <summary>One track of music.json: a bar grid and the stems (files) that play in sync on it.</summary>
    public sealed class MusicTrack
    {
        public string Name;
        public double Bpm;                                   // 137.5 is fine: the grid rounds to whole samples
        public long BeatsPerBar = 4;
        public long Bars;
        public long LoopStartBar;                            // bars before it are an intro that plays once
        public Dictionary<string, string> Stems = new Dictionary<string, string>();   // stem name -> file
    }

    /// <summary>A one-shot that plays at the switch point; the next track enters after its bars.</summary>
    public sealed class MusicStinger
    {
        public string File;
        public double Bars;                                  // may be fractional (1.5 bars), as in the reference
    }

    /// <summary>A transition rule after merging (built-in default, then default_transition, then the rule).</summary>
    public sealed class MusicRule
    {
        public string Quantize = MusicDirector.QUANTIZE_BAR;
        public double FadeMs;
        public bool Sync;
        public string Stinger;                               // null for none
        public long PhraseBars = MusicDirector.DEFAULT_PHRASE_BARS;
    }

    /// <summary>What Plan decided, in samples on the clock the caller passed in. StingerAt is null without a stinger.</summary>
    public sealed class MusicPlan
    {
        public long SwitchAt;                                // the boundary: old track starts to fade (or stops)
        public long FromStopAt;                              // SwitchAt + Fade: old track is silent and stopped
        public long Fade;                                    // fade length in samples (0 = a hard cut)
        public long ToOffset;                                // where in the new track it enters (samples from its start)
        public long ToStartAt;                               // when the new track starts
        public string Stinger;                               // the stinger's name, null for none
        public long? StingerAt;
    }

    public sealed class MusicDirector
    {
        // ---- Tunables ------------------------------------------------------------
        public const int VERSION = 1;
        public const long DEFAULT_BEATS_PER_BAR = 4;
        public const long DEFAULT_PHRASE_BARS = 4;

        public const string QUANTIZE_IMMEDIATE = "immediate";
        public const string QUANTIZE_BEAT = "beat";
        public const string QUANTIZE_BAR = "bar";
        public const string QUANTIZE_PHRASE = "phrase";
        public const string QUANTIZE_LOOP_END = "loop_end";
        public static readonly string[] QUANTIZE =
        {
            QUANTIZE_IMMEDIATE, QUANTIZE_BEAT, QUANTIZE_BAR, QUANTIZE_PHRASE, QUANTIZE_LOOP_END,
        };
        public const string ANY = "*";

        // The built-in rule under every other one (music.py DEFAULT_RULE)
        private static readonly Dictionary<string, object> DEFAULT_RULE = new Dictionary<string, object>
        {
            { "quantize", QUANTIZE_BAR }, { "fade_ms", 0.0 }, { "sync", false },
        };

        // ---- State ---------------------------------------------------------------
        private readonly Dictionary<string, MusicTrack> _tracks = new Dictionary<string, MusicTrack>();
        private readonly Dictionary<string, MusicStinger> _stingers = new Dictionary<string, MusicStinger>();
        private readonly List<Dictionary<string, object>> _transitions = new List<Dictionary<string, object>>();
        private readonly Dictionary<string, object> _defaultTransition = new Dictionary<string, object>();

        public long SampleRate { get; }
        public string Start { get; }                         // the track to start with, null when the file names none
        public IReadOnlyDictionary<string, MusicTrack> Tracks => _tracks;
        public IReadOnlyDictionary<string, MusicStinger> Stingers => _stingers;

        // ---- Construction ----------------------------------------------------------

        /// <summary>A director from music.json's text. Throws FormatException on bad JSON and ArgumentException
        /// (naming the field) on a malformed track, stinger or transition.</summary>
        public static MusicDirector FromJson(string text)
        {
            if (!(Json.Parse(text) is Dictionary<string, object> root))
            {
                throw new ArgumentException("music: the file must be a JSON object");
            }
            return new MusicDirector(root);
        }

        /// <summary>A director from the parsed value tree (Json.cs): { sample_rate, tracks, stingers?, transitions?,
        /// default_transition?, start? }. Only what Plan needs is checked here; music.py validate checks the rest
        /// (files, loop chunks, ranges).</summary>
        public MusicDirector(Dictionary<string, object> data)
        {
            if (data == null)
            {
                throw new ArgumentNullException(nameof(data));
            }
            SampleRate = RequireWhole(data, "sample_rate", "music");
            if (SampleRate < 1)
            {
                throw new ArgumentException("music: sample_rate must be a whole number of Hz above 0");
            }
            if (!(data.TryGetValue("tracks", out object tracks) && tracks is Dictionary<string, object> trackMap)
                || trackMap.Count == 0)
            {
                throw new ArgumentException("music: \"tracks\" must be an object of track name -> track");
            }
            foreach (KeyValuePair<string, object> entry in trackMap)
            {
                _tracks[entry.Key] = ParseTrack(entry.Key, entry.Value);
            }
            if (data.TryGetValue("stingers", out object stingers) && stingers != null)
            {
                if (!(stingers is Dictionary<string, object> stingerMap))
                {
                    throw new ArgumentException("music: \"stingers\" must be an object of stinger name -> stinger");
                }
                foreach (KeyValuePair<string, object> entry in stingerMap)
                {
                    _stingers[entry.Key] = ParseStinger(entry.Key, entry.Value);
                }
            }
            if (data.TryGetValue("default_transition", out object def) && def != null)
            {
                if (!(def is Dictionary<string, object> defMap))
                {
                    throw new ArgumentException("music: \"default_transition\" must be an object");
                }
                foreach (KeyValuePair<string, object> kv in defMap)
                {
                    _defaultTransition[kv.Key] = kv.Value;
                }
            }
            if (data.TryGetValue("transitions", out object transitions) && transitions != null)
            {
                if (!(transitions is List<object> list))
                {
                    throw new ArgumentException("music: \"transitions\" must be a list of rules");
                }
                for (int i = 0; i < list.Count; i++)
                {
                    if (!(list[i] is Dictionary<string, object> rule))
                    {
                        throw new ArgumentException($"music: transitions[{i}] must be an object");
                    }
                    _transitions.Add(rule);
                    ParseRule(Merge(rule), $"music: transitions[{i}]");   // fail now, not at the first change
                }
            }
            ParseRule(Merge(null), "music: default_transition");
            if (data.TryGetValue("start", out object start) && start != null)
            {
                Start = start as string;
                if (Start == null || !_tracks.ContainsKey(Start))
                {
                    throw new ArgumentException("music: start must name a track");
                }
            }
        }

        // ---- The grid ------------------------------------------------------------------

        /// <summary>First sample of beat k (k may be fractional, e.g. a stinger of 1.5 bars, or negative).</summary>
        public static long BeatSample(double k, double bpm, long rate)
        {
            // Left to right like Python's k * 60 * rate / bpm: whole-number products are exact below 2^53
            return (long)Math.Floor(k * 60.0 * rate / bpm + 0.5);
        }

        public static long BarSample(long bar, MusicTrack track, long rate)
        {
            return BeatSample(bar * track.BeatsPerBar, track.Bpm, rate);
        }

        /// <summary>The bar that contains sample (exact on the rounded grid, not a float estimate).</summary>
        public static long BarIndexAt(long sample, MusicTrack track, long rate)
        {
            long b = (long)Math.Floor(sample * track.Bpm / (60.0 * rate * track.BeatsPerBar));
            // The estimate can be one bar off where rounding moved a bar line: walk to the exact one
            while (BarSample(b + 1, track, rate) <= sample)
            {
                b++;
            }
            while (b > 0 && BarSample(b, track, rate) > sample)
            {
                b--;
            }
            return b;
        }

        /// <summary>(loop start, loop end) in samples: the loop plays [start, end) forever after the intro.</summary>
        public static (long Start, long End) LoopPoints(MusicTrack track, long rate)
        {
            return (BarSample(track.LoopStartBar, track, rate), BarSample(track.Bars, track, rate));
        }

        public (long Start, long End) LoopPoints(string trackName)
        {
            return LoopPoints(Track(trackName), SampleRate);
        }

        /// <summary>Where in the track (samples from its start) playback is at now, when it started at since
        /// from entry.</summary>
        public static long Position(MusicTrack track, long rate, long since, long now, long entry = 0)
        {
            long p = now - since + entry;
            (long start, long end) = LoopPoints(track, rate);
            if (p >= end)
            {
                p = start + PyMod(p - start, end - start);
            }
            return p;
        }

        /// <summary>The first boundary of the given kind at or after track position p (0 &lt;= p &lt; loop end).</summary>
        public static long NextBoundary(MusicTrack track, long rate, long p, string quantize, long phraseBars = DEFAULT_PHRASE_BARS)
        {
            if (quantize == QUANTIZE_IMMEDIATE)
            {
                return p;
            }
            long end = LoopPoints(track, rate).End;
            if (quantize == QUANTIZE_LOOP_END)
            {
                return end;
            }
            long step;
            switch (quantize)
            {
                case QUANTIZE_BEAT: step = 1; break;
                case QUANTIZE_BAR: step = track.BeatsPerBar; break;
                case QUANTIZE_PHRASE: step = track.BeatsPerBar * phraseBars; break;
                default: throw new ArgumentException($"music: unknown quantize '{quantize}'");
            }
            if (step < 1)
            {
                throw new ArgumentException("music: a phrase must be 1 bar or more");   // the loop below would never end
            }
            // The beat at or after p, then up to the next multiple of step (counted from the track's first beat)
            long k = (long)Math.Floor(p * track.Bpm / (60.0 * rate));
            while (BeatSample(k, track.Bpm, rate) < p)
            {
                k++;
            }
            while (k % step != 0)                       // only zero / non-zero matters, so C#'s signed % is fine
            {
                k++;
            }
            return Math.Min(BeatSample(k, track.Bpm, rate), end);
        }

        // ---- Rules and plans --------------------------------------------------------------

        /// <summary>The transition rule: exact pair, then from "*", then to "*", then default_transition, then
        /// the built-in default (bar, no fade, no sync).</summary>
        public MusicRule RuleFor(string from, string to)
        {
            string[][] wants = { new[] { from, to }, new[] { ANY, to }, new[] { from, ANY } };
            foreach (string[] want in wants)
            {
                foreach (Dictionary<string, object> r in _transitions)
                {
                    // Python compares (r.get("from"), r.get("to")) == want: a missing key is None, never a match
                    if (Equals(Get(r, "from"), want[0]) && Equals(Get(r, "to"), want[1]))
                    {
                        return ParseRule(Merge(r), $"music: transition {from} -> {to}");
                    }
                }
            }
            return ParseRule(Merge(null), "music: default_transition");
        }

        /// <summary>When and how to change from track `from` (playing since sample `since` from offset `entry`) to
        /// `to`, asked at sample `now`. Throws KeyNotFoundException for an unknown track or stinger.</summary>
        public MusicPlan Plan(string from, long since, long entry, string to, long now)
        {
            long rate = SampleRate;
            MusicTrack a = Track(from), b = Track(to);
            MusicRule rule = RuleFor(from, to);
            long p = Position(a, rate, since, now, entry);
            long boundary = NextBoundary(a, rate, p, rule.Quantize, rule.PhraseBars);
            long switchAt = now + (boundary - p);
            long fade = (long)Math.Floor(rule.FadeMs * rate / 1000.0 + 0.5);
            var plan = new MusicPlan
            {
                SwitchAt = switchAt, FromStopAt = switchAt + fade, Fade = fade, ToOffset = 0, ToStartAt = switchAt,
                Stinger = rule.Stinger, StingerAt = null,
            };
            if (!string.IsNullOrEmpty(rule.Stinger))
            {
                if (!_stingers.TryGetValue(rule.Stinger, out MusicStinger st))
                {
                    throw new KeyNotFoundException($"music: unknown stinger '{rule.Stinger}'");
                }
                plan.StingerAt = switchAt;
                plan.ToStartAt = switchAt + BeatSample(st.Bars * b.BeatsPerBar, b.Bpm, rate);
            }
            else if (rule.Sync && a.Bpm == b.Bpm && a.BeatsPerBar == b.BeatsPerBar)
            {
                // Keep the beat: enter the target at the same place in its bar (bar boundaries are where they line up)
                plan.ToOffset = boundary - BarSample(BarIndexAt(boundary, a, rate), a, rate);
            }
            return plan;
        }

        public MusicTrack Track(string name)
        {
            if (name == null || !_tracks.TryGetValue(name, out MusicTrack t))
            {
                throw new KeyNotFoundException($"music: unknown track '{name}'");
            }
            return t;
        }

        public MusicStinger Stinger(string name)
        {
            if (name == null || !_stingers.TryGetValue(name, out MusicStinger s))
            {
                throw new KeyNotFoundException($"music: unknown stinger '{name}'");
            }
            return s;
        }

        // ---- Internals -------------------------------------------------------------------

        // {**DEFAULT_RULE, **default_transition, **rule}: later keys win, an explicit null included
        private Dictionary<string, object> Merge(Dictionary<string, object> rule)
        {
            var merged = new Dictionary<string, object>(DEFAULT_RULE);
            foreach (KeyValuePair<string, object> kv in _defaultTransition)
            {
                merged[kv.Key] = kv.Value;
            }
            if (rule != null)
            {
                foreach (KeyValuePair<string, object> kv in rule)
                {
                    merged[kv.Key] = kv.Value;
                }
            }
            return merged;
        }

        private static MusicRule ParseRule(Dictionary<string, object> r, string where)
        {
            var rule = new MusicRule();
            rule.Quantize = Get(r, "quantize") as string;
            if (Array.IndexOf(QUANTIZE, rule.Quantize) < 0)
            {
                throw new ArgumentException($"{where}: quantize must be one of {string.Join(", ", QUANTIZE)}");
            }
            object fade = Get(r, "fade_ms");
            if (fade != null && !Json.IsNumber(fade))
            {
                throw new ArgumentException($"{where}: fade_ms must be a number");
            }
            rule.FadeMs = fade == null ? 0.0 : Json.ToNumber(fade);
            rule.Sync = Truthy(Get(r, "sync"));
            object stinger = Get(r, "stinger");
            if (stinger != null && !(stinger is string))
            {
                throw new ArgumentException($"{where}: stinger must be a stinger name or null");
            }
            rule.Stinger = (string)stinger;
            if (r.ContainsKey("phrase_bars"))
            {
                rule.PhraseBars = RequireWhole(r, "phrase_bars", where);
                if (rule.PhraseBars < 1)
                {
                    throw new ArgumentException($"{where}: phrase_bars must be 1 or more");
                }
            }
            return rule;
        }

        private static MusicTrack ParseTrack(string name, object value)
        {
            string where = $"music: track {name}";
            if (!(value is Dictionary<string, object> t))
            {
                throw new ArgumentException($"{where}: must be an object");
            }
            object bpm = Get(t, "bpm");
            if (!Json.IsNumber(bpm) || !(Json.ToNumber(bpm) > 0))
            {
                throw new ArgumentException($"{where}: bpm must be a number above 0");
            }
            var track = new MusicTrack
            {
                Name = name,
                Bpm = Json.ToNumber(bpm),
                BeatsPerBar = t.ContainsKey("beats_per_bar") ? RequireWhole(t, "beats_per_bar", where) : DEFAULT_BEATS_PER_BAR,
                Bars = RequireWhole(t, "bars", where),
                LoopStartBar = t.ContainsKey("loop_start_bar") ? RequireWhole(t, "loop_start_bar", where) : 0,
            };
            if (track.BeatsPerBar < 1)
            {
                throw new ArgumentException($"{where}: beats_per_bar must be 1 or more");
            }
            if (track.Bars < 1 || track.LoopStartBar < 0 || track.LoopStartBar >= track.Bars)
            {
                throw new ArgumentException($"{where}: bars must be 1 or more and loop_start_bar 0..bars-1");
            }
            if (t.TryGetValue("stems", out object stems) && stems != null)
            {
                if (!(stems is Dictionary<string, object> stemMap))
                {
                    throw new ArgumentException($"{where}: stems must be an object of stem name -> file");
                }
                foreach (KeyValuePair<string, object> kv in stemMap)
                {
                    track.Stems[kv.Key] = kv.Value as string ?? throw new ArgumentException($"{where}: stem {kv.Key} must be a file path");
                }
            }
            return track;
        }

        private static MusicStinger ParseStinger(string name, object value)
        {
            string where = $"music: stinger {name}";
            if (!(value is Dictionary<string, object> s))
            {
                throw new ArgumentException($"{where}: must be an object");
            }
            object bars = Get(s, "bars");
            if (!Json.IsNumber(bars) || !(Json.ToNumber(bars) > 0))
            {
                throw new ArgumentException($"{where}: bars must be a number above 0");
            }
            return new MusicStinger { File = Get(s, "file") as string, Bars = Json.ToNumber(bars) };
        }

        private static object Get(Dictionary<string, object> obj, string key)
        {
            return obj != null && obj.TryGetValue(key, out object v) ? v : null;
        }

        // Python truthiness for a JSON value (sync: true, 1 and "yes" all count, like the reference's `if rule.get("sync")`)
        private static bool Truthy(object v)
        {
            switch (v)
            {
                case null: return false;
                case bool b: return b;
                case string s: return s.Length > 0;
                case List<object> l: return l.Count > 0;
                case Dictionary<string, object> d: return d.Count > 0;
            }
            return !Json.IsNumber(v) || Json.ToNumber(v) != 0.0;
        }

        // A whole number (JSON numbers arrive as double) that fits a long exactly
        private static long RequireWhole(Dictionary<string, object> obj, string key, string where)
        {
            object v = Get(obj, key);
            double d = Json.IsNumber(v) ? Json.ToNumber(v) : double.NaN;
            if (double.IsNaN(d) || double.IsInfinity(d) || d != Math.Floor(d) || Math.Abs(d) > 9e15)
            {
                throw new ArgumentException($"{where}: {key} must be a whole number");
            }
            return (long)d;
        }

        // Python's a % m for m > 0: never negative (C#'s % keeps the sign of a)
        private static long PyMod(long a, long m)
        {
            long r = a % m;
            return r < 0 ? r + m : r;
        }
    }
}

// {{FOOTER}}
