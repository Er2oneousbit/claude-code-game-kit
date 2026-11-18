// ---------------------------------------------------------------------------
// JuiceVectorTests.cs
// Purpose : Runs every case of data/golden/juice.json through the Core juice modules (noise, shake, hitstop,
//           ease, follow camera, input buffer, coyote timer, spring, squash, flash limiter): one test per case.
// Usage   : python tools/dev.py test              (or --filter Juice)
// Notes   : The expected values come from the file at test time (tools/golden_vectors.py writes it); never
//           copy them in here. A case type without a runner fails, so a new vector type cannot be skipped.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the recipe helpers' cases (Feel: impact, float_text,
//           trail; SOP-18 step 4, #170, #164)
// ---------------------------------------------------------------------------
using System.Collections.Generic;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;
using G = {{GAME_SLUG}}.Tests.GoldenVectors;

namespace {{GAME_SLUG}}.Tests
{
    public class JuiceVectorTests
    {
        private const string FILE = "juice.json";

        private static readonly string[] REQUIRED_TYPES =
        {
            "noise", "shake", "hitstop", "ease", "follow", "input_buffer", "coyote", "spring", "squash", "flash_limiter",
            "impact", "float_text", "trail",
        };

        public static IEnumerable<TestCaseData> Cases()
        {
            return G.CaseData(FILE, "Juice");
        }

        [Test]
        public void Juice_EveryRequiredTypeHasCases()
        {
            var seen = new HashSet<string>();
            foreach (object c in G.Cases(FILE))
            {
                seen.Add(G.Str((Dictionary<string, object>)c, "type"));
            }
            foreach (string type in REQUIRED_TYPES)
            {
                Assert.IsTrue(seen.Contains(type), $"{FILE} has no '{type}' case");
            }
        }

        [TestCaseSource(nameof(Cases))]
        public void Juice(int index)
        {
            Dictionary<string, object> c = G.Case(FILE, index);
            double tol = G.Tolerance(FILE);
            string type = G.Str(c, "type");
            switch (type)
            {
                case "noise": RunNoise(c, tol); break;
                case "shake": RunShake(c, tol); break;
                case "hitstop": RunHitstop(c, tol); break;
                case "ease": RunEase(c, tol); break;
                case "follow": RunFollow(c, tol); break;
                case "input_buffer": RunInputBuffer(c, tol); break;
                case "coyote": RunCoyote(c, tol); break;
                case "spring": RunSpring(c, tol); break;
                case "squash": RunSquash(c, tol); break;
                case "flash_limiter": RunFlashLimiter(c, tol); break;
                case "impact": RunImpact(c, tol); break;
                case "float_text": RunFloatText(c, tol); break;
                case "trail": RunTrail(c, tol); break;
                default:
                    Assert.Fail($"unknown case type '{type}' in {FILE}: add a runner for it here");
                    break;
            }
        }

        // ---- Runners: points ([inputs..., expected]) ---------------------------------

        private static void RunNoise(Dictionary<string, object> c, double tol)
        {
            foreach (object p in G.List(c, "points"))
            {
                var pt = (List<object>)p;
                double got = Noise.Value((long)Json.ToNumber(pt[0]), Json.ToNumber(pt[1]), (int)Json.ToNumber(pt[2]));
                G.AssertClose(got, pt[3], tol, $"{G.Str(c, "name")} {Json.Stringify(pt)}");
            }
        }

        private static void RunEase(Dictionary<string, object> c, double tol)
        {
            foreach (object p in G.List(c, "points"))
            {
                var pt = (List<object>)p;
                G.AssertClose(Ease.Apply((string)pt[0], Json.ToNumber(pt[1])), pt[2], tol, $"{G.Str(c, "name")} {Json.Stringify(pt)}");
            }
        }

        private static void RunSquash(Dictionary<string, object> c, double tol)
        {
            foreach (object p in G.List(c, "points"))
            {
                var pt = (List<object>)p;
                var s = Squash.Scale(Json.ToNumber(pt[0]));
                G.AssertClose(new List<object> { s.ScaleX, s.ScaleY }, pt.GetRange(1, 2), tol, $"{G.Str(c, "name")} {Json.Stringify(pt)}");
            }
        }

        private static void RunImpact(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            foreach (object o in G.List(c, "points"))
            {
                var pt = (List<object>)o;
                var r = Feel.Impact(Json.ToNumber(pt[0]), Json.ToNumber(pt[1]), G.Num(p, "hitstop_min"), G.Num(p, "hitstop_max"),
                                    G.Num(p, "trauma_min"), G.Num(p, "trauma_max"), G.Num(p, "flash_at"));
                G.AssertClose(new List<object> { r.Hitstop, r.Trauma, r.Flash }, pt.GetRange(2, 3), tol,
                              $"{G.Str(c, "name")} {Json.Stringify(pt)}");
            }
        }

        private static void RunFloatText(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            foreach (object o in G.List(c, "points"))
            {
                var pt = (List<object>)o;
                var r = Feel.FloatText(Json.ToNumber(pt[0]), G.Num(p, "life"), G.Num(p, "rise"), G.Num(p, "pop_s"));
                G.AssertClose(new List<object> { r.Dy, r.Scale, r.Alpha, r.Done }, pt.GetRange(1, 4), tol,
                              $"{G.Str(c, "name")} {Json.Stringify(pt)}");
            }
        }

        // ---- Runners: scripted steps (call, inputs, expect) -----------------------------

