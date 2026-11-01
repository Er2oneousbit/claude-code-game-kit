// ---------------------------------------------------------------------------
// smoke.mjs
// Purpose : Boot the BUILT game (dist/) in headless Chromium and fail on errors.
//           Optionally drive a scenario (URL flags, wait for a gameplay marker) and
//           capture it (a screenshot, or PNG frames for tools/art/frames_to_gif.py).
//           Called by `python tools/dev.py smoke`; run it directly only for debugging.
// Usage   : node tools/smoke.mjs [--frames N] [--marker TEXT] [--query Q] [--until TEXT]
//                                [--fail-on TEXT[,TEXT]] [--timeout-ms MS] [--viewport WxH]
//                                [--screenshot FILE] [--record DIR] [--record-every MS] [--headed] [--gpu] [--verbose]
//                                [--drive SCENARIO] [--data-dir DIR] [--locale ID]
//                                [--compare BASELINE.png] [--tolerance N] [--python EXE]
//           e.g. --query autoplay --until ESCAPED --fail-on CAUGHT --record build/frames
//                --drive menus --data-dir build/smoke-data
//                --drive show:settings --screenshot captures/settings.png --compare baselines/settings.png
// Exit    : 0 ok, 1 errors / marker missing / a --fail-on marker seen / --compare found a difference,
//           2 environment problem (no dist/, Playwright browser not installed, no tools/image_diff.py)
// Notes   : Serves dist/ with Vite's preview server on a free port, loads the page
//           (plus ?Q), waits for the boot marker, then either lets N animation frames
//           run or waits for the --until marker. Any console.error, uncaught page
//           error, failed request or HTTP 4xx/5xx response (a missing asset) fails it.
//           Headless Chromium has no GPU: games that need WebGPU (local AI models) or real WebGL
//           speed run with --headed (a visible window), or try --gpu (Chrome's headless WebGPU flags).
//           --drive X adds ?drive=X and waits for DRIVE_DONE (DRIVE_ABORT fails at once); the game does the
//           driving (src/shell/drive.ts in games built on the kit's shell). --data-dir DIR maps the game's
//           user-data folder (localStorage) onto a real folder: its files are loaded into localStorage under the
//           prefix DIR/ before the page starts (?data-dir=DIR) and written back after the run, so tests can
//           read settings.json, logs/, crashes/ and telemetry.csv as files. A console line "<NAME>_WRITTEN <file>"
//           is printed again with the real path. A --drive run without --data-dir uses build/smoke-data.
//           --locale ID adds ?locale=ID. --compare runs tools/image_diff.py on the --screenshot.
//
// Pseudocode:
//   start preview server -> launch chromium -> collect console + page errors
//   (data dir) seed localStorage from DIR -> goto page?query -> wait for boot marker
//   -> (--until / --drive) wait for it | N frames ; recording: screenshot every --record-every ms
//   screenshot -> (data dir) write localStorage back to DIR -> scenario checks -> (--compare) image_diff
//   print errors (or everything with --verbose) -> close all -> exit code
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
};
const FRAMES = Number(opt("--frames", "120"));
const TIMEOUT_MS = Number(opt("--timeout-ms", "30000"));
const MARKER = opt("--marker", "BOOT_OK");
const QUERY = opt("--query", "");
const DRIVE = opt("--drive", "");
const UNTIL = opt("--until", "") || (DRIVE ? "DRIVE_DONE" : "");
const ABORT = DRIVE ? "DRIVE_ABORT" : "";
const FAIL_ON = [...opt("--fail-on", "").split(","), ABORT].filter(Boolean);
const LOCALE = opt("--locale", "");
const [VW, VH] = opt("--viewport", "1280x720").split("x").map(Number);
const ROOT = resolve(import.meta.dirname, "..");
const SCREENSHOT = opt("--screenshot", "") && resolve(ROOT, opt("--screenshot", ""));
const RECORD = opt("--record", "") && resolve(ROOT, opt("--record", ""));
const RECORD_EVERY = Number(opt("--record-every", "66"));
const DATA_ARG = (opt("--data-dir", "") || (DRIVE ? "build/smoke-data" : "")).replace(/\\/g, "/");
const DATA_DIR = DATA_ARG && resolve(ROOT, DATA_ARG);
const DATA_PREFIX = DATA_ARG && (DATA_ARG.endsWith("/") ? DATA_ARG : DATA_ARG + "/");
const COMPARE = opt("--compare", "") && resolve(ROOT, opt("--compare", ""));
const TOLERANCE = opt("--tolerance", "0");
const PYTHON = opt("--python", process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"));
const VERBOSE = args.includes("--verbose");
const HEADED = args.includes("--headed");
const GPU_ARGS = args.includes("--gpu") ? ["--enable-unsafe-webgpu", "--enable-features=Vulkan", "--use-angle=vulkan"] : [];
const SEED_MAX_BYTES = 1024 * 1024; // a data-dir file bigger than this is not loaded into localStorage
const SEED_MAX_FILES = 1000; // more than this is not a game's user-data folder: refuse it
const NOTE = /\b(DRIVE_[A-Z]+|PSEUDO_[A-Z]+|SHOWN|[A-Z]+_WRITTEN|QUIT)\b/; // printed even without --verbose
const WRITTEN = /\b([A-Z]+_WRITTEN) (\S+)/;

const fail2 = (msg) => {
  console.error(`[error] ${msg}`);
  process.exit(2);
};
if (!existsSync(resolve(ROOT, "dist", "index.html"))) fail2("dist/index.html not found: run `python tools/dev.py build` first");
if (!VW || !VH) fail2("--viewport must look like 1280x720");
if (COMPARE && !SCREENSHOT) fail2("--compare needs --screenshot (the picture to compare)");
if (COMPARE && !existsSync(COMPARE)) fail2(`no baseline at ${COMPARE}: run once with --screenshot and copy the picture there`);
if (COMPARE && !existsSync(join(ROOT, "tools", "image_diff.py"))) fail2("tools/image_diff.py is missing (it ships with the kit's core tools)");
if (DATA_DIR && (DATA_DIR === ROOT || DATA_DIR === dirname(DATA_DIR) || existsSync(join(DATA_DIR, "package.json")))) {
  fail2(`--data-dir must be a folder of its own, not a project or drive root (got ${DATA_DIR})`);
}

const { preview } = await import("vite");
let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch (err) {
  console.error(`[error] playwright is not installed (${err.message}): run \`python tools/dev.py setup\``);
  process.exit(2);
}

/** Resolves when a console line contains `text` (or at once if already seen). */
function waiter(text) {
  let hit = false, done;
  const p = new Promise((res) => (done = res));
  return { promise: p, check: (line) => { if (!hit && line.includes(text)) { hit = true; done(true); } } };
}
const timeout = (ms) => new Promise((res) => setTimeout(() => res(false), ms));

/** Every file under dir as { "logs/game.log": text }; PNGs become data URLs (the game stores them that way). */
function readTree(dir) {
  const out = {};
  if (!existsSync(dir)) return out;
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const full = join(d, e.name);
      if (Object.keys(out).length > SEED_MAX_FILES) fail2(`--data-dir ${dir} holds more than ${SEED_MAX_FILES} files: is it the right folder?`);
      if (e.isDirectory()) walk(full);
      else if (statSync(full).size <= SEED_MAX_BYTES) {
        const name = relative(dir, full).split(sep).join("/");
        out[name] = name.endsWith(".png") ? `data:image/png;base64,${readFileSync(full).toString("base64")}` : readFileSync(full, "utf-8");
      }
    }
  };
  walk(dir);
  return out;
}

