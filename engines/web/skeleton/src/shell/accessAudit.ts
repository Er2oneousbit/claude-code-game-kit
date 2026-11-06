// ---------------------------------------------------------------------------
// accessAudit.ts
// Purpose : What a player sees on one screen, as data for tools/access/sweep.py (#91, #85): every visible text with
//           its size, colour, the colour behind it, where its glyphs land and whether it fits; the panel it sits
//           on, and whether something drawn later covers it.
// Usage   : const report = accessScreen(document.getElementById("shell")!, "settings/audio", overGame)
//           (the access drive, drive.ts, logs it as ACCESS_SCREEN <json>)
// Notes   : Browser only (layout and computed styles). Sizes are CSS pixels of the page, which is the window: the
//           report says scaling "fractional" with the window as its design, so sweep.py takes them as they are.
//           A text's background is its ancestors' background colours blended down; on a screen over the game
//           (the HUD, pause) a text with no opaque panel is "over the game", and its panel layers are listed for a
//           worst-case check. A text-shadow counts as its outline. Hidden text, display:none and text scrolled out
//           of its scroll box are left out, as the pseudo check leaves them out.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
const COVER_ALPHA = 0.9; // a panel this opaque hides what is under it (a dialog over a screen)
const MAX_TEXT = 60; // characters of each text in the report

type Rgba = [number, number, number, number];

function parseColour(css: string): Rgba | null {
  const m = /rgba?\(([^)]+)\)/.exec(css);
  if (!m) return null;
  const v = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
  return [v[0], v[1], v[2], v.length > 3 ? v[3] : 1];
}

const hex = (c: Rgba | [number, number, number]) =>
  "#" + [c[0], c[1], c[2]].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

function visible(e: Element): boolean {
  const s = getComputedStyle(e);
  if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
  const r = e.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

/** The elements whose own text the player reads: an element with a non-empty direct text node. */
function textElements(root: HTMLElement): HTMLElement[] {
  const out: HTMLElement[] = [];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const p = n.parentElement;
    if (p && (n.textContent ?? "").trim() && !out.includes(p) && visible(p)) out.push(p);
  }
  return out;
}

/** Background layers from e outward until one is opaque (top first), and the element that drew the last one. */
function layers(e: HTMLElement): { list: Rgba[]; card: HTMLElement | null } {
  const list: Rgba[] = [];
  let card: HTMLElement | null = null;
  for (let n: HTMLElement | null = e; n; n = n.parentElement) {
    const c = parseColour(getComputedStyle(n).backgroundColor);
    if (c && c[3] > 0) {
      list.push(c);
      if (c[3] >= COVER_ALPHA && !card) card = n;
      if (c[3] >= 0.999) break;
    }
  }
  return { list, card };
}

function blend(list: Rgba[], base: [number, number, number]): [number, number, number] {
  let c = base;
  for (const l of [...list].reverse()) c = [0, 1, 2].map((i) => l[i] * l[3] + c[i] * (1 - l[3])) as [number, number, number];
  return c;
}

/** Where the element's own text glyphs land (the union of its text nodes' boxes). */
function ink(e: HTMLElement): number[] {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const n of Array.from(e.childNodes)) {
    if (n.nodeType !== Node.TEXT_NODE || !(n.textContent ?? "").trim()) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of Array.from(range.getClientRects())) {
      x1 = Math.min(x1, r.left); y1 = Math.min(y1, r.top); x2 = Math.max(x2, r.right); y2 = Math.max(y2, r.bottom);
    }
  }
  return x1 === Infinity ? [] : [x1, y1, x2 - x1, y2 - y1];
}

/** True when something else is on top at the middle of the text (a dialog over the screen). */
function covered(e: HTMLElement, box: number[]): boolean {
  if (box.length !== 4) return false;
  const top = document.elementFromPoint(box[0] + box[2] / 2, box[1] + box[3] / 2);
  if (!top || top === e || e.contains(top) || top.contains(e)) return false;
  const card = layers(top as HTMLElement).card;
  return !!card && !card.contains(e);
}

/** Text cut off by its own box, or outside the window or its scroll box. */
function fits(e: HTMLElement, box: number[]): string {
  const s = getComputedStyle(e);
  if (s.textOverflow === "ellipsis" && e.scrollWidth > e.clientWidth + 1) return "cut off with an ellipsis";
  if (s.overflow !== "visible" && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)) {
    return `text ${e.scrollWidth}x${e.scrollHeight} px does not fit its ${e.clientWidth}x${e.clientHeight} px box`;
  }
  if (box.length !== 4) return "";
  const scroller = scrollParent(e);
  if (scroller) {
    // in a scroll area, text above or below the fold is what scrolling is for; sideways it must fit (as the
    // pseudo check and the other engines' reports treat it)
    const r = scroller.getBoundingClientRect();
    return box[0] < r.left - 1 || box[0] + box[2] > r.right + 1 ? "wider than its scroll area" : "";
  }
  if (box[0] < -1 || box[1] < -1 || box[0] + box[2] > innerWidth + 1 || box[1] + box[3] > innerHeight + 1) {
    return "runs past the window";
  }
  return "";
}

function scrollParent(e: HTMLElement): HTMLElement | null {
  for (let n = e.parentElement; n; n = n.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(n).overflowY)) return n;
  }
  return null;
}

function scrolledOut(e: HTMLElement, box: number[]): boolean {
  const n = scrollParent(e);
  if (!n || box.length !== 4) return false;
  const r = n.getBoundingClientRect();
  return box[1] + box[3] < r.top || box[1] > r.bottom;
}

function rectOf(e: Element): number[] {
  const r = e.getBoundingClientRect();
  return [r.left, r.top, r.width, r.height];
}

/** The report for one screen; overGame = the screen is drawn over the game (HUD, pause). */
export function accessScreen(root: HTMLElement, screen: string, overGame: boolean): Record<string, unknown> {
  const page = parseColour(getComputedStyle(document.body).backgroundColor) ?? [0, 0, 0, 1];
  const texts: Record<string, unknown>[] = [];
  const all = Array.from(document.querySelectorAll("*")); // document order: a later card is drawn on top
  textElements(root).forEach((e) => {
    const box = ink(e);
    if (scrolledOut(e, box)) return;
    const s = getComputedStyle(e);
    const fg = parseColour(s.color) ?? [255, 255, 255, 1];
    const { list, card } = layers(e);
    const opaque = list.length > 0 && list[list.length - 1][3] >= 0.999;
    const shadow = parseColour(s.textShadow);
    const why = fits(e, box);
    const row: Record<string, unknown> = {
      node: e.closest<HTMLElement>("[data-id]")?.dataset.id ?? e.className ?? e.tagName.toLowerCase(),
      text: (e.textContent ?? "").trim().slice(0, MAX_TEXT), state: e.closest(".focused") ? "focus" : "",
      px: parseFloat(s.fontSize), fg: hex(fg), outline: shadow && s.textShadow !== "none" ? hex(shadow) : null,
      fits: !why, ink: box, covered: covered(e, box),
      card: card ? { order: all.indexOf(card), rect: rectOf(card) } : {},
    };
    if (why) row.why = why;
    if (opaque || !overGame) row.bg = hex(blend(list, [page[0], page[1], page[2]]));
    else row.over_game = list.map((l) => [hex(l), Math.round(l[3] * 1000) / 1000]);
    texts.push(row);
  });
  return { screen, design: [innerWidth, innerHeight], scaling: "fractional", texts };
}

// {{FOOTER}}
