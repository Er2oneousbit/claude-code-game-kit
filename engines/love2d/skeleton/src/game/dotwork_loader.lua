-- ---------------------------------------------------------------------------
-- dotwork_loader.lua
-- Purpose : Finds and reads the game's Dotwork asset manifests (assets/dotwork/*.assets.json) through
--           love.filesystem, so it works from the game folder and from a packed .love, and checks that every file
--           a manifest names ships and is the size the manifest says. No love.graphics: runs headless (tests,
--           `smoke --headless`); src/game/dotwork_view.lua turns a loaded manifest into images and draws it.
-- Usage   : local Loader = require("src.game.dotwork_loader")
--           local art = Loader.load_all()            -- { models = {...}, problems = {...} }, warnings logged
--           local model = Loader.load("assets/dotwork/town.assets.json")   -- errors on a broken manifest
--           local problems = Loader.verify(model)    -- missing files, PNGs of the wrong size, broken references
--           Loader.find_asset(art.models, "sprite", "crate")
-- Notes   : The parsing is src/core/dotwork_manifest.lua (engine-free). PNGs are decoded with love.image (no
--           window needed) only by verify(): the game's load stays a JSON read. Names are unique per pack, not
--           across packs: find_asset returns the first pack's.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   find(dir): every *.assets.json in dir, sorted
--   load(path): read -> Json.decode -> Manifest.parse (format, major version, kinds) -> model
--   load_all(dir): load each, a failure becomes a problem line (logged), warnings logged once
--   verify(model): model.problems + for each listed file: exists? a PNG decodes, has the listed size, every rect
--                  inside it; a .fnt exists
local Json = require("src.core.json")
local Log = require("src.core.log")
local Manifest = require("src.core.dotwork_manifest")

local Loader = {}

-- ---- Tunables ----------------------------------------------------------------
Loader.DIR = "assets/dotwork"             -- <assets_dir>/dotwork in a LÖVE game
local LOG = "dotwork"                     -- log channel

function Loader.find(dir)
  dir = dir or Loader.DIR
  local out = {}
  if not love.filesystem.getInfo(dir, "directory") then return out end
  for _, name in ipairs(love.filesystem.getDirectoryItems(dir)) do
    if name:sub(-#Manifest.SUFFIX) == Manifest.SUFFIX then out[#out + 1] = dir .. "/" .. name end
  end
  table.sort(out)
  return out
end

function Loader.load(path)
  local text = love.filesystem.read(path)
  if not text then error(path .. ": cannot read the manifest", 0) end
  local ok, doc = pcall(Json.decode, text)
  if not ok then error(path .. ": not valid JSON: " .. tostring(doc), 0) end
  return Manifest.parse(doc, path)
end

-- Every manifest in dir. A manifest that does not load is a problem line, not an error: the game keeps running.
function Loader.load_all(dir)
  local art = { models = {}, problems = {} }
  for _, path in ipairs(Loader.find(dir)) do
    local ok, model = pcall(Loader.load, path)
    if ok then
      for _, w in ipairs(model.warnings) do Log.warn(LOG, w) end
      for _, p in ipairs(model.problems) do Log.warn(LOG, p) end
      art.models[#art.models + 1] = model
      Log.info(LOG, string.format("loaded %s (%d assets, %d skipped)", path, #model.order, #model.skipped))
    else
      art.problems[#art.problems + 1] = tostring(model)
      Log.warn(LOG, tostring(model))
    end
  end
  return art
end

-- The first asset of that kind and name across the loaded packs (nil when none has it).
function Loader.find_asset(models, kind, name)
  for _, m in ipairs(models or {}) do
    if m[kind] and m[kind][name] then return m[kind][name], m end
  end
  return nil
end

-- The first asset of a kind that passes accept(asset) (or any), in pack then manifest order.
function Loader.first(models, kind, accept)
  for _, m in ipairs(models or {}) do
    for _, a in ipairs(m.order) do
      if a.kind == kind and (not accept or accept(a)) then return a, m end
    end
  end
  return nil
end

local function png_problems(f, out)
  local ok, data = pcall(love.image.newImageData, f.path)
  if not ok then
    out[#out + 1] = f.path .. " (" .. f.where .. "): not a readable PNG: " .. tostring(data)
    return
  end
  local w, h = data:getDimensions()
  data:release()
  if f.size and (f.size[1] ~= w or f.size[2] ~= h) then
    out[#out + 1] = string.format("%s (%s): is %dx%d, the manifest says %dx%d", f.path, f.where, w, h,
                                  f.size[1], f.size[2])
  end
  for _, r in ipairs(f.rects) do
    if r[1] < 0 or r[2] < 0 or r[1] + r[3] > w or r[2] + r[4] > h then
      out[#out + 1] = string.format("%s (%s): rect [%d, %d, %d, %d] leaves the %dx%d image", f.path, r.where,
                                    r[1], r[2], r[3], r[4], w, h)
    end
  end
end

-- Everything wrong with a loaded manifest: its broken references plus missing or mis-sized files.
function Loader.verify(model)
  local out = {}
  for _, p in ipairs(model.problems) do out[#out + 1] = p end
  for _, f in ipairs(model.files) do
    if not love.filesystem.getInfo(f.path, "file") then
      out[#out + 1] = f.path .. " (" .. f.where .. "): missing"
    elseif f.path:lower():match("%.png$") then
      png_problems(f, out)
    end
  end
  return out
end

return Loader

-- {{FOOTER}}
