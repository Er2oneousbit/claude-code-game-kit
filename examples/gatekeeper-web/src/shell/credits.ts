// ---------------------------------------------------------------------------
// credits.ts
// Purpose : CREDITS.md as the credits screen shows it: HTML comments out (tools/credits.py writes one, #279), then
//           heading marks, list markers and emphasis stars off, the same rule on every engine (#284).
// Usage   : const text = creditsText(markdown) ; text === null -> show the placeholder
// Notes   : No DOM, so Vitest runs it (tests/credits.test.ts). stripHtmlComments and creditsMarkdownText follow
//           tools/golden_vectors.py strip_html_comments and credits_text; data/golden/credits.json holds the cases
//           every engine's credits screen passes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): creditsMarkdownText, the markdown marks off (the
//           screen showed "#" and "- " as written) (#284)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
const COMMENT_OPEN = "<!--";
const COMMENT_CLOSE = "-->";
const LIST_ITEM = /^[-*+][ \t]/; // a list marker, then a space or tab

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

/**
 * CREDITS.md as every engine's credits screen shows it (tools/golden_vectors.py credits_text, #284): HTML comments
 * out, then per line a heading's marks ("#" then a space, a tab or the line end) or a list marker ("-", "*" or "+"
 * then a space or tab), every emphasis star, and the spaces and tabs at both ends; blank lines at the start and the
 * end go. "" means nothing to show. Spaces and tabs only, never trim(): it also takes a no-break space.
 */
export function creditsMarkdownText(markdown: string): string {
  const lines = stripHtmlComments(markdown)
    .split("\n")
    .map((line) => {
      let s = line.replace(/^[ \t]+/, "");
      const marks = /^#+/.exec(s)?.[0].length ?? 0;
      if (marks > 0 && (marks === s.length || s[marks] === " " || s[marks] === "\t")) {
        s = s.slice(marks).replace(/^[ \t]+/, ""); // a heading: its text stays
      } else if (LIST_ITEM.test(s)) {
        s = s.slice(1).replace(/^[ \t]+/, ""); // a list item: its text stays
      }
      return s.replace(/\*/g, "").replace(/[ \t]+$/, "");
    });
  let first = 0;
  let last = lines.length;
  while (first < last && lines[first] === "") first++;
  while (last > first && lines[last - 1] === "") last--;
  return lines.slice(first, last).join("\n");
}

/** The text the credits screen scrolls, or null (the placeholder) when the file is missing or holds nothing else. */
export function creditsText(markdown: string | undefined): string | null {
  if (markdown === undefined) return null;
  const text = creditsMarkdownText(markdown);
  return text === "" ? null : text;
}
