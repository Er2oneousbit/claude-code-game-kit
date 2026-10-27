// ---------------------------------------------------------------------------
// RDDungeon.cpp
// Purpose : See RDDungeon.h.
//
// Pseudocode:
//   one big floor collider; for each piece in FRDLevel::Pieces:
//     floor -> floor instance | wall/column/prop -> instance + box collider | gate -> skeletal gate mesh
//   one collider per gate across its three tiles; a light per room; a post-process volume with fixed exposure;
//   the dungeon ambience, a looping 2D sound (build_content.py sets the wave's loop flag)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Game/RDDungeon.h"

#include "Components/BoxComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/PostProcessComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Core/RDLevel.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Game/RDCommon.h"
#include "Kismet/GameplayStatics.h"
#include "NavigationSystem.h"
#include "Sound/SoundBase.h"

ARDDungeon::ARDDungeon()
{
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
}

UInstancedStaticMeshComponent* ARDDungeon::Meshes(const TCHAR* Name)
{
	TObjectPtr<UInstancedStaticMeshComponent>& Set = MeshSets.FindOrAdd(FName(Name));
	if (!Set)
	{
		Set = NewObject<UInstancedStaticMeshComponent>(this);
		Set->SetupAttachment(RootComponent);
		Set->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Set->SetCanEverAffectNavigation(false);
		if (UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *RDAssets::Object(RDAssets::Dungeon, Name)))
		{
			Set->SetStaticMesh(Mesh);
		}
		else
		{
			UE_LOG(LogRuneDelve, Error, TEXT("missing dungeon mesh %s (run python tools/dev.py exec tools/unreal/build_content.py)"), Name);
		}
		Set->RegisterComponent();
	}
	return Set;
}

UBoxComponent* ARDDungeon::AddBlocker(const FVector& Center, const FVector& Extent)
{
	UBoxComponent* Box = NewObject<UBoxComponent>(this);
	Box->SetupAttachment(RootComponent);
	Box->SetBoxExtent(Extent);
	Box->SetWorldLocation(Center);
	Box->SetCollisionProfileName(TEXT("BlockAll"));
	Box->SetCanEverAffectNavigation(true);
	Box->SetHiddenInGame(true);
	Box->RegisterComponent();
	return Box;
}

