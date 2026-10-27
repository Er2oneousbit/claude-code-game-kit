// ---------------------------------------------------------------------------
// EndSequence.cs
// Purpose : How a night ends. Dawn (the loss): the night's sounds fade, birds sing, the yard warms to sunrise,
//           then the screen fades to the end card and the loss sting plays. Escape (the win): a moment on the
//           open gate, the night fades out, then the end card and the win music.
// Usage   : var end = gameObject.AddComponent<EndSequence>();
//           end.Begin(dawn, setup.dawnChorus, moon, cam, endClip, narration, volume, worldAudio);   // Hud reads Fade, CardVisible
// Notes   : The timeline is a pure function of time (At), so tests check it without playing a night. The night's
//           sounds are every AudioSource alive when the sequence starts; the end music and the birds are added
//           after, so they never fade with them. A missing clip is skipped (the Suno files may not be in yet).
//
// Pseudocode (each frame, t = seconds since the night ended):
//   night sounds: volume = start volume x (1 - t / LayerFade)
//   dawn only: blend moon, ambient, fog and sky toward sunrise over DawnShow
//   after the lead (DawnShow or EscapeHold): darken the screen over ScreenFade, then show the card + play the music
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class EndSequence : MonoBehaviour
    {
        public const float DawnShow = 3.5f;      // s of sunrise before the screen fades (dawn only)
        public const float EscapeHold = 0.8f;    // s on the open gate before the fade (escape)
        public const float LayerFade = 2.0f;     // s for the night's sounds to fade out
        public const float ScreenFade = 1.2f;    // s to darken the screen
        public const float CardDim = 0.85f;      // how dark the screen gets behind the end card
        private const float DawnVolume = 0.8f;
        private const float EndMusicVolume = 0.7f;
        private const float NarrationVolume = 0.9f;
        private const float DuckLevel = 0.4f;          // music level under the narrator's words
        private const float DuckRelease = 1.0f;        // s to bring the music back up after the words
        private static readonly Color DawnAmbient = new Color(0.55f, 0.45f, 0.45f);
        private static readonly Color DawnFog = new Color(0.78f, 0.58f, 0.48f);
        private const float DawnFogDensity = 0.02f;
        private static readonly Color SunColor = new Color(1.0f, 0.78f, 0.55f);
        private const float SunIntensity = 1.0f;
        private static readonly Color DawnSky = new Color(0.9f, 0.65f, 0.5f);

        public struct Frame
        {
            public float Dawn;     // 0..1 how far the sunrise has come
            public float Fade;     // 0..CardDim screen darkness
            public bool Card;      // the end card (and its music) is up
        }

        public float Fade { get; private set; }
        public bool CardVisible { get; private set; }
        public bool IsDawn { get; private set; }

        private float _t;
        private bool _musicStarted;
        private float _scale;
        private AudioClip _endClip;
        private Light _moon;
        private Camera _cam;
        private readonly List<AudioSource> _layers = new List<AudioSource>();
        private readonly List<float> _layerStart = new List<float>();
        private Color _ambient0, _fog0, _moon0, _sky0;
        private float _fogDensity0, _moonIntensity0;
        private AudioSource _out;
        private AudioSource _voice;
        private AudioClip _narration;
        private float _duckUntil;

        public static Frame At(bool dawn, float t)
        {
            float lead = dawn ? DawnShow : EscapeHold;
            float fade = (t - lead) / ScreenFade;   // 0..1 through the screen fade
            return new Frame
            {
                Dawn = dawn ? Mathf.Clamp01(t / DawnShow) : 0f,
                Fade = Mathf.Clamp01(fade) * CardDim,
                Card = fade >= 1f - 1e-4f,   // tolerant: a float sum may land a hair under the exact end
            };
        }

        public void Begin(bool dawn, AudioClip dawnChorus, Light moon, Camera cam, AudioClip endClip, AudioClip narration,
            float volumeScale, GraveyardAudio world)
        {
            _narration = narration;
            IsDawn = dawn;
            _endClip = endClip;
            _scale = volumeScale;
            _moon = moon;
            _cam = cam;
            if (world != null) world.Silence();
            // every sound playing now belongs to the night and fades out
            foreach (var src in FindObjectsByType<AudioSource>(FindObjectsSortMode.None))
            {
                _layers.Add(src);
                _layerStart.Add(src.volume);
            }
            _ambient0 = RenderSettings.ambientLight;
            _fog0 = RenderSettings.fogColor;
            _fogDensity0 = RenderSettings.fogDensity;
            if (_moon != null) { _moon0 = _moon.color; _moonIntensity0 = _moon.intensity; }
            if (_cam != null) _sky0 = _cam.backgroundColor;
            _out = gameObject.AddComponent<AudioSource>();   // added after the capture: never faded
            _voice = gameObject.AddComponent<AudioSource>();
            if (dawn && dawnChorus != null) _out.PlayOneShot(dawnChorus, DawnVolume * _scale);
        }

        private void Update()
        {
            _t += Time.deltaTime;
            var f = At(IsDawn, _t);
            Fade = f.Fade;
            CardVisible = f.Card;

            float keep = 1f - Mathf.Clamp01(_t / LayerFade);
            for (int i = 0; i < _layers.Count; i++)
                if (_layers[i] != null) _layers[i].volume = _layerStart[i] * keep;

            if (IsDawn)
            {
                float k = Mathf.SmoothStep(0f, 1f, f.Dawn);
                RenderSettings.ambientLight = Color.Lerp(_ambient0, DawnAmbient, k);
                RenderSettings.fogColor = Color.Lerp(_fog0, DawnFog, k);
                RenderSettings.fogDensity = Mathf.Lerp(_fogDensity0, DawnFogDensity, k);
                if (_moon != null)
                {
                    _moon.color = Color.Lerp(_moon0, SunColor, k);
                    _moon.intensity = Mathf.Lerp(_moonIntensity0, SunIntensity, k);
                }
                if (_cam != null) _cam.backgroundColor = Color.Lerp(_sky0, DawnSky, k);
            }

            if (f.Card && !_musicStarted)
            {
                _musicStarted = true;
                if (_narration != null)   // the narrator closes the night; the music sits under the words
                {
                    _voice.PlayOneShot(_narration, NarrationVolume * _scale);
                    _duckUntil = _t + _narration.length + DuckRelease;
                }
                if (_endClip != null)
                {
                    _out.clip = _endClip;
                    _out.volume = EndMusicVolume * _scale * (_narration != null ? DuckLevel : 1f);
                    _out.Play();
                }
            }
            if (_musicStarted && _out.isPlaying && _t > _duckUntil)   // back to full once the narrator is done
                _out.volume = Mathf.MoveTowards(_out.volume, EndMusicVolume * _scale, Time.deltaTime / DuckRelease * EndMusicVolume * _scale);
        }
    }
}
