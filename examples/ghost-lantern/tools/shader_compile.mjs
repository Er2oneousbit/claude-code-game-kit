// ---------------------------------------------------------------------------
// shader_compile.mjs
// Purpose : Compiles every kit shader recipe's fragment shader (the generated GLSL in src/shaders/kit/) with WebGL in
//           headless Chromium, so `dev.py check` fails on a shader error without building or running the game.
// Usage   : node tools/shader_compile.mjs [--file src/shaders/kit/kitShaders.ts]
// Exit    : 0 all compile, 1 a shader does not, 2 environment (no Playwright browser, no generated file)
// Notes   : Compile only (the full render check against the golden images is `dev.py smoke --shaders`). The file is
//           read as text: the JSON after "KIT_FRAGMENTS =" holds one GLSL source per recipe.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const args = process.argv.slice(2);
const at = args.indexOf("--file");
const ROOT = resolve(import.meta.dirname, "..");
const FILE = resolve(ROOT, at >= 0 ? args[at + 1] : "src/shaders/kit/kitShaders.ts");

if (!existsSync(FILE)) {
  console.error(`[error] ${FILE} not found: python tools/shaders/shader_gen.py writes it`);
  process.exit(2);
}
const text = readFileSync(FILE, "utf-8");
const m = /KIT_FRAGMENTS = (\{[\s\S]*?\n\});/.exec(text);
if (!m) {
  console.error(`[error] no KIT_FRAGMENTS in ${FILE}`);
  process.exit(2);
}
const fragments = JSON.parse(m[1]);

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch (err) {
  console.error(`[error] playwright is not installed (${err.message}): run \`python tools/dev.py setup\``);
  process.exit(2);
}
let browser;
try {
  browser = await chromium.launch();
} catch (err) {
  console.error(`[error] headless Chromium did not start (${String(err.message).split("\n")[0]}): python tools/dev.py setup`);
  process.exit(2);
}
const page = await browser.newPage();
const results = await page.evaluate((sources) => {
  const gl = document.createElement("canvas").getContext("webgl");
  if (!gl) return { error: "no WebGL in this browser" };
  const out = {};
  for (const [name, src] of Object.entries(sources)) {
    const s = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    out[name] = gl.getShaderParameter(s, gl.COMPILE_STATUS) ? "" : gl.getShaderInfoLog(s) || "failed";
  }
  return { out };
}, fragments);
await browser.close();
if (results.error) {
  console.error(`[error] ${results.error}`);
  process.exit(2);
}
const bad = Object.entries(results.out).filter(([, log]) => log);
for (const [name, log] of bad) console.log(`[FAIL] shader ${name}:\n  ${log.trim().split("\n").join("\n  ")}`);
if (bad.length) process.exit(1);
console.log(`[ OK ] ${Object.keys(results.out).length} shader recipe(s) compile`);
