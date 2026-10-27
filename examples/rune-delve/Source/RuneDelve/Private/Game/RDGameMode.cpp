// ---------------------------------------------------------------------------
// RDGameMode.cpp
// Purpose : See RDGameMode.h.
//
// Pseudocode:
//   StartPlay: fixed step if asked -> build dungeon -> spawn orcs for the seed -> READY, DELVE_START
//   Tick: time; the mage's room; a room whose orcs are all dead is cleared (marker, heal, open its gate;
//         the last one ends the delve); timeout; screenshots; packaged autoplay quits after the end
//   BotSnapshot: the living orcs where they stand now (in the mage's room, or in a doorway of it)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 review fix: the bots saw orcs by spawn room, so an orc that chased the mage through a
//           gate was invisible to them; they now see orcs by the room (or doorway) the orc stands in
// ---------------------------------------------------------------------------
#include "Game/RDGameMode.h"

#include "Abilities/RDEffects.h"
#include "Abilities/RDTags.h"
#include "Engine/Engine.h"
#include "Game/RDCommon.h"
#include "Game/RDDungeon.h"
#include "Game/RDHUD.h"
#include "Game/RDMage.h"
#include "Game/RDOrc.h"
#include "Game/RDPlayerController.h"
#include "Game/RDTuning.h"
#include "HAL/PlatformMisc.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#include "Misc/Paths.h"
#include "UnrealClient.h"

ARDGameMode::ARDGameMode()
{
	PrimaryActorTick.bCanEverTick = true;
	DefaultPawnClass = ARDMage::StaticClass();
	PlayerControllerClass = ARDPlayerController::StaticClass();
	HUDClass = ARDHUD::StaticClass();
}

void ARDGameMode::StartPlay()
{
	const FRDLaunchOptions& O = FRDLaunchOptions::Get();
	if (O.bFixedFps)
	{
		FApp::SetUseFixedTimeStep(true);
		FApp::SetFixedDeltaTime(1.0 / 60.0);
		FApp::SetBenchmarking(true);   // do not wait for real time between frames
	}
	Dungeon = GetWorld()->SpawnActor<ARDDungeon>();
	Dungeon->Build();
	SpawnOrcs();
	Super::StartPlay();
	RD_MARK(TEXT("READY %s"), *FString(FApp::GetProjectName()));
	RD_MARK(TEXT("DELVE_START seed %d bot %s"), O.Seed, RDBot::Name(O.Bot));
}

void ARDGameMode::SpawnOrcs()
{
	const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
	TArray<FRDSpawn> Spawns;
	FRDLevel::Orcs(FRDLaunchOptions::Get().Seed, Spawns);
	for (const FRDSpawn& S : Spawns)
	{
		const float Scale = S.bWarden ? ARDOrc::WardenScale : 1.f;
		const FTransform At(FRotator(0.f, S.Yaw, 0.f), FVector(S.Pos, ARDCharacterBase::CapsuleHalfHeight * Scale + 5.f));
		ARDOrc* Orc = GetWorld()->SpawnActorDeferred<ARDOrc>(ARDOrc::StaticClass(), At, nullptr, nullptr,
		                                                     ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn);
		Orc->Setup(S, S.bWarden ? N.Warden : N.Grunt);
		Orc->FinishSpawning(At);
		Orcs.Add(Orc);
	}
}

ARDMage* ARDGameMode::GetMage() const
{
	const APlayerController* Pc = GetWorld()->GetFirstPlayerController();
	return Pc ? Cast<ARDMage>(Pc->GetPawn()) : nullptr;
}

int32 ARDGameMode::RoomsCleared() const
{
	int32 N = 0;
	for (bool b : bCleared)
	{
		N += b ? 1 : 0;
	}
	return N;
}

void ARDGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ToastLeft = FMath::Max(0.f, ToastLeft - DeltaSeconds);
	Record();
	if (Outcome != ERDOutcome::Playing)
	{
		EndTimer += DeltaSeconds;
		if (FRDLaunchOptions::Get().bQuitAtEnd && EndTimer >= QuitDelaySeconds)
		{
			FPlatformMisc::RequestExitWithStatus(false, Outcome == ERDOutcome::Cleared ? 0 : 3);
		}
		return;
	}
	Elapsed += DeltaSeconds;
	if (ARDMage* Mage = GetMage())
	{
		const int32 R = FRDLevel::RoomOf(Mage->Ground());
		CurrentRoom = R >= 0 ? R : CurrentRoom;
	}
	UpdateRooms();
	if (Outcome == ERDOutcome::Playing && Elapsed >= FRDLaunchOptions::Get().MaxSeconds)
	{
		Finish(ERDOutcome::Timeout, TEXT("TIMEOUT"));
	}
}

