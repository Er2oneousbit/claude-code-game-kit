// ---------------------------------------------------------------------------
// AudioEventPlayer.cs
// Purpose : Plays what the Core AudioDirector decides through AudioSources: one pooled source per voice at the
//           chosen file, pitch and volume, stolen voices stopped, and every voice's level from its bus chain
//           (volume_db + ducking, times the player's volume slider, for the bus and each parent up to master).
// Usage   : add the component; set Events Json (data/audio_events.json as a TextAsset) and Clips, or from code:
//           player.Init(File.ReadAllText(eventsPath), file => myClips[file]);
//           player.Play("step_stone");                   // now on the DSP clock, or player.Play(name, atMs)
//           player.ApplySettings(settings);              // GameSettings: the audio sliders (AudioAccess.UserBusGains)
//           player.SetBusVolume("music", -6);            // a bus's own level in dB (normally from the events file)
//           player.BusGain("music")                      // MusicPlayer.cs multiplies its stems by this
// Notes   : Thin glue: decisions, randomness and timing rules live in Assets/Scripts/Core/AudioDirector.cs, the
//           slider rule in AudioAccess.cs. Times are milliseconds on AudioSettings.dspTime (the audio thread's
//           clock), so PlayScheduled and SetScheduledEndTime land on the sample. The director needs calls in time
//           order: a Play scheduled ahead moves the director's clock there, and Update evaluates ducking at that
//           time until the real clock catches up. Levels update once per frame (AudioSource.volume is not a
//           scheduled parameter), so a duck ramp moves in frame steps. AudioSource.volume stops at 1: a positive
//           volume_db or gain_db cannot boost here (route through an AudioMixer for that). Clips are matched to
//           the events file's paths by file name without extension (assets/audio/sfx/step_0.wav -> step_0).
//           lengths_ms comes from each clip (samples / frequency). Run in Play mode on Unity 6000.6.6f1 by
//           Assets/Tests/PlayMode/AudioPlayModeTests.cs (takes, pitch and volume, ducking, the sliders, read
//           back from the AudioSources); how it sounds is not checked (verify by ear).
//
// Pseudocode:
//   Init: buses {parent, volume_db} -> events with lengths_ms from the clips -> AudioDirector
//   Play(name, at): d = director.Play -> stolen? stop that source at `at` -> pooled source(clip, pitch)
//                   -> PlayScheduled(at) -> remember voice id -> source
//   Update: duck = director.Duck(now); finished voices back to the pool;
//           each voice: volume = gain_db as linear x product over its bus chain of (volume_db + duck) x slider
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using graveyard_shift.Core;

namespace graveyard_shift.Game
{
    public sealed class AudioEventPlayer : MonoBehaviour
    {
        // ---- Inspector -------------------------------------------------------------
        [SerializeField] private TextAsset _eventsJson = null;           // data/audio_events.json; or call Init
        [SerializeField] private AudioClip[] _clips = new AudioClip[0];  // every file the events name

        // ---- State ---------------------------------------------------------------
        private sealed class Bus
        {
            public string Parent;                // null for master
            public double VolumeDb;
        }

        private sealed class Voice
        {
            public AudioSource Source;
            public string Bus;
            public double Gain;                  // the director's gain_db as a linear factor
            public double EndsMs;                // when it finishes (or was stopped), on the DSP clock
        }

        private readonly Dictionary<string, Bus> _buses = new Dictionary<string, Bus>();
        private Dictionary<string, object> _busesRaw = new Dictionary<string, object>();   // for AudioAccess
        private Dictionary<string, double> _user = new Dictionary<string, double>();       // slider gains per bus
        private Dictionary<string, double> _duck = new Dictionary<string, double>();       // dB per ducked bus
        private readonly Dictionary<int, Voice> _voices = new Dictionary<int, Voice>();
        private readonly Stack<AudioSource> _pool = new Stack<AudioSource>();
        private readonly List<int> _done = new List<int>();
        private Func<string, AudioClip> _resolve;
        private double _clockMs;                 // the latest time handed to the director

        public AudioDirector Director { get; private set; }

        /// <summary>The DSP clock in milliseconds (what Play and Update use when no time is given).</summary>
        public static double NowMs => AudioSettings.dspTime * 1000.0;

        public static double DbToGain(double db)
        {
            return Math.Pow(10.0, db / 20.0);
        }

        // ---- Setup -------------------------------------------------------------------

        private void Awake()
        {
            if (Director == null && _eventsJson != null)
            {
                Init(_eventsJson.text, ClipFromList);
            }
        }

