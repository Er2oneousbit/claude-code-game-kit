-- ---------------------------------------------------------------------------
-- test_json.lua
-- Purpose : Unit tests for src/core/json.lua: decoding, encoding, array vs object kinds, null, escapes, errors.
-- Usage   : python tools/dev.py test     (or --filter json)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local T = {}

function T.test_decodes_values()
  local v = Json.decode('{"a": [1, 2.5, -3e2], "b": true, "c": false, "d": null, "e": "x"}')
  A.eq(v.a[1], 1); A.eq(v.a[2], 2.5); A.eq(v.a[3], -300)
  A.eq(v.b, true); A.eq(v.c, false); A.eq(v.d, Json.null); A.eq(v.e, "x")
end

function T.test_empty_array_and_object_keep_their_kind()
  local v = Json.decode('{"list": [], "map": {}}')
  A.eq(Json.kind(v.list), "array")
  A.eq(Json.kind(v.map), "object")
  A.eq(Json.encode(v), '{"list":[],"map":{}}')
end

function T.test_plain_tables()
  A.eq(Json.kind({ 1, 2 }), "array")
  A.eq(Json.kind({ a = 1 }), "object")
  A.eq(Json.kind({}), "object", "an empty plain table is an object")
  A.eq(Json.encode(Json.array({})), "[]")
end

function T.test_string_escapes_and_unicode()
  local v = Json.decode('"a\\"b\\\\c\\n\\u00e9\\ud83d\\ude00"')
  A.eq(v, 'a"b\\c\n\195\169\240\159\152\128')
  A.eq(Json.decode(Json.encode("tab\there \"q\" \1")), "tab\there \"q\" \1")
  A.eq(Json.decode('"Í ”"'), "Í ”", "UTF-8 passes through")
end

function T.test_numbers_round_trip_shortest()
  A.eq(Json.encode(0.6), "0.6")
  A.eq(Json.encode(1920), "1920")
  A.eq(Json.encode(-0.25), "-0.25")
  A.eq(Json.decode(Json.encode(0.1 + 0.2)), 0.1 + 0.2)
  A.raises(function() Json.encode(0 / 0) end)
end

function T.test_sorted_keys_and_indent()
  A.eq(Json.encode({ b = 1, a = { 2 } }, { indent = 1 }), '{\n "a": [\n  2\n ],\n "b": 1\n}')
end

function T.test_bad_json_raises_with_position()
  for _, bad in ipairs({ "", "{", "[1,]", "{volume: loud", "01", "1.", "tru", '"\n"', "[1] x", "{\"a\" 1}" }) do
    local ok, err = Json.try_decode(bad)
    A.falsy(ok, "should fail: " .. bad)
    A.truthy(tostring(err):find("json:"), "message names json: " .. tostring(err))
  end
end

function T.test_bom_is_skipped()
  A.eq(Json.decode("\239\187\191[1]")[1], 1)
end

function T.test_copy_keeps_marks()
  local v = Json.copy(Json.decode('{"x": []}'))
  A.eq(Json.kind(v.x), "array")
end

return T

-- {{FOOTER}}