/** Mirrors the page's user data into dir; removes files the game deleted (only ones it was given). */
function writeTree(dir, files, seeded) {
  for (const [name, text] of Object.entries(files)) {
    const path = resolve(dir, name);
    if (!(path + sep).startsWith(dir + sep) && path !== dir) continue; // never outside the data dir
    mkdirSync(dirname(path), { recursive: true });
    const m = /^data:image\/png;base64,(.*)$/s.exec(text);
    writeFileSync(path, m ? Buffer.from(m[1], "base64") : text);
  }
  for (const name of Object.keys(seeded)) if (!(name in files)) rmSync(resolve(dir, name), { force: true });
}

/** What a --drive scenario must leave in the data dir. Returns error strings. */
function scenarioChecks(files) {
  const problems = [];
  if (DRIVE === "menus") {
    let s = null;
    try {
      s = JSON.parse(files["settings.json"] ?? "null");
    } catch { /* reported below */ }
    if (!s) problems.push("[drive menus] settings.json missing or unreadable in the data dir");
    else if (s.audio?.master !== 0.5 || s.access?.reduce_motion !== true) {
      problems.push(`[drive menus] settings.json holds master ${s.audio?.master}, reduce_motion ${s.access?.reduce_motion} (want 0.5, true)`);
    }
    const consent = s?.telemetry?.consent ?? "unset";
    if (consent !== "yes" && "telemetry.csv" in files) problems.push(`[drive menus] telemetry.csv written although consent is "${consent}"`);
    else console.log(`[ OK ] telemetry.csv ${"telemetry.csv" in files ? "written (consent yes)" : `not written (consent ${consent})`}`);
  }
  if (DRIVE === "crash" && !Object.keys(files).some((n) => n.startsWith("crashes/"))) problems.push("[drive crash] no crash file in crashes/");
  return problems;
}

