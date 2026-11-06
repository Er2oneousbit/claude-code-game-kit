// ---------------------------------------------------------------------------
// drive.ts
// Purpose : Scripted runs for `dev.py smoke --drive <scenario>`: the game plays itself through the real input
//           path (injected actions, the same route a key press takes) and logs markers smoke waits for.
// Usage   : ?drive=menus | crash | pseudo | pseudo-plant | show:<title|settings|pause|subtitle|juice>
//           | access[:res=WxH][,scale=N][,pad] (every screen reported for tools/access/sweep.py)
//           (dev.py smoke --drive X adds it to the URL; --locale pseudo adds ?locale=pseudo)
// Notes   : Browser only. Every scenario ends with DRIVE_DONE <scenario>; a failed step logs DRIVE_ABORT (an
//           error, so smoke exits 1). Markers: SETTINGS_WRITTEN <file> (menus), CRASH_WRITTEN <file> (crash),
//           PSEUDO_OK / PSEUDO_FAIL (pseudo), SHOWN <screen> (show:*). Navigation walks the focus with
//           ui_down until the wanted item is focused, so the menus' keyboard navigation is part of the test.
//           A scenario rewrites settings and saves, so driveRequest() runs one only with its own ?data-dir=
//           (never the player's real keys) and only in a dev server or a browser under automation
//           (navigator.webdriver: Playwright, which dev.py smoke uses). A crafted ?drive= link to the hosted
//           game logs DRIVE_IGNORED and changes nothing. ?debug does not count: anyone can add it to a link.
//
// Pseudocode:
//   menus : title (consent: Later) -> menu -> settings -> Audio: master -> 0.5 (left or right from whatever the
//           data folder held) -> Accessibility:
//           reduce motion on -> back (saves) -> read settings.json back -> quit
//   crash : menu -> play -> a planted error in the next frame (the crash hook does the rest)
//   pseudo: every screen and settings section once; the shell checks each one as it appears (PSEUDO_SCREEN
//           <id> labels N per check); the "saved" toast is counted on the menu only, then waited out, and the
//           juice demo's subtitle (skipped while it types) is finished and checked again; the subtitle clock
//           stands still for the tour (holdTime), so the count is the same on every run of a build, however
//           long loading takes
//   show  : open one screen, settle, freeze the game, SHOWN <screen> (smoke takes the screenshot)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { glyphName, glyphSet, promptBinding } from "../core/bindings";
import { PSEUDO_LOCALE } from "../core/i18n";
import { Log } from "../core/log";
import { settingsLoad } from "../core/settings";
import { DATA_DIR_PARAM, dataPrefix } from "../core/textStore";
import { accessScreen } from "./accessAudit";
import type { Shell } from "./app";
import { MAX_SLIDER_STEPS, MENU_TARGET, slideAction } from "./driveLogic";
import { SETTINGS_FILE } from "./meta";
import { TABS } from "./settingsScreen";
import { glyphText } from "./ui";

// ---- Tunables ----------------------------------------------------------------
const WAIT_MS = 8000; // longest wait for one screen
const STEP_FRAMES = 2; // frames after each injected press (DOM and layout settle)
export const DRIVE_PARAM = "drive";

/**
 * The scenario this page may run: "" when none was asked for or it is refused (then `refused` says why).
 * realPrefix is the player's own key prefix; trusted = a dev server or an automated browser.
 */
export function driveRequest(search: string, realPrefix: string, trusted: boolean): { scenario: string; refused: string } {
  const asked = new URLSearchParams(search).get(DRIVE_PARAM) ?? "";
  if (!asked) return { scenario: "", refused: "" };
  if (dataPrefix(search, realPrefix) === realPrefix) {
    return { scenario: "", refused: `needs its own ?${DATA_DIR_PARAM}= (a scenario rewrites settings and saves)` };
  }
  if (!trusted) return { scenario: "", refused: "runs only in a dev server or an automated browser (dev.py smoke)" };
  return { scenario: asked, refused: "" };
}

