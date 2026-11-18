// ---------------------------------------------------------------------------
// GameKitPlatformSteam.h
// Purpose : The Steam backend's mapping for the platform layer (#84, docs/PLATFORM.md): which Steamworks call each
//           platform call becomes, over a table of functions (FSteamCalls), so automation tests run it with fakes.
//           GameKitShellUI's GameKitPlatformBackends.cpp fills the table from the Steamworks SDK that ships with
//           Unreal (the engine's "Steamworks" module) when the build turns GAMEKIT_STEAM on.
// Usage   : GameKit::FSteamCalls Calls = ...;   // tests: lambdas; a Steam build: the SDK
//           TUniquePtr<GameKit::IPlatformBackend> B = MakeUnique<GameKit::FSteamPlatformBackend>(Defs, DataDir, Calls);
// Notes   : Only StoreStats returning false counts as a failed store; a later UserStatsStored_t failure is not
//           seen (verify). The overlay arrives through OverlayChanged() (the SDK's GameOverlayActivated_t).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
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

	private:
		bool IsInt(const FString& Id) const;
		TSharedRef<FJsonObject> Defs;
		FString DataDir;
		FSteamCalls Calls;
		TOptional<bool> Overlay;
	};
}

// {{FOOTER}}
