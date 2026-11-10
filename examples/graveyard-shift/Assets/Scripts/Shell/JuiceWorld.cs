// ---------------------------------------------------------------------------
// JuiceWorld.cs
// Purpose : The juice demo (#275, as Godot and LÖVE have it; editor and development builds): a box you hit (attack)
//           that shakes the view with trauma, freezes the game for a hitstop, squashes on a spring and flashes the
//           screen through the FlashLimiter; a follow camera with its deadzone drawn; an input-buffered jump with
//           coyote time; a held guard (interact) that honours hold_to_toggle; the intro line, a bark and a sound
//           caption; analog movement (a half-leaned stick walks at half speed, #274); the access settings live.
// Usage   : main menu > Juice demo, or python tools/dev.py smoke --drive show:juice --screenshot Logs/juice.png
// Notes   : Drawn with UI Toolkit elements in the world layer (no sprites needed). Time: the hitstop and the flash
//           limiter run on REAL time (unscaled); everything else (shake, follow, spring, input buffer, coyote) on GAME
//           time = the hitstop-scaled real delta times access.game_speed. Nothing moves while paused. The limiter is
//           always on (at most 3 flashes per real second); access.flash_limit only tones each flash down to
//           FLASH_GENTLE. Shake intensity is GameSettings.EffectiveShake (0 with reduce motion). Colours come from
//           data/access/colours.json (player, target, hit, floor, deadzone) when it has them, so the colour-blind
//           setting swaps this demo's palette. timing_scale lengthens the buffer and coyote windows.
//
// Pseudocode (Tick):
//   paused -> nothing ; real += unscaled dt ; flash fades on real time ; dt = hitstop.ScaledDt(real dt) * speed
//   move by ShellInput.MoveVector().x ; gravity, floor ; jump = buffer + coyote ; guard = held interact (or toggle)
//   attack in range -> trauma, hitstop, spring kick, flash (when the limiter allows), caption, bark
//   camera follows ; shake offset ; spring ; draw: stage translated by camera + shake, rotated by the shake angle
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using graveyard_shift.Core;

namespace graveyard_shift.Shell
{
    public sealed class JuiceWorld : ShellWorld
    {
        // ---- Tunables ------------------------------------------------------------
        public const double COYOTE_S = 0.1;            // coyote time before access.timing_scale
        public const float WORLD_W = 1600f;
        public const float FLOOR_Y = 420f;
        public const float PLAYER = 28f;
        public const float TARGET = 56f;
        public const float TARGET_X = 600f;
        public const float START_X = 540f;             // in hitting range from the start (a drive attacks at once)
        public const float SPEED = 220f;
        public const float GRAVITY = 1300f;
        public const float JUMP_SPEED = 520f;
        public const float HIT_RANGE = 100f;           // px between centres
        public const double HIT_TRAUMA = 0.55;
        public const double HIT_STOP_S = 0.09;
        public const double HIT_SQUASH = 0.45;         // spring displacement on a hit
        public const float FLASH_S = 0.12f;            // a flash fades out over this (real time)
        public const float FLASH_FULL = 0.85f, FLASH_GENTLE = 0.3f;   // peak opacity without / with access.flash_limit
        public const float POP_S = 0.25f;              // the hit ring eases out over this
        public const string INTRO_LINE = "guide.intro", HIT_BARK = "box.ouch", HIT_CAPTION = "box_hit";
        public static readonly string[] HINT_ACTIONS = { "move_left", "move_right", "jump", "attack", "interact", "pause" };
        private static readonly Dictionary<string, Color> DEFAULT_COLOURS = new Dictionary<string, Color>
        {
            { "player", new Color(0.36f, 0.78f, 1.0f) }, { "target", new Color(1.0f, 0.62f, 0.26f) },
            { "hit", new Color(1.0f, 0.95f, 0.75f) }, { "floor", new Color(0.20f, 0.23f, 0.34f) },
            { "deadzone", new Color(0.55f, 0.60f, 0.75f, 0.5f) },
        };

        /// <summary>The demo is on the main menu in the editor and development builds only.</summary>
        public static bool Available => Debug.isDebugBuild || Application.isEditor;

        public int Hits { get; private set; }
        public int Refused { get; private set; }       // flashes the limiter held back
        public bool Guarding { get; private set; }
        public float PlayerX => _px;

