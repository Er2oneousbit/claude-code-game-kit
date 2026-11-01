// ---------------------------------------------------------------------------
// JsonTests.cs
// Purpose : EditMode tests for Core.Json: the value tree it reads, what strict JSON it refuses (the same
//           texts Python's json and JavaScript's JSON.parse refuse), and that the writer round-trips.
// Usage   : python tools/dev.py test              (or --filter Json)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using NUnit.Framework;
using {{GAME_SLUG}}.Core;

namespace {{GAME_SLUG}}.Tests
{
    public class JsonTests
    {
        [Test]
        public void Json_ReadsTheValueTree()
        {
            var v = (Dictionary<string, object>)Json.Parse(" {\"a\": [1, 2.5, -3e2], \"b\": {\"c\": null}, \"d\": true, \"e\": \"x\"} ");
            var a = (List<object>)v["a"];
            Assert.AreEqual(1.0, a[0]);
            Assert.AreEqual(2.5, a[1]);
            Assert.AreEqual(-300.0, a[2]);
            Assert.IsNull(((Dictionary<string, object>)v["b"])["c"]);
            Assert.AreEqual(true, v["d"]);
            Assert.AreEqual("x", v["e"]);
        }

        [Test]
        public void Json_ReadsEscapesAndUnicode()
        {
            Assert.AreEqual("q\" b\\ s/ \n\t \u00e9 \ud83d\ude00", Json.Parse("\"q\\\" b\\\\ s\\/ \\n\\t \\u00e9 \\ud83d\\ude00\""));
            Assert.AreEqual("プレイ", Json.Parse("\"プレイ\""));
        }

        [Test]
        public void Json_DuplicateKeyKeepsTheLastValue()
        {
            Assert.AreEqual(2.0, ((Dictionary<string, object>)Json.Parse("{\"a\": 1, \"a\": 2}"))["a"]);
        }

        [TestCase("")]
        [TestCase("   ")]
        [TestCase("{volume: loud")]
        [TestCase("{\"a\": 1,}")]
        [TestCase("[1, 2,]")]
        [TestCase("{'a': 1}")]
        [TestCase("NaN")]
        [TestCase("Infinity")]
        [TestCase("01")]
        [TestCase("1.")]
        [TestCase(".5")]
        [TestCase("+1")]
        [TestCase("\"\\x\"")]
        [TestCase("\"tab\tinside\"")]
        [TestCase("\"open")]
        [TestCase("[1] 2")]
        [TestCase("{\"a\" 1}")]
        [TestCase("// comment\n{}")]
        [TestCase("tru")]
        public void Json_RefusesWhatStrictJsonRefuses(string text)
        {
            Assert.Throws<FormatException>(() => Json.Parse(text));
            Assert.IsFalse(Json.TryParse(text, out object value));
            Assert.IsNull(value);
        }

        [Test]
        public void Json_RefusesHostileNesting()
        {
            Assert.IsFalse(Json.TryParse(new string('[', 10000), out _));
        }

        [Test]
        public void Json_WriterRoundTrips()
        {
            var tree = new Dictionary<string, object>
            {
                { "n", 1920.0 }, { "f", 0.8 }, { "tiny", 1e-7 }, { "neg", -0.25 }, { "s", "line\nbreak \"q\" \u0001 Í" },
                { "list", new List<object> { true, false, null, new List<object>(), new Dictionary<string, object>() } },
            };
            foreach (int indent in new[] { 0, 1, 2 })
            {
                string text = Json.Stringify(tree, indent);
                GoldenVectors.AssertClose(Json.Parse(text), tree, 0.0, $"indent {indent}: {text}");
            }
        }

        [Test]
        public void Json_WritesNumbersLikeTheOtherPorts()
        {
            Assert.AreEqual("1920", Json.FormatNumber(1920.0));
            Assert.AreEqual("0.8", Json.FormatNumber(0.8));
            Assert.AreEqual("-3", Json.FormatNumber(-3.0));
            Assert.AreEqual("null", Json.FormatNumber(double.NaN));
            Assert.AreEqual("{\"a\":[1,2]}", Json.Stringify(new Dictionary<string, object> { { "a", new List<object> { 1, 2.0 } } }));
            Assert.AreEqual("{\n \"a\": 1\n}", Json.Stringify(new Dictionary<string, object> { { "a", 1.0 } }, 1));
        }
    }
}

// {{FOOTER}}
