// ---------------------------------------------------------------------------
// Hud.cs
// Purpose : The title screen (difficulty, Start) and the HUD: souls, time to dawn, lantern, best time, the seed and
//           difficulty, version, start and end messages, and a
//           mark over each ghost (? suspicious or searching, ! hunting). With --debug-ai, each ghost's
//           state and the bot's reason.
// Usage   : added by GraveyardGame at start
// Notes   : Immediate-mode GUI (OnGUI): no UI package or scene objects. A 1280x720 layout scaled to fit inside the
//           screen (the smaller of the two ratios), so an ultrawide gets a wider layout, not a taller one.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using graveyard_shift.Core;
using UnityEngine;

namespace graveyard_shift.Game
{
    public sealed class Hud : MonoBehaviour
    {
        private const float RefWidth = 1280f;
        private const float RefHeight = 720f;
        private float _w = RefWidth;   // the layout's width this frame, in reference pixels (wider on an ultrawide)
        private GUIStyle _big;
        private GUIStyle _small;
        private GUIStyle _center;
        private GUIStyle _mark;
        private GUIStyle _blurb;
        private Texture2D _panel;
        private int _selected = -1;   // the title screen's highlighted difficulty
        private bool _seedLogged;

        // The seed label at the bottom of the screen
        public static string SeedText(int seed, bool handMade) => handMade ? $"SEED {seed}  (the hand-made yard)" : $"SEED {seed}";

        // What OnGUI draws as the seed label, kept up to date every frame, so a batch-mode test (where Unity never
        // calls OnGUI) can read it from the live HUD
        public string SeedLabel { get; private set; }

        private void Update()
        {
            var game = GraveyardGame.Current;
            if (game != null && game.Yard != null) SeedLabel = SeedText(game.NightSeed, game.Yard.HandMade);
        }

        private void Styles()
        {
            if (_big != null) return;
            _panel = new Texture2D(1, 1);
            _panel.SetPixel(0, 0, new Color(0.06f, 0.07f, 0.12f, 0.8f));
            _panel.Apply();
            _big = new GUIStyle(GUI.skin.label) { fontSize = 26, fontStyle = FontStyle.Bold };
            _big.normal.textColor = new Color(0.98f, 0.96f, 0.9f);
            _small = new GUIStyle(_big) { fontSize = 16, fontStyle = FontStyle.Normal };
            _center = new GUIStyle(_big) { alignment = TextAnchor.MiddleCenter, fontSize = 22, wordWrap = true };
            _mark = new GUIStyle(_big) { fontSize = 34, alignment = TextAnchor.MiddleCenter };
            _blurb = new GUIStyle(_small) { wordWrap = true, alignment = TextAnchor.MiddleLeft };
        }

