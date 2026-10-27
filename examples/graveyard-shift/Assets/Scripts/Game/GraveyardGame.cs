// ---------------------------------------------------------------------------
// GraveyardGame.cs
// Purpose : The one MonoBehaviour in the scene (on "Bootstrap"): builds the level, spawns the keeper and
//           the ghosts, reads input (or runs a bot), runs the night's rules, plays sounds, logs markers
//           and keeps the save.
// Usage   : The scene is made by SceneBuilder.Build (dev.py exec SceneBuilder.Build). Command line options
//           (player or editor, after `--` or anywhere): --autoplay careful|lit|dark, --seed N, --handmade, --difficulty D, --fixed-fps, --shot FILE,
//           --god, --debug-ai. Without --seed each night gets the next seed (LevelGenerator.SeedForNight: night 0
//           is the hand-made yard, every later one a generated yard); the HUD shows it, --seed N replays it.
//           Tests set GraveyardGame.Options before loading the scene.
// Notes   : Markers for dev.py smoke --until/--fail-on: NIGHT_START, SOUL n/12, GATE_OPEN, GATE_SHUT, GHOST_HUNT id,
//           CAUGHT (costs a soul and the walk back), ESCAPED, DAWN. Keyboard: WASD/arrows move, Space or F lantern, R restart; gamepad
//           through the Input Manager's default axes (left stick, button 3 for the lantern).
//
// Pseudocode (Update):
//   R: reload the scene | input = bot or keyboard/gamepad | lantern toggle
//   keeper.Move | each ghost: Think (perception, state machine, agent) -> caught?
//   rules.Tick (clock, souls, gate) -> events: sounds, log markers, gate light, save on the end
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes (Claude Opus 5.5): GateShut after a catch shuts the gate at once (the respawned
//           keeper slipped out while it swung); bot nights never write the save (--autoplay advanced the player's
//           nightsPlayed); OnEvent is public so PlayMode tests can drive a catch or an ending.
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using graveyard_shift.Core;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace graveyard_shift.Game
{
    public sealed class LaunchOptions
    {
        public BotMode? Bot;
        public bool God;
        public bool DebugAi;
        public int? Seed;         // which night: the yard (0 = hand-made), where each ghost starts and which way round; null = the next night
        public bool HandMadeYard; // the hand-made yard whatever the seed (the scenario trio's baseline)
        public bool FixedFps;     // every frame is exactly 1/60 s of game time: replays a test night exactly, fast
        public string SavePath;   // null = persistentDataPath/save.json
        public string ShotPath;   // --shot FILE: save one frame, HUD included, after ShotDelayFrames (a windowed player only)
        public Core.Difficulty? Difficulty;   // --difficulty easy|normal|hard|insane: skips the title screen; null = the saved one

        public static LaunchOptions FromCommandLine()
        {
            var o = new LaunchOptions();
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--autoplay" && i + 1 < args.Length)
                {
                    string m = args[++i];
                    o.Bot = m == "lit" ? BotMode.AlwaysLit : m == "dark" ? BotMode.AlwaysDark : BotMode.Careful;
                }
                else if (args[i] == "--god") o.God = true;
                else if (args[i] == "--debug-ai") o.DebugAi = true;
                else if (args[i] == "--seed" && i + 1 < args.Length && int.TryParse(args[++i], out int seed)) o.Seed = seed & int.MaxValue;   // never negative
                else if (args[i] == "--handmade") o.HandMadeYard = true;
                else if (args[i] == "--fixed-fps") o.FixedFps = true;
                else if (args[i] == "--shot" && i + 1 < args.Length) o.ShotPath = args[++i];
                else if (args[i] == "--difficulty" && i + 1 < args.Length) o.Difficulty = DifficultySettings.Parse(args[++i]);
            }
            return o;
        }
    }

    public sealed class GraveyardGame : MonoBehaviour
    {
        public static LaunchOptions Options;          // set by tests before the scene loads, else the command line
        public static GraveyardGame Current { get; private set; }
        public static bool TitleDone;                 // the title screen was passed this session (R restarts without it)

        [SerializeField] private GraveyardSetup setup;

        private GameTuning _t;
        private Level _level;
        private BuiltLevel _built;
        private GraveyardAudio _world;
        private Camera _cam;
        public EndSequence End { get; private set; }
        private AudioSource _audio;
        private SaveStore _store;
        private bool _saved;
        private float _endTimer;
        private const float AutoplayQuitAfter = 2f;   // s
        private const int ShotDelayFrames = 90;       // --shot waits this long, so the HUD and the yard have settled
        private const float FallLimit = -3f;          // m: below the ground means out of the world

        public NightRules Night { get; private set; }
        public KeeperController Keeper { get; private set; }
        public readonly List<GhostAgent> Ghosts = new List<GhostAgent>();
        public KeeperBot Bot { get; private set; }
        public SaveV3 Save { get; private set; }
        public LaunchOptions Launch { get; private set; }
        public Outcome Outcome => Night?.Outcome ?? Outcome.Playing;
        public GameTuning Tuning => _t;
        public int NightSeed { get; private set; }
        public Level Yard => _level;
        public DifficultySettings Difficulty { get; private set; }
        public bool OnTitle { get; private set; }     // the title screen is up: the night waits
        public float CaughtMessage { get; private set; }          // s left to show the caught message
        private const float CaughtMessageSeconds = 2.5f;

        private void Start()
        {
            Current = this;
            Launch = Options ?? LaunchOptions.FromCommandLine();
            GameLog.DebugEnabled = Launch.DebugAi;
            if (Launch.FixedFps) Time.captureFramerate = 60;
            if (setup == null)
            {
                GameLog.Error("game", "Bootstrap has no SO_GraveyardSetup (run python tools/dev.py exec SceneBuilder.Build)");
                enabled = false;
                return;
            }
            _t = setup.tuning;
            _store = new SaveStore(Launch.SavePath);
            Save = _store.Load();
            // The difficulty: given on the command line (bots, tests), else the one saved from the title screen
            Difficulty = DifficultySettings.For(Launch.Difficulty ?? DifficultySettings.Parse(Save.settings.difficulty));
            OnTitle = Options == null && Launch.Bot == null && Launch.Difficulty == null && !TitleDone;
            // Tonight's yard: the seed given, else the next night's; generated, or the hand-made one for seed 0
            NightSeed = Launch.Seed ?? LevelGenerator.SeedForNight(Save.nightsPlayed);
            _level = Launch.HandMadeYard ? Level.Graveyard() : LevelGenerator.Generate(NightSeed, _t);
            if (_level.Fallback) GameLog.Warn("game", $"seed {NightSeed}: no fair yard in {LevelGenerator.MaxAttempts} attempts, using the hand-made one");
            _built = LevelBuilder.Build(_level, setup, Difficulty);
            Night = new NightRules(_t, _level.Souls.Count);

            var keeperGo = new GameObject("Keeper");
            keeperGo.transform.position = LevelBuilder.ToWorld(_level.KeeperStart);
            Keeper = keeperGo.AddComponent<KeeperController>();
            Keeper.Init(_t, setup, Difficulty.DarkGlowScale);

            // One ghost per patrol loop, then the difficulty's extra ghosts on the longest loops, on the opposite
            // corner and walking the other way (GhostPlan; every corner is checked: no ghost starts on the keeper)
            foreach (var spawn in GhostPlan.For(_level, NightSeed, Difficulty.ExtraGhosts))
            {
                var g = new GameObject($"Ghost{Ghosts.Count}").AddComponent<GhostAgent>();
                g.Init(Ghosts.Count, _t, spawn.Route(_level), setup, spawn.Start, Difficulty.GhostLightScale);
                Ghosts.Add(g);
            }

            var cam = CameraRig.Create(keeperGo.transform);
            _cam = cam;
            _audio = cam.gameObject.AddComponent<AudioSource>();
            _audio.volume = Save.settings.volume;
            StartLoop(cam.gameObject, setup.ambience, setup.ambienceVolume);
            StartLoop(cam.gameObject, PickMusic(setup.musicTracks, Save.nightsPlayed), setup.musicVolume);
            _world = gameObject.AddComponent<GraveyardAudio>();
            _world.Init(setup, Keeper, Ghosts, _built.Souls, cam.transform, Save.settings.volume, intro: !OnTitle);
            gameObject.AddComponent<Hud>();
            if (Launch.Bot.HasValue) Bot = new KeeperBot(Launch.Bot.Value);
            string yard = _level.HandMade ? "hand-made" : $"generated attempts={_level.Attempts}";
            GameLog.Info("game", $"READY v{Application.version} seed={NightSeed} yard={yard} difficulty={Difficulty.Level} ghosts={Ghosts.Count}" + (OnTitle ? " title" : "") + (Bot != null ? $" autoplay={Bot.Mode}" : "") + (Launch.God ? " god" : ""));
            if (!string.IsNullOrEmpty(Launch.ShotPath)) StartCoroutine(Shot(Launch.ShotPath));
        }

        // One frame as the player sees it (the HUD is IMGUI, so camera renders miss it; ScreenCapture does not)
        private System.Collections.IEnumerator Shot(string path)
        {
            for (int i = 0; i < ShotDelayFrames; i++) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(path);
            GameLog.Info("game", $"SHOT {path}");
        }

        // The title screen's Start: remember the difficulty and build the night with it
        public void StartNight(Core.Difficulty difficulty)
        {
            Save.settings.difficulty = difficulty.ToString();
            _store.Write(Save);
            TitleDone = true;
            SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
        }

        private void Update()
        {
            if (Night == null || OnTitle) return;    // the title screen (Hud) is up
            float dt = Time.deltaTime;
            if (Input.GetKeyDown(KeyCode.R) || Input.GetKeyDown(KeyCode.JoystickButton7))
            {
                SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
                return;
            }
            if (Input.GetKeyDown(KeyCode.Escape) && Bot == null)
            {
                TitleDone = false;   // back to the title screen
                SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
                return;
            }
            if (Night.Outcome != Outcome.Playing)
            {
                // A command-line autoplay run (a smoke test of the built player) quits by itself after the night
                _endTimer += dt;
                if (Bot != null && Options == null && _endTimer >= AutoplayQuitAfter) Application.Quit(Night.Outcome == Outcome.Escaped ? 0 : 3);
                return;
            }
            CaughtMessage = Mathf.Max(0f, CaughtMessage - dt);

            Vector2 move;
            if (Bot != null)
            {
                Bot.Think(dt, _t, Keeper, Night, _built.SoulPositions, _level.Gate, Ghosts, _level);
                move = Bot.Direction;
                if (Bot.Lantern != Keeper.LanternLit) ToggleLantern();
            }
            else
            {
                move = new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));
                if (Input.GetKeyDown(KeyCode.Space) || Input.GetKeyDown(KeyCode.F) || Input.GetKeyDown(KeyCode.JoystickButton3))
                    ToggleLantern();
            }
            Keeper.Move(move, dt);
            // Safety net: whatever hole a future layout opens, nobody falls forever
            if (Keeper.transform.position.y < FallLimit)
            {
                Keeper.Respawn(LevelBuilder.ToWorld(_level.KeeperStart));
                GameLog.Warn("game", "FELL out of the yard: back at the start");
            }

            bool caught = false;
            foreach (var g in Ghosts)
            {
                bool touch = g.Think(dt, Keeper, out bool changed);
                if (changed && g.Brain.State == GhostState.Suspicious) Play(setup.ghostAlert, 0.7f);
                if (changed) _world.GhostChanged(g);   // the ghost speaks: noticed you, lost you, gives up
                if (changed && g.Brain.State == GhostState.Hunt) GameLog.Info("game", $"GHOST_HUNT ghost={g.Id}");
                if (changed) GameLog.Debug("ai", $"ghost {g.Id} -> {g.Brain.State}");
                caught |= touch && !Launch.God;
            }

            foreach (var e in Night.Tick(dt, Keeper.Moving, Keeper.Ground, _built.SoulPositions, _level.Gate, caught, _built.Gate.IsOpen))
            {
                OnEvent(e);
            }
        }

        private void ToggleLantern()
        {
            Keeper.SetLantern(!Keeper.LanternLit);
            Play(setup.lanternToggle, 0.4f);
        }

        // public for PlayMode tests (a catch at the open gate, the end of a bot night) that need no ghost or walk
        public void OnEvent(NightEvent e)
        {
            switch (e)
            {
                case NightEvent.Started:
                    GameLog.Info("game", "NIGHT_START");
                    break;
                case NightEvent.SoulCollected:
                    for (int i = 0; i < _built.Souls.Count; i++) _built.Souls[i].SetActive(!Night.IsCollected(i));
                    Play(setup.soulCollected, 0.8f);
                    _world.KeeperSays(KeeperLine.Soul);
                    GameLog.Info("game", $"SOUL {Night.Collected}/{Night.SoulCount}");
                    break;
                case NightEvent.AllSouls:
                    _built.GateLight.color = new Color(0.5f, 1f, 0.55f);
                    _built.Gate.Open();
                    Play(setup.gateOpens, 0.9f);
                    _world.KeeperSays(KeeperLine.Gate);
                    GameLog.Info("game", "GATE_OPEN");
                    break;
                case NightEvent.LowTime:
                    GameLog.Info("game", "LOW_TIME");
                    _world.KeeperSays(KeeperLine.LowTime);
                    break;
                case NightEvent.Escaped:
                    Keeper.PlayEnd(true);
                    GameLog.Info("game", $"ESCAPED time={Night.Elapsed:0.0}s");
                    EndNight(escaped: true);
                    break;
                case NightEvent.Caught:
                    // Costs time, not the night: wake at the gate, the last soul slips back, the ghost goes home
                    Play(setup.caught, 1f);
                    _world.Caught();
                    Keeper.Respawn(LevelBuilder.ToWorld(_level.KeeperStart));
                    if (Night.LastLostSoul >= 0) _built.Souls[Night.LastLostSoul].SetActive(true);
                    foreach (var g in Ghosts) if (V2.Distance(g.Ground, Keeper.Ground) < 30f && g.Brain.State == GhostState.Hunt) g.Brain.Tire();
                    _built.GateLight.color = new Color(1f, 0.35f, 0.25f);
                    CaughtMessage = CaughtMessageSeconds;
                    GameLog.Info("game", $"CAUGHT time={Night.Elapsed:0.0}s souls={Night.Collected} catches={Night.Catches}");
                    break;
                case NightEvent.GateShut:
                    // The soul that slipped back was the last one: the gate shuts until it is collected again. At once,
                    // not swinging: the keeper just woke 3 m inside it (Caught comes first in the same tick)
                    _built.Gate.Shut();
                    GameLog.Info("game", "GATE_SHUT");
                    break;
                case NightEvent.Dawn:
                    GameLog.Info("game", $"DAWN souls={Night.Collected}");
                    EndNight(escaped: false);
                    break;
            }
        }

        private void EndNight(bool escaped)
        {
            if (_saved) return;
            _saved = true;
            // Bots never touch the save: an --autoplay run of the player would move your next night on (and its seed)
            if (Bot == null)
            {
                Save.nightsPlayed++;
                if (escaped) Save.RecordEscape(Night.Elapsed);
                _store.Write(Save);
            }
            // the ending: dawn (birds, sunrise) or a moment at the gate, a screen fade, the end card and its music
            End = gameObject.AddComponent<EndSequence>();
            End.Begin(!escaped, setup.dawnChorus, _built.Moon, _cam,
                PickMusic(escaped ? setup.winTracks : setup.lossStings, Save.nightsPlayed),
                PickMusic(escaped ? setup.narratorEscape : setup.narratorDawn, Save.nightsPlayed), Save.settings.volume, _world);
        }

        private void Play(AudioClip clip, float volume)
        {
            if (clip != null && _audio != null) _audio.PlayOneShot(clip, volume);
        }

        // The tracks take turns: each finished night (saved) moves to the next one, so replays do not always sound the same
        public static AudioClip PickMusic(AudioClip[] tracks, int nightsPlayed)
        {
            if (tracks == null || tracks.Length == 0) return null;
            int i = ((nightsPlayed % tracks.Length) + tracks.Length) % tracks.Length;
            return tracks[i];
        }

        // A looping background layer (night ambience, music); a missing clip is skipped, not an error
        private void StartLoop(GameObject host, AudioClip clip, float volume)
        {
            if (clip == null) return;
            var src = host.AddComponent<AudioSource>();
            src.clip = clip;
            src.loop = true;
            src.volume = volume * Save.settings.volume;
            src.Play();
        }
    }
}