        private readonly FrontEnd _front;
        private readonly Shake _shake = new Shake(10.0, 0.04);
        private readonly Hitstop _hitstop = new Hitstop();
        private readonly Spring _spring = new Spring(4.0, 0.35);
        private readonly FlashLimiter _limiter = new FlashLimiter();
        private readonly InputBuffer _buffer = new InputBuffer();
        private CoyoteTimer _coyote = new CoyoteTimer(COYOTE_S);
        private FollowCamera _cam;
        private double _timingScale = 1.0;
        private float _px = START_X, _py = FLOOR_Y - PLAYER, _vx, _vy;
        private double _real, _flash, _flashPeak, _pop;
        private (double X, double Y, double Angle) _offset;
        private bool _introPlayed;
        private Dictionary<string, Color> _colours;

        private VisualElement _root, _view, _stage, _target, _player, _guardRing, _hitRing, _deadzone, _flashLayer, _hud;
        private Label _hint, _stats, _guard;

        public JuiceWorld(FrontEnd front)
        {
            _front = front;
            _cam = new FollowCamera(120, 80, 0.2, 6, START_X + PLAYER / 2, FLOOR_Y - 120);
        }

        public override string Name => "juice";

        public override void Build(VisualElement layer)
        {
            Shell s = Shell.I;
            _root = Box("Juice", UiTheme.BG);
            _root.style.position = Position.Absolute;
            Fill(_root);
            layer.Add(_root);
            _view = Box("JuiceView", Color.clear);
            Fill(_view);
            _view.style.overflow = Overflow.Hidden;
            _view.style.transformOrigin = new TransformOrigin(Length.Percent(50), Length.Percent(50));
            _root.Add(_view);
            _stage = Box("Stage", Color.clear);
            _stage.style.position = Position.Absolute;
            _stage.style.left = 0;
            _stage.style.top = 0;
            _view.Add(_stage);
            _stage.Add(Rect("Floor", -200, FLOOR_Y, WORLD_W + 400, 300, "floor"));
            for (float gx = 0; gx <= WORLD_W; gx += 80)
            {
                _stage.Add(Rect("Mark", gx, FLOOR_Y + 8, 3, 10, null, UiTheme.BORDER));   // floor marks: camera motion shows
            }
            _deadzone = Box("Deadzone", Color.clear);
            _deadzone.style.position = Position.Absolute;
            _stage.Add(_deadzone);
            _target = Rect("Target", TARGET_X, FLOOR_Y - TARGET, TARGET, TARGET, "target");
            _stage.Add(_target);
            _hitRing = Box("HitRing", Color.clear);
            _hitRing.style.position = Position.Absolute;
            _stage.Add(_hitRing);
            _player = Rect("Player", _px, _py, PLAYER, PLAYER, "player");
            _stage.Add(_player);
            _guardRing = Box("GuardRing", Color.clear);
            _guardRing.style.position = Position.Absolute;
            _stage.Add(_guardRing);
            _flashLayer = Box("Flash", Color.clear);
            Fill(_flashLayer);
            _root.Add(_flashLayer);
            _hud = Box("Hud", Color.clear);           // one column: rows grow with the text size and the language
            _hud.style.position = Position.Absolute;
            _hud.style.left = 16;
            _hud.style.right = 16;
            _hud.style.top = 12;
            _hud.style.flexDirection = FlexDirection.Column;
            _root.Add(_hud);
            Hud(new Label(s.T("juice.title")) { name = "JuiceTitle" }, 1.3f, UiTheme.FOCUS);
            _hint = Hud(new Label("") { name = "Hint" }, 0.8f, UiTheme.TEXT);
            _stats = Hud(new Label("") { name = "Stats" }, 0.8f, UiTheme.TEXT_DIM);
            _guard = Hud(new Label(s.T("juice.guard")) { name = "Guard" }, 0.8f, UiTheme.FOCUS);
            _root.Add(Subtitles.Root);
            Recolour();
            RefreshHint();
            s.SetObjective(s.T("juice.objective"));
            s.SettingsChanged += OnSettingsChanged;
            ShellInput.DeviceChanged += OnDevice;
            Draw();
        }

        public override void Dispose()
        {
            Shell.I.SettingsChanged -= OnSettingsChanged;
            ShellInput.DeviceChanged -= OnDevice;
            _root?.RemoveFromHierarchy();
            _root = null;
        }

