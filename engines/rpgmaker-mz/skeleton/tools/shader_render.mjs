// ---------------------------------------------------------------------------
// shader_render.mjs
// Purpose : Renders every kit shader recipe from game/js/plugins/KitShaders.js the way a PIXI 5 filter runs it
//           (RPG Maker MZ draws with PIXI 5) and writes build/shader_check/<name>.png for
//           tools/shaders/shader_ref.py compare. Needs no MZ project: only Node, Playwright and the plugin file.
// Usage   : node tools/shader_render.mjs [--file game/js/plugins/KitShaders.js] [--out build/shader_check]
//           (python tools/dev.py smoke --shaders runs it, then the compare)
// Exit    : 0 all rendered, 1 a recipe did not compile or render, 2 environment (no Playwright, no plugin file)
// Notes   : Pseudocode
//             read KIT_FRAGMENTS and KIT_SHADERS (JSON) out of the plugin text
//             in headless Chromium, per recipe: a 128x128 input texture with the picture, drawn at 64x64 as a
//             sprite on screen would be (nearest), in its top-left
//             corner (PIXI pads a filter's input to a larger texture), inputSize = (128, 128, 1/128, 1/128),
//             outputFrame = (0, 0, 64, 64), vTextureCoord running top-down over the padded area as PIXI's
//             default filter vertex shader sets it; draw, read the canvas back as PNG
//           The padding is what catches a recipe that forgets the outputFrame / inputSize scale. This emulates the
//           uniforms PIXI hands a filter; it is not PIXI itself (verify: one render inside a real MZ game).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const SIZE = 64;         // the check canvas (tools/shaders/recipes.json)
const PADDED = 128;      // the input texture PIXI would hand the filter

const args = process.argv.slice(2);
const opt = (name, fallback) => (args.indexOf(name) >= 0 ? args[args.indexOf(name) + 1] : fallback);
const ROOT = resolve(import.meta.dirname, "..");
const FILE = resolve(ROOT, opt("--file", "game/js/plugins/KitShaders.js"));
const OUT = resolve(ROOT, opt("--out", "build/shader_check"));
const INPUTS = resolve(ROOT, "data", "shaders", "inputs");

function block(text, name) {
  const m = new RegExp(`${name} = (\\{[\\s\\S]*?\\n\\});`).exec(text);
  if (!m) throw new Error(`no ${name} in ${FILE}`);
  return JSON.parse(m[1]);
}

let fragments, recipes;
try {
  if (!existsSync(FILE)) throw new Error(`${FILE} not found: python tools/shaders/shader_gen.py writes it`);
  const text = readFileSync(FILE, "utf-8");
  fragments = block(text, "KIT_FRAGMENTS");
  recipes = block(text, "KIT_SHADERS");
} catch (err) {
  console.error(`[error] ${err.message}`);
  process.exit(2);
}

const inputUrl = (name) => {
  const f = join(INPUTS, `${name === "sphere" ? "sphere_normal" : name}.png`);
  if (!existsSync(f)) throw new Error(`no input picture ${f}`);
  return `data:image/png;base64,${readFileSync(f).toString("base64")}`;
};

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
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

let failed = 0;
for (const [name, meta] of Object.entries(recipes)) {
  let job;
  try {
    job = { src: fragments[name], main: inputUrl(meta.main), aux: meta.aux ? inputUrl(meta.aux) : null,
            params: meta.params, size: SIZE, padded: PADDED };
  } catch (err) {
    console.error(`[error] ${err.message}`);
    await browser.close();
    process.exit(2);
  }
  const result = await page.evaluate(async ({ src, main, aux, params, size, padded }) => {
    const load = (u) => new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = u; });
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const gl = c.getContext("webgl", { preserveDrawingBuffer: true, premultipliedAlpha: false, antialias: false });
    if (!gl) return { error: "no WebGL in this browser" };
    // PIXI 5's default filter vertex shader, with the projection folded in: y runs top-down
    const vs = "attribute vec2 p; uniform vec4 inputSize; uniform vec4 outputFrame; varying vec2 vTextureCoord;\n" +
      "void main() { vec2 a = vec2(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5);\n" +
      "  vTextureCoord = a * (outputFrame.zw * inputSize.zw); gl_Position = vec4(p, 0.0, 1.0); }";
    const shader = (type, text) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, text);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || "compile failed");
      return s;
    };
    try {
      const prog = gl.createProgram();
      gl.attachShader(prog, shader(gl.VERTEX_SHADER, vs));
      gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, src));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) || "link failed");
      gl.useProgram(prog);
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, "p");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      const texture = async (url, unit, uniform, pad) => {
        const img = await load(url);
        const t = gl.createTexture();
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);   // PIXI uploads top row first
        if (pad) {
          // a filter sees the sprite as drawn on screen: scaled (nearest) to the frame, then padded
          const drawn = document.createElement("canvas");
          drawn.width = drawn.height = size;
          const ctx = drawn.getContext("2d");
          ctx.imageSmoothingEnabled = false;
          ctx.drawImage(img, 0, 0, size, size);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, padded, padded, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
          gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, drawn);
        } else {
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        }
        for (const k of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, k, gl.NEAREST);
        for (const k of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D, k, gl.CLAMP_TO_EDGE);
        gl.uniform1i(gl.getUniformLocation(prog, uniform), unit);
      };
      await texture(main, 0, "uSampler", true);
      if (aux) await texture(aux, 1, "uAuxSampler", false);
      gl.uniform4f(gl.getUniformLocation(prog, "inputSize"), padded, padded, 1 / padded, 1 / padded);
      gl.uniform4f(gl.getUniformLocation(prog, "outputFrame"), 0, 0, size, size);
      for (const [k, v] of Object.entries(params)) {
        const l = gl.getUniformLocation(prog, `u_${k}`);
        if (!l) continue;   // the compiler dropped an unused parameter
        if (Array.isArray(v)) gl[`uniform${v.length}fv`](l, v);
        else gl.uniform1f(l, v);
      }
      gl.viewport(0, 0, size, size);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      return { png: c.toDataURL("image/png") };
    } catch (err) {
      return { error: String(err.message || err) };
    }
  }, job);
  if (result.error) {
    failed += 1;
    console.log(`[FAIL] shader ${name}: ${result.error.trim()}`);
    continue;
  }
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(result.png.split(",")[1], "base64"));
}
await browser.close();
const n = Object.keys(recipes).length - failed;
console.log(`[info] ${n} shader picture(s) in ${OUT}`);
process.exit(failed ? 1 : 0);
