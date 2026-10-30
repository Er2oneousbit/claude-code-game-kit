// ---------------------------------------------------------------------------
// GraveyardAudio.cs
// Purpose : The sounds and voices of the yard that follow the game. Each soul whispers where it floats (find it
//           by ear), each ghost moans louder as it grows wary and loudest when it hunts you, and speaks when it
//           notices you, loses you or gives up; the keeper's footsteps follow the distance walked, the lantern
//           crackles while lit, the keeper mutters at the big moments, and a narrator opens the first night.
//           Also places the audio listener.
// Usage   : gameObject.AddComponent<GraveyardAudio>().Init(setup, keeper, ghosts, souls, cam.transform, volume, intro)
//           then GhostChanged(ghost), KeeperSays(KeeperLine.Soul), Caught(), Silence() from the game.
// Notes   : The listener sits at the keeper, not on the high camera, so "closer to a soul" means closer to the
//           keeper; it takes the camera's heading, so left on screen is left in your ears. Positional clips must
//           be mono. Keeper and narrator share one voice channel: a line waits (briefly) for the one playing, so
//           nobody talks over anybody, and a line that waited too long is dropped. Ghosts speak from where they
//           float, at most once per WhisperCooldown each. A set never plays the same line twice in a row.
//           Missing clips are skipped. All numbers are in the constants block.
//
// Pseudocode (each frame):
//   listener -> keeper position, camera heading
//   narrator intro (first night of a launch) after IntroDelay; a queued keeper line when the channel is free
//   ghosts: fade each moan toward the volume for its state (patrol, wary, hunting)
//   footsteps: add the distance walked; every stride (lit or dark) play a random take, small pitch change
//   lantern: fade the crackle toward lit or out
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using graveyard_shift.Core;
using UnityEngine;

namespace graveyard_shift.Game
{
    public enum KeeperLine { Soul, Gate, LowTime, Caught }

    public sealed class GraveyardAudio : MonoBehaviour
    {
        private const float ListenerHeight = 1.2f;    // m above the keeper's feet (about the ears)
        private const float SoulVolume = 0.55f;
        private const float SoulNear = 1.5f;          // m: full volume inside this
        private const float SoulFar = 11f;            // m: silent beyond this (a soul across the yard is not heard)
        private const float GhostNear = 2f;
        private const float GhostFar = 16f;
        private const float GhostPatrol = 0.25f;      // volume by ghost state
        private const float GhostWary = 0.5f;
        private const float GhostHunt = 0.9f;
        private const float GhostFade = 1.5f;         // volume per second when a ghost changes state
        private const float StrideLit = 1.4f;         // m between footsteps, lantern lit (fast, long strides)
        private const float StrideDark = 0.9f;        // m between footsteps in the dark (creeping)
        private const float StepLit = 0.22f;          // footstep volume (halved after the user's mix check: "too loud")
        private const float StepDark = 0.1f;
        private const float StepPitch = 0.06f;        // +- pitch per step, so steps do not sound like a loop
        private const float Teleport = 2f;            // m in one frame: a respawn, not a walk (no burst of steps)
        private const float FlameVolume = 0.35f;
        private const float FlameFade = 1.5f;
        private const float WhisperVolume = 0.9f;
        private const float WhisperFar = 18f;         // m: a ghost's whisper carries further than its moan
        private const float WhisperCooldown = 6f;     // s per ghost, so a ghost that dithers does not chatter
        private const float VoiceVolume = 0.85f;      // keeper, narrator and the caught line (2D)
        private const float VoiceGap = 0.25f;         // s of quiet between two lines on the voice channel
        private const float VoiceMaxWait = 2.5f;      // s a line may wait for the channel before it is dropped
        private const float IntroDelay = 1.0f;        // s after the scene loads before the narrator starts

        private static bool s_introPlayed;            // the intro opens the first night of a launch, not every R

        // A set of takes that never plays the same one twice in a row
        private sealed class Lines
        {
            private readonly AudioClip[] _clips;
            private int _last = -1;
            public Lines(AudioClip[] clips) { _clips = clips ?? new AudioClip[0]; }
            public bool Empty => _clips.Length == 0;
            public AudioClip Next(System.Random rng)
            {
                if (_clips.Length == 0) return null;
                int i = rng.Next(_clips.Length);
                if (_clips.Length > 1 && i == _last) i = (i + 1) % _clips.Length;
                _last = i;
                return _clips[i];
            }
        }

