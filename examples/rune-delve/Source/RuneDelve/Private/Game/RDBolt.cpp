// ---------------------------------------------------------------------------
// RDBolt.cpp
// Purpose : See RDBolt.h.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix: the caster ignores its bolt both ways (the mage adds it, EndPlay removes it)
// ---------------------------------------------------------------------------
#include "Game/RDBolt.h"

#include "Abilities/RDEffects.h"
#include "Components/PointLightComponent.h"
#include "Components/SphereComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Core/RDNumbers.h"
#include "Engine/StaticMesh.h"
#include "Game/RDMage.h"
#include "Game/RDOrc.h"
#include "GameFramework/ProjectileMovementComponent.h"
#include "UObject/ConstructorHelpers.h"

ARDBolt::ARDBolt()
{
	Collision = CreateDefaultSubobject<USphereComponent>(TEXT("Collision"));
	Collision->InitSphereRadius(18.f);
	Collision->SetCollisionObjectType(ECC_WorldDynamic);
	Collision->SetCollisionResponseToAllChannels(ECR_Block);
	Collision->SetCollisionResponseToChannel(ECC_Camera, ECR_Ignore);
	Collision->SetCollisionResponseToChannel(ECC_Visibility, ECR_Ignore);
	Collision->SetNotifyRigidBodyCollision(true);
	Collision->CanCharacterStepUpOn = ECB_No;
	RootComponent = Collision;

	static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	Orb = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Orb"));
	Orb->SetupAttachment(Collision);
	Orb->SetStaticMesh(Sphere.Object);
	Orb->SetRelativeScale3D(FVector(0.22f));
	Orb->SetCollisionEnabled(ECollisionEnabled::NoCollision);

	Glow = CreateDefaultSubobject<UPointLightComponent>(TEXT("Glow"));
	Glow->SetupAttachment(Collision);
	Glow->SetLightColor(FLinearColor(0.3f, 0.6f, 1.f));
	Glow->SetIntensity(6000.f);
	Glow->SetAttenuationRadius(300.f);
	Glow->SetCastShadows(false);

	Movement = CreateDefaultSubobject<UProjectileMovementComponent>(TEXT("Movement"));
	Movement->ProjectileGravityScale = 0.f;
	Movement->bRotationFollowsVelocity = true;
	Movement->bAutoActivate = false;
}

void ARDBolt::Launch(ARDMage* Caster, const FVector& Direction, const FRDNumbers& N)
{
	Mage = Caster;
	Damage = N.BoltDamage;
	Collision->IgnoreActorWhenMoving(Caster, true);
	Collision->OnComponentHit.AddDynamic(this, &ARDBolt::OnHit);
	Movement->InitialSpeed = N.BoltSpeed;
	Movement->MaxSpeed = N.BoltSpeed;
	Movement->Velocity = Direction.GetSafeNormal() * N.BoltSpeed;
	Movement->Activate();
	SetLifeSpan(N.BoltRange / FMath::Max(1.f, N.BoltSpeed));
}

void ARDBolt::EndPlay(const EEndPlayReason::Type Reason)
{
	if (Mage.IsValid())
	{
		Mage->MoveIgnoreActorRemove(this);
	}
	Super::EndPlay(Reason);
}

void ARDBolt::OnHit(UPrimitiveComponent* HitComp, AActor* Other, UPrimitiveComponent* OtherComp, FVector Impulse, const FHitResult& Hit)
{
	ARDOrc* Orc = Cast<ARDOrc>(Other);
	if (Orc && Orc->IsAlive() && Mage.IsValid())
	{
		Mage->ApplyInstant(URDEffect_Damage::StaticClass(), Damage, Orc->GetAbilitySystemComponent());
	}
	Destroy();
}
