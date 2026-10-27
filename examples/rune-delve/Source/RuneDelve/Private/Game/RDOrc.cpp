// ---------------------------------------------------------------------------
// RDOrc.cpp
// Purpose : See RDOrc.h.
//
// Pseudocode (each tick):
//   senses = (perception fired this tick and the mage is in this orc's room) or the orc was hurt this tick
//   out = brain.Tick(dt, alive, senses, distance, staggered tag)
//   alerted -> "!" and a grunt; move -> controller chases the mage; windup -> face the mage, glow red,
//   weapon raised, and ContactDelay before the swing lands the attack clip starts so its contact frame meets it
//   strike -> if the mage is still within Reach * StrikeSlack and in front: melee damage effect
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fixes: being hurt wakes the orc even when the mage is outside its room (a bolt
//           through an open gate could kill a sleeping orc that never woke); the attack clip is timed so its
//           contact frame lands with the damage (the hit used to land on the clip's first frame)
// ---------------------------------------------------------------------------
#include "Game/RDOrc.h"

#include "Abilities/RDEffects.h"
#include "Abilities/RDTags.h"
#include "AIController.h"
#include "Components/CapsuleComponent.h"
#include "Components/PointLightComponent.h"
#include "TimerManager.h"
#include "Game/RDCommon.h"
#include "Game/RDGameMode.h"
#include "Game/RDMage.h"
#include "Game/RDOrcController.h"
#include "Game/RDTuning.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Navigation/PathFollowingComponent.h"

ARDOrc::ARDOrc()
{
	SetupBody(TEXT("character-orc"));
	AIControllerClass = ARDOrcController::StaticClass();
	AutoPossessAI = EAutoPossessAI::Spawned;
	GetCharacterMovement()->bOrientRotationToMovement = true;
	GetCharacterMovement()->RotationRate = FRotator(0.f, 540.f, 0.f);
	bUseControllerRotationYaw = false;

	Telegraph = CreateDefaultSubobject<UPointLightComponent>(TEXT("Telegraph"));
	Telegraph->SetupAttachment(RootComponent);
	Telegraph->SetRelativeLocation(FVector(30.f, 0.f, 60.f));
	Telegraph->SetLightColor(FLinearColor(1.f, 0.12f, 0.05f));
	Telegraph->SetAttenuationRadius(320.f);
	Telegraph->SetIntensity(0.f);
	Telegraph->SetCastShadows(false);
}

void ARDOrc::Setup(const FRDSpawn& Spawn, const FRDOrcStats& InStats)
{
	Stats = InStats;
	Room = Spawn.Room;
	bWarden = Spawn.bWarden;
	Brain.Emplace(Stats);
	if (bWarden)
	{
		GetMesh()->SetRelativeScale3D(FVector(FRDLevel::WorldScale * WardenScale));
		GetCapsuleComponent()->SetCapsuleSize(CapsuleRadius * WardenScale, CapsuleHalfHeight * WardenScale);
		GetMesh()->SetRelativeLocation(FVector(0.f, 0.f, -CapsuleHalfHeight * WardenScale));
		Telegraph->SetAttenuationRadius(480.f);
	}
}

void ARDOrc::BeginPlay()
{
	Super::BeginPlay();
	InitStats(Stats.Health, 0.f);
	GetCharacterMovement()->MaxWalkSpeed = Stats.Speed;
	PlayAnim(TEXT("idle"), true);
}

void ARDOrc::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	AlertMark = FMath::Max(0.f, AlertMark - DeltaSeconds);
	ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>();
	ARDMage* Mage = Game ? Game->GetMage() : nullptr;
	if (!Brain.IsSet() || !Mage)
	{
		return;
	}
	const bool bWasDead = Brain->GetState() == ERDOrcState::Dead;
	const bool bMageHere = Mage->IsAlive() && FRDLevel::RoomOf(Mage->Ground()) == Room;
	const float Dist = FVector2D::Distance(Ground(), Mage->Ground());
	// The room gate is for sight and hearing only: damage always wakes the orc, wherever the shooter stands
	const bool bSenses = (bSensedThisTick && bMageHere) || bHurtThisTick;
	const FRDOrcOutput Out = Brain->Tick(FRDOrcInput{DeltaSeconds, IsAlive(), bSenses, Dist, HasTag(RDTags::State_Staggered)});
	bSensedThisTick = false;
	bHurtThisTick = false;
	if (bWasDead)
	{
		return;
	}

	AAIController* Ai = Cast<AAIController>(GetController());
	if (Out.bAlerted)
	{
		AlertMark = AlertMarkSeconds;
		PlaySound(TEXT("orc-alert"), 0.6f);
		RD_MARK(TEXT("ORC_ALERT room %d"), Room + 1);
	}
	if (Ai)
	{
		if (Out.bMove && Mage->IsAlive())
		{
			if (Ai->GetMoveStatus() != EPathFollowingStatus::Moving)
			{
				Ai->MoveToActor(Mage, Stats.Reach * 0.5f, true, true, false);
			}
		}
		else if (Ai->GetMoveStatus() == EPathFollowingStatus::Moving)
		{
			Ai->StopMovement();
		}
	}

	const ERDOrcState State = Brain->GetState();
	if (State == ERDOrcState::Windup)
	{
		const FVector ToMage = (Mage->GetActorLocation() - GetActorLocation()).GetSafeNormal2D();
		SetActorRotation(FMath::RInterpTo(GetActorRotation(), ToMage.Rotation(), DeltaSeconds, 12.f));
		Telegraph->SetIntensity(TelegraphIntensity * FMath::Clamp(Brain->GetStateTime() / Stats.Windup, 0.25f, 1.f));
		const float Left = Brain->WindupLeft();
		if (Left > ContactDelay)
		{
			PlayAnim(TEXT("holding-right"), false);
		}
		else if (CurrentAnim != FName(SwingAnim))
		{
			StartSwingClip(ContactDelay - Left);
		}
	}
	else
	{
		Telegraph->SetIntensity(0.f);
	}
	if (Out.bStrike)
	{
		Strike(Mage);
	}
	switch (State)
	{
	case ERDOrcState::Hunt:
		PlayAnim(TEXT("walk"), true, Stats.Speed / 300.f);
		break;
	case ERDOrcState::Staggered:
		PlayAnim(TEXT("emote-no"), true, 0.6f);
		break;
	case ERDOrcState::Sleep:
		PlayAnim(TEXT("idle"), true);
		break;
	default:
		break;
	}
}

