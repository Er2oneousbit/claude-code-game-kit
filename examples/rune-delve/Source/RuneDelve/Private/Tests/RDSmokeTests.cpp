// ---------------------------------------------------------------------------
// RDSmokeTests.cpp
// Purpose : Smoke tests on the real map in Play In Editor: the boot check, and the scenario pair (SOP-14
//           step 6): the Weaver and the Masher bots play whole delves over several seeds, and the pair test
//           compares them (pillar 1: timing beats spam).
// Usage   : python tools/dev.py smoke                      (all RuneDelve.Smoke.*, headless)
//           RUNEDELVE_SEEDS=3 python tools/dev.py smoke    (one seed: report only, no judgement)
// Notes   : Every frame is 1/60 s of game time and the engine runs flat out (FRDLaunchOptions bFixedFps),
//           so a delve takes seconds and replays exactly. Each run reopens the map (fresh PIE world).
//           Assert a gap over seeds, never one outcome (SOP-14). The review regressions are in RDRegressionTests.cpp.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-10-26 the measured pair after the review fixes (thresholds unchanged)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_EDITOR

#include "Core/RDLevel.h"
#include "Editor.h"
#include "Engine/Engine.h"
#include "Game/RDCommon.h"
#include "Game/RDGameMode.h"
#include "Game/RDMage.h"
#include "Game/RDOrc.h"
#include "HAL/PlatformMisc.h"
#include "Misc/App.h"
#include "Misc/PackageName.h"
#include "NavigationSystem.h"
#include "Settings/LevelEditorPlaySettings.h"
#include "Tests/AutomationCommon.h"

namespace
{
	constexpr EAutomationTestFlags SmokeFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;
	constexpr double WallTimeoutSeconds = 600.0;   // one delve, real time: a stuck run fails instead of hanging
	const int32 AllSeeds[] = {0, 1, 2, 3, 4, 5, 6, 7};

	struct FRDRunResult
	{
		ERDBotMode Bot = ERDBotMode::None;
		int32 Seed = 0;
		ERDOutcome Outcome = ERDOutcome::Playing;
		int32 Rooms = 0;
		int32 Kills = 0;
		/** Progress: every kill counts 1, a full clear 2 more (8 orcs, so 10 per delve at most). */
		int32 Progress() const { return Kills + (Outcome == ERDOutcome::Cleared ? 2 : 0); }
	};
	TArray<FRDRunResult> GResults;

	TArray<int32> Seeds()
	{
		const FString Only = FPlatformMisc::GetEnvironmentVariable(TEXT("RUNEDELVE_SEEDS"));
		if (Only.IsEmpty())
		{
			return TArray<int32>(AllSeeds, UE_ARRAY_COUNT(AllSeeds));
		}
		TArray<FString> Parts;
		Only.ParseIntoArray(Parts, TEXT(","));
		TArray<int32> Out;
		for (const FString& P : Parts)
		{
			Out.Add(FCString::Atoi(*P));
		}
		return Out;
	}

	UWorld* PieWorld()
	{
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			if (Context.WorldType == EWorldType::PIE && Context.World())
			{
				return Context.World();
			}
		}
		return nullptr;
	}

	ARDGameMode* PieGame()
	{
		UWorld* World = PieWorld();
		return World ? World->GetAuthGameMode<ARDGameMode>() : nullptr;
	}

	/** The map exists only after tools/unreal/build_content.py has run; without it every run would idle to its timeout. */
	bool ContentReady(FAutomationTestBase& Test)
	{
		if (FPackageName::DoesPackageExist(RDAssets::Map))
		{
			return true;
		}
		Test.AddError(TEXT("no Delve map: run python tools/dev.py exec tools/unreal/build_content.py first"));
		return false;
	}

	void StopFastTime()
	{
		FApp::SetUseFixedTimeStep(false);
		FApp::SetBenchmarking(false);
		FRDLaunchOptions::ClearTestOverride();
	}
}

