// ---------------------------------------------------------------------------
// RDRegressionTests.cpp
// Purpose : Regression tests in Play In Editor for the defects a code review found (2026-10-26), each stage
//           asserting the fixed behaviour on the real map:
//           1. Ward: one ward blocks one swing (it used to block every swing for its whole 0.45 s window).
//           2. Swing: when an orc's hit lands, its attack clip is at its contact frame (it used to start then).
//           3. Dash: a dash right behind a fresh bolt slides the full DashDistance (the mage's own bolt used to
//              block it) and the mage dodges on every frame of the slide.
//           4. Doorway: a sleeping grunt shot from the next room through an open gate wakes and hunts (being
//              hurt was discarded unless the mage stood in the orc's room, so it could be sniped asleep).
//           The warden-on-a-grunt's-tile spawn fix is checked over 300 seeds by RuneDelve.Core.Level.
// Usage   : python tools/dev.py smoke --filter Regressions      (also part of a plain `smoke`)
// Notes   : One PIE session on seed 7 (room 1's grunts stand on tiles (17,1), (16,0) and (15,0), a clear line
//           from room 0 through gate 0). Every frame is 1/60 s; the test steps once per frame. Ported from the
//           reviewer's probes in a scratch copy, which asserted the expected behaviour and failed before the fixes.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5), from probes by Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_EDITOR

#include "Abilities/RDEffects.h"
#include "Abilities/RDTags.h"
#include "Animation/AnimSingleNodeInstance.h"
#include "Components/SkeletalMeshComponent.h"
#include "Core/RDLevel.h"
#include "Core/RDOrcBrain.h"
#include "Editor.h"
#include "Engine/Engine.h"
#include "Game/RDCommon.h"
#include "Game/RDGameMode.h"
#include "Game/RDMage.h"
#include "Game/RDOrc.h"
#include "Game/RDTuning.h"
#include "Misc/App.h"
#include "Misc/PackageName.h"
#include "NavigationSystem.h"
#include "Settings/LevelEditorPlaySettings.h"
#include "Tests/AutomationCommon.h"

namespace
{
	constexpr EAutomationTestFlags RegressionFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;
	constexpr int32 RegressionSeed = 7;
	constexpr double WallTimeoutSeconds = 300.0;   // real time for the whole session
	constexpr int32 StageTimeoutFrames = 900;      // 15 s of game time for any one stage
	constexpr float FrameSeconds = 1.f / 60.f;
	constexpr float DashToleranceCm = 2.f;
	constexpr float SwingToleranceSeconds = 2.5f * FrameSeconds;   // the test reads the clip a frame after the hit
	constexpr float WakeMoveCm = 50.f;             // a woken grunt has clearly left its tile

	UWorld* RegressionWorld()
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

	ARDOrc* OrcNear(ARDGameMode& Game, const FVector2D& Where)
	{
		ARDOrc* Best = nullptr;
		float BestD = TNumericLimits<float>::Max();
		for (const TObjectPtr<ARDOrc>& Entry : Game.GetOrcs())
		{
			ARDOrc* O = Entry.Get();
			const float D = O ? FVector2D::Distance(O->Ground(), Where) : BestD;
			if (D < BestD)
			{
				BestD = D;
				Best = O;
			}
		}
		return Best;
	}

	void Teleport(ARDMage& Mage, const FVector2D& To)
	{
		Mage.SetActorLocation(FVector(To, Mage.GetActorLocation().Z), false, nullptr, ETeleportType::TeleportPhysics);
	}
}

/** One PIE session on RegressionSeed; Step runs once per game frame until it returns true. */
class FRDRegressionSession : public IAutomationLatentCommand
{
public:
	using FStep = TFunction<bool(FAutomationTestBase&, ARDGameMode&, int32)>;
	FRDRegressionSession(FAutomationTestBase* InTest, FStep InStep) : Test(InTest), Step(MoveTemp(InStep)) {}
	virtual ~FRDRegressionSession() override
	{
		if (Settings)
		{
			Settings->RemoveFromRoot();
		}
	}