void ARDDungeon::Build()
{
	const float T = FRDLevel::Tile;
	const float S = FRDLevel::WorldScale;
	const FBox Nav = FRDLevel::NavBounds();
	AddBlocker(FVector(Nav.GetCenter().X, Nav.GetCenter().Y, -10.f), FVector(Nav.GetExtent().X, Nav.GetExtent().Y, 10.f));

	USkeletalMesh* GateMesh = LoadObject<USkeletalMesh>(nullptr, *RDAssets::Object(RDAssets::Dungeon, TEXT("gate")));
	TArray<FRDPiece> Pieces;
	FRDLevel::Pieces(Pieces);
	for (const FRDPiece& P : Pieces)
	{
		const FVector2D At = FRDLevel::TileToWorld(P.X, P.Y);
		const FTransform Place(FRotator(0.f, P.Yaw, 0.f), FVector(At, 0.f), FVector(S));
		switch (P.Kind)
		{
		case ERDPiece::Floor:
			Meshes(TEXT("floor"))->AddInstance(Place, true);
			break;
		case ERDPiece::Wall:
			Meshes(TEXT("wall"))->AddInstance(Place, true);
			AddBlocker(FVector(At, WallHeight * 0.5f), FVector(T * 0.5f, T * 0.5f, WallHeight * 0.5f));
			break;
		case ERDPiece::Column:
			Meshes(TEXT("column"))->AddInstance(Place, true);
			AddBlocker(FVector(At, WallHeight * 0.5f), FVector(T * 0.25f, T * 0.25f, WallHeight * 0.5f));
			break;
		case ERDPiece::Barrel:
			Meshes(TEXT("barrel"))->AddInstance(Place, true);
			AddBlocker(FVector(At, 50.f), FVector(T * 0.26f, T * 0.26f, 50.f));
			break;
		case ERDPiece::Rocks:
			Meshes(TEXT("rocks"))->AddInstance(Place, true);
			AddBlocker(FVector(At, 50.f), FVector(T * 0.45f, T * 0.45f, 50.f));
			break;
		case ERDPiece::Gate:
			if (GateMesh)
			{
				USkeletalMeshComponent* G = NewObject<USkeletalMeshComponent>(this);
				G->SetupAttachment(RootComponent);
				G->SetSkeletalMeshAsset(GateMesh);
				G->SetWorldTransform(FTransform(FRotator(0.f, P.Yaw, 0.f), FVector(At, 0.f), FVector(GateWidthScale, S, S)));
				G->SetCollisionEnabled(ECollisionEnabled::NoCollision);
				G->SetCanEverAffectNavigation(false);
				G->SetAnimationMode(EAnimationMode::AnimationSingleNode);
				G->RegisterComponent();
				GateMeshes.Add(G);
				GateOfMesh.Add(P.Gate);
			}
			break;
		}
	}
	for (int32 G = 0; G < GateCount; ++G)
	{
		const FVector2D C = FRDLevel::GateCenter(G);
		GateBlockers.Add(AddBlocker(FVector(C, WallHeight * 0.5f),
		                            FVector(T * 0.5f, T * (FRDLevel::GateHalf + 0.5f), WallHeight * 0.5f)));
	}
	AddLights();
	if (USoundBase* Ambience = LoadObject<USoundBase>(nullptr, *RDAssets::Object(RDAssets::Audio, TEXT("dungeon-ambience"))))
	{
		UGameplayStatics::SpawnSound2D(this, Ambience, AmbienceVolume);
	}
}

void ARDDungeon::AddLights()
{
	for (int32 R = 0; R < FRDLevel::RoomCount; ++R)
	{
		UPointLightComponent* L = NewObject<UPointLightComponent>(this);
		L->SetupAttachment(RootComponent);
		L->SetWorldLocation(FVector(FRDLevel::RoomInterior(R).GetCenter(), 700.f));
		L->SetLightColor(FLinearColor(1.f, 0.72f, 0.45f));
		L->SetIntensity(RoomLightIntensity);
		L->SetAttenuationRadius(2200.f);
		L->SetCastShadows(true);
		L->RegisterComponent();
	}
	// Fixed exposure: auto exposure would brighten the dark rooms and wash out the rune and wind-up lights
	UPostProcessComponent* Post = NewObject<UPostProcessComponent>(this);
	Post->SetupAttachment(RootComponent);
	Post->bUnbound = true;
	Post->Settings.bOverride_AutoExposureMethod = true;
	Post->Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Post->Settings.bOverride_AutoExposureBias = true;
	Post->Settings.AutoExposureBias = 10.f;
	Post->RegisterComponent();
}

void ARDDungeon::OpenGate(int32 Gate)
{
	if (Gate < 0 || Gate >= GateCount || bGateOpen[Gate])
	{
		return;
	}
	bGateOpen[Gate] = true;
	// The Kenney gate's own animation keeps the bars in the doorway as seen from the top-down camera, so an
	// open gate simply disappears (the door sound sells it)
	for (int32 I = 0; I < GateMeshes.Num(); ++I)
	{
		if (GateOfMesh[I] == Gate)
		{
			GateMeshes[I]->SetVisibility(false);
		}
	}
	UBoxComponent* Blocker = GateBlockers[Gate];
	Blocker->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	if (UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(GetWorld()))
	{
		Nav->UpdateComponentInNavOctree(*Blocker);
	}
	if (USoundBase* Sound = LoadObject<USoundBase>(nullptr, *RDAssets::Object(RDAssets::Audio, TEXT("door-open"))))
	{
		UGameplayStatics::PlaySoundAtLocation(this, Sound, FVector(FRDLevel::GateCenter(Gate), 100.f));
	}
}
