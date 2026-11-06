// ---------------------------------------------------------------------------
// RDGameMode.h
// Purpose : Runs a delve: builds the dungeon, spawns the seeded orcs, tracks rooms (clear -> gate opens,
//           mage healed), decides the outcome, logs the markers, feeds the bot, restarts on R.
// Usage   : GlobalDefaultGameMode in Config/DefaultEngine.ini; the Delve map only holds a PlayerStart and
//           the NavMesh bounds (tools/unreal/build_content.py)
// Notes   : Markers: READY, DELVE_START, ORC_ALERT, WARD_BLOCK, ORC_DOWN, ROOM_CLEARED n/3, MAGE_DOWN,
//           DELVE_COMPLETE, TIMEOUT. -fixedfps makes every frame 1/60 s and lets the engine run flat out,
//           so a packaged autoplay run and the smoke test play the same delve; it also finishes the runtime
//           NavMesh's pending tiles before the actors of a frame tick (FinishNavBuild, #8). -tracedelve logs one
//           [trace] line per frame for tools/unreal/replay_check.py.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Core/RDBotPolicy.h"
#include "Core/RDLevel.h"
#include "GameFramework/GameModeBase.h"
#include "RDGameMode.generated.h"

class ARDDungeon;
class ARDMage;
class ARDOrc;

UENUM()
enum class ERDOutcome : uint8
{
	Playing,
	Cleared,
	Fallen,
	Timeout
};

UCLASS()
class RUNEDELVE_API ARDGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	static constexpr float QuitDelaySeconds = 2.f;
	static constexpr float ToastSeconds = 2.5f;

	ARDGameMode();
	virtual void StartPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	ARDMage* GetMage() const;
	const TArray<TObjectPtr<ARDOrc>>& GetOrcs() const { return Orcs; }
	ERDOutcome GetOutcome() const { return Outcome; }
	int32 RoomsCleared() const;
	int32 GetKills() const { return Kills; }
	int32 GetCurrentRoom() const { return CurrentRoom; }
	float GetElapsed() const { return Elapsed; }
	const FString& GetToast() const { return Toast; }
	float GetToastLeft() const { return ToastLeft; }
	/** One line for the scenario log: outcome, rooms, kills, time and the mage's counters. */
	FString Summary() const;

	FRDBotSnapshot BotSnapshot() const;
	void OnOrcDied(ARDOrc* Orc);
	void OnMageDied();
	void RestartDelve();

private:
	void SpawnOrcs();
	void UpdateRooms();
	void Finish(ERDOutcome Result, const TCHAR* Marker);
	void Record();
	void Trace(UWorld* World, ELevelTick TickType, float DeltaSeconds);
	void ShowToast(const FString& Text);
	void QuitAtEnd(uint8 ExitCode);
	void FinishNavBuild(UWorld* World, ELevelTick TickType, float DeltaSeconds);

	UPROPERTY() TObjectPtr<ARDDungeon> Dungeon;
	UPROPERTY() TArray<TObjectPtr<ARDOrc>> Orcs;

	ERDOutcome Outcome = ERDOutcome::Playing;
	bool bCleared[FRDLevel::RoomCount] = {false, false, false};
	int32 CurrentRoom = 0;
	int32 Kills = 0;
	float Elapsed = 0.f;
	float EndTimer = 0.f;
	bool bQuitRequested = false;
	int32 Frame = 0;
	int32 TraceFrame = 0;
	int32 NavSyncBuilds = 0;      // -fixedfps: frames on which FinishNavBuild had tiles to finish
	FDelegateHandle NavSyncHandle;
	FDelegateHandle TraceHandle;
	FString Toast;
	float ToastLeft = 0.f;
};
