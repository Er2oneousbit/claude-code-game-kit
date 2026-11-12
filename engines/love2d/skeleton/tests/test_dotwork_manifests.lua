-- ---------------------------------------------------------------------------
-- test_dotwork_manifests.lua
-- Purpose : Every real Dotwork asset manifest of the game (assets/dotwork/*.assets.json) loads, and every file it
--           names ships at the size it says: the LÖVE stand-in for Dotwork's Godot `verify`. A game with no
--           manifests passes and says so.
-- Usage   : python tools/dev.py test     (or --filter dotwork)
-- Notes   : Fails on a manifest that does not parse, another major version, a missing or mis-sized PNG, a rect
--           outside its image, or a broken reference (a map's tileset, a portrait's animation, a tile a map names).
--           Warnings (an unknown kind or layer kind, a terrain key no tile answers to, an unknown field) are
--           printed, not failed.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- Updated : 2026-11-11 with Claude (Fable 5.1, claude-fable-5-1): spec 1.1.0 (#285): every kind loads now, so the
--           warnings named here are the ones left.
-- ---------------------------------------------------------------------------
local Loader = require("src.game.dotwork_loader")

local T = {}

function T.test_every_game_manifest_loads()
  local paths = Loader.find()
  local bad = {}
  for _, path in ipairs(paths) do
    local ok, model = pcall(Loader.load, path)
    if not ok then
      bad[#bad + 1] = tostring(model)
    else
      for _, p in ipairs(Loader.verify(model)) do bad[#bad + 1] = p end
      for _, w in ipairs(model.warnings) do print("WARN " .. w) end
    end
  end
  if #paths == 0 then
    print("DOTWORK no manifests in " .. Loader.DIR .. " (nothing to check)")
  else
    print(string.format("DOTWORK %d manifest(s) checked in %s, %d problem(s)", #paths, Loader.DIR, #bad))
  end
  if #bad > 0 then error(#bad .. " problem(s):\n  " .. table.concat(bad, "\n  "), 0) end
end

return T

-- {{FOOTER}}
