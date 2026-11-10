// ---------------------------------------------------------------------------
// FrontEnd.cs
// Purpose : The screen flow on a UI Toolkit panel: boot -> title -> main menu -> settings / credits / play or the
//           juice demo (through the loading screen), pause over either with What now?, Dialogue history and settings,
//           quit to title. F8 saves a bug report (editor and development builds).
//           Reads the menu actions once a frame (ShellInput), moves focus on the top screen, narrates, and runs the
//           smoke drive when dev.py asks.
// Usage   : a scene with a Camera and one GameObject carrying FrontEnd (GameKitScenes.CreateShellScene makes it);
//           from code: FrontEnd.I.Pause(), FrontEnd.I.World.Subtitles.Play("line.id"),
//           FrontEnd.I.StartWorld(() => new MyGame(FrontEnd.I))   // your ShellWorld instead of PlayWorld
// Notes   : The panel scales the 1280x720 reference to the window so the smallest side fits (PanelScreenMatchMode
//           .Shrink: the same min(w/W, h/H) rule the access sweep uses). In batchmode and for captures the panel
//           draws into a RenderTexture (GameKitCapture composes it over the camera's picture) of the drive's size.
//           UI Toolkit's own navigation events are stopped at the root: the shell moves focus from the player's
//           bindings instead, so a remapped ui_accept works in the menus too; when ShellInput cannot poll (ui_events)
//           those events are turned into the menu actions (see ShellInput). Time.timeScale is 0 while paused and
//           access.game_speed otherwise; the menus run on unscaled time. Replace PlayWorld with your game.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the UI Toolkit fallback only when ShellInput cannot poll (#266)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): worlds (ShellWorld: play, the juice demo), the F8 bug
//           report, the crash drive's planted error (#275)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;
using {{GAME_SLUG}}.Core;
using {{GAME_SLUG}}.Shell.Screens;

namespace {{GAME_SLUG}}.Shell
{
    public sealed class FrontEnd : MonoBehaviour
    {
        // ---- Tunables ------------------------------------------------------------
        public const int REF_W = 1280;               // the reference resolution every size in UiTheme is given in
        public const int REF_H = 720;
        public const string THEME = "GameKit/GameKitTheme";      // Resources path of the panel theme (.tss)
        public const string SCENE_PATH = "Assets/Scenes/Shell.unity";
        public const int LOADING_FRAMES = 6;         // frames the loading screen shows while the world is built
        public static readonly string[] MENU_ACTIONS = { "ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel" };
        private static readonly string[] LOOK_KEYS = { "text_scale", "readable_font", "line_spacing", "language" };

        public static FrontEnd I { get; private set; }
        /// <summary>A PlayMode test sets this before loading the scene when it wants Shell.Drive to run.</summary>
        public static bool DriveArmed;

        public event Action<string> ScreenShown;
        public bool ConsentAsked;
        public bool QuitRequested { get; private set; }
        public ShellWorld World { get; private set; }
        /// <summary>The crash drive sets it: the next frame throws, as an unhandled bug in a game would (#275).</summary>
        public bool PlantCrash;
        public SmokeDrive Drive { get; private set; }
        public Narrator Narrator { get; } = new Narrator();
        public RenderTexture UiTexture { get; private set; }
        public UIDocument Document { get; private set; }

        private readonly List<ShellScreen> _stack = new List<ShellScreen>();
        private VisualElement _root;
        private VisualElement _worldLayer;
        private VisualElement _screenLayer;
        private PanelSettings _panel;
        private bool _paused;
        private int _loadingFrames = -1;
        private Func<ShellWorld> _nextWorld;

        // ---- life cycle ----------------------------------------------------------------

        private void Awake()
        {
            I = this;
            Shell.Ensure(gameObject);     // boots the sibling Shell even when its Awake has not run yet
            BuildPanel();
            Shell.I.SettingsChanged += OnSettingsChanged;
            Shell.I.LocaleChanged += RebuildAll;
        }

        private void Start()
        {
            Shell.I.ApplyAll();
            ShowTitle();
            if (DriveArmed && !string.IsNullOrEmpty(Shell.I.Drive))
            {
                Drive = new SmokeDrive(this, Shell.I.Drive);
                StartCoroutine(Drive.Run());
            }
        }

