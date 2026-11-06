-- ---------------------------------------------------------------------------
-- title.lua
-- Purpose : The title screen: the game's name, "press any key", the version. On the first visit of a run while
--           telemetry consent is still unset, it asks once: Yes / No / Later (Later keeps it unset, so the
--           question comes back next run; nothing is recorded until a Yes).
-- Usage   : app:push("title"); any key or button (after the question) opens the main menu
-- Notes   : The question is a modal list on top of the title: the key that answers it does not also count as
--           the "any key". The prompt blinks, except with reduce motion.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Widgets = require("src.shell.widgets")
local Version = require("src.version")

local Title = {}

-- ---- Tunables ----------------------------------------------------------------
local BLINK_S = 0.6
local CONSENT_W, CONSENT_H = 420, 190         -- the dialog; it grows taller when the text needs it
local CONSENT_PAD = 10

function Title:enter()
  self.t = 0
  local app = self.app
  if not app.asked_consent and app.settings.telemetry.consent == "unset" then
    app.asked_consent = true
    local function answer(value)
      return function()
        app:set_consent(value)
        app:play_sound("accept", "ui")
        self.consent = nil
      end
    end
    self.consent = Widgets.list({
      Widgets.button("yes", function() return app:t("consent.yes") end, answer("yes")),
      Widgets.button("no", function() return app:t("consent.no") end, answer("no")),
      Widgets.button("later", function() return app:t("consent.later") end, answer("unset")),
    }, { on_move = function() app:play_sound("move", "ui") end })
    self.consent:focus("later")
  end
end

function Title:update(dt) self.t = self.t + dt end

function Title:focus_id()
  if self.consent then return "consent." .. self.consent:focused_id() end
  return "title"
end

function Title:open_menu()
  self.app:play_sound("accept", "ui")
  self.app:push("main_menu")
end

function Title:action(name)
  if self.consent then
    if name == "ui_cancel" then                   -- cancel = Later
      self.consent:focus("later")
      self.consent:focused().accept()
      return true
    end
    return self.consent:action(name)
  end
  if name == "ui_accept" then self:open_menu() return true end
  return false
end

-- "press any key / button": everything but the cancel key opens the menu
function Title:raw(binding)
  if self.consent then return false end
  if binding == "key:escape" or binding == "pad:east" then return false end
  self:open_menu()
  return true
end

function Title:draw(ui)
  local app = self.app
  local W, H = Style.BASE_W, Style.BASE_H
  ui:label("title.name", app:t("title.name", { name = Version.name }), 0, H * 0.22, W, 48,
           { align = "center", font = ui:font(Style.TITLE_PX), color = Style.color.accent })
  local reduce = app.settings.access.reduce_motion
  if not self.consent and (reduce or (self.t % (BLINK_S * 2)) < BLINK_S) then
    ui:label("title.press", app:t("title.press_any"), 0, H * 0.62, W, 24, { align = "center" })
  end
  ui:label("title.version", app:t("title.version", { version = Version.version }), 0, H - 26, W - 12, 18,
           { align = "right", font = ui:font(Style.SMALL_PX), color = Style.color.dim })
  if self.consent then
    love.graphics.setColor(Style.color.overlay)
    love.graphics.rectangle("fill", 0, 0, W, H)
    -- every height from the text it holds, so the dialog grows with the text size instead of overflowing (#91: at
    -- 200 % the body ran into the buttons)
    local title_h = ui:font():getHeight()
    local small = ui:font(Style.SMALL_PX)
    local _, body_lines = small:getWrap(app:t("consent.body"), CONSENT_W - 32)
    local body_h = #body_lines * small:getHeight()
    local list_h = #self.consent.rows * (ui:row_h() + 2)
    local ch = math.max(CONSENT_H, CONSENT_PAD + title_h + 4 + body_h + 8 + list_h + CONSENT_PAD)
    local x, y = (W - CONSENT_W) / 2, math.max(4, (H - ch) / 2)
    ui:panel(x, y, CONSENT_W, ch)
    ui:label("consent.title", app:t("consent.title"), x + 16, y + CONSENT_PAD, CONSENT_W - 32, title_h,
             { color = Style.color.accent })
    ui:label("consent.body", app:t("consent.body"), x + 16, y + CONSENT_PAD + title_h + 4, CONSENT_W - 32, body_h,
             { wrap = true, font = small })
    self.consent:draw(ui, x + 110, y + CONSENT_PAD + title_h + 4 + body_h + 8, CONSENT_W - 220,
                      { prefix = "consent", center = true })
  end
end

return Title

-- {{FOOTER}}