const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));

async function frames(n: number): Promise<void> {
  for (let i = 0; i < n; i++) await frame();
}

async function waitFor(what: string, ok: () => boolean, ms = WAIT_MS): Promise<void> {
  const end = performance.now() + ms;
  while (!ok()) {
    if (performance.now() > end) throw new Error(`timed out waiting for ${what}`);
    await frame();
  }
}

class Driver {
  /** The access drive's gamepad-only run: every press is the action's gamepad binding. */
  pad = false;

  constructor(private readonly shell: Shell) {}

  async press(action: string): Promise<void> {
    if (this.pad) {
      if (!this.shell.input.injectPad(action)) throw new Error(`${action} has no gamepad binding: a gamepad-only player cannot press it`);
    } else if (!this.shell.input.inject(action)) throw new Error(`action ${action} has no binding`);
    await frames(STEP_FRAMES);
  }

  async screen(id: string): Promise<void> {
    await waitFor(`screen "${id}" (now "${this.shell.topId}")`, () => this.shell.topId === id);
    await frames(STEP_FRAMES);
  }

  /** Moves the focus down until item id is focused (wraps once around). */
  async focus(id: string): Promise<void> {
    const menu = this.shell.top?.menu;
    if (!menu || !menu.items.some((i) => i.id === id)) throw new Error(`no item "${id}" on screen "${this.shell.topId}"`);
    for (let n = 0; n <= menu.items.length && menu.focused?.id !== id; n++) await this.press("ui_down");
    if (menu.focused?.id !== id) throw new Error(`could not focus "${id}"`);
  }

  async choose(screen: string, id: string): Promise<void> {
    await this.screen(screen);
    await this.focus(id);
    await this.press("ui_accept");
  }

  /** Title up, the consent question (if any) answered with Later. */
  async pastConsent(): Promise<void> {
    await waitFor("title", () => ["title", "consent"].includes(this.shell.topId));
    await frames(STEP_FRAMES);
    if (this.shell.topId === "consent") await this.choose("consent", "consent.later");
    await this.screen("title");
  }

  async toMenu(): Promise<void> {
    await this.pastConsent();
    await this.press("ui_accept"); // "press any key"
    await this.screen("menu");
  }

  async tab(name: (typeof TABS)[number]): Promise<void> {
    await this.focus("settings.tabs");
    for (let n = 0; n < TABS.length && TABS[this.shell.settingsTab] !== name; n++) await this.press("ui_right");
    if (TABS[this.shell.settingsTab] !== name) throw new Error(`could not open settings section ${name}`);
  }

  /** Presses left or right on a slider row until read() equals target, from any start value. */
  async slideTo(id: string, read: () => number, target: number): Promise<void> {
    await this.focus(id);
    for (let n = 0; n < MAX_SLIDER_STEPS; n++) {
      const action = slideAction(read(), target);
      if (!action) return;
      await this.press(action);
    }
    if (slideAction(read(), target)) throw new Error(`${id} did not reach ${target} (is ${read()})`);
  }

  /** Steps a value row with ui_left / ui_right until read() gives want. */
  async setValue(id: string, read: () => unknown, want: unknown, dir: "ui_left" | "ui_right"): Promise<void> {
    await this.focus(id);
    for (let n = 0; n < 40 && read() !== want; n++) await this.press(dir);
    if (read() !== want) throw new Error(`${id} did not reach ${String(want)} (is ${String(read())})`);
  }

  async game(key: "main" | "juice"): Promise<void> {
    this.shell.startGame(key);
    await this.screen(key === "main" ? "play" : "juice");
    await frames(10);
  }

  async pseudoWait(): Promise<void> {
    await frames(STEP_FRAMES);
    await waitFor("pseudo checks", () => !this.shell.checksPending);
  }