        private void OnDestroy()
        {
            if (Shell.I != null)
            {
                Shell.I.SettingsChanged -= OnSettingsChanged;
                Shell.I.LocaleChanged -= RebuildAll;
            }
            if (UiTexture != null)
            {
                UiTexture.Release();
            }
            Time.timeScale = 1f;
            if (I == this)
            {
                I = null;
            }
        }

        private void Update()
        {
            float dt = Time.unscaledDeltaTime;
            ShellInput.Begin(dt);
            if (PlantCrash)
            {
                PlantCrash = false;
                throw new InvalidOperationException("drive crash: a planted error to prove the crash file (expected)");
            }
            if (ShellReports.BugKeyEnabled && ShellInput.KeyDown(ShellReports.BUG_REPORT_KEY))
            {
                ShellReports.BugReport(this);
            }
            if (_loadingFrames >= 0 && --_loadingFrames < 0)
            {
                EnterWorld();
            }
            ShellScreen top = Top();
            if (ShellInput.JustPressed("pause") && World != null && (top == null || top.Name == "pause"))
            {
                if (_paused)
                {
                    Resume();
                }
                else
                {
                    Pause();
                }
            }
            else if (top != null)
            {
                foreach (string action in MENU_ACTIONS)
                {
                    if (ShellInput.JustPressed(action))
                    {
                        top.HandleAction(action);
                        break;                      // one menu action a frame, as a player presses them
                    }
                }
                if (ShellInput.JustPressed("pause") && top.Name == "title")
                {
                    top.HandleAction("pause");
                }
            }
            Top()?.Tick(dt);
            World?.Tick(Time.deltaTime);
            Narrator.Tick();
        }

        private void OnApplicationFocus(bool focused)
        {
            if (!focused && World != null && !_paused && Top() == null && !Shell.I.Smoke)
            {
                Pause();
            }
        }

        // ---- the panel -------------------------------------------------------------------

