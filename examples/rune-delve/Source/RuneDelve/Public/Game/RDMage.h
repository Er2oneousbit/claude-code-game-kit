// ---------------------------------------------------------------------------
// RDMage.h
// Purpose : The player's rune-mage: top-down camera, Enhanced Input (WASD/stick, mouse/stick aim, bolt,
//           ward, dash, restart), the three GAS abilities, and an optional autoplay bot (RDBot policies).
// Usage   : ARDGameMode's default pawn; -autoplay=weaver|masher hands it to a bot
// Notes   : Input actions and the mapping context are built in C++ at runtime (no input assets to make in
//           the editor). The camera looks down +X, so W moves along +X and D along +Y.
//           The bot follows NavMesh paths (FindPathToLocationSynchronously) and casts through the same
//           abilities a player uses, so cooldowns and mana apply to it exactly as to a person.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 SetAimForTest (the regression tests aim without a mouse); dash and bolt review fixes
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Core/RDBotPolicy.h"
#include "Game/RDCharacterBase.h"
#include "InputActionValue.h"
#include "RDMage.generated.h"

class UCameraComponent;
class UInputAction;
class UInputMappingContext;
class UPointLightComponent;
class USpringArmComponent;
struct FRDNumbers;

UCLASS()
class RUNEDELVE_API ARDMage : public ARDCharacterBase
{
	GENERATED_BODY()

public:
	static constexpr float CameraPitch = -60.f;
	static constexpr float CameraDistance = 1700.f;
	static constexpr float RepathSeconds = 0.3f;

	ARDMage();
	virtual void Tick(float DeltaSeconds) override;
	virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;
	virtual bool IsGod() const override;

	// Spell effects, called by the abilities after cost and cooldown are paid
	void FireBolt(const FRDNumbers& N);
	void RaiseWard(const FRDNumbers& N);
	void StartDash(const FRDNumbers& N);

	virtual void OnHurt(float Damage, ARDCharacterBase* Source) override;
	virtual void OnWardBlock(ARDCharacterBase* Attacker) override;
	virtual void OnDodged() override;
	virtual void OnZeroHealth(ARDCharacterBase* Killer) override;

	float CooldownLeft(const FGameplayTag& Tag) const { return TimeLeft(Tag); }
	const TCHAR* BotReason() const { return LastReason; }
	FVector2D AimPoint() const { return Aim; }
	/** Tests only: hold the aim at P (a headless PIE session has no mouse to aim with). */
	void SetAimForTest(const FVector2D& P) { Aim = P; bTestAim = true; }
	bool IsDashing() const { return DashLeft > 0.f; }

	// Counters for the scenario log
	int32 BoltsCast = 0;
	int32 WardsCast = 0;
	int32 WardBlocks = 0;
	float DamageTaken = 0.f;

protected:
	virtual void BeginPlay() override;

private:
	void UpdatePlayerAim();
	void DriveBot(float DeltaSeconds);
	void MoveAlongPath(const FVector2D& To, float DeltaSeconds);
	bool CastSpell(TSubclassOf<class URDAbility> Ability);
	void BuildInput();

	void OnMove(const FInputActionValue& Value);
	void OnMoveStop(const FInputActionValue& Value) { MoveInput = FVector2D::ZeroVector; }
	void OnStickAim(const FInputActionValue& Value) { StickAim = Value.Get<FVector2D>(); }
	void OnBolt(const FInputActionValue& Value);
	void OnWard(const FInputActionValue& Value);
	void OnDash(const FInputActionValue& Value);
	void OnRestart(const FInputActionValue& Value);

	UPROPERTY(VisibleAnywhere) TObjectPtr<USpringArmComponent> Arm;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UCameraComponent> Camera;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UPointLightComponent> RuneLight;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UPointLightComponent> WardLight;

	UPROPERTY() TObjectPtr<UInputMappingContext> Mapping;
	UPROPERTY() TObjectPtr<UInputAction> MoveAction;
	UPROPERTY() TObjectPtr<UInputAction> AimAction;
	UPROPERTY() TObjectPtr<UInputAction> BoltAction;
	UPROPERTY() TObjectPtr<UInputAction> WardAction;
	UPROPERTY() TObjectPtr<UInputAction> DashAction;
	UPROPERTY() TObjectPtr<UInputAction> RestartAction;

	ERDBotMode Bot = ERDBotMode::None;
	const TCHAR* LastReason = TEXT("");
	FVector2D MoveInput = FVector2D::ZeroVector;   // x = right (D), y = forward (W)
	FVector2D StickAim = FVector2D::ZeroVector;
	FVector2D Aim = FVector2D::ZeroVector;
	bool bTestAim = false;
	FVector2D DashDirOverride = FVector2D::ZeroVector;
	FVector DashVelocity = FVector::ZeroVector;
	float DashLeft = 0.f;
	TArray<FVector> Path;
	FVector2D PathGoal = FVector2D(1e9f, 1e9f);
	float RepathTimer = 0.f;
};
