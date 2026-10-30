// ---------------------------------------------------------------------------
// serve.mjs
// Purpose : Serve the MZ game folder (game/, or another folder) over http on localhost. RPG Maker MZ loads its data
//           with XHR, which a page opened from disk (file://) is not allowed to do, so a browser needs a server.
// Usage   : node tools/serve.mjs [--root game] [--port 8080] [--open]      (python tools/dev.py run does this)
//           import { serve } from "./serve.mjs";  const { url, close } = await serve("game");   (smoke.mjs)
// Notes   : Node's standard library only. Read-only, localhost only, no directory listings. A missing file is a
//           real 404 (smoke counts it as an error). Paths are kept inside the root, after following links
//           (a symlink or junction inside the root that leads out of it is a 404). Only Host headers naming
//           this machine (127.0.0.1, localhost, [::1]) are answered, so a web page cannot reach it under
//           another host name. A read error mid-response ends that response, not the server.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { createServer } from "node:http";
import { createReadStream, realpathSync, statSync } from "node:fs";
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

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);   // Host header names this server answers to

// True when the Host header is a local name with no port or with this server's port
function hostAllowed(host, port) {
  if (!host) return false;
  const m = /^(\[[^\]]*\]|[^:]+)(?::(\d+))?$/.exec(host.toLowerCase());
  return !!m && LOCAL_HOSTS.has(m[1]) && (m[2] === undefined || Number(m[2]) === port);
}

// True when file (a real path) is the real root or inside it
function inside(file, realRoot) {
  return file === realRoot || file.startsWith(realRoot.endsWith(sep) ? realRoot : realRoot + sep);
}

export function serve(rootDir, port = 0) {
  const root = resolve(rootDir);
  let realRoot;
  try {
    realRoot = realpathSync(root);       // the root itself may be a link; compare real paths with real paths
  } catch {
    realRoot = root;                     // a missing root: every request is a 404 anyway
  }
  const server = createServer((req, res) => {
    if (!hostAllowed(req.headers.host, server.address().port)) {
      res.writeHead(403).end();
      return;
    }
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
    let real;
    try {
      real = realpathSync(file);         // stat followed links; the real path must still be inside the root
    } catch {
      real = null;
    }
    if (!real || !inside(real, realRoot)) {
      res.writeHead(404, { "content-type": "text/plain" }).end(`not found: ${rel}`);
      return;
    }
    const stream = createReadStream(real);
    stream.on("error", () => {           // removed or locked after stat: end this response, keep the server
      if (res.headersSent) res.destroy();
      else res.writeHead(500).end();
    });
    stream.once("open", () => {          // headers only once the file is really open, so a failed open is a 500
      res.writeHead(200, { "content-type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
                           "content-length": st.size, "cache-control": "no-store" });
      stream.pipe(res);
    });
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
