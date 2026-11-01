-- ---------------------------------------------------------------------------
-- audio_access.lua
-- Purpose : Audio accessibility rules with no love.* in them (the tests run them against data/golden/access.json):
--           which settings slider turns which bus of data/audio_events.json up or down, and which arrow a
--           directional caption gets when the sound comes from off screen.
-- Usage   : local AudioAccess = require("src.core.audio_access")
--           AudioAccess.user_bus_gains(events.buses, settings.audio)   -- { music = 0.8, sfx = 1, dialogue = 1, ... }
--           AudioAccess.chain_gain(events.buses, gains, "ambience", "master")   -- what a source on the bus gets
--           AudioAccess.caption_direction(dx, dy, half_w, half_h)       -- -1 on screen, else 0..7
--           AudioAccess.caption_arrow(src_x - cam_x, src_y - cam_y, view_w / 2, view_h / 2)   -- "" | "←" | "↗" ...
-- Notes   : A port of tools/audio/wavesmith/access.py (the reference). Sliders are linear 0..1 (settings.audio), as
--           the settings screen shows them. A bus follows the slider named in SLIDER_FOR_BUS; when one of its parent
--           buses already follows the same slider it gets 1, so a slider never counts twice down one branch
--           (ambience under sfx). Buses without a slider get 1. A bad slider value clamps to 0..1, and a missing,
--           non-numeric (a string, Json.null) or non-finite one counts as 1. Parents default to "master" (master has
--           none); the parent walk stops after one step per bus, so a cycle cannot hang.
--           Arrows: screen coordinates (y grows downwards), eight directions, nothing while the source is on screen
--           (edges included). k = floor(atan2(dy, dx) / 45 degrees + 0.5) mod 8, never a round() (languages
--           disagree on halves). The arrows are UTF-8 strings: the font must have the glyphs (U+2190..U+2199).
--
-- Pseudocode:
--   gains: for each bus: slider = SLIDER_FOR_BUS[bus]; walk the parents; a parent with the same slider -> 1;
--          no slider -> 1; else clamp(slider value)
--   arrow: inside the half sizes -> none; else k from atan2 -> ARROWS[k + 1]
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")

local AudioAccess = {}

-- ---- Tunables ----------------------------------------------------------------
-- Bus name -> settings slider. Edit it when your audio_events.json uses other bus names.
AudioAccess.SLIDER_FOR_BUS = { master = "master", music = "music", sfx = "sfx", ambience = "sfx", ui = "ui",
                               dialogue = "voice", voice = "voice" }
-- Direction k = 0..7 clockwise from the right (y down); Lua index k + 1.
AudioAccess.ARROWS = { "→", "↘", "↓", "↙", "←", "↖", "↑", "↗" }
local ROOT_BUS = "master"                -- the parent of every bus that names none

local function is_finite(v)
  return v == v and v ~= math.huge and v ~= -math.huge
end

-- A slider value as a gain: numbers clamp to 0..1; anything else (missing, a string, null, NaN, inf) is 1.
function AudioAccess.clamp01(v)
  if type(v) ~= "number" or not is_finite(v) then return 1.0 end
  return math.min(1.0, math.max(0.0, v))
end

-- A bus's parent: its "parent" field, else master (master itself has none). A bus missing from the table
-- counts as one with no fields, as in the reference.
local function parent_of(buses, b)
  local def = buses[b]
  local p = type(def) == "table" and def ~= Json.null and def.parent or nil
  if p == Json.null then p = nil end
  if p ~= nil then return p end
  if b == ROOT_BUS then return nil end
  return ROOT_BUS
end

local function count_of(t)
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  return n
end

-- Linear gain per bus from the player's sliders, a slider never applied twice down one branch.
-- buses: { name = { parent = "..." } } (data/audio_events.json "buses"); sliders: settings.audio.
function AudioAccess.user_bus_gains(buses, sliders, mapping)
  mapping = mapping or AudioAccess.SLIDER_FOR_BUS
  sliders = sliders or {}
  local count = count_of(buses)
  local out = {}
  for name in pairs(buses) do
    local slider = mapping[name]
    local inherited = false
    -- walk up the parents (at most one step per bus, so a cycle cannot hang)
    local p, n = parent_of(buses, name), 0
    while p ~= nil and n < count do
      if slider ~= nil and mapping[p] == slider then inherited = true end
      p, n = parent_of(buses, p), n + 1
    end
    if slider == nil or inherited then
      out[name] = 1.0
    else
      out[name] = AudioAccess.clamp01(sliders[slider])
    end
  end
  return out
end

-- The gain a sound on `bus` gets from the sliders: the product of `gains` (user_bus_gains) along the bus and its
-- parents, skipping buses that follow `skip_slider` (LÖVE applies master as the listener volume, so app.lua passes
-- "master"). user_bus_gains already put 1 where a parent has the same slider, so the product counts every
-- slider once. Cycle-safe like user_bus_gains: at most one step per bus.
function AudioAccess.chain_gain(buses, gains, bus, skip_slider, mapping)
  mapping = mapping or AudioAccess.SLIDER_FOR_BUS
  local count = count_of(buses)
  local g, b, n = 1.0, bus, 0
  while b ~= nil and n <= count do
    if skip_slider == nil or mapping[b] ~= skip_slider then g = g * (gains[b] or 1.0) end
    b, n = parent_of(buses, b), n + 1
  end
  return g
end

-- -1 while a sound at (dx, dy) from the view's centre is inside the view (edges included), else the direction
-- 0..7 clockwise from the right (screen y grows downwards).
function AudioAccess.caption_direction(dx, dy, half_w, half_h)
  if type(dx) ~= "number" or type(dy) ~= "number" or not is_finite(dx) or not is_finite(dy) then return -1 end
  if math.abs(dx) <= half_w and math.abs(dy) <= half_h then return -1 end
  local k = math.floor(math.atan2(dy, dx) / (math.pi / 4) + 0.5)
  return k % 8                           -- Lua's % is a floor modulo: -1 % 8 == 7, exact for small integers
end

-- The arrow for a sound at (dx, dy) from the view's centre, or "" while it is inside the view.
function AudioAccess.caption_arrow(dx, dy, half_w, half_h)
  local k = AudioAccess.caption_direction(dx, dy, half_w, half_h)
  if k < 0 then return "" end
  return AudioAccess.ARROWS[k + 1]
end

-- True for the arrows that point left (they go before the caption text; the others go after it).
local LEFT = { ["←"] = true, ["↖"] = true, ["↙"] = true }
function AudioAccess.arrow_leads(arrow)
  return LEFT[arrow] == true
end

return AudioAccess

-- {{FOOTER}}
