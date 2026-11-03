// ---------------------------------------------------------------------------
// RDCoreTests.cpp
// Purpose : Unit tests for the engine-light core: combat rules, the orc FSM (every transition), the level
//           data, the bot policies, and that every tunable in the ini is set.
// Usage   : python tools/dev.py test --filter RuneDelve.Core      (or `test` for everything)
// Notes   : Numbers come from URDTuning (Config/DefaultGame.ini), the same values the game reads, so a
//           tuning change that breaks a rule fails here first. Distances are relative to the tuning.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 Level checks 300 seeds for shared spawn tiles (the warden landed on a grunt's tile for
//           24 of seeds 0..199; the old loop stopped at 7) and checks GateOf
// Updated : 2026-11-03 (issue #150) checks what the game runs: no RDRules::Regen checks (the live regen is a GAS
//           effect, checked by the Regressions smoke), the stagger a blocked swing gives (Recover -> Staggered),
//           and the masher's low-mana ward; orcs stand down when the mage is dead (issue #149)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#include "Core/RDBotPolicy.h"
#include "Core/RDLevel.h"
#include "Core/RDOrcBrain.h"
#include "Core/RDRules.h"
#include "Game/RDTuning.h"

namespace
{
	constexpr EAutomationTestFlags CoreFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;

	constexpr float ReactSeconds = 0.4f;   // s: shortest telegraph a player can be asked to answer
	constexpr int32 LevelSeeds = 300;      // seeds the Level test lays out

	FRDNumbers Tuned() { return GetDefault<URDTuning>()->Numbers(); }

