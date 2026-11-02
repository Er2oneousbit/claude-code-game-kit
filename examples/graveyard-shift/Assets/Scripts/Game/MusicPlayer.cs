// ---------------------------------------------------------------------------
// MusicPlayer.cs
// Purpose : Plays data/music.json through AudioSources on the DSP clock: each track's stems start together and
//           loop on the bar grid (an intro plays once), and a change of track happens on the sample the Core
//           MusicDirector plans (next beat, bar, phrase or loop end), with an optional fade and stinger.
// Usage   : add the component; set Music Json (data/music.json as a TextAsset), Clips, and optionally Events (an
//           AudioEventPlayer: the "music" bus's volume_db, ducking and slider then apply). From code:
//           music.Init(File.ReadAllText(musicPath), file => myClips[file]);
//           music.PlayTrack("explore");                 // or let Play Start Track start music.json's "start"
//           MusicPlan p = music.Request("combat");       // samples on the music clock (see Notes)
//           music.SetStemGain("explore", "drums", 0f);   // layers: a stem in or out (linear 0..1)
// Notes   : Thin glue: the grid and every decision live in Assets/Scripts/Core/MusicDirector.cs. The music clock is
//           AudioSettings.dspTime in samples at music.json's sample_rate; a plan's sample s is scheduled at dspTime
//           s / sample_rate with AudioSource.PlayScheduled / SetScheduledEndTime, which Unity starts and stops on
//           the exact output sample. A request is planned at now + Schedule Lead, so the switch is never already in
//           the past when it reaches the audio thread. Loops: each stem has a head source (the clip from the
//           entry point, scheduled to end at the loop end) and a loop source (a clip of just [loop start, loop end),
//           made once with GetData / SetData, looping natively) scheduled to begin on that same sample. So
//           GetData must work: import music stems as Decompress On Load (the default for short clips) with
//           Preload Audio Data on. Every stem clip must run at sample_rate (refused otherwise); Unity resamples to
//           the output rate, which only matters for sample accuracy when they differ (a warning says so).
//           A fade is a straight line in volume from switch_at to from_stop_at, applied per frame; the stop itself
//           is scheduled. Starting a source mid-clip sets timeSamples before PlayScheduled.
//           Compile-checked against Unity 6.6 (verify in the editor: Play mode behaviour was not run by the kit).
//
// Pseudocode:
//   PlayTrack(track, at): per stem: head(clip from entry, ends at loop end) + loop(loop clip, from loop end on)
//   Request(to): plan = director.Plan(current, since, entry, to, now + lead)
//                -> old track: fade from switch_at, scheduled stop at from_stop_at
//                -> stinger source at stinger_at -> new track's stems from to_offset at to_start_at
//   Update: volume = track fade x stem gain x music bus gain x Volume; drop tracks and stingers that ended
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using graveyard_shift.Core;

namespace graveyard_shift.Game
{
    public sealed class MusicPlayer : MonoBehaviour
    {
        // ---- Inspector -------------------------------------------------------------
        [SerializeField] private TextAsset _musicJson = null;            // data/music.json; or call Init
        [SerializeField] private AudioClip[] _clips = new AudioClip[0];  // every stem and stinger file
        [SerializeField] private AudioEventPlayer _events = null;        // optional: bus levels, ducking, slider
        [SerializeField] private string _bus = "music";                  // the events file's bus the music sits on
        [SerializeField] private bool _playStartTrack = true;            // start music.json's "start" track in Start()
        [SerializeField] private double _scheduleLeadSeconds = 0.05;     // how far ahead a change is planned
        [SerializeField, Range(0f, 1f)] private float _volume = 1f;

        // ---- State ---------------------------------------------------------------
        private sealed class Stem
        {
            public string Name;
            public AudioSource Head;             // plays the clip from the entry point once, up to the loop end
            public AudioSource Loop;             // plays [loop start, loop end) forever from there
            public float Gain = 1f;
        }

        private sealed class Playing
        {
            public string Name;
            public long Since;                   // music-clock sample it started on
            public long Entry;                   // where in the track it started
            public long LoopFrom;                // music-clock sample the loop sources take over
            public long FadeFrom = long.MaxValue;
            public long FadeLength;
            public long StopAt = long.MaxValue;
            public readonly List<Stem> Stems = new List<Stem>();
        }

