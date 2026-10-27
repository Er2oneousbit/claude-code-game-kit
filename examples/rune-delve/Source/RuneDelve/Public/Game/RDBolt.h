// ---------------------------------------------------------------------------
// RDBolt.h
// Purpose : The rune bolt: a fast glowing projectile that damages the first orc it hits and stops at walls
//           and columns.
// Usage   : spawned by ARDMage::FireBolt, then Launch(Mage, Direction, Numbers)
// Notes   : Damage goes through GAS (URDEffect_Damage from the mage's ASC), so a staggered orc takes the
//           multiplier in URDAttributeSet. Dead orcs have no collision, so bolts fly over corpses.
//           The bolt blocks pawns (that is how it hits orcs), so it and its caster ignore each other when moving:
//           Launch makes the bolt ignore the mage, ARDMage::FireBolt the mage ignore the bolt.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 EndPlay drops the bolt from the caster's move-ignore list
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RDBolt.generated.h"

class ARDMage;
class UPointLightComponent;
class UProjectileMovementComponent;
class USphereComponent;
class UStaticMeshComponent;
struct FRDNumbers;

UCLASS()
class RUNEDELVE_API ARDBolt : public AActor
{
	GENERATED_BODY()

public:
	ARDBolt();
	void Launch(ARDMage* Caster, const FVector& Direction, const FRDNumbers& N);

protected:
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	UFUNCTION()
	void OnHit(UPrimitiveComponent* HitComp, AActor* Other, UPrimitiveComponent* OtherComp, FVector Impulse, const FHitResult& Hit);

	UPROPERTY(VisibleAnywhere) TObjectPtr<USphereComponent> Collision;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UStaticMeshComponent> Orb;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UPointLightComponent> Glow;
	UPROPERTY(VisibleAnywhere) TObjectPtr<UProjectileMovementComponent> Movement;

	TWeakObjectPtr<ARDMage> Mage;
	float Damage = 0.f;
};
