-- ---------------------------------------------------------------------------
-- json.lua
-- Purpose : A small JSON reader and writer (LÖVE has none): enough for settings, saves, string tables, dialogue
--           and the golden vectors. Numbers become Lua numbers, null becomes Json.null (so a key that holds null
--           still exists), and arrays and objects keep their kind, so an empty [] writes back as [] and {} as {}.
-- Usage   : local Json = require("src.core.json")
--           local ok, value = Json.try_decode(text)        -- ok false: value is the error message
--           local value = Json.decode(text)                -- raises on bad JSON
--           local text = Json.encode(value, { indent = 2 }) -- keys sorted, so files diff cleanly
--           Json.array({}) / Json.object({}) mark a table's kind; Json.kind(v) tells what a value is
-- Notes   : No love.* calls (the tests run it without a window). A plain Lua table (not made by the decoder or
--           marked) counts as an array when its keys are exactly 1..n with n >= 1, else as an object; an EMPTY
--           plain table is an object. Mark a list that can be empty with Json.array, or it writes back as {}.
--           Json.copy keeps the marks. Strict JSON only: no comments, no trailing commas, no NaN or Infinity.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
--
-- Pseudocode
--   decode: recursive descent over the bytes; value = object | array | string | number | true | false | null
--           strings: escapes and \uXXXX (surrogate pairs too) become UTF-8; then only whitespace may follow
--   encode: kind of value -> text; objects with sorted keys; numbers in the shortest form that reads back exact
local Json = {}

-- ---- Tunables ----------------------------------------------------------------
local MAX_DEPTH = 200                     -- nesting limit (a hostile file must not overflow the Lua stack)
local INT_LIMIT = 2 ^ 53                  -- integral numbers below this print without a decimal point

local ARRAY_MT = { __jsonkind = "array" }
local OBJECT_MT = { __jsonkind = "object" }

-- The JSON null. A unique table, so `value == Json.null` is the test.
Json.null = setmetatable({}, { __jsonkind = "null", __tostring = function() return "null" end })

function Json.array(t) return setmetatable(t or {}, ARRAY_MT) end
function Json.object(t) return setmetatable(t or {}, OBJECT_MT) end

-- "null" | "boolean" | "number" | "string" | "array" | "object" | nil (functions, userdata)
function Json.kind(v)
  local t = type(v)
  if t == "nil" then return "null" end
  if t == "boolean" or t == "number" or t == "string" then return t end
  if t ~= "table" then return nil end
  if v == Json.null then return "null" end
  local mt = getmetatable(v)
  if mt == ARRAY_MT then return "array" end
  if mt == OBJECT_MT then return "object" end
  local n = 0
  for k in pairs(v) do
    if type(k) ~= "number" or k < 1 or k ~= math.floor(k) then return "object" end
    n = n + 1
  end
  if n == 0 then return "object" end
  for i = 1, n do if v[i] == nil then return "object" end end
  return "array"
end

function Json.is_array(v) return Json.kind(v) == "array" end
function Json.is_object(v) return Json.kind(v) == "object" end

-- A deep copy that keeps the array / object marks (Json.null stays the one null).
function Json.copy(v)
  if type(v) ~= "table" or v == Json.null then return v end
  local out = {}
  for k, x in pairs(v) do out[k] = Json.copy(x) end
  return setmetatable(out, getmetatable(v))
end

-- Sorted keys of a table (strings before numbers would be odd: JSON keys are strings, so compare as text).
function Json.sorted_keys(t)
  local keys = {}
  for k in pairs(t) do keys[#keys + 1] = k end
  table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
  return keys
end

-- ---- Decoder -------------------------------------------------------------------
local ESCAPES = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }

