// ---------------------------------------------------------------------------
// AudioPlayModeTests.cs
// Purpose : AudioEventPlayer in Play mode with real AudioSources and generated clips: takes never repeat back to
//           back and pitch and volume stay in their ranges, a ducking rule dips the music bus and brings it back
//           on the planned times, and each volume slider changes only its own buses (ambience under sfx is not
//           turned down twice), all read from the sources' pitch and volume.
// Usage   : python tools/dev.py test --mode PlayMode --filter Audio
// Notes   : No scene needed: each test builds its player in the test runner's scene and destroys it. Times are
//           handed to Play and Tick explicitly (milliseconds a second ahead of the DSP clock), so the checks
//           do not depend on frame timing or on an audio device; Update still runs every frame in between.
//           AudioEventPlayer lives in Assembly-CSharp, which a test assembly cannot reference, so it is reached
//           by reflection (its type name, public methods only). The decisions themselves are golden-tested in
//           EditMode (AudioVectorTests, AccessVectorTests); this checks the glue that applies them.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using graveyard_shift.Core;

namespace graveyard_shift.Tests
{
    public class AudioPlayModeTests
    {
        private const string PLAYER_TYPE = "graveyard_shift.Game.AudioEventPlayer";
        private const int RATE = 44100;
        private const double AHEAD_MS = 1000.0;          // every planned time starts this far past the DSP clock
        private const float TOL = 1e-4f;

        private GameObject _go;
        private Component _player;
        private readonly Dictionary<string, AudioClip> _clips = new Dictionary<string, AudioClip>();

        [TearDown]
        public void TearDown()
        {
            if (_go != null)
            {
                UnityEngine.Object.Destroy(_go);
            }
            foreach (AudioClip c in _clips.Values)
            {
                UnityEngine.Object.Destroy(c);
            }
            _clips.Clear();
        }

        // ---- Tests ---------------------------------------------------------------------

        [UnityTest]
        public IEnumerator Audio_TakesNeverRepeatAndPitchAndVolumeStayInRange()
        {
            Make(@"{ ""seed"": 3, ""buses"": { ""master"": {}, ""sfx"": {} }, ""events"": {
                ""step"": { ""bus"": ""sfx"", ""files"": [""step_0.wav"", ""step_1.wav"", ""step_2.wav"", ""step_3.wav""],
                            ""pick"": ""random_no_repeat"", ""pitch_semitones"": [-2, 2], ""volume_db"": [-6, 0],
                            ""max_voices"": 64 } } }", "step_0", "step_1", "step_2", "step_3");
            double t0 = Now() + AHEAD_MS;
            string last = null;
            var seen = new HashSet<string>();
            for (int i = 0; i < 24; i++)
            {
                var d = (AudioPlayResult)Call("Play", "step", t0 + 250.0 * i);
                Assert.IsTrue(d.Played, $"play {i}: {d.Result}");
                AudioSource src = NewestSource();
                Assert.AreEqual("step_" + d.Variant, src.clip.name, $"play {i}: the source plays the chosen take");
                Assert.AreNotEqual(last, src.clip.name, $"play {i}: the same take twice in a row");
                last = src.clip.name;
                seen.Add(last);
                Assert.AreEqual((float)d.PitchRatio, src.pitch, TOL, $"play {i}: pitch");
                Assert.That(src.pitch, Is.InRange(Mathf.Pow(2f, -2f / 12f) - TOL, Mathf.Pow(2f, 2f / 12f) + TOL));
                Assert.AreEqual((float)Math.Pow(10.0, d.GainDb / 20.0), src.volume, TOL, $"play {i}: volume");
                Assert.That(src.volume, Is.InRange(Mathf.Pow(10f, -6f / 20f) - TOL, 1f + TOL));
                yield return null;                       // Update runs between plays, as in a game
            }
            Assert.AreEqual(4, seen.Count, "every take is used");
            Debug.Log($"[test] audio takes: 24 plays, {seen.Count} takes, none twice in a row");
        }