	virtual bool Update() override
	{
		if (Phase == 0)   // end any earlier session, then request PIE directly (see FRDPlayDelve in RDSmokeTests.cpp)
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
			O.Seed = RegressionSeed;
			O.bFixedFps = true;
			FRDLaunchOptions::SetTestOverride(O);
			FRequestPlaySessionParams Params;
			Settings = NewObject<ULevelEditorPlaySettings>();
			Settings->AddToRoot();
			Settings->SetPlayNumberOfClients(1);
			Settings->bLaunchSeparateServer = false;
			Params.EditorPlaySettings = Settings;
			GEditor->RequestPlaySession(Params);
			GEditor->StartQueuedPlaySessionRequest();
			Started = FPlatformTime::Seconds();
			Phase = 1;
			return false;
		}
		UWorld* World = RegressionWorld();
		ARDGameMode* Game = World ? World->GetAuthGameMode<ARDGameMode>() : nullptr;
		if (Game && Step(*Test, *Game, Frame++))
		{
			Stop();
			return true;
		}
		if (FPlatformTime::Seconds() - Started > WallTimeoutSeconds)
		{
			Test->AddError(TEXT("the regression session timed out"));
			Stop();
			return true;
		}
		return false;
	}

private:
	static void Stop()
	{
		FApp::SetUseFixedTimeStep(false);
		FApp::SetBenchmarking(false);
		FRDLaunchOptions::ClearTestOverride();
		GEditor->RequestEndPlayMap();
	}

	FAutomationTestBase* Test;
	FStep Step;
	int32 Phase = 0;
	int32 Frame = 0;
	bool bEndRequested = false;
	double Started = 0.0;
	ULevelEditorPlaySettings* Settings = nullptr;
};

enum class ERDRegStage : uint8
{
	WaitReady,
	Ward,
	Swing,
	ClearRoom,
	Dash,
	Doorway,
	Done
};

struct FRDRegressionState
{
	ERDRegStage Stage = ERDRegStage::WaitReady;
	int32 StageFrame = 0;
	TMap<TWeakObjectPtr<ARDOrc>, ERDOrcState> LastStates;
	FVector2D DashStart = FVector2D::ZeroVector;
	int32 DashFrames = 0;
	int32 DashFramesUndodged = 0;
	TWeakObjectPtr<ARDOrc> Target;
	FVector2D TargetStart = FVector2D::ZeroVector;
	float TargetHealth = 0.f;
	int32 HitFrame = -1;
	int32 WakeFrame = -1;

