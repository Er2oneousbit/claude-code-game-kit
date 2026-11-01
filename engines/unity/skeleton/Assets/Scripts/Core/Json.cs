// ---------------------------------------------------------------------------
// Json.cs
// Purpose : A small JSON reader and writer for the engine-free Core code (settings, saves, string tables)
//           and the golden-vector tests. Unity's JsonUtility only maps fixed [Serializable] classes, so it
//           cannot keep a settings file's unknown keys or read an arbitrary file.
// Usage   : object v = Json.Parse(text);                  // FormatException (with line and column) on bad JSON
//           if (Json.TryParse(text, out object v)) ...
//           var obj = Json.AsObject(v); double n = Json.ToNumber(obj["x"]);
//           string text = Json.Stringify(v, 1);             // 1 = one-space indent, 0 = compact
// Notes   : The value tree is plain types: object = Dictionary<string, object>, array = List<object>,
//           number = double (every number, as in JavaScript, GDScript and Lua), string, bool, null.
//           Strict RFC 8259 like Python's json and JavaScript's JSON.parse: no comments, trailing commas,
//           single quotes, NaN or Infinity; a duplicate key keeps the last value. The writer prints integral
//           numbers without ".0" and NaN or infinity as null (like JSON.stringify). Own code, no packages,
//           no UnityEngine types (EditMode tests run it instantly).
//
// Pseudocode (reader, recursive descent over the string):
//   value  = object | array | string | number | true | false | null, whitespace allowed around it
//   object = '{' [string ':' value (',' string ':' value)*] '}'   array = '[' [value (',' value)*] ']'
//   string = '"' (char | \" \\ \/ \b \f \n \r \t \uXXXX)* '"', a raw control character is an error
//   number = -?(0|[1-9][0-9]*)(.[0-9]+)?([eE][+-]?[0-9]+)?, parsed with the invariant culture
//   text left after the top value is an error ; nesting deeper than MAX_DEPTH is an error
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace {{GAME_SLUG}}.Core
{
    public static class Json
    {
        // ---- Tunables ------------------------------------------------------------
        private const int MAX_DEPTH = 256;            // a hostile file cannot overflow the stack
        private const double MAX_EXACT_INTEGER = 1e15; // integral doubles below this print as integers

        // ---- Reading ---------------------------------------------------------------

        /// <summary>Parses JSON text into the value tree. Throws FormatException on bad JSON.</summary>
        public static object Parse(string text)
        {
            if (text == null)
            {
                throw new ArgumentNullException(nameof(text));
            }
            var reader = new Reader(text);
            reader.SkipWhitespace();
            object value = reader.ReadValue(0);
            reader.SkipWhitespace();
            if (!reader.AtEnd)
            {
                throw reader.Error("unexpected text after the value");
            }
            return value;
        }

        /// <summary>False (and value null) for null text or bad JSON, instead of an exception.</summary>
        public static bool TryParse(string text, out object value)
        {
            value = null;
            if (text == null)
            {
                return false;
            }
            try
            {
                value = Parse(text);
                return true;
            }
            catch (FormatException)
            {
                return false;
            }
        }

        // ---- Value helpers ---------------------------------------------------------

        /// <summary>True for any CLR number type (bool is not a number, as in Python's check).</summary>
        public static bool IsNumber(object value)
        {
            return value is double || value is float || value is int || value is long || value is short
                   || value is byte || value is sbyte || value is uint || value is ulong || value is ushort
                   || value is decimal;
        }

        public static double ToNumber(object value)
        {
            return Convert.ToDouble(value, CultureInfo.InvariantCulture);
        }

        public static Dictionary<string, object> AsObject(object value)
        {
            return value as Dictionary<string, object>;
        }

        public static List<object> AsList(object value)
        {
            return value as List<object>;
        }

        /// <summary>A deep copy of a value tree. Any IDictionary becomes a Dictionary&lt;string, object&gt; and any
        /// non-string IEnumerable a List&lt;object&gt;; strings, numbers, bools and null are shared (immutable).</summary>
        public static object DeepCopy(object value)
        {
            if (value == null || value is string || value is bool || IsNumber(value))
            {
                return value;
            }
            if (value is IDictionary dict)
            {
                var copy = new Dictionary<string, object>(dict.Count);
                foreach (DictionaryEntry entry in dict)
                {
                    copy[Convert.ToString(entry.Key, CultureInfo.InvariantCulture)] = DeepCopy(entry.Value);
                }
                return copy;
            }
            if (value is IEnumerable list)
            {
                var copy = new List<object>();
                foreach (object item in list)
                {
                    copy.Add(DeepCopy(item));
                }
                return copy;
            }
            return value;
        }

        // ---- Writing ---------------------------------------------------------------

        /// <summary>The value as JSON text. indent 0 = compact, n = n spaces per level with ": " after keys.</summary>
        public static string Stringify(object value, int indent = 0)
        {
            var sb = new StringBuilder();
            Write(sb, value, Math.Max(indent, 0), 0);
            return sb.ToString();
        }

        /// <summary>A number the way the writer prints it: "1920", "0.8", null for NaN or infinity.</summary>
        public static string FormatNumber(double d)
        {
            if (double.IsNaN(d) || double.IsInfinity(d))
            {
                return "null";
            }
            if (d == Math.Floor(d) && Math.Abs(d) < MAX_EXACT_INTEGER)
            {
                return ((long)d).ToString(CultureInfo.InvariantCulture);
            }
            string s = d.ToString("R", CultureInfo.InvariantCulture);
            // Older runtimes' "R" is not always round-trip; G17 always is
            if (double.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture) != d)
            {
                s = d.ToString("G17", CultureInfo.InvariantCulture);
            }
            return s;
        }

        private static void Write(StringBuilder sb, object value, int indent, int level)
        {
            if (value == null)
            {
                sb.Append("null");
            }
            else if (value is string s)
            {
                WriteString(sb, s);
            }
            else if (value is bool b)
            {
                sb.Append(b ? "true" : "false");
            }
            else if (IsNumber(value))
            {
                sb.Append(FormatNumber(ToNumber(value)));
            }
            else if (value is IDictionary dict)
            {
                if (dict.Count == 0)
                {
                    sb.Append("{}");
                    return;
                }
                sb.Append('{');
                bool first = true;
                foreach (DictionaryEntry entry in dict)
                {
                    if (!first)
                    {
                        sb.Append(',');
                    }
                    first = false;
                    NewLine(sb, indent, level + 1);
                    WriteString(sb, Convert.ToString(entry.Key, CultureInfo.InvariantCulture));
                    sb.Append(indent > 0 ? ": " : ":");
                    Write(sb, entry.Value, indent, level + 1);
                }
                NewLine(sb, indent, level);
                sb.Append('}');
            }
            else if (value is IEnumerable list)
            {
                bool first = true;
                sb.Append('[');
                foreach (object item in list)
                {
                    if (!first)
                    {
                        sb.Append(',');
                    }
                    first = false;
                    NewLine(sb, indent, level + 1);
                    Write(sb, item, indent, level + 1);
                }
                if (!first)
                {
                    NewLine(sb, indent, level);
                }
                sb.Append(']');
            }
            else
            {
                throw new ArgumentException($"cannot write a {value.GetType().Name} as JSON");
            }
        }

        private static void NewLine(StringBuilder sb, int indent, int level)
        {
            if (indent > 0)
            {
                sb.Append('\n').Append(' ', indent * level);
            }
        }

        private static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < 0x20)
                        {
                            sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            sb.Append(c);      // non-ASCII stays as is: the files are UTF-8
                        }
                        break;
                }
            }
            sb.Append('"');
        }

        // ---- The reader --------------------------------------------------------------

        private sealed class Reader
        {
            private readonly string _s;
            private int _i;

            public Reader(string s)
            {
                _s = s;
            }

            public bool AtEnd => _i >= _s.Length;

            public void SkipWhitespace()
            {
                while (_i < _s.Length && (_s[_i] == ' ' || _s[_i] == '\t' || _s[_i] == '\n' || _s[_i] == '\r'))
                {
                    _i++;
                }
            }

            public FormatException Error(string why)
            {
                int line = 1, col = 1;
                for (int k = 0; k < _i && k < _s.Length; k++)
                {
                    if (_s[k] == '\n')
                    {
                        line++;
                        col = 1;
                    }
                    else
                    {
                        col++;
                    }
                }
                return new FormatException($"JSON: {why} at line {line}, column {col}");
            }

            public object ReadValue(int depth)
            {
                if (depth > MAX_DEPTH)
                {
                    throw Error("nested too deeply");
                }
                if (AtEnd)
                {
                    throw Error("unexpected end of text");
                }
                char c = _s[_i];
                switch (c)
                {
                    case '{': return ReadObject(depth);
                    case '[': return ReadArray(depth);
                    case '"': return ReadString();
                    case 't': return ReadLiteral("true", true);
                    case 'f': return ReadLiteral("false", false);
                    case 'n': return ReadLiteral("null", null);
                }
                if (c == '-' || IsDigit(c))
                {
                    return ReadNumber();
                }
                throw Error($"unexpected character '{c}'");
            }

            private static bool IsDigit(char c)
            {
                return c >= '0' && c <= '9';       // char.IsDigit would accept other scripts' digits
            }

            private object ReadLiteral(string word, object value)
            {
                if (string.CompareOrdinal(_s, _i, word, 0, word.Length) != 0)
                {
                    throw Error("unknown word");
                }
                _i += word.Length;
                return value;
            }

            private Dictionary<string, object> ReadObject(int depth)
            {
                var obj = new Dictionary<string, object>();
                _i++;                                  // '{'
                SkipWhitespace();
                if (!AtEnd && _s[_i] == '}')
                {
                    _i++;
                    return obj;
                }
                while (true)
                {
                    SkipWhitespace();
                    if (AtEnd || _s[_i] != '"')
                    {
                        throw Error("expected a key in double quotes");
                    }
                    string key = ReadString();
                    SkipWhitespace();
                    if (AtEnd || _s[_i] != ':')
                    {
                        throw Error("expected ':' after the key");
                    }
                    _i++;
                    SkipWhitespace();
                    obj[key] = ReadValue(depth + 1);  // a duplicate key keeps the last value
                    SkipWhitespace();
                    if (AtEnd)
                    {
                        throw Error("unterminated object");
                    }
                    if (_s[_i] == ',')
                    {
                        _i++;
                        continue;
                    }
                    if (_s[_i] == '}')
                    {
                        _i++;
                        return obj;
                    }
                    throw Error("expected ',' or '}'");
                }
            }

            private List<object> ReadArray(int depth)
            {
                var list = new List<object>();
                _i++;                                  // '['
                SkipWhitespace();
                if (!AtEnd && _s[_i] == ']')
                {
                    _i++;
                    return list;
                }
                while (true)
                {
                    SkipWhitespace();
                    list.Add(ReadValue(depth + 1));
                    SkipWhitespace();
                    if (AtEnd)
                    {
                        throw Error("unterminated array");
                    }
                    if (_s[_i] == ',')
                    {
                        _i++;
                        continue;
                    }
                    if (_s[_i] == ']')
                    {
                        _i++;
                        return list;
                    }
                    throw Error("expected ',' or ']'");
                }
            }

            private string ReadString()
            {
                var sb = new StringBuilder();
                _i++;                                  // opening quote
                while (true)
                {
                    if (AtEnd)
                    {
                        throw Error("unterminated string");
                    }
                    char c = _s[_i];
                    if (c == '"')
                    {
                        _i++;
                        return sb.ToString();
                    }
                    if (c < 0x20)
                    {
                        throw Error("control character in a string (escape it)");
                    }
                    if (c != '\\')
                    {
                        sb.Append(c);
                        _i++;
                        continue;
                    }
                    if (_i + 1 >= _s.Length)
                    {
                        throw Error("unterminated escape");
                    }
                    char e = _s[_i + 1];
                    _i += 2;
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            sb.Append(ReadHex4());       // surrogate pairs arrive as two escapes: valid UTF-16
                            break;
                        default:
                            _i -= 2;
                            throw Error($"unknown escape '\\{e}'");
                    }
                }
            }

            private char ReadHex4()
            {
                if (_i + 4 > _s.Length)
                {
                    throw Error("short \\u escape");
                }
                int code = 0;
                for (int k = 0; k < 4; k++)
                {
                    char h = _s[_i + k];
                    int digit = h >= '0' && h <= '9' ? h - '0'
                              : h >= 'a' && h <= 'f' ? h - 'a' + 10
                              : h >= 'A' && h <= 'F' ? h - 'A' + 10 : -1;
                    if (digit < 0)
                    {
                        throw Error("bad \\u escape");
                    }
                    code = code * 16 + digit;
                }
                _i += 4;
                return (char)code;
            }

            private double ReadNumber()
            {
                int start = _i;
                if (_s[_i] == '-')
                {
                    _i++;
                }
                if (AtEnd || !IsDigit(_s[_i]))
                {
                    throw Error("expected a digit");
                }
                if (_s[_i] == '0')
                {
                    _i++;                              // no leading zeros: "01" leaves "1" as extra text
                }
                else
                {
                    SkipDigits();
                }
                if (!AtEnd && _s[_i] == '.')
                {
                    _i++;
                    if (AtEnd || !IsDigit(_s[_i]))
                    {
                        throw Error("expected a digit after '.'");
                    }
                    SkipDigits();
                }
                if (!AtEnd && (_s[_i] == 'e' || _s[_i] == 'E'))
                {
                    _i++;
                    if (!AtEnd && (_s[_i] == '+' || _s[_i] == '-'))
                    {
                        _i++;
                    }
                    if (AtEnd || !IsDigit(_s[_i]))
                    {
                        throw Error("expected a digit in the exponent");
                    }
                    SkipDigits();
                }
                string token = _s.Substring(start, _i - start);
                try
                {
                    return double.Parse(token, NumberStyles.Float, CultureInfo.InvariantCulture);
                }
                catch (OverflowException)
                {
                    // Older runtimes throw for 1e999; newer ones (and Python) give infinity
                    return token[0] == '-' ? double.NegativeInfinity : double.PositiveInfinity;
                }
            }

            private void SkipDigits()
            {
                while (!AtEnd && IsDigit(_s[_i]))
                {
                    _i++;
                }
            }
        }
    }
}

// {{FOOTER}}
