-- ---------------------------------------------------------------------------
-- juice_demo.lua
-- Purpose : The juice demo (debug builds): a box you hit (attack) that shakes the camera with trauma, freezes
--           the game for a hitstop, squashes on a spring and flashes the screen through the FlashLimiter; a follow
--           camera with a visible deadzone; an input-buffered jump with coyote time; a held guard (interact) that
--           honours hold_to_toggle; a subtitle line and a bark; and the accessibility settings applied live.
-- Usage   : main menu > Juice demo  (or python tools/dev.py smoke --drive show:juice --screenshot captures/juice.png)
-- Notes   : Time: the hitstop and the flash limiter run on REAL time (love.timer's dt); everything else (shake,
--           follow, spring, input buffer, coyote) runs on GAME time = the hitstop-scaled dt times game_speed.
--           The limiter is always on (at most 3 flashes per real second); access.flash_limit only tones each
--           flash down to FLASH_GENTLE. Shake intensity is Settings.effective_shake (0 with reduce motion).
--           Colourblind modes swap this demo's palette (src/shell/style.lua), not the whole screen.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Style = require("src.shell.style")
local Settings = require("src.core.settings")
local Shake = require("src.core.shake")
local Hitstop = require("src.core.hitstop")
local FollowCamera = require("src.core.follow_camera")
local InputBuffer = require("src.core.input_buffer")
local CoyoteTimer = require("src.core.coyote_timer")
local Spring = require("src.core.spring")
local FlashLimiter = require("src.core.flash_limiter")
local Ease = require("src.core.ease")

local Demo = { pausable = true }

-- ---- Tunables ----------------------------------------------------------------
local WORLD_W = 1600
local FLOOR_Y = 300
local PLAYER = 20
local TARGET = 40
local TARGET_X = 440
local SPEED = 160
local GRAVITY = 900
local JUMP_SPEED = 340
local HIT_RANGE = 80                     -- px between centres
local HIT_TRAUMA = 0.55
local HIT_STOP_S = 0.09
local HIT_SQUASH = 0.45                  -- spring displacement on a hit
local FLASH_S = 0.12                     -- a flash fades out over this (real time)
local FLASH_FULL, FLASH_GENTLE = 0.85, 0.3   -- peak opacity without / with access.flash_limit
local INTRO_LINE, HIT_BARK, HIT_CAPTION = "guide.welcome", "box.ouch", "box_hit"
local POP_S = 0.25                       -- the "hit!" marker eases out over this

function Demo:enter()
  local app = self.app
  self.player = { x = 380, y = FLOOR_Y - PLAYER, vx = 0, vy = 0 }
  self.shake = Shake.new({ max_offset = 10, max_angle = 0.04 })
  self.hitstop = Hitstop.new()
  self.cam = FollowCamera.new({ deadzone_w = 96, deadzone_h = 64, lookahead = 0.2, smoothing = 6,
                                x = self.player.x, y = FLOOR_Y - 80 })
  self.buffer = InputBuffer.new()
  self.coyote = CoyoteTimer.new(0.1)
  self.spring = Spring.new(4.0, 0.35)
  self.limiter = FlashLimiter.new()
  self.real_time, self.flash, self.flash_peak = 0, 0, 0
  self.hits, self.refused, self.pop = 0, 0, 0
  self.guard, self.offset = false, { 0, 0, 0 }
  app:say(INTRO_LINE)
end

function Demo:hit()
  local app = self.app
  local p = self.player
  if math.abs((p.x + PLAYER / 2) - (TARGET_X + TARGET / 2)) > HIT_RANGE then return end
  self.hits = self.hits + 1
  self.shake:add_trauma(HIT_TRAUMA)
  self.hitstop:hit(HIT_STOP_S)
  self.spring.x = HIT_SQUASH
  self.pop = POP_S
  if self.limiter:request(self.real_time) then            -- real time: always rate-limited
    self.flash = FLASH_S
    self.flash_peak = app.settings.access.flash_limit and FLASH_GENTLE or FLASH_FULL
  else
    self.refused = self.refused + 1
  end
  app:play_sound("hit", "sfx")
  app.subtitles:caption(HIT_CAPTION)
  app:say(HIT_BARK)
end

function Demo:action(name)
  if name == "pause" then self.app:push("pause") return true end
  if name == "jump" then self.buffer:press("jump") return true end
  if name == "attack" then self:hit() return true end
  if name == "interact" and self.app.settings.access.hold_to_toggle then self.guard = not self.guard return true end
  return false
end

function Demo:update(real_dt)
  local app = self.app
  local input = app.input
  self.real_time = self.real_time + real_dt
  self.flash = math.max(0, self.flash - real_dt)
  local dt = self.hitstop:scaled_dt(real_dt) * app:game_speed()          -- game time from here on
  local p = self.player
  local stick_x = input:move_vector()
  local dir = (input:is_down("move_right") and 1 or 0) - (input:is_down("move_left") and 1 or 0)
  if dir == 0 then dir = stick_x end
  p.vx = dir * SPEED
  p.x = math.max(0, math.min(WORLD_W - PLAYER, p.x + p.vx * dt))
  p.vy = p.vy + GRAVITY * dt
  p.y = p.y + p.vy * dt
  local on_floor = p.y >= FLOOR_Y - PLAYER
  if on_floor then p.y, p.vy = FLOOR_Y - PLAYER, 0 end
  self.coyote:update(dt, on_floor)
  self.buffer:update(dt)
  if self.coyote:can_jump() and self.buffer:consume("jump") then
    p.vy = -JUMP_SPEED
    self.coyote:consume()
  end
  if not app.settings.access.hold_to_toggle then self.guard = input:is_down("interact") end
  self.cam:update(dt, p.x + PLAYER / 2, p.y, p.vx, 0)
  local x, y, angle = self.shake:update(dt, Settings.effective_shake(app.settings))
  self.offset = { x, y, angle }
  self.spring:update(dt)
  self.pop = math.max(0, self.pop - dt)
