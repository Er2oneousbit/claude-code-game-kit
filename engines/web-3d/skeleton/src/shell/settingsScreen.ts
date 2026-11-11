// ---------------------------------------------------------------------------
// settingsScreen.ts
// Purpose : The settings screen: sections Display, Audio, Controls, Accessibility, Language, one row per
//           settings field the browser can apply, rebinding with "press a key", swap and conflict display,
//           reset to defaults. Back (or ui_cancel) saves settings.json atomically.
// Usage   : shell.push(settingsScreen(shell))      // from the main menu or the pause menu
// Notes   : Browser only (DOM). Changes apply live (shell.apply()). Not shown because a browser cannot apply
//           them: display.vsync (the browser always syncs) and display.resolution (the canvas follows the
//           window). They stay in settings.json for desktop builds of the same game.
//
// Pseudocode:
//   tabs row (left/right switch section) ; rows of the section (left/right change, accept steps or acts)
//   controls: accept on an action row -> capture the next key (slot 0) or button (slot 1) -> rebind() swap
//   back: save -> previous screen
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import presetData from "../../data/input/presets.json";
import { DEFAULT_BINDINGS, GLYPH_SETS, findConflicts, glyphName, glyphSet, rebind } from "../core/bindings";
import { PSEUDO_LOCALE } from "../core/i18n";
import { COLORBLIND, CONSENT, DIFFICULTIES, DISPLAY_MODES, FRAME_CAPS, SUB_SIZES, type Settings } from "../core/settings";
import type { Screen, Shell } from "./app";
import { Menu, buttonItem, el, glyph, tl, valueRow, type Item } from "./ui";

// ---- Tunables ----------------------------------------------------------------
export const TABS = ["display", "audio", "controls", "access", "language"] as const;
const REBINDABLE = Object.keys(DEFAULT_BINDINGS).filter((a) => !a.startsWith("ui_")); // ui_* stay fixed

const round2 = (v: number) => Math.round(v * 100) / 100;

type Ctx = { shell: Shell; menu: Menu; list: HTMLElement; status: HTMLElement };
/** A choice's label: a string table key, or a key with arguments ("opt.fps", { n: 60 }). */
type Label = string | [string, Record<string, unknown>];

function numRow(c: Ctx, key: string, get: (s: Settings) => number, set: (s: Settings, v: number) => void, lo: number, hi: number, step: number, fmt: (v: number) => string): void {
  const change = (d: number) => {
    set(c.shell.settings, round2(Math.min(hi, Math.max(lo, get(c.shell.settings) + d))));
    c.shell.apply();
    draw();
  };
  const row = valueRow(c.shell.i18n, key, () => change(-step), () => change(step));
  row.item.role = "slider"; // narration (#165)
  const draw = () => row.set(fmt(get(c.shell.settings)), false);
  draw();
  c.list.append(c.menu.add(row.item).el);
}

function choiceRow<T extends string | number>(c: Ctx, key: string, values: readonly T[], get: (s: Settings) => T, set: (s: Settings, v: T) => void, label: (v: T) => Label, after?: () => void, role = "choice"): void {
  const change = (d: number) => {
    const i = values.indexOf(get(c.shell.settings));
    set(c.shell.settings, values[(i + d + values.length) % values.length]);
    c.shell.apply();
    draw();
    after?.();
  };
  const row = valueRow(c.shell.i18n, key, () => change(-1), () => change(1));
  row.item.role = role;
  const draw = () => {
    const l = label(get(c.shell.settings));
    row.set(typeof l === "string" ? c.shell.i18n.t(l) : c.shell.i18n.t(l[0], l[1]), true);
  };
  draw();
  c.list.append(c.menu.add(row.item).el);
}

function boolRow(c: Ctx, key: string, get: (s: Settings) => boolean, set: (s: Settings, v: boolean) => void): void {
  choiceRow(c, key, [false, true].map(String), (s) => String(get(s)), (s, v) => set(s, v === "true"), (v) => (v === "true" ? "opt.on" : "opt.off"), undefined, "toggle");
}

const pct = (v: number) => `${Math.round(v * 100)} %`;
const times = (v: number) => `${v.toFixed(2)}x`;

