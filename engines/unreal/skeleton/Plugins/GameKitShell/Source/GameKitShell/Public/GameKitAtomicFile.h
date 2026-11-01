// ---------------------------------------------------------------------------
// GameKitAtomicFile.h
// Purpose : Crash-safe file writes for settings and saves, plus whole-file readers that tell "never written"
//           from "the disk said no". Plain C++ on Unreal's platform file layer.
// Usage   : FString Error;
//           if (!GameKit::WriteFileAtomic(Path, Text, &Error)) { UE_LOG(LogMyGame, Error, TEXT("save failed: %s"), *Error); }
//           if (const TOptional<FString> Text = GameKit::ReadTextFile(Path)) { ... *Text ... }
// Notes   : A crash at any moment leaves either the old file or the new one, never half a file: the bytes go to
//           <file>.tmp first, are flushed to the disk, and only then renamed over <file> (MoveFileExW with
//           replace and write-through on Windows). After a power cut this also depends on the file system keeping
//           the rename, which is why saves also keep a .bak (FGameKitSaveStore).
//           A stale <file>.tmp from a crash is harmless (nobody reads it) and is replaced by the next write.
//           WriteTemp() and CommitTemp() are the two halves, public so tests can stop in between. Text is
//           written as UTF-8 without a BOM; reading accepts UTF-8 with or without a BOM, and UTF-16.
//           Windows renames with MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH): the engine's MoveFile
//           refuses to replace an existing file there, and IFileManager::Move deletes first (not atomic).
//           Put player files under FPaths::ProjectSavedDir() (the user's folder in a packaged game).
//           GameKitSaveStore.h adds the <file>.bak of the previous good save.
//
// Pseudocode:
//   WriteTemp(f, bytes): create folders, open f.tmp, write, flush to disk, close; any failure -> delete f.tmp
//   CommitTemp(f)      : rename f.tmp over f in one step
//   WriteFileAtomic    : WriteTemp, then CommitTemp
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

namespace GameKit
{
	// ---- Constants ----
	inline constexpr const TCHAR* TempSuffix = TEXT(".tmp");     // <file>.tmp while a write is in flight
	inline constexpr const TCHAR* BackupSuffix = TEXT(".bak");   // <file>.bak: the previous good save (SaveStore)

	/** <file>.tmp and <file>.bak next to Target (the suffix is appended: save.json -> save.json.tmp). */
	GAMEKITSHELL_API FString TempPathFor(const FString& Target);
	GAMEKITSHELL_API FString BackupPathFor(const FString& Target);

	/** The whole file, or unset. A missing file leaves *OutError empty; a file that exists but cannot be read sets it. */
	GAMEKITSHELL_API TOptional<TArray<uint8>> ReadFileBytes(const FString& Path, FString* OutError = nullptr);
	GAMEKITSHELL_API TOptional<FString> ReadTextFile(const FString& Path, FString* OutError = nullptr);

	/** Step 1: the bytes (or the text as UTF-8) into <Target>.tmp, flushed to the disk. Creates missing folders. */
	GAMEKITSHELL_API bool WriteTemp(const FString& Target, const TArray<uint8>& Bytes, FString* OutError = nullptr);
	GAMEKITSHELL_API bool WriteTemp(const FString& Target, const FString& Text, FString* OutError = nullptr);

	/** Step 2: <Target>.tmp replaces Target. False on failure (Target is unchanged). */
	GAMEKITSHELL_API bool CommitTemp(const FString& Target, FString* OutError = nullptr);

	/** Both steps: the crash-safe replacement for "open, write, close". */
	GAMEKITSHELL_API bool WriteFileAtomic(const FString& Target, const TArray<uint8>& Bytes, FString* OutError = nullptr);
	GAMEKITSHELL_API bool WriteFileAtomic(const FString& Target, const FString& Text, FString* OutError = nullptr);
}

// {{FOOTER}}
