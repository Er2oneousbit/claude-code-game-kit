// ---------------------------------------------------------------------------
// screens.ts
// Purpose : The front end's screens, built in code: boot, title (with the one-time telemetry question),
//           main menu, credits, loading, the gameplay HUD (play and juice demo), pause, quit and crash.
//           The settings screen lives in settingsScreen.ts.
// Usage   : shell.reset(screens.title(shell)) ; shell.push(screens.pause(shell)) ...
// Notes   : Browser only (DOM). Every string goes through tl() (tr) or val() (data), every panel is a
//           [data-box] for the pseudo-locale check. ui_cancel goes back one screen everywhere it can.
//           CREDITS.md at the project root (if present) is bundled and scrolls on the credits screen, without its
//           HTML comments (credits.ts).
//           Ghost Lantern: the main menu also has the difficulty (left/right, a one-line hint under it), the same
//           setting as Settings > Accessibility, saved when the player leaves the menu.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the loading screen starts the world through the
//           shell's GameHost, so web and web-3d share this file; pseudo-plant's label stays on one line, so the
//           pseudo check fails on it as it must (it wrapped and passed) (#175)
// ---------------------------------------------------------------------------
import { glyphName, glyphSet, promptBinding } from "../core/bindings";
import { DIFFICULTIES } from "../core/settings";
import type { Screen, Shell } from "./app";
import { creditsText } from "./credits";
import type { GameKey } from "./host";
import { GAME_NAME, GAME_VERSION } from "./meta";
import { settingsScreen } from "./settingsScreen";
import { Menu, buttonItem, el, glyph, glyphText, tl, val, valueRow } from "./ui";

// ---- Tunables ----------------------------------------------------------------
const LOADING_MIN_S = 0.6; // the bar is visible at least this long (no flash of a loading screen)
const CREDITS_SPEED = 24; // pixels per second of auto-scroll (0 with reduce motion)
const HUD_ACTIONS = ["move_left", "move_right", "jump", "attack", "interact", "pause"];

