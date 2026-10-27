// ---------------------------------------------------------------------------
// RDNumbers.h
// Purpose : The plain numbers the engine-light core runs on: spells, mage, orcs, warden.
// Usage   : FRDNumbers N = GetDefault<URDTuning>()->Numbers();   (game and tests alike)
// Notes   : No defaults here on purpose. The single source of truth is URDTuning, whose defaults live in
//           Config/DefaultGame.ini, so tests and the game can never disagree about a number.
//           Distances in centimetres, times in seconds.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

/** One kind of orc (a grunt or the warden). */
struct FRDOrcStats
{
	float Health = 0.f;
	float Speed = 0.f;     // cm/s
	float Reach = 0.f;     // cm: starts a wind-up inside this, and the swing lands inside Reach * StrikeSlack
	float Windup = 0.f;    // s: the telegraph, raised weapon and red glow
	float Damage = 0.f;
	float Recover = 0.f;   // s after a swing before it can move again
};

struct FRDNumbers
{
	// Mage
	float MageHealth = 0.f;
	float MageMana = 0.f;
	float ManaRegen = 0.f;        // per second
	float MageSpeed = 0.f;        // cm/s
	float RoomClearHeal = 0.f;

	// Bolt: cheap, quick, noisy
	float BoltCost = 0.f;
	float BoltCooldown = 0.f;
	float BoltDamage = 0.f;
	float BoltSpeed = 0.f;
	float BoltRange = 0.f;
	float BoltNoise = 0.f;        // cm: orcs in the same room within this hear it

	// Dash: free, long cooldown, dodges hits while it lasts
	float DashCooldown = 0.f;
	float DashDistance = 0.f;
	float DashSeconds = 0.f;

	// Ward: expensive, blocks one melee swing and staggers the attacker
	float WardCost = 0.f;
	float WardCooldown = 0.f;
	float WardSeconds = 0.f;
	float StaggerSeconds = 0.f;
	float StaggerDamageMult = 0.f;

	// Orc senses and swings
	float OrcSight = 0.f;
	float OrcSightHalfAngle = 0.f;  // degrees either side of facing
	float StrikeSlack = 0.f;        // a swing still lands if the mage is within Reach * this when it fires
	FRDOrcStats Grunt;
	FRDOrcStats Warden;
};
