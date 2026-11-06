-- ---------------------------------------------------------------------------
-- test_access_colours.lua
-- Purpose : The demo palette per colour-blind setting comes from data/access/colours.json, the file
--           tools/access/colour_check.py checks (#169): every mode the file names is what Style.palette returns,
--           a mode or colour the file leaves out falls back, and the deadzone overlay stays the shell's own.
-- Usage   : python tools/dev.py test     (or --filter access_colours)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local Style = require("src.shell.style")
local T = {}

local function hex(s)
  local r, g, b = s:match("^#(%x%x)(%x%x)(%x%x)$")
  return { tonumber(r, 16) / 255, tonumber(g, 16) / 255, tonumber(b, 16) / 255 }
end

function T.test_every_mode_in_the_file_is_the_palette_the_demo_draws()
  local data = Json.decode(love.filesystem.read(Style.COLOURS_FILE))
  local seen = 0
  for mode, colours in pairs(data.palettes) do
    local pal = Style.palette(mode)
    for name, value in pairs(colours) do
      A.same(pal[name], hex(value), 1e-9, mode .. "." .. name)
    end
    A.eq(#pal.deadzone, 4, mode .. " keeps its deadzone overlay")
    seen = seen + 1
  end
  A.eq(seen, 4, "the file has a palette for none and each colour-blind mode")
end

function T.test_a_missing_mode_or_colour_falls_back()
  local p = Style.palettes_from({ palettes = { none = { player = "#ff0000", target = "#00ff00", hit = "#ffffff",
                                                         floor = "#000000" },
                                               tritanopia = { player = "#0000ff" } } })
  A.same(p.tritanopia.player, { 0, 0, 1 }, 1e-9, "its own colour")
  A.same(p.tritanopia.target, { 0, 1, 0 }, 1e-9, "the rest from none")
  local empty = Style.palettes_from(nil)
  A.truthy(empty.none.player and empty.none.floor, "no file: the built-in colours")
end

return T
