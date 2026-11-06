// ---------------------------------------------------------------------------
// FrameTrace.cs
// Purpose : A per-frame record of a bot night (the keeper, every ghost's position, state and path), so two runs of
//           the same night can be compared to the first frame where they part (issue #160: a night that did not
//           replay). In memory for the repeatability test; to a file when GRAVEYARD_FRAMETRACE names a folder.
// Usage   : var trace = FrameTrace.Begin(game, "lit-seed6");   each frame: trace.Frame(game);   trace.End();
//           FrameTrace.FirstDifference(a, b) -> -1 when identical, else the first differing frame
// Notes   : Positions are written with "R" (every digit), so a millimeter shows. The file is one line per frame:
//           frame, game time, physics time, then the compared part: K keeper x z lantern catches souls, and per
//           ghost: id x z state (P pending, H has a path) vx vz.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using graveyard_shift.Game;
using UnityEngine;
using UnityEngine.AI;

namespace graveyard_shift.Tests
{
    public sealed class FrameTrace
    {
        private static readonly string Dir = System.Environment.GetEnvironmentVariable("GRAVEYARD_FRAMETRACE");

        public readonly List<string> Lines = new List<string>();
        private StreamWriter _file;
        private int _frame;
        private static int _nights;   // traces of this process so far: the file name says which night of the run it was

        public static FrameTrace Begin(string name)
        {
            var t = new FrameTrace();
            if (!string.IsNullOrEmpty(Dir))
            {
                Directory.CreateDirectory(Dir);
                t._file = new StreamWriter(Path.Combine(Dir, $"{_nights++:00}-{name}.txt"), false, new UTF8Encoding(false));
            }
            return t;
        }

        private static string F(float v) => v.ToString("R", CultureInfo.InvariantCulture);

        // Lines holds what must replay (from the keeper on); the file also carries the frame and the clocks, which
        // differ between runs with the load (Time.time keeps counting across scenes, and the physics clock's phase
        // against the frames depends on real time spent before captureFramerate took hold).
        public void Frame(GraveyardGame game)
        {
            var sb = new StringBuilder(256);
            sb.Append("K ").Append(F(game.Keeper.transform.position.x)).Append(' ').Append(F(game.Keeper.transform.position.z));
            sb.Append(game.Keeper.LanternLit ? " lit" : " out");
            sb.Append(" c").Append(game.Night.Catches).Append(" s").Append(game.Night.Collected);
            foreach (var g in game.Ghosts)
            {
                var a = g.GetComponent<NavMeshAgent>();
                sb.Append(" | G").Append(g.Id).Append(' ').Append(F(g.transform.position.x)).Append(' ').Append(F(g.transform.position.z));
                sb.Append(' ').Append(g.Brain.State).Append(a.pathPending ? " P" : " -").Append(a.hasPath ? "H" : "-");
                sb.Append(' ').Append(F(a.velocity.x)).Append(' ').Append(F(a.velocity.z));
            }
            string line = sb.ToString();
            Lines.Add(line);
            _file?.WriteLine($"{_frame} {F(Time.time)} {F(Time.fixedTime)} {line}");
            _frame++;
        }

        public void End()
        {
            _file?.Dispose();
            _file = null;
        }

        // The first frame whose record differs between two traces, or -1 when they match to the last digit
        public static int FirstDifference(FrameTrace a, FrameTrace b)
        {
            int n = Mathf.Min(a.Lines.Count, b.Lines.Count);
            for (int i = 0; i < n; i++)
            {
                if (a.Lines[i] != b.Lines[i]) return i;
            }
            return a.Lines.Count == b.Lines.Count ? -1 : n;
        }
    }
}