function controls(c: Ctx): void {
  const { shell } = c;
  choiceRow(c, "input.glyphs", GLYPH_SETS, (s) => s.input.glyphs, (s, v) => (s.input.glyphs = v), (v) => `opt.glyphs.${v}`, () => drawActions());
  numRow(c, "input.deadzone", (s) => s.input.deadzone, (s, v) => (s.input.deadzone = v), 0, 0.9, 0.05, pct);
  boolRow(c, "input.invert_y", (s) => s.input.invert_y, (s, v) => (s.input.invert_y = v));
  const head = el("div", "row muted");
  head.append(tl(shell.i18n, "controls.hint", "text", {}, "div"));
  c.list.append(head);

  const caps = new Map<string, HTMLElement>();
  const drawActions = () => {
    const active = glyphSet(shell.settings.input.glyphs, shell.input.lastDevice);
    const padSet = active === "keyboard" ? "generic" : active;
    const conflicts = findConflicts(shell.settings.input.bindings);
    for (const action of REBINDABLE) {
      const box = caps.get(action);
      if (!box) continue;
      const lst = shell.settings.input.bindings[action] ?? [];
      const k = glyph(shell.i18n, glyphName("keyboard", lst[0] ?? ""), active === "keyboard" ? "active" : "");
      const p = glyph(shell.i18n, glyphName(padSet, lst[1] ?? ""), active === "keyboard" ? "" : "active");
      conflicts.forEach(([a, s]) => a === action && (s === 0 ? k : p).classList.add("conflict"));
      box.replaceChildren(k, p);
    }
    if (conflicts.length >= 2 && !c.status.textContent) {
      c.status.replaceChildren(tl(shell.i18n, "controls.conflict", "", { a: shell.i18n.t(`action.${conflicts[0][0]}`), b: shell.i18n.t(`action.${conflicts[1][0]}`) }));
    }
  };
  for (const action of REBINDABLE) {
    const e = el("div", "");
    const box = el("span", "value");
    caps.set(action, box);
    e.append(tl(shell.i18n, `action.${action}`), box);
    const item: Item = {
      id: `action.${action}`,
      el: e,
      accept: () => {
        box.replaceChildren(tl(shell.i18n, "controls.press", ""));
        shell.input.capture((binding) => {
          c.status.replaceChildren();
          if (binding) {
            const slot = binding.startsWith("key:") || binding.startsWith("mouse:") ? 0 : 1;
            const b = shell.settings.input.bindings;
            const lst = (b[action] = [...(b[action] ?? [])]);
            while (lst.length < slot) lst.push(""); // keep the keyboard/pad slot meaning
            const r = rebind(b, action, slot, binding);
            shell.settings.input.bindings = r.bindings;
            if (r.conflicts.length) {
              c.status.replaceChildren(tl(shell.i18n, "controls.swapped", "", { action: shell.i18n.t(`action.${r.conflicts[0][0]}`) }));
            }
          }
          drawActions();
        });
      },
    };
    c.list.append(c.menu.add(item).el);
  }
  c.list.append(c.menu.add(buttonItem(shell.i18n, "controls.reset", () => {
    shell.settings.input.bindings = structuredClone(DEFAULT_BINDINGS) as Settings["input"]["bindings"];
    c.status.replaceChildren();
    drawActions();
  })).el);
  // one-handed layouts (#166, motor access), from data/input/presets.json
  const presets = presetData.presets as Record<string, { bindings: Record<string, string[]> }>;
  for (const name of Object.keys(presets)) {
    c.list.append(c.menu.add(buttonItem(shell.i18n, `controls.preset.${name}`, () => {
      const b = structuredClone(DEFAULT_BINDINGS) as Record<string, string[]>;
      for (const [action, pair] of Object.entries(presets[name].bindings)) b[action] = [...pair];
      shell.settings.input.bindings = b as Settings["input"]["bindings"];
      c.status.replaceChildren(tl(shell.i18n, "controls.preset_done", "text"));
      drawActions();
    })).el);
  }
  drawActions();
}

