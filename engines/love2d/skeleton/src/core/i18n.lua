-- ---------------------------------------------------------------------------
-- i18n.lua
-- Purpose : Localization: string tables per locale with a fallback chain (fr-CA -> fr -> en), {name}
--           placeholders, one/other plurals, and the pseudo-locale that makes untranslated, clipped and
--           too-tight text visible. Matches data/golden/shell.json "tr", "plural", "pseudo".
-- Usage   : local I18n = require("src.core.i18n")
--           local i18n = I18n.new(tables, "fr")         -- tables: locale -> { key -> text } (data/i18n/*.json)
--           i18n:t("menu.play")  i18n:t("greet", { name = "Ana" })  i18n:tp("apples", 3)
--           pure parts: I18n.tr(tables, locale, key, args), I18n.plural(locale, n), I18n.pseudo(text)
-- Notes   : No love.* calls. A missing key returns the key itself, so it shows on screen and in tests. Locale
--           "pseudo" shows the English text through pseudo(): accented look-alikes, 40 % longer, in brackets;
--           a string that is not in brackets on a pseudo run did not go through t(). Lua 5.1 has no utf8
--           library: LÖVE's require("utf8") is used when present, else lead bytes are counted.
--
-- Pseudocode (pseudo):
--   walk the text: {name}, %s %d %i %f %% pass through and are not counted; every other character becomes its
--   accented look-alike and counts; result = "[" .. text .. "~" x ceil(count * 0.40) .. "]"
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local I18n = {}
I18n.__index = I18n

-- ---- Tunables ----------------------------------------------------------------
I18n.FALLBACK = "en"
I18n.PSEUDO_LOCALE = "pseudo"
I18n.PSEUDO_GROWTH = 0.40                -- translated English runs about 40 % longer (SOP-19)
local PSEUDO = { a = "á", e = "é", i = "í", o = "ó", u = "ú", c = "ç", n = "ñ", y = "ý",
                 A = "Á", E = "É", I = "Í", O = "Ó", U = "Ú", C = "Ç", N = "Ñ", Y = "Ý" }
local PRINTF = { s = true, d = true, i = true, f = true, ["%"] = true }

local function base_of(locale)
  return (locale:match("^[^-]*") or locale):match("^[^_]*") or locale
end

function I18n.locale_chain(locale, fallback)
  fallback = fallback or I18n.FALLBACK
  local chain, seen = {}, {}
  for _, loc in ipairs({ locale, base_of(locale), fallback }) do
    if loc ~= "" and not seen[loc] then
      seen[loc] = true
      chain[#chain + 1] = loc
    end
  end
  return chain
end

local function show(v)
  if type(v) == "number" and v == math.floor(v) and math.abs(v) < 2 ^ 53 then return string.format("%d", v) end
  return tostring(v)
end

-- {name} -> args.name; braces without a matching argument stay as they are
function I18n.fill(text, args)
  if not args or not text:find("{", 1, true) then return text end
  local out, i, n = {}, 1, #text
  while i <= n do
    local c = text:sub(i, i)
    if c == "{" then
      local j = text:find("}", i + 1, true)
      if j then
        local name = text:sub(i + 1, j - 1)
        if args[name] ~= nil then
          out[#out + 1] = show(args[name])
          i = j + 1
        else
          out[#out + 1] = c
          i = i + 1
        end
      else
        out[#out + 1] = c
        i = i + 1
      end
    else
      out[#out + 1] = c
      i = i + 1
    end
  end
  return table.concat(out)
end

-- the raw text for key through the chain, or nil
function I18n.lookup(tables, locale, key)
  for _, loc in ipairs(I18n.locale_chain(locale)) do
    local t = tables[loc]
    if t and t[key] ~= nil then return t[key] end
  end
  return nil
end

function I18n.tr(tables, locale, key, args)
  local text = I18n.lookup(tables, locale, key)
  if text == nil then return key end
  return I18n.fill(text, args or {})
end

function I18n.plural(locale, n)
  local base = base_of(locale)
  if base == "ja" or base == "zh" or base == "ko" then return "other" end
  if base == "fr" then
    if n == 0 or n == 1 then return "one" end
    return "other"
  end
  if n == 1 then return "one" end
  return "other"
end

function I18n.tr_plural(tables, locale, key, n, args)
  local a = {}
  for k, v in pairs(args or {}) do a[k] = v end
  a.n = n
  return I18n.tr(tables, locale, key .. "." .. I18n.plural(locale, n), a)
end

-- bytes of the UTF-8 character starting at byte i
local function char_len(text, i)
  local b = text:byte(i)
  if b >= 0xF0 then return 4 end
  if b >= 0xE0 then return 3 end
  if b >= 0xC0 then return 2 end
  return 1
end

function I18n.pseudo(text)
  local out, visible, i, n = {}, 0, 1, #text
  while i <= n do
    local c = text:sub(i, i)
    local handled = false
    if c == "{" then
      local j = text:find("}", i + 1, true)
      if j then
        out[#out + 1] = text:sub(i, j)
        i = j + 1
        handled = true
      end
    end
    if not handled and c == "%" and i < n and PRINTF[text:sub(i + 1, i + 1)] then
      out[#out + 1] = text:sub(i, i + 1)
      i = i + 2
      handled = true
    end
    if not handled then
      local len = char_len(text, i)
      local ch = text:sub(i, i + len - 1)
      out[#out + 1] = PSEUDO[ch] or ch
      visible = visible + 1
      i = i + len
    end
  end
  return "[" .. table.concat(out) .. string.rep("~", math.ceil(visible * I18n.PSEUDO_GROWTH)) .. "]"
end

-- Code points in a UTF-8 string (LÖVE's utf8 when there, else lead bytes).
function I18n.length(text)
  local ok, utf8 = pcall(require, "utf8")
  if ok and utf8 and utf8.len then
    local n = utf8.len(text)
    if n then return n end
  end
  local _, count = text:gsub("[^\128-\191]", "")
  return count
end

-- ---- The game's translator ---------------------------------------------------------------------------
function I18n.new(tables, locale)
  return setmetatable({ tables = tables or {}, locale = locale or I18n.FALLBACK }, I18n)
end

function I18n:set_locale(locale) self.locale = locale end
function I18n:is_pseudo() return self.locale == I18n.PSEUDO_LOCALE end

-- true when key has a text in the current chain (pseudo: in English)
function I18n:has(key)
  local loc = self:is_pseudo() and I18n.FALLBACK or self.locale
  return I18n.lookup(self.tables, loc, key) ~= nil
end

function I18n:t(key, args)
  if self:is_pseudo() then
    local text = I18n.lookup(self.tables, I18n.FALLBACK, key)
    if text == nil then return key end                     -- unbracketed on purpose: the check flags it
    return I18n.fill(I18n.pseudo(text), args or {})
  end
  return I18n.tr(self.tables, self.locale, key, args)
end

function I18n:tp(key, n, args)
  local a = {}
  for k, v in pairs(args or {}) do a[k] = v end
  a.n = n
  local loc = self:is_pseudo() and I18n.FALLBACK or self.locale
  return self:t(key .. "." .. I18n.plural(loc, n), a)
end

-- Locales that have a table, sorted (for a language menu).
function I18n:locales()
  local out = {}
  for loc in pairs(self.tables) do out[#out + 1] = loc end
  table.sort(out)
  return out
end

return I18n

-- {{FOOTER}}
