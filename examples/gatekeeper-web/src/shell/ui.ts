// ---------------------------------------------------------------------------
// ui.ts
// Purpose : DOM building blocks for the front end: elements, translated labels, the focusable Menu list
//           (keyboard, gamepad and mouse), and prompt glyphs with a text fallback.
// Usage   : const m = new Menu() ; m.add(buttonItem(i18n, "menu.play", () => play())) ; panel.append(...m.elements())
//           screen.onAction = (a) => m.handle(a)
//           glyph(i18n, "key_space")   // <img> when public/assets/ui/glyphs/key_space.png exists, else a keycap
// Notes   : Browser only, no Phaser. Every visible string is marked: data-tr (went through I18n.t, the
//           pseudo-locale check expects "[" at its start) or data-val (numbers, key names, content). The
//           pseudo check (pseudoCheck.ts) flags any text that is neither. data-id names a label in reports.
//           Glyph PNGs (public/assets/ui/glyphs/<glyph_name>.png) can come from Dotwork's UI kit
//           (tools/art/dotwork, the widgets lane); until they exist, prompts show a text keycap.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import uiAssets from "virtual:ui-assets";
import type { I18n } from "../core/i18n";

// ---- Tunables ----------------------------------------------------------------
const GLYPH_DIR = "glyphs/"; // under public/assets/ui/
const GLYPH_URL = "assets/ui/glyphs/";
const GLYPH_LINE_EM = 1.4; // a glyph is scaled by a whole number to about this many ems tall

const uiFiles = new Set(uiAssets);

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** A translated string: data-tr, data-id = key. */
export function tl(i18n: I18n, key: string, cls = "label", args: Record<string, unknown> = {}, tag: "span" | "div" = "span"): HTMLElement {
  const e = el(tag, cls, i18n.t(key, args));
  e.dataset.tr = "";
  e.dataset.id = key;
  return e;
}

/** An untranslated value (a number, a key name, content from a file): data-val. */
export function val(text: string, cls = "", id = ""): HTMLElement {
  const e = el("span", cls, text);
  e.dataset.val = "";
  if (id) e.dataset.id = id;
  return e;
}

export type Item = {
  id: string;
  el: HTMLElement;
  accept?: () => void;
  left?: () => void;
  right?: () => void;
};

/** A vertical list of focusable items. Up/down move (wrapping), left/right change values, accept activates. */
export class Menu {
  readonly items: Item[] = [];
  index = 0;
  /** A row of buttons: left/right move between items (when the item has no value to change). */
  horizontal = false;

  add(item: Item): Item {
    item.el.classList.add("item");
    item.el.dataset.item = item.id;
    item.el.addEventListener("mouseenter", () => this.focusId(item.id));
    item.el.addEventListener("click", (ev) => {
      this.focusId(item.id);
      const target = ev.target as HTMLElement;
      if (target.closest("[data-dir='left']")) item.left?.();
      else if (item.accept) item.accept();
      else item.right?.();
    });
    this.items.push(item);
    if (this.items.length === 1) this.render();
    return item;
  }

  get focused(): Item | undefined {
    return this.items[this.index];
  }

  focusId(id: string): boolean {
    const i = this.items.findIndex((it) => it.id === id);
    if (i < 0) return false;
    this.index = i;
    this.render();
    return true;
  }

  move(step: number): void {
    if (!this.items.length) return;
    this.index = (this.index + step + this.items.length) % this.items.length;
    this.render();
  }

  /** Handles one ui_* action; false when it is not one this menu uses. */
  handle(action: string): boolean {
    const it = this.focused;
    switch (action) {
      case "ui_up": this.move(-1); return true;
      case "ui_down": this.move(1); return true;
      case "ui_left":
        if (it?.left) it.left();
        else if (this.horizontal) this.move(-1);
        else return false;
        return true;
      case "ui_right":
        if (it?.right) it.right();
        else if (this.horizontal) this.move(1);
        else return false;
        return true;
      case "ui_accept":
        if (it?.accept) it.accept();
        else it?.right?.(); // accept on a value row steps it forward (toggles a switch)
        return !!it;
      default: return false;
    }
  }

  render(): void {
    this.items.forEach((it, i) => {
      const on = i === this.index;
      it.el.classList.toggle("focused", on);
      it.el.setAttribute("aria-selected", String(on));
      if (on && typeof it.el.scrollIntoView === "function") it.el.scrollIntoView({ block: "nearest" });
    });
  }
}

/** A button item with a translated label. */
export function buttonItem(i18n: I18n, key: string, accept: () => void, id = key): Item {
  const e = el("div", "button");
  e.setAttribute("role", "button");
  e.append(tl(i18n, key));
  return { id, el: e, accept };
}

/** A value row: label on the left, "< value >" on the right; set(text, translated) redraws the value. */
export function valueRow(i18n: I18n, key: string, left: () => void, right: () => void): { item: Item; set: (text: string, translated: boolean) => void } {
  const e = el("div", "");
  const v = el("span", "value");
  const a = val("‹", "arrow");
  a.dataset.dir = "left";
  const b = val("›", "arrow");
  const center = el("span", "");
  v.append(a, center, b);
  e.append(tl(i18n, key), v);
  const set = (text: string, translated: boolean) => {
    center.textContent = text;
    delete center.dataset.tr;
    delete center.dataset.val;
    if (translated) center.dataset.tr = "";
    else center.dataset.val = "";
    center.dataset.id = key + ".value";
  };
  return { item: { id: key, el: e, left, right }, set };
}

/** Readable text for a glyph name when there is no art: key_space -> "Space", xbox_a -> "A". */
export function glyphText(i18n: I18n, name: string): string {
  if (name === "unknown") return i18n.t("controls.none");
  if (i18n.has(`glyph.${name}`)) return i18n.t(`glyph.${name}`);
  const cut = name.indexOf("_");
  let rest = name.startsWith("mouse_") ? "mouse " + name.slice(6) : cut >= 0 ? name.slice(cut + 1) : name;
  rest = rest.replace(/_/g, " ");
  return rest.length === 1 ? rest.toUpperCase() : rest.charAt(0).toUpperCase() + rest.slice(1);
}

/** The prompt glyph: art from public/assets/ui/glyphs/<name>.png (whole-number scaled, nearest) or a keycap. */
export function glyph(i18n: I18n, name: string, cls = ""): HTMLElement {
  if (name !== "unknown" && uiFiles.has(`${GLYPH_DIR}${name}.png`)) {
    const img = el("img", ("glyph " + cls).trim());
    img.alt = glyphText(i18n, name);
    img.dataset.val = "";
    img.addEventListener("load", () => {
      const em = parseFloat(getComputedStyle(img).fontSize) || 16;
      const k = Math.max(1, Math.round((em * GLYPH_LINE_EM) / Math.max(img.naturalHeight, 1)));
      img.style.width = `${img.naturalWidth * k}px`;
      img.style.height = `${img.naturalHeight * k}px`;
    });
    img.src = `${GLYPH_URL}${name}.png`;
    return img;
  }
  return val(glyphText(i18n, name), ("keycap " + cls).trim());
}

/** Is this public/assets/ui/ file part of the build? */
export function hasUiFile(path: string): boolean {
  return uiFiles.has(path);
}
