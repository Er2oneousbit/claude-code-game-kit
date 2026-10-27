// ---------------------------------------------------------------------------
// vite.config.ts
// Purpose : Dev server and production build settings.
// Notes   : base "./" keeps every URL relative, so dist/ works from any folder:
//           itch.io HTML5 uploads, GitHub Pages project sites, a plain file server.
//           Files in public/ (public/assets/...) are copied to dist/ as-is.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    assetsInlineLimit: 0, // keep game assets as files (easier to cache and to audit)
    chunkSizeWarningLimit: 2000, // Three.js alone is over the 500 kB default
  },
  server: { port: 5173, open: false },
});

// {{FOOTER}}
