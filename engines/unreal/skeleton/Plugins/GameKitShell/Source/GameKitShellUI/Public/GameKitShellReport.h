// ---------------------------------------------------------------------------
// GameKitShellReport.h
// Purpose : What a player hands a developer when something goes wrong (#275), as the LÖVE and Godot shells do:
//           the log tail (the last lines Unreal logged), a crash file written when the game hits a fatal error
//           (<DataDir>/crashes/crash_<time>.txt with the version, the error, the log tail and the settings), and the
//           unique file names both use. The F8 bug report (FGameKitShellModel::BugReport) uses the log tail too.
// Usage   : GameKit::ShellReport::StartLogTail();                       // the module does this at start-up
//           GameKit::ShellReport::SetCrashTarget(this, {DataDir, Name, Version, SettingsJson});   // a running shell
//           GameKit::ShellReport::WriteCrash(TEXT("what went wrong"));   // -> the file's path, logs CRASH_WRITTEN
// Notes   : The module binds OnSystemError() to FCoreDelegates::OnHandleSystemError, which the engine fires on a
//           fatal error or crash before its own crash reporter runs; a crash file is written only while a shell has
//           set a target (the subsystem does, for the game and PIE), never for an editor crash elsewhere. That path
//           runs on the crash-handling thread: it takes the locks with TryLock, so a thread that crashed holding
//           one cannot hang the report. Nothing leaves the machine.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit::ShellReport
{
	// ---- Tunables ----
	inline constexpr int32 KeepLines = 400;          // log lines the tail keeps
	inline constexpr int32 CrashTailLines = 60;      // lines a crash file shows
	inline constexpr int32 BugTailLines = 200;       // lines a bug report's log_tail.txt shows
	inline constexpr int32 MaxSameSecond = 50;       // crash_<time>_2.txt ... when several share a second
	inline constexpr const TCHAR* CrashFolder = TEXT("crashes");

	/** Where a crash file goes, and what it says about the game. */
	struct FCrashTarget
	{
		FString DataDir;
		FString GameName;
		FString Version;
		FString SettingsJson;
	};

	/** Starts keeping the last KeepLines log lines (GLog); StopLogTail() lets go. */
	GAMEKITSHELLUI_API void StartLogTail();
	GAMEKITSHELLUI_API void StopLogTail();
	/** Adds one line to the tail by hand (tests; the log device does it for every logged line). */
	GAMEKITSHELLUI_API void AddLogLine(const FString& Line);
	/** The last Lines log lines, oldest first, one per line ("" when none). */
	GAMEKITSHELLUI_API FString LogTail(int32 Lines);

	/** Owner's target for crash files (the newest owner wins); ClearCrashTarget(Owner) removes it if it is still Owner's. */
	GAMEKITSHELLUI_API void SetCrashTarget(const void* Owner, const FCrashTarget& Target);
	GAMEKITSHELLUI_API void UpdateCrashSettings(const void* Owner, const FString& SettingsJson);
	GAMEKITSHELLUI_API void ClearCrashTarget(const void* Owner);
	GAMEKITSHELLUI_API bool HasCrashTarget();

	/** The crash file's text (pure: the tests check it). */
	GAMEKITSHELLUI_API FString CrashText(const FCrashTarget& Target, const FString& Error, const FString& Tail, const FString& Time);

	/** Writes <DataDir>/crashes/crash_<time>.txt for Error and logs CRASH_WRITTEN <path>; the path, or "" when no shell
	 *  set a target or the file could not be written. */
	GAMEKITSHELLUI_API FString WriteCrash(const FString& Error);

	/** What FCoreDelegates::OnHandleSystemError calls: WriteCrash with the engine's error text. */
	GAMEKITSHELLUI_API void OnSystemError();

	/** A path in Dir not taken yet: <Prefix><Stamp><Ext>, else <Prefix><Stamp>_2<Ext> ... (files and folders alike). */
	GAMEKITSHELLUI_API FString UniquePath(const FString& Dir, const FString& Prefix, const FString& Stamp, const FString& Ext);

	/** Now as yyyymmdd_hhmmss (local time), the stamp in crash and bug report names. */
	GAMEKITSHELLUI_API FString Stamp();
}

// {{FOOTER}}
