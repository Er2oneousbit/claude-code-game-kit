// ---------------------------------------------------------------------------
// RDDungeon.h
// Purpose : Builds the dungeon from FRDLevel at runtime: instanced Kenney meshes for looks, box colliders
//           for walking, bolts and sight (and so for the NavMesh), gates, lights and fixed exposure.
// Usage   : ARDGameMode spawns one and calls Build(); OpenGate(G) when room G is cleared
// Notes   : Visuals and collision are separate on purpose: the boxes are exact tile sizes, so the NavMesh,
//           AI sight and the tests never depend on how a Kenney mesh was modelled. Gates are Kenney skeletal
//           meshes, hidden when they open (their own animation does not read from above); opening also drops
//           the collider, and the NavMesh (RuntimeGeneration=Dynamic in DefaultEngine.ini) rebuilds the doorway.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RDDungeon.generated.h"

class UBoxComponent;
class UInstancedStaticMeshComponent;
class USkeletalMeshComponent;

UCLASS()
class RUNEDELVE_API ARDDungeon : public AActor
{
	GENERATED_BODY()

public:
	static constexpr int32 GateCount = 2;
	static constexpr float WallHeight = 300.f;     // collider height (the mesh is 220 cm)
	static constexpr float RoomLightIntensity = 60000.f;
	static constexpr float GateWidthScale = 2.5f;  // the 80 cm Kenney gate fills a 200 cm tile
	static constexpr float AmbienceVolume = 0.5f;  // the dungeon's drip and rumble, under the fight

	ARDDungeon();
	void Build();
	void OpenGate(int32 Gate);
	bool IsGateOpen(int32 Gate) const { return Gate >= 0 && Gate < GateCount && bGateOpen[Gate]; }

private:
	UInstancedStaticMeshComponent* Meshes(const TCHAR* Name);
	UBoxComponent* AddBlocker(const FVector& Center, const FVector& Extent);
	void AddLights();

	UPROPERTY() TMap<FName, TObjectPtr<UInstancedStaticMeshComponent>> MeshSets;
	UPROPERTY() TArray<TObjectPtr<UBoxComponent>> GateBlockers;      // index = gate
	UPROPERTY() TArray<TObjectPtr<USkeletalMeshComponent>> GateMeshes;
	TArray<int32> GateOfMesh;
	bool bGateOpen[GateCount] = {false, false};
};