/** End any PIE session, start a fresh one with this run's options, wait for the delve to end, record it.
 *  PIE is requested directly: AutomationOpenMap called from inside a latent command queues its "start PIE"
 *  step at the END of the test's latent queue, behind every later run, so each run would wait forever. */
class FRDPlayDelve : public IAutomationLatentCommand
{
public:
	FRDPlayDelve(FAutomationTestBase* InTest, ERDBotMode InBot, int32 InSeed) : Test(InTest), Bot(InBot), Seed(InSeed) {}
	virtual ~FRDPlayDelve() override
	{
		if (Settings)
		{
			Settings->RemoveFromRoot();
		}
	}

	virtual bool Update() override
	{
		if (Phase == 0)   // end the previous session
		{
			if (GEditor->PlayWorld)
			{
				if (!bEndRequested)
				{
					GEditor->RequestEndPlayMap();
					bEndRequested = true;
				}
				return false;
			}
			FRDLaunchOptions O;
			O.Bot = Bot;
			O.Seed = Seed;
			O.bFixedFps = true;
			FRDLaunchOptions::SetTestOverride(O);
			FRequestPlaySessionParams Params;
			Settings = NewObject<ULevelEditorPlaySettings>();
			Settings->AddToRoot();   // the params struct does not keep it alive for the GC
			Settings->SetPlayNumberOfClients(1);
			Settings->bLaunchSeparateServer = false;
			Params.EditorPlaySettings = Settings;
			GEditor->RequestPlaySession(Params);
			GEditor->StartQueuedPlaySessionRequest();
			Started = FPlatformTime::Seconds();
			Phase = 1;
			return false;
		}
		ARDGameMode* Game = PieGame();
		if (Game && Game->GetOutcome() != ERDOutcome::Playing)
		{
			FRDRunResult R;
			R.Bot = Bot;
			R.Seed = Seed;
			R.Outcome = Game->GetOutcome();
			R.Rooms = Game->RoomsCleared();
			R.Kills = Game->GetKills();
			GResults.Add(R);
			UE_LOG(LogRuneDelve, Display, TEXT("[test] %s seed %d: %s"), RDBot::Name(Bot), Seed, *Game->Summary());
			return true;
		}
		if (FPlatformTime::Seconds() - Started > WallTimeoutSeconds)
		{
			Test->AddError(FString::Printf(TEXT("%s seed %d did not finish in %.0f s of real time"), RDBot::Name(Bot), Seed, WallTimeoutSeconds));
			return true;
		}
		return false;
	}

private:
	FAutomationTestBase* Test;
	ERDBotMode Bot;
	int32 Seed;
	int32 Phase = 0;
	bool bEndRequested = false;
	double Started = 0.0;
	ULevelEditorPlaySettings* Settings = nullptr;
};

/** Compare the bots once every run is in. */
class FRDJudgePair : public IAutomationLatentCommand
{
public:
	explicit FRDJudgePair(FAutomationTestBase* InTest) : Test(InTest) {}

