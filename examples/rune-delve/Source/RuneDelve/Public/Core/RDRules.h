// ---------------------------------------------------------------------------
// RDRules.h
// Purpose : Combat rules with no engine state: how a hit resolves (ward, dash, stagger) and whether a spell
//           can be cast. The GAS attribute set calls ResolveHit, the bots call CanCast, the tests call both.
//           Mana regeneration is a periodic GAS effect (URDEffect_ManaRegen), checked live by the Regressions smoke.
// Usage   : FRDHitResult R = RDRules::ResolveHit(Damage, bWarded, bDashing, bStaggered, bMelee, N.StaggerDamageMult);
// Notes   : Pillar 1 lives here: a ward meeting a melee swing blocks it AND staggers the attacker, and a
//           staggered target takes StaggerDamageMult times the damage. Spammed wards meet no swing.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-03 (Claude Opus 5.5): Regen removed; nothing in the game called it (issue #150)
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
}
