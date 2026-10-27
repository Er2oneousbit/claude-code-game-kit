// ---------------------------------------------------------------------------
// RDOrcBrain.h
// Purpose : The orc's decisions as a small finite state machine (SOP-14: a handful of modes, so an FSM),
//           with no engine types: Sleep -> Hunt -> Windup -> (swing) -> Recover -> Hunt, Staggered, Dead.
// Usage   : FRDOrcBrain Brain(N.Grunt); each tick: FRDOrcOutput Out = Brain.Tick({Dt, bAlive, bSenses, Dist, bStaggered});
//           Out.bMove -> chase the mage; Out.bStrike -> the swing fires now (the actor checks reach and applies damage)
// Notes   : Pillar 2 (read the orcs): every swing has a Windup the player can see. A stagger (from a ward)
//           interrupts the wind-up, so no swing comes out. Once awake an orc always knows where the mage is
//           (rooms are closed until cleared).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Core/RDNumbers.h"

enum class ERDOrcState : uint8
{
	Sleep,
	Hunt,
	Windup,
	Recover,
	Staggered,
	Dead
};

struct FRDOrcInput
{
	float Dt = 0.f;
	bool bAlive = true;
	bool bSensesMage = false;   // saw or heard the mage this tick (same room only)
	float DistToMage = 1e9f;
	bool bStaggered = false;    // the GAS State.Staggered tag is on this orc
};

struct FRDOrcOutput
{
	bool bMove = false;      // chase the mage
	bool bStrike = false;    // the swing fires this tick
	bool bAlerted = false;   // just woke up (show "!", play a sound)
	bool bWindupStart = false;
};

class RUNEDELVE_API FRDOrcBrain
{
public:
	explicit FRDOrcBrain(const FRDOrcStats& InStats) : Stats(InStats) {}

	FRDOrcOutput Tick(const FRDOrcInput& In);

	ERDOrcState GetState() const { return State; }
	float GetStateTime() const { return StateTime; }
	/** Seconds until the swing lands, or a big number when not winding up. */
	float WindupLeft() const { return State == ERDOrcState::Windup ? FMath::Max(0.f, Stats.Windup - StateTime) : 1e9f; }
	const FRDOrcStats& GetStats() const { return Stats; }
	static const TCHAR* StateName(ERDOrcState S);

private:
	void Go(ERDOrcState Next);

	FRDOrcStats Stats;
	ERDOrcState State = ERDOrcState::Sleep;
	float StateTime = 0.f;
};
