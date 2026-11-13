// ---------------------------------------------------------------------------
// CreditsText.cs
// Purpose : CREDITS.md as the credits screen shows it: HTML comments out (tools/credits.py writes one, #279), heading
//           marks, list markers and emphasis stars off (#284), then one paragraph per block between blank lines.
//           Shell/Screens/TextPages.cs (CreditsScreen) draws them.
// Usage   : List<string> blocks = CreditsText.Blocks(File.ReadAllText("CREDITS.md"));   // null: the placeholder
//           string plain = CreditsText.Plain(markdown);
// Notes   : No UnityEngine types (EditMode tests run it: Tests/EditMode/CreditsTextTests.cs). StripHtmlComments and
//           Plain follow tools/golden_vectors.py strip_html_comments and credits_text; data/golden/credits.json holds
//           the cases every engine's credits screen passes.
//
// Pseudocode:
//   StripHtmlComments: per line, cut <!-- ... --> (a comment may span lines; an unclosed one runs to the end);
//     drop a line that held only comments, and one blank line after it when a blank line came before
//   Plain: strip, then per line a heading's marks or a list marker, every '*', the spaces and tabs at the ends
//   Blocks: Plain's lines grouped between blank lines, null when none is left
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): Plain, the markdown marks off (the screen showed "#"
//           as written), Blocks built on it (#284)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Text;

namespace graveyard_shift.Core
{
    public static class CreditsText
    {
        // ---- Tunables ------------------------------------------------------------
        private const string COMMENT_OPEN = "<!--";
        private const string COMMENT_CLOSE = "-->";
        private const string LIST_MARKERS = "-*+";                       // a list item's first character
        private static readonly char[] SPACE_TAB = { ' ', '\t' };        // never Trim(): it also takes a no-break space

        /// <summary>Every HTML comment removed, one line or many; a comment-only line goes (see the header).</summary>
        public static string StripHtmlComments(string text)
        {
            var output = new List<string>();
            bool inComment = false;
            bool skipBlank = false;             // the blank line after a dropped comment-only line
            foreach (string line in (text ?? "").Replace("\r\n", "\n").Split('\n'))
            {
                var kept = new StringBuilder();
                bool had = inComment;
                int i = 0;
                while (true)
                {
                    if (inComment)
                    {
                        int end = line.IndexOf(COMMENT_CLOSE, i, StringComparison.Ordinal);
                        if (end < 0)
                        {
                            break;              // the comment goes on into the next line
                        }
                        inComment = false;
                        i = end + COMMENT_CLOSE.Length;
                    }
                    else
                    {
                        int start = line.IndexOf(COMMENT_OPEN, i, StringComparison.Ordinal);
                        if (start < 0)
                        {
                            kept.Append(line, i, line.Length - i);
                            break;
                        }
                        kept.Append(line, i, start - i);
                        inComment = true;
                        had = true;
                        i = start + COMMENT_OPEN.Length;
                    }
                }
                string k = kept.ToString();
                if (had && Blank(k))
                {
                    skipBlank = output.Count == 0 || Blank(output[output.Count - 1]);
                    continue;
                }
                if (skipBlank && Blank(k))
                {
                    skipBlank = false;
                    continue;
                }
                skipBlank = false;
                output.Add(k);
            }
            return string.Join("\n", output);
        }

        /// <summary>
        /// CREDITS.md as every engine's credits screen shows it (tools/golden_vectors.py credits_text, #284): HTML
        /// comments out, then per line a heading's marks or a list marker, every emphasis star and the spaces and
        /// tabs at both ends; blank lines at the start and the end go. "" means nothing to show.
        /// </summary>
        public static string Plain(string markdown)
        {
            var lines = new List<string>();
            foreach (string line in StripHtmlComments(markdown).Split('\n'))
            {
                string s = line.TrimStart(SPACE_TAB);
                int marks = 0;
                while (marks < s.Length && s[marks] == '#')
                {
                    marks++;
                }
                if (marks > 0 && (marks == s.Length || s[marks] == ' ' || s[marks] == '\t'))
                {
                    s = s.Substring(marks).TrimStart(SPACE_TAB);     // a heading: its text stays
                }
                else if (s.Length >= 2 && LIST_MARKERS.IndexOf(s[0]) >= 0 && (s[1] == ' ' || s[1] == '\t'))
                {
                    s = s.Substring(1).TrimStart(SPACE_TAB);         // a list item: its text stays
                }
                lines.Add(s.Replace("*", "").TrimEnd(SPACE_TAB));
            }
            int first = 0;
            int last = lines.Count;
            while (first < last && lines[first].Length == 0)
            {
                first++;
            }
            while (last > first && lines[last - 1].Length == 0)
            {
                last--;
            }
            return string.Join("\n", lines.GetRange(first, last - first));
        }

        /// <summary>The paragraphs the credits screen shows (Plain's lines between blank lines), or null (the
        /// placeholder) when nothing is left.</summary>
        public static List<string> Blocks(string markdown)
        {
            if (markdown == null)
            {
                return null;
            }
            var blocks = new List<string>();
            var block = new List<string>();
            foreach (string line in Plain(markdown).Split('\n'))
            {
                if (line.Length > 0)
                {
                    block.Add(line);
                    continue;
                }
                if (block.Count > 0)
                {
                    blocks.Add(string.Join("\n", block));
                    block.Clear();
                }
            }
            if (block.Count > 0)
            {
                blocks.Add(string.Join("\n", block));
            }
            return blocks.Count > 0 ? blocks : null;
        }

        /// <summary>Only spaces and tabs (every port counts these two; Unicode whitespace differs by language).</summary>
        private static bool Blank(string line)
        {
            foreach (char c in line)
            {
                if (c != ' ' && c != '\t')
                {
                    return false;
                }
            }
            return true;
        }
    }
}