        /// <summary>Builds the director from the events file's text ({ seed?, buses, events, ducking? }) and a
        /// lookup from a file path of the events file to its clip. Throws ArgumentException on a malformed file or
        /// a file without a clip.</summary>
        public void Init(string eventsJson, Func<string, AudioClip> resolveClip)
        {
            _resolve = resolveClip ?? throw new ArgumentNullException(nameof(resolveClip));
            if (!(Json.Parse(eventsJson) is Dictionary<string, object> root))
            {
                throw new ArgumentException("audio events: the file must be a JSON object");
            }
            ReadBuses(root);
            // The director wants lengths_ms per file: measure them from the clips (a copy, the text stays as is)
            if (!(root.TryGetValue("events", out object evObj) && evObj is Dictionary<string, object> events))
            {
                throw new ArgumentException("audio events: \"events\" must be an object of event id -> event");
            }
            var withLengths = (Dictionary<string, object>)Json.DeepCopy(events);
            foreach (KeyValuePair<string, object> entry in withLengths)
            {
                if (!(entry.Value is Dictionary<string, object> ev && ev.TryGetValue("files", out object f)
                      && f is List<object> files))
                {
                    continue;                                   // the director names the problem
                }
                var lengths = new List<object>(files.Count);
                foreach (object file in files)
                {
                    AudioClip clip = Clip(file as string, entry.Key);
                    lengths.Add((double)clip.samples / clip.frequency * 1000.0);
                }
                ev["lengths_ms"] = lengths;
            }
            var parameters = new Dictionary<string, object> { { "events", withLengths } };
            if (root.TryGetValue("seed", out object seed))
            {
                parameters["seed"] = seed;
            }
            if (root.TryGetValue("ducking", out object ducking))
            {
                parameters["ducking"] = ducking;
            }
            StopAll();
            Director = new AudioDirector(parameters);
            _clockMs = 0.0;
            _duck = new Dictionary<string, double>();
            _user = AudioAccess.UserBusGains(_busesRaw, new Dictionary<string, object>());   // every slider at 1
        }

        private void ReadBuses(Dictionary<string, object> root)
        {
            _buses.Clear();
            _busesRaw = root.TryGetValue("buses", out object b) && b is Dictionary<string, object> buses
                ? buses
                : new Dictionary<string, object> { { AudioAccess.MASTER, new Dictionary<string, object>() } };
            foreach (KeyValuePair<string, object> entry in _busesRaw)
            {
                var def = entry.Value as Dictionary<string, object>;
                object parent = null, volume = null;
                def?.TryGetValue("parent", out parent);
                def?.TryGetValue("volume_db", out volume);
                _buses[entry.Key] = new Bus
                {
                    Parent = parent as string ?? (entry.Key == AudioAccess.MASTER ? null : AudioAccess.MASTER),
                    VolumeDb = Json.IsNumber(volume) ? Json.ToNumber(volume) : 0.0,
                };
            }
        }

        // ---- Playing -------------------------------------------------------------------

        public AudioPlayResult Play(string eventName)
        {
            return Play(eventName, NowMs);
        }

        /// <summary>Plays an event at atMs on the DSP clock (now or ahead). Returns the director's decision; only
        /// a "played" one starts a source. A time before the last call is moved up to it (the director's rule).</summary>
        public AudioPlayResult Play(string eventName, double atMs)
        {
            RequireInit();
            atMs = Math.Max(atMs, _clockMs);
            _clockMs = atMs;
            AudioPlayResult d = Director.Play(eventName, atMs);
            if (!d.Played)
            {
                return d;
            }
            if (d.Stolen.HasValue && _voices.TryGetValue(d.Stolen.Value, out Voice victim))
            {
                StopVoiceAt(victim, atMs);
            }
            AudioSource src = Rent();
            src.clip = Clip(Director.FileOf(eventName, d.Variant), eventName);
            src.pitch = (float)d.PitchRatio;
            var voice = new Voice { Source = src, Bus = Director.BusOf(eventName), Gain = DbToGain(d.GainDb), EndsMs = d.EndsMs };
            src.volume = Level(voice);
            src.PlayScheduled(atMs / 1000.0);               // a time already passed plays at once
            _voices[d.Voice] = voice;
            return d;
        }

        /// <summary>The settings file's values (GameSettings): reads its "audio" section's sliders.</summary>
        public void ApplySettings(Dictionary<string, object> settings)
        {
            ApplySliders(settings != null && settings.TryGetValue("audio", out object a) ? a as Dictionary<string, object> : null);
        }

