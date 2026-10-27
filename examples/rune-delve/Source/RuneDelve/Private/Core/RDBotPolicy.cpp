// ---------------------------------------------------------------------------
// RDBotPolicy.cpp
// Purpose : See RDBotPolicy.h.
//
// Pseudocode:
//   room cleared -> walk into the next room (the gate is open by then)
//   target = nearest orc; aim where it will be when the bolt arrives
//   move to StandRange of the target, then hold ground
//   hurt and crowded -> dash away from the crowd (both bots)
//   Weaver: ward if a swing lands inside the ward window; bolt staggered orcs first; keep a ward's mana
//   Masher: ward whenever an orc is close; bolt whenever ready
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Core/RDBotPolicy.h"

#include "Core/RDLevel.h"
#include "Core/RDRules.h"

namespace
{
	FVector2D Lead(const FRDBotOrc& O, const FVector2D& From, float BoltSpeed)
	{
		const float T = FVector2D::Distance(From, O.Pos) / FMath::Max(1.f, BoltSpeed);
		return O.Pos + O.Vel * T;
	}
}

FRDBotAction RDBot::Decide(ERDBotMode Mode, const FRDBotSnapshot& S, const FRDNumbers& N)
{
	FRDBotAction A;
	if (Mode == ERDBotMode::None)
	{
		return A;
	}

	// Nothing alive here: on to the next room
	if (S.Orcs.Num() == 0)
	{
		if (S.bRoomCleared && S.Room < FRDLevel::RoomCount - 1)
		{
			A.bMove = true;
			A.MoveTo = FRDLevel::RoomInterior(S.Room + 1).GetCenter();
			A.Reason = TEXT("next room");
		}
		return A;
	}

	// Shared movement and aim
	const FRDBotOrc* Target = nullptr;
	float TargetDist = TNumericLimits<float>::Max();
	FVector2D Crowd = FVector2D::ZeroVector;
	int32 Close = 0;
	for (const FRDBotOrc& O : S.Orcs)
	{
		const float D = FVector2D::Distance(S.MagePos, O.Pos);
		if (D < TargetDist)
		{
			TargetDist = D;
			Target = &O;
		}
		if (D <= O.Reach * 1.2f)
		{
			Crowd += O.Pos;
			++Close;
		}
	}
	if (TargetDist > StandRange)
	{
		A.bMove = true;
		A.MoveTo = Target->Pos;
	}
	A.bAim = true;
	A.AimAt = Lead(*Target, S.MagePos, N.BoltSpeed);
	A.Reason = A.bMove ? TEXT("approach") : TEXT("hold");

	if (S.Health < S.MaxHealth * HurtFraction && Close >= CrowdCount && S.DashCooldown <= 0.f)
	{
		A.bDash = true;
		A.DashDir = (S.MagePos - Crowd / Close).GetSafeNormal();
		A.Reason = TEXT("dash out");
	}

	if (Mode == ERDBotMode::Masher)
	{
		A.bWard = Close > 0 && RDRules::CanCast(S.Mana, N.WardCost, S.WardCooldown);
		A.bBolt = TargetDist <= N.BoltRange && RDRules::CanCast(S.Mana - (A.bWard ? N.WardCost : 0.f), N.BoltCost, S.BoltCooldown);
		return A;
	}

	// Weaver: meet the swing with the ward, burst the staggered orc, never spend the ward's mana on bolts
	for (const FRDBotOrc& O : S.Orcs)
	{
		const bool bInReach = FVector2D::Distance(S.MagePos, O.Pos) <= O.Reach * N.StrikeSlack;
		if (O.State == ERDOrcState::Windup && bInReach && O.WindupLeft <= N.WardSeconds - WardMargin &&
		    RDRules::CanCast(S.Mana, N.WardCost, S.WardCooldown))
		{
			A.bWard = true;
			A.Reason = TEXT("ward the swing");
			break;
		}
	}
	const FRDBotOrc* Burst = nullptr;
	for (const FRDBotOrc& O : S.Orcs)
	{
		if (O.bStaggered && (!Burst || FVector2D::Distance(S.MagePos, O.Pos) < FVector2D::Distance(S.MagePos, Burst->Pos)))
		{
			Burst = &O;
		}
	}
	const FRDBotOrc* BoltAt = Burst ? Burst : Target;
	const float Reserve = Burst ? 0.f : N.WardCost;   // a staggered orc is worth the last mana
	const float Spent = A.bWard ? N.WardCost : 0.f;
	if (FVector2D::Distance(S.MagePos, BoltAt->Pos) <= N.BoltRange &&
	    RDRules::CanCast(S.Mana - Spent - Reserve, N.BoltCost, S.BoltCooldown))
	{
		A.bBolt = true;
		A.AimAt = Lead(*BoltAt, S.MagePos, N.BoltSpeed);
		if (Burst)
		{
			A.Reason = TEXT("burst the staggered");
		}
	}
	return A;
}

ERDBotMode RDBot::Parse(const FString& Name)
{
	if (Name.Equals(TEXT("weaver"), ESearchCase::IgnoreCase))
	{
		return ERDBotMode::Weaver;
	}
	if (Name.Equals(TEXT("masher"), ESearchCase::IgnoreCase))
	{
		return ERDBotMode::Masher;
	}
	return ERDBotMode::None;
}

const TCHAR* RDBot::Name(ERDBotMode Mode)
{
	switch (Mode)
	{
	case ERDBotMode::Weaver: return TEXT("Weaver");
	case ERDBotMode::Masher: return TEXT("Masher");
	default: return TEXT("None");
	}
}
