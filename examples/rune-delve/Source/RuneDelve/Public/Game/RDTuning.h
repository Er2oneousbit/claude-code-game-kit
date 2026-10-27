// ---------------------------------------------------------------------------
// RDTuning.h
// Purpose : Every gameplay number, read from Config/DefaultGame.ini [/Script/RuneDelve.RDTuning] and shown
//           under Project Settings > Game > Rune Delve Tuning.
// Usage   : const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
// Notes   : No C++ defaults on purpose (all zero): the ini is the one source of truth, so a changed number
//           reaches the game and the tests alike. A zero left anywhere fails RuneDelve.Core.Tuning.
//           (The Unity example learned the hard way that code defaults and an asset drift apart.)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "Core/RDNumbers.h"
#include "RDTuning.generated.h"

UCLASS(Config = Game, DefaultConfig, meta = (DisplayName = "Rune Delve Tuning"))
class RUNEDELVE_API URDTuning : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	FRDNumbers Numbers() const;

	UPROPERTY(Config, EditAnywhere, Category = "Mage") float MageHealth = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Mage") float MageMana = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Mage") float ManaRegen = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Mage") float MageSpeed = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Mage") float RoomClearHeal = 0.f;

	UPROPERTY(Config, EditAnywhere, Category = "Bolt") float BoltCost = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Bolt") float BoltCooldown = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Bolt") float BoltDamage = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Bolt") float BoltSpeed = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Bolt") float BoltRange = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Bolt") float BoltNoise = 0.f;

	UPROPERTY(Config, EditAnywhere, Category = "Dash") float DashCooldown = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Dash") float DashDistance = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Dash") float DashSeconds = 0.f;

	UPROPERTY(Config, EditAnywhere, Category = "Ward") float WardCost = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Ward") float WardCooldown = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Ward") float WardSeconds = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Ward") float StaggerSeconds = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Ward") float StaggerDamageMult = 0.f;

	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float OrcSight = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float OrcSightHalfAngle = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float StrikeSlack = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float GruntHealth = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float GruntSpeed = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float GruntReach = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float GruntWindup = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float GruntDamage = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float GruntRecover = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float WardenHealth = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float WardenSpeed = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float WardenReach = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float WardenWindup = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float WardenDamage = 0.f;
	UPROPERTY(Config, EditAnywhere, Category = "Orcs") float WardenRecover = 0.f;
};
