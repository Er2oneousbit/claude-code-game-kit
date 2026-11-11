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
//           --drive X adds ?drive=X and waits for DRIVE_DONE (DRIVE_ABORT or DRIVE_IGNORED fail at once); the
//           game does the driving (src/shell/drive.ts in games built on the kit's shell). --data-dir DIR maps the
//           game's user-data folder (localStorage) onto a real folder: its files are loaded into localStorage
//           under the prefix DIR/ before the page starts (?data-dir=DIR) and written back after the run, so tests
//           can read settings.json, logs/, crashes/ and telemetry.csv as files. A console line
//           "<NAME>_WRITTEN <file>" is printed again with the real path. A --drive run without --data-dir uses
//           build/smoke-data: the shell runs a scenario only with its own data dir, never on the player's keys.
//           drive= and data-dir= inside --query count as --drive and --data-dir.
//           --locale ID adds ?locale=ID. --compare runs tools/image_diff.py on the --screenshot.
//
// Pseudocode:
//   start preview server -> launch chromium -> collect console + page errors
//   (data dir) seed localStorage from DIR -> goto page?query -> wait for boot marker
//   -> (--until / --drive) wait for it | N frames ; recording: screenshot every --record-every ms
//   screenshot -> (data dir) write localStorage back to DIR -> scenario checks -> (--compare) image_diff
//   print errors (or everything with --verbose) -> close all -> exit code
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-02 with Claude (Opus 5.5, claude-opus-5-5): a recorded frame that fails to save is an error
//           (it was swallowed), an old --screenshot is deleted first, and each capture is checked after the run
// Updated : 2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): --record clears the folder's old f*.png frames
//           first, so it holds this run's frames only
// Updated : 2026-11-03 with Claude (Opus 5.5, claude-opus-5-5): a DRIVE_ABORT or DRIVE_IGNORED run skips the
//           data-dir scenario checks (the refusal is its one error)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the "--drive crash fails on purpose" note prints
//           only when a crash file was written (it also followed a refused drive or a crash hook that wrote nothing)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): --drive pseudo-plant says it fails on purpose
//           when the planted label is what failed (#175)
// ---------------------------------------------------------------------------
import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
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
const QUERY_ARGS = new URLSearchParams(QUERY);
const DRIVE = opt("--drive", "") || QUERY_ARGS.get("drive") || "";
const UNTIL = opt("--until", "") || (DRIVE ? "DRIVE_DONE" : "");
const ABORTS = DRIVE ? ["DRIVE_ABORT", "DRIVE_IGNORED"] : []; // a failed step, or the game refused the scenario
const FAIL_ON = [...opt("--fail-on", "").split(","), ...ABORTS].filter(Boolean);
const LOCALE = opt("--locale", "");
// the access drive names its window size (access:res=1280x800,...): tools/access/sweep.py runs it per screen size
const ACCESS_RES = /^access:(?:.*,)?res=(\d+x\d+)/.exec(DRIVE)?.[1];
const [VW, VH] = opt("--viewport", ACCESS_RES ?? "1280x720").split("x").map(Number);
const ROOT = resolve(import.meta.dirname, "..");
const SCREENSHOT = opt("--screenshot", "") && resolve(ROOT, opt("--screenshot", ""));
const RECORD = opt("--record", "") && resolve(ROOT, opt("--record", ""));
const RECORD_EVERY = Number(opt("--record-every", "66"));
const FRAME_FILE = /^f\d+\.png$/; // the frames --record writes (f00000.png, ...), cleared before a run
const DATA_ARG = (opt("--data-dir", "") || QUERY_ARGS.get("data-dir") || (DRIVE ? "build/smoke-data" : "")).replace(/\\/g, "/");
const DATA_DIR = DATA_ARG && resolve(ROOT, DATA_ARG);
const DATA_PREFIX = DATA_ARG && (DATA_ARG.endsWith("/") ? DATA_ARG : DATA_ARG + "/");
const COMPARE = opt("--compare", "") && resolve(ROOT, opt("--compare", ""));
const TOLERANCE = opt("--tolerance", "0");
const PYTHON = opt("--python", process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"));
const VERBOSE = args.includes("--verbose");
// --shaders: the page renders every kit shader recipe (?shadercheck=1, src/shaders/shaderCheck.ts) and hands back
// each picture; they land in build/shader_check/ and tools/shaders/shader_ref.py compares them with the golden images
const SHADERS = args.includes("--shaders");
const SHADER_OUT = resolve(ROOT, "build", "shader_check");
const HEADED = args.includes("--headed");
const GPU_ARGS = args.includes("--gpu") ? ["--enable-unsafe-webgpu", "--enable-features=Vulkan", "--use-angle=vulkan"] : [];
const SEED_MAX_BYTES = 1024 * 1024; // a data-dir file bigger than this is not loaded into localStorage
const SEED_MAX_FILES = 1000; // more than this is not a game's user-data folder: refuse it
const NOTE = /\b(DRIVE_[A-Z]+|PSEUDO_[A-Z]+|ACCESS_[A-Z]+|SHOWN|[A-Z]+_WRITTEN|QUIT)\b/; // printed even without --verbose
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
// #251: a folder of the project's own (src, assets, public, dist, tools) would have every file rewritten after the run
// and seeded files the game clears deleted: the data dir is a folder for user data, under build/ by default
// #256: the guards look at where the folder really is (a symlink to src/ passed as build/...), and compare names
// without letter case (SRC is src/ on Windows and macOS)
const realOf = (p) => {
  try { return realpathSync.native(p); } catch { return resolve(p); }
};
if (DATA_DIR) {
  const real = realOf(DATA_DIR), root = realOf(ROOT);
  const inside = (real + sep).toLowerCase().startsWith((root + sep).toLowerCase());
  if (real.toLowerCase() === root.toLowerCase() || real === dirname(real)) fail2(`--data-dir ${DATA_ARG} is the project or a drive root`);
  if (inside) {
    const top = relative(root, real).split(sep)[0].toLowerCase();
    if (["src", "assets", "public", "dist", "tools", "tests", "docs", "node_modules", "data"].includes(top)) {
      fail2(`--data-dir ${DATA_ARG} is inside the project's ${top}/: use a folder of its own (build/smoke-data)`);
    }
  }
}

const { preview } = await import("vite");
let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch (err) {
  console.error(`[error] playwright is not installed (${err.message}): run \`python tools/dev.py setup\``);
  process.exit(2);
}

/** Resolves when a console line contains one of `texts` (or at once if already seen); seen() says whether one did. */
function waiter(...texts) {
  let hit = false, done;
  const p = new Promise((res) => (done = res));
  return { promise: p, seen: () => hit, check: (line) => { if (!hit && texts.some((t) => line.includes(t))) { hit = true; done(true); } } };
}
const timeout = (ms) => new Promise((res) => setTimeout(() => res(false), ms));

/** Every file under dir as { "logs/game.log": text }; PNGs become data URLs (the game stores them that way). A file
 *  that is not UTF-8 text (a binary save, a WAV) is left out: it was read as text and written back corrupted (#251),
 *  and a file that is not seeded is never written or deleted. */
const UTF8 = new TextDecoder("utf-8", { fatal: true });
function readTree(dir) {
  const out = {};
  if (!existsSync(dir)) return out;
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const full = join(d, e.name);
      if (Object.keys(out).length > SEED_MAX_FILES) fail2(`--data-dir ${dir} holds more than ${SEED_MAX_FILES} files: is it the right folder?`);
      if (e.isSymbolicLink()) {
        console.log(`[smoke] --data-dir: ${relative(dir, full)} is a symlink; left out (and left alone)`);   // #256
        continue;
      }
      if (e.isDirectory()) walk(full);
      else if (statSync(full).size <= SEED_MAX_BYTES) {
        const name = relative(dir, full).split(sep).join("/");
        const raw = readFileSync(full);
        if (name.endsWith(".png")) out[name] = `data:image/png;base64,${raw.toString("base64")}`;
        else {
          try {
            out[name] = UTF8.decode(raw);
          } catch {
            console.log(`[smoke] --data-dir: ${name} is not UTF-8 text; left out (and left alone)`);
          }
        }
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
    if (linkOnPath(dir, path)) continue; // #256: never write through a symlink (it could point anywhere)
    mkdirSync(dirname(path), { recursive: true });
    const m = /^data:image\/png;base64,(.*)$/s.exec(text);
    writeFileSync(path, m ? Buffer.from(m[1], "base64") : text);
  }
  for (const name of Object.keys(seeded)) if (!(name in files) && !linkOnPath(dir, resolve(dir, name))) rmSync(resolve(dir, name), { force: true });
}

/** True when path, or a folder between dir and it, is a symlink. */
function linkOnPath(dir, path) {
  let p = dir;
  for (const part of relative(dir, path).split(sep)) {
    p = join(p, part);
    try {
      if (lstatSync(p).isSymbolicLink()) return true;
    } catch {
      return false;
    }
  }
  return false;
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
let recording = null; // the screenshot in flight, awaited before the final picture
let recordError = "";
let frameCount = 0;
let code = 0;
if (SCREENSHOT) rmSync(SCREENSHOT, { force: true }); // a picture from an earlier run must not pass for this one
if (RECORD && existsSync(RECORD)) {
  // nor frames from an earlier, longer run: the folder holds this run's frames only
  for (const name of readdirSync(RECORD)) if (FRAME_FILE.test(name)) rmSync(join(RECORD, name), { force: true });
}
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
  const shaderDone = SHADERS ? waiter("SHADER_CHECK_DONE") : null;
  const until = UNTIL ? waiter(UNTIL) : null;
  const abort = ABORTS.length ? waiter(...ABORTS) : null;
  page.on("console", (msg) => {
    const text = `[console.${msg.type()}] ${msg.text()}`;
    lines.push(text);
    if (msg.type() === "error" && !msg.location()?.url?.endsWith("/favicon.ico")) errors.push(text);
    for (const bad of FAIL_ON) if (msg.text().includes(bad)) errors.push(`[fail-on ${bad}] ${msg.text()}`);
    const w = WRITTEN.exec(msg.text());
    if (w) written.push([w[1], w[2]]);
    boot.check(msg.text());
    shaderDone?.check(msg.text());
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
  if (DRIVE && !QUERY_ARGS.has("drive")) extra.set("drive", DRIVE);
  if (LOCALE) extra.set("locale", LOCALE);
  if (SHADERS) extra.set("shadercheck", "1");
  if (DATA_PREFIX && !QUERY_ARGS.has("data-dir")) extra.set("data-dir", DATA_PREFIX);
  const query = [QUERY, extra.toString()].filter(Boolean).join("&");
  await page.goto(query ? `${base}?${query}` : base, { waitUntil: "load", timeout: TIMEOUT_MS });
  if (!(await Promise.race([boot.promise, timeout(TIMEOUT_MS)]))) {
    errors.push(`[smoke] marker ${JSON.stringify(MARKER)} not seen within ${TIMEOUT_MS} ms`);
  } else {
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
    if (until) {
      const hit = await Promise.race([until.promise, abort ? abort.promise.then(() => "abort") : new Promise(() => {}), timeout(TIMEOUT_MS)]);
      if (hit === "abort") {
        /* the DRIVE_ABORT or DRIVE_IGNORED line is already an error (FAIL_ON) */
      } else if (!hit) {
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
    if (shaderDone) {
      const ok = await Promise.race([shaderDone.promise, timeout(TIMEOUT_MS * 4)]);
      if (!ok) errors.push(`[shaders] the shader check did not finish within ${TIMEOUT_MS * 4} ms`);
      else {
        rmSync(SHADER_OUT, { recursive: true, force: true });
        mkdirSync(SHADER_OUT, { recursive: true });
        let n = 0;
        for (const l of lines) {
          const m = /SHADER_PNG (\w+) data:image\/png;base64,(\S+)/.exec(l);
          if (m) {
            writeFileSync(join(SHADER_OUT, `${m[1]}.png`), Buffer.from(m[2], "base64"));
            n += 1;
          }
          const done = /SHADER_CHECK_DONE failed=(\d+)/.exec(l);
          if (done && done[1] !== "0") errors.push(`[shaders] ${done[1]} recipe(s) could not be rendered`);
        }
        console.log(`[info] ${n} shader picture(s) in ${SHADER_OUT}`);
      }
    }
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
  if (DATA_DIR) {
    // #256: raced against a deadline: a frozen page never answers, and the run must end with a failure, not hang
    const files = await Promise.race([
      (async () => {
        await page.evaluate(() => new Promise((r) => setTimeout(r, 50))); // let a pending log flush land
        return page.evaluate((prefix) => {
          const out = {};
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && k.startsWith(prefix)) out[k.slice(prefix.length)] = localStorage.getItem(k);
          }
          return out;
        }, DATA_PREFIX);
      })(),
      timeout(TIMEOUT_MS),
    ]);
    if (files === false) throw new Error(`the page did not hand back its user data within ${TIMEOUT_MS} ms (frozen?)`);
    writeTree(DATA_DIR, files, seeded);
    console.log(`[info] user data (${Object.keys(files).length} file(s)) in ${DATA_DIR}`);
    for (const [marker, name] of written) console.log(`${marker} ${resolve(DATA_DIR, name)}`);
    // a refused or failed scenario is already its one error: what it would have written is not checked
    if (!abort?.seen()) errors.push(...scenarioChecks(files));
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

if (SHADERS && !errors.length) {
  const r = spawnSync(PYTHON, [join(ROOT, "tools", "shaders", "shader_ref.py"), "compare", SHADER_OUT], { encoding: "utf-8" });
  const out = `${r.stdout ?? ""}${r.stderr ?? ""}`.trim();
  if (r.error || r.status === 2 || r.status === null) {
    console.error(`[error] shader_ref.py could not run (${r.error?.message ?? out}); set --python or PYTHON`);
    process.exit(2);
  }
  console.log(out);
  if (r.status === 1) errors.push("[shaders] a recipe differs from its golden image (see the lines above)");
}

// a shader picture is a long data URL: never print it whole
const shown = (l) => (l.includes("SHADER_PNG ") ? `${l.slice(0, 80)}...` : l);
if (VERBOSE || errors.length) for (const l of lines) console.log(shown(l));
else for (const l of lines) if (NOTE.test(l)) console.log(l);
if (errors.length) {
  console.log("[FAIL] errors during smoke:");
  for (const e of errors.slice(0, 20)) console.log(`  ${e}`);
  // only with the proof: a crash hook that wrote nothing, or a game that refused the drive (DRIVE_ABORT: a game
  // without the kit's shell), is a real failure and must not read as the expected one
  const crashProof = written.some(([m]) => m === "CRASH_WRITTEN") && !errors.some((e) => e.startsWith("[drive crash]"));
  if (DRIVE === "crash" && crashProof) console.log("[info] --drive crash fails on purpose: the CRASH_WRITTEN file above is the proof (exit 1 is the pass)");
  if (DRIVE === "pseudo-plant" && errors.some((e) => e.includes("PSEUDO_FAIL") && e.includes("plant.too_small"))) {
    console.log("[info] --drive pseudo-plant fails on purpose: the PSEUDO_FAIL line names the planted label (exit 1 is the pass)");
  }
  code = 1;
} else {
  const what = UNTIL ? `marker ${JSON.stringify(UNTIL)} reached` : `${FRAMES} frames`;
  console.log(`[ OK ] boot marker seen, ${what}, no errors`);
  if (SCREENSHOT) console.log(`[ OK ] screenshot: ${SCREENSHOT}`);
  if (RECORD) console.log(`[ OK ] ${frameCount} frame(s) in ${RECORD} (make a GIF: python tools/art/frames_to_gif.py ${RECORD} out.gif)`);
}
process.exit(code);
