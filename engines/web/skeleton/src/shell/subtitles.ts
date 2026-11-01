// ---------------------------------------------------------------------------
// subtitles.ts
// Purpose : The subtitle bar and SFX captions, fed by data/dialogue/*.built.json (dialogue format v0) and the
//           player's settings (subtitles on/off, size, background, speaker names, barks, sound captions).
// Usage   : shell.subtitles.say("demo.welcome")          // typewriter (default) or { typewriter: false } for cues
//           shell.subtitles.caption("hit")               // "[thud]" when access.captions_sfx is on
//           shell.subtitles.finish()                     // reveal the whole line now (screenshots)
// Notes   : Browser only (DOM), no Phaser. Bundles every data/dialogue/*.built.json at build time (Vite glob);
//           a later file's line id wins. In locale "pseudo" the text runs through pseudo(), so the bar's
//           layout gets the same overflow check as the menus. Unknown fields in the files are ignored.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { cueAt, dialogueFrom, lineLife, revealCount, shouldShow, type Caption, type DialogueLine } from "../core/dialogue";
import { PSEUDO_LOCALE, pseudo } from "../core/i18n";
import { Log } from "../core/log";
import type { Shell } from "./app";
import { el } from "./ui";

type Showing = { line: DialogueLine; t: number; typewriter: boolean; root: HTMLElement; body: HTMLElement; chars: string[] };

function loadDialogue(): { lines: Record<string, DialogueLine>; captions: Record<string, Caption> } {
  const files = import.meta.glob("../../data/dialogue/*.built.json", { eager: true, import: "default" }) as Record<string, unknown>;
  const out = { lines: {} as Record<string, DialogueLine>, captions: {} as Record<string, Caption> };
  for (const [path, raw] of Object.entries(files).sort()) {
    try {
      const d = dialogueFrom(raw);
      Object.assign(out.lines, d.lines);
      Object.assign(out.captions, d.captions);
    } catch (err) {
      Log.warn("subtitles", `${path} skipped: ${String(err)}`);
    }
  }
  return out;
}

export class SubtitleBar {
  private readonly data = loadDialogue();
  private showing: Showing | null = null;
  private readonly captions: { root: HTMLElement; left: number }[] = [];

  constructor(private readonly shell: Shell, private readonly host: HTMLElement) {}

  private mark(e: HTMLElement): void {
    if (this.shell.i18n.locale === PSEUDO_LOCALE) e.dataset.tr = "";
    else e.dataset.val = ""; // dialogue text is content from the dialogue file, not a UI string
  }

  private text(s: string): string {
    return this.shell.i18n.locale === PSEUDO_LOCALE ? pseudo(s) : s;
  }

  /** Shows a line; false when the id is unknown or the settings hide it (subtitles off, a bark without barks). */
  say(id: string, opts: { typewriter?: boolean } = {}): boolean {
    const line = this.data.lines[id];
    if (!line) {
      Log.warn("subtitles", `no dialogue line "${id}"`);
      return false;
    }
    if (!shouldShow(line, this.shell.settings.access)) return false;
    this.showing?.root.remove();
    const root = el("div", "sub");
    root.dataset.id = `line.${id}`;
    if (this.shell.settings.access.speaker_names && line.name) {
      const who = el("span", "speaker", this.text(line.name) + ": ");
      who.style.color = line.color;
      this.mark(who);
      root.append(who);
    }
    const body = el("span", "subtext");
    this.mark(body);
    body.dataset.id = `line.${id}`;
    root.append(body);
    this.host.append(root);
    this.showing = { line, t: 0, typewriter: opts.typewriter ?? true, root, body, chars: Array.from(this.text(line.text)) };
    this.draw();
    return true;
  }

  /** A sound caption ("[thud]") for an audio event id, shown at least its min_s. */
  caption(id: string): boolean {
    const c = this.data.captions[id];
    if (!c || !this.shell.settings.access.captions_sfx) return false;
    const root = el("div", "sub caption", this.text(c.text));
    root.dataset.id = `caption.${id}`;
    this.mark(root);
    this.host.append(root);
    this.captions.push({ root, left: c.minS });
    return true;
  }

  /** Reveals the current line completely (a screenshot or a skip button). */
  finish(): void {
    if (!this.showing) return;
    this.showing.t = this.showing.line.durationS;
    this.draw();
  }

  clear(): void {
    this.showing?.root.remove();
    this.showing = null;
    for (const c of this.captions.splice(0)) c.root.remove();
  }

  update(dt: number): void {
    for (const c of [...this.captions]) {
      c.left -= dt;
      if (c.left <= 0) {
        c.root.remove();
        this.captions.splice(this.captions.indexOf(c), 1);
      }
    }
    const s = this.showing;
    if (!s) return;
    s.t += dt;
    if (s.t >= lineLife(s.line)) {
      s.root.remove();
      this.showing = null;
      return;
    }
    this.draw();
  }

  private draw(): void {
    const s = this.showing;
    if (!s) return;
    if (s.typewriter) {
      s.body.textContent = s.chars.slice(0, revealCount(s.line, s.t, s.chars.length)).join("");
    } else {
      const cue = cueAt(s.line, Math.min(s.t, s.line.durationS - 1e-6));
      s.body.textContent = cue ? this.text(cue.lines.join("\n")) : "";
    }
  }
}

// {{FOOTER}}