        private KeeperController _keeper;
        private List<GhostAgent> _ghosts;
        private readonly List<AudioSource> _ghostSources = new List<AudioSource>();
        private readonly List<AudioSource> _ghostVoices = new List<AudioSource>();
        private readonly List<float> _lastWhisper = new List<float>();
        private Transform _listener;
        private Transform _camera;
        private AudioSource _steps;
        private AudioSource _flame;
        private AudioSource _voice;
        private AudioClip[] _footsteps;
        private Lines _notice, _search, _giveUp, _caught, _intro;
        private readonly Dictionary<KeeperLine, Lines> _keeperLines = new Dictionary<KeeperLine, Lines>();
        private AudioClip _pending;
        private float _pendingUntil;
        private float _voiceFreeAt;
        private float _introAt = -1f;
        private bool _silent;
        private float _scale;
        private Vector3 _lastPos;
        private float _walked;
        private readonly System.Random _rng = new System.Random(7);

        public void Init(GraveyardSetup setup, KeeperController keeper, List<GhostAgent> ghosts, List<GameObject> souls,
            Transform cameraTransform, float volumeScale, bool intro = true)
        {
            _keeper = keeper;
            _ghosts = ghosts;
            _camera = cameraTransform;
            _scale = volumeScale;
            var listener = new GameObject("AudioListener");
            listener.AddComponent<AudioListener>();
            _listener = listener.transform;

            for (int i = 0; i < souls.Count; i++)
                Loop(souls[i], setup.soulWhisper, SoulVolume * _scale, SoulNear, SoulFar, i);
            for (int i = 0; i < ghosts.Count; i++)
            {
                _ghostSources.Add(Loop(ghosts[i].gameObject, setup.ghostPresence, GhostPatrol * _scale, GhostNear, GhostFar, i + 11));
                var voice = ghosts[i].gameObject.AddComponent<AudioSource>();
                voice.playOnAwake = false;
                voice.spatialBlend = 1f;
                voice.rolloffMode = AudioRolloffMode.Linear;
                voice.minDistance = GhostNear;
                voice.maxDistance = WhisperFar;
                voice.dopplerLevel = 0f;
                _ghostVoices.Add(voice);
                _lastWhisper.Add(-WhisperCooldown);
            }
            _notice = new Lines(setup.ghostNotice);
            _search = new Lines(setup.ghostSearch);
            _giveUp = new Lines(setup.ghostGiveUp);
            _caught = new Lines(setup.ghostCaught);
            _intro = new Lines(setup.narratorIntro);
            _keeperLines[KeeperLine.Soul] = new Lines(setup.keeperSoul);
            _keeperLines[KeeperLine.Gate] = new Lines(setup.keeperGate);
            _keeperLines[KeeperLine.LowTime] = new Lines(setup.keeperLowTime);
            _keeperLines[KeeperLine.Caught] = new Lines(setup.keeperCaught);

            _footsteps = setup.footsteps ?? new AudioClip[0];
            _steps = keeper.gameObject.AddComponent<AudioSource>();
            _steps.playOnAwake = false;
            _voice = keeper.gameObject.AddComponent<AudioSource>();
            _voice.playOnAwake = false;
            if (setup.lanternFlame != null)
            {
                _flame = keeper.gameObject.AddComponent<AudioSource>();
                _flame.clip = setup.lanternFlame;
                _flame.loop = true;
                _flame.volume = keeper.LanternLit ? FlameVolume * _scale : 0f;
                _flame.Play();
            }
            _lastPos = Flat(keeper.transform.position);
            if (intro && !s_introPlayed && !_intro.Empty)   // not behind the title screen: the night has not begun
            {
                s_introPlayed = true;
                _introAt = Time.time + IntroDelay;
            }
        }

        // A 3D loop on a world object; loops start at different points so several never pulse together
        private static AudioSource Loop(GameObject host, AudioClip clip, float volume, float near, float far, int index)
        {
            if (clip == null) return null;
            var s = host.AddComponent<AudioSource>();
            s.clip = clip;
            s.loop = true;
            s.volume = volume;
            s.spatialBlend = 1f;
            s.rolloffMode = AudioRolloffMode.Linear;
            s.minDistance = near;
            s.maxDistance = far;
            s.dopplerLevel = 0f;
            s.Play();
            s.timeSamples = (int)(index * 0.37f % 1f * clip.samples);
            return s;
        }