void ARDOrc::StartSwingClip(float Position)
{
	PlayAnim(SwingAnim, false, 1.f, true);
	GetMesh()->SetPosition(FMath::Max(0.f, Position), false);   // catch up on the part of a frame already gone
}

void ARDOrc::Strike(ARDMage* Mage)
{
	if (CurrentAnim != FName(SwingAnim))
	{
		StartSwingClip(ContactDelay);   // a wind-up shorter than ContactDelay: show the contact frame at least
	}
	PlaySound(bWarden ? TEXT("warden-swing") : TEXT("orc-swing"), 0.6f);
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	const FVector ToMage = Mage->GetActorLocation() - GetActorLocation();
	const bool bInReach = ToMage.Size2D() <= Stats.Reach * N.StrikeSlack;
	const bool bInFront = FVector::DotProduct(GetActorForwardVector(), ToMage.GetSafeNormal2D()) > 0.2f;
	if (Mage->IsAlive() && bInReach && bInFront)
	{
		ApplyInstant(URDEffect_Damage::StaticClass(), Stats.Damage, Mage->GetAbilitySystemComponent(), true);
	}
}

void ARDOrc::OnHurt(float Damage, ARDCharacterBase* Source)
{
	PlaySound(TEXT("orc-hurt"), 0.7f);
	bHurtThisTick = true;   // being shot wakes you up, even from outside the room
}

void ARDOrc::OnZeroHealth(ARDCharacterBase* Killer)
{
	PlaySound(TEXT("orc-die"));
	PlayAnim(TEXT("die"), false, 1.f, true);
	Telegraph->SetIntensity(0.f);
	GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	GetCharacterMovement()->DisableMovement();
	if (AAIController* Ai = Cast<AAIController>(GetController()))
	{
		Ai->StopMovement();
	}
	if (ARDGameMode* Game = GetWorld()->GetAuthGameMode<ARDGameMode>())
	{
		Game->OnOrcDied(this);
	}
	// The Kenney die clip ends upright, which reads as a living orc: fade out instead
	FTimerHandle Vanish;
	GetWorldTimerManager().SetTimer(Vanish, FTimerDelegate::CreateWeakLambda(this, [this]() { SetActorHiddenInGame(true); }),
	                                CorpseSeconds, false);
}

FRDBotOrc ARDOrc::ToBot() const
{
	FRDBotOrc B;
	B.Pos = Ground();
	B.Vel = FVector2D(GetVelocity());
	B.State = GetState();
	B.WindupLeft = WindupLeft();
	B.Reach = Stats.Reach;
	B.Health = GetHealth();
	B.bStaggered = HasTag(RDTags::State_Staggered);
	return B;
}
