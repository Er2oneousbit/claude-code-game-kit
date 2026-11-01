-- ---------------------------------------------------------------------------
-- loading.lua
-- Purpose : The loading screen between the menu and play: runs the load steps one per frame with a progress bar,
--           then replaces itself with the target screen (play or the juice demo).
-- Usage   : app:push("loading", { next = "play" })
--           a game adds real steps with Game.loading_steps() -> { { name = "level", run = function() ... end } }
-- Notes   : A step is any function; keep each short (one frame each), or split big loads into several steps. The
--           screen stays at least MIN_S so it does not flash by (MIN_FRAMES in an automated run).
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")

local Loading = {}

-- ---- Tunables ----------------------------------------------------------------
local MIN_S = 0.6
local MIN_FRAMES = 6
local BAR_W, BAR_H = 360, 12
local FILLER_STEPS = 4                   -- placeholder steps so the bar visibly moves in the template

function Loading:enter(params)
  self.next = params.next or "play"
  self.t, self.frames, self.done = 0, 0, 0
  self.steps = {}
  local ok, Game = pcall(require, "src.game.game")
  if ok and self.next == "play" and type(Game.loading_steps) == "function" then self.steps = Game.loading_steps() end
  for i = #self.steps + 1, FILLER_STEPS do self.steps[i] = { name = "filler" .. i, run = function() end } end
end

function Loading:progress() return #self.steps > 0 and self.done / #self.steps or 1 end

function Loading:update(dt)
  self.t, self.frames = self.t + dt, self.frames + 1
  if self.done < #self.steps then
    self.done = self.done + 1
    self.steps[self.done].run()
    return
  end
  local waited = self.app.kit.automated and self.frames >= MIN_FRAMES or self.t >= MIN_S
  if waited then self.app:replace(self.next) end
end

function Loading:draw(ui)
  local app = self.app
  local x, y = (Style.BASE_W - BAR_W) / 2, Style.BASE_H / 2
  ui:label("loading.title", app:t("loading.title"), 0, y - 40, Style.BASE_W, 24, { align = "center" })
  ui:bar(x, y, BAR_W, BAR_H, self:progress(), Style.color.accent)
  ui:label("loading.percent", app:t("value.percent", { n = math.floor(self:progress() * 100 + 0.5) }), 0, y + 18,
           Style.BASE_W, 20, { align = "center", font = ui:font(Style.SMALL_PX), color = Style.color.dim })
end

-- no input while loading
function Loading:action() return true end

return Loading

-- {{FOOTER}}
