// ---------------------------------------------------------------------------
// GoldenVectors.cs
// Purpose : Test helpers for the golden vectors: load data/golden/<file>.json from disk at test time, hand
//           NUnit one test per case, and compare results with the expected values structurally.
// Usage   : [TestCaseSource(nameof(Cases))] public void Vector(int index) { var c = GoldenVectors.Case(FILE, index); ... }
//           static IEnumerable<TestCaseData> Cases() => GoldenVectors.CaseData(FILE, "Juice");
//           GoldenVectors.AssertClose(actual, expected, GoldenVectors.Tolerance(FILE), "case step 3");
// Notes   : The vectors are written by tools/golden_vectors.py (the reference implementation) and shared by
//           every engine of the kit: never copy expected values into a test. EditMode runs with the project
//           root as the working directory, so data/golden is found from there. Comparison rules: numbers
//           within the file's absolute tolerance (an int 0 equals 0.0), arrays in order, objects as key sets,
//           everything else exactly. A file that cannot be read becomes one failing test, not zero tests.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public static class GoldenVectors
    {
        // ---- Tunables ------------------------------------------------------------
        public const string GOLDEN_DIR = "data/golden";    // relative to the project root
        private const int BROKEN_FILE = -1;                // the index of the one test a broken file becomes

        private static readonly Dictionary<string, Dictionary<string, object>> LOADED =
            new Dictionary<string, Dictionary<string, object>>();
        private static readonly Dictionary<string, string> LOAD_ERRORS = new Dictionary<string, string>();

        public static string PathOf(string file)
        {
            return Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), GOLDEN_DIR, file));
        }

        /// <summary>The parsed file (cached). Throws with a readable reason when it is missing or malformed.</summary>
        public static Dictionary<string, object> Load(string file)
        {
            if (LOADED.TryGetValue(file, out Dictionary<string, object> root))
            {
                return root;
            }
            string path = PathOf(file);
            if (!File.Exists(path))
            {
                throw new FileNotFoundException($"{path} not found (the kit ships it at data/golden; restore it from the kit)");
            }
            root = Json.Parse(File.ReadAllText(path, Encoding.UTF8)) as Dictionary<string, object>;
            if (root == null || !(root.TryGetValue("cases", out object cases) && cases is List<object>)
                || !(root.TryGetValue("tolerance", out object tol) && Json.IsNumber(tol)))
            {
                throw new InvalidDataException($"{path} is not a golden vector file (needs \"cases\" and \"tolerance\")");
            }
            LOADED[file] = root;
            return root;
        }

        public static double Tolerance(string file)
        {
            return Json.ToNumber(Load(file)["tolerance"]);
        }

        public static List<object> Cases(string file)
        {
            return (List<object>)Load(file)["cases"];
        }

        /// <summary>One NUnit case per vector case, named Prefix_00_type_name; a broken file gives one failing case.</summary>
        public static IEnumerable<TestCaseData> CaseData(string file, string prefix)
        {
            var data = new List<TestCaseData>();
            try
            {
                List<object> cases = Cases(file);
                for (int i = 0; i < cases.Count; i++)
                {
                    var c = cases[i] as Dictionary<string, object>;
                    string type = c != null && c.TryGetValue("type", out object t) ? t as string : null;
                    string name = c != null && c.TryGetValue("name", out object n) ? n as string : null;
                    data.Add(new TestCaseData(i).SetName(Safe($"{prefix}_{i:00}_{type ?? "notype"}_{name ?? "noname"}")));
                }
            }
            catch (Exception e)
            {
                LOAD_ERRORS[file] = e.Message;
                data.Add(new TestCaseData(BROKEN_FILE).SetName(Safe($"{prefix}_FileUnreadable")));
            }
            return data;
        }

        /// <summary>The case at index (fails the test if the file was unreadable at discovery).</summary>
        public static Dictionary<string, object> Case(string file, int index)
        {
            if (index == BROKEN_FILE)
            {
                Assert.Fail(LOAD_ERRORS.TryGetValue(file, out string why) ? why : $"{file} could not be read");
            }
            var c = Cases(file)[index] as Dictionary<string, object>;
            Assert.IsNotNull(c, $"{file} case {index} is not an object");
            return c;
        }

        // ---- Field access with readable failures ------------------------------------

        public static object Get(Dictionary<string, object> obj, string key)
        {
            if (obj == null || !obj.ContainsKey(key))
            {
                Assert.Fail($"vector field '{key}' is missing");
            }
            return obj[key];
        }

        public static double Num(Dictionary<string, object> obj, string key)
        {
            object v = Get(obj, key);
            Assert.IsTrue(Json.IsNumber(v), $"vector field '{key}' is not a number");
            return Json.ToNumber(v);
        }

        public static string Str(Dictionary<string, object> obj, string key)
        {
            return Get(obj, key) as string;            // null for a JSON null (a missing save file)
        }

        public static bool Bool(Dictionary<string, object> obj, string key)
        {
            object v = Get(obj, key);
            Assert.IsTrue(v is bool, $"vector field '{key}' is not a bool");
            return (bool)v;
        }

        public static Dictionary<string, object> Obj(Dictionary<string, object> obj, string key)
        {
            var v = Get(obj, key) as Dictionary<string, object>;
            Assert.IsNotNull(v, $"vector field '{key}' is not an object");
            return v;
        }

        public static List<object> List(Dictionary<string, object> obj, string key)
        {
            var v = Get(obj, key) as List<object>;
            Assert.IsNotNull(v, $"vector field '{key}' is not an array");
            return v;
        }

        /// <summary>An object from key/value pairs: Make("x", 1.0, "y", 2.0).</summary>
        public static Dictionary<string, object> Make(params object[] pairs)
        {
            var obj = new Dictionary<string, object>();
            for (int i = 0; i + 1 < pairs.Length; i += 2)
            {
                obj[(string)pairs[i]] = pairs[i + 1];
            }
            return obj;
        }

        // ---- Comparison ---------------------------------------------------------------

        /// <summary>The first difference between actual and expected as "path: why", or null when they match.</summary>
        public static string Diff(object actual, object expected, double tol, string path = "$")
        {
            if (Json.IsNumber(expected))
            {
                if (!Json.IsNumber(actual))
                {
                    return $"{path}: expected number {Show(expected)}, got {Show(actual)}";
                }
                double a = Json.ToNumber(actual), e = Json.ToNumber(expected);
                return Math.Abs(a - e) <= tol ? null : $"{path}: expected {Show(e)}, got {Show(a)} (tolerance {tol})";
            }
            if (expected is IDictionary expectedObj)
            {
                if (!(actual is IDictionary actualObj))
                {
                    return $"{path}: expected an object, got {Show(actual)}";
                }
                List<string> ek = SortedKeys(expectedObj), ak = SortedKeys(actualObj);
                if (string.Join("\u0000", ek) != string.Join("\u0000", ak))
                {
                    return $"{path}: keys differ: expected [{string.Join(", ", ek)}], got [{string.Join(", ", ak)}]";
                }
                foreach (string k in ek)
                {
                    string d = Diff(actualObj[k], expectedObj[k], tol, path + "." + k);
                    if (d != null)
                    {
                        return d;
                    }
                }
                return null;
            }
            if (expected is IList expectedList)
            {
                if (!(actual is IList actualList))
                {
                    return $"{path}: expected an array, got {Show(actual)}";
                }
                if (actualList.Count != expectedList.Count)
                {
                    return $"{path}: expected {expectedList.Count} items, got {actualList.Count}: {Show(actual)}";
                }
                for (int i = 0; i < expectedList.Count; i++)
                {
                    string d = Diff(actualList[i], expectedList[i], tol, $"{path}[{i}]");
                    if (d != null)
                    {
                        return d;
                    }
                }
                return null;
            }
            if (expected == null)
            {
                return actual == null ? null : $"{path}: expected null, got {Show(actual)}";
            }
            return Equals(actual, expected) ? null : $"{path}: expected {Show(expected)}, got {Show(actual)}";
        }

        /// <summary>Fails the test with the first difference.</summary>
        public static void AssertClose(object actual, object expected, double tol, string where)
        {
            string d = Diff(actual, expected, tol);
            if (d != null)
            {
                Assert.Fail($"{where}: {d}");
            }
        }

        private static List<string> SortedKeys(IDictionary obj)
        {
            var keys = new List<string>();
            foreach (object k in obj.Keys)
            {
                keys.Add(k as string ?? "");
            }
            keys.Sort(StringComparer.Ordinal);
            return keys;
        }

        private static string Show(object value)
        {
            try
            {
                return Json.Stringify(value);
            }
            catch (ArgumentException)
            {
                return value.ToString();
            }
        }

        // Test names with only letters, digits and _ (dots and commas confuse the runner's tree and filters)
        private static string Safe(string name)
        {
            var sb = new StringBuilder(name.Length);
            foreach (char c in name)
            {
                sb.Append(c < 128 && char.IsLetterOrDigit(c) ? c : '_');
            }
            return sb.ToString();
        }
    }
}

// {{FOOTER}}
