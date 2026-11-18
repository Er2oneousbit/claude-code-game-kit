-- ---------------------------------------------------------------------------
-- test_i18n_tables.lua
-- Purpose : The game's string tables (data/i18n/*.json): every key the shell's code asks for exists in en.json,
--           other languages only use English keys (they may be partial: missing keys fall back to English), every
--           English string survives the pseudo-locale, and code points are counted, not bytes.
-- Usage   : python tools/dev.py test     (or --filter i18n)
-- Notes   : The key scan finds literal keys in calls like app:t("menu.play"); keys built at runtime
--           ("settings." .. section .. "." .. name) are covered by the pseudo smoke run instead.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): the translator the shell uses honours clean language
--           in t, tp and the pseudo-locale, and the shipped word list loads apart from the tables (#207)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local I18n = require("src.core.i18n")
local T = {}

local DIR = "data/i18n/"
local SCAN = { "src/shell", "src/game" }

local function table_of(loc)
  return Json.decode(assert(love.filesystem.read(DIR .. loc .. ".json"), loc .. ".json missing"))
end

local function lua_files(dir, out)
  for _, item in ipairs(love.filesystem.getDirectoryItems(dir)) do
    local path = dir .. "/" .. item
    if love.filesystem.getInfo(path, "directory") then lua_files(path, out)
    elseif item:match("%.lua$") then out[#out + 1] = path end
  end
  return out
end

function T.test_every_literal_key_is_in_english()
  local en = table_of("en")
  local missing = {}
  for _, root in ipairs(SCAN) do
    for _, file in ipairs(lua_files(root, {})) do
      local src = love.filesystem.read(file)
      for kind, key in src:gmatch(":t([pv]?)%(%s*\"([%w_%.]+)\"") do
        if kind == "p" then key = key .. ".other" end         -- tp("apples", n) reads apples.one / apples.other
        -- "settings.tab." .. tab is a prefix (built at runtime), not a key
        if key:sub(-1) ~= "." and en[key] == nil then missing[#missing + 1] = file .. ": " .. key end
      end
    end
  end
  A.eq(#missing, 0, "keys missing from en.json: " .. table.concat(missing, ", "))
end

function T.test_other_languages_use_english_keys()
  local en = table_of("en")
  for _, file in ipairs(love.filesystem.getDirectoryItems(DIR)) do
    local loc = file:match("^(.+)%.json$")
    if loc and loc ~= "en" then
      for key in pairs(table_of(loc)) do
        A.truthy(en[key] ~= nil, loc .. ".json has a key English lacks: " .. key)
      end
    end
  end
end

function T.test_french_falls_back_to_english()
  -- the shipped fr.json is complete (#270), so a partial table stands in for a translation in progress
  local tables = { en = table_of("en"), fr = { ["menu.play"] = table_of("fr")["menu.play"] } }
  local i18n = I18n.new(tables, "fr")
  A.eq(i18n:t("menu.play"), tables.fr["menu.play"])
  A.eq(i18n:t("menu.juice"), tables.en["menu.juice"], "a key fr lacks shows the English text")
  A.eq(i18n:t("no.such.key"), "no.such.key")
end

function T.test_every_english_string_survives_pseudo()
  local en = table_of("en")
  local i18n = I18n.new({ en = en }, "pseudo")
  for key, text in pairs(en) do
    local p = i18n:t(key, {})
    A.eq(p:sub(1, 1), "[", key)
    A.eq(p:sub(-1), "]", key)
    A.truthy(I18n.length(p) >= I18n.length(text), key)
  end
end

function T.test_the_shell_translator_honours_clean_language()
  local words = I18n.mature_words(love.filesystem.read(DIR .. "mature/en.json"), Json.try_decode)
  A.eq(#words, 0, "the kit's word list ships empty")
  local i18n = I18n.new({
    en = { bye = "Damn, bye {name}.", ["bye@clean"] = "Bye {name}.", ["hits.one"] = "{n} damn hit",
           ["hits.one@clean"] = "{n} hit", ["hits.other"] = "{n} hits" },
    fr = { bye = "Merde, salut {name}." } }, "fr")
  i18n.mature = { fr = { "merde" }, en = { "damn" } }
  A.eq(i18n:t("bye", { name = "Ana" }), "Merde, salut Ana.", "off: as written")
  i18n.clean = true
  A.eq(i18n:t("bye", { name = "Damn" }), "#@$%#, salut #@$%.", "fr stays fr; masked with both lists")
  i18n:set_locale("en")
  A.eq(i18n:t("bye", { name = "Ana" }), "Bye Ana.")
  A.eq(i18n:tp("hits", 1), "1 hit")
  i18n:set_locale("pseudo")
  A.eq(i18n:t("bye", { name = "Ana" }), "[Býé Ana.~~]")
end

function T.test_code_points_not_bytes()
  A.eq(I18n.length("Í”é"), 3)
  A.eq(I18n.pseudo("Í"), "[Í~]", "a 2-byte character counts once")
end

return T

-- {{FOOTER}}
