// ---------------------------------------------------------------------------
// RDOrcController.h
// Purpose : The orc's AI controller: AI Perception with a sight cone and hearing (bolt noise), and NavMesh
//           path following for the chase. It tells the orc when it perceives the mage; the orc's brain decides.
// Usage   : ARDOrc sets AIControllerClass to this; nothing else to do
// Notes   : Sight radius and angle come from URDTuning when the orc is possessed. Bolts report noise with
//           UAISense_Hearing::ReportNoiseEvent (range = BoltNoise). Walls and columns block sight
//           (their colliders block the Visibility channel).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "AIController.h"
#include "Perception/AIPerceptionTypes.h"
#include "RDOrcController.generated.h"

class UAISenseConfig_Hearing;
class UAISenseConfig_Sight;

UCLASS()
class RUNEDELVE_API ARDOrcController : public AAIController
{
	GENERATED_BODY()

public:
	ARDOrcController();

protected:
	virtual void OnPossess(APawn* InPawn) override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UFUNCTION()
	void OnPerceived(AActor* Actor, FAIStimulus Stimulus);

	UPROPERTY()
	TObjectPtr<UAISenseConfig_Sight> Sight;
	UPROPERTY()
	TObjectPtr<UAISenseConfig_Hearing> Hearing;
};
