// ---------------------------------------------------------------------------
// RDOrcController.cpp
// Purpose : See RDOrcController.h.
// Notes   : Perception events arrive when a sense changes; Tick also re-checks "currently seen" so an orc
//           that already sees the mage keeps reporting it every frame (the brain only needs it once, but
//           a mage who walks out of the room and back must be seen again).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Game/RDOrcController.h"

#include "Game/RDMage.h"
#include "Game/RDOrc.h"
#include "Game/RDTuning.h"
#include "Perception/AIPerceptionComponent.h"
#include "Perception/AISenseConfig_Hearing.h"
#include "Perception/AISenseConfig_Sight.h"
#include "Perception/AISense_Sight.h"

ARDOrcController::ARDOrcController()
{
	PrimaryActorTick.bCanEverTick = true;
	SetPerceptionComponent(*CreateDefaultSubobject<UAIPerceptionComponent>(TEXT("Perception")));
	Sight = CreateDefaultSubobject<UAISenseConfig_Sight>(TEXT("Sight"));
	Sight->DetectionByAffiliation.bDetectEnemies = true;
	Sight->DetectionByAffiliation.bDetectNeutrals = true;
	Sight->DetectionByAffiliation.bDetectFriendlies = true;
	Hearing = CreateDefaultSubobject<UAISenseConfig_Hearing>(TEXT("Hearing"));
	Hearing->DetectionByAffiliation.bDetectEnemies = true;
	Hearing->DetectionByAffiliation.bDetectNeutrals = true;
	Hearing->DetectionByAffiliation.bDetectFriendlies = true;
	GetPerceptionComponent()->ConfigureSense(*Sight);
	GetPerceptionComponent()->ConfigureSense(*Hearing);
	GetPerceptionComponent()->SetDominantSense(UAISense_Sight::StaticClass());
}

void ARDOrcController::OnPossess(APawn* InPawn)
{
	Super::OnPossess(InPawn);
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	Sight->SightRadius = N.OrcSight;
	Sight->LoseSightRadius = N.OrcSight + 200.f;
	Sight->PeripheralVisionAngleDegrees = N.OrcSightHalfAngle;
	Hearing->HearingRange = N.BoltNoise;
	GetPerceptionComponent()->ConfigureSense(*Sight);
	GetPerceptionComponent()->ConfigureSense(*Hearing);
	GetPerceptionComponent()->OnTargetPerceptionUpdated.AddUniqueDynamic(this, &ARDOrcController::OnPerceived);
}

void ARDOrcController::OnPerceived(AActor* Actor, FAIStimulus Stimulus)
{
	ARDOrc* Orc = Cast<ARDOrc>(GetPawn());
	const bool bMage = Cast<ARDMage>(Actor) || (Actor && Cast<ARDMage>(Actor->GetInstigator()));
	if (Orc && bMage && Stimulus.WasSuccessfullySensed())
	{
		Orc->NotifySensed();
	}
}

void ARDOrcController::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ARDOrc* Orc = Cast<ARDOrc>(GetPawn());
	if (!Orc)
	{
		return;
	}
	TArray<AActor*> Seen;
	GetPerceptionComponent()->GetCurrentlyPerceivedActors(UAISense_Sight::StaticClass(), Seen);
	for (AActor* A : Seen)
	{
		if (Cast<ARDMage>(A))
		{
			Orc->NotifySensed();
		}
	}
}
