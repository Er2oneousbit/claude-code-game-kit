// ---------------------------------------------------------------------------
// RDTuning.cpp
// Purpose : Copy the ini-backed settings into the plain struct the core runs on.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Game/RDTuning.h"

FRDNumbers URDTuning::Numbers() const
{
	FRDNumbers N;
	N.MageHealth = MageHealth;
	N.MageMana = MageMana;
	N.ManaRegen = ManaRegen;
	N.MageSpeed = MageSpeed;
	N.RoomClearHeal = RoomClearHeal;
	N.BoltCost = BoltCost;
	N.BoltCooldown = BoltCooldown;
	N.BoltDamage = BoltDamage;
	N.BoltSpeed = BoltSpeed;
	N.BoltRange = BoltRange;
	N.BoltNoise = BoltNoise;
	N.DashCooldown = DashCooldown;
	N.DashDistance = DashDistance;
	N.DashSeconds = DashSeconds;
	N.WardCost = WardCost;
	N.WardCooldown = WardCooldown;
	N.WardSeconds = WardSeconds;
	N.StaggerSeconds = StaggerSeconds;
	N.StaggerDamageMult = StaggerDamageMult;
	N.OrcSight = OrcSight;
	N.OrcSightHalfAngle = OrcSightHalfAngle;
	N.StrikeSlack = StrikeSlack;
	N.Grunt = FRDOrcStats{GruntHealth, GruntSpeed, GruntReach, GruntWindup, GruntDamage, GruntRecover};
	N.Warden = FRDOrcStats{WardenHealth, WardenSpeed, WardenReach, WardenWindup, WardenDamage, WardenRecover};
	return N;
}
