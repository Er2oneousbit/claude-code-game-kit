// ---------------------------------------------------------------------------
// DotworkTileAnimatorSubsystem.h
// Purpose : Plays the animated tiles of every Dotwork tile map in a game world (#286): at BeginPlay it binds an
//           FDotworkTilePlayer to each PaperTileMapComponent whose tiles animate, and advances them every tick.
// Usage   : Nothing to call for maps placed in the level. A map spawned later:
//             GetWorld()->GetSubsystem<UDotworkTileAnimatorSubsystem>()->Register(TileMapComponent);
// Notes   : Game and PIE worlds only (an editor viewport shows the first frame, as Paper2D's own editor does).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "GameKitDotworkTiles.h"
#include "DotworkTileAnimatorSubsystem.generated.h"

class UPaperTileMapComponent;

UCLASS()
class GAMEKITDOTWORK_API UDotworkTileAnimatorSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** Plays this component's animated tiles (true when it has some). */
	UFUNCTION(BlueprintCallable, Category = "Dotwork")
	bool Register(UPaperTileMapComponent* Component);

	/** How many tile maps are playing. */
	UFUNCTION(BlueprintPure, Category = "Dotwork")
	int32 NumPlaying() const { return Players.Num(); }

	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

protected:
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
	TArray<FDotworkTilePlayer> Players;
};
