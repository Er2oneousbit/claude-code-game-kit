-- ---------------------------------------------------------------------------
-- subtitles.lua
-- Purpose : Draws the line that is playing (app.track, src/core/dialogue.lua) as a subtitle bar at the bottom of
--           the screen, with the player's settings: on/off, size, background opacity, speaker names, barks;
--           and sound captions ("[thud]") when captions_sfx is on.
-- Usage   : app.subtitles:draw(ui) once per frame (app.lua does it, over every screen)
--           app:say("guide.welcome")              app.subtitles:caption("box_hit")
-- Notes   : TYPEWRITER = true reveals the line character by character from the file's reveal list; false shows
--           the classic cue chunks. The text goes through the string tables first (key "dialogue.<id>"), and in
--           the pseudo-locale through pseudo(), so the layout check covers subtitles too. The speaker's colour is
--           never the only cue: the name is written out.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Dialogue = require("src.core.dialogue")
local I18n = require("src.core.i18n")
local UI = require("src.shell.ui")

local Subtitles = {}
Subtitles.__index = Subtitles

-- ---- Tunables ----------------------------------------------------------------
Subtitles.TYPEWRITER = true
local BAR_W = 520                        -- px, centred
local BOTTOM = 14                        -- px from the bottom edge
local PAD = 6
local CAPTION_MIN_S = 1.0

function Subtitles.new(app)
  return setmetatable({ app = app, captions = {} }, Subtitles)
end

local function hex_color(hex)
  if type(hex) ~= "string" then return Style.color.accent end
  local r, g, b = hex:match("^#(%x%x)(%x%x)(%x%x)$")
  if not r then return Style.color.accent end
  return { tonumber(r, 16) / 255, tonumber(g, 16) / 255, tonumber(b, 16) / 255 }
end

-- the text to show for a line: its translation, else (pseudo-locale) the pseudo text, else the file's text
function Subtitles:text_of(line)
  local app = self.app
  local key = "dialogue." .. line.id
  if app.i18n:has(key) then return app:t(key) end
  if app.i18n:is_pseudo() then return I18n.pseudo(line.text) end
  return line.text
end

function Subtitles:caption(event_id)
  local c = self.app.dialogue.captions[event_id]
  if not c or not self.app.settings.access.captions_sfx then return false end
  local key = "caption." .. event_id
  local text = self.app.i18n:has(key) and self.app:t(key) or
               (self.app.i18n:is_pseudo() and I18n.pseudo(c.text) or c.text)
  self.captions[event_id] = { text = text, t = math.max(c.min_s or CAPTION_MIN_S, CAPTION_MIN_S) }
  return true
end

function Subtitles:update(dt)
  for id, c in pairs(self.captions) do
    c.t = c.t - dt
    if c.t <= 0 then self.captions[id] = nil end
  end
end

function Subtitles:draw(ui)
  local app = self.app
  local access = app.settings.access
  local bottom = Style.BASE_H - BOTTOM
  local cur = app.track:current()
  if cur and Dialogue.allowed(cur.line, app.settings) then
    local font = ui:font(Style.SUBTITLE_PX[access.subtitle_size] or Style.SUBTITLE_PX.medium, true)
    local lh = font:getHeight()
    local full = self:text_of(cur.line)
    local text, shown = full, nil
    if Subtitles.TYPEWRITER then
      local total = UI.utf8_len(cur.line.text)
      local revealed = Dialogue.revealed(cur.line, cur.t)
      shown = total > 0 and math.floor(revealed / total * UI.utf8_len(full) + 0.5) or 0
      if revealed >= total then shown = nil end
    else
      local cue = Dialogue.cue_at(cur.line, cur.t) or {}
      local parts = {}
      for _, l in ipairs(cue) do parts[#parts + 1] = app.i18n:is_pseudo() and I18n.pseudo(l) or l end
      text = table.concat(parts, "\n")
    end
    local inner = BAR_W - PAD * 2
    local _, lines = font:getWrap(text, inner)
    local name_h = access.speaker_names and cur.line.name and lh or 0
    local h = #lines * lh + name_h + PAD * 2
    local x, y = (Style.BASE_W - BAR_W) / 2, bottom - h
    love.graphics.setColor(0, 0, 0, access.subtitle_background)
    love.graphics.rectangle("fill", x, y, BAR_W, h, 4, 4)
    if name_h > 0 then
      ui:label("subtitle.speaker", app:t("subtitle.speaker", { name = cur.line.name }), x + PAD, y + PAD, inner, lh,
               { font = font, color = hex_color(cur.line.color) })
    end
    ui:label("subtitle.text", text, x + PAD, y + PAD + name_h, inner, #lines * lh,
             { font = font, wrap = true, shown = shown })
    bottom = y - 4
  end
  local font = ui:font(Style.SMALL_PX)
  for id, c in pairs(self.captions) do
    local w = font:getWidth(c.text) + PAD * 2
    local h = font:getHeight() + PAD
    local x, y = Style.BASE_W - w - 12, bottom - h
    love.graphics.setColor(0, 0, 0, math.max(access.subtitle_background, 0.4))
    love.graphics.rectangle("fill", x, y, w, h, 3, 3)
    ui:label("caption." .. id, c.text, x + PAD, y, w - PAD * 2, h, { font = font })
    bottom = y - 2
  end
end

return Subtitles

-- {{FOOTER}}
