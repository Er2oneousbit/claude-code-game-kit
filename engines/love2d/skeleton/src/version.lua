-- ---------------------------------------------------------------------------
-- version.lua
-- Purpose : The game's name and version, in ONE place (docs/sop/SOP-06 "Versioning"): the title screen, the log's
--           first line, crash files and bug reports read it from here.
-- Usage   : local Version = require("src.version"); print(Version.name, Version.version)
-- Notes   : Bump version in the same commit as the change log entry, and tag the commit v<version>.
-- Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
-- ---------------------------------------------------------------------------
return {
  name = "{{GAME_NAME}}",
  version = "0.1.0",
}

-- {{FOOTER}}