	virtual bool Update() override
	{
		StopFastTime();
		GEditor->RequestEndPlayMap();
		auto Totals = [](ERDBotMode Bot, int32& Progress, int32& Clears, int32& Runs) {
			Progress = Clears = Runs = 0;
			for (const FRDRunResult& R : GResults)
			{
				if (R.Bot == Bot)
				{
					Progress += R.Progress();
					Clears += R.Outcome == ERDOutcome::Cleared ? 1 : 0;
					++Runs;
				}
			}
		};
		int32 WP, WC, WR, MP, MC, MR;
		Totals(ERDBotMode::Weaver, WP, WC, WR);
		Totals(ERDBotMode::Masher, MP, MC, MR);
		const FString Line = FString::Printf(TEXT("progress weaver %d, masher %d (of %d each); full clears weaver %d/%d, masher %d/%d"),
		                                     WP, MP, WR * 10, WC, WR, MC, MR);
		UE_LOG(LogRuneDelve, Display, TEXT("[test] pair: %s"), *Line);
		if (Seeds().Num() < UE_ARRAY_COUNT(AllSeeds))
		{
			return true;   // a partial run (capture, debugging): report, do not judge
		}
		// Pillar 1: timing the ward must beat casting everything the moment it is ready.
		// Measured 2026-10-22 (UE 5.8.4): weaver 71, masher 55 of 80; clears weaver 5/8, masher 0/8. The masher's
		// wards met no swing in any run: spam drains the mana the ward needs.
		// 2026-10-26, after the review fixes (a ward stops one swing, not every swing in its window): weaver 65,
		// masher 55; clears 3/8 against 0/8. Both checks pass with no margin left: tune before tightening them.
		Test->TestTrue(TEXT("the weaver gets clearly further than the masher: ") + Line, WP - MP >= 10);
		Test->TestTrue(TEXT("the weaver clears clearly more delves: ") + Line, WC >= MC + 3);
		return true;
	}

private:
	FAutomationTestBase* Test;
};

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDBootSmoke, "RuneDelve.Smoke.Boot", SmokeFlags)
bool FRDBootSmoke::RunTest(const FString&)
{
	if (!ContentReady(*this))
	{
		return false;
	}
	FRDLaunchOptions O;
	O.bFixedFps = true;
	FRDLaunchOptions::SetTestOverride(O);
	AutomationOpenMap(RDAssets::Map, true);
	ADD_LATENT_AUTOMATION_COMMAND(FWaitLatentCommand(1.0f));
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this]() {
		ARDGameMode* Game = PieGame();
		UWorld* World = PieWorld();
		if (!Game || !World)
		{
			AddError(TEXT("no Rune Delve game in the PIE world (GlobalDefaultGameMode in Config/DefaultEngine.ini?)"));
			return true;
		}
		UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World);
		if (Nav && Nav->IsNavigationBuildInProgress() && Game->GetElapsed() < 30.f)
		{
			return false;   // the runtime NavMesh is still building
		}
		ARDMage* Mage = Game->GetMage();
		TestNotNull(TEXT("the mage spawned"), Mage);
		TestEqual(TEXT("the mage starts in room 1"), Mage ? FRDLevel::RoomOf(Mage->Ground()) : -2, 0);
		TestEqual(TEXT("eight orcs"), Game->GetOrcs().Num(), 8);
		TestNotNull(TEXT("navigation system"), Nav);
		for (int32 R = 0; Nav && R < FRDLevel::RoomCount; ++R)
		{
			FNavLocation Hit;
			const FVector Centre(FRDLevel::RoomInterior(R).GetCenter(), 0.f);
			TestTrue(FString::Printf(TEXT("NavMesh covers room %d"), R + 1), Nav->ProjectPointToNavigation(Centre, Hit, FVector(50.f, 50.f, 300.f)));
		}
		StopFastTime();
		GEditor->RequestEndPlayMap();
		return true;
	}));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDPairSmoke, "RuneDelve.Smoke.Pair", SmokeFlags)
bool FRDPairSmoke::RunTest(const FString&)
{
	if (!ContentReady(*this))
	{
		return false;
	}
	GResults.Reset();
	AutomationOpenMap(RDAssets::Map);   // the editor world must be the Delve map before the runs start PIE on it
	for (const ERDBotMode Bot : {ERDBotMode::Masher, ERDBotMode::Weaver})
	{
		for (const int32 Seed : Seeds())
		{
			ADD_LATENT_AUTOMATION_COMMAND(FRDPlayDelve(this, Bot, Seed));
		}
	}
	ADD_LATENT_AUTOMATION_COMMAND(FRDJudgePair(this));
	return true;
}

#endif // WITH_EDITOR
