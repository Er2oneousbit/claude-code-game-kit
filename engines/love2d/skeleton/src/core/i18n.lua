-- ---------------------------------------------------------------------------
-- i18n.lua
-- Purpose : Localization: string tables per locale with a fallback chain (fr-CA -> fr -> en), {name}
--           placeholders, CLDR plurals, clean-language variants with a word mask, and the pseudo-locale that
--           makes untranslated, clipped and too-tight text visible. Matches data/golden/shell.json "tr",
--           "plural", "plural_rules", "tr_clean", "mask_words", "mature_words" and "pseudo".
-- Usage   : local I18n = require("src.core.i18n")
--           local i18n = I18n.new(tables, "fr")         -- tables: locale -> { key -> text } (data/i18n/*.json)
--           i18n:t("menu.play")  i18n:t("greet", { name = "Ana" })  i18n:tp("apples", 3)
--           i18n.clean = true ; i18n.mature = { en = {...} }   -- content.clean_language and the word lists
--           pure parts: I18n.tr(tables, locale, key, args, clean, words), I18n.plural(locale, n),
--           I18n.pseudo(text), I18n.mask_words(text, words), I18n.mature_words(file_text_or_nil)
-- Notes   : No love.* calls. A missing key returns the key itself, so it shows on screen and in tests. Locale
--           "pseudo" shows the English text through pseudo(): accented look-alikes, 40 % longer, in brackets;
--           a string that is not in brackets on a pseudo run did not go through t(). Lua 5.1 has no utf8
--           library: LÖVE's require("utf8") is used when present, else lead bytes are counted. The word mask
--           decodes UTF-8 itself (code points, the reference's pinned ranges and fold), so it runs the same
--           under plain Lua and LuaJIT. Plural rules are CLDR 46's for whole numbers
--           (tools/golden_vectors.py PLURAL_FAMILIES).
--
-- Pseudocode (pseudo):
--   walk the text: {name}, %s %d %i %f %% pass through and are not counted; every other character becomes its
--   accented look-alike and counts; result = "[" .. text .. "~" x ceil(count * 0.40) .. "]"
-- Pseudocode (clean): per locale of the chain, key@clean (clean on) then key; fill; clean -> mask_words
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plural rules, the .other fallback per
--           locale, @clean variants, mask_words and mature_words, i18n.clean and i18n.mature (#207, #87)
-- Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): compile_words and mask_word_set; the translator folds
--           the chain's words once per locale and list (assign a new i18n.mature table to change the lists), not
--           on every t()
-- ---------------------------------------------------------------------------
local I18n = {}
I18n.__index = I18n

-- ---- Tunables ----------------------------------------------------------------
I18n.FALLBACK = "en"
I18n.PSEUDO_LOCALE = "pseudo"
I18n.PSEUDO_GROWTH = 0.40                -- translated English runs about 40 % longer (SOP-19)
I18n.CLEAN_SUFFIX = "@clean"             -- "guard.insult@clean": the line with the clean-language setting on
I18n.GRAWLIX = "#@$%"                    -- the mask: one character per code point, again for each word
local PSEUDO = { a = "á", e = "é", i = "í", o = "ó", u = "ú", c = "ç", n = "ñ", y = "ý",
                 A = "Á", E = "É", I = "Í", O = "Ó", U = "Ú", C = "Ç", N = "Ñ", Y = "Ý" }
local PRINTF = { s = true, d = true, i = true, f = true, ["%"] = true }
-- CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES)
local PLURAL_LANGUAGES = {
  other = "ja zh ko vi th id ms lo my km yo ig jv su",
  one = "en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr",
  zero_one = "hi bn fa gu kn hy", one_many = "es it ca", zero_one_many = "fr pt", one_21 = "is mk",
  fil = "fil tl", east_slavic = "ru uk be", pl = "pl", cs = "cs sk", lt = "lt", balkan = "hr sr bs",
  ro = "ro mo", lv = "lv", he = "he", sl = "sl", ga = "ga", ar = "ar", cy = "cy",
}
local PLURAL_LOCALE_FAMILIES = { ["pt-pt"] = "one_many" }   -- a region with its own rule
local MILLION = 1000000
-- code point ranges that are never part of a word (the reference's MASK_BOUNDARY_RANGES)
local MASK_BOUNDARY_RANGES = {
  { 0x0080, 0x00BF }, { 0x00D7, 0x00D7 }, { 0x00F7, 0x00F7 }, { 0x2000, 0x2BFF }, { 0x2E00, 0x2E7F },
  { 0x3000, 0x303F }, { 0xFE00, 0xFE0F }, { 0xFE10, 0xFE1F }, { 0xFE30, 0xFE6F }, { 0xFEFF, 0xFEFF },
  { 0xFF00, 0xFF0F }, { 0xFF1A, 0xFF20 }, { 0xFF3B, 0xFF40 }, { 0xFF5B, 0xFF65 }, { 0x1F000, 0x1FAFF },
}

local FAMILY_OF = {}
for fam, langs in pairs(PLURAL_LANGUAGES) do
  for lang in langs:gmatch("%S+") do FAMILY_OF[lang] = fam end
end

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

-- one table's text for key: its @clean variant first when clean is on, else key; nil when neither
local function pick(t, key, clean)
  if not t then return nil end
  if clean and t[key .. I18n.CLEAN_SUFFIX] ~= nil then return t[key .. I18n.CLEAN_SUFFIX] end
  return t[key]
end

-- the raw text for key through the chain (per locale: @clean first when clean is on), or nil
function I18n.lookup(tables, locale, key, clean)
  for _, loc in ipairs(I18n.locale_chain(locale)) do
    local text = pick(tables[loc], key, clean)
    if text ~= nil then return text end
  end
  return nil
end

function I18n.finish(text, args, clean, words)
  local out = I18n.fill(text, args or {})
  if not clean or not words then return out end
  if words.is_word_set then return I18n.mask_word_set(out, words) end   -- compiled already (the translator's cache)
  if #words > 0 then return I18n.mask_words(out, words) end
  return out
end

function I18n.tr(tables, locale, key, args, clean, words)
  local text = I18n.lookup(tables, locale, key, clean)
  if text == nil then return key end
  return I18n.finish(text, args, clean, words)
end

-- The plural rule family: the full locale (pt-PT) first, then its language, then English's rule.
function I18n.plural_family(locale)
  local norm = locale:gsub("_", "-"):lower()
  for name, fam in pairs(PLURAL_LOCALE_FAMILIES) do
    if norm == name or norm:sub(1, #name + 1) == name .. "-" then return fam end
  end
  return FAMILY_OF[norm:match("^[^-]*")] or "one"
end

-- The CLDR plural category of a whole number (a negative one counts as its absolute value).
function I18n.plural(locale, count)
  local fam = I18n.plural_family(locale)
  local n = math.floor(math.abs(count))
  local m10, m100 = n % 10, n % 100
  if fam == "other" then return "other" end
  if fam == "one" then return n == 1 and "one" or "other" end
  if fam == "zero_one" then return n <= 1 and "one" or "other" end
  if fam == "one_many" or fam == "zero_one_many" then
    if n == 1 or (n == 0 and fam == "zero_one_many") then return "one" end
    if n ~= 0 and n % MILLION == 0 then return "many" end
    return "other"
  end
  if fam == "one_21" then return (m10 == 1 and m100 ~= 11) and "one" or "other" end
  if fam == "fil" then
    if m10 == 4 or m10 == 6 or m10 == 9 then return "other" end
    return "one"
  end
  if fam == "east_slavic" or fam == "balkan" then
    if m10 == 1 and m100 ~= 11 then return "one" end
    if m10 >= 2 and m10 <= 4 and not (m100 >= 12 and m100 <= 14) then return "few" end
    return fam == "east_slavic" and "many" or "other"
  end
  if fam == "pl" then
    if n == 1 then return "one" end
    if m10 >= 2 and m10 <= 4 and not (m100 >= 12 and m100 <= 14) then return "few" end
    return "many"
  end
  if fam == "cs" then
    if n == 1 then return "one" end
    return (n >= 2 and n <= 4) and "few" or "other"
  end
  if fam == "lt" then
    if m100 >= 11 and m100 <= 19 then return "other" end
    if m10 == 1 then return "one" end
    return m10 >= 2 and "few" or "other"
  end
  if fam == "ro" then
    if n == 1 then return "one" end
    return (n == 0 or (m100 >= 1 and m100 <= 19)) and "few" or "other"
  end
  if fam == "lv" then
    if m10 == 0 or (m100 >= 11 and m100 <= 19) then return "zero" end
    return m10 == 1 and "one" or "other"
  end
  if fam == "he" then
    if n == 1 then return "one" end
    return n == 2 and "two" or "other"
  end
  if fam == "sl" then
    if m100 == 1 then return "one" end
    if m100 == 2 then return "two" end
    return (m100 == 3 or m100 == 4) and "few" or "other"
  end
  if fam == "ga" then
    if n == 1 then return "one" end
    if n == 2 then return "two" end
    if n >= 3 and n <= 6 then return "few" end
    return (n >= 7 and n <= 10) and "many" or "other"
  end
  if fam == "ar" then
    if n <= 2 then return ({ [0] = "zero", "one", "two" })[n] end
    if m100 >= 3 and m100 <= 10 then return "few" end
    return m100 >= 11 and "many" or "other"
  end
  if fam == "cy" then
    return ({ [0] = "zero", [1] = "one", [2] = "two", [3] = "few", [6] = "many" })[n] or "other"
  end
  error("unknown plural family " .. tostring(fam))
end

-- key.<category> through the chain, each locale with its own category, then that locale's key.other
function I18n.lookup_plural(tables, locale, key, n, clean)
  for _, loc in ipairs(I18n.locale_chain(locale)) do
    local cat = I18n.plural(loc, n)
    local text = pick(tables[loc], key .. "." .. cat, clean)
    if text == nil and cat ~= "other" then text = pick(tables[loc], key .. ".other", clean) end
    if text ~= nil then return text end
  end
  return nil
end

function I18n.tr_plural(tables, locale, key, n, args, clean, words)
  local a = {}
  for k, v in pairs(args or {}) do a[k] = v end
  a.n = n
  local text = I18n.lookup_plural(tables, locale, key, n, clean)
  if text == nil then return key .. "." .. I18n.plural(locale, n) end
  return I18n.finish(text, a, clean, words)
end

-- ---- the word mask (#207) ------------------------------------------------------------------------------
-- (code point, bytes it takes) of the UTF-8 character at byte i; a stray byte counts as itself
local function decode(text, i)
  local b = text:byte(i)
  local len, cp = 1, b
  if b >= 0xF0 then len, cp = 4, b - 0xF0
  elseif b >= 0xE0 then len, cp = 3, b - 0xE0
  elseif b >= 0xC0 then len, cp = 2, b - 0xC0 end
  for k = 1, len - 1 do
    local c = text:byte(i + k)
    if not c then return b, 1 end
    cp = cp * 64 + (c - 0x80)
  end
  return cp, len
end

function I18n.is_word_char(cp)
  if cp < 0x80 then
    return (cp >= 0x30 and cp <= 0x39) or (cp >= 0x41 and cp <= 0x5A) or (cp >= 0x61 and cp <= 0x7A)
  end
  for _, r in ipairs(MASK_BOUNDARY_RANGES) do
    if cp >= r[1] and cp <= r[2] then return false end
  end
  return true
end

-- the pinned case fold (the reference's fold_char): one code point to one code point
function I18n.fold_char(cp)
  if (cp >= 0x41 and cp <= 0x5A) or (cp >= 0xC0 and cp <= 0xDE and cp ~= 0xD7) then return cp + 0x20 end
  if cp == 0x130 then return 0x69 end
  if cp == 0x178 then return 0xFF end
  if ((cp >= 0x100 and cp <= 0x12F) or (cp >= 0x132 and cp <= 0x137) or (cp >= 0x14A and cp <= 0x177))
      and cp % 2 == 0 then return cp + 1 end
  if ((cp >= 0x139 and cp <= 0x148) or (cp >= 0x179 and cp <= 0x17E)) and cp % 2 == 1 then return cp + 1 end
  if cp >= 0x391 and cp <= 0x3AB and cp ~= 0x3A2 then return cp + 0x20 end
  if cp == 0x386 then return 0x3AC end
  if cp >= 0x388 and cp <= 0x38A then return cp + 0x25 end
  if cp == 0x38C then return 0x3CC end
  if cp == 0x38E or cp == 0x38F then return cp + 0x3F end
  if cp == 0x3C2 then return 0x3C3 end
  if cp >= 0x400 and cp <= 0x40F then return cp + 0x50 end
  if cp >= 0x410 and cp <= 0x42F then return cp + 0x20 end
  return cp
end

-- the words of text as { from, to (bytes), key (folded code points), count (code points) } plus the gaps
local function scan(text)
  local parts, i, n = {}, 1, #text
  while i <= n do
    local cp, len = decode(text, i)
    if not I18n.is_word_char(cp) then
      parts[#parts + 1] = { from = i, to = i + len - 1 }
      i = i + len
    else
      local from, keys = i, {}
      while i <= n do
        cp, len = decode(text, i)
        if not I18n.is_word_char(cp) then break end
        keys[#keys + 1] = tostring(I18n.fold_char(cp))
        i = i + len
      end
      parts[#parts + 1] = { from = from, to = i - 1, key = table.concat(keys, ","), count = #keys }
    end
  end
  return parts
end

-- The folded set the mask matches against ({ is_word_set = true, keys = {...}, any = bool }): build it once per
-- word list (t() runs for every label every frame)
function I18n.compile_words(words)
  local set = { is_word_set = true, keys = {}, any = false }
  for _, w in ipairs(words or {}) do
    local parts = scan(w)
    if #parts == 1 and parts[1].key then
      set.keys[parts[1].key] = true
      set.any = true
    end
  end
  return set
end

-- text with every whole word that is in words (case folded) replaced by a same-length grawlix
function I18n.mask_words(text, words)
  return I18n.mask_word_set(text, I18n.compile_words(words))
end

-- mask_words with the list compiled already (compile_words)
function I18n.mask_word_set(text, set)
  if not set.any then return text end
  local wanted = set.keys
  local out, g = {}, I18n.GRAWLIX
  for _, p in ipairs(scan(text)) do
    if p.key and wanted[p.key] then
      for k = 0, p.count - 1 do
        local j = k % #g + 1
        out[#out + 1] = g:sub(j, j)
      end
    else
      out[#out + 1] = text:sub(p.from, p.to)
    end
  end
  return table.concat(out)
end

-- A word list file's words ({"words": [...]}, strings only); anything else (or nil, no file) is no words.
-- decode: a JSON decoder returning ok, data (src.core.json's try_decode; passed in so this file stays pure).
function I18n.mature_words(text, decode_json)
  if type(text) ~= "string" then return {} end
  local ok, data = decode_json(text)
  if not ok or type(data) ~= "table" or type(data.words) ~= "table" then return {} end
  local out = {}
  for _, w in ipairs(data.words) do
    if type(w) == "string" then out[#out + 1] = w end
  end
  return out
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
-- clean: content.clean_language; mature: locale -> words (data/i18n/mature/<locale>.json)
function I18n.new(tables, locale)
  return setmetatable({ tables = tables or {}, locale = locale or I18n.FALLBACK, clean = false, mature = {} }, I18n)
end

function I18n:set_locale(locale) self.locale = locale end
function I18n:is_pseudo() return self.locale == I18n.PSEUDO_LOCALE end

-- true when key has a text in the current chain (pseudo: in English)
function I18n:has(key)
  local loc = self:is_pseudo() and I18n.FALLBACK or self.locale
  return I18n.lookup(self.tables, loc, key) ~= nil
end

-- the word lists of every locale in the current chain (a fallback line can come from any of them)
function I18n:words()
  local out = {}
  for _, loc in ipairs(I18n.locale_chain(self:is_pseudo() and I18n.FALLBACK or self.locale)) do
    for _, w in ipairs(self.mature[loc] or {}) do out[#out + 1] = w end
  end
  return out
end

-- the chain's words folded once: rebuilt when the locale changes or i18n.mature is a new table
function I18n:word_set()
  local c = self._word_cache
  if not c or c.locale ~= self.locale or c.mature ~= self.mature then
    c = { locale = self.locale, mature = self.mature, set = I18n.compile_words(self:words()) }
    self._word_cache = c
  end
  return c.set
end

function I18n:t(key, args)
  if self:is_pseudo() then
    local text = I18n.lookup(self.tables, I18n.FALLBACK, key, self.clean)
    if text == nil then return key end                     -- unbracketed on purpose: the check flags it
    return I18n.fill(I18n.pseudo(text), args or {})
  end
  return I18n.tr(self.tables, self.locale, key, args, self.clean, self.clean and self:word_set() or nil)
end

function I18n:tp(key, n, args)
  if not self:is_pseudo() then
    return I18n.tr_plural(self.tables, self.locale, key, n, args, self.clean, self.clean and self:word_set() or nil)
  end
  local a = {}
  for k, v in pairs(args or {}) do a[k] = v end
  a.n = n
  local text = I18n.lookup_plural(self.tables, I18n.FALLBACK, key, n, self.clean)
  if text == nil then return key .. "." .. I18n.plural(I18n.FALLBACK, n) end
  return I18n.fill(I18n.pseudo(text), a)
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
