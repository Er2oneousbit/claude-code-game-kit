// ---------------------------------------------------------------------------
// vite.config.ts
// Purpose : Dev server and production build settings.
// Notes   : base "./" keeps every URL relative, so dist/ works from any folder:
//           itch.io HTML5 uploads, GitHub Pages project sites, a plain file server.
//           Files in public/ (public/assets/...) are copied to dist/ as-is.
//           The "ui-assets" plugin lists public/assets/ui/ at build time as `virtual:ui-assets`, so the
//           shell knows which glyph PNGs and theme files exist without requesting a missing one (a 404
//           fails smoke). Restart `dev.py run` after adding files there.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="node" />
import { existsSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const UI_DIR = fileURLToPath(new URL("./public/assets/ui/", import.meta.url));
const VIRTUAL_ID = "virtual:ui-assets";

/** Every file under public/assets/ui/, as paths relative to it ("glyphs/key_space.png"). */
function listUiAssets(dir = UI_DIR): string[] {
  if (!existsSync(dir)) return [];
  const out: string[] = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, e.name);
    if (e.isDirectory()) out.push(...listUiAssets(full));
    else out.push(relative(UI_DIR, full).split(/[\\/]/).join("/"));
  }
  return out.sort();
}

function uiAssets(): Plugin {
  const resolved = "\0" + VIRTUAL_ID;
  return {
    name: "ui-assets",
    resolveId: (id) => (id === VIRTUAL_ID ? resolved : null),
    load: (id) => (id === resolved ? `export default ${JSON.stringify(listUiAssets())};` : null),
  };
}

export default defineConfig({
  base: "./",
  plugins: [uiAssets()],
  build: {
    outDir: "dist",
    assetsInlineLimit: 0, // keep game assets as files (easier to cache and to audit)
    chunkSizeWarningLimit: 2000, // Three.js alone is over the 500 kB default
  },
  server: { port: 5173, open: false },
});

// {{FOOTER}}
