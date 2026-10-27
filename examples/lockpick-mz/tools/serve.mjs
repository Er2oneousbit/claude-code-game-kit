// ---------------------------------------------------------------------------
// serve.mjs
// Purpose : Serve the MZ game folder (game/, or another folder) over http on localhost. RPG Maker MZ loads its data
//           with XHR, which a page opened from disk (file://) is not allowed to do, so a browser needs a server.
// Usage   : node tools/serve.mjs [--root game] [--port 8080] [--open]      (python tools/dev.py run does this)
//           import { serve } from "./serve.mjs";  const { url, close } = await serve("game");   (smoke.mjs)
// Notes   : Node's standard library only. Read-only, localhost only, no directory listings. A missing file is a
//           real 404 (smoke counts it as an error). Paths are kept inside the root.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { createServer } from "node:http";
import { createReadStream, statSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { spawn } from "node:child_process";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".css": "text/css; charset=utf-8", ".wasm": "application/wasm",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
  ".wav": "audio/wav", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
  ".efkefc": "application/octet-stream", ".txt": "text/plain; charset=utf-8",
};

export function serve(rootDir, port = 0) {
  const root = resolve(rootDir);
  const server = createServer((req, res) => {
    let rel;
    try {
      rel = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    } catch {
      res.writeHead(400).end();
      return;
    }
    if (rel.endsWith("/")) rel += "index.html";
    const file = normalize(join(root, rel));
    if (file !== root && !file.startsWith(root + sep)) {   // ../ tricks stay inside the root
      res.writeHead(403).end();
      return;
    }
    let st;
    try {
      st = statSync(file);
    } catch {
      res.writeHead(404, { "content-type": "text/plain" }).end(`not found: ${rel}`);
      return;
    }
    if (!st.isFile()) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "content-type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
                         "content-length": st.size, "cache-control": "no-store" });
    createReadStream(file).pipe(res);
  });
  return new Promise((ok, fail) => {
    server.once("error", fail);
    server.listen(port, "127.0.0.1", () => {
      const url = `http://127.0.0.1:${server.address().port}/`;
      ok({ url, close: () => new Promise((done) => server.close(done)) });
    });
  });
}

// Command line: python tools/dev.py run
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  const opt = (name, fallback) => {
    const i = args.indexOf(name);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : fallback;
  };
  const root = resolve(opt("--root", "game"));
  const { url } = await serve(root, Number(opt("--port", "8080")));
  console.log(`[ OK ] serving ${root} at ${url} (Ctrl+C to stop)`);
  if (args.includes("--open")) {
    const [cmd, cmdArgs] = process.platform === "win32" ? ["cmd", ["/c", "start", "", url]]
      : process.platform === "darwin" ? ["open", [url]] : ["xdg-open", [url]];
    spawn(cmd, cmdArgs, { stdio: "ignore", detached: true }).unref();
  }
}