        public override void Tick(float dt)
        {
            if (Time.timeScale <= 0f)
            {
                return;                               // paused: the pause menu is over the demo
            }
            Shell s = Shell.I;
            double real = Time.unscaledDeltaTime;
            _real += real;
            _flash = Math.Max(0, _flash - real);
            double g = _hitstop.ScaledDt(real) * s.GameSpeed();      // game time from here on
            if (!_introPlayed)
            {
                _introPlayed = true;
                Subtitles.Play(INTRO_LINE);
            }
            TimingWindows(GameSettings.Number(s.Settings, "access", "timing_scale"));
            _vx = ShellInput.MoveVector().x * SPEED;
            _px = Mathf.Clamp(_px + (float)(_vx * g), 0, WORLD_W - PLAYER);
            _vy += (float)(GRAVITY * g);
            _py += (float)(_vy * g);
            bool onFloor = _py >= FLOOR_Y - PLAYER;
            if (onFloor)
            {
                _py = FLOOR_Y - PLAYER;
                _vy = 0;
            }
            if (ShellInput.JustPressed("jump"))
            {
                _buffer.Press("jump");
            }
            if (ShellInput.JustPressed("attack"))      // auto-repeats while held with access.auto_repeat (#166)
            {
                Hit();
            }
            if (s.AccessOn("hold_to_toggle"))
            {
                if (ShellInput.JustPressed("interact"))
                {
                    Guarding = !Guarding;
                }
            }
            else
            {
                Guarding = ShellInput.IsGameHeld("interact");
            }
            _coyote.Update(g, onFloor);
            _buffer.Update(g);
            if (_coyote.CanJump() && _buffer.Consume("jump"))
            {
                _vy = -JUMP_SPEED;
                _coyote.Consume();
            }
            _cam.Update(g, _px + PLAYER / 2, _py, _vx, 0);
            _offset = _shake.Update(g, s.EffectiveShake());
            _spring.Update(g);
            _pop = Math.Max(0, _pop - g);
            Subtitles.Tick(dt);
            Draw();
        }

        /// <summary>An attack: in range of the box, every juice primitive fires once.</summary>
        public void Hit()
        {
            if (Mathf.Abs((_px + PLAYER / 2) - (TARGET_X + TARGET / 2)) > HIT_RANGE)
            {
                return;
            }
            Hits++;
            _shake.AddTrauma(HIT_TRAUMA);
            _hitstop.Hit(HIT_STOP_S);
            _spring.X = HIT_SQUASH;
            _pop = POP_S;
            if (_limiter.Request(_real))                // real time: always rate-limited
            {
                _flash = FLASH_S;
                _flashPeak = Shell.I.AccessOn("flash_limit") ? FLASH_GENTLE : FLASH_FULL;
            }
            else
            {
                Refused++;
            }
            Subtitles.Caption(HIT_CAPTION);
            Subtitles.Play(HIT_BARK);
        }

        // ---- drawing -------------------------------------------------------------------------

        private void Draw()
        {
            if (_root == null)
            {
                return;
            }
            float vw = _view.resolvedStyle.width > 0 ? _view.resolvedStyle.width : FrontEnd.REF_W;    // NaN before the first layout
            float vh = _view.resolvedStyle.height > 0 ? _view.resolvedStyle.height : FrontEnd.REF_H;
            _stage.style.translate = new Translate(Mathf.Floor(vw / 2 - (float)_cam.X + (float)_offset.X),
                                                   Mathf.Floor(vh / 2 - (float)_cam.Y + (float)_offset.Y));
            _view.style.rotate = new Rotate(new Angle((float)_offset.Angle * Mathf.Rad2Deg, AngleUnit.Degree));
            (double sx, double sy) = Squash.Scale(_spring.X);
            float tw = TARGET * (float)sx, th = TARGET * (float)sy;
            Place(_target, TARGET_X + (TARGET - tw) / 2, FLOOR_Y - th, tw, th);
            Place(_player, _px, _py, PLAYER, PLAYER);
            Ring(_guardRing, _px + PLAYER / 2, _py + PLAYER / 2, PLAYER, Guarding);
            float k = _pop > 0 ? (float)Ease.Apply("out_back", 1 - _pop / POP_S) : 0f;
            Ring(_hitRing, TARGET_X + TARGET / 2, FLOOR_Y - TARGET / 2, 14 + 40 * k, _pop > 0);
            Place(_deadzone, (float)(_cam.X - _cam.DeadzoneW / 2), (float)(_cam.Y - _cam.DeadzoneH / 2),
                  (float)_cam.DeadzoneW, (float)_cam.DeadzoneH);
            Color hit = Colour("hit");
            _flashLayer.style.backgroundColor = new Color(hit.r, hit.g, hit.b, _flash > 0 ? (float)(_flashPeak * (_flash / FLASH_S)) : 0f);
            Shell s = Shell.I;
            _stats.text = s.T("juice.stats", new Dictionary<string, object>
            {
                { "hits", Hits }, { "trauma", _shake.Trauma.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture) },
                { "shake", s.EffectiveShake().ToString("0.00", System.Globalization.CultureInfo.InvariantCulture) },
                { "refused", Refused }, { "speed", (int)Math.Round(s.GameSpeed() * 100) },
            });
            _guard.style.display = Guarding ? DisplayStyle.Flex : DisplayStyle.None;
        }