        private sealed class OneShot
        {
            public AudioSource Source;
            public long EndsAt;
        }

        private readonly List<Playing> _leaving = new List<Playing>();   // fading out or waiting for their stop
        private readonly List<OneShot> _stingers = new List<OneShot>();
        private readonly Dictionary<string, AudioClip> _loopClips = new Dictionary<string, AudioClip>();
        private readonly Stack<AudioSource> _pool = new Stack<AudioSource>();
        private Func<string, AudioClip> _resolve;
        private Playing _current;

        public MusicDirector Director { get; private set; }
        public string Track => _current?.Name;
        public float Volume { get => _volume; set => _volume = Mathf.Clamp01(value); }

        /// <summary>The music clock: AudioSettings.dspTime in whole samples at music.json's sample_rate.</summary>
        public long NowSample => (long)Math.Floor(AudioSettings.dspTime * Director.SampleRate + 0.5);

        // ---- Setup -------------------------------------------------------------------

        private void Awake()
        {
            if (Director == null && _musicJson != null)
            {
                Init(_musicJson.text, ClipFromList);
            }
        }

        private void Start()
        {
            if (_playStartTrack && Director != null && Director.Start != null && _current == null)
            {
                PlayTrack(Director.Start);
            }
        }

        /// <summary>Builds the director from music.json's text and a lookup from a file path of music.json to its
        /// clip. Checks every stem now (clip present, at sample_rate, long enough for the loop), so a bad import
        /// fails at load, not at the first change.</summary>
        public void Init(string musicJson, Func<string, AudioClip> resolveClip)
        {
            _resolve = resolveClip ?? throw new ArgumentNullException(nameof(resolveClip));
            StopAll();
            Director = MusicDirector.FromJson(musicJson);
            foreach (MusicTrack t in Director.Tracks.Values)
            {
                long loopEnd = Director.LoopPoints(t.Name).End;
                foreach (KeyValuePair<string, string> stem in t.Stems)
                {
                    AudioClip clip = Clip(stem.Value, $"track {t.Name} stem {stem.Key}");
                    if (clip.samples < loopEnd)
                    {
                        throw new ArgumentException($"music: track {t.Name} stem {stem.Key}: {clip.samples} samples, " +
                                                    $"the loop needs {loopEnd} (make it with music.py loop)");
                    }
                }
            }
            if (AudioSettings.outputSampleRate != Director.SampleRate)
            {
                Debug.LogWarning($"[WARN][music] output runs at {AudioSettings.outputSampleRate} Hz, music.json at " +
                                 $"{Director.SampleRate} Hz: switches land within one output sample, not on it");
            }
        }

        // ---- Playing -------------------------------------------------------------------

        /// <summary>Starts a track Schedule Lead from now, stopping whatever plays (use Request for a planned change).</summary>
        public void PlayTrack(string name)
        {
            RequireInit();
            PlayTrack(name, NowSample + LeadSamples());
        }

        /// <summary>Starts a track at a music-clock sample, from its beginning, stopping whatever plays.</summary>
        public void PlayTrack(string name, long atSample)
        {
            RequireInit();
            StopAll();
            _current = Launch(name, atSample, 0);
        }

        /// <summary>Plans and schedules a change to `to`, planned at now + Schedule Lead; returns the plan (null when
        /// nothing played yet, so `to` simply starts, or when `to` is already the current track).</summary>
        public MusicPlan Request(string to)
        {
            RequireInit();
            return Request(to, NowSample + LeadSamples());
        }

        /// <summary>As Request(to), planned at a music-clock sample. A request while the previous change has not
        /// started yet is planned from the moment that track starts.</summary>
        public MusicPlan Request(string to, long nowSample)
        {
            RequireInit();
            Playing cur = _current;
            if (cur == null)
            {
                PlayTrack(to, nowSample);
                return null;
            }
            if (cur.Name == to)
            {
                return null;
            }
            long now = Math.Max(nowSample, cur.Since);
            MusicPlan p = Director.Plan(cur.Name, cur.Since, cur.Entry, to, now);
            Leave(cur, p.SwitchAt, p.Fade, p.FromStopAt);
            if (!string.IsNullOrEmpty(p.Stinger) && p.StingerAt.HasValue)
            {
                PlayStinger(p.Stinger, p.StingerAt.Value);
            }
            _current = Launch(to, p.ToStartAt, p.ToOffset);
            return p;
        }