        private void BuildPanel()
        {
            Document = GetComponent<UIDocument>() ?? gameObject.AddComponent<UIDocument>();
            _panel = ScriptableObject.CreateInstance<PanelSettings>();
            _panel.name = "GameKitPanel";
            var theme = Resources.Load<ThemeStyleSheet>(THEME);
            if (theme != null)
            {
                _panel.themeStyleSheet = theme;
            }
            else
            {
                Debug.LogWarning($"[WARN][shell] no theme at Resources/{THEME}.tss: text may not render");
            }
            _panel.scaleMode = PanelScaleMode.ScaleWithScreenSize;
            _panel.screenMatchMode = PanelScreenMatchMode.Shrink;
            _panel.referenceResolution = new Vector2Int(REF_W, REF_H);
            _panel.clearColor = true;
            _panel.colorClearValue = new Color(0, 0, 0, 0);
            if (Application.isBatchMode || !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("GAMEKIT_SCREENSHOT"))
                || !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("GAMEKIT_RECORD_DIR")))
            {
                SetWindow(REF_W, REF_H);
            }
            Document.panelSettings = _panel;
            _root = Document.rootVisualElement;
            _root.name = "Root";
            _root.style.flexGrow = 1;
            _root.pickingMode = PickingMode.Ignore;
            _worldLayer = Layer("WorldLayer");
            _screenLayer = Layer("ScreenLayer");
            _root.RegisterCallback<NavigationMoveEvent>(OnNavigationMove, TrickleDown.TrickleDown);
            _root.RegisterCallback<NavigationSubmitEvent>(evt => Swallow(evt, "ui_accept"), TrickleDown.TrickleDown);
            _root.RegisterCallback<NavigationCancelEvent>(evt => Swallow(evt, "ui_cancel"), TrickleDown.TrickleDown);
            _root.RegisterCallback<KeyDownEvent>(OnKeyDown, TrickleDown.TrickleDown);
        }

        private VisualElement Layer(string name)
        {
            var layer = new VisualElement { name = name, pickingMode = PickingMode.Ignore };
            layer.style.position = Position.Absolute;
            layer.style.left = 0;
            layer.style.top = 0;
            layer.style.right = 0;
            layer.style.bottom = 0;
            _root.Add(layer);
            return layer;
        }

        /// <summary>The panel draws into a texture of this size (a headless run, a capture, or the access drive's
        /// window); the layout follows it. In a windowed player the panel follows the window instead.</summary>
        public void SetWindow(int width, int height)
        {
            if (UiTexture != null && UiTexture.width == width && UiTexture.height == height)
            {
                return;
            }
            var rt = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32) { name = "GameKitUi" };
            rt.Create();
            _panel.targetTexture = rt;
            if (UiTexture != null)
            {
                UiTexture.Release();
            }
            UiTexture = rt;
        }

        /// <summary>The window the panel lays out for: the texture's size, or the screen's.</summary>
        public Vector2Int WindowSize()
        {
            return UiTexture != null ? new Vector2Int(UiTexture.width, UiTexture.height) : new Vector2Int(Screen.width, Screen.height);
        }

        public VisualElement Root => _root;

        // UI Toolkit's own navigation would move focus a second time: the shell moves it from the bindings
        private void OnNavigationMove(NavigationMoveEvent evt)
        {
            string action = evt.direction == NavigationMoveEvent.Direction.Up || evt.direction == NavigationMoveEvent.Direction.Previous ? "ui_up"
                          : evt.direction == NavigationMoveEvent.Direction.Down || evt.direction == NavigationMoveEvent.Direction.Next ? "ui_down"
                          : evt.direction == NavigationMoveEvent.Direction.Left ? "ui_left"
                          : evt.direction == NavigationMoveEvent.Direction.Right ? "ui_right" : null;
            Swallow(evt, action);
        }

        private void OnKeyDown(KeyDownEvent evt)
        {
            if (!ShellInput.Polls && evt.keyCode == KeyCode.F8 && ShellReports.BugKeyEnabled)
            {
                ShellReports.BugReport(this);
            }
            if (!ShellInput.Polls)
            {
                // Nothing to poll (the Input System without its package): keyboard bindings come from the panel's key events
                Dictionary<string, object> bindings = Shell.I.BindingsMap();
                foreach (string action in bindings.Keys)
                {
                    foreach (string b in Bindings.Of(bindings, action))
                    {
                        if (ShellInput.KindOf(b) == "key" && ShellInput.ParseKey(ShellInput.NameOf(b)) == evt.keyCode)
                        {
                            ShellInput.Inject(action, "keyboard");
                        }
                    }
                }
            }
            evt.StopPropagation();
        }

        private void Swallow(EventBase evt, string action)
        {
            if (action != null && !ShellInput.Polls)
            {
                ShellInput.Inject(action, action == "ui_accept" || action == "ui_cancel" ? "pad_other" : null);
            }
            evt.StopPropagation();
            _root.focusController?.IgnoreEvent(evt);
        }

        // ---- the screen stack ------------------------------------------------------------

        public ShellScreen Top()
        {
            return _stack.Count > 0 ? _stack[_stack.Count - 1] : null;
        }

        public string CurrentName()
        {
            ShellScreen top = Top();
            return top != null ? top.Name : World != null ? World.Name : "";
        }

        public void Push(ShellScreen screen)
        {
            ShellScreen below = Top();
            if (below != null)
            {
                below.Root.style.display = DisplayStyle.None;    // one screen at a time; Back shows it again
            }
            _stack.Add(screen);
            _screenLayer.Add(screen.Build());
            screen.FocusFirst();
            Shown(screen);
        }

        public void Replace(ShellScreen screen)
        {
            ClearStack();
            Push(screen);
        }

        public void Back()
        {
            if (_stack.Count == 0)
            {
                return;
            }
            ShellScreen top = _stack[_stack.Count - 1];
            _stack.RemoveAt(_stack.Count - 1);
            top.Root.RemoveFromHierarchy();
            ShellScreen now = Top();
            if (now != null)
            {
                now.Root.style.display = DisplayStyle.Flex;
                now.Root.RemoveFromHierarchy();
                _screenLayer.Add(now.Build());      // rebuilt: values and bindings may have changed underneath
                now.FocusFirst();
                Shown(now);
            }
            else if (World == null)
            {
                ShowTitle();
            }
            else
            {
                Resume();
            }
        }

        public void RebuildAll()
        {
            foreach (ShellScreen screen in _stack)
            {
                string focused = screen.Focused?.Name;
                bool shown = screen.Root.resolvedStyle.display != DisplayStyle.None;
                screen.Root.RemoveFromHierarchy();
                _screenLayer.Add(screen.Build());
                screen.Root.style.display = shown ? DisplayStyle.Flex : DisplayStyle.None;
                Control c = focused != null ? screen.Find(focused) : null;
                if (c != null)
                {
                    screen.Focus(c);
                }
                else
                {
                    screen.FocusFirst();
                }
            }
        }

        public void ShowTitle()
        {
            ClearWorld();
            Replace(new TitleScreen(this));
        }

        public void OpenMainMenu()
        {
            Replace(new MainMenu(this));
        }

        public void OpenSettings()
        {
            Push(new SettingsScreen(this));
        }

        public void OpenCredits()
        {
            Push(new CreditsScreen(this));
        }

        public void OpenHelp()
        {
            Push(new HelpScreen(this));
        }

        public void OpenHistory()
        {
            Push(new HistoryScreen(this));
        }

        /// <summary>Play: the loading screen for a few frames, then the world with no screen over it.</summary>
        public void StartPlay()
        {
            StartWorld(() => new PlayWorld(this));
        }

        /// <summary>The juice demo (main menu, editor and development builds): hit the box (#275).</summary>
        public void StartJuice()
        {
            StartWorld(() => new JuiceWorld(this));
        }

        /// <summary>Any world through the loading screen: make is called once the loading frames are over.</summary>
        public void StartWorld(Func<ShellWorld> make)
        {
            Replace(new LoadingScreen(this));
            _nextWorld = make;
            _loadingFrames = LOADING_FRAMES;
        }

        private void EnterWorld()
        {
            ClearStack();
            Func<ShellWorld> make = _nextWorld ?? (() => new PlayWorld(this));
            ClearWorld();
            World = make();
            World.Build(_worldLayer);
            _paused = false;
            Time.timeScale = Shell.I.GameSpeed();
            WorldShown();
        }

        private void WorldShown()
        {
            ShellReports.CurrentScreen = World.Name;
            ScreenShown?.Invoke(World.Name);
            Debug.Log($"[INFO][shell] screen: {World.Name}");
        }

        public void Pause()
        {
            if (World == null || _paused)
            {
                return;
            }
            _paused = true;
            Time.timeScale = 0f;
            Push(new PauseMenu(this));
        }

        public void Resume()
        {
            ClearStack();
            _paused = false;
            Time.timeScale = World != null ? Shell.I.GameSpeed() : 1f;
            if (World != null)
            {
                ShellReports.CurrentScreen = World.Name;
                ScreenShown?.Invoke(World.Name);
            }
        }

        public void QuitToTitle()
        {
            ShowTitle();
        }

        /// <summary>Quit: a player exits; the editor and a PlayMode test only record the wish (QuitRequested).</summary>
        public void QuitGame()
        {
            QuitRequested = true;
            Debug.Log("[INFO][shell] quit");
            if (!Application.isEditor)
            {
                Application.Quit();
            }
        }

        // ---- focus and narration ---------------------------------------------------------

        public void OnFocusChanged(ShellScreen screen, Control c)
        {
            if (screen == Top() && c != null)
            {
                Narrator.OnFocus(c);
            }
        }

        public void OnValueChanged(ShellScreen screen, Control c)
        {
            Narrator.Tick();
        }

        private void Shown(ShellScreen screen)
        {
            Debug.Log($"[INFO][shell] screen: {screen.Name}");
            ShellReports.CurrentScreen = screen.Name;
            ScreenShown?.Invoke(screen.Name);
            Narrator.OnScreen(screen);
            if (screen.Focused != null)
            {
                Narrator.OnFocus(screen.Focused);
            }
        }

        private void OnSettingsChanged(string section, string key)
        {
            if ((section == "access" || section == "language") && Array.IndexOf(LOOK_KEYS, key) >= 0)
            {
                RebuildAll();
            }
            if (section == "access" && key == "game_speed" && World != null && !_paused)
            {
                Time.timeScale = Shell.I.GameSpeed();
            }
        }

        private void ClearStack()
        {
            foreach (ShellScreen screen in _stack)
            {
                screen.Root.RemoveFromHierarchy();
            }
            _stack.Clear();
        }

        private void ClearWorld()
        {
            _loadingFrames = -1;
            _nextWorld = null;
            if (World != null)
            {
                World.Dispose();
                World = null;
            }
            _paused = false;
            Time.timeScale = 1f;
        }
    }
}

// {{FOOTER}}