  /** Waits until every toast has timed out, so no later screen check depends on how long a step took. */
  async toastsGone(): Promise<void> {
    await waitFor("the toasts to leave", () => this.shell.toastCount === 0);
  }
}

async function menus(shell: Shell, d: Driver): Promise<void> {
  await d.toMenu();
  await d.choose("menu", "menu.settings");
  await d.screen("settings");
  await d.tab("audio");
  await d.slideTo("audio.master", () => shell.settings.audio.master, MENU_TARGET.master);
  await d.tab("access");
  await d.setValue("access.reduce_motion", () => shell.settings.access.reduce_motion, MENU_TARGET.reduceMotion, "ui_right");
  await d.press("ui_cancel"); // back saves
  await d.screen("menu");
  const { settings, problems } = settingsLoad(shell.store.read(SETTINGS_FILE));
  if (problems.length || slideAction(settings.audio.master, MENU_TARGET.master) || settings.access.reduce_motion !== MENU_TARGET.reduceMotion) {
    throw new Error(`${SETTINGS_FILE} does not hold the new values (master ${settings.audio.master}, reduce_motion ${settings.access.reduce_motion})`);
  }
  await d.choose("menu", "menu.quit");
  await d.screen("quit");
}

async function crash(shell: Shell, d: Driver): Promise<void> {
  await d.toMenu();
  await d.choose("menu", "menu.play");
  await d.screen("play");
  shell.plantedCrash = true; // the play scene throws in its next update; the crash hook logs DRIVE_DONE crash
  await waitFor("the crash screen", () => shell.topId === "crash");
}

async function pseudoTour(shell: Shell, d: Driver): Promise<void> {
  if (shell.i18n.locale !== PSEUDO_LOCALE) throw new Error("this scenario needs the pseudo-locale: add --locale pseudo");
  // Subtitles stand still for the whole tour, so each check sees the same subtitle state on a fast or a slow
  // machine: the line the juice demo says while loading stays untyped (skipped), the finished one stays up
  shell.subtitles.holdTime = true;
  try {
    await pseudoSteps(shell, d);
  } finally {
    shell.subtitles.holdTime = false;
  }
  const c = shell.checks;
  if (c.failures.length) Log.error("i18n", `PSEUDO_FAILED ${c.failures.length} problem(s) on ${c.screens} screen check(s)`);
  else Log.info("i18n", `PSEUDO_OK ${c.screens} screen check(s), ${c.labels} label(s), nothing truncated`);
}

async function pseudoSteps(shell: Shell, d: Driver): Promise<void> {
  await d.pastConsent();
  await d.pseudoWait();
  await d.press("ui_accept");
  await d.screen("menu");
  await d.pseudoWait();
  await d.choose("menu", "menu.settings");
  await d.screen("settings");
  for (const t of TABS) {
    await d.tab(t);
    await d.pseudoWait();
  }
  await d.press("ui_cancel"); // back saves: the "saved" toast is checked on the menu, then left to go
  await d.screen("menu");
  await d.pseudoWait();
  await d.toastsGone();
  await d.choose("menu", "menu.credits");
  await d.screen("credits");
  await d.pseudoWait();
  await d.press("ui_cancel");
  await d.screen("menu");
  await d.game("juice");
  shell.subtitles.say("demo.welcome");
  shell.subtitles.finish(); // a line still typing is skipped by the check: check the whole line once more
  if (shell.top) shell.checkLayout(shell.top);
  await d.pseudoWait();
  await d.press("pause");
  await d.screen("pause");
  await d.pseudoWait();
  await d.choose("pause", "pause.quit");
  await d.toMenu();
  await d.choose("menu", "menu.play"); // the loading screen is checked on the way
  await d.screen("play");
  await d.pseudoWait();
  await d.press("pause");
  await d.choose("pause", "pause.quit");
  await d.toMenu();
  await d.choose("menu", "menu.quit");
  await d.screen("quit");
  await d.pseudoWait();
}