        /// <summary>A stem's level (linear 0..1) on the current track; applied from this frame on.</summary>
        public void SetStemGain(string track, string stem, float value)
        {
            if (_current == null || _current.Name != track)
            {
                return;
            }
            Stem s = _current.Stems.Find(x => x.Name == stem);
            if (s == null)
            {
                throw new KeyNotFoundException($"music: track {track} has no stem {stem}");
            }
            s.Gain = Mathf.Clamp01(value);
        }

        /// <summary>Stops the music and every stinger now.</summary>
        public void StopAll()
        {
            if (_current != null)
            {
                Release(_current);
                _current = null;
            }
            foreach (Playing p in _leaving)
            {
                Release(p);
            }
            _leaving.Clear();
            foreach (OneShot s in _stingers)
            {
                Return(s.Source);
            }
            _stingers.Clear();
        }

        // ---- Per frame -----------------------------------------------------------------

        private void Update()
        {
            if (Director == null)
            {
                return;
            }
            long now = NowSample;
            float bus = (float)(_events != null ? _events.BusGain(_bus) : 1.0) * _volume;
            if (_current != null)
            {
                SetLevels(_current, bus, now);
            }
            for (int i = _leaving.Count - 1; i >= 0; i--)
            {
                Playing p = _leaving[i];
                if (now >= p.StopAt)
                {
                    Release(p);
                    _leaving.RemoveAt(i);
                    continue;
                }
                SetLevels(p, bus, now);
            }
            for (int i = _stingers.Count - 1; i >= 0; i--)
            {
                OneShot s = _stingers[i];
                if (now >= s.EndsAt && !s.Source.isPlaying)
                {
                    Return(s.Source);
                    _stingers.RemoveAt(i);
                    continue;
                }
                s.Source.volume = Mathf.Clamp01(bus);
            }
        }

        // ---- Internals -------------------------------------------------------------------

        // One head and one loop source per stem, both scheduled now on the DSP clock, so the stems stay locked
        private Playing Launch(string name, long at, long entry)
        {
            MusicTrack t = Director.Track(name);
            (long loopStart, long loopEnd) = Director.LoopPoints(name);
            if (entry >= loopEnd)
            {
                entry = MusicDirector.Position(t, Director.SampleRate, 0, entry);   // wrap into the loop
            }
            var playing = new Playing { Name = name, Since = at, Entry = entry, LoopFrom = at + (loopEnd - entry) };
            foreach (KeyValuePair<string, string> stem in t.Stems)
            {
                AudioClip clip = Clip(stem.Value, $"track {name} stem {stem.Key}");
                AudioSource head = Rent();
                head.clip = clip;
                head.loop = false;
                head.timeSamples = (int)entry;
                head.volume = 0f;                            // Update sets the level
                head.PlayScheduled(Dsp(at));
                head.SetScheduledEndTime(Dsp(playing.LoopFrom));
                AudioSource loop = Rent();
                loop.clip = LoopClip(stem.Value, clip, loopStart, loopEnd);
                loop.loop = true;
                loop.timeSamples = 0;
                loop.volume = 0f;
                loop.PlayScheduled(Dsp(playing.LoopFrom));
                playing.Stems.Add(new Stem { Name = stem.Key, Head = head, Loop = loop });
            }
            return playing;
        }

        // The old track fades over [switchAt, switchAt + fade) and stops on stopAt (scheduled, sample exact)
        private void Leave(Playing p, long switchAt, long fade, long stopAt)
        {
            p.FadeFrom = switchAt;
            p.FadeLength = fade;
            p.StopAt = stopAt;
            foreach (Stem s in p.Stems)
            {
                if (stopAt <= p.LoopFrom)
                {
                    s.Head.SetScheduledEndTime(Dsp(stopAt));
                    s.Loop.Stop();                           // never starts: cancels its PlayScheduled
                }
                else
                {
                    s.Loop.SetScheduledEndTime(Dsp(stopAt));
                }
            }
            _leaving.Add(p);
        }