const credits = import.meta.glob("/CREDITS.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

function screenEl(id: string, cls = "dim"): HTMLElement {
  const s = el("section", ("screen " + cls).trim());
  s.dataset.screen = id;
  return s;
}

function panel(cls = ""): HTMLElement {
  const p = el("div", ("panel " + cls).trim());
  p.dataset.box = "";
  return p;
}

/** A screen whose content is rebuilt by build() (on language change too). */
function built(id: string, cls: string, build: (root: HTMLElement, menu: Menu) => void, extra: Partial<Screen> = {}): Screen {
  const root = screenEl(id, cls);
  const s: Screen = { id, root, ...extra };
  s.render = () => {
    root.replaceChildren();
    s.menu = new Menu();
    build(root, s.menu);
    s.menu.render();
  };
  s.render();
  return s;
}

export function boot(shell: Shell): Screen {
  return built("boot", "dim", (root) => {
    root.append(tl(shell.i18n, "boot.loading", "press muted", {}, "div"));
  });
}

export function title(shell: Shell): Screen {
  const s = built("title", "", (root) => {
    const col = el("div", "");
    col.style.textAlign = "center";
    col.append(tl(shell.i18n, "game.title", "bigtitle", { name: GAME_NAME }, "div"), tl(shell.i18n, "title.press", "press blink", {}, "div"));
    root.append(col, tl(shell.i18n, "version", "corner", { v: GAME_VERSION }, "div"));
    root.addEventListener("click", () => shell.topId === "title" && shell.replace(menu(shell)));
  }, {
    onAnyPress: () => {
      shell.replace(menu(shell));
      return true;
    },
    enter: () => {
      if (shell.settings.telemetry.consent === "unset" && !shell.consentAsked) {
        shell.consentAsked = true; // once per launch while undecided ("Later" asks again next time)
        queueMicrotask(() => shell.push(consent(shell)));
      }
    },
  });
  return s;
}

export function consent(shell: Shell): Screen {
  const choose = (value: "yes" | "no" | "unset") => {
    shell.settings.telemetry.consent = value;
    if (value !== "unset") shell.saveSettings();
    shell.back();
  };
  return built("consent", "dim", (root, m) => {
    const p = panel("narrow");
    p.append(tl(shell.i18n, "consent.title", "heading", {}, "div"), tl(shell.i18n, "consent.body", "text", {}, "div"));
    const row = el("div", "row");
    m.horizontal = true; // a row of buttons: left/right move between them too
    for (const [key, value] of [["consent.yes", "yes"], ["consent.no", "no"], ["consent.later", "unset"]] as const) {
      row.append(m.add(buttonItem(shell.i18n, key, () => choose(value))).el);
    }
    p.append(row);
    root.append(p);
  }, { cancel: () => choose("unset") });
}

/** The difficulty on the main menu: "< Normal >" plus a hint line. Returns a save-if-changed for leaving the menu. */
function difficultyRow(shell: Shell, m: Menu, list: HTMLElement): () => void {
  const a = shell.settings.access;
  const saved = a.difficulty;
  let hint = tl(shell.i18n, `diff.hint.${a.difficulty}`, "muted hint", {}, "div");
  const row = valueRow(shell.i18n, "access.difficulty", () => change(-1), () => change(1));
  const draw = () => row.set(shell.i18n.t(`opt.diff.${a.difficulty}`), true);
  const change = (d: number) => {
    const i = Math.max(0, DIFFICULTIES.indexOf(a.difficulty as (typeof DIFFICULTIES)[number]));
    a.difficulty = DIFFICULTIES[(i + d + DIFFICULTIES.length) % DIFFICULTIES.length];
    draw();
    const next = tl(shell.i18n, `diff.hint.${a.difficulty}`, "muted hint", {}, "div");
    hint.replaceWith(next);
    hint = next;
    const top = shell.top;
    if (top) shell.checkLayout(top); // the pseudo-locale check sees the new hint too
  };
  draw();
  list.append(m.add(row.item).el, hint);
  return () => {
    if (a.difficulty !== saved) shell.saveSettings();
  };
}

export function menu(shell: Shell): Screen {
  let leave = () => {};
  return built("menu", "dim", (root, m) => {
    const p = panel("narrow");
    p.append(tl(shell.i18n, "game.title", "heading", { name: GAME_NAME }, "div"));
    const list = el("div", "list");
    const add = (key: string, fn: () => void) => list.append(m.add(buttonItem(shell.i18n, key, fn)).el);
    add("menu.play", () => shell.startGame("main"));
    leave = difficultyRow(shell, m, list);
    add("menu.settings", () => shell.push(settingsScreen(shell)));
    add("menu.credits", () => shell.push(creditsScreen(shell)));
    if (shell.debugBuild) add("menu.juice", () => shell.startGame("juice"));
    add("menu.quit", () => shell.quit());
    p.append(list);
    if (shell.drive === "pseudo-plant") {
      // a label far too small for its text, on one line: .label wraps anywhere, and a wrapped label fits (#175)
      const planted = tl(shell.i18n, "menu.settings", "label", {}, "div");
      planted.dataset.id = "plant.too_small"; // the name every engine's pseudo-plant drive reports
      planted.style.width = "2.5em";
      planted.style.whiteSpace = "nowrap";
      planted.style.overflow = "hidden";
      p.append(planted);
    }
    root.append(p, tl(shell.i18n, "version", "corner", { v: GAME_VERSION }, "div"));
  }, { cancel: () => shell.reset(title(shell)), leave: () => leave() });
}

export function creditsScreen(shell: Shell): Screen {
  let box: HTMLElement | null = null;
  return built("credits", "dim", (root, m) => {
    const p = panel();
    p.append(tl(shell.i18n, "credits.title", "heading", {}, "div"));
    box = el("div", "credits");
    const text = creditsText(Object.values(credits)[0]); // HTML comments out (#279)
    box.append(text ? val(text, "credits-body", "credits.body") : tl(shell.i18n, "credits.placeholder", "credits-body", {}, "div"));
    p.append(box, m.add(buttonItem(shell.i18n, "credits.back", () => shell.back())).el);
    root.append(p);
  }, {
    cancel: () => shell.back(),
    onAction: (a) => {
      if (!box || (a !== "ui_up" && a !== "ui_down")) return false;
      box.scrollTop += a === "ui_down" ? 40 : -40;
      return true;
    },
    tick: (dt) => {
      if (!box || shell.settings.access.reduce_motion) return;
      box.scrollTop += CREDITS_SPEED * dt;
      if (box.scrollTop + box.clientHeight >= box.scrollHeight - 1) box.scrollTop = 0;
    },
  });
}

export function loading(shell: Shell, key: GameKey): Screen {
  let fill: HTMLElement | null = null;
  let pct: HTMLElement | null = null;
  let t = 0;
  let loaded = 0;
  let started = false;
  let created = false;
  const s = built("loading", "dim", (root) => {
    const p = panel("narrow");
    const bar = el("div", "bar");
    fill = el("div", "fill");
    bar.append(fill);
    pct = val("0 %", "muted");
    p.append(tl(shell.i18n, "loading.title", "heading", {}, "div"), bar, pct);
    root.append(p);
  }, {
    enter: () => {
      const host = shell.host;
      if (!host || started) return;
      started = true;
      host.start(key, (v) => (loaded = v), () => {
        loaded = 1;
        created = true;
      });
    },
    tick: (dt) => {
      t += dt;
      const shown = Math.min(loaded, t / LOADING_MIN_S, 1);
      if (fill) fill.style.width = `${Math.round(shown * 100)}%`;
      if (pct) pct.textContent = `${Math.round(shown * 100)} %`;
      if (created && shown >= 1) shell.enterGame(key);
    },
  });
  return s;
}

/** The HUD over a running world: prompts with glyphs for the current device. */
export function gameplay(shell: Shell, key: GameKey): Screen {
  let lastSet = "";
  const s = built(key === "main" ? "play" : "juice", "hud", (root) => {
    const hud = el("div", "hudbar");
    const set = glyphSet(shell.settings.input.glyphs, shell.input.lastDevice);
    lastSet = set;
    for (const action of key === "main" ? ["pause"] : HUD_ACTIONS) {
      const pr = el("span", "prompt");
      pr.append(glyph(shell.i18n, glyphName(set, promptBinding(shell.settings.input.bindings, action, set))), tl(shell.i18n, `action.${action}`, ""));
      hud.append(pr);
    }
    root.append(hud);
  }, {
    gameplay: true,
    onAction: (a) => {
      if (a !== "pause") return false;
      shell.pauseGame();
      return true;
    },
    tick: () => {
      // prompts follow the last device used (keyboard <-> gamepad)
      if (glyphSet(shell.settings.input.glyphs, shell.input.lastDevice) !== lastSet) shell.rerender();
    },
  });
  return s;
}

export function pause(shell: Shell): Screen {
  return built("pause", "dim", (root, m) => {
    const p = panel("narrow");
    p.append(tl(shell.i18n, "pause.title", "heading", {}, "div"));
    const list = el("div", "list");
    list.append(
      m.add(buttonItem(shell.i18n, "pause.resume", () => shell.resumeGame())).el,
      m.add(buttonItem(shell.i18n, "pause.help", () => shell.push(helpScreen(shell)))).el, // #167
      m.add(buttonItem(shell.i18n, "pause.history", () => shell.push(historyScreen(shell)))).el,
      m.add(buttonItem(shell.i18n, "pause.settings", () => shell.push(settingsScreen(shell)))).el,
      m.add(buttonItem(shell.i18n, "pause.quit", () => shell.quitToTitle())).el,
    );
    p.append(list);
    root.append(p);
  }, { cancel: () => shell.resumeGame() });
}

/** A page of wrapped lines that up and down scroll, with Back: "What now?" and the dialogue history (#167). */
function textPage(shell: Shell, id: string, titleKey: string, fill: (box: HTMLElement) => void, atEnd = false): Screen {
  let box: HTMLElement | null = null;
  return built(id, "dim", (root, m) => {
    const p = panel();
    p.append(tl(shell.i18n, titleKey, "heading", {}, "div"));
    box = el("div", "pagebox");
    fill(box);
    p.append(box, m.add(buttonItem(shell.i18n, "credits.back", () => shell.back())).el);
    root.append(p);
    if (atEnd) queueMicrotask(() => { if (box) box.scrollTop = box.scrollHeight; });
  }, {
    cancel: () => shell.back(),
    onAction: (a) => {
      if (!box || (a !== "ui_up" && a !== "ui_down")) return false;
      box.scrollTop += a === "ui_down" ? 40 : -40;
      return true;
    },
  });
}

/** "What now?" (#167, cognitive access): the goal, the last line said, and the controls for play. */
export function helpScreen(shell: Shell): Screen {
  return textPage(shell, "help", "help.title", (box) => {
    box.append(shell.objective ? tl(shell.i18n, "help.objective", "text", { text: shell.objective }, "div")
      : tl(shell.i18n, "help.no_objective", "text", {}, "div"));
    const last = shell.history[shell.history.length - 1];
    if (last) box.append(tl(shell.i18n, "help.last_line", "text", { name: last.name, text: last.text }, "div"));
    box.append(tl(shell.i18n, "help.controls", "text muted", {}, "div"));
    const set = glyphSet(shell.settings.input.glyphs, shell.input.lastDevice);
    for (const action of HUD_ACTIONS) {
      const key = glyphText(shell.i18n, glyphName(set, promptBinding(shell.settings.input.bindings, action, set)));
      box.append(val(`${shell.i18n.t(`action.${action}`)}: ${key}`, "text", `help.${action}`));
    }
  });
}

/** "Dialogue history" (#167, cognitive access): every line said so far, newest last, opened at the newest. */
export function historyScreen(shell: Shell): Screen {
  return textPage(shell, "history", "history.title", (box) => {
    if (!shell.history.length) box.append(tl(shell.i18n, "history.empty", "text", {}, "div"));
    for (const h of shell.history) box.append(tl(shell.i18n, "help.last_line", "text", { name: h.name, text: h.text }, "div"));
  }, true);
}

export function quit(shell: Shell): Screen {
  return built("quit", "dim", (root, m) => {
    const p = panel("narrow");
    p.append(tl(shell.i18n, "quit.title", "heading", {}, "div"), tl(shell.i18n, "quit.body", "text", {}, "div"));
    p.append(m.add(buttonItem(shell.i18n, "quit.again", () => shell.reset(title(shell)))).el);
    root.append(p);
  });
}

export function crashed(shell: Shell, file: string): Screen {
  return built("crash", "dim", (root) => {
    const p = panel("narrow");
    p.append(tl(shell.i18n, "crash.title", "heading", {}, "div"), tl(shell.i18n, "crash.body", "text", { file }, "div"));
    root.append(p);
  });
}