async function show(shell: Shell, d: Driver, what: string): Promise<void> {
  switch (what) {
    case "title":
      await d.pastConsent();
      break;
    case "settings":
      await d.toMenu();
      await d.choose("menu", "menu.settings");
      await d.screen("settings");
      await d.tab("audio");
      await d.focus("audio.master"); // a control with visible focus
      break;
    case "pause":
      await d.toMenu();
      await d.game("main");
      await d.press("pause");
      await d.screen("pause");
      break;
    case "subtitle":
    case "juice":
      await d.toMenu();
      await d.game("juice");
      if (what === "subtitle") {
        shell.subtitles.say("demo.welcome");
        shell.subtitles.finish();
      } else {
        await d.press("attack"); // the box is in reach at the start: shake, hitstop, squash, flash
        await frames(4);
      }
      if (shell.scene) shell.game?.scene.pause(shell.scene); // a still frame for the screenshot
      break;
    default:
      throw new Error(`unknown screen "${what}" (title, settings, pause, subtitle, juice)`);
  }
  await frames(STEP_FRAMES);
  Log.info("drive", `SHOWN ${what}`);
}

/** Runs one scenario; resolves after DRIVE_DONE (or throws, and the caller logs DRIVE_ABORT). */
// ---- the accessibility sweep (#91, #85): access[:res=WxH][,scale=N][,pad] -------------------------------------
const ACCESS_ACTIONS = ["ui_up", "ui_down", "ui_left", "ui_right", "ui_accept", "ui_cancel", "pause"];
const PROMPT_ACTIONS = ["move_left", "move_right", "jump", "attack", "interact", "pause"];
const OVER_GAME = ["play", "juice", "pause"];

async function reach(shell: Shell, d: Driver): Promise<Record<string, unknown>> {
  const menu = shell.top?.menu;
  if (!menu) return { start: "", controls: 0, reached: 0, unreached: [], focus_like_hover: [] };
  const want = menu.items.map((i) => i.id);
  const start = menu.focused?.id ?? "";
  const seen = new Set<string>();
  for (let n = 0; n <= want.length; n++) {
    if (menu.focused) seen.add(menu.focused.id);
    await d.press("ui_down");
  }
  return { start, controls: want.length, reached: want.filter((id) => seen.has(id)).length,
           unreached: want.filter((id) => !seen.has(id)), focus_like_hover: [] };
}

async function report(shell: Shell, d: Driver, name: string): Promise<void> {
  await frames(STEP_FRAMES);
  const root = document.getElementById("shell") ?? document.body;
  const r = accessScreen(root, name, OVER_GAME.includes(shell.topId));
  r.focus = await reach(shell, d);
  Log.info("drive", "ACCESS_SCREEN " + JSON.stringify(r));
}