local function utf8_char(cp)
  if cp < 0x80 then return string.char(cp) end
  if cp < 0x800 then
    return string.char(0xC0 + math.floor(cp / 0x40), 0x80 + cp % 0x40)
  end
  if cp < 0x10000 then
    return string.char(0xE0 + math.floor(cp / 0x1000), 0x80 + math.floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
  end
  return string.char(0xF0 + math.floor(cp / 0x40000), 0x80 + math.floor(cp / 0x1000) % 0x40,
                     0x80 + math.floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
end

local function decode_error(text, pos, what)
  local line, col = 1, 1
  for i = 1, math.min(pos - 1, #text) do
    if text:sub(i, i) == "\n" then line, col = line + 1, 1 else col = col + 1 end
  end
  error(string.format("json: %s at line %d column %d", what, line, col), 0)
end

local function skip_ws(text, pos)
  return text:find("[^ \t\r\n]", pos) or (#text + 1)
end

local decode_value

local function decode_string(text, pos)
  -- pos is at the opening quote
  local parts, i = {}, pos + 1
  while true do
    local j = text:find('["\\%c]', i)
    if not j then decode_error(text, pos, "unterminated string") end
    parts[#parts + 1] = text:sub(i, j - 1)
    local c = text:sub(j, j)
    if c == '"' then return table.concat(parts), j + 1 end
    if c ~= "\\" then decode_error(text, j, "control character in string") end
    local e = text:sub(j + 1, j + 1)
    if e == "u" then
      local hex = text:sub(j + 2, j + 5)
      if not hex:match("^%x%x%x%x$") then decode_error(text, j, "bad \\u escape") end
      local cp = tonumber(hex, 16)
      local next_i = j + 6
      if cp >= 0xD800 and cp <= 0xDBFF then                  -- a surrogate pair: 😀
        local lo = text:match("^\\u(%x%x%x%x)", next_i)
        local lo_cp = lo and tonumber(lo, 16)
        if lo_cp and lo_cp >= 0xDC00 and lo_cp <= 0xDFFF then
          cp = 0x10000 + (cp - 0xD800) * 0x400 + (lo_cp - 0xDC00)
          next_i = next_i + 6
        else
          cp = 0xFFFD                                         -- a lone surrogate: the replacement character
        end
      elseif cp >= 0xDC00 and cp <= 0xDFFF then
        cp = 0xFFFD
      end
      parts[#parts + 1] = utf8_char(cp)
      i = next_i
    elseif ESCAPES[e] then
      parts[#parts + 1] = ESCAPES[e]
      i = j + 2
    else
      decode_error(text, j, "bad escape")
    end
  end
end

local function decode_number(text, pos)
  -- JSON grammar: -?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?
  local i = pos
  if text:sub(i, i) == "-" then i = i + 1 end
  local c = text:sub(i, i)
  if c == "0" then
    i = i + 1
  elseif c:match("%d") then
    i = (text:find("[^%d]", i) or (#text + 1))
  else
    decode_error(text, pos, "bad number")
  end
  if text:sub(i, i) == "." then
    if not text:sub(i + 1, i + 1):match("%d") then decode_error(text, i, "bad number") end
    i = (text:find("[^%d]", i + 1) or (#text + 1))
  end
  local e = text:sub(i, i)
  if e == "e" or e == "E" then
    i = i + 1
    local s = text:sub(i, i)
    if s == "+" or s == "-" then i = i + 1 end
    if not text:sub(i, i):match("%d") then decode_error(text, i, "bad exponent") end
    i = (text:find("[^%d]", i) or (#text + 1))
  end
  local n = tonumber(text:sub(pos, i - 1))
  if not n then decode_error(text, pos, "bad number") end
  return n, i
end

local function decode_array(text, pos, depth)
  local out = Json.array({})
  local i = skip_ws(text, pos + 1)
  if text:sub(i, i) == "]" then return out, i + 1 end
  while true do
    local v
    v, i = decode_value(text, i, depth + 1)
    out[#out + 1] = v
    i = skip_ws(text, i)
    local c = text:sub(i, i)
    if c == "]" then return out, i + 1 end
    if c ~= "," then decode_error(text, i, "expected , or ]") end
    i = skip_ws(text, i + 1)
  end
end

local function decode_object(text, pos, depth)
  local out = Json.object({})
  local i = skip_ws(text, pos + 1)
  if text:sub(i, i) == "}" then return out, i + 1 end
  while true do
    if text:sub(i, i) ~= '"' then decode_error(text, i, "expected a key string") end
    local key
    key, i = decode_string(text, i)
    i = skip_ws(text, i)
    if text:sub(i, i) ~= ":" then decode_error(text, i, "expected :") end
    local v
    v, i = decode_value(text, skip_ws(text, i + 1), depth + 1)
    out[key] = v                                              -- a repeated key: the last one wins (as in Python)
    i = skip_ws(text, i)
    local c = text:sub(i, i)
    if c == "}" then return out, i + 1 end
    if c ~= "," then decode_error(text, i, "expected , or }") end
    i = skip_ws(text, i + 1)
  end
end

decode_value = function(text, pos, depth)
  if depth > MAX_DEPTH then decode_error(text, pos, "nested too deep") end
  local c = text:sub(pos, pos)
  if c == "{" then return decode_object(text, pos, depth) end
  if c == "[" then return decode_array(text, pos, depth) end
  if c == '"' then return decode_string(text, pos) end
  if c == "-" or c:match("%d") then return decode_number(text, pos) end
  if text:sub(pos, pos + 3) == "true" then return true, pos + 4 end
  if text:sub(pos, pos + 4) == "false" then return false, pos + 5 end
  if text:sub(pos, pos + 3) == "null" then return Json.null, pos + 4 end
  if c == "" then decode_error(text, pos, "unexpected end of input") end
  decode_error(text, pos, "unexpected character " .. string.format("%q", c))
end

function Json.decode(text)
  if type(text) ~= "string" then error("json: expected a string, got " .. type(text), 0) end
  if text:sub(1, 3) == "\239\187\191" then text = text:sub(4) end   -- a UTF-8 BOM (Notepad writes one)
  local value, pos = decode_value(text, skip_ws(text, 1), 0)
  pos = skip_ws(text, pos)
  if pos <= #text then decode_error(text, pos, "trailing characters") end
  return value
end

function Json.try_decode(text)
  local ok, value = pcall(Json.decode, text)
  return ok, value
end

-- ---- Encoder -------------------------------------------------------------------
local function encode_string(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    local map = { ['"'] = '\\"', ["\\"] = "\\\\", ["\b"] = "\\b", ["\f"] = "\\f", ["\n"] = "\\n", ["\r"] = "\\r",
                  ["\t"] = "\\t" }
    return map[c] or string.format("\\u%04x", c:byte())
  end) .. '"'
end

-- The shortest text that reads back as exactly n (0.6 stays "0.6", not "0.59999999999999998").
function Json.number_text(n)
  if n ~= n or n == math.huge or n == -math.huge then error("json: cannot encode NaN or infinity", 0) end
  if n == math.floor(n) and math.abs(n) < INT_LIMIT then return string.format("%d", n) end
  for digits = 14, 17 do
    local s = string.format("%." .. digits .. "g", n)
    if tonumber(s) == n then return s end
  end
  return string.format("%.17g", n)
end

local function encode_value(v, indent, level, out)
  local kind = Json.kind(v)
  if kind == "null" then out[#out + 1] = "null"
  elseif kind == "boolean" then out[#out + 1] = v and "true" or "false"
  elseif kind == "number" then out[#out + 1] = Json.number_text(v)
  elseif kind == "string" then out[#out + 1] = encode_string(v)
  elseif kind == "array" or kind == "object" then
    if level > MAX_DEPTH then error("json: nested too deep (a cycle?)", 0) end
    local open, close = "[", "]"
    if kind == "object" then open, close = "{", "}" end
    local items = {}
    if kind == "array" then
      for i = 1, #v do items[#items + 1] = { nil, v[i] } end
    else
      for _, k in ipairs(Json.sorted_keys(v)) do items[#items + 1] = { tostring(k), v[k] } end
    end
    if #items == 0 then out[#out + 1] = open .. close; return end
    local pad = indent and ("\n" .. string.rep(" ", indent * (level + 1))) or ""
    local sep = indent and ": " or ":"
    out[#out + 1] = open
    for i, item in ipairs(items) do
      out[#out + 1] = pad
      if item[1] then out[#out + 1] = encode_string(item[1]) .. sep end
      encode_value(item[2], indent, level + 1, out)
      if i < #items then out[#out + 1] = "," end
    end
    out[#out + 1] = (indent and ("\n" .. string.rep(" ", indent * level)) or "") .. close
  else
    error("json: cannot encode a " .. type(v), 0)
  end
end

-- options.indent: spaces per level (nil = one compact line)
function Json.encode(v, options)
  local out = {}
  encode_value(v, options and options.indent, 0, out)
  return table.concat(out)
end

return Json

-- {{FOOTER}}
