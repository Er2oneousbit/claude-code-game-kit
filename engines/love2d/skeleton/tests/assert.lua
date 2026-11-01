-- ---------------------------------------------------------------------------
-- assert.lua
-- Purpose : Assertions for the project's tests: A.eq, A.near, A.truthy, A.falsy, A.same (deep, numbers compared
--           within a tolerance), A.raises. A failed assertion raises an error the runner reports with the message.
-- Usage   : local A = require("tests.assert"); A.eq(got, want, "what it means")
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = {}

local function fail(msg, detail)
  error((msg and (msg .. ": ") or "") .. detail, 3)
end

local function show(v)
  if type(v) == "string" then return string.format("%q", v) end
  return tostring(v)
end

function A.eq(got, want, msg)
  if got ~= want then fail(msg, "expected " .. show(want) .. ", got " .. show(got)) end
end

function A.near(got, want, tol, msg)
  tol = tol or 1e-6
  if type(got) ~= "number" or math.abs(got - want) > tol then
    fail(msg, "expected " .. show(want) .. " within " .. tol .. ", got " .. show(got))
  end
end

function A.truthy(v, msg) if not v then fail(msg, "expected a true value, got " .. show(v)) end end
function A.falsy(v, msg) if v then fail(msg, "expected a false value, got " .. show(v)) end end

-- Deep comparison: numbers within tol, tables key by key (arrays in order). Returns nil or the first difference.
function A.diff(got, want, tol, path)
  path = path or "$"
  if type(want) == "number" and type(got) == "number" then
    if math.abs(got - want) > (tol or 1e-6) then return path .. ": " .. show(want) .. " ~= " .. show(got) end
    return nil
  end
  if type(want) ~= type(got) then return path .. ": type " .. type(want) .. " ~= " .. type(got) end
  if type(want) ~= "table" then
    if got ~= want then return path .. ": " .. show(want) .. " ~= " .. show(got) end
    return nil
  end
  for k, v in pairs(want) do
    local d = A.diff(got[k], v, tol, path .. "." .. tostring(k))
    if d then return d end
  end
  for k in pairs(got) do
    if want[k] == nil then return path .. "." .. tostring(k) .. ": unexpected key" end
  end
  return nil
end

function A.same(got, want, tol, msg)
  local d = A.diff(got, want, tol)
  if d then fail(msg, d) end
end

function A.raises(fn, msg)
  local ok = pcall(fn)
  if ok then fail(msg, "expected an error") end
end

return A

-- {{FOOTER}}