        private static void RunTrail(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            var pts = new List<double[]>();
            Steps(c, (st, call, where) =>
            {
                if (call == "push")
                {
                    pts = Feel.TrailPush(pts, G.Num(st, "x"), G.Num(st, "y"), G.Num(p, "spacing"), G.Num(p, "max_len"));
                }
                else if (call == "shrink")
                {
                    pts = Feel.TrailShrink(pts, G.Num(st, "amount"));
                }
                else
                {
                    return false;
                }
                var listed = new List<object>();
                foreach (double[] q in pts)
                {
                    listed.Add(new List<object> { q[0], q[1] });
                }
                G.AssertClose(G.Make("points", listed, "length", Feel.TrailLength(pts)), G.Obj(st, "expect"), tol, where);
                return true;
            });
        }

        private static void RunShake(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            var shake = new Shake(G.Num(p, "max_offset"), G.Num(p, "max_angle"), G.Num(p, "decay"), G.Num(p, "frequency"),
                                  (long)G.Num(p, "seed"));
            Steps(c, (st, call, where) =>
            {
                if (call == "add_trauma")
                {
                    shake.AddTrauma(G.Num(st, "a"));
                }
                else if (call == "update")
                {
                    var s = shake.Update(G.Num(st, "dt"), G.Num(st, "intensity"));
                    G.AssertClose(G.Make("x", s.X, "y", s.Y, "angle", s.Angle, "trauma", shake.Trauma), G.Obj(st, "expect"), tol, where);
                }
                else
                {
                    return false;
                }
                return true;
            });
        }

        private static void RunHitstop(Dictionary<string, object> c, double tol)
        {
            var hitstop = new Hitstop(G.Num(G.Obj(c, "params"), "max_s"));
            Steps(c, (st, call, where) =>
            {
                if (call == "hit")
                {
                    hitstop.Hit(G.Num(st, "duration"));
                }
                else if (call == "scaled_dt")
                {
                    double dt = hitstop.ScaledDt(G.Num(st, "dt"));
                    G.AssertClose(G.Make("dt", dt, "remaining", hitstop.Remaining), G.Obj(st, "expect"), tol, where);
                }
                else
                {
                    return false;
                }
                return true;
            });
        }

        private static void RunFollow(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            var follow = new FollowCamera(G.Num(p, "deadzone_w"), G.Num(p, "deadzone_h"), G.Num(p, "lookahead"),
                                          G.Num(p, "smoothing"), G.Num(p, "x"), G.Num(p, "y"));
            Steps(c, (st, call, where) =>
            {
                if (call != "update")
                {
                    return false;
                }
                var pos = follow.Update(G.Num(st, "dt"), G.Num(st, "tx"), G.Num(st, "ty"), G.Num(st, "vx"), G.Num(st, "vy"));
                G.AssertClose(G.Make("x", pos.X, "y", pos.Y), G.Obj(st, "expect"), tol, where);
                return true;
            });
        }

        private static void RunInputBuffer(Dictionary<string, object> c, double tol)
        {
            var buffer = new InputBuffer(G.Num(G.Obj(c, "params"), "window_s"));
            Steps(c, (st, call, where) =>
            {
                if (call == "press")
                {
                    buffer.Press(G.Str(st, "action"));
                }
                else if (call == "update")
                {
                    buffer.Update(G.Num(st, "dt"));
                }
                else if (call == "consume")
                {
                    G.AssertClose(G.Make("result", buffer.Consume(G.Str(st, "action"))), G.Obj(st, "expect"), tol, where);
                }
                else
                {
                    return false;
                }
                return true;
            });
        }

        private static void RunCoyote(Dictionary<string, object> c, double tol)
        {
            var coyote = new CoyoteTimer(G.Num(G.Obj(c, "params"), "window_s"));
            Steps(c, (st, call, where) =>
            {
                if (call == "update")
                {
                    coyote.Update(G.Num(st, "dt"), G.Bool(st, "on_floor"));
                }
                else if (call == "consume")
                {
                    coyote.Consume();
                }
                else if (call == "can_jump")
                {
                    G.AssertClose(G.Make("result", coyote.CanJump()), G.Obj(st, "expect"), tol, where);
                }
                else
                {
                    return false;
                }
                return true;
            });
        }

        private static void RunSpring(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            var spring = new Spring(G.Num(p, "frequency"), G.Num(p, "damping"))
            {
                X = G.Num(p, "x"), V = G.Num(p, "v"), Target = G.Num(p, "target"),
            };
            Steps(c, (st, call, where) =>
            {
                if (call != "update")
                {
                    return false;
                }
                double x = spring.Update(G.Num(st, "dt"));
                G.AssertClose(G.Make("x", x, "v", spring.V), G.Obj(st, "expect"), tol, where);
                return true;
            });
        }

        private static void RunFlashLimiter(Dictionary<string, object> c, double tol)
        {
            var p = G.Obj(c, "params");
            var limiter = new FlashLimiter((int)G.Num(p, "max_flashes"), G.Num(p, "window_s"));
            Steps(c, (st, call, where) =>
            {
                if (call != "request")
                {
                    return false;
                }
                G.AssertClose(G.Make("result", limiter.Request(G.Num(st, "now"))), G.Obj(st, "expect"), tol, where);
                return true;
            });
        }

        // Runs each step through run(step, call, where); run returns false for a call it does not know
        private static void Steps(Dictionary<string, object> c, System.Func<Dictionary<string, object>, string, string, bool> run)
        {
            List<object> steps = G.List(c, "steps");
            Assert.IsNotEmpty(steps, $"{G.Str(c, "name")}: no steps");
            for (int i = 0; i < steps.Count; i++)
            {
                var st = (Dictionary<string, object>)steps[i];
                string call = G.Str(st, "call");
                string where = $"{G.Str(c, "name")} step {i} ({call})";
                if (!run(st, call, where))
                {
                    Assert.Fail($"{where}: unknown call '{call}' for a {G.Str(c, "type")} case");
                }
            }
        }
    }
}

// {{FOOTER}}