        [UnityTest]
        public IEnumerator Audio_DuckingDipsTheMusicBusAndRecovers()
        {
            Make(@"{ ""buses"": { ""master"": {}, ""music"": {}, ""dialogue"": {} }, ""events"": {
                ""theme"": { ""bus"": ""music"", ""files"": [""theme.wav""] },
                ""line"": { ""bus"": ""dialogue"", ""files"": [""line.wav""] } },
                ""ducking"": [ { ""trigger"": ""dialogue"", ""targets"": [""music""], ""depth_db"": -8,
                                 ""attack_ms"": 80, ""release_ms"": 400 } ] }", ("theme", 10.0), ("line", 2.0));
            double t0 = Now() + AHEAD_MS;
            Call("Play", "theme", t0);
            AudioSource theme = NewestSource();
            Call("Play", "line", t0 + 1000.0);
            AudioSource line = NewestSource();
            // (time after t0, music's duck in dB): the golden ducking case, attack 80 ms, hold, release 400 ms
            var plan = new[] { (1000.0, 0.0), (1040.0, -4.0), (1080.0, -8.0), (2000.0, -8.0), (3000.0, -8.0),
                               (3200.0, -4.0), (3400.0, 0.0), (3600.0, 0.0) };
            foreach ((double at, double duckDb) in plan)
            {
                Call("Tick", t0 + at);
                yield return null;                       // Update's own Tick must not move the level
                float want = (float)Math.Pow(10.0, duckDb / 20.0);
                Assert.AreEqual(want, theme.volume, TOL, $"music at +{at} ms");
                Assert.AreEqual(want, (float)(double)Call("BusGain", "music"), TOL, $"BusGain(music) at +{at} ms");
                if (at < 3000.0)                         // the line ends at +3000 ms and its source goes back
                {
                    Assert.AreEqual(1f, line.volume, TOL, $"the dialogue itself is not ducked at +{at} ms");
                }
            }
            Debug.Log("[test] audio ducking: music -4 / -8 / -4 / 0 dB on the planned times");
        }

        [UnityTest]
        public IEnumerator Audio_EachSliderTurnsOnlyItsOwnBuses()
        {
            Make(@"{ ""buses"": { ""master"": {}, ""music"": {}, ""sfx"": {}, ""ambience"": { ""parent"": ""sfx"" },
                                ""ui"": {}, ""dialogue"": {} }, ""events"": {
                ""m"": { ""bus"": ""music"", ""files"": [""tone.wav""] }, ""s"": { ""bus"": ""sfx"", ""files"": [""tone.wav""] },
                ""a"": { ""bus"": ""ambience"", ""files"": [""tone.wav""] }, ""u"": { ""bus"": ""ui"", ""files"": [""tone.wav""] },
                ""d"": { ""bus"": ""dialogue"", ""files"": [""tone.wav""] } } }", ("tone", 10.0));
            double t0 = Now() + AHEAD_MS;
            var src = new Dictionary<string, AudioSource>();
            foreach (string ev in new[] { "m", "s", "a", "u", "d" })
            {
                Call("Play", ev, t0);
                src[ev] = NewestSource();
            }
            // slider values -> the volume each event's source must have (bus m=music, s=sfx, a=ambience under sfx, ...)
            var steps = new (Dictionary<string, object> sliders, Dictionary<string, float> want)[]
            {
                (Sliders(), Want(1, 1, 1, 1, 1)),
                (Sliders(("music", 0.5)), Want(0.5f, 1, 1, 1, 1)),
                (Sliders(("sfx", 0.25)), Want(1, 0.25f, 0.25f, 1, 1)),           // ambience follows sfx once
                (Sliders(("ui", 0.2), ("voice", 0.4)), Want(1, 1, 1, 0.2f, 0.4f)),
                (Sliders(("master", 0.5), ("sfx", 0.5)), Want(0.5f, 0.25f, 0.25f, 0.5f, 0.5f)),
            };
            int n = 0;
            foreach ((Dictionary<string, object> sliders, Dictionary<string, float> want) in steps)
            {
                Call("ApplySliders", sliders);
                Call("Tick", t0 + 100.0 * ++n);
                yield return null;
                foreach (KeyValuePair<string, float> w in want)
                {
                    Assert.AreEqual(w.Value, src[w.Key].volume, TOL, $"step {n}: event {w.Key}'s volume");
                }
            }
            Debug.Log("[test] audio sliders: each slider moved only its buses; ambience under sfx counted once");
        }

        // ---- Helpers -------------------------------------------------------------------

        private static double Now()
        {
            return AudioSettings.dspTime * 1000.0;
        }

        private static Dictionary<string, object> Sliders(params (string name, double value)[] set)
        {
            var d = new Dictionary<string, object>();
            foreach ((string name, double value) in set)
            {
                d[name] = value;
            }
            return d;
        }

        private static Dictionary<string, float> Want(float m, float s, float a, float u, float d)
        {
            return new Dictionary<string, float> { { "m", m }, { "s", s }, { "a", a }, { "u", u }, { "d", d } };
        }

        private void Make(string eventsJson, params string[] names)
        {
            var spec = new (string, double)[names.Length];
            for (int i = 0; i < names.Length; i++)
            {
                spec[i] = (names[i], 0.2 + 0.01 * i);
            }
            Make(eventsJson, spec);
        }

        // A player on a fresh object, its clips generated: a quiet sine per name, of the given seconds
        private void Make(string eventsJson, params (string name, double seconds)[] clips)
        {
            Type type = FindType(PLAYER_TYPE);
            Assert.IsNotNull(type, $"{PLAYER_TYPE} not found (Assets/Scripts/Game/AudioEventPlayer.cs)");
            _go = new GameObject("audio player under test");
            _player = _go.AddComponent(type);
            foreach ((string name, double seconds) in clips)
            {
                int frames = (int)(seconds * RATE);
                var data = new float[frames];
                for (int i = 0; i < frames; i++)
                {
                    data[i] = 0.1f * Mathf.Sin(2f * Mathf.PI * 440f * i / RATE);
                }
                AudioClip clip = AudioClip.Create(name, frames, 1, RATE, false);
                clip.SetData(data, 0);
                _clips[name] = clip;
            }
            Func<string, AudioClip> resolve = file =>
                _clips.TryGetValue(System.IO.Path.GetFileNameWithoutExtension(file), out AudioClip c) ? c : null;
            Call("Init", eventsJson, resolve);
        }

        // The source the last Play started: plays here never end before the next one, so it is a new child
        private AudioSource NewestSource()
        {
            Transform t = _go.transform;
            Assert.Greater(t.childCount, 0, "no voice source was created");
            return t.GetChild(t.childCount - 1).GetComponent<AudioSource>();
        }

        private object Call(string method, params object[] args)
        {
            var types = new Type[args.Length];
            for (int i = 0; i < args.Length; i++)
            {
                types[i] = args[i].GetType();
            }
            MethodInfo m = _player.GetType().GetMethod(method, BindingFlags.Public | BindingFlags.Instance, null, types, null);
            Assert.IsNotNull(m, $"AudioEventPlayer.{method} with these argument types not found");
            try
            {
                return m.Invoke(_player, args);
            }
            catch (TargetInvocationException e)
            {
                throw e.InnerException ?? e;
            }
        }

        private static Type FindType(string fullName)
        {
            foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type t = asm.GetType(fullName);
                if (t != null)
                {
                    return t;
                }
            }
            return null;
        }
    }
}