        /// <summary>The volume sliders (linear 0..1: master, music, sfx, ui, voice); takes effect this frame.</summary>
        public void ApplySliders(IDictionary<string, object> sliders)
        {
            _user = AudioAccess.UserBusGains(_busesRaw, sliders ?? new Dictionary<string, object>());
        }

        public void SetBusVolume(string bus, double db)
        {
            if (!_buses.TryGetValue(bus, out Bus b))
            {
                throw new KeyNotFoundException($"audio player: unknown bus '{bus}'");
            }
            b.VolumeDb = db;
        }

        /// <summary>A bus's linear level right now: (volume_db + duck) x slider for the bus and every parent up to
        /// master. A bus the events file does not list counts as 0 dB under master.</summary>
        public double BusGain(string bus)
        {
            double gain = 1.0;
            string b = bus;
            // At most one step per bus (plus the bus itself), so a parent cycle cannot hang
            for (int n = 0; b != null && n <= _buses.Count; n++)
            {
                _buses.TryGetValue(b, out Bus def);
                double db = (def?.VolumeDb ?? 0.0) + (_duck.TryGetValue(b, out double duck) ? duck : 0.0);
                gain *= DbToGain(db) * (_user.TryGetValue(b, out double user) ? user : 1.0);
                b = def != null ? def.Parent : (b == AudioAccess.MASTER ? null : AudioAccess.MASTER);
            }
            return gain;
        }

        // ---- Per frame -----------------------------------------------------------------

        private void Update()
        {
            if (Director != null)
            {
                Tick(NowMs);
            }
        }

        /// <summary>Ducking, finished voices and levels at nowMs (Update calls it with the DSP clock).</summary>
        public void Tick(double nowMs)
        {
            RequireInit();
            double t = Math.Max(nowMs, _clockMs);
            _clockMs = t;
            _duck = Director.Duck(t);
            _done.Clear();
            foreach (KeyValuePair<int, Voice> kv in _voices)
            {
                Voice v = kv.Value;
                if (v.EndsMs <= nowMs && !v.Source.isPlaying)
                {
                    _done.Add(kv.Key);
                    continue;
                }
                v.Source.volume = Level(v);
            }
            foreach (int id in _done)
            {
                Return(_voices[id].Source);
                _voices.Remove(id);
            }
        }

        /// <summary>Stops every voice now (a scene change, a pause menu that silences the world).</summary>
        public void StopAll()
        {
            foreach (Voice v in _voices.Values)
            {
                v.Source.Stop();
                Return(v.Source);
            }
            _voices.Clear();
        }

        // ---- Internals -------------------------------------------------------------------

        private float Level(Voice v)
        {
            return Mathf.Clamp01((float)(v.Gain * BusGain(v.Bus)));
        }

        // A stolen voice stops when the new one starts: at once when that is now, else on the DSP clock
        private static void StopVoiceAt(Voice v, double atMs)
        {
            if (atMs <= NowMs)
            {
                v.Source.Stop();
            }
            else
            {
                v.Source.SetScheduledEndTime(atMs / 1000.0);
            }
            v.EndsMs = Math.Min(v.EndsMs, atMs);
        }

        private AudioSource Rent()
        {
            while (_pool.Count > 0)
            {
                AudioSource pooled = _pool.Pop();
                if (pooled != null)
                {
                    return pooled;
                }
            }
            var go = new GameObject("voice");
            go.transform.SetParent(transform, false);
            var src = go.AddComponent<AudioSource>();
            src.playOnAwake = false;
            src.loop = false;
            src.spatialBlend = 0f;                          // 2D; set it on the source for positional sound
            return src;
        }

        private void Return(AudioSource src)
        {
            if (src == null)
            {
                return;
            }
            src.clip = null;
            _pool.Push(src);
        }

        private AudioClip Clip(string file, string eventName)
        {
            AudioClip clip = file != null ? _resolve(file) : null;
            if (clip == null)
            {
                throw new ArgumentException($"audio player: event {eventName}: no clip for '{file}' (add it to Clips)");
            }
            return clip;
        }

        // The inspector's list: a path from the events file matches a clip of the same file name without extension
        private AudioClip ClipFromList(string file)
        {
            string want = Path.GetFileNameWithoutExtension(file);
            foreach (AudioClip c in _clips)
            {
                if (c != null && c.name == want)
                {
                    return c;
                }
            }
            return null;
        }

        private void RequireInit()
        {
            if (Director == null)
            {
                throw new InvalidOperationException("audio player: call Init (or set Events Json) first");
            }
        }
    }
}
