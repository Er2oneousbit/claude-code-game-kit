// ---------------------------------------------------------------------------
// GameKitSaveStore.h
// Purpose : Save games: a versioned envelope, migration of old saves to the current version, a fallback to
//           the backup when the main file is broken, and crash-safe writes that keep the previous good save as
//           <file>.bak. Plain C++ on FJsonObject (no USaveGame, so the file stays text Claude can read).
// Usage   : const FGameKitSaveStore Store(FPaths::ProjectSavedDir() / TEXT("GameKit/save.json"));
//           const FGameKitSaveLoad Loaded = Store.Load();
//           if (!Loaded.Envelope.IsValid()) { StartNewGame(); }        // Loaded.Problems says why (log it)
//           else { Restore(Loaded.Envelope->GetObjectField(TEXT("data"))); }   // already migrated to SaveVersion
//           FString Error;  if (!Store.Save(Snapshot(), &Error)) { UE_LOG(LogMyGame, Error, TEXT("%s"), *Error); }
// Notes   : The file is {"format": "save", "version": N, "data": {...game state...}}. Bump SaveVersion when
//           the data's shape changes and add one migration step (GameKitSaveStore.cpp SaveMigrations; a
//           static_assert there fails the build until you do), and a test that loads a save of the old
//           version. A save from a NEWER game version is never loaded, and Save() refuses to overwrite it
//           (the player may go back to the newer build). Matches tools/golden_vectors.py (save_load,
//           migrations), checked against data/golden/shell.json; the files are tested in a temp folder.
//
// Pseudocode:
//   Parse(text): missing | unreadable | not a save | bad version | newer -> problem ; else the envelope
//   SaveLoad(primary, backup): the first of the two that parses, migrated step by step to SaveVersion
//   Save(data):
//     either file holds a newer save -> refuse
//     write <file>.tmp ; if the current <file> is a good save, copy it to <file>.bak (atomically)
//     rename <file>.tmp over <file>
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

struct FGameKitSaveLoad
{
	TSharedPtr<FJsonObject> Envelope;   // at SaveVersion, or null when nothing could be loaded
	FString Source;                     // "primary", "backup" or "none"
	TArray<FString> Problems;           // "primary: unreadable", "backup: missing", ...
	bool bNewer = false;                // a file came from a newer game version (tell the player; never overwrite)
};

namespace GameKit
{
	// ---- Constants ----
	inline constexpr int32 SaveVersion = 3;               // the version this build writes; older saves are migrated up to it
	inline constexpr const TCHAR* SaveFormat = TEXT("save");

	/** Loads from the two files' texts (unset = that file does not exist). */
	GAMEKITSHELL_API FGameKitSaveLoad SaveLoad(const TOptional<FString>& Primary, const TOptional<FString>& Backup);

	/** A copy of Envelope migrated to SaveVersion (its version must be 1..SaveVersion). */
	GAMEKITSHELL_API TSharedRef<FJsonObject> SaveMigrate(const TSharedRef<FJsonObject>& Envelope);

	/** A current-version envelope around the game's data (copied). */
	GAMEKITSHELL_API TSharedRef<FJsonObject> SaveEnvelope(const TSharedRef<FJsonObject>& Data);
}

class GAMEKITSHELL_API FGameKitSaveStore
{
public:
	explicit FGameKitSaveStore(const FString& InFile) : File(InFile) {}

	FGameKitSaveLoad Load() const;

	/** Writes Data as the new save (see Pseudocode). False and *OutError on failure; the old save is then untouched. */
	bool Save(const TSharedRef<FJsonObject>& Data, FString* OutError = nullptr) const;

	const FString& GetFile() const { return File; }
	FString GetBackupFile() const;

private:
	FString File;
};
