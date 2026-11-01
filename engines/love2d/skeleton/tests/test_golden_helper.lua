-- ---------------------------------------------------------------------------
-- test_golden_helper.lua
-- Purpose : Tests the golden-vector comparison itself (tests/helpers/golden.lua), so a lenient comparer cannot
--           make the vector tests pass by accident, and an unknown case type fails.
-- Usage   : python tools/dev.py test     (or --filter golden_helper)
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local Json = require("src.core.json")
local Golden = require("tests.helpers.golden")
local T = {}

function T.test_numbers_within_tolerance()
  A.eq(Golden.diff(0, 0.0, 1e-6), nil, "int 0 equals 0.0")
  A.eq(Golden.diff(1.0000001, 1, 1e-6), nil)
  A.truthy(Golden.diff(1.01, 1, 1e-6))
  A.truthy(Golden.diff("1", 1, 1e-6), "a string is not a number")
end

function T.test_arrays_in_order_objects_as_key_sets()
  A.truthy(Golden.diff(Json.array({ 2, 1 }), Json.decode("[1, 2]"), 0), "order matters")
  A.truthy(Golden.diff(Json.array({ 1 }), Json.decode("[1, 2]"), 0), "length matters")
  A.truthy(Golden.diff({ a = 1 }, Json.decode('{"a": 1, "b": 2}'), 0), "a missing key")
  A.truthy(Golden.diff({ a = 1, c = 3 }, Json.decode('{"a": 1}'), 0), "an extra key")
  A.eq(Golden.diff({ b = 2, a = 1 }, Json.decode('{"a": 1, "b": 2}'), 0), nil)
  A.eq(Golden.diff({}, Json.decode("[]"), 0), nil, "an empty Lua table matches []")
  A.truthy(Golden.diff(true, Json.decode("false"), 0))
end

function T.test_null_equals_missing()
  A.eq(Golden.diff(nil, Json.null, 0), nil)
  A.truthy(Golden.diff({}, Json.null, 0))
end

function T.test_unknown_case_type_fails()
  local suite = Golden.suite({ tolerance = 0, cases = { { type = "brand_new", name = "x" } } }, {}, "fake.json")
  local ok = 0
  for name, fn in pairs(suite) do
    if name:find("brand_new", 1, true) then
      A.raises(fn, "a case type without a handler must fail")
      ok = ok + 1
    end
  end
  A.eq(ok, 1)
end

return T

-- {{FOOTER}}
