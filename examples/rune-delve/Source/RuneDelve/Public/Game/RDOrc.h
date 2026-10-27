// ---------------------------------------------------------------------------
// RDOrc.h
// Purpose : An orc grunt or the warden: runs FRDOrcBrain each tick, chases the mage on the NavMesh through
//           its ARDOrcController, swings when the brain says so, and shows its wind-up (red glow, raised
//           weapon) so a player can time the ward.
// Usage   : spawned by ARDGameMode with SpawnActorDeferred, Setup(Spawn, Stats) before FinishSpawning
// Notes   : Senses come from AI Perception on the controller (sight cone, hearing for bolt noise), and only
//           count inside the orc's own room; being hurt wakes it wherever the mage stands, and once awake it
//           hunts the mage through any open gate. The brain decides; this class turns that into movement,
//           animation, light and damage.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes: hurt bypasses the room gate; ContactDelay times the swing clip to the hit
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Core/RDBotPolicy.h"
#include "Core/RDLevel.h"
#include "Core/RDOrcBrain.h"
#include "Game/RDCharacterBase.h"
#include "RDOrc.generated.h"

class ARDMage;
class UPointLightComponent;

UCLASS()
class RUNEDELVE_API ARDOrc : public ARDCharacterBase
{
	GENERATED_BODY()

public:
	static constexpr float WardenScale = 1.5f;
	static constexpr float TelegraphIntensity = 9000.f;
	static constexpr float AlertMarkSeconds = 1.2f;
	static constexpr float CorpseSeconds = 0.8f;   // a dead orc disappears after its death animation
	// s from the start of the Kenney attack-melee-right clip (0.417 s long) to its contact frame: the arm and torso
	// reach the end of the forward swing at 0.25 s (measured by sampling the clip's bones with a headless exec probe)
	static constexpr float ContactDelay = 0.25f;
	static constexpr const TCHAR* SwingAnim = TEXT("attack-melee-right");

	ARDOrc();
	void Setup(const FRDSpawn& Spawn, const FRDOrcStats& InStats);
	virtual void Tick(float DeltaSeconds) override;

	/** AI Perception saw or heard the mage (the controller calls this). */
	void NotifySensed() { bSensedThisTick = true; }

	int32 GetRoom() const { return Room; }
	bool IsWarden() const { return bWarden; }
	ERDOrcState GetState() const { return Brain.IsSet() ? Brain->GetState() : ERDOrcState::Sleep; }
	float WindupLeft() const { return Brain.IsSet() ? Brain->WindupLeft() : 1e9f; }
	float GetReach() const { return Stats.Reach; }
	float AlertMarkLeft() const { return AlertMark; }
	FRDBotOrc ToBot() const;

	virtual void OnHurt(float Damage, ARDCharacterBase* Source) override;
	virtual void OnZeroHealth(ARDCharacterBase* Killer) override;

protected:
	virtual void BeginPlay() override;

private:
	void Strike(ARDMage* Mage);
	/** Play the swing clip from Position seconds in, so its contact frame comes ContactDelay - Position later. */
	void StartSwingClip(float Position);

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UPointLightComponent> Telegraph;

	TOptional<FRDOrcBrain> Brain;
	FRDOrcStats Stats;
	int32 Room = 0;
	bool bWarden = false;
	bool bSensedThisTick = false;
	bool bHurtThisTick = false;
	float AlertMark = 0.f;
};
