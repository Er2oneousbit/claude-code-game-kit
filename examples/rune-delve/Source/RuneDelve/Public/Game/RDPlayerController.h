// ---------------------------------------------------------------------------
// RDPlayerController.h
// Purpose : Shows the mouse cursor (aim) and keeps game input focused on the world.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "RDPlayerController.generated.h"

UCLASS()
class RUNEDELVE_API ARDPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	ARDPlayerController();

protected:
	virtual void BeginPlay() override;
};