end

function Demo:draw(ui)
  local app = self.app
  local W, H = Style.BASE_W, Style.BASE_H
  local pal = Style.palette(app.settings.access.colorblind)
  love.graphics.setColor(Style.color.bg)
  love.graphics.rectangle("fill", 0, 0, W, H)
  love.graphics.push()
  love.graphics.translate(W / 2, H / 2)
  love.graphics.rotate(self.offset[3])
  love.graphics.translate(-W / 2 + self.offset[1], -H / 2 + self.offset[2])
  love.graphics.translate(math.floor(W / 2 - self.cam.x), math.floor(H / 2 - self.cam.y))
  love.graphics.setColor(pal.floor)
  love.graphics.rectangle("fill", -200, FLOOR_Y, WORLD_W + 400, 200)
  for gx = 0, WORLD_W, 80 do                              -- floor marks, so camera motion is visible
    love.graphics.setColor(Style.color.panel_edge)
    love.graphics.rectangle("fill", gx, FLOOR_Y + 6, 2, 8)
  end
  local sx, sy = Spring.squash(self.spring.x)
  love.graphics.setColor(pal.target)
  local tw, th = TARGET * sx, TARGET * sy
  love.graphics.rectangle("fill", TARGET_X + (TARGET - tw) / 2, FLOOR_Y - th, tw, th)
  local p = self.player
  love.graphics.setColor(pal.player)
  love.graphics.rectangle("fill", p.x, p.y, PLAYER, PLAYER)
  if self.guard then
    love.graphics.setColor(pal.player)
    love.graphics.setLineWidth(2)
    love.graphics.circle("line", p.x + PLAYER / 2, p.y + PLAYER / 2, PLAYER)
  end
  if self.pop > 0 then                                    -- an eased "hit" ring on the box
    local k = Ease.ease("out_back", 1 - self.pop / POP_S)
    love.graphics.setColor(pal.hit)
    love.graphics.setLineWidth(2)
    love.graphics.circle("line", TARGET_X + TARGET / 2, FLOOR_Y - TARGET / 2, 10 + 30 * k)
  end
  love.graphics.setColor(pal.deadzone)
  love.graphics.setLineWidth(1)
  love.graphics.rectangle("line", self.cam.x - self.cam.deadzone_w / 2, self.cam.y - self.cam.deadzone_h / 2,
                          self.cam.deadzone_w, self.cam.deadzone_h)
  love.graphics.pop()
  if self.flash > 0 then
    local c = pal.hit
    love.graphics.setColor(c[1], c[2], c[3], self.flash_peak * (self.flash / FLASH_S))
    love.graphics.rectangle("fill", 0, 0, W, H)
  end
  self:draw_hud(ui)
end

function Demo:draw_hud(ui)
  local app = self.app
  local font = ui:font(Style.SMALL_PX)
  local black = { 0, 0, 0 }                              -- HUD text is outlined: it reads over any part of the game
  local title_h = ui:font():getHeight()
  ui:label("juice.title", app:t("juice.title"), 12, 8, 300, title_h, { color = Style.color.accent, outline = black })
  -- the controls with their prompts, wrapping to another row when a language or a large text size makes them long;
  -- rows are as tall as the text (#91: fixed 22 px rows ran into each other at 200 % text)
  local row = math.max(20, font:getHeight() + 4)
  local x, y = 12, 8 + title_h + 4
  for _, action in ipairs({ "move_left", "move_right", "jump", "attack", "interact", "pause" }) do
    local gname, label = app:prompt(action)
    local text = app:t("action." .. action)
    local tw = font:getWidth(text)
    local need = font:getWidth(label) + 8 + tw + 6
    if x + need > Style.BASE_W - 12 and x > 12 then x, y = 12, y + row + 2 end
    local w = ui:glyph_cell("juice.glyph." .. action, gname, label, x, y, row, { outline = black })
    ui:label("juice.action." .. action, text, x + w + 4, y, tw + 2, row,
             { font = font, color = Style.color.dim, outline = black })
    x = x + w + tw + 16
  end
  self.hud_bottom = y + row + 4
  local stats = app:t("juice.stats", { hits = self.hits, trauma = string.format("%.2f", self.shake.trauma),
    shake = string.format("%.2f", Settings.effective_shake(app.settings)),
    refused = self.refused, speed = math.floor(app:game_speed() * 100 + 0.5) })
  local _, stat_lines = font:getWrap(stats, Style.BASE_W - 24)
  local stats_h = #stat_lines * ui:line_h(font)
  ui:label("juice.stats", stats, 12, self.hud_bottom, Style.BASE_W - 24, stats_h,
           { font = font, color = Style.color.dim, wrap = true, outline = black })
  if self.guard then
    ui:label("juice.guard", app:t("juice.guard"), 12, self.hud_bottom + stats_h, 300, font:getHeight(),
             { font = font, color = Style.color.accent, outline = black })
  end
end

return Demo

-- {{FOOTER}}
