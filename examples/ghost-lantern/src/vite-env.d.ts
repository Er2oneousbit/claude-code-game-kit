// ---------------------------------------------------------------------------
// vite-env.d.ts
// Purpose : Type declarations for Vite features the game uses: import.meta.env / import.meta.glob (vite/client)
//           and the build-time list of files under public/assets/ui/ (the ui-assets plugin in vite.config.ts).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="vite/client" />

declare module "virtual:ui-assets" {
  /** Paths relative to public/assets/ui/, e.g. "glyphs/key_space.png", "theme_default.css". */
  const files: string[];
  export default files;
}
