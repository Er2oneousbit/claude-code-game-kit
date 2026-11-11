// ---------------------------------------------------------------------------
// credits.ts
// Purpose : CREDITS.md as the credits screen shows it: HTML comments out (tools/credits.py writes one, #279), the
//           rest as written.
// Usage   : const text = creditsText(markdown) ; text === null -> show the placeholder
// Notes   : No DOM, so Vitest runs it (tests/credits.test.ts). stripHtmlComments follows tools/golden_vectors.py
//           strip_html_comments; data/golden/credits.json holds the cases every engine's credits screen passes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
const COMMENT_OPEN = "<!--";
const COMMENT_CLOSE = "-->";

/** Only spaces and tabs (every port counts these two; Unicode whitespace differs between languages). */
function blank(line: string): boolean {
  return /^[ \t]*$/.test(line);
}

/**
 * Every <!-- --> comment removed, one line or many (an unclosed one runs to the end). A line that held only comments
 * goes, with one blank line after it when a blank line (or the top of the file) came before. CRLF becomes LF.
 */
export function stripHtmlComments(text: string): string {
  const out: string[] = [];
  let inComment = false;
  let skipBlank = false; // the blank line after a dropped comment-only line
  for (const line of text.replace(/\r\n/g, "\n").split("\n")) {
    let kept = "";
    let had = inComment;
    let i = 0;
    for (;;) {
      if (inComment) {
        const end = line.indexOf(COMMENT_CLOSE, i);
        if (end < 0) break; // the comment goes on into the next line
        inComment = false;
        i = end + COMMENT_CLOSE.length;
      } else {
        const start = line.indexOf(COMMENT_OPEN, i);
        if (start < 0) {
          kept += line.slice(i);
          break;
        }
        kept += line.slice(i, start);
        inComment = true;
        had = true;
        i = start + COMMENT_OPEN.length;
      }
    }
    if (had && blank(kept)) {
      skipBlank = out.length === 0 || blank(out[out.length - 1]);
      continue;
    }
    if (skipBlank && blank(kept)) {
      skipBlank = false;
      continue;
    }
    skipBlank = false;
    out.push(kept);
  }
  return out.join("\n");
}

/** The text the credits screen scrolls, or null (the placeholder) when the file is missing or holds nothing else. */
export function creditsText(markdown: string | undefined): string | null {
  if (markdown === undefined) return null;
  const text = stripHtmlComments(markdown).trim();
  return text === "" ? null : text;
}

// {{FOOTER}}
