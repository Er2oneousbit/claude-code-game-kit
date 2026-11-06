// ---------------------------------------------------------------------------
// palettes.ts
// Purpose : The demo's colours per colour-blind setting, from data/access/colours.json: the file
//           tools/access/colour_check.py checks, so the colours the game draws are the colours that were checked
//           (#169).
// Usage   : import { PALETTES } from "./palettes";   PALETTES[settings.access.colorblind] ?? PALETTES.none
// Notes   : Colours are numbers (0xrrggbb) as Phaser takes them. A mode the file has no palette for falls back to
//           "none" where it is used (app.ts palette()).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import colourData from "../../data/access/colours.json";

export type Palette = { player: number; target: number; hit: number; ground: number; accent: number };

/** Demo colors per colorblind setting (web applies the option to the juice demo palette only). */
export const PALETTES: Record<string, Palette> = Object.fromEntries(
  Object.entries(colourData.palettes as Record<string, Record<string, string>>).map(([mode, colours]) => [
    mode,
    Object.fromEntries(Object.entries(colours).map(([k, v]) => [k, parseInt(v.replace("#", ""), 16)])) as Palette,
  ]),
);

// {{FOOTER}}
