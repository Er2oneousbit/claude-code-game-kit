// ---------------------------------------------------------------------------
// GameKitPlatformSteam.h
// Purpose : The Steam backend's mapping for the platform layer (#84, docs/PLATFORM.md): which Steamworks call each
//           platform call becomes, over a table of functions (FSteamCalls), so automation tests run it with fakes.
//           GameKitShellUI's GameKitPlatformBackends.cpp fills the table from the Steamworks SDK that ships with
//           Unreal (the engine's "Steamworks" module) when the build turns GAMEKIT_STEAM on.
// Usage   : GameKit::FSteamCalls Calls = ...;   // tests: lambdas; a Steam build: the SDK
//           TUniquePtr<GameKit::IPlatformBackend> B = MakeUnique<GameKit::FSteamPlatformBackend>(Defs, DataDir, Calls);
// Notes   : A store StoreStats accepted that UserStatsStored_t later reports failed goes back to the layer through
//           TakeStoreFailure() (its stats and unlocks are queued again). Steam starts whether or not
//           data/achievements.json exists (MakeSteamBackend; presence, the overlay and cloud saves need it too). The overlay arrives through OverlayChanged() (the SDK's GameOverlayActivated_t).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): StatsStored failures reach the layer; MakeSteamBackend
//           (the start rule: Steam with or without achievements)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameKitPlatform.h"

namespace GameKit
{
	/** The Steam calls the backend needs (ISteamUserStats, ISteamFriends, ISteamRemoteStorage). */
	struct FSteamCalls
	{
		TFunction<bool(const FString&)> SetAchievement;
		TFunction<bool(const FString&, bool&)> GetAchievement;
		TFunction<bool(const FString&, int32)> SetStatInt;
		TFunction<bool(const FString&, float)> SetStatFloat;
		TFunction<bool(const FString&, int32&)> GetStatInt;
		TFunction<bool(const FString&, float&)> GetStatFloat;
		TFunction<bool()> StoreStats;
		TFunction<bool(const FString&, uint32, uint32)> IndicateProgress;
		TFunction<bool(bool)> ResetAllStats;
		TFunction<bool(const FString&, const FString&)> SetRichPresence;
		TFunction<void()> ClearRichPresence;
		TFunction<bool(const FString&, const TArray<uint8>&)> FileWrite;
		TFunction<void()> RunCallbacks;
		TFunction<void()> Shutdown;
	};

	class GAMEKITSHELL_API FSteamPlatformBackend : public IPlatformBackend
	{
	public:
		FSteamPlatformBackend(const TSharedRef<FJsonObject>& InDefs, const FString& InDataDir, FSteamCalls InCalls);
		virtual ~FSteamPlatformBackend() override;
		virtual FString Name() const override { return TEXT("steam"); }
		virtual bool Available() override { return true; }
		virtual TSharedRef<FJsonObject> Remote() override;
		virtual bool Send(const TArray<TSharedPtr<FJsonValue>>& Call) override;
		virtual TOptional<bool> Update() override;
		/** The SDK half reports the overlay here; Update() hands it to the shell once. */
		void OverlayChanged(bool bActive) { Overlay = bActive; }
		/** The SDK half reports UserStatsStored_t here (true: k_EResultOK); a failure queues that store's batch. */
		void StatsStored(bool bOk);
		virtual TOptional<TArray<TSharedPtr<FJsonValue>>> TakeStoreFailure() override;

	private:
		bool IsInt(const FString& Id) const;
		TSharedRef<FJsonObject> Defs;
		FString DataDir;
		FSteamCalls Calls;
		TOptional<bool> Overlay;
		TArray<TSharedPtr<FJsonValue>> Staged;            // set_stat / set_achievement since the last store_stats
		TArray<TArray<TSharedPtr<FJsonValue>>> Inflight;  // batches stores accepted, until their UserStatsStored
		TArray<TArray<TSharedPtr<FJsonValue>>> Failed;    // batches whose UserStatsStored failed
	};

	/** The Steam backend when Init() succeeds (SteamAPI_Init in a Steam build), whatever Defs holds (none is fine),
	 *  else null; bAutomated: null. GameKitShellUI's MakePlatformBackend uses it with the SDK; tests pass fakes. */
	GAMEKITSHELL_API TUniquePtr<FSteamPlatformBackend> MakeSteamBackend(const TSharedRef<FJsonObject>& Defs, const FString& DataDir,
	                                                                     bool bAutomated, TFunctionRef<bool()> Init,
	                                                                     TFunctionRef<FSteamCalls()> MakeCalls);
}
