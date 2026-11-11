-- ---------------------------------------------------------------------------
-- game.lua
-- Purpose : The starter game: a box that runs and jumps (with coyote time) on a floor. Replace it with your game;
--           keep the functions the shell's play screen calls (src/shell/screens/play.lua). When the game has
--           Dotwork art (assets/dotwork/*.assets.json), the starter scene shows it: the first character walks in
--           place of the box, a prop stands on the floor, the first map is drawn and a label is set in the first
--           font.
-- Usage   : Game.load(kit, { app = app, save = data_or_nil })   once per play session
--           Game.update(dt)   dt is game time (the player's game_speed applied)
--           Game.draw()       in the 640x360 base (the shell scales it)
--           Game.action(name) a pressed action ("jump", "attack", ...); return true when used
--           Game.save_data()  a table the shell saves to slot 1 when the player leaves (optional)
--           Game.loading_steps() load steps the loading screen runs, one per frame (optional)
-- Notes   : Creates graphics only in draw (and draw never runs headless), so `dev.py smoke --headless` still boots.
--           Input comes as actions from the player's bindings, not raw keys: rebinding works without changes
--           here. Held actions: ctx.app.input:is_down("move_left"). This file is a TEMPLATE: replace it.
--           Dotwork: src/game/dotwork_loader.lua reads the manifests (headless), src/game/dotwork_view.lua draws.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local CoyoteTimer = require("src.core.coyote_timer")
local Manifest = require("src.core.dotwork_manifest")
local DotworkLoader = require("src.game.dotwork_loader")
local DotworkView = require("src.game.dotwork_view")

local SPEED = 140                         -- px/s
local GRAVITY = 900                       -- px/s^2
local JUMP_SPEED = 330                    -- px/s
local FLOOR_Y = 300                       -- top of the floor, in the 640x360 base
local BOX = 20                            -- box size, px
local COYOTE_S = 0.1
local ART_SCALE = 2                       -- Dotwork art is 1x pixel art: drawn at a whole-number scale
local MAP_X, MAP_Y = 16, 40               -- where the first Dotwork map sits (top-left)
local PROP_X = 480                        -- the first prop's pivot (its base) on the floor
local LABEL_X, LABEL_Y = 16, 200          -- the font sample (below the map; the pause hint owns the top-left)
local LABEL_CHARS = 32                    -- the sample shows up to this many of the font's own glyphs

local Game = {}
local box, coyote, runs
local art                                 -- loaded Dotwork manifests ({ models, problems }) or nil
local scene                               -- what the starter scene shows from them (assets; draw objects lazily)

-- The first of each core thing the starter scene shows, from every loaded pack.
local function pick_scene(models)
  local s = {}
  s.hero = DotworkLoader.first(models, "animated_sprite", function(a)
    return a.directions.walk ~= nil or a.clips.walk_e ~= nil or a.clips.walk_s ~= nil
  end) or DotworkLoader.first(models, "animated_sprite")
  s.prop = DotworkLoader.first(models, "sprite")
  s.map = DotworkLoader.first(models, "map")
  s.font = DotworkLoader.first(models, "font")
  if not (s.hero or s.prop or s.map or s.font) then return nil end
  if s.hero then
    local first = s.hero.clips.walk_e or s.hero.clips.walk_s or s.hero.clips[s.hero.clip_order[1]]
    s.player = Manifest.player(first)            -- timing runs in update, headless too
  end
  if s.font then
    local glyphs = {}
    for _, c in ipairs(s.font.char_list) do
      local printable = c.id >= 33 and c.id < 127                -- ASCII only: string.char takes bytes
      if c.w > 0 and printable and #glyphs < LABEL_CHARS then glyphs[#glyphs + 1] = string.char(c.id) end
    end
    s.label = table.concat(glyphs)
  end
  return s
end

local function load_art()
  if not art then
    art = DotworkLoader.load_all()
    scene = pick_scene(art.models)
  end
end

function Game.loading_steps()
  return { { name = "dotwork art", run = load_art } }
end

function Game.load(kit, ctx)
  Game.kit = kit
  box = { x = 100, y = FLOOR_Y - BOX, vy = 0, dir = 1 }
  coyote = CoyoteTimer.new(COYOTE_S)
  local save = ctx and ctx.save or {}
  runs = (tonumber(save.runs) or 0) + 1
  load_art()                                     -- a no-op when the loading screen already ran it
end

-- The walk clip facing the box's direction (directions table first, then walk_e / walk_w names).
local function hero_clip(hero, dir)
  local d = dir > 0 and "e" or "w"
  local name = hero.directions.walk and hero.directions.walk[d] or ("walk_" .. d)
  return hero.clips[name] or hero.clips.walk_e or hero.clips.walk_s
end

function Game.update(dt)
  -- walk back and forth on its own, so a smoke run exercises movement and jumping
  box.x = box.x + box.dir * SPEED * dt
  if box.x < 20 or box.x > 620 - BOX then box.dir = -box.dir end
  box.vy = box.vy + GRAVITY * dt
  box.y = box.y + box.vy * dt
  local on_floor = box.y >= FLOOR_Y - BOX
  if on_floor then box.y, box.vy = FLOOR_Y - BOX, 0 end
  coyote:update(dt, on_floor)
  if scene and scene.player then
    local clip = hero_clip(scene.hero, box.dir)
    if clip then scene.player:play(clip, true) end
    scene.player:update(dt)
  end
  if scene and scene.map_view then scene.map_view:update(dt) end
end

function Game.jump()
  if coyote:can_jump() then
    box.vy = -JUMP_SPEED
    coyote:consume()
  end
end

function Game.action(name)
  if name == "jump" then Game.jump() return true end
  return false
end

function Game.save_data()
  return { runs = runs, level = 1, health = 3 }
end

-- The Dotwork part of the scene; returns true when a character stood in for the box.
local function draw_art()
  if not scene then return false end
  scene.view = scene.view or DotworkView.new()   -- graphics objects only once a window draws
  local view = scene.view
  if scene.map then
    scene.map_view = scene.map_view or view:map(scene.map)
    scene.map_view:draw(MAP_X, MAP_Y, ART_SCALE)
  end
  if scene.prop then view:draw_sprite(scene.prop, PROP_X, FLOOR_Y, ART_SCALE) end
  if scene.font and scene.label ~= "" then view:print(scene.font, scene.label, LABEL_X, LABEL_Y, ART_SCALE) end
  if scene.hero then
    scene.hero_view = scene.hero_view or view:animated(scene.hero, nil, scene.player)   -- the clock lives in update
    scene.hero_view:draw(box.x + BOX / 2, box.y + BOX, ART_SCALE)   -- the pivot (feet) on the box's bottom centre
    return true
  end
  return false
end

function Game.draw()
  love.graphics.clear(0.08, 0.09, 0.12)
  love.graphics.setColor(0.25, 0.27, 0.32)
  love.graphics.rectangle("fill", 0, FLOOR_Y, 640, 360 - FLOOR_Y)
  love.graphics.setColor(1, 1, 1)
  if not draw_art() then
    love.graphics.setColor(0.95, 0.75, 0.3)
    love.graphics.rectangle("fill", box.x, box.y, BOX, BOX)
    love.graphics.setColor(1, 1, 1)
  end
end

return Game

-- {{FOOTER}}
