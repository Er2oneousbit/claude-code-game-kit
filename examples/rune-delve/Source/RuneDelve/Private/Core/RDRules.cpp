// ---------------------------------------------------------------------------
// RDRules.cpp
// Purpose : See RDRules.h.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Core/RDRules.h"

FRDHitResult RDRules::ResolveHit(float Damage, bool bTargetWarded, bool bTargetDashing, bool bTargetStaggered, bool bMelee,
                                 float StaggerDamageMult)
{
	FRDHitResult R;
	if (bTargetDashing)
	{
		R.bDodged = true;
		return R;
	}
	if (bTargetWarded)
	{
		R.bBlocked = true;
		R.bStaggerAttacker = bMelee;   // a ward only turns a swing back on the swinger
		return R;
	}
	R.Damage = FMath::Max(0.f, Damage) * (bTargetStaggered ? StaggerDamageMult : 1.f);
	return R;
}

bool RDRules::CanCast(float Mana, float Cost, float CooldownLeft)
{
	return CooldownLeft <= 0.f && Mana >= Cost;
}
