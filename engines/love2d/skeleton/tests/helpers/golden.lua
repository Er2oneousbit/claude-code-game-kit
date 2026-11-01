-- ---------------------------------------------------------------------------
-- golden.lua
-- Purpose : Test helpers for the golden vectors: load data/golden/<file>.json at test time and compare results
--           with the expected values structurally, and turn every case into its own test function.
-- Usage   : local Golden = require("tests.helpers.golden")
--           local g = Golden.load("juice.json")
--           Golden.expect(actual, expected, g.tolerance, "shake/one hit decays step 3")
--           return Golden.suite(g, { shake = function(case, tol) ... end, ... })   -- a runner suite
-- Notes   : The vectors are written by tools/golden_vectors.py (the reference implementation) and shared by every
--           engine of the kit: never copy expected values into a test. Rules: numbers within the file's absolute
--           tolerance (an int 0 equals 0.0), arrays in order, objects as key sets, null equals a missing value,
--           everything else exactly. A case of a type with no handler FAILS, so a new vector type cannot be
--           skipped silently.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local Json = require("src.core.json")

local Golden = {}

-- ---- Tunables ----------------------------------------------------------------
Golden.DIR = "data/golden/"
local NAME_CHARS = "[^%w]+"              -- case names become test names: test_<type>_<nn>_<name>

function Golden.load(file)
  local text = love.filesystem.read(Golden.DIR .. file)
  if not text then error("cannot read " .. Golden.DIR .. file .. " (it ships with the kit: restore it)", 0) end
  local data = Json.decode(text)
  if not Json.is_array(data.cases) or type(data.tolerance) ~= "number" then
    error(file .. ": not a golden vector file", 0)
  end
  return data
end

local function show(v)
  local kind = Json.kind(v)
  if kind == "array" or kind == "object" then
    local ok, text = pcall(Json.encode, v)
    if ok then return #text > 120 and (text:sub(1, 117) .. "...") or text end
  end
  if type(v) == "string" then return string.format("%q", v) end
  return tostring(v)
end

-- The first difference between actual and expected as "path: why", or nil when they match.
function Golden.diff(actual, expected, tol, path)
  path = path or "$"
  if actual == Json.null then actual = nil end
  if expected == Json.null then expected = nil end
  local ek = Json.kind(expected)
  if expected == nil then
    if actual == nil then return nil end
    return path .. ": expected null, got " .. show(actual)
  end
  if ek == "number" then
    if type(actual) ~= "number" then return path .. ": expected number " .. show(expected) .. ", got " .. show(actual) end
    if math.abs(actual - expected) <= tol then return nil end
    return path .. ": expected " .. string.format("%.17g", expected) .. ", got " .. string.format("%.17g", actual)
  end
  if ek == "array" then
    local ak = Json.kind(actual)
    -- an empty Lua table has no kind of its own: accept it for an empty array
    if not (ak == "array" or (type(actual) == "table" and next(actual) == nil)) then
      return path .. ": expected an array, got " .. show(actual)
    end
    if #actual ~= #expected then return path .. ": expected " .. #expected .. " items, got " .. #actual end
    for i = 1, #expected do
      local d = Golden.diff(actual[i], expected[i], tol, path .. "[" .. (i - 1) .. "]")
      if d then return d end
    end
    return nil
  end
  if ek == "object" then
    if type(actual) ~= "table" or (Json.kind(actual) ~= "object" and next(actual) ~= nil) then
      return path .. ": expected an object, got " .. show(actual)
    end
    for k, v in pairs(expected) do
      if v ~= Json.null and actual[k] == nil then return path .. "." .. tostring(k) .. ": missing" end
    end
    for k, v in pairs(actual) do
      if expected[k] == nil and v ~= Json.null then return path .. "." .. tostring(k) .. ": unexpected key" end
    end
    for _, k in ipairs(Json.sorted_keys(expected)) do
      local d = Golden.diff(actual[k], expected[k], tol, path .. "." .. tostring(k))
      if d then return d end
    end
    return nil
  end
  if actual == expected then return nil end
  return path .. ": expected " .. show(expected) .. ", got " .. show(actual)
end

function Golden.expect(actual, expected, tol, where)
  local d = Golden.diff(actual, expected, tol)
  if d then error(where .. ": " .. d, 0) end
end

-- JSON null -> nil (the vectors store a missing text as null)
function Golden.opt(v)
  if v == Json.null then return nil end
  return v
end

-- A runner suite: one test function per case, named test_<type>_<nn>_<name>. handlers[type](case, tol, where)
-- runs one case and returns the number of values it checked. Counts land in Golden.checked[file].
Golden.checked = {}
function Golden.suite(data, handlers, file)
  local suite = {}
  Golden.checked[file] = { cases = 0, values = 0 }
  for index, case in ipairs(data.cases) do
    local name = string.format("test_%s_%02d_%s", tostring(case.type), index, tostring(case.name):gsub(NAME_CHARS, "_"))
    suite[name] = function()
      local handler = handlers[case.type]
      if not handler then
        error("no handler for case type '" .. tostring(case.type) .. "' (" .. tostring(case.name) ..
              "): a new vector type needs a port and a test", 0)
      end
      local n = handler(case, data.tolerance, case.type .. "/" .. tostring(case.name)) or 0
      Golden.checked[file].cases = Golden.checked[file].cases + 1
      Golden.checked[file].values = Golden.checked[file].values + n
    end
  end
  -- runs last (names sort after test_<type>...): prints how much was checked, the proof in the test output
  suite["test_zz_summary_" .. file:gsub("%W", "_")] = function()
    local c = Golden.checked[file]
    print(string.format("GOLDEN %s: %d of %d cases passed, %d values checked", file, c.cases, #data.cases, c.values))
  end
  return suite
end

return Golden

-- {{FOOTER}}