        private void OnGUI()
        {
            var game = GraveyardGame.Current;
            if (game == null || game.Night == null) return;
            Styles();
            float s = Mathf.Min(Screen.width / RefWidth, Screen.height / RefHeight);
            _w = Screen.width / s;
            GUI.matrix = Matrix4x4.Scale(new Vector3(s, s, 1f));
            float h = Screen.height / s;
            var night = game.Night;
            if (game.OnTitle)
            {
                DrawTitle(game, h);
                return;
            }

            GUI.DrawTexture(new Rect(12, 12, 330, 112), _panel);
            GUI.Label(new Rect(24, 18, 320, 34), $"SOULS {night.Collected} / {night.SoulCount}", _big);
            int left = Mathf.Max(0, Mathf.CeilToInt(night.TimeLeft));
            var timeStyle = new GUIStyle(_big);
            if (night.Started && night.TimeLeft <= game.Tuning.LowTimeSeconds) timeStyle.normal.textColor = GhostAgent.Hunting;
            GUI.Label(new Rect(24, 50, 320, 34), $"DAWN IN {left / 60}:{left % 60:00}", timeStyle);
            GUI.Label(new Rect(24, 86, 320, 26), game.Keeper.LanternLit ? "LANTERN LIT  (seen from afar, fast)" : "LANTERN OUT  (hidden, slow)", _small);
            if (game.Save.bestEscapeSeconds > 0f)
                GUI.Label(new Rect(_w - 260, 14, 250, 26), $"BEST ESCAPE {game.Save.bestEscapeSeconds:0.0} s", _small);
            GUI.Label(new Rect(_w - 120, h - 30, 110, 24), $"v{Application.version}", _small);
            // Tonight's seed: --seed N replays this exact yard (generated nights); seed 0 is the hand-made one
            string yard = SeedLabel ?? SeedText(game.NightSeed, game.Yard.HandMade);
            GUI.Label(new Rect(_w - 420, h - 30, 290, 24), yard, _small);
            GUI.Label(new Rect(24, h - 30, 400, 24), $"{game.Difficulty.Level.ToString().ToUpperInvariant()}  (Esc: title screen)", _small);
            if (!_seedLogged && Event.current.type == EventType.Repaint)
            {
                _seedLogged = true;   // once per night, so tests can see the label was really drawn
                GameLog.Info("hud", $"SEED_SHOWN \"{yard}\"");
            }

            // Marks over the ghosts (pillar 2): ? for suspicious or searching, ! for hunting
            var cam = Camera.main;
            foreach (var g in game.Ghosts)
            {
                string mark = g.Brain.State == GhostState.Hunt ? "!" :
                              g.Brain.State == GhostState.Suspicious || g.Brain.State == GhostState.Search ? "?" : null;
                if (game.Launch.DebugAi) mark = $"{mark} {g.Brain.State}";
                if (string.IsNullOrEmpty(mark) || cam == null) continue;
                Vector3 p = cam.WorldToScreenPoint(g.transform.position + Vector3.up * 2.6f);
                if (p.z < 0f) continue;
                _mark.normal.textColor = GhostAgent.GlowColor(g.Brain.State);
                GUI.Label(new Rect(p.x / s - 80, (Screen.height - p.y) / s - 20, 160, 40), mark, _mark);
            }
            if (game.Launch.DebugAi && game.Bot != null)
                GUI.Label(new Rect(24, 130, 400, 24), $"bot {game.Bot.Mode}: {game.Bot.Reason}", _small);

            // the end of the night: the screen darkens (EndSequence), then the end card shows
            var end = game.End;
            if (end != null && end.Fade > 0f)
            {
                var before = GUI.color;
                GUI.color = new Color(0f, 0f, 0f, end.Fade);
                GUI.DrawTexture(new Rect(0, 0, _w, h), Texture2D.whiteTexture);
                GUI.color = before;
            }
            bool card = end == null || end.CardVisible;

            string msg = null;
            switch (night.Outcome)
            {
                case Outcome.Escaped: if (card) msg = $"YOU ESCAPED WITH ALL SOULS IN {night.Elapsed:0.0} S\nPress R for another night"; break;
                case Outcome.Dawn: if (card) msg = "DAWN BROKE BEFORE YOU GOT OUT\nPress R to try again"; break;
                default:
                    if (game.CaughtMessage > 0f)
                        msg = "CAUGHT! You wake at the gate.\nYour last soul slipped back to its grave.";
                    else if (!night.Started && game.Save.settings.showHints)
                        msg = $"Collect the {night.SoulCount} lost souls and leave by the gate before dawn.\nWASD to move, SPACE to light or hide the lantern. Lit: fast, but ghosts see you from afar.";
                    else if (night.AllCollected) msg = "THE GATE IS OPEN";
                    break;
            }
            if (msg != null)
            {
                var r = new Rect(_w / 2 - 420, h - 120, 840, 96);
                GUI.DrawTexture(r, _panel);
                GUI.Label(r, msg, _center);
            }
        }

        // The title screen: the name, the four difficulties (mouse, arrows or W/S, Enter) and Start
        private void DrawTitle(GraveyardGame game, float h)
        {
            if (_selected < 0) _selected = (int)game.Difficulty.Level;
            var e = Event.current;
            if (e.type == EventType.KeyDown)
            {
                if (e.keyCode == KeyCode.UpArrow || e.keyCode == KeyCode.W) _selected = (_selected + 3) % 4;
                if (e.keyCode == KeyCode.DownArrow || e.keyCode == KeyCode.S) _selected = (_selected + 1) % 4;
                if (e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter || e.keyCode == KeyCode.Space)
                {
                    game.StartNight((Difficulty)_selected);
                    return;
                }
            }

            GUI.DrawTexture(new Rect(0, 0, _w, h), _panel);
            var title = new GUIStyle(_center) { fontSize = 64, fontStyle = FontStyle.Bold };
            GUI.Label(new Rect(0, h * 0.12f, _w, 80), "GRAVEYARD SHIFT", title);
            GUI.Label(new Rect(0, h * 0.12f + 78, _w, 30), "Gather the lost souls and slip out the gate before dawn.", _center);

            float y = h * 0.12f + 140;
            for (int i = 0; i < 4; i++)
            {
                var d = DifficultySettings.For((Difficulty)i);
                var row = new Rect(_w / 2 - 380, y + i * 64, 760, 56);
                if (i == _selected) GUI.DrawTexture(row, _panel);
                var name = new GUIStyle(_big) { fontSize = 28 };
                name.normal.textColor = i == _selected ? GhostAgent.Wary : _big.normal.textColor;
                if (GUI.Button(new Rect(row.x, row.y, 200, 56), (i == _selected ? "> " : "  ") + d.Level.ToString().ToUpperInvariant(), name))
                    _selected = i;
                GUI.Label(new Rect(row.x + 210, row.y, 540, 56), d.Blurb, _blurb);
            }

            var start = new Rect(_w / 2 - 160, y + 4 * 64 + 20, 320, 56);
            GUI.DrawTexture(start, _panel);
            if (GUI.Button(start, "START THE NIGHT", _center)) game.StartNight((Difficulty)_selected);
            GUI.Label(new Rect(0, h - 80, _w, 60), "Arrows or W/S to choose, Enter to start.  In the night: WASD move, SPACE lantern, R restart, Esc this screen.\nAlt+Enter: window or fullscreen.", _center);
        }
    }
}
