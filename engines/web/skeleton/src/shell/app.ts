// ---------------------------------------------------------------------------
// app.ts
// Purpose : The front end ("shell") around the game: the screen stack (boot, title, consent, menu, settings,
//           credits, loading, play, pause, quit, crash), settings applied at runtime and saved atomically,
//           the user-data folder (localStorage under one prefix), the game log, the crash hook, consent-gated
//           telemetry, the F8 bug report, subtitles and the smoke driver.
// Usage   : import { shell } from "./shell/app"   (first import in main.ts: the crash hook goes in early)
//           shell.start(host) once the renderer is up (host.ts) ; the game reads shell.settings / shell.input /
//           shell.palette()
// Notes   : Browser only, no renderer import: the same file in the web and web-3d overlays (host.ts). The screens
//           are HTML over the canvas (real text layout, so text scaling, wrapping and the pseudo-locale check work
//           like any web page); the game itself runs in the host's worlds ("main" = play, "juice" = the juice
//           demo) with a still backdrop behind the menus.
//           URL parameters: ?debug (debug build: Juice demo, F8), ?locale=<id> (overrides the setting),
//           ?data-dir=<prefix> (user-data key prefix), ?drive=<scenario> (smoke, see drive.ts: only with its
//           own ?data-dir= and in a dev server or an automated browser, so a crafted link changes nothing).
//
// Pseudocode:
//   constructor: store (prefix) -> game log (rotate) -> crash hook -> settings (repair) -> i18n -> input
//   start(host): apply settings -> boot screen -> title (BOOT_OK) -> drive scenario if asked
//   every press: the top screen gets it (its own handler, then its menu, then ui_cancel = back)
//   every screen shown: telemetry "screen" event (if allowed), pseudo-locale check (if locale is pseudo)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a drive is the only input; the real keyboard, mouse
//           and pads are ignored while one runs (input.scripted, #276)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the renderer sits behind a GameHost (host.ts), so
//           web-3d runs the same shell over Three.js (#175)
// ---------------------------------------------------------------------------
import { atomicWrite } from "../core/atomicFile";
import { I18n, PSEUDO_LOCALE, type Tables } from "../core/i18n";
import { Log } from "../core/log";
import { SaveStore } from "../core/saveStore";
import { defaultSettings, settingsLoad, settingsText, telemetryAllowed, type Settings } from "../core/settings";
import { DEFAULT_DATA_PREFIX, MemoryStore, WebStorageStore, dataPrefix, type TextStore } from "../core/textStore";
import { GameLog, Telemetry, TAIL_LINES, stamp, writeCrash } from "../core/userData";
import { DRIVE_PARAM, driveRequest, runDrive } from "./drive";
import type { GameHost, GameKey } from "./host";
import { Narrator } from "./narrator";
import { ShellInput } from "./input";
import { checkScreen } from "./pseudoCheck";
import * as screens from "./screens";
import { SubtitleBar } from "./subtitles";
import { GAME_NAME, GAME_SLUG, GAME_VERSION, SETTINGS_FILE } from "./meta";
import { el, hasUiFile, tl, focusHooks } from "./ui";
import "./shell.css";

// ---- Tunables ----------------------------------------------------------------
export { GAME_NAME, GAME_VERSION, SETTINGS_FILE };
export const SAVE_SLOT = 1;
const THEME_FILE = "theme_default.css"; // public/assets/ui/<this>, loaded after the built-in style when present
const LOG_FLUSH_MS = 1000;
const TOAST_MS = 3500;
const MAX_HISTORY = 50; // subtitle lines the dialogue history keeps (#167)
const MAX_CRASH_FILES = 3; // per page load: a crash loop must not fill the storage
const MAX_DT = 0.1;
export const SUB_SIZE_EM: Record<string, number> = { small: 0.9, medium: 1.1, large: 1.4, xl: 1.8 };
export { PALETTES } from "./palettes";
import { PALETTES } from "./palettes";

export type Screen = {
  id: string;
  root: HTMLElement;
  menu?: import("./ui").Menu;
  /** Handles an action first; true = handled. */
  onAction?: (action: string) => boolean;
  /** Sees every press before actions are routed (title: any key). true = handled. */
  onAnyPress?: (binding: string) => boolean;
  /** ui_cancel: usually back one screen. */
  cancel?: () => void;
  enter?: () => void;
  leave?: () => void;
  tick?: (dt: number) => void;
  /** Rebuilds the DOM (language change). */
  render?: () => void;
  /** Play and juice: game input is live, focus loss pauses. */
  gameplay?: boolean;
};

