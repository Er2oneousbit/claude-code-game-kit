// ---------------------------------------------------------------------------
// narrator.ts
// Purpose : Menu narration (#165): every focus change, value change and screen says a short line ("Music volume,
//           slider, 70 percent"), so a blind or low-vision player can use the title, settings and pause screens.
// Usage   : shell.narrator = new Narrator(shell); narrator.focus(item) / narrator.screen(name)  (ui.ts and app.ts call
//           them); describe(shell, item) is the line for one menu item (the access drive reports it for each item)
// Notes   : Browser only. The line always goes to an ARIA live region (polite), which a screen reader announces;
//           with access.narration on, the browser's speech (speechSynthesis) says it too, cutting off the line
//           before. The page's own menus are drawn, not real buttons, so the live region is what a screen reader
//           hears (verify with NVDA, VoiceOver and Orca).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { narrationLine } from "../core/bindings";
import type { Shell } from "./app";
import type { Item } from "./ui";

const ARROWS = /[‹›<>]/g; // the value row's arrows are drawn, not said
const ROLE_KEYS: Record<string, string> = { button: "narrate.button", toggle: "narrate.toggle", slider: "narrate.slider", choice: "narrate.choice" };

/** The line one menu item says: its label, its role, its value. */
export function describe(shell: Shell, item: Item): string {
  const tab = item.el.querySelector(".tab.current");
  if (tab) return narrationLine(shell.i18n.t("settings.title"), shell.i18n.t("narrate.tab"), tab.textContent ?? "");
  const label = item.el.querySelector(".label")?.textContent ?? item.el.textContent ?? "";
  const value = (item.el.querySelector(".value")?.textContent ?? "").replace(ARROWS, "");
  const role = item.role ?? (value ? "choice" : "button");
  return narrationLine(label, shell.i18n.t(ROLE_KEYS[role] ?? "narrate.button"), value);
}

export class Narrator {
  private readonly live: HTMLElement;
  private last = "";

  constructor(private readonly shell: Shell) {
    this.live = document.createElement("div");
    this.live.id = "narration";
    this.live.className = "visually-hidden";
    this.live.setAttribute("aria-live", "polite");
    this.live.setAttribute("role", "status");
    document.body.append(this.live);
  }

  focus(item: Item): void {
    this.say(describe(this.shell, item));
  }

  screen(title: string): void {
    this.say(narrationLine(title, this.shell.i18n.t("narrate.screen")));
  }

  private say(line: string): void {
    if (!line || line === this.last) return;
    this.last = line;
    this.shell.lastNarration = line;
    this.live.textContent = line;
    if (!this.shell.settings.access.narration || typeof speechSynthesis === "undefined") return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(line);
    u.lang = this.shell.i18n.locale;
    speechSynthesis.speak(u);
  }
}