	FRDOrcOutput Step(FRDOrcBrain& B, float Dt, bool bSenses, float Dist, bool bStaggered = false, bool bAlive = true,
	                  bool bMageAlive = true)
	{
		return B.Tick(FRDOrcInput{Dt, bAlive, bSenses, Dist, bStaggered, bMageAlive});
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDTuningTest, "RuneDelve.Core.Tuning", CoreFlags)
bool FRDTuningTest::RunTest(const FString&)
{
	// Every number set in Config/DefaultGame.ini (the class has no defaults): a zero means a missing line
	const URDTuning* T = GetDefault<URDTuning>();
	int32 Checked = 0;
	for (TFieldIterator<FFloatProperty> It(URDTuning::StaticClass(), EFieldIteratorFlags::ExcludeSuper); It; ++It)
	{
		const float V = It->GetPropertyValue_InContainer(T);
		TestTrue(FString::Printf(TEXT("%s is set in DefaultGame.ini"), *It->GetName()), V > 0.f);
		++Checked;
	}
	TestTrue(TEXT("tunables found"), Checked >= 30);
	const FRDNumbers N = Tuned();
	// Pillar 2: a wind-up a person can see and answer (reaction time is about a quarter second, plus margin)
	TestTrue(TEXT("a grunt wind-up is long enough to react to"), N.Grunt.Windup >= ReactSeconds);
	TestTrue(TEXT("the warden's wind-up is long enough to react to"), N.Warden.Windup >= ReactSeconds);
	TestTrue(TEXT("the ward window is wider than a reaction"), N.WardSeconds >= ReactSeconds);
	TestTrue(TEXT("a staggered orc stays down long enough for two bolts"), N.StaggerSeconds > 2.f * N.BoltCooldown);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDRulesTest, "RuneDelve.Core.Rules", CoreFlags)
bool FRDRulesTest::RunTest(const FString&)
{
	const FRDHitResult Plain = RDRules::ResolveHit(18.f, false, false, false, true, 2.f);
	TestEqual(TEXT("plain hit"), Plain.Damage, 18.f);
	const FRDHitResult Warded = RDRules::ResolveHit(18.f, true, false, false, true, 2.f);
	TestTrue(TEXT("ward blocks"), Warded.bBlocked && Warded.Damage == 0.f);
	TestTrue(TEXT("ward staggers a melee attacker"), Warded.bStaggerAttacker);
	TestFalse(TEXT("ward does not stagger a non-melee source"), RDRules::ResolveHit(18.f, true, false, false, false, 2.f).bStaggerAttacker);
	const FRDHitResult Dash = RDRules::ResolveHit(18.f, true, true, false, true, 2.f);
	TestTrue(TEXT("a dash dodges, even through a ward"), Dash.bDodged && Dash.Damage == 0.f && !Dash.bStaggerAttacker);
	TestEqual(TEXT("staggered targets take double"), RDRules::ResolveHit(12.f, false, false, true, false, 2.f).Damage, 24.f);
	TestTrue(TEXT("can cast"), RDRules::CanCast(20.f, 14.f, 0.f));
	TestFalse(TEXT("not without mana"), RDRules::CanCast(10.f, 14.f, 0.f));
	TestFalse(TEXT("not on cooldown"), RDRules::CanCast(100.f, 14.f, 0.1f));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDOrcBrainTest, "RuneDelve.Core.OrcBrain", CoreFlags)
bool FRDOrcBrainTest::RunTest(const FString&)
{
	const FRDNumbers N = Tuned();
	const FRDOrcStats G = N.Grunt;
	const float Dt = 1.f / 60.f;
	FRDOrcBrain B(G);
	TestTrue(TEXT("starts asleep"), B.GetState() == ERDOrcState::Sleep);
	TestFalse(TEXT("sleeps through nothing"), Step(B, Dt, false, 100.f).bAlerted);
	TestTrue(TEXT("wakes when it senses the mage"), Step(B, Dt, true, G.Reach * 3.f).bAlerted);
	TestTrue(TEXT("hunts"), B.GetState() == ERDOrcState::Hunt);
	TestTrue(TEXT("moves while out of reach"), Step(B, Dt, true, G.Reach * 3.f).bMove);
	const FRDOrcOutput W = Step(B, Dt, true, G.Reach * 0.9f);
	TestTrue(TEXT("winds up in reach"), W.bWindupStart && B.GetState() == ERDOrcState::Windup && !W.bMove);
	TestTrue(TEXT("wind-up countdown"), FMath::IsNearlyEqual(B.WindupLeft(), G.Windup, 0.001f));
	int32 Strikes = 0;
	for (float T = 0.f; T < G.Windup + Dt * 2.f; T += Dt)
	{
		Strikes += Step(B, Dt, true, G.Reach * 0.9f).bStrike ? 1 : 0;
	}
	TestEqual(TEXT("exactly one swing per wind-up"), Strikes, 1);
	TestTrue(TEXT("recovers after the swing"), B.GetState() == ERDOrcState::Recover);
	for (float T = 0.f; T < G.Recover + Dt; T += Dt)
	{
		Step(B, Dt, true, G.Reach * 3.f);
	}
	TestTrue(TEXT("hunts again after recovering"), B.GetState() == ERDOrcState::Hunt);

	// The path a timed ward takes in the game: the blocked swing tags the orc as it strikes (the brain is already in
	// Recover), the brain sees the tag on the next tick, stays Staggered with no swing for as long as the tag lasts
	// (StaggerSeconds), and winds up again only after it, even with the mage still in reach
	FRDOrcBrain S(G);
	const float Close = G.Reach * 0.5f;
	Step(S, Dt, true, Close);
	Step(S, Dt, true, Close);
	TestTrue(TEXT("winding up"), S.GetState() == ERDOrcState::Windup);
	bool bStruck = false;
	for (float T = 0.f; T < G.Windup + Dt * 2.f && !bStruck; T += Dt)
	{
		bStruck = Step(S, Dt, true, Close).bStrike;
	}
	TestTrue(TEXT("the swing comes out and the orc recovers"), bStruck && S.GetState() == ERDOrcState::Recover);
	Step(S, Dt, true, Close, true);
	TestTrue(TEXT("the tag from the blocked swing staggers it on the next tick"), S.GetState() == ERDOrcState::Staggered);
	int32 StaggeredStrikes = 0;
	int32 StaggeredWindups = 0;
	bool bStayedStaggered = true;
	for (float T = Dt; T < N.StaggerSeconds; T += Dt)
	{
		const FRDOrcOutput O = Step(S, Dt, true, Close, true);
		StaggeredStrikes += O.bStrike ? 1 : 0;
		StaggeredWindups += O.bWindupStart ? 1 : 0;
		bStayedStaggered &= S.GetState() == ERDOrcState::Staggered;
	}
	TestTrue(TEXT("staggered for all of StaggerSeconds"), bStayedStaggered);
	TestEqual(TEXT("no swing while staggered"), StaggeredStrikes, 0);
	TestEqual(TEXT("no wind-up while staggered"), StaggeredWindups, 0);
	Step(S, Dt, true, Close, false);
	TestTrue(TEXT("back to hunting when the stagger ends"), S.GetState() == ERDOrcState::Hunt);
	TestTrue(TEXT("the next wind-up only after the stagger"), Step(S, Dt, true, Close).bWindupStart && S.GetState() == ERDOrcState::Windup);

	// The mage falls: a hunting orc and one mid wind-up stand down, with no swing and no step toward the body
	FRDOrcBrain H(G);
	Step(H, Dt, true, G.Reach * 3.f);
	TestTrue(TEXT("hunting before the mage falls"), H.GetState() == ERDOrcState::Hunt);
	const FRDOrcOutput Down = Step(H, Dt, false, G.Reach * 3.f, false, true, false);
	TestTrue(TEXT("a hunting orc stands down when the mage is dead"), H.GetState() == ERDOrcState::Sleep && !Down.bMove);
	FRDOrcBrain Wind(G);
	Step(Wind, Dt, true, Close);
	Step(Wind, Dt, true, Close);
	TestTrue(TEXT("winding up before the mage falls"), Wind.GetState() == ERDOrcState::Windup);
	int32 BodyStrikes = 0;
	for (float T = 0.f; T < G.Windup + G.Recover + Dt * 4.f; T += Dt)
	{
		const FRDOrcOutput O = Step(Wind, Dt, false, Close, false, true, false);
		BodyStrikes += O.bStrike || O.bWindupStart ? 1 : 0;
	}
	TestEqual(TEXT("no swing at the body"), BodyStrikes, 0);
	TestTrue(TEXT("an orc mid wind-up stands down when the mage is dead"), Wind.GetState() == ERDOrcState::Sleep);

	Step(S, Dt, true, 0.f, false, false);
	TestTrue(TEXT("dies"), S.GetState() == ERDOrcState::Dead);
	TestFalse(TEXT("the dead do not swing"), Step(S, Dt, true, 0.f).bStrike);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDLevelTest, "RuneDelve.Core.Level", CoreFlags)
bool FRDLevelTest::RunTest(const FString&)
{
	TArray<FRDPiece> Pieces;
	FRDLevel::Pieces(Pieces);
	TSet<FIntPoint> Solid;
	TSet<FIntPoint> Floor;
	int32 GateTiles[2] = {0, 0};
	for (const FRDPiece& P : Pieces)
	{
		(P.Kind == ERDPiece::Floor ? Floor : Solid).Add(FIntPoint(P.X, P.Y));
		if (P.Kind == ERDPiece::Gate)
		{
			GateTiles[P.Gate]++;
		}
	}
	TestEqual(TEXT("gate 0 is three tiles"), GateTiles[0], 3);
	TestEqual(TEXT("gate 1 is three tiles"), GateTiles[1], 3);
	TestTrue(TEXT("mage starts on open floor in room 0"),
	         FRDLevel::RoomOf(FRDLevel::MageStart()) == 0 && !Solid.Contains(FIntPoint(2, 0)));
	for (int32 R = 0; R < FRDLevel::RoomCount; ++R)
	{
		TestTrue(FString::Printf(TEXT("room %d centre is inside room %d"), R, R),
		         FRDLevel::RoomOf(FRDLevel::RoomInterior(R).GetCenter()) == R);
	}
	TestEqual(TEXT("gates are not inside a room"), FRDLevel::RoomOf(FRDLevel::GateCenter(0)), -1);
	TestEqual(TEXT("gate 0 is a doorway"), FRDLevel::GateOf(FRDLevel::GateCenter(0)), 0);
	TestEqual(TEXT("gate 1's outer tile is a doorway"), FRDLevel::GateOf(FRDLevel::TileToWorld(20, 1)), 1);
	TestEqual(TEXT("a room centre is no doorway"), FRDLevel::GateOf(FRDLevel::RoomInterior(1).GetCenter()), -1);
	TestEqual(TEXT("a wall beside a gate is no doorway"), FRDLevel::GateOf(FRDLevel::TileToWorld(10, 2)), -1);
	const FBox Nav = FRDLevel::NavBounds();
	TestTrue(TEXT("nav bounds cover the far wall"), Nav.Max.X > FRDLevel::TileToWorld(30, 0).X);

	// Seed 35 was the first with the warden on a grunt's tile; a few hundred seeds cover every room shuffle well.
	// Only failures are reported per seed, so a pass stays a few lines in the log.
	int32 Overlaps = 0;
	for (int32 Seed = 0; Seed < LevelSeeds; ++Seed)
	{
		TArray<FRDSpawn> Orcs;
		FRDLevel::Orcs(Seed, Orcs);
		if (Orcs.Num() != 8)
		{
			AddError(FString::Printf(TEXT("seed %d: %d orcs, want 2 + 3 + 2 grunts and a warden"), Seed, Orcs.Num()));
		}
		TSet<FIntPoint> Spots;
		for (const FRDSpawn& O : Orcs)
		{
			const FIntPoint Tile(FMath::RoundToInt(O.Pos.X / FRDLevel::Tile), FMath::RoundToInt(O.Pos.Y / FRDLevel::Tile));
			if (Solid.Contains(Tile))
			{
				AddError(FString::Printf(TEXT("seed %d: an orc inside a column or wall at %s"), Seed, *Tile.ToString()));
			}
			if (FRDLevel::RoomOf(O.Pos) != O.Room)
			{
				AddError(FString::Printf(TEXT("seed %d: an orc outside its own room %d"), Seed, O.Room));
			}
			if (Spots.Contains(Tile))
			{
				AddError(FString::Printf(TEXT("seed %d: two orcs on tile %s%s"), Seed, *Tile.ToString(), O.bWarden ? TEXT(" (the warden)") : TEXT("")));
				++Overlaps;
			}
			Spots.Add(Tile);
		}
	}
	TestEqual(FString::Printf(TEXT("no two orcs share a spawn tile in seeds 0..%d"), LevelSeeds - 1), Overlaps, 0);
	TArray<FRDSpawn> A, B, C;
	FRDLevel::Orcs(3, A);
	FRDLevel::Orcs(3, B);
	FRDLevel::Orcs(4, C);
	TestTrue(TEXT("same seed, same orcs"), A[0].Pos == B[0].Pos && A[4].Yaw == B[4].Yaw);
	bool bDiffer = false;
	for (int32 I = 0; I < A.Num(); ++I)
	{
		bDiffer |= A[I].Pos != C[I].Pos;
	}
	TestTrue(TEXT("different seed, different orcs"), bDiffer);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDBotTest, "RuneDelve.Core.Bots", CoreFlags)
bool FRDBotTest::RunTest(const FString&)
{
	const FRDNumbers N = Tuned();
	FRDBotSnapshot S;
	S.MagePos = FVector2D(0.f, 0.f);
	S.Health = S.MaxHealth = N.MageHealth;
	S.Mana = N.MageMana;
	FRDBotOrc O;
	O.Pos = FVector2D(N.Grunt.Reach * 0.8f, 0.f);
	O.Reach = N.Grunt.Reach;
	O.State = ERDOrcState::Hunt;
	S.Orcs.Add(O);

	// An orc right next to you but not swinging: the masher wards anyway, the weaver waits
	TestTrue(TEXT("masher wards early"), RDBot::Decide(ERDBotMode::Masher, S, N).bWard);
	TestFalse(TEXT("weaver holds the ward"), RDBot::Decide(ERDBotMode::Weaver, S, N).bWard);

	// The swing is about to land: the weaver wards
	S.Orcs[0].State = ERDOrcState::Windup;
	S.Orcs[0].WindupLeft = N.WardSeconds * 0.5f;
	TestTrue(TEXT("weaver wards the swing"), RDBot::Decide(ERDBotMode::Weaver, S, N).bWard);
	S.Orcs[0].WindupLeft = N.WardSeconds + 0.5f;
	TestFalse(TEXT("weaver does not ward a swing beyond the window"), RDBot::Decide(ERDBotMode::Weaver, S, N).bWard);

	// Low mana: the masher wards first, which leaves too little for a bolt; the weaver keeps a ward's worth
	S.Orcs[0].State = ERDOrcState::Hunt;
	S.Mana = N.WardCost + N.BoltCost * 0.5f;
	const FRDBotAction Mash = RDBot::Decide(ERDBotMode::Masher, S, N);
	TestTrue(TEXT("masher spends the last mana on a ward, not a bolt"), Mash.bWard && !Mash.bBolt);
	TestFalse(TEXT("weaver keeps the ward's mana"), RDBot::Decide(ERDBotMode::Weaver, S, N).bBolt);
	S.Orcs[0].bStaggered = true;
	TestTrue(TEXT("...unless the orc is staggered"), RDBot::Decide(ERDBotMode::Weaver, S, N).bBolt);

	// Both walk in from far away, and to the next room once this one is clear
	S.Orcs[0] = O;
	S.Orcs[0].Pos = FVector2D(RDBot::StandRange * 2.f, 0.f);
	TestTrue(TEXT("approach"), RDBot::Decide(ERDBotMode::Weaver, S, N).bMove && RDBot::Decide(ERDBotMode::Masher, S, N).bMove);
	S.Orcs.Reset();
	S.bRoomCleared = true;
	const FRDBotAction Next = RDBot::Decide(ERDBotMode::Weaver, S, N);
	TestTrue(TEXT("next room"), Next.bMove && FRDLevel::RoomOf(Next.MoveTo) == 1);
	TestTrue(TEXT("parse"), RDBot::Parse(TEXT("Weaver")) == ERDBotMode::Weaver && RDBot::Parse(TEXT("x")) == ERDBotMode::None);
	return true;
}