const lines = [];
const errors = [];
const written = [];
let server;
let browser;
let recorder;
let frameCount = 0;
let code = 0;
let seeded = {};
try {
  // appType "mpa": a missing file is a real 404, not the SPA fallback page with status 200
  server = await preview({ root: ROOT, appType: "mpa", logLevel: "silent", preview: { port: 4173, strictPort: false, open: false } });
  const base = server.resolvedUrls?.local?.[0];
  if (!base) throw new Error("preview server did not report a URL");
  try {
    browser = await chromium.launch({ headless: !HEADED, args: GPU_ARGS });
  } catch (err) {
    console.error(`[error] cannot start headless Chromium: ${String(err.message).split("\n")[0]}`);
    console.error("        run `python tools/dev.py setup` (installs the Playwright browser)");
    process.exit(2);
  }
  const page = await browser.newPage({ viewport: { width: VW, height: VH } });
  if (DATA_DIR) {
    seeded = readTree(DATA_DIR);
    await page.addInitScript(({ prefix, files }) => {
      if (sessionStorage.getItem("__smoke_seeded")) return; // once per run, not on every reload
      for (const [name, text] of Object.entries(files)) localStorage.setItem(prefix + name, text);
      sessionStorage.setItem("__smoke_seeded", "1");
    }, { prefix: DATA_PREFIX, files: seeded });
  }
  const boot = waiter(MARKER);
  const until = UNTIL ? waiter(UNTIL) : null;
  const abort = ABORT ? waiter(ABORT) : null;
  page.on("console", (msg) => {
    const text = `[console.${msg.type()}] ${msg.text()}`;
    lines.push(text);
    if (msg.type() === "error" && !msg.location()?.url?.endsWith("/favicon.ico")) errors.push(text);
    for (const bad of FAIL_ON) if (msg.text().includes(bad)) errors.push(`[fail-on ${bad}] ${msg.text()}`);
    const w = WRITTEN.exec(msg.text());
    if (w) written.push([w[1], w[2]]);
    boot.check(msg.text());
    until?.check(msg.text());
    abort?.check(msg.text());
  });
  page.on("pageerror", (err) => {
    const text = `[pageerror] ${err.message}`;
    lines.push(text);
    errors.push(text);
  });
  page.on("requestfailed", (req) => errors.push(`[requestfailed] ${req.url()} ${req.failure()?.errorText ?? ""}`));
  page.on("response", (res) => {
    // a missing asset fails smoke; the browser's own favicon probe (headed runs) does not
    if (res.status() >= 400 && !res.url().endsWith("/favicon.ico")) errors.push(`[http ${res.status()}] ${res.url()}`);
  });
  const extra = new URLSearchParams();
  if (DRIVE) extra.set("drive", DRIVE);
  if (LOCALE) extra.set("locale", LOCALE);
  if (DATA_PREFIX) extra.set("data-dir", DATA_PREFIX);
  const query = [QUERY, extra.toString()].filter(Boolean).join("&");
  await page.goto(query ? `${base}?${query}` : base, { waitUntil: "load", timeout: TIMEOUT_MS });
  if (!(await Promise.race([boot.promise, timeout(TIMEOUT_MS)]))) {
    errors.push(`[smoke] marker ${JSON.stringify(MARKER)} not seen within ${TIMEOUT_MS} ms`);
  } else {
    if (RECORD) {
      mkdirSync(RECORD, { recursive: true });
      let busy = false;
      recorder = setInterval(async () => {
        if (busy) return;
        busy = true;
        try {
          await page.screenshot({ path: join(RECORD, `f${String(frameCount).padStart(5, "0")}.png`) });
          frameCount++;
        } catch { /* page closing */ }
        busy = false;
      }, RECORD_EVERY);
    }
    if (until) {
      const hit = await Promise.race([until.promise, abort ? abort.promise.then(() => "abort") : new Promise(() => {}), timeout(TIMEOUT_MS)]);
      if (hit === "abort") {
        /* the DRIVE_ABORT line is already an error */
      } else if (!hit) {
        errors.push(`[smoke] marker ${JSON.stringify(UNTIL)} not seen within ${TIMEOUT_MS} ms`);
      } else {
        await timeout(500); // let the result screen draw for the screenshot or recording
      }
    } else {
      await page.evaluate(
        (n) => new Promise((done) => {
          let left = n;
          const tick = () => (--left <= 0 ? done() : requestAnimationFrame(tick));
          requestAnimationFrame(tick);
        }),
        FRAMES,
      );
    }
    if (recorder) clearInterval(recorder);
    if (SCREENSHOT) {
      mkdirSync(dirname(SCREENSHOT), { recursive: true });
      await page.screenshot({ path: SCREENSHOT });
    }
  }
  if (DATA_DIR) {
    await page.evaluate(() => new Promise((r) => setTimeout(r, 50))); // let a pending log flush land
    const files = await page.evaluate((prefix) => {
      const out = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(prefix)) out[k.slice(prefix.length)] = localStorage.getItem(k);
      }
      return out;
    }, DATA_PREFIX);
    writeTree(DATA_DIR, files, seeded);
    console.log(`[info] user data (${Object.keys(files).length} file(s)) in ${DATA_DIR}`);
    for (const [marker, name] of written) console.log(`${marker} ${resolve(DATA_DIR, name)}`);
    errors.push(...scenarioChecks(files));
  }
} catch (err) {
  errors.push(`[smoke] ${err.message}`);
} finally {
  if (recorder) clearInterval(recorder);
  if (browser) await browser.close();
  if (server) await server.close();
}

