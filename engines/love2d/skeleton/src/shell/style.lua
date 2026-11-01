-- ---------------------------------------------------------------------------
-- style.lua
-- Purpose : The built-in look of the menus (colours, sizes, spacing) and the demo palette with its colourblind
--           variants. One table, so a game can restyle the shell without touching screen code.
-- Usage   : local Style = require("src.shell.style")
--           love.graphics.setColor(Style.color.text)     Style.palette("deuteranopia").hit
-- Notes   : Sizes are in the 640x360 base (the shell scales by whole numbers). Focus is never colour alone: the
--           focused item gets an outline and a ">" marker as well (ui.lua). The colourblind setting swaps the
--           DEMO palette only (the box, the player, the hit flash); the menus use a palette that is readable in
--           all four modes already. Dotwork's UI kit (tools/art/dotwork, the widgets lane) can replace this
--           later.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = {}

-- ---- Tunables ----------------------------------------------------------------
Style.BASE_W, Style.BASE_H = 640, 360
Style.FONT_PX = 12                       -- UI text at text_scale 1
Style.TITLE_PX = 28
Style.SMALL_PX = 10
Style.SUBTITLE_PX = { small = 10, medium = 12, large = 16, xl = 20 }
Style.ROW_PAD = 6                        -- px above + below the text in a list row
Style.MARGIN = 24
Style.FOCUS_LINE = 2                     -- focus outline width, px

Style.color = {
  bg = { 0.07, 0.08, 0.11 },
  panel = { 0.13, 0.15, 0.20 },
  panel_edge = { 0.30, 0.34, 0.42 },
  row = { 0.16, 0.18, 0.24 },
  row_focus = { 0.26, 0.30, 0.40 },
  text = { 0.92, 0.93, 0.96 },
  dim = { 0.62, 0.65, 0.72 },
  accent = { 0.98, 0.78, 0.32 },         -- amber: reads in every colourblind mode
  focus = { 1.0, 1.0, 1.0 },
  warn = { 1.0, 0.45, 0.35 },
  bar = { 0.40, 0.70, 1.00 },
  overlay = { 0.0, 0.0, 0.0, 0.62 },
}

-- demo palettes: player, target, hit (the flash and the hit marker), floor, deadzone
local PALETTES = {
  none = { player = { 0.95, 0.75, 0.30 }, target = { 0.35, 0.80, 0.45 }, hit = { 1.0, 0.30, 0.25 },
           floor = { 0.25, 0.27, 0.32 }, deadzone = { 0.5, 0.6, 0.9, 0.35 } },
  -- red and green look alike: blue against orange
  protanopia = { player = { 0.95, 0.70, 0.20 }, target = { 0.25, 0.55, 0.95 }, hit = { 1.0, 1.0, 1.0 },
                 floor = { 0.25, 0.27, 0.32 }, deadzone = { 0.6, 0.6, 0.6, 0.35 } },
  deuteranopia = { player = { 0.95, 0.70, 0.20 }, target = { 0.25, 0.55, 0.95 }, hit = { 1.0, 1.0, 1.0 },
                   floor = { 0.25, 0.27, 0.32 }, deadzone = { 0.6, 0.6, 0.6, 0.35 } },
  -- blue and yellow look alike: red against teal
  tritanopia = { player = { 0.95, 0.35, 0.40 }, target = { 0.20, 0.75, 0.75 }, hit = { 1.0, 1.0, 1.0 },
                 floor = { 0.25, 0.27, 0.32 }, deadzone = { 0.6, 0.6, 0.6, 0.35 } },
}

function Style.palette(mode) return PALETTES[mode] or PALETTES.none end

return Style

-- {{FOOTER}}