function loadTables(): Tables {
  const files = import.meta.glob("../../data/i18n/*.json", { eager: true, import: "default" }) as Record<string, Record<string, string>>;
  const tables: Tables = {};
  for (const [path, table] of Object.entries(files)) tables[path.replace(/^.*\//, "").replace(/\.json$/, "")] = table;
  return tables;
}

function openStore(): TextStore {
  try {
    const s = new WebStorageStore(window.localStorage, dataPrefix(location.search));
    s.write(".probe", "1");
    s.remove(".probe");
    return s;
  } catch {
    Log.warn("core", "localStorage unavailable (private mode or blocked): settings and saves last until the tab closes");
    return new MemoryStore();
  }
}

/** Hands the player a file (the "downloadable file" side of the user-data folder). */
export function download(name: string, text: string, type = "application/json"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = el("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export class Shell {
  readonly params = new URLSearchParams(location.search);
  readonly debugBuild = import.meta.env.DEV || this.params.has("debug");
  /** The smoke scenario to run ("" = none, or refused: see driveRequest in drive.ts). */
  readonly drive: string;
  readonly store: TextStore;
  readonly log: GameLog;
  readonly i18n: I18n;
  readonly input: ShellInput;
  readonly telemetry: Telemetry;
  readonly saves: SaveStore;
  readonly subtitles: SubtitleBar;
  /** Cognitive access (#167): the goal "What now?" shows, and every subtitle line shown (newest last). */
  objective = "";
  /** The line the narrator last worked out (#165), spoken or not. */
  lastNarration = "";
  narrator!: Narrator;
  readonly history: { name: string; text: string }[] = [];

  /** The goal "What now?" on the pause menu shows; "" clears it. Pass translated text (i18n.t). */
  setObjective(text: string): void {
    this.objective = text;
  }

  /** Records a line the player saw (the subtitle bar calls it), for the history and "What now?". */
  recordLine(name: string, text: string): void {
    this.history.push({ name, text });
    if (this.history.length > MAX_HISTORY) this.history.shift();
  }
  settings: Settings;
  /** The renderer under the shell (null until start). */
  host: GameHost | null = null;
  /** The running gameplay world ("main" or "juice"), if any. */
  scene: GameKey | null = null;
  consentAsked = false;
  settingsTab = 0;
  plantedCrash = false;
  readonly checks = { screens: 0, labels: 0, failures: [] as string[] };
  seed: number | null = null;

  private readonly rootEl: HTMLElement;
  private readonly screensEl: HTMLElement;
  private readonly toastsEl: HTMLElement;
  private stack: Screen[] = [];
  private crashes = 0;
  private lastT = 0;
  private lastFlush = 0;
  private frameCap = -1;
  private pendingChecks = 0;

  constructor() {
    this.store = openStore();
    this.log = new GameLog(this.store, `${GAME_NAME} ${GAME_VERSION}`);
    Log.addSink((line) => this.log.append(line));
    window.addEventListener("error", (e) => this.crash(e.error ?? e.message));
    window.addEventListener("unhandledrejection", (e) => this.crash(e.reason));
    window.addEventListener("pagehide", () => this.log.flush());
    const drive = driveRequest(location.search, DEFAULT_DATA_PREFIX, import.meta.env.DEV || navigator.webdriver === true);
    this.drive = drive.scenario;
    if (drive.refused) Log.warn("drive", `DRIVE_IGNORED ${this.params.get(DRIVE_PARAM)}: ${drive.refused}`);

    const text = this.store.read(SETTINGS_FILE);
    const { settings, problems } = settingsLoad(text);
    this.settings = settings;
    this.i18n = new I18n(loadTables(), settings.language);
    if (text !== null && problems.length) {
      Log.warn("settings", `${SETTINGS_FILE} repaired (${problems.join(", ")})`);
      queueMicrotask(() => this.toast("toast.repaired", { n: problems.length }));
    }

    this.input = new ShellInput(
      () => this.settings.input.bindings,
      () => this.settings.input.deadzone,
      () => this.settings.input.invert_y,
    );
    this.input.scripted = this.drive !== ""; // only the drive presses: no real keyboard, mouse or pad (#276)
    this.input.onPress = (binding, actions) => this.route(binding, actions);
    this.input.onRawKey = (code) => {
      if (code === "F8" && this.debugBuild) this.bugReport();
    };
    this.telemetry = new Telemetry(this.store, () => telemetryAllowed(this.settings));
    this.saves = new SaveStore(this.store);

    const root = el("div");
    root.id = "shell";
    this.screensEl = el("div");
    const subs = el("div");
    subs.id = "subtitles";
    this.toastsEl = el("div");
    this.toastsEl.id = "toasts";
    root.append(this.screensEl, subs, this.toastsEl);
    document.body.append(root);
    this.rootEl = root;
    this.subtitles = new SubtitleBar(this, subs);
    this.narrator = new Narrator(this); // menu narration (#165)
    focusHooks.push((item) => this.narrator.focus(item));
    if (hasUiFile(THEME_FILE)) {
      const link = el("link");
      link.rel = "stylesheet";
      link.href = `assets/ui/${THEME_FILE}`;
      document.head.append(link);
    }
  }

  // ---- lifecycle -------------------------------------------------------------
  start(host: GameHost): void {
    this.host = host;
    this.input.attach(window);
    window.addEventListener("blur", () => this.focusLost());
    document.addEventListener("visibilitychange", () => document.hidden && this.focusLost());
    this.apply();
    this.telemetry.event("launch", GAME_VERSION);
    this.reset(screens.boot(this));
    requestAnimationFrame(this.frame);
    const ready = document.fonts?.ready ?? Promise.resolve();
    ready.then(() => {
      this.reset(screens.title(this));
      Log.info("core", `BOOT_OK ${GAME_NAME}`);
      if (this.drive) {
        runDrive(this, this.drive).catch((err: unknown) => Log.error("drive", `DRIVE_ABORT ${this.drive}: ${err instanceof Error ? err.message : String(err)}`));
      }
    });
  }

  private frame = (t: number): void => {
    const dt = this.lastT ? Math.min((t - this.lastT) / 1000, MAX_DT) : 0;
    this.lastT = t;
    this.input.poll();
    this.subtitles.update(dt);
    this.top?.tick?.(dt);
    if (t - this.lastFlush > LOG_FLUSH_MS) {
      this.log.flush();
      this.lastFlush = t;
    }
    requestAnimationFrame(this.frame);
  };

  // ---- screens ---------------------------------------------------------------
  get top(): Screen | undefined {
    return this.stack[this.stack.length - 1];
  }

  get topId(): string {
    return this.top?.id ?? "";
  }

  /** Opens a screen on top (Back returns to the one below). */
  push(s: Screen): void {
    this.stack.push(s);
    this.screensEl.append(s.root);
    this.activate();
  }

  /** Replaces the top screen. */
  replace(s: Screen): void {
    const old = this.stack.pop();
    old?.leave?.();
    old?.root.remove();
    this.push(s);
  }

  /** Clears the stack and shows s. */
  reset(s: Screen): void {
    for (const old of this.stack.reverse()) {
      old.leave?.();
      old.root.remove();
    }
    this.stack = [];
    this.push(s);
  }

  /** Back one screen (the title when nothing is below). */
  back(): void {
    const old = this.stack.pop();
    old?.leave?.();
    old?.root.remove();
    if (!this.stack.length) this.push(screens.title(this));
    else this.activate();
  }

  private activate(): void {
    this.stack.forEach((s, i) => s.root.classList.toggle("hidden", i !== this.stack.length - 1));
    const s = this.top;
    if (!s) return;
    s.enter?.();
    this.shown(s);
  }

  /** After a screen appears or redraws: telemetry, and the pseudo-locale check. */
  shown(s: Screen): void {
    this.narrator?.screen(s.root.querySelector(".heading, .bigtitle")?.textContent ?? s.id);
    this.telemetry.event("screen", s.id);
    Log.debug("core", `screen ${s.id}`);
    this.checkLayout(s);
  }

  /** In locale "pseudo": checks every visible label two frames from now, while s is still the screen shown. */
  checkLayout(s: Screen): void {
    if (this.i18n.locale !== PSEUDO_LOCALE) return;
    this.pendingChecks++;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      this.pendingChecks--;
      if (!s.root.isConnected || s.root.classList.contains("hidden")) return;
      const r = checkScreen(this.rootEl); // the screen plus subtitles and toasts: everything visible
      this.checks.screens++;
      this.checks.labels += r.labels;
      Log.info("i18n", `PSEUDO_SCREEN ${s.id} labels ${r.labels} problems ${r.failures.length}`);
      for (const f of r.failures) {
        const line = `PSEUDO_FAIL ${s.id}: "${f.id}" ${f.reason}: ${JSON.stringify(f.text)}`;
        this.checks.failures.push(line);
        Log.error("i18n", line);
      }
    }));
  }

  get checksPending(): boolean {
    return this.pendingChecks > 0;
  }

  /** Toasts on screen now (each one leaves after TOAST_MS). */
  get toastCount(): number {
    return this.toastsEl.childElementCount;
  }

  /** Redraws the top screen in place (language or layout changed), keeping the focused item. */
  rerender(): void {
    const s = this.top;
    if (!s?.render) return;
    const focus = s.menu?.focused?.id;
    s.render();
    if (focus) s.menu?.focusId(focus);
    this.shown(s);
  }

  private route(binding: string, actions: string[]): void {
    const s = this.top;
    if (!s) return;
    if (s.onAnyPress?.(binding)) return;
    // accept first dismisses a subtitle line waiting for the player (access.subtitle_hold, #167)
    if (actions.includes("ui_accept") && this.subtitles.holding()) {
      this.subtitles.dismiss();
      return;
    }
    for (const a of actions) {
      if (s.onAction?.(a)) return;
      if (s.menu?.handle(a)) return;
      if (a === "ui_cancel" && s.cancel) {
        s.cancel();
        return;
      }
    }
  }

  // ---- settings --------------------------------------------------------------
  /** Pushes every setting the browser can apply into the page and the game. */
  apply(): void {
    const s = this.settings;
    const css = document.documentElement.style;
    css.setProperty("--ui-scale", String(s.display.ui_scale));
    css.setProperty("--text-scale", String(s.access.text_scale));
    css.setProperty("--line-spacing", String(s.access.line_spacing)); // #167
    document.getElementById("shell")?.classList.toggle("readable", !!s.access.readable_font);
    css.setProperty("--sub-size", String(SUB_SIZE_EM[s.access.subtitle_size] ?? 1.1));
    css.setProperty("--sub-bg", String(s.access.subtitle_background));
    document.documentElement.classList.toggle("reduce-motion", s.access.reduce_motion);
    document.documentElement.classList.toggle("still", !!this.drive); // no blinking in scripted runs: stable screenshots
    this.i18n.locale = this.params.get("locale") || s.language;
    document.documentElement.lang = this.i18n.locale === PSEUDO_LOCALE ? "en" : this.i18n.locale;
    const host = this.host;
    if (!host) return;
    if (s.display.frame_cap !== this.frameCap) {
      this.frameCap = s.display.frame_cap;
      host.frameCap(s.display.frame_cap);
    }
    host.audio(s.audio.master, s.audio.mono);
  }

  /** Volume for one category (master included), for game code that plays sounds. */
  volume(category: "music" | "sfx" | "ui" | "voice"): number {
    return this.settings.audio.master * this.settings.audio[category];
  }

  palette(): (typeof PALETTES)["none"] {
    return PALETTES[this.settings.access.colorblind] ?? PALETTES.none;
  }

  /** Fullscreen and borderless are the same thing in a browser: the Fullscreen API (needs a key press or click). */
  applyDisplayMode(): void {
    const want = this.settings.display.mode !== "windowed";
    const doc = document;
    if (want && !doc.fullscreenElement && doc.documentElement.requestFullscreen) {
      doc.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => this.toast("toast.fullscreen"));
    } else if (!want && doc.fullscreenElement) {
      doc.exitFullscreen().catch(() => {});
    }
  }

  /** Writes settings.json atomically; logs SETTINGS_WRITTEN <name> (smoke maps it to a file path). */
  saveSettings(): boolean {
    try {
      atomicWrite(this.store, SETTINGS_FILE, settingsText(this.settings));
      Log.info("settings", `SETTINGS_WRITTEN ${SETTINGS_FILE}`);
      this.telemetry.event("settings_saved");
      this.toast("toast.saved");
      return true;
    } catch (err) {
      Log.error("settings", `could not save ${SETTINGS_FILE}: ${String(err)}`);
      return false;
    }
  }

  resetSettings(): void {
    this.settings = defaultSettings();
    this.apply();
  }

  // ---- gameplay --------------------------------------------------------------
  /** Loading screen, then the world with its HUD screen. */
  startGame(key: GameKey): void {
    if (key === "main") this.recordRun();
    this.telemetry.event("play_start", key);
    this.replace(screens.loading(this, key));
  }

  /** Called by the loading screen once the world is up. */
  enterGame(key: GameKey): void {
    this.scene = key;
    this.host?.backdrop(false);
    this.input.clearPresses();
    this.replace(screens.gameplay(this, key));
  }

  pauseGame(): void {
    if (!this.scene || !this.host || this.topId === "pause") return;
    this.host.pause(this.scene);
    this.push(screens.pause(this));
  }

  resumeGame(): void {
    if (!this.scene || !this.host) return;
    if (this.topId === "pause") this.back();
    this.host.resume(this.scene);
    this.input.clearPresses();
  }

  quitToTitle(): void {
    this.stopGame();
    this.reset(screens.title(this));
  }

  stopGame(): void {
    try {
      if (this.scene && this.host) this.host.stop(this.scene);
      this.host?.backdrop(true);
    } catch (err) {
      Log.debug("core", `world stop failed (after a crash): ${String(err)}`);
    }
    this.scene = null;
    this.subtitles.clear();
  }

  quit(): void {
    this.stopGame();
    this.telemetry.event("quit");
    this.log.flush();
    this.reset(screens.quit(this));
    Log.info("core", "QUIT");
  }

  private focusLost(): void {
    if (this.drive) return; // a headless run must not pause itself
    if (this.top?.gameplay) this.pauseGame();
  }

  /** The template save: counts runs in slot 1 (shows the save store, .bak and migration in action). */
  private recordRun(): void {
    try {
      const r = this.saves.load(SAVE_SLOT);
      const data = { level: 1, health: 3, ...(r.envelope?.data ?? {}) } as Record<string, unknown>;
      data.runs = (typeof data.runs === "number" ? data.runs : 0) + 1;
      data.difficulty = this.settings.access.difficulty;
      this.saves.save(SAVE_SLOT, data);
    } catch (err) {
      Log.warn("save", String(err instanceof Error ? err.message : err));
    }
  }

  // ---- messages, crashes, bug reports ----------------------------------------
  toast(key: string, args: Record<string, unknown> = {}): void {
    const t = tl(this.i18n, key, "toast", args, "div");
    this.toastsEl.append(t);
    setTimeout(() => t.remove(), TOAST_MS);
  }

  /** Unhandled error: log it, write crashes/crash_<ts>.txt, show the crash screen. */
  crash(reason: unknown): void {
    const err = reason instanceof Error ? reason : new Error(String(reason));
    Log.error("core", `uncaught: ${err.message}`);
    if (this.crashes >= MAX_CRASH_FILES) return;
    this.crashes++;
    try {
      const name = writeCrash(this.store, {
        header: `${GAME_NAME} ${GAME_VERSION}`, error: err.message, stack: err.stack, seed: this.seed, tail: this.log.tail(40),
      });
      this.log.flush();
      Log.info("core", `CRASH_WRITTEN ${name}`);
      this.stopGame();
      this.reset(screens.crashed(this, name));
    } catch (inner) {
      console.error(`[ERROR][core] could not write the crash file: ${String(inner)}`);
    }
    if (this.drive === "crash") Log.info("drive", "DRIVE_DONE crash");
  }

  /** F8 in debug builds: log tail, settings and a screenshot into bug_<ts>/, plus a download of the bundle. */
  bugReport(): void {
    const dir = `bug_${stamp()}/`;
    const tail = this.log.tail(TAIL_LINES).join("\n") + "\n";
    const settings = settingsText(this.settings);
    const finish = (png: string) => {
      try {
        this.store.write(dir + "log_tail.txt", tail);
        this.store.write(dir + "settings.json", settings);
        if (png) this.store.write(dir + "screenshot.png", png);
        Log.info("core", `BUG_WRITTEN ${dir}`);
        this.toast("toast.bug", { dir });
      } catch (err) {
        Log.warn("core", `bug report not stored: ${String(err)}`);
      }
      download(`${dir.slice(0, -1)}.json`, JSON.stringify({ log_tail: tail, settings: JSON.parse(settings), screenshot: png }, null, 1));
    };
    if (this.host) this.host.snapshot(finish);
    else finish("");
  }

  /** Every file of the user-data folder as one JSON download. */
  exportData(): void {
    const files: Record<string, string> = {};
    for (const name of this.store.list()) files[name] = this.store.read(name) ?? "";
    download(`${GAME_SLUG}-data.json`, JSON.stringify({ game: GAME_NAME, version: GAME_VERSION, files }, null, 1));
  }
}

export const shell = new Shell();

// {{FOOTER}}
