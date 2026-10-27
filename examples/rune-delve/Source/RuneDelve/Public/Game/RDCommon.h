// ---------------------------------------------------------------------------
// RDCommon.h
// Purpose : Shared bits for the game layer: the log category and scenario markers, launch options (command
//           line or a test), and every asset path in one table.
// Usage   : RD_MARK(TEXT("ROOM_CLEARED %d/3"), N);  const FRDLaunchOptions& O = FRDLaunchOptions::Get();
// Notes   : Markers are what `dev.py smoke` scenario runs and the packaged-build replay look for in the log.
//           Asset paths: content is made by tools/unreal/build_content.py (Interchange names an animation
//           <mesh name><anim name>, e.g. character-orcwalk). Config/DefaultGame.ini cooks /Game/Art and
//           /Game/Audio always, because nothing references these assets except by path (ENGINE.md gotcha 7).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Core/RDBotPolicy.h"

RUNEDELVE_API DECLARE_LOG_CATEGORY_EXTERN(LogRuneDelve, Log, All);

#define RD_MARK(Format, ...) UE_LOG(LogRuneDelve, Display, TEXT("[MARK] ") Format, ##__VA_ARGS__)

struct RUNEDELVE_API FRDLaunchOptions
{
	ERDBotMode Bot = ERDBotMode::None;
	int32 Seed = 0;
	bool bGod = false;
	bool bDebugAI = false;
	bool bFixedFps = false;       // 1/60 s per frame, as fast as the machine allows: runs replay exactly
	bool bQuitAtEnd = false;      // packaged autoplay: exit 0 on a full clear, 3 otherwise
	FString RecordDir;            // screenshots every RecordEvery frames (needs a real renderer)
	int32 RecordEvery = 6;
	float MaxSeconds = 300.f;     // a stuck delve ends as a timeout instead of hanging a test

	/** The options in force: a test's override if set, else parsed once from the command line. */
	static const FRDLaunchOptions& Get();
	static void SetTestOverride(const FRDLaunchOptions& Options);
	static void ClearTestOverride();
};

namespace RDAssets
{
	inline const TCHAR* Characters = TEXT("/Game/Art/Characters/");
	inline const TCHAR* Dungeon = TEXT("/Game/Art/Dungeon/");
	inline const TCHAR* Audio = TEXT("/Game/Audio/");
	inline const TCHAR* Map = TEXT("/Game/Maps/Delve");
	/** "/Game/Art/Dungeon/floor" -> "/Game/Art/Dungeon/floor.floor" (a loadable object path). */
	inline FString Object(const TCHAR* Folder, const FString& Name) { return FString::Printf(TEXT("%s%s.%s"), Folder, *Name, *Name); }
}
