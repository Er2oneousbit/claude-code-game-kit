-- ---------------------------------------------------------------------------
-- display_staging.lua
-- Purpose : The Display tab's Apply (#308, SOP-19 section 2): Display changes wait for Apply, every other tab
--           applies at once. Apply sends only the changed fields (mode before resolution); a change to mode or
--           resolution opens "Keep these display settings?" for 15 s of real time, and running out, Revert or Back
--           put back exactly what that Apply replaced. Back with unapplied changes warns once, then discards them.
-- Usage   : local DisplayStaging = require("src.core.display_staging")
--           local st = DisplayStaging.new(app.settings.display)
--           st:stage("mode", "fullscreen")          -- "staged", or "busy" while the confirm is open
--           local calls = st:apply()                -- { { "mode", "fullscreen" }, ... }: set each, then apply
--           st:tick_at(love.timer.getTime())        -- every frame: the countdown in real time; returns revert calls
--           st:keep() ; st:revert() ; st:back()     -- back() -> "revert" | "warn" | "leave", calls
-- Notes   : Engine-free (no love.*), held to data/golden/shell.json's display_staging cases, which
--           tools/golden_vectors.py (DisplayStaging, the reference) writes. Values are deep-copied and compared by
--           value (tables element by element, numbers by value), so a resolution table equal to the applied one
--           drops the pending change. tick_at(now) counts from clock readings, never from the frame dt, so the
--           game-speed setting, a hitstop or a fixed-step smoke run cannot stretch or shrink the 15 s.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   stage(f, v): confirm open -> "busy"; v equals applied -> drop f from pending; else pending[f] = copy(v)
--   apply: changed = pending fields unlike applied -> replaced = their applied values -> set them in
--          APPLY_ORDER -> mode or resolution among them: open the confirm (CONFIRM_S)
--   tick(dt): left -= dt; left <= 0 -> revert ; seconds() = ceil(left)
--   back: confirm open -> revert ; pending and not warned -> warn ; else discard pending, leave

local DisplayStaging = {}
DisplayStaging.__index = DisplayStaging

-- ---- Tunables ----------------------------------------------------------------
DisplayStaging.APPLY_ORDER = { "mode", "resolution", "vsync", "frame_cap", "ui_scale" }   -- mode before resolution
DisplayStaging.CONFIRM_FIELDS = { mode = true, resolution = true }   -- can black out the screen: Apply asks first
DisplayStaging.CONFIRM_S = 15.0                                      -- real seconds before an unanswered confirm reverts

local function copy(v)
  if type(v) ~= "table" then return v end
  local out = {}
  for k, x in pairs(v) do out[k] = copy(x) end
  return setmetatable(out, getmetatable(v))   -- keeps a Json.array / Json.object mark
end

-- Equal by value: numbers by value (1 == 1.0), tables key by key, everything else exactly.
function DisplayStaging.same(a, b)
  if type(a) ~= "table" or type(b) ~= "table" then return a == b end
  for k, v in pairs(a) do
    if not DisplayStaging.same(v, b[k]) then return false end
  end
  for k in pairs(b) do
    if a[k] == nil then return false end
  end
  return true
end

function DisplayStaging.new(applied)
  return setmetatable({ applied = copy(applied), pending = {}, replaced = {}, left = nil, warned = false,
                        last_now = nil }, DisplayStaging)
end

-- The value the control shows: the staged one, else the applied one.
function DisplayStaging:value(field)
  if self.pending[field] ~= nil then return self.pending[field] end
  return self.applied[field]
end

function DisplayStaging:has_pending() return next(self.pending) ~= nil end
function DisplayStaging:confirming() return self.left ~= nil end

function DisplayStaging:stage(field, v)
  if self.left ~= nil then return "busy" end
  if DisplayStaging.same(v, self.applied[field]) then
    self.pending[field] = nil
  else
    self.pending[field] = copy(v)
  end
  self.warned = false
  return "staged"
end

-- sets values (a field -> value table) in APPLY_ORDER; returns the calls { { field, value }, ... }
function DisplayStaging:_set(values)
  local calls = {}
  for _, field in ipairs(DisplayStaging.APPLY_ORDER) do
    if values[field] ~= nil then
      self.applied[field] = copy(values[field])
      calls[#calls + 1] = { field, copy(values[field]) }
    end
  end
  return calls
end

function DisplayStaging:apply()
  local changed = {}
  for f, v in pairs(self.pending) do
    if not DisplayStaging.same(v, self.applied[f]) then changed[f] = v end
  end
  self.replaced = {}
  for f in pairs(changed) do self.replaced[f] = copy(self.applied[f]) end
  self.pending = {}
  self.warned = false
  local calls = self:_set(changed)
  for f in pairs(changed) do
    if DisplayStaging.CONFIRM_FIELDS[f] then
      self.left = DisplayStaging.CONFIRM_S
      self.last_now = nil
      break
    end
  end
  return calls
end

-- ceil(left) for the "Reverting in N s" line, nil while no confirm is open
function DisplayStaging:seconds()
  if self.left == nil then return nil end
  return math.ceil(self.left)
end

function DisplayStaging:tick(dt)
  if self.left == nil then return {} end
  self.left = self.left - dt
  if self.left <= 0 then return self:revert() end
  return {}
end

-- The countdown from clock readings (seconds, e.g. love.timer.getTime()): the first reading after Apply starts it.
function DisplayStaging:tick_at(now)
  if self.left == nil then self.last_now = nil return {} end
  local dt = self.last_now and math.max(0, now - self.last_now) or 0
  self.last_now = now
  return self:tick(dt)
end

function DisplayStaging:keep()
  self.left = nil
  self.replaced = {}
end

function DisplayStaging:revert()
  local calls = self:_set(self.replaced)
  self.left = nil
  self.replaced = {}
  return calls
end

-- "revert" (a confirm was open), "warn" (unapplied changes, first time), or "leave"; plus the calls to make.
function DisplayStaging:back()
  if self.left ~= nil then return "revert", self:revert() end
  if self:has_pending() and not self.warned then
    self.warned = true
    return "warn", {}
  end
  self.pending = {}
  self.warned = false
  return "leave", {}
end

return DisplayStaging

-- {{FOOTER}}
