// ---------------------------------------------------------------------------
// vite-env.d.ts
// Purpose : Type declarations for Vite features the game uses: import.meta.env / import.meta.glob (vite/client),
//           the build-time list of files under public/assets/ui/ (the ui-assets plugin in vite.config.ts) and of
//           Dotwork asset manifests (the dotwork-manifests plugin).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
/// <reference types="vite/client" />

declare module "virtual:ui-assets" {
  /** Paths relative to public/assets/ui/, e.g. "glyphs/key_space.png", "theme_default.css". */
  const files: string[];
  export default files;
}

declare module "virtual:dotwork-manifests" {
  /** Page-relative URLs of public/assets/dotwork/*.assets.json, e.g. "assets/dotwork/town.assets.json". */
  const files: string[];
  export default files;
}
