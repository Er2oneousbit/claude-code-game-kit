-- ---------------------------------------------------------------------------
-- test_audio_wiring.lua
-- Purpose : The shell's use of the audio accessibility rules: the volume a source gets along its bus chain
--           (app:bus_volume, AudioAccess.chain_gain) and the arrow on a directional caption (subtitles.lua).
-- Usage   : python tools/dev.py test     (or --filter wiring)
-- Notes   : Fake app tables only (no window, no audio). The rules themselves are checked against the golden file
--           in test_access_golden.lua; this file checks how the shell puts them together.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
local A = require("tests.assert")
local AudioAccess = require("src.core.audio_access")
local Subtitles = require("src.shell.subtitles")
local App = require("src.shell.app")
local T = {}

local BUSES = { master = {}, sfx = { parent = "master" }, ambience = { parent = "sfx" }, music = {},
                stingers = { parent = "music" }, ui = { parent = "master" } }
local SLIDERS = { master = 0.9, music = 0.5, sfx = 0.25, ui = 0.75, voice = 0.6 }

function T.test_chain_gain_counts_each_slider_once()
  local g = AudioAccess.user_bus_gains(BUSES, SLIDERS)
  -- ambience under sfx: sfx once (0.25), not 0.25 * 0.25; master is the listener volume, so it is skipped
  A.near(AudioAccess.chain_gain(BUSES, g, "ambience", "master"), 0.25, 1e-12, "ambience")
  A.near(AudioAccess.chain_gain(BUSES, g, "ambience"), 0.25 * 0.9, 1e-12, "ambience with master")
  A.near(AudioAccess.chain_gain(BUSES, g, "stingers", "master"), 0.5, 1e-12, "stingers under music")
  A.near(AudioAccess.chain_gain(BUSES, g, "ui", "master"), 0.75, 1e-12, "ui")
  local cycle = { a = { parent = "b" }, b = { parent = "a" } }
  A.near(AudioAccess.chain_gain(cycle, AudioAccess.user_bus_gains(cycle, SLIDERS), "a"), 1, 1e-12, "a cycle ends")
end

function T.test_bus_volume_with_and_without_an_events_file()
  local settings = { audio = { master = 0.9, music = 0.5, sfx = 0.25, ui = 0.75, voice = 0.6 } }
  local plain = { settings = settings }
  A.eq(App.bus_volume(plain, "sfx"), 0.25, "no events file: the slider of the same name")
  A.eq(App.bus_volume(plain, "ambience"), 1, "no events file, no such slider: 1")
  local routed = { settings = settings, buses = BUSES, bus_gains = AudioAccess.user_bus_gains(BUSES, settings.audio) }
  A.near(App.bus_volume(routed, "ambience"), 0.25, 1e-12, "events file: ambience follows sfx once")
  A.near(App.bus_volume(routed, "music"), 0.5, 1e-12, "music")
  A.eq(App.bus_volume(routed, "voice"), 0.6, "a bus the file does not name: the slider")
end

function T.test_arrow_side()
  A.eq(Subtitles.with_arrow("[growl]", "←"), "← [growl]", "left: before")
  A.eq(Subtitles.with_arrow("[growl]", "↖"), "↖ [growl]", "up-left: before")
  A.eq(Subtitles.with_arrow("[growl]", "↙"), "↙ [growl]", "down-left: before")
  A.eq(Subtitles.with_arrow("[growl]", "→"), "[growl] →", "right: after")
  A.eq(Subtitles.with_arrow("[growl]", "↑"), "[growl] ↑", "up: after")
  A.eq(Subtitles.with_arrow("[growl]", ""), "[growl]", "on screen: none")
end

local function fake_app()
  return {
    dialogue = { captions = { growl = { text = "[growl]", directional = true }, thud = { text = "[thud]" } } },
    settings = { access = { captions_sfx = true } },
    i18n = { has = function() return false end, is_pseudo = function() return false end },
    t = function(_, key) return key end,
  }
end

function T.test_directional_caption()
  local s = Subtitles.new(fake_app())
  local view = { half_w = 320, half_h = 180 }
  local function from(dx, dy) return { dx = dx, dy = dy, half_w = view.half_w, half_h = view.half_h } end
  A.truthy(s:caption("growl", from(-900, 0)))
  A.eq(s.captions.growl.shown, "← [growl]", "off screen left")
  s:caption("growl", from(900, 120))
  A.eq(s.captions.growl.shown, "[growl] →", "off screen right")
  s:caption("growl", from(-500, 500))
  A.eq(s.captions.growl.shown, "↙ [growl]", "down-left")
  s:caption("growl", from(100, 100))
  A.eq(s.captions.growl.shown, "[growl]", "on screen: no arrow")
  s:caption("growl")
  A.eq(s.captions.growl.shown, "[growl]", "no source: no arrow")
  s:caption("thud", from(-900, 0))
  A.eq(s.captions.thud.shown, "[thud]", "not directional: no arrow")
end

return T

-- {{FOOTER}}
