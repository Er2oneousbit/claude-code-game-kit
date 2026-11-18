// ---------------------------------------------------------------------------
// DotworkTileAnimatorSubsystem.cpp
// Purpose : The world subsystem that plays every Dotwork tile map's animated tiles (#286); see the header.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "DotworkTileAnimatorSubsystem.h"

#include "EngineUtils.h"
#include "PaperTileMapComponent.h"

DEFINE_LOG_CATEGORY_STATIC(LogDotworkTiles, Log, All);

bool UDotworkTileAnimatorSubsystem::Register(UPaperTileMapComponent* Component)
{
	for (const FDotworkTilePlayer& P : Players)
	{
		if (Component && P.Component() == Component)
		{
			return true;   // already playing
		}
	}
	FDotworkTilePlayer Player;
	if (!Player.Bind(Component))
	{
		return false;
	}
	UE_LOG(LogDotworkTiles, Log, TEXT("DOTWORK_TILES %s: %d animated cell(s)"), *GetNameSafe(Component->GetOwner()), Player.Cells().Num());
	Players.Add(MoveTemp(Player));
	return true;
}

void UDotworkTileAnimatorSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	for (TActorIterator<AActor> It(&InWorld); It; ++It)
	{
		TArray<UPaperTileMapComponent*> Maps;
		It->GetComponents(Maps);
		for (UPaperTileMapComponent* Map : Maps)
		{
			Register(Map);
		}
	}
}

void UDotworkTileAnimatorSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	Players.RemoveAll([](const FDotworkTilePlayer& P) { return !P.IsBound(); });
	for (FDotworkTilePlayer& P : Players)
	{
		P.Advance(DeltaTime);
	}
}

TStatId UDotworkTileAnimatorSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UDotworkTileAnimatorSubsystem, STATGROUP_Tickables);
}

bool UDotworkTileAnimatorSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}
