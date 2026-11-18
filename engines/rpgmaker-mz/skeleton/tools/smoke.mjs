// ---------------------------------------------------------------------------
// smoke.mjs
// Purpose : Boot the RPG Maker MZ game (game/, or --root) in headless Chromium and fail on errors.
//           Optionally drive a scenario (URL flags, wait for a gameplay marker) and
//           capture it (a screenshot, or PNG frames for tools/art/frames_to_gif.py).
//           Called by `python tools/dev.py smoke`; run it directly only for debugging.
// Usage   : node tools/smoke.mjs [--root game] [--frames N] [--marker TEXT] [--query Q] [--until TEXT]
//                                [--fail-on TEXT[,TEXT]] [--timeout-ms MS] [--viewport WxH]
//                                [--screenshot FILE] [--record DIR] [--record-every MS] [--drive NAME] [--headed] [--gpu] [--verbose]
//           e.g. --query autoplay --until ESCAPED --fail-on CAUGHT --record build/frames
//           --drive menus|access|crash runs a scripted walk of MZ's own screens (tools/mz_drives.js) after boot (#280)
// Exit    : 0 ok, 1 errors / marker missing / a --fail-on marker seen, 2 environment
//           problem (no MZ project in the root, Playwright browser not installed)
// Notes   : Serves the root with tools/serve.mjs on a free port, loads index.html
//           (plus ?Q), waits for the boot marker, then either lets N animation frames
//           run or waits for the --until marker. Any console.error, uncaught page
//           error, failed request or HTTP 4xx/5xx response (a missing asset) fails it.
//           MZ needs WebGL: headless Chromium draws it in software (slow but enough to boot); --headed uses
//           the real GPU. The viewport defaults to MZ's 816x624 screen. Browser audio waits for a click, so
//           the AudioContext warning is expected and not an error. (verify against a real MZ project)
//
// Pseudocode:
//   serve the root -> launch chromium -> collect console + page errors
//   goto page?query -> wait for boot marker -> (--until) wait for it | N frames
//   recording: screenshot every --record-every ms while it runs
//   screenshot -> print errors (or everything with --verbose) -> close all -> exit code
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Sonnet 5.5, claude-sonnet-5-5): --drive runs a scenario from tools/mz_drives.js in the
//           page after boot and needs its DRIVE_DONE marker (#280)
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a recorded frame that fails to save is an error
//           (it was swallowed), an old --screenshot is deleted first, and each capture is checked after the run
// Updated : 2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): --record clears the folder's old f*.png frames
//           first, so it holds this run's frames only
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the time between animation frames after boot is
//           sampled (tools/frame_times.mjs) and a passing run prints it as the FRAME_TIMES line dev.py smoke
//           reports and checks against --frame-budget (#90)
// ---------------------------------------------------------------------------
import { existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
};
const FRAMES = Number(opt("--frames", "120"));
const TIMEOUT_MS = Number(opt("--timeout-ms", "30000"));
const MARKER = opt("--marker", "BOOT_OK");
const QUERY = opt("--query", "");
const UNTIL = opt("--until", "");
const FAIL_ON = opt("--fail-on", "").split(",").filter(Boolean);
const [VW, VH] = opt("--viewport", "816x624").split("x").map(Number);
const ROOT = resolve(import.meta.dirname, "..");
const GAME = resolve(ROOT, opt("--root", "game"));
const SCREENSHOT = opt("--screenshot", "") && resolve(ROOT, opt("--screenshot", ""));
const RECORD = opt("--record", "") && resolve(ROOT, opt("--record", ""));
const RECORD_EVERY = Number(opt("--record-every", "66"));
const FRAME_FILE = /^f\d+\.png$/; // the frames --record writes (f00000.png, ...), cleared before a run
const DRIVE = opt("--drive", "");
const VERBOSE = args.includes("--verbose");
const HEADED = args.includes("--headed");
const GPU_ARGS = args.includes("--gpu") ? ["--enable-unsafe-webgpu", "--enable-features=Vulkan", "--use-angle=vulkan"] : [];

if (!existsSync(resolve(GAME, "index.html")) || !existsSync(resolve(GAME, "js", "rmmz_core.js"))) {
  console.error(`[error] no RPG Maker MZ project in ${GAME}: run \`python tools/dev.py setup --from <a new MZ project>\``);
  process.exit(2);
}
if (!VW || !VH) {
  console.error("[error] --viewport must look like 816x624");
  process.exit(2);
}

let DRIVES = {};
if (DRIVE) {
  // only a --drive run needs tools/mz_drives.js (a project without it still boots and records)
  try {
    ({ DRIVES } = createRequire(import.meta.url)("./mz_drives.js"));
  } catch (err) {
    console.error(`[error] --drive needs tools/mz_drives.js (${String(err.message).split("\n")[0]})`);
    process.exit(2);
  }
  if (!DRIVES[DRIVE]) {
    console.error(`[error] no drive ${JSON.stringify(DRIVE)}: the drives are ${Object.keys(DRIVES).join(", ")}`);
    process.exit(2);
  }
}

const { serve } = await import("./serve.mjs");
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

