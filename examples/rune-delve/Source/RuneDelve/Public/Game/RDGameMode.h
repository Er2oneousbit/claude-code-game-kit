// ---------------------------------------------------------------------------
// RDGameMode.h
// Purpose : Runs a delve: builds the dungeon, spawns the seeded orcs, tracks rooms (clear -> gate opens,
//           mage healed), decides the outcome, logs the markers, feeds the bot, restarts on R.
// Usage   : GlobalDefaultGameMode in Config/DefaultEngine.ini; the Delve map only holds a PlayerStart and
//           the NavMesh bounds (tools/unreal/build_content.py)
// Notes   : Markers: READY, DELVE_START, ORC_ALERT, WARD_BLOCK, ORC_DOWN, ROOM_CLEARED n/3, MAGE_DOWN,
//           DELVE_COMPLETE, TIMEOUT. -fixedfps makes every frame 1/60 s and lets the engine run flat out,
//           so a packaged autoplay run and the smoke test play the same delve.
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
	void ShowToast(const FString& Text);

	UPROPERTY() TObjectPtr<ARDDungeon> Dungeon;
	UPROPERTY() TArray<TObjectPtr<ARDOrc>> Orcs;

	ERDOutcome Outcome = ERDOutcome::Playing;
	bool bCleared[FRDLevel::RoomCount] = {false, false, false};
	int32 CurrentRoom = 0;
	int32 Kills = 0;
	float Elapsed = 0.f;
	float EndTimer = 0.f;
	int32 Frame = 0;
	FString Toast;
	float ToastLeft = 0.f;
};
