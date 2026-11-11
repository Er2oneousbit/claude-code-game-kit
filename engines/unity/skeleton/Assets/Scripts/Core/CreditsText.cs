// ---------------------------------------------------------------------------
// CreditsText.cs
// Purpose : CREDITS.md as the credits screen shows it: HTML comments out (tools/credits.py writes one, #279), then
//           one paragraph per block between blank lines. Shell/Screens/TextPages.cs (CreditsScreen) draws them.
// Usage   : List<string> blocks = CreditsText.Blocks(File.ReadAllText("CREDITS.md"));   // null: the placeholder
//           string plain = CreditsText.StripHtmlComments(markdown);
// Notes   : No UnityEngine types (EditMode tests run it: Tests/EditMode/CreditsTextTests.cs). StripHtmlComments
//           follows tools/golden_vectors.py strip_html_comments; data/golden/credits.json holds the cases every
//           engine's credits screen passes.
//
// Pseudocode:
//   StripHtmlComments: per line, cut <!-- ... --> (a comment may span lines; an unclosed one runs to the end);
//     drop a line that held only comments, and one blank line after it when a blank line came before
//   Blocks: strip, split on blank-line gaps, trim each block, null when none is left
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Text;

namespace {{GAME_SLUG}}.Core
{
    public static class CreditsText
    {
        // ---- Tunables ------------------------------------------------------------
        private const string COMMENT_OPEN = "<!--";
        private const string COMMENT_CLOSE = "-->";

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

        /// <summary>The paragraphs the credits screen shows, or null (the placeholder) when nothing is left.</summary>
        public static List<string> Blocks(string markdown)
        {
            if (markdown == null)
            {
                return null;
            }
            var blocks = new List<string>();
            foreach (string block in StripHtmlComments(markdown).Split(new[] { "\n\n" }, StringSplitOptions.RemoveEmptyEntries))
            {
                string b = block.Trim();
                if (b.Length > 0)
                {
                    blocks.Add(b);
                }
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

// {{FOOTER}}
