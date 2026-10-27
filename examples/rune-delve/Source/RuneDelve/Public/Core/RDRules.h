// ---------------------------------------------------------------------------
// RDRules.h
// Purpose : Combat rules with no engine state: how a hit resolves (ward, dash, stagger), whether a spell
//           can be cast, mana regeneration. The GAS attribute set calls these, the tests call them directly.
// Usage   : FRDHitResult R = RDRules::ResolveHit(Damage, bWarded, bDashing, bStaggered, bMelee, N.StaggerDamageMult);
// Notes   : Pillar 1 lives here: a ward meeting a melee swing blocks it AND staggers the attacker, and a
//           staggered target takes StaggerDamageMult times the damage. Spammed wards meet no swing.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

struct FRDHitResult
{
	float Damage = 0.f;            // what the target actually loses
	bool bBlocked = false;         // a ward ate it
	bool bStaggerAttacker = false; // the attacker reels (only melee into a ward)
	bool bDodged = false;          // a dash was in progress
};

namespace RDRules
{
	/** Resolve one hit on a target. Order: dash dodges everything, then ward blocks, then stagger multiplies. */
	FRDHitResult ResolveHit(float Damage, bool bTargetWarded, bool bTargetDashing, bool bTargetStaggered, bool bMelee,
	                        float StaggerDamageMult);

	/** Enough mana and no cooldown left. */
	bool CanCast(float Mana, float Cost, float CooldownLeft);

	/** Mana after Dt seconds of regeneration, capped at MaxMana. */
	float Regen(float Mana, float MaxMana, float PerSecond, float Dt);
}