        private void PlayStinger(string name, long at)
        {
            MusicStinger st = Director.Stinger(name);
            AudioClip clip = Clip(st.File, $"stinger {name}");
            AudioSource src = Rent();
            src.clip = clip;
            src.loop = false;
            src.timeSamples = 0;
            src.volume = 0f;
            src.PlayScheduled(Dsp(at));
            long length = (long)Math.Ceiling((double)clip.samples / clip.frequency * Director.SampleRate);
            _stingers.Add(new OneShot { Source = src, EndsAt = at + length });
        }

        private static void SetLevels(Playing p, float bus, long now)
        {
            float fade = 1f;
            if (now >= p.FadeFrom)
            {
                fade = p.FadeLength <= 0 ? 0f : Mathf.Clamp01(1f - (float)(now - p.FadeFrom) / p.FadeLength);
            }
            foreach (Stem s in p.Stems)
            {
                float v = Mathf.Clamp01(fade * s.Gain * bus);
                s.Head.volume = v;
                s.Loop.volume = v;
            }
        }

        private void Release(Playing p)
        {
            foreach (Stem s in p.Stems)
            {
                Return(s.Head);
                Return(s.Loop);
            }
            p.Stems.Clear();
        }

        // The loop region as its own clip, so AudioSource.loop wraps on the bar grid. Reuses the clip itself
        // when it is exactly the loop (no intro, nothing past the end), else copies [start, end) once per file.
        private AudioClip LoopClip(string file, AudioClip clip, long start, long end)
        {
            if (start == 0 && clip.samples == end)
            {
                return clip;
            }
            string key = $"{file}|{start}|{end}";
            if (_loopClips.TryGetValue(key, out AudioClip made) && made != null)
            {
                return made;
            }
            if (clip.loadState != AudioDataLoadState.Loaded && !clip.LoadAudioData())
            {
                throw new InvalidOperationException($"music: {file}: the audio data could not be loaded");
            }
            int frames = checked((int)(end - start));
            var data = new float[checked(frames * clip.channels)];
            if (!clip.GetData(data, checked((int)start)))
            {
                throw new InvalidOperationException($"music: {file}: GetData failed (import it as Decompress On Load)");
            }
            made = AudioClip.Create($"{clip.name}_loop", frames, clip.channels, clip.frequency, false);
            made.SetData(data, 0);
            _loopClips[key] = made;
            return made;
        }

        private AudioClip Clip(string file, string where)
        {
            AudioClip clip = file != null ? _resolve(file) : null;
            if (clip == null)
            {
                throw new ArgumentException($"music: {where}: no clip for '{file}' (add it to Clips)");
            }
            if (clip.frequency != Director.SampleRate)
            {
                throw new ArgumentException($"music: {where}: {file} runs at {clip.frequency} Hz, music.json says " +
                                            $"{Director.SampleRate} Hz (resample the file or fix sample_rate)");
            }
            return clip;
        }

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
            var go = new GameObject("music_source");
            go.transform.SetParent(transform, false);
            var src = go.AddComponent<AudioSource>();
            src.playOnAwake = false;
            src.spatialBlend = 0f;
            return src;
        }

        private void Return(AudioSource src)
        {
            if (src == null)
            {
                return;
            }
            src.Stop();
            src.clip = null;
            _pool.Push(src);
        }

        private double Dsp(long sample)
        {
            return (double)sample / Director.SampleRate;
        }

        private long LeadSamples()
        {
            return (long)Math.Ceiling(Math.Max(0.0, _scheduleLeadSeconds) * Director.SampleRate);
        }

        private void RequireInit()
        {
            if (Director == null)
            {
                throw new InvalidOperationException("music: call Init (or set Music Json) first");
            }
        }

        private void OnDestroy()
        {
            foreach (AudioClip c in _loopClips.Values)
            {
                if (c != null)
                {
                    Destroy(c);
                }
            }
            _loopClips.Clear();
        }
    }
}
