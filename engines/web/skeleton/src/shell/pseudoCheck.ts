// ---------------------------------------------------------------------------
// pseudoCheck.ts
// Purpose : The pseudo-locale layout check: after a screen appears in locale "pseudo", every VISIBLE piece of
//           text is checked for (1) not going through tr (a translated label must start with "["; text with no
//           data-tr or data-val mark at all is hard-coded), (2) clipped by its own box (ellipsis, cut off),
//           (3) sticking out of its panel ([data-box]) or the window.
// Usage   : const r = checkScreen(document.getElementById("shell")!)   // { labels, failures: [{ id, reason, text }] }
//           The shell runs it on every screen in locale "pseudo" and logs PSEUDO_FAIL lines (console.error,
//           so `dev.py smoke --locale pseudo --drive pseudo` exits 1).
// Notes   : Browser only (layout APIs). Hidden screens, display:none and text scrolled out of a scroll box do not
//           count as visible. Inline spans have no box of their own: only their panel and the window are checked.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
const SLACK_PX = 1; // sub-pixel rounding is not truncation

export type CheckFailure = { id: string; reason: string; text: string };

function describe(e: Element): string {
  const named = e.closest<HTMLElement>("[data-id]");
  if (named?.dataset.id) return named.dataset.id;
  return e.tagName.toLowerCase() + (e.className ? "." + String(e.className).split(" ").join(".") : "");
}

function intersects(a: DOMRect, b: { left: number; right: number; top: number; bottom: number }): boolean {
  return a.right > b.left && a.left < b.right && a.bottom > b.top && a.top < b.bottom;
}

/** On screen, not hidden, and not scrolled out of view inside a scroll box. */
function visible(e: HTMLElement): boolean {
  const r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  const st = getComputedStyle(e);
  if (st.visibility === "hidden" || st.display === "none") return false;
  if (!intersects(r, { left: 0, top: 0, right: innerWidth, bottom: innerHeight })) return false;
  for (let p = e.parentElement; p; p = p.parentElement) {
    if (p.classList.contains("hidden")) return false;
    const ps = getComputedStyle(p);
    if (ps.overflowY !== "visible" && p.scrollHeight > p.clientHeight && !intersects(r, p.getBoundingClientRect())) return false;
  }
  return true;
}

export function checkScreen(root: HTMLElement): { labels: number; failures: CheckFailure[] } {
  const failures: CheckFailure[] = [];
  const marked = new Set<HTMLElement>();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.textContent ?? "").trim();
    const parent = n.parentElement;
    if (!text || !parent || !visible(parent)) continue;
    const mark = parent.closest<HTMLElement>("[data-tr],[data-val]");
    if (!mark || !root.contains(mark)) {
      failures.push({ id: describe(parent), reason: "not passed through tr (no data-tr / data-val mark)", text });
      continue;
    }
    marked.add(mark);
  }
  for (const e of marked) {
    const text = (e.textContent ?? "").trim();
    if ("tr" in e.dataset && !text.startsWith("[")) {
      failures.push({ id: describe(e), reason: "not passed through tr (no \"[\" at the start)", text });
    }
    const st = getComputedStyle(e);
    if (st.display !== "inline" && (e.scrollWidth > e.clientWidth + SLACK_PX || (st.overflowY !== "visible" && e.scrollHeight > e.clientHeight + SLACK_PX))) {
      failures.push({ id: describe(e), reason: `clipped (needs ${e.scrollWidth}x${e.scrollHeight} px, has ${e.clientWidth}x${e.clientHeight})`, text });
      continue;
    }
    const r = e.getBoundingClientRect();
    const box = e.closest<HTMLElement>("[data-box]");
    if (box) {
      const b = box.getBoundingClientRect();
      if (r.right > b.right + SLACK_PX || r.left < b.left - SLACK_PX) {
        failures.push({ id: describe(e), reason: "overflows its panel", text });
        continue;
      }
    }
    if (r.right > innerWidth + SLACK_PX || r.left < -SLACK_PX) failures.push({ id: describe(e), reason: "runs off the screen", text });
  }
  return { labels: marked.size, failures };
}

// {{FOOTER}}