        private void RefreshHint()
        {
            Shell s = Shell.I;
            var args = new Dictionary<string, object>();
            foreach (string action in HINT_ACTIONS)
            {
                args[action.Replace("move_", "")] = s.BindingText(s.PromptFor(action));
            }
            _hint.text = s.T("play.hint", args);
        }

        private void Recolour()
        {
            _colours = Shell.I.Palette();
            _stage.Query<VisualElement>().ForEach(e =>
            {
                if (e.userData is string key)
                {
                    e.style.backgroundColor = Colour(key);
                }
            });
            UiTheme.Border(_deadzone, Colour("deadzone"), 1);
            UiTheme.Border(_guardRing, Colour("player"), 2);
            UiTheme.Border(_hitRing, Colour("hit"), 3);
        }

        private Color Colour(string key)
        {
            return _colours != null && _colours.TryGetValue(key, out Color c) ? c : DEFAULT_COLOURS[key];
        }

        private void TimingWindows(double k)
        {
            if (Math.Abs(k - _timingScale) < 1e-9)
            {
                return;
            }
            _timingScale = k;                         // access.timing_scale (#166): every timing window, longer by the factor
            _buffer.Window = InputBuffer.DEFAULT_WINDOW_S * k;
            _coyote = new CoyoteTimer(COYOTE_S * k);
        }

        private void OnSettingsChanged(string section, string key)
        {
            Subtitles.OnSettingsChanged(section, key);
            if (section == "access" && key == "colorblind")
            {
                Recolour();
            }
            if (section == "input" || section == "access" || section == "language")
            {
                RefreshHint();
            }
        }

        private void OnDevice(string device)
        {
            RefreshHint();
        }

        // ---- element helpers ----------------------------------------------------------------

        private static VisualElement Box(string name, Color bg)
        {
            var v = new VisualElement { name = name, pickingMode = PickingMode.Ignore };
            v.style.backgroundColor = bg;
            return v;
        }

        private static void Fill(VisualElement v)
        {
            v.style.position = Position.Absolute;
            v.style.left = 0;
            v.style.top = 0;
            v.style.right = 0;
            v.style.bottom = 0;
        }

        private VisualElement Rect(string name, float x, float y, float w, float h, string colourKey, Color? colour = null)
        {
            VisualElement v = Box(name, colour ?? Color.clear);
            v.userData = colourKey;                    // Recolour paints it from the palette
            v.style.position = Position.Absolute;
            Place(v, x, y, w, h);
            return v;
        }

        private static void Place(VisualElement v, float x, float y, float w, float h)
        {
            v.style.left = x;
            v.style.top = y;
            v.style.width = w;
            v.style.height = h;
        }

        private static void Ring(VisualElement v, float cx, float cy, float r, bool shown)
        {
            v.style.display = shown ? DisplayStyle.Flex : DisplayStyle.None;
            Place(v, cx - r, cy - r, r * 2, r * 2);
            UiTheme.Radius(v, r);
        }

        private Label Hud(Label label, float mult, Color colour)
        {
            label.pickingMode = PickingMode.Ignore;
            UiTheme.Text(label, mult, colour);
            UiTheme.Outline(label);                    // HUD text is outlined: it reads over any part of the game
            label.style.marginBottom = 4;
            _hud.Add(label);
            return label;
        }
    }
}