if (COMPARE && SCREENSHOT && existsSync(SCREENSHOT)) {
  const r = spawnSync(PYTHON, [join(ROOT, "tools", "image_diff.py"), SCREENSHOT, COMPARE, "--tolerance", TOLERANCE], { encoding: "utf-8" });
  const out = `${r.stdout ?? ""}${r.stderr ?? ""}`.trim();
  if (r.error || r.status === 2 || r.status === null) {
    console.error(`[error] image_diff could not run (${r.error?.message ?? out}); set --python or PYTHON`);
    process.exit(2);
  }
  if (out) console.log(out);
  if (r.status === 1) errors.push(`[compare] ${SCREENSHOT} differs from ${COMPARE} (see why: python tools/image_diff.py <new> <baseline> --diff diff.png)`);
  else console.log(`[ OK ] screenshot matches ${COMPARE} (tolerance ${TOLERANCE})`);
}

if (VERBOSE || errors.length) for (const l of lines) console.log(l);
else for (const l of lines) if (NOTE.test(l)) console.log(l);
if (errors.length) {
  console.log("[FAIL] errors during smoke:");
  for (const e of errors.slice(0, 20)) console.log(`  ${e}`);
  if (DRIVE === "crash") console.log("[info] --drive crash fails on purpose: the planted error must reach the crash hook (exit 1 is the pass)");
  code = 1;
} else {
  const what = UNTIL ? `marker ${JSON.stringify(UNTIL)} reached` : `${FRAMES} frames`;
  console.log(`[ OK ] boot marker seen, ${what}, no errors`);
  if (SCREENSHOT) console.log(`[ OK ] screenshot: ${SCREENSHOT}`);
  if (RECORD) console.log(`[ OK ] ${frameCount} frame(s) in ${RECORD} (make a GIF: python tools/art/frames_to_gif.py ${RECORD} out.gif)`);
}
process.exit(code);
