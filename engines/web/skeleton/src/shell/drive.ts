// ---------------------------------------------------------------------------
// drive.ts
// Purpose : Scripted runs for `dev.py smoke --drive <scenario>`: the game plays itself through the real input
//           path (injected actions, the same route a key press takes) and logs markers smoke waits for.
// Usage   : ?drive=menus | crash | pseudo | pseudo-plant | show:<title|settings|pause|subtitle|juice>
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
import { PSEUDO_LOCALE } from "../core/i18n";
import { Log } from "../core/log";
import { settingsLoad } from "../core/settings";
import { DATA_DIR_PARAM, dataPrefix } from "../core/textStore";
import type { Shell } from "./app";
import { MAX_SLIDER_STEPS, MENU_TARGET, slideAction } from "./driveLogic";
import { SETTINGS_FILE } from "./meta";
import { TABS } from "./settingsScreen";

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
  constructor(private readonly shell: Shell) {}

  async press(action: string): Promise<void> {
    if (!this.shell.input.inject(action)) throw new Error(`action ${action} has no binding`);
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
export async function runDrive(shell: Shell, scenario: string): Promise<void> {
  const d = new Driver(shell);
  Log.info("drive", `DRIVE_START ${scenario}`);
  if (scenario === "menus") await menus(shell, d);
  else if (scenario === "crash") return crash(shell, d);
  else if (scenario === "pseudo" || scenario === "pseudo-plant") await pseudoTour(shell, d);
  else if (scenario.startsWith("show:")) await show(shell, d, scenario.slice(5));
  else throw new Error(`unknown scenario "${scenario}" (menus, crash, pseudo, pseudo-plant, show:<screen>)`);
  Log.info("drive", `DRIVE_DONE ${scenario}`);
}

// {{FOOTER}}