        public static float GhostVolume(GhostState state)
        {
            switch (state)
            {
                case GhostState.Hunt: return GhostHunt;
                case GhostState.Suspicious:
                case GhostState.Search: return GhostWary;
                default: return GhostPatrol;
            }
        }

        // A ghost changed state: it speaks for the states that have lines, from where it floats (once per cooldown)
        public void GhostChanged(GhostAgent ghost)
        {
            if (_silent) return;
            int i = _ghosts.IndexOf(ghost);
            if (i < 0) return;
            Lines set = ghost.Brain.State == GhostState.Suspicious ? _notice
                      : ghost.Brain.State == GhostState.Search ? _search
                      : ghost.Brain.State == GhostState.Return ? _giveUp : null;
            if (set == null || set.Empty || Time.time - _lastWhisper[i] < WhisperCooldown) return;
            _lastWhisper[i] = Time.time;
            _ghostVoices[i].PlayOneShot(set.Next(_rng), WhisperVolume * _scale);
        }

        // Caught: the ghost's line plays at the listener (it is on top of the keeper), then the keeper groans
        public void Caught()
        {
            if (_silent) return;
            Say(_caught.Next(_rng));
            KeeperSays(KeeperLine.Caught);
        }

        public void KeeperSays(KeeperLine line)
        {
            if (_silent || !_keeperLines.TryGetValue(line, out var set)) return;
            Say(set.Next(_rng));
        }

        // The night is over: stop steering volumes and voices, so EndSequence can fade everything out
        public void Silence()
        {
            _silent = true;
            _pending = null;
        }

        // The shared voice channel: play now if free, else wait (one line, the newest wins) for at most VoiceMaxWait
        private void Say(AudioClip clip)
        {
            if (clip == null) return;
            if (Time.time >= _voiceFreeAt) Play(clip);
            else
            {
                _pending = clip;
                _pendingUntil = Time.time + VoiceMaxWait;
            }
        }

        private void Play(AudioClip clip)
        {
            _voice.PlayOneShot(clip, VoiceVolume * _scale);
            _voiceFreeAt = Time.time + clip.length + VoiceGap;
        }

        private void LateUpdate()
        {
            if (_keeper == null) return;
            float dt = Time.deltaTime;
            _listener.position = _keeper.transform.position + Vector3.up * ListenerHeight;
            _listener.rotation = Quaternion.Euler(0f, _camera.eulerAngles.y, 0f);
            if (_silent) return;

            if (_introAt >= 0f && Time.time >= _introAt)
            {
                _introAt = -1f;
                Say(_intro.Next(_rng));
            }
            if (_pending != null && Time.time >= _voiceFreeAt)
            {
                if (Time.time <= _pendingUntil) Play(_pending);
                _pending = null;
            }

            for (int i = 0; i < _ghostSources.Count; i++)
            {
                var src = _ghostSources[i];
                if (src == null || _ghosts[i] == null) continue;
                src.volume = Mathf.MoveTowards(src.volume, GhostVolume(_ghosts[i].Brain.State) * _scale, GhostFade * dt);
            }

            bool lit = _keeper.LanternLit;
            var pos = Flat(_keeper.transform.position);
            float d = Vector3.Distance(pos, _lastPos);
            _lastPos = pos;
            float stride = lit ? StrideLit : StrideDark;
            if (!_keeper.Moving || d > Teleport) _walked = stride * 0.5f;   // the first step comes half a stride in
            else _walked += d;
            if (_walked >= stride)
            {
                _walked -= stride;
                Step(lit);
            }

            if (_flame != null)
                _flame.volume = Mathf.MoveTowards(_flame.volume, lit ? FlameVolume * _scale : 0f, FlameFade * dt);
        }

        private void Step(bool lit)
        {
            if (_footsteps.Length == 0) return;
            _steps.pitch = 1f + (float)(_rng.NextDouble() * 2.0 - 1.0) * StepPitch;
            _steps.PlayOneShot(_footsteps[_rng.Next(_footsteps.Length)], (lit ? StepLit : StepDark) * _scale);
        }

        private static Vector3 Flat(Vector3 v) => new Vector3(v.x, 0f, v.z);
    }
}