function section(c: Ctx, tab: (typeof TABS)[number]): void {
  const { shell } = c;
  switch (tab) {
    case "display":
      choiceRow(c, "display.mode", DISPLAY_MODES, (s) => s.display.mode, (s, v) => (s.display.mode = v), (v) => `opt.mode.${v}`, () => shell.applyDisplayMode());
      choiceRow(c, "display.frame_cap", FRAME_CAPS, (s) => s.display.frame_cap as (typeof FRAME_CAPS)[number], (s, v) => (s.display.frame_cap = v),
        (v) => (v === 0 ? "opt.frame_cap.0" : ["opt.fps", { n: v }]));
      numRow(c, "display.ui_scale", (s) => s.display.ui_scale, (s, v) => (s.display.ui_scale = v), 0.75, 2.0, 0.25, times);
      break;
    case "audio":
      for (const k of ["master", "music", "sfx", "ui", "voice"] as const) {
        numRow(c, `audio.${k}`, (s) => s.audio[k], (s, v) => (s.audio[k] = v), 0, 1, 0.1, pct);
      }
      boolRow(c, "audio.mono", (s) => s.audio.mono, (s, v) => (s.audio.mono = v));
      break;
    case "controls":
      controls(c);
      break;
    case "access": {
      const a = (s: Settings) => s.access;
      numRow(c, "access.text_scale", (s) => a(s).text_scale, (s, v) => (a(s).text_scale = v), 0.75, 2.0, 0.25, times);
      boolRow(c, "access.subtitles", (s) => a(s).subtitles, (s, v) => (a(s).subtitles = v));
      choiceRow(c, "access.subtitle_size", SUB_SIZES, (s) => a(s).subtitle_size, (s, v) => (a(s).subtitle_size = v), (v) => `opt.sub.${v}`);
      numRow(c, "access.subtitle_background", (s) => a(s).subtitle_background, (s, v) => (a(s).subtitle_background = v), 0, 1, 0.1, pct);
      for (const k of ["speaker_names", "subtitle_barks", "captions_sfx"] as const) boolRow(c, `access.${k}`, (s) => a(s)[k], (s, v) => (a(s)[k] = v));
      choiceRow(c, "access.colorblind", COLORBLIND, (s) => a(s).colorblind, (s, v) => (a(s).colorblind = v), (v) => `opt.cb.${v}`);
      boolRow(c, "access.reduce_motion", (s) => a(s).reduce_motion, (s, v) => (a(s).reduce_motion = v));
      numRow(c, "access.shake_scale", (s) => a(s).shake_scale, (s, v) => (a(s).shake_scale = v), 0, 1, 0.1, pct);
      for (const k of ["flash_limit", "hold_to_toggle"] as const) boolRow(c, `access.${k}`, (s) => a(s)[k], (s, v) => (a(s)[k] = v));
      choiceRow(c, "access.difficulty", DIFFICULTIES, (s) => a(s).difficulty, (s, v) => (a(s).difficulty = v), (v) => `opt.diff.${v}`);
      numRow(c, "access.game_speed", (s) => a(s).game_speed, (s, v) => (a(s).game_speed = v), 0.5, 1.0, 0.1, pct);
      // #167 cognitive and #166 motor access
      boolRow(c, "access.readable_font", (s) => a(s).readable_font, (s, v) => (a(s).readable_font = v));
      numRow(c, "access.line_spacing", (s) => a(s).line_spacing, (s, v) => (a(s).line_spacing = v), 1, 2, 0.25, times);
      boolRow(c, "access.subtitle_hold", (s) => a(s).subtitle_hold, (s, v) => (a(s).subtitle_hold = v));
      numRow(c, "access.timing_scale", (s) => a(s).timing_scale, (s, v) => (a(s).timing_scale = v), 1, 3, 0.5, times);
      boolRow(c, "access.auto_repeat", (s) => a(s).auto_repeat, (s, v) => (a(s).auto_repeat = v));
      boolRow(c, "access.narration", (s) => a(s).narration, (s, v) => (a(s).narration = v)); // #165
      break;
    }
    case "language": {
      const locales = shell.i18n.locales.filter((l) => l !== PSEUDO_LOCALE || shell.debugBuild || shell.settings.language === PSEUDO_LOCALE);
      choiceRow(c, "language.language", locales, (s) => (locales.includes(s.language) ? s.language : locales[0]), (s, v) => (s.language = v), (v) => `lang.${v}`,
        () => shell.rerender());
      choiceRow(c, "telemetry.consent", CONSENT, (s) => s.telemetry.consent, (s, v) => (s.telemetry.consent = v), (v) => `opt.consent.${v}`);
      c.list.append(c.menu.add(buttonItem(shell.i18n, "data.export", () => shell.exportData())).el);
      break;
    }
  }
}

export function settingsScreen(shell: Shell): Screen {
  const root = el("section", "screen dim");
  root.dataset.screen = "settings";
  const leave = () => {
    shell.saveSettings();
    shell.back();
  };
  const s: Screen = { id: "settings", root, cancel: leave };
  s.render = () => {
    root.replaceChildren();
    const menu = new Menu();
    s.menu = menu;
    const p = el("div", "panel");
    p.dataset.box = "";
    p.append(tl(shell.i18n, "settings.title", "heading", {}, "div"));

    const tabs = el("div", "tabs");
    TABS.forEach((t, i) => {
      const e = tl(shell.i18n, `tab.${t}`, "tab" + (i === shell.settingsTab ? " current" : ""));
      e.addEventListener("click", (ev) => {
        ev.stopPropagation();
        switchTab(i - shell.settingsTab);
      });
      tabs.append(e);
    });
    const switchTab = (d: number) => {
      shell.settingsTab = (shell.settingsTab + d + TABS.length) % TABS.length;
      shell.rerender();
    };
    const tabItem: Item = { id: "settings.tabs", el: el("div", ""), left: () => switchTab(-1), right: () => switchTab(1) };
    tabItem.el.append(tabs);
    tabItem.el.style.justifyContent = "center";

    const list = el("div", "list");
    const status = el("div", "status");
    const c: Ctx = { shell, menu, list, status };
    p.append(menu.add(tabItem).el, list);
    section(c, TABS[shell.settingsTab]);
    p.append(status, menu.add(buttonItem(shell.i18n, "settings.back", leave)).el);
    root.append(p);
    menu.render();
  };
  s.render();
  return s;
}

// {{FOOTER}}
