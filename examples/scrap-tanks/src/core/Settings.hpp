// ---------------------------------------------------------------------------
// Settings.hpp
// Purpose : The player's settings (display, audio, language, accessibility, input, telemetry consent):
//           built-in defaults, loading with validation, and crash-safe saving. Plain C++, no SDL.
// Usage   : auto loaded = core::settings_load_file(core::path_from_utf8(user_dir + "/settings.json"));
//           for (const auto& p : loaded.problems) LOG_WARN("settings", "fixed " << p);
//           nlohmann::json& s = loaded.settings;
//           const double volume = s["audio"]["master"].get<double>() * s["audio"]["sfx"].get<double>();
//           shake.update(dt, core::effective_shake(s));
//           s["access"]["text_scale"] = 1.25;  core::settings_save_file(path, s);
// Notes   : Settings are a JSON object, so keys this build does not know (a newer game's file) survive a
//           load and a save. Loading never fails: a missing file gives the defaults, a broken one gives the
//           defaults plus the problem "unreadable", and each bad field is replaced (numbers are clamped to
//           their range, wrong types take the default) and listed in problems. Matches
//           tools/golden_vectors.py (DEFAULT_SETTINGS, SCHEMA, settings_load), checked against
//           data/golden/shell.json. The option lists below are what a settings menu offers.
//
// Pseudocode:
//   settings_load(text):
//     missing -> {} ; not JSON -> defaults, ["unreadable"] ; not an object -> defaults, ["not an object"]
//     out = copy of everything in the file ; version = 1 ; language = valid tag (2..12 characters) or "en"
//     per schema section: not an object -> problem, treat as {} ; keep its unknown keys
//       per field: missing -> default ; present -> fixed by its rule (num clamp, bool, enum, resolution)
//     input.bindings: defaults, then each action from the file (string entries only)
//   effective_shake = 0 with reduce_motion, else shake_scale ; telemetry_allowed = consent is "yes"
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include <array>
#include <cstddef>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <nlohmann/json.hpp>

namespace core {

// ---- Constants: the settings schema's choices (defaults live in default_settings()) ----
constexpr int kSettingsVersion = 1;
constexpr std::size_t kLanguageMinLength = 2;   // "en"
constexpr std::size_t kLanguageMaxLength = 12;  // "zh-Hant-TW" fits
constexpr std::array<std::string_view, 4> kDifficulties = {"story", "easy", "normal", "hard"};
constexpr std::array<std::string_view, 4> kColorblindModes = {"none", "protanopia", "deuteranopia", "tritanopia"};
constexpr std::array<std::string_view, 4> kSubtitleSizes = {"small", "medium", "large", "xl"};
constexpr std::array<std::string_view, 3> kDisplayModes = {"windowed", "fullscreen", "borderless"};
constexpr std::array<int, 6> kFrameCaps = {0, 30, 60, 120, 144, 240};  // 0 = uncapped
constexpr std::array<std::string_view, 3> kConsentValues = {"unset", "yes", "no"};
// input.glyphs choices: kGlyphSets in Bindings.hpp

struct SettingsLoad {
    nlohmann::json settings;            // complete and valid, unknown keys kept
    std::vector<std::string> problems;  // what was fixed: "audio.master", "input.bindings.jump", "unreadable", ...
};

// The built-in defaults (a fresh install).
nlohmann::json default_settings();

// Settings from a file's text; std::nullopt means there is no file (defaults, no problems).
SettingsLoad settings_load(const std::optional<std::string>& text);

// settings_load() on a file. A file that exists but cannot be read counts as the problem "unreadable".
SettingsLoad settings_load_file(const std::filesystem::path& file);

// Writes settings crash-safely (AtomicFile.hpp), pretty-printed so players can edit the file.
bool settings_save_file(const std::filesystem::path& file, const nlohmann::json& settings,
                        std::string* error = nullptr);

// The shake intensity to use: 0 with reduce motion, else the shake_scale slider.
double effective_shake(const nlohmann::json& settings);

// True only after the player said yes (consent "yes"); "unset" and "no" both mean no telemetry.
bool telemetry_allowed(const nlohmann::json& settings);

}  // namespace core
