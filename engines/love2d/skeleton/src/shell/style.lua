-- ---------------------------------------------------------------------------
-- style.lua
-- Purpose : The built-in look of the menus (colours, sizes, spacing) and the demo palette with its colourblind
--           variants. One table, so a game can restyle the shell without touching screen code.
-- Usage   : local Style = require("src.shell.style")
--           love.graphics.setColor(Style.color.text)     Style.palette("deuteranopia").hit
--           Style.hud_font_size(12, text_scale, ui_scale)   -- a game HUD's font size (app:hud_font(12) does it all)
-- Notes   : Sizes are in the 640x360 base (the shell scales by whole numbers). Focus is never colour alone: the
--           focused item gets an outline and a ">" marker as well (ui.lua). The colourblind setting swaps the
--           DEMO palette only (the box, the player, the hit flash); the menus use a palette that is readable in
--           all four modes already. Dotwork's UI kit (tools/art/dotwork, the widgets lane) can replace this
--           later.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): hud_font_size, the size a game HUD's text gets from
--           the player's text size and UI scale (#309)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")

local Style = {}

-- ---- Tunables ----------------------------------------------------------------
Style.BASE_W, Style.BASE_H = 640, 360
Style.FONT_PX = 12                       -- UI text at text_scale 1
Style.READABLE_FONT = "src/shell/fonts/AtkinsonHyperlegible-Regular.ttf"   -- access.readable_font (#167)
Style.TITLE_PX = 28
Style.SMALL_PX = 10
Style.MIN_FONT_PX = 6                    -- no text smaller than this, whatever the scales say
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

-- demo palettes (player, target, hit: the flash and the hit marker, floor) from data/access/colours.json, which
-- tools/access/colour_check.py checks (#169); the deadzone overlay is not an important colour and stays here
Style.COLOURS_FILE = "data/access/colours.json"
local DEADZONE = { none = { 0.5, 0.6, 0.9, 0.35 }, other = { 0.6, 0.6, 0.6, 0.35 } }
local FALLBACK = { player = { 0.95, 0.75, 0.30 }, target = { 0.35, 0.80, 0.45 }, hit = { 1.0, 0.30, 0.25 },
                   floor = { 0.25, 0.27, 0.32 } }

local function hex(s)
  local r, g, b = tostring(s):match("^#?(%x%x)(%x%x)(%x%x)$")
  if not r then return nil end
  return { tonumber(r, 16) / 255, tonumber(g, 16) / 255, tonumber(b, 16) / 255 }
end

-- {mode: {name: {r, g, b}}} from a decoded colours.json (pure: the tests call it without LÖVE)
function Style.palettes_from(data)
  local out = {}
  for mode, colours in pairs(type(data) == "table" and type(data.palettes) == "table" and data.palettes or {}) do
    local p = {}
    for name, value in pairs(colours) do p[name] = hex(value) end
    p.deadzone = DEADZONE[mode] or DEADZONE.other
    out[mode] = p
  end
  if not out.none then out.none = { deadzone = DEADZONE.none } end
  for _, p in pairs(out) do   -- a colour a mode leaves out comes from "none", then the built-in one
    for k, v in pairs(FALLBACK) do
      if p[k] == nil then p[k] = out.none[k] or v end
    end
  end
  return out
end

local PALETTES
local function palettes()
  if not PALETTES then
    local text = love and love.filesystem and love.filesystem.read(Style.COLOURS_FILE)
    local ok, data = false, nil
    if text then ok, data = Json.try_decode(text) end
    PALETTES = Style.palettes_from(ok and data or nil)
  end
  return PALETTES
end

-- The pixel size of a game HUD's text: base (px at scale 1, in the 640x360 base) times the player's
-- access.text_scale and display.ui_scale, whole pixels, never under MIN_FONT_PX. The menus use the same product
-- (ui.lua's scale), so a HUD drawn with it matches them. Pure: tests call it without LÖVE.
function Style.hud_font_size(base, text_scale, ui_scale)
  return math.max(Style.MIN_FONT_PX, math.floor(base * (text_scale or 1) * (ui_scale or 1) + 0.5))
end

function Style.palette(mode) local p = palettes() return p[mode] or p.none end

return Style

-- {{FOOTER}}
