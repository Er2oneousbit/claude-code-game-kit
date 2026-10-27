// ---------------------------------------------------------------------------
// RDOrcBrain.cpp
// Purpose : See RDOrcBrain.h.
//
// Pseudocode:
//   dead stays dead; a stagger interrupts anything (no swing comes out), and ends back in Hunt
//   Sleep: senses the mage -> Hunt (alerted)
//   Hunt: move; within Reach -> Windup
//   Windup: after Windup seconds -> strike, Recover
//   Recover: after Recover seconds -> Hunt
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Core/RDOrcBrain.h"

void FRDOrcBrain::Go(ERDOrcState Next)
{
	State = Next;
	StateTime = 0.f;
}

FRDOrcOutput FRDOrcBrain::Tick(const FRDOrcInput& In)
{
	FRDOrcOutput Out;
	if (State == ERDOrcState::Dead)
	{
		return Out;
	}
	if (!In.bAlive)
	{
		Go(ERDOrcState::Dead);
		return Out;
	}
	StateTime += In.Dt;

	if (In.bStaggered)
	{
		if (State != ERDOrcState::Staggered)
		{
			Go(ERDOrcState::Staggered);
		}
		return Out;
	}

	switch (State)
	{
	case ERDOrcState::Sleep:
		if (In.bSensesMage)
		{
			Out.bAlerted = true;
			Go(ERDOrcState::Hunt);
		}
		break;
	case ERDOrcState::Staggered:   // the tag ran out
		Go(ERDOrcState::Hunt);
		break;
	case ERDOrcState::Hunt:
		if (In.DistToMage <= Stats.Reach)
		{
			Out.bWindupStart = true;
			Go(ERDOrcState::Windup);
		}
		else
		{
			Out.bMove = true;
		}
		break;
	case ERDOrcState::Windup:
		if (StateTime >= Stats.Windup)
		{
			Out.bStrike = true;
			Go(ERDOrcState::Recover);
		}
		break;
	case ERDOrcState::Recover:
		if (StateTime >= Stats.Recover)
		{
			Go(ERDOrcState::Hunt);
		}
		break;
	default:
		break;
	}
	return Out;
}

const TCHAR* FRDOrcBrain::StateName(ERDOrcState S)
{
	switch (S)
	{
	case ERDOrcState::Sleep: return TEXT("SLEEP");
	case ERDOrcState::Hunt: return TEXT("HUNT");
	case ERDOrcState::Windup: return TEXT("WINDUP");
	case ERDOrcState::Recover: return TEXT("RECOVER");
	case ERDOrcState::Staggered: return TEXT("STAGGERED");
	case ERDOrcState::Dead: return TEXT("DEAD");
	}
	return TEXT("?");
}