void ARDGameMode::UpdateRooms()
{
	for (int32 R = 0; R < FRDLevel::RoomCount; ++R)
	{
		if (bCleared[R])
		{
			continue;
		}
		bool bAnyAlive = false;
		for (const ARDOrc* O : Orcs)
		{
			bAnyAlive |= O && O->GetRoom() == R && O->IsAlive();
		}
		if (bAnyAlive)
		{
			continue;
		}
		bCleared[R] = true;
		RD_MARK(TEXT("ROOM_CLEARED %d/%d at %.1fs"), RoomsCleared(), FRDLevel::RoomCount, Elapsed);
		if (ARDMage* Mage = GetMage())
		{
			Mage->ApplyInstant(URDEffect_Heal::StaticClass(), GetDefault<URDTuning>()->Numbers().RoomClearHeal,
			                   Mage->GetAbilitySystemComponent());
		}
		if (R < ARDDungeon::GateCount)
		{
			Dungeon->OpenGate(R);
			ShowToast(TEXT("Room cleared: the gate opens"));
		}
		else
		{
			Finish(ERDOutcome::Cleared, TEXT("DELVE_COMPLETE"));
		}
	}
}

void ARDGameMode::OnOrcDied(ARDOrc* Orc)
{
	++Kills;
	RD_MARK(TEXT("ORC_DOWN %d %s"), Kills, Orc->IsWarden() ? TEXT("warden") : TEXT("grunt"));
}

void ARDGameMode::OnMageDied()
{
	Finish(ERDOutcome::Fallen, TEXT("MAGE_DOWN"));
}

void ARDGameMode::Finish(ERDOutcome Result, const TCHAR* Marker)
{
	if (Outcome != ERDOutcome::Playing)
	{
		return;
	}
	Outcome = Result;
	EndTimer = 0.f;
	RD_MARK(TEXT("%s %s"), Marker, *Summary());
	ShowToast(Result == ERDOutcome::Cleared ? TEXT("Delve complete!  R to delve again")
	                                        : TEXT("You fell.  R to try again"));
	ToastLeft = 1e9f;
}

FString ARDGameMode::Summary() const
{
	const ARDMage* Mage = GetMage();
	return FString::Printf(TEXT("rooms %d/%d kills %d/%d time %.1fs bolts %d wards %d blocks %d damage %.0f"),
	                       RoomsCleared(), FRDLevel::RoomCount, Kills, Orcs.Num(), Elapsed,
	                       Mage ? Mage->BoltsCast : 0, Mage ? Mage->WardsCast : 0, Mage ? Mage->WardBlocks : 0,
	                       Mage ? Mage->DamageTaken : 0.f);
}

void ARDGameMode::RestartDelve()
{
	UGameplayStatics::OpenLevel(this, FName(*UGameplayStatics::GetCurrentLevelName(this)));
}

void ARDGameMode::ShowToast(const FString& Text)
{
	Toast = Text;
	ToastLeft = ToastSeconds;
}

FRDBotSnapshot ARDGameMode::BotSnapshot() const
{
	FRDBotSnapshot S;
	const ARDMage* Mage = GetMage();
	if (!Mage)
	{
		return S;
	}
	S.MagePos = Mage->Ground();
	S.Health = Mage->GetHealth();
	S.MaxHealth = Mage->GetMaxHealth();
	S.Mana = Mage->GetMana();
	S.BoltCooldown = Mage->CooldownLeft(RDTags::Cooldown_Bolt);
	S.WardCooldown = Mage->CooldownLeft(RDTags::Cooldown_Ward);
	S.DashCooldown = Mage->CooldownLeft(RDTags::Cooldown_Dash);
	S.Room = CurrentRoom;
	S.bRoomCleared = bCleared[CurrentRoom];
	for (const ARDOrc* O : Orcs)
	{
		if (!O || !O->IsAlive())
		{
			continue;
		}
		const int32 Here = FRDLevel::RoomOf(O->Ground());
		const int32 Gate = Here < 0 ? FRDLevel::GateOf(O->Ground()) : -1;
		const bool bInDoorway = Gate >= 0 && (Gate == CurrentRoom || Gate + 1 == CurrentRoom);
		if (Here == CurrentRoom || bInDoorway)
		{
			S.Orcs.Add(O->ToBot());
		}
	}
	return S;
}

void ARDGameMode::Record()
{
	const FRDLaunchOptions& O = FRDLaunchOptions::Get();
	if (O.RecordDir.IsEmpty() || (Frame++ % O.RecordEvery) != 0)
	{
		return;
	}
	const FString Dir = FPaths::IsRelative(O.RecordDir) ? FPaths::Combine(FPaths::ProjectDir(), O.RecordDir) : O.RecordDir;
	FScreenshotRequest::RequestScreenshot(FPaths::Combine(Dir, FString::Printf(TEXT("frame_%05d.png"), Frame / O.RecordEvery)), false, false);
}
