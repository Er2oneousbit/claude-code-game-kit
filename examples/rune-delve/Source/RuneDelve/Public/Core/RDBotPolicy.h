// ---------------------------------------------------------------------------
// RDBotPolicy.h
// Purpose : The autoplay bots for the scenario pair (SOP-14 step 6), engine-free: a snapshot of the fight
//           in, an action out. Weaver times its ward to orc wind-ups and saves mana for it; Masher casts
//           everything the moment it is ready. Both share one movement brain, so the spell policy is the
//           only difference and the pair isolates pillar 1 (timing beats spam).
// Usage   : FRDBotAction A = RDBot::Decide(ERDBotMode::Weaver, Snapshot, Numbers);
// Notes   : Movement: walk to StandRange of the nearest living orc in the room and hold ground (no kiting:
//           the orcs come to you, which is the fight the game is about); dash away when hurt and crowded.
//           Room empty: walk to the next gate, then into the next room.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Core/RDNumbers.h"
#include "Core/RDOrcBrain.h"

enum class ERDBotMode : uint8
{
	None,
	Weaver,
	Masher
};

struct FRDBotOrc
{
	FVector2D Pos = FVector2D::ZeroVector;
	FVector2D Vel = FVector2D::ZeroVector;
	ERDOrcState State = ERDOrcState::Sleep;
	float WindupLeft = 1e9f;
	float Reach = 0.f;
	float Health = 0.f;
	bool bStaggered = false;
};

struct FRDBotSnapshot
{
	FVector2D MagePos = FVector2D::ZeroVector;
	float Health = 0.f;
	float MaxHealth = 1.f;
	float Mana = 0.f;
	float BoltCooldown = 0.f;   // seconds left
	float WardCooldown = 0.f;
	float DashCooldown = 0.f;
	int32 Room = 0;             // the room the mage stands in (or is heading for)
	bool bRoomCleared = false;  // every orc in that room is dead
	TArray<FRDBotOrc> Orcs;     // living orcs standing in that room or one of its doorways (wherever they spawned)
};

struct FRDBotAction
{
	bool bMove = false;
	FVector2D MoveTo = FVector2D::ZeroVector;
	bool bAim = false;
	FVector2D AimAt = FVector2D::ZeroVector;
	bool bBolt = false;
	bool bWard = false;
	bool bDash = false;
	FVector2D DashDir = FVector2D::ZeroVector;
	const TCHAR* Reason = TEXT("");
};

namespace RDBot
{
	constexpr float StandRange = 650.f;      // cm from the target orc
	constexpr float WardMargin = 0.1f;       // s: ward this long before the window would close on the swing
	constexpr float HurtFraction = 0.35f;    // dash out below this much health...
	constexpr int32 CrowdCount = 2;          // ...when this many orcs are within reach

	FRDBotAction Decide(ERDBotMode Mode, const FRDBotSnapshot& S, const FRDNumbers& N);
	ERDBotMode Parse(const FString& Name);
	const TCHAR* Name(ERDBotMode Mode);
}