	void Go(ERDRegStage Next, int32 Frame)
	{
		Stage = Next;
		StageFrame = Frame;
	}
};

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRDRegressionSmoke, "RuneDelve.Smoke.Regressions", RegressionFlags)
bool FRDRegressionSmoke::RunTest(const FString&)
{
	if (!FPackageName::DoesPackageExist(RDAssets::Map))
	{
		AddError(TEXT("no Delve map: run python tools/dev.py exec tools/unreal/build_content.py first"));
		return false;
	}
	AutomationOpenMap(RDAssets::Map);
	TSharedPtr<FRDRegressionState> S = MakeShared<FRDRegressionState>();
	ADD_LATENT_AUTOMATION_COMMAND(FRDRegressionSession(this, [S](FAutomationTestBase& T, ARDGameMode& Game, int32 Frame) -> bool {
		ARDMage* Mage = Game.GetMage();
		if (!Mage || Mage->GetMaxHealth() <= 0.f)
		{
			return false;
		}
		const FRDNumbers N = GetDefault<URDTuning>()->Numbers();
		const int32 InStage = Frame - S->StageFrame;
		if (S->Stage != ERDRegStage::WaitReady && S->Stage != ERDRegStage::Done && InStage > StageTimeoutFrames)
		{
			T.AddError(FString::Printf(TEXT("stage %d did not finish in %d frames"), static_cast<int32>(S->Stage), StageTimeoutFrames));
			return true;
		}
		switch (S->Stage)
		{
		case ERDRegStage::WaitReady:   // the orcs chase on the runtime NavMesh, so wait for it
		{
			UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(Mage->GetWorld());
			if (Frame < 5 || (Nav && Nav->IsNavigationBuildInProgress() && Frame < 1800))
			{
				return false;
			}
			S->Go(ERDRegStage::Ward, Frame);
			return false;
		}
		case ERDRegStage::Ward:   // two swings inside one ward window: the first is blocked, the second lands
		{
			ARDOrc* Swinger = nullptr;
			for (const TObjectPtr<ARDOrc>& O : Game.GetOrcs())
			{
				if (O && O->GetRoom() == 0)
				{
					Swinger = O.Get();
					break;
				}
			}
			if (!T.TestNotNull(TEXT("ward: a room 0 grunt to swing"), Swinger))
			{
				return true;
			}
			const int32 Blocks = Mage->WardBlocks;
			const float Taken = Mage->DamageTaken;
			Mage->RaiseWard(N);
			T.TestTrue(TEXT("ward: raised"), Mage->HasTag(RDTags::State_Warded));
			Swinger->ApplyInstant(URDEffect_Damage::StaticClass(), N.Grunt.Damage, Mage->GetAbilitySystemComponent(), true);
			T.TestEqual(TEXT("ward: the first swing is blocked"), Mage->WardBlocks, Blocks + 1);
			T.TestEqual(TEXT("ward: the blocked swing does no damage"), Mage->DamageTaken, Taken);
			T.TestTrue(TEXT("ward: the block staggers the swinger"), Swinger->HasTag(RDTags::State_Staggered));
			T.TestFalse(TEXT("ward: a block spends the ward"), Mage->HasTag(RDTags::State_Warded));
			Swinger->ApplyInstant(URDEffect_Damage::StaticClass(), N.Grunt.Damage, Mage->GetAbilitySystemComponent(), true);
			T.TestEqual(TEXT("ward: a second swing in the same window is not blocked"), Mage->WardBlocks, Blocks + 1);
			T.TestEqual(TEXT("ward: the second swing lands"), Mage->DamageTaken, Taken + N.Grunt.Damage);
			// Wake room 0 for the swing stage: a light hit wakes an orc (Sleep -> Hunt)
			for (const TObjectPtr<ARDOrc>& O : Game.GetOrcs())
			{
				if (O && O->GetRoom() == 0)
				{
					Mage->ApplyInstant(URDEffect_Damage::StaticClass(), 1.f, O->GetAbilitySystemComponent());
				}
			}
			S->Go(ERDRegStage::Swing, Frame);
			return false;
		}
		case ERDRegStage::Swing:   // the first swing that lands: its clip must be at the contact frame
			for (const TObjectPtr<ARDOrc>& Entry : Game.GetOrcs())
			{
				ARDOrc* O = Entry.Get();
				if (!O || O->GetRoom() != 0)
				{
					continue;
				}
				const TWeakObjectPtr<ARDOrc> Key(O);
				const ERDOrcState Now = O->GetState();
				const ERDOrcState Was = S->LastStates.FindRef(Key, ERDOrcState::Sleep);
				S->LastStates.Add(Key, Now);
				if (Was != ERDOrcState::Windup || Now != ERDOrcState::Recover)
				{
					continue;
				}
				const UAnimSingleNodeInstance* Anim = O->GetMesh()->GetSingleNodeInstance();
				const UAnimationAsset* Clip = Anim ? Anim->GetAnimationAsset() : nullptr;
				const float At = Anim ? Anim->GetCurrentTime() : -1.f;
				UE_LOG(LogRuneDelve, Display, TEXT("[test] swing landed: clip %s at %.3f s (contact frame %.3f s)"),
				       Clip ? *Clip->GetName() : TEXT("none"), At, ARDOrc::ContactDelay);
				T.TestTrue(TEXT("swing: the attack clip plays when the hit lands"), Clip && Clip->GetName().EndsWith(ARDOrc::SwingAnim));
				T.TestTrue(FString::Printf(TEXT("swing: the clip is at its contact frame when the hit lands (%.3f s, want %.3f)"), At, ARDOrc::ContactDelay),
				           FMath::Abs(At - ARDOrc::ContactDelay) <= SwingToleranceSeconds);
				S->Go(ERDRegStage::ClearRoom, Frame);
				return false;
			}
			return false;
		case ERDRegStage::ClearRoom:   // room 0's orcs out of the way; its gate opens
			if (InStage == 1)   // stages start one frame after the Go() call
			{
				for (const TObjectPtr<ARDOrc>& O : Game.GetOrcs())
				{
					if (O && O->GetRoom() == 0 && O->IsAlive())
					{
						Mage->ApplyInstant(URDEffect_Damage::StaticClass(), 1000.f, O->GetAbilitySystemComponent());
					}
				}
				return false;
			}
			if (InStage < 11)
			{
				return false;
			}
			if (!T.TestEqual(TEXT("room 0 cleared"), Game.RoomsCleared(), 1))
			{
				return true;
			}
			Teleport(*Mage, FRDLevel::MageStart());
			Mage->SetAimForTest(FRDLevel::MageStart() + FVector2D(1000.f, 0.f));
			S->Go(ERDRegStage::Dash, Frame);
			return false;
		case ERDRegStage::Dash:   // bolt, then dash the same way in the same frame (the dash outruns the bolt)
			if (InStage == 1)     // one frame for the mage to turn to the aim
			{
				S->DashStart = Mage->Ground();
				Mage->FireBolt(N);
				Mage->StartDash(N);
				T.TestTrue(TEXT("dash: dodging from the start"), Mage->HasTag(RDTags::State_Dashing));
				return false;
			}
			if (InStage < 1)
			{
				return false;
			}
			if (Mage->IsDashing())
			{
				++S->DashFrames;
				S->DashFramesUndodged += Mage->HasTag(RDTags::State_Dashing) ? 0 : 1;
				return false;
			}
			{
				const float Slid = FVector2D::Distance(S->DashStart, Mage->Ground());
				UE_LOG(LogRuneDelve, Display, TEXT("[test] dash: %.1f cm in %d frames (want %.1f cm)"), Slid, S->DashFrames + 1, N.DashDistance);
				T.TestTrue(FString::Printf(TEXT("dash: the full DashDistance behind a fresh bolt (%.1f cm, want %.1f)"), Slid, N.DashDistance),
				           FMath::Abs(Slid - N.DashDistance) <= DashToleranceCm);
				T.TestEqual(TEXT("dash: dodging on every frame of the slide"), S->DashFramesUndodged, 0);
				T.TestFalse(TEXT("dash: the dodge ends with the slide"), Mage->HasTag(RDTags::State_Dashing));
			}
			Teleport(*Mage, FVector2D(1700.f, 0.f));   // room 0, next to the open gate 0
			Mage->SetAimForTest(FRDLevel::TileToWorld(15, 0));
			S->Target = OrcNear(Game, FRDLevel::TileToWorld(15, 0));
			S->Go(ERDRegStage::Doorway, Frame);
			return false;
		case ERDRegStage::Doorway:   // shoot a sleeping room 1 grunt from room 0: it must wake and come
		{
			ARDOrc* O = S->Target.Get();
			if (!T.TestNotNull(TEXT("doorway: the grunt on tile (15,0)"), O))
			{
				return true;
			}
			if (InStage == 1)
			{
				T.TestEqual(TEXT("doorway: the mage stands in room 0"), FRDLevel::RoomOf(Mage->Ground()), 0);
				T.TestEqual(TEXT("doorway: the grunt belongs to room 1"), O->GetRoom(), 1);
				T.TestTrue(TEXT("doorway: the grunt starts asleep"), O->GetState() == ERDOrcState::Sleep);
				S->TargetStart = O->Ground();
				S->TargetHealth = O->GetHealth();
				Mage->FireBolt(N);
				return false;
			}
			if (InStage < 1)
			{
				return false;
			}
			if (S->HitFrame < 0 && O->GetHealth() < S->TargetHealth)
			{
				S->HitFrame = InStage;
			}
			if (S->HitFrame >= 0 && S->WakeFrame < 0 && O->GetState() != ERDOrcState::Sleep)
			{
				S->WakeFrame = InStage;
			}
			const float Moved = FVector2D::Distance(S->TargetStart, O->Ground());
			if (S->WakeFrame >= 0 && Moved >= WakeMoveCm)
			{
				UE_LOG(LogRuneDelve, Display, TEXT("[test] doorway: hit at frame %d, awake at %d, moved %.0f cm by %d"), S->HitFrame,
				       S->WakeFrame, Moved, InStage);
				T.TestTrue(TEXT("doorway: the shot grunt wakes at once"), S->WakeFrame - S->HitFrame <= 2);
				S->Go(ERDRegStage::Done, Frame);
				return true;
			}
			if (S->HitFrame >= 0 && InStage - S->HitFrame > 120)
			{
				T.AddError(FString::Printf(TEXT("doorway: hit at frame %d but awake %d and moved only %.0f cm in 2 s (asleep: shot from outside its room)"),
				                           S->HitFrame, S->WakeFrame >= 0 ? 1 : 0, Moved));
				return true;
			}
			if (S->HitFrame < 0 && InStage > 120)
			{
				T.AddError(TEXT("doorway: the bolt did not reach the grunt in 2 s"));
				return true;
			}
			return false;
		}
		default:
			return true;
		}
	}));
	return true;
}

#endif // WITH_EDITOR
