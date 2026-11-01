// ---------------------------------------------------------------------------
// GameKitSettings.h
// Purpose : The player's settings (display, audio, language, accessibility, input, telemetry consent):
//           built-in defaults, loading with validation, and crash-safe saving. Plain C++ on FJsonObject.
// Usage   : const FString File = FPaths::ProjectSavedDir() / TEXT("GameKit/settings.json");
//           FGameKitSettingsLoad Loaded = GameKit::SettingsLoadFile(File);
//           for (const FString& P : Loaded.Problems) { UE_LOG(LogMyGame, Warning, TEXT("settings: fixed %s"), *P); }
//           TSharedRef<FJsonObject> S = Loaded.Settings;
//           const double Volume = GameKit::SettingNumber(*S, TEXT("audio"), TEXT("master")) * GameKit::SettingNumber(*S, TEXT("audio"), TEXT("sfx"));
//           Shake.Update(DeltaSeconds, GameKit::EffectiveShake(*S));
//           S->GetObjectField(TEXT("access"))->SetNumberField(TEXT("text_scale"), 1.25);  GameKit::SettingsSaveFile(File, S);
// Notes   : Settings are a JSON object, so keys this build does not know (a newer game's file) survive a
//           load and a save. Loading never fails: a missing file gives the defaults, a broken one gives the
//           defaults plus the problem "unreadable", and each bad field is replaced (numbers are clamped to
//           their range, wrong types take the default) and listed in Problems. Hand the values to the
//           engine yourself (UGameUserSettings for the window and vsync, Sound Classes for volumes). Matches
//           tools/golden_vectors.py (DEFAULT_SETTINGS, SCHEMA, settings_load), checked against
//           data/golden/shell.json. The option lists below are what a settings menu offers.
//
// Pseudocode:
//   SettingsLoad(text):
//     missing -> {} ; not JSON -> defaults, ["unreadable"] ; not an object -> defaults, ["not an object"]
//     out = copy of everything in the file ; version = 1 ; language = a tag of 2..12 characters, or "en"
//     per schema section: not an object -> problem, treat as {} ; keep its unknown keys
//       per field: missing -> default ; present -> fixed by its rule (num clamp, bool, enum, resolution)
//     input.bindings: defaults, then each action from the file (string entries only)
//   EffectiveShake = 0 with reduce_motion, else shake_scale ; TelemetryAllowed = consent is "yes"
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

struct FGameKitSettingsLoad
{
	TSharedRef<FJsonObject> Settings = MakeShared<FJsonObject>();   // complete and valid, unknown keys kept
	TArray<FString> Problems;   // what was fixed: "audio.master", "input.bindings.jump", "unreadable", ...
};

namespace GameKit
{
	// ---- Constants: the schema's choices (the defaults and ranges live in GameKitSettings.cpp) ----
	inline constexpr int32 SettingsVersion = 1;
	inline constexpr int32 LanguageMinLength = 2;    // "en"
	inline constexpr int32 LanguageMaxLength = 12;   // "zh-Hant-TW" fits
	inline constexpr const TCHAR* Difficulties[] = {TEXT("story"), TEXT("easy"), TEXT("normal"), TEXT("hard")};
	inline constexpr const TCHAR* ColorblindModes[] = {TEXT("none"), TEXT("protanopia"), TEXT("deuteranopia"), TEXT("tritanopia")};
	inline constexpr const TCHAR* SubtitleSizes[] = {TEXT("small"), TEXT("medium"), TEXT("large"), TEXT("xl")};
	inline constexpr const TCHAR* DisplayModes[] = {TEXT("windowed"), TEXT("fullscreen"), TEXT("borderless")};
	inline constexpr int32 FrameCaps[] = {0, 30, 60, 120, 144, 240};   // 0 = uncapped
	inline constexpr const TCHAR* ConsentValues[] = {TEXT("unset"), TEXT("yes"), TEXT("no")};
	// input.glyphs choices: GlyphSets in GameKitBindings.h

	/** The built-in defaults (a fresh install). A new object each call: change it freely. */
	GAMEKITSHELL_API TSharedRef<FJsonObject> DefaultSettings();

	/** Settings from a file's text; unset Text means there is no file (defaults, no problems). */
	GAMEKITSHELL_API FGameKitSettingsLoad SettingsLoad(const TOptional<FString>& Text);

	/** SettingsLoad() on a file. A file that exists but cannot be read counts as the problem "unreadable". */
	GAMEKITSHELL_API FGameKitSettingsLoad SettingsLoadFile(const FString& File);

	/** Writes settings crash-safely (GameKitAtomicFile.h), pretty-printed so players can edit the file. */
	GAMEKITSHELL_API bool SettingsSaveFile(const FString& File, const TSharedRef<FJsonObject>& Settings, FString* OutError = nullptr);

	/** The shake intensity to use: 0 with reduce motion, else the shake_scale slider. */
	GAMEKITSHELL_API double EffectiveShake(const FJsonObject& Settings);

	/** True only after the player said yes (consent "yes"); "unset" and "no" both mean no telemetry. */
	GAMEKITSHELL_API bool TelemetryAllowed(const FJsonObject& Settings);

	// ---- Typed reads of one field (section.field), falling back to the built-in default ----
	GAMEKITSHELL_API double SettingNumber(const FJsonObject& Settings, const FString& Section, const FString& Field);
	GAMEKITSHELL_API bool SettingBool(const FJsonObject& Settings, const FString& Section, const FString& Field);
	GAMEKITSHELL_API FString SettingString(const FJsonObject& Settings, const FString& Section, const FString& Field);
	/** The language tag ("en", "fr-CA"). */
	GAMEKITSHELL_API FString SettingLanguage(const FJsonObject& Settings);
	/** display.resolution as a point (1920 x 1080 by default). */
	GAMEKITSHELL_API FIntPoint SettingResolution(const FJsonObject& Settings);
}