async function access(shell: Shell, d: Driver, options: string): Promise<void> {
  let scale = 1;
  let read = false;
  for (const part of options.split(",").filter(Boolean)) {
    if (part === "pad") d.pad = true;
    else if (part === "read") read = true; // the readable font and double line spacing (#167)
    else if (part.startsWith("scale=")) scale = Number(part.slice(6));
    else if (!part.startsWith("res=")) throw new Error(`unknown access option ${part} (res=WxH, scale=N, pad, read)`);
  }
  const actions: Record<string, { keyboard: boolean; gamepad: boolean }> = {};
  for (const a of ACCESS_ACTIONS) {
    const list = shell.settings.input.bindings[a] ?? [];
    actions[a] = { keyboard: list.some((b) => b.startsWith("key:")), gamepad: list.some((b) => b.startsWith("pad")) };
  }
  Log.info("drive", "ACCESS_INPUT " + JSON.stringify({ pad: d.pad, text_scale: scale, actions }));
  await waitFor("title", () => ["title", "consent"].includes(shell.topId));
  if (scale !== 1 || read) {
    shell.settings.access.text_scale = scale;
    if (read) {
      shell.settings.access.readable_font = true;
      shell.settings.access.line_spacing = 2;
    }
    shell.apply();
  }
  await report(shell, d, shell.topId);
  await d.pastConsent();
  await d.press("ui_accept");
  await d.screen("menu");
  await report(shell, d, "main_menu");
  await d.choose("menu", "menu.settings");
  await d.screen("settings");
  for (const t of TABS) {
    await d.tab(t);
    await report(shell, d, "settings/" + t);
    if (t === "controls") { // the one-handed layout (#166), live, then reset
      await d.focus("controls.preset.one_hand_left");
      await d.press("ui_accept");
      const applied = shell.settings.input.bindings.attack[0] === "key:f";
      await d.focus("controls.reset");
      await d.press("ui_accept");
      Log.info("drive", "ACCESS_PRESET " + JSON.stringify({ applied, reset: shell.settings.input.bindings.attack[0] === "key:j" }));
    }
  }
  await d.press("ui_cancel");
  await d.screen("menu");
  await d.toastsGone();
  await d.choose("menu", "menu.credits");
  await d.screen("credits");
  await report(shell, d, "credits");
  await d.press("ui_cancel");
  await d.screen("menu");
  await d.game("juice");
  shell.subtitles.say("demo.welcome");
  shell.subtitles.finish();
  await frames(STEP_FRAMES);
  await report(shell, d, "juice");
  Log.info("drive", "ACCESS_SUBTITLE " + JSON.stringify(shell.subtitles.shown()));
  const set = glyphSet(shell.settings.input.glyphs, shell.input.lastDevice);
  const rows: Record<string, { keyboard: string; shown: string }> = {};
  for (const a of PROMPT_ACTIONS) {
    const b = shell.settings.input.bindings;
    rows[a] = { keyboard: glyphText(shell.i18n, glyphName("keyboard", promptBinding(b, a, "keyboard"))),
                shown: glyphText(shell.i18n, glyphName(set, promptBinding(b, a, set))) };
  }
  Log.info("drive", "ACCESS_PROMPTS " + JSON.stringify({ device: shell.input.lastDevice, glyphs: set, actions: rows }));
  // subtitle_hold (#167), live: a finished line stays until accept, then goes
  shell.settings.access.subtitle_hold = true;
  shell.subtitles.dismiss();
  shell.subtitles.say("demo.welcome");
  await waitFor("the line to finish", () => shell.subtitles.holding(), 20000);
  const held = shell.subtitles.holding();
  await d.press("ui_accept");
  Log.info("drive", "ACCESS_HOLD " + JSON.stringify({ held, dismissed: !shell.subtitles.holding() && shell.subtitles.shown().text === "" }));
  shell.settings.access.subtitle_hold = false;
  await d.press("pause");
  await d.screen("pause");
  await report(shell, d, "pause");
  for (const page of ["help", "history"]) { // #167: both reachable and readable
    await d.choose("pause", `pause.${page}`);
    await d.screen(page);
    await report(shell, d, page);
    await d.press("ui_cancel");
    await d.screen("pause");
  }
  await d.choose("pause", "pause.quit");
  await d.pastConsent();
}

export async function runDrive(shell: Shell, scenario: string): Promise<void> {
  const d = new Driver(shell);
  Log.info("drive", `DRIVE_START ${scenario}`);
  if (scenario === "menus") await menus(shell, d);
  else if (scenario === "crash") return crash(shell, d);
  else if (scenario === "pseudo" || scenario === "pseudo-plant") await pseudoTour(shell, d);
  else if (scenario.startsWith("show:")) await show(shell, d, scenario.slice(5));
  else if (scenario === "access" || scenario.startsWith("access:")) await access(shell, d, scenario.slice(7));
  else throw new Error(`unknown scenario "${scenario}" (menus, crash, pseudo, pseudo-plant, access[:...], show:<screen>)`);
  Log.info("drive", `DRIVE_DONE ${scenario}`);
}
