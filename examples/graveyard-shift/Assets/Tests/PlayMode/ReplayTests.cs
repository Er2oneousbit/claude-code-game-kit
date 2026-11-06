// ---------------------------------------------------------------------------
// ReplayTests.cs
// Purpose : PlayMode regression tests for a night that replays (issue #160): the same bot night played twice must
//           give the same positions and catches to the last digit. The issue: a millimeter between two ghosts that
//           passed close was said to move the always-lit bot's catches between runs (12 or 14 on the hand-made yard).
// Usage   : python tools/dev.py smoke --filter Smoke_R1[01]
//           GRAVEYARD_FRAMETRACE=Logs/trace python tools/dev.py smoke --filter Smoke_R10   (the per-frame records as files)
// Notes   : R10 is the night the issue asks for: the always-lit bot twice on one seed, every frame compared.
//           R11 is the lab for the suspected trigger: two ghosts swap ends of a straight 13 m patrol leg on the
//           hand-made yard, so they must pass head-on with the NavMeshAgent's obstacle avoidance deciding who steps
//           aside; repeated in one process, each pass is compared frame by frame with the first.
//           Neither failed on 6000.6.6f1 with AI Navigation 2.0.16 (see HOW_IT_WAS_MADE, "Later: the night that
//           replays after all"); they are here so a change that breaks the replay shows up in smoke.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using graveyard_shift.Core;
using graveyard_shift.Game;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.AI;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace graveyard_shift.Tests
{
    public class ReplayTests
    {
        private const string Scene = "Graveyard";
        private const int Fps = 60;
        private const int NightSeed = 7;              // the hand-made night whose two ghosts pass closest (0.91 m, frame 17956)
        private const int MaxFrames = Fps * 400;      // longer than a night (300 s): a stuck bot fails, never hangs
        private const int Passes = 4;                 // how many times the same pass is played
        private const int PassFrames = Fps * 8;       // 8 s: 13 m at patrol speed takes about 6.5 s
        private static readonly V2 LegA = new V2(-26f, -24f);   // the hand-made yard's first patrol leg (Level.Graveyard)
        private static readonly V2 LegB = new V2(-13f, -24f);
        private static string SavePath => Path.Combine(Application.temporaryCachePath, "replay_save.json");

        [TearDown]
        public void Reset()
        {
            Time.captureFramerate = 0;
            GraveyardGame.Options = null;
        }

        private static string F(float v) => v.ToString("R", CultureInfo.InvariantCulture);

        private static string Record(GhostAgent g)
        {
            var a = g.GetComponent<NavMeshAgent>();
            var p = g.transform.position;
            return $"{F(p.x)} {F(p.y)} {F(p.z)} {F(a.velocity.x)} {F(a.velocity.z)}{(a.pathPending ? " P" : "")}{(a.hasPath ? " H" : "")}";
        }

        // The always-lit bot plays one hand-made night twice (the seed whose two ghosts pass closest, 0.91 m apart,
        // with every catch of the night) and the second night must match the first frame for frame: every ghost's
        // position and path state, the keeper, the catches. A night runs about 18 s real time at 60 captured frames.
        [UnityTest]
        public IEnumerator Smoke_R10_AnAlwaysLitNightReplaysExactly()
        {
            var traces = new List<FrameTrace>();
            var catches = new List<int>();
            for (int run = 0; run < 2; run++)
            {
                GraveyardGame.Options = new LaunchOptions
                {
                    Bot = BotMode.AlwaysLit, Seed = NightSeed, HandMadeYard = true, Difficulty = Core.Difficulty.Easy, SavePath = SavePath,
                };
                Time.captureFramerate = Fps;
                yield return SceneManager.LoadSceneAsync(Scene);
                var trace = FrameTrace.Begin($"replay{run}-lit-seed{NightSeed}");
                int frames = 0;
                while (GraveyardGame.Current == null || GraveyardGame.Current.Night == null ||
                       GraveyardGame.Current.Outcome == Outcome.Playing)
                {
                    if (++frames > MaxFrames) break;
                    if (GraveyardGame.Current?.Night != null && GraveyardGame.Current.Keeper != null) trace.Frame(GraveyardGame.Current);
                    yield return null;
                }
                trace.End();
                var game = GraveyardGame.Current;
                Assert.AreNotEqual(Outcome.Playing, game.Outcome, $"run {run}: the night never ended in {MaxFrames} frames");
                traces.Add(trace);
                catches.Add(game.Night.Catches);
                Debug.Log($"[INFO][test] replay run {run}: lit seed {NightSeed} {game.Outcome}, souls {game.Night.Collected}, caught {catches[run]}x, {trace.Lines.Count} frames");
            }
            int first = FrameTrace.FirstDifference(traces[0], traces[1]);
            Debug.Log($"[INFO][test] replay: catches {catches[0]} and {catches[1]}, " + (first < 0 ? "every frame identical" : $"the nights part at frame {first}"));
            Assert.AreEqual(catches[0], catches[1], "the always-lit bot's catches changed between two runs of the same night");
            Assert.AreEqual(-1, first, first < 0 ? "" : $"the night did not replay: frame {first}\n  run 0: {traces[0].Lines[first]}\n  run 1: {traces[1].Lines[first]}");
        }

        // Two ghosts walk a straight leg toward each other and must pass; the pass is played Passes times on one
        // scene load and every replay must match the first frame for frame.
        [UnityTest]
        public IEnumerator Smoke_R11_TwoGhostsPassingEachOtherReplayExactly()
        {
            GraveyardGame.Options = new LaunchOptions { Seed = 0, HandMadeYard = true, Difficulty = Core.Difficulty.Easy, SavePath = SavePath };
            Time.captureFramerate = Fps;
            yield return SceneManager.LoadSceneAsync(Scene);
            yield return null;
            var game = GraveyardGame.Current;
            game.enabled = false;                      // only this test moves the ghosts
            var a = game.Ghosts[0];
            var b = game.Ghosts[1];
            foreach (var g in game.Ghosts) g.GetComponent<NavMeshAgent>().isStopped = true;
            float speed = game.Tuning.PatrolSpeed;

            var runs = new List<List<string>>();
            var closest = new List<float>();
            for (int pass = 0; pass < Passes; pass++)
            {
                Assert.IsTrue(a.GetComponent<NavMeshAgent>().Warp(LevelBuilder.ToWorld(LegA)), "ghost A on the leg");
                Assert.IsTrue(b.GetComponent<NavMeshAgent>().Warp(LevelBuilder.ToWorld(LegB)), "ghost B on the leg");
                a.transform.rotation = Quaternion.LookRotation(Vector3.right);
                b.transform.rotation = Quaternion.LookRotation(Vector3.left);
                yield return null;
                var frames = new List<string>(PassFrames);
                float nearest = float.MaxValue;
                for (int f = 0; f < PassFrames; f++)
                {
                    a.Drive(LegB, speed);
                    b.Drive(LegA, speed);
                    yield return null;
                    frames.Add($"{Record(a)} | {Record(b)}");
                    nearest = Mathf.Min(nearest, Vector3.Distance(a.transform.position, b.transform.position));
                }
                a.Drive(LegB, 0f);
                b.Drive(LegA, 0f);
                runs.Add(frames);
                closest.Add(nearest);
            }
            var report = new List<string>();
            var different = new List<string>();
            for (int pass = 1; pass < Passes; pass++)
            {
                int first = -1;
                for (int f = 0; f < PassFrames; f++)
                {
                    if (runs[0][f] != runs[pass][f]) { first = f; break; }
                }
                report.Add($"pass {pass} closest {closest[pass]:0.000} m, " + (first < 0 ? "identical" : $"parts at frame {first}"));
                if (first >= 0) different.Add($"pass {pass} parts from pass 0 at frame {first}:\n  0: {runs[0][first]}\n  {pass}: {runs[pass][first]}");
            }
            Debug.Log($"[INFO][test] two ghosts head-on, pass 0 closest {closest[0]:0.000} m; " + string.Join("; ", report));
            string dir = System.Environment.GetEnvironmentVariable("GRAVEYARD_FRAMETRACE");
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
                File.WriteAllLines(Path.Combine(dir, "headon-pass0.txt"), runs[0]);   // to compare across processes
            }
            Assert.Less(closest[0], 2f, "the ghosts passed each other (avoidance had to act)");
            Assert.IsEmpty(different, "the same pass did not replay:\n" + string.Join("\n", different));
        }
    }
}
