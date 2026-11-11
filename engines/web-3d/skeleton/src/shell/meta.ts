// ---------------------------------------------------------------------------
// meta.ts
// Purpose : The game's name and version in one place for the shell, logs and crash files.
// Notes   : The version comes from package.json (the one version source, SOP-06).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
import { version } from "../../package.json";

export const GAME_NAME = "{{GAME_NAME}}";
export const GAME_SLUG = "{{GAME_SLUG}}";
export const GAME_VERSION: string = version;
export const SETTINGS_FILE = "settings.json";

// {{FOOTER}}