const lines = [];
const errors = [];
let server;
let browser;
let recorder;
let recording = null; // the screenshot in flight, awaited before the final picture
let recordError = "";
let frameCount = 0;
let frameTimes = null; // #90: the time between animation frames after boot (tools/frame_times.mjs)
const frameKit = await import("./frame_times.mjs").catch(() => null); // a project without it measures nothing
let code = 0;
if (SCREENSHOT) rmSync(SCREENSHOT, { force: true }); // a picture from an earlier run must not pass for this one
if (RECORD && existsSync(RECORD)) {
  // nor frames from an earlier, longer run: the folder holds this run's frames only
  for (const name of readdirSync(RECORD)) if (FRAME_FILE.test(name)) rmSync(join(RECORD, name), { force: true });
}
try {
  server = await serve(GAME);
  const base = server.url;
  try {
    browser = await chromium.launch({ headless: !HEADED, args: GPU_ARGS });
  } catch (err) {
    console.error(`[error] cannot start headless Chromium: ${String(err.message).split("\n")[0]}`);
    console.error("        run `python tools/dev.py setup` (installs the Playwright browser)");
    process.exit(2);
  }
  const page = await browser.newPage({ viewport: { width: VW, height: VH } });
  const boot = waiter(MARKER);
  const until = UNTIL ? waiter(UNTIL) : null;
  const driveDone = DRIVE ? waiter(`DRIVE_DONE ${DRIVE}`) : null;
  page.on("console", (msg) => {
    const text = `[console.${msg.type()}] ${msg.text()}`;
    lines.push(text);
    if (msg.type() === "error" && !msg.location()?.url?.endsWith("/favicon.ico")) errors.push(text);
    for (const bad of FAIL_ON) if (msg.text().includes(bad)) errors.push(`[fail-on ${bad}] ${msg.text()}`);
    boot.check(msg.text());
    until?.check(msg.text());
    driveDone?.check(msg.text());
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
  await page.goto(QUERY ? `${base}?${QUERY}` : base, { waitUntil: "load", timeout: TIMEOUT_MS });
  if (!(await Promise.race([boot.promise, timeout(TIMEOUT_MS)]))) {
    errors.push(`[smoke] marker ${JSON.stringify(MARKER)} not seen within ${TIMEOUT_MS} ms`);
  } else {
    await frameKit?.startFrameSampler(page);
    if (RECORD) {
      mkdirSync(RECORD, { recursive: true });
      recorder = setInterval(() => {
        if (recording) return;
        const file = join(RECORD, `f${String(frameCount).padStart(5, "0")}.png`);
        recording = page.screenshot({ path: file })
          .then(() => frameCount++)
          .catch((err) => { recordError ||= `[record] could not save ${file}: ${String(err.message).split("\n")[0]}`; })
          .finally(() => { recording = null; });
      }, RECORD_EVERY);
    }
    if (DRIVE) {
      // the drive's source goes into the page; an error it throws is a console error or page error: smoke fails on it
      await page.evaluate(`(${DRIVES[DRIVE].toString()})()`).catch((err) => errors.push(`[drive ${DRIVE}] ${String(err.message).split("\n")[0]}`));
      if (!(await Promise.race([driveDone.promise, timeout(1000)]))) errors.push(`[drive ${DRIVE}] DRIVE_DONE ${DRIVE} not printed: the drive did not get to its end`);
      await timeout(300); // an error thrown in a scene's update arrives after the drive's own last frame
    } else if (until) {
      if (!(await Promise.race([until.promise, timeout(TIMEOUT_MS)]))) {
        errors.push(`[smoke] marker ${JSON.stringify(UNTIL)} not seen within ${TIMEOUT_MS} ms`);
      } else {
        await timeout(500); // let the result screen draw for the screenshot or recording
      }
    } else {
      // raced against a timeout (#251): a page whose main thread freezes after the boot marker never resolves this
      const frameMs = TIMEOUT_MS + Math.ceil((FRAMES * 1000) / 20);
      const ran = await Promise.race([
        page.evaluate(
          (n) => new Promise((done) => {
            let left = n;
            const tick = () => (--left <= 0 ? done(true) : requestAnimationFrame(tick));
            requestAnimationFrame(tick);
          }),
          FRAMES,
        ),
        timeout(frameMs),
      ]);
      if (!ran) errors.push(`[smoke] ${FRAMES} frames did not run within ${frameMs} ms (the page froze?)`);
    }
    frameTimes = (await frameKit?.stopFrameSampler(page)) ?? null;
    if (recorder) clearInterval(recorder);
    recorder = null;
    await recording; // the last frame lands (or fails) before the page can close
    if (SCREENSHOT) {
      mkdirSync(dirname(SCREENSHOT), { recursive: true });
      await page.screenshot({ path: SCREENSHOT });
    }
    // every capture asked for must be there after the run
    if (recordError) errors.push(recordError);
    else if (RECORD && frameCount === 0) errors.push(`[record] no frame saved in ${RECORD}`);
    if (SCREENSHOT && !(existsSync(SCREENSHOT) && statSync(SCREENSHOT).size > 0)) errors.push(`[screenshot] no picture written to ${SCREENSHOT}`);
  }
} catch (err) {
  errors.push(`[smoke] ${err.message}`);
} finally {
  if (recorder) clearInterval(recorder);
  if (browser) await browser.close();
  if (server) await server.close();
}

if (VERBOSE || errors.length) for (const l of lines) console.log(l);
if (errors.length) {
  console.log("[FAIL] errors during smoke:");
  for (const e of errors.slice(0, 20)) console.log(`  ${e}`);
  code = 1;
} else {
  const what = DRIVE ? `drive ${DRIVE} done` : UNTIL ? `marker ${JSON.stringify(UNTIL)} reached` : `${FRAMES} frames`;
  console.log(`[ OK ] boot marker seen, ${what}, no errors`);
  const frames = frameKit?.frameLine(frameTimes, HEADED ? "render" : "software") ?? "";
  if (frames) console.log(frames); // dev.py smoke reports it and checks --frame-budget
  if (SCREENSHOT) console.log(`[ OK ] screenshot: ${SCREENSHOT}`);
  if (RECORD) console.log(`[ OK ] ${frameCount} frame(s) in ${RECORD} (make a GIF: python tools/art/frames_to_gif.py ${RECORD} out.gif)`);
}
process.exit(code);
