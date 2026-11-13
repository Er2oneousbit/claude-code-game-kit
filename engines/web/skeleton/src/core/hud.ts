// ---------------------------------------------------------------------------
// hud.ts
// Purpose : Font sizes for a game HUD drawn by the renderer (Phaser text, a Three.js label, a canvas), so it follows
//           the player's display.ui_scale and access.text_scale like the shell's menus do (#309, SOP-20: text size
//           reaches all text).
// Usage   : const px = hudFontPx(16, shell.settings)          // 16 px at 1x, 30 px at ui 1.25x and text 1.5x
//           const off = shell.onLook(() => label.setFontSize(hudFontPx(16, shell.settings)))   // call off() on stop
// Notes   : No renderer import (Vitest runs it). HTML in the shell (the HUD bar in screens.ts) needs none of this:
//           its CSS already multiplies by --ui-scale and --text-scale, so using this there would scale it twice.
//           A primitive, not a layout system: positions and boxes are the game's business (scale them by hudScale).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): new, the HUD font size helper (#309)
// ---------------------------------------------------------------------------

// ---- Tunables ----------------------------------------------------------------
export const HUD_MIN_PX = 6; // never smaller than this, whatever the settings

type LookSettings = { display: { ui_scale: number }; access: { text_scale: number } };

/** How much bigger HUD text is drawn than at 1x: display.ui_scale times access.text_scale. */
export function hudScale(s: LookSettings): number {
  return s.display.ui_scale * s.access.text_scale;
}

/** A HUD font size in whole pixels for a size designed at 1x. */
export function hudFontPx(base: number, s: LookSettings): number {
  return Math.max(HUD_MIN_PX, Math.round(base * hudScale(s)));
}

// {{FOOTER}}
