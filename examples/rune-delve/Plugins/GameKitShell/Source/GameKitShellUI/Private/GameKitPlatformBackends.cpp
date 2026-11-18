// ---------------------------------------------------------------------------
// GameKitPlatformBackends.cpp
// Purpose : MakePlatformBackend (see GameKitPlatformBackends.h): the null backend in every build, and Steam's when
//           GameKitShellUI.Build.cs turns GAMEKIT_STEAM on (the engine's own Steamworks module, the SDK that ships
//           with Unreal) and Steam starts.
// Usage   : see GameKitPlatformBackends.h
// Notes   : The SDK calls follow the Steamworks API reference for the SDK Unreal bundles (v1.64 in UE 5.8; verify
//           after an engine upgrade). STEAM_CALLBACK registers the overlay listener while the backend lives.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): UserStatsStored_t reaches the backend; MakeSteamBackend
// ---------------------------------------------------------------------------
#include "GameKitPlatformBackends.h"

#include "GameKitPlatformSteam.h"
#include "GameKitShellLog.h"

#if GAMEKIT_STEAM
THIRD_PARTY_INCLUDES_START
#include "steam/steam_api.h"
THIRD_PARTY_INCLUDES_END
#endif

namespace GameKit
{
#if GAMEKIT_STEAM
	namespace
	{
		/** The SDK's overlay callback, forwarded to the backend. */
		struct FOverlayListener
		{
			FSteamPlatformBackend* Backend = nullptr;
			STEAM_CALLBACK(FOverlayListener, OnOverlay, GameOverlayActivated_t);
			STEAM_CALLBACK(FOverlayListener, OnStatsStored, UserStatsStored_t);
		};

		void FOverlayListener::OnStatsStored(UserStatsStored_t* E)
		{
			if (Backend)
			{
				Backend->StatsStored(E->m_eResult == k_EResultOK);
			}
		}

		void FOverlayListener::OnOverlay(GameOverlayActivated_t* E)
		{
			if (Backend)
			{
				Backend->OverlayChanged(E->m_bActive != 0);
			}
		}

		FOverlayListener* GListener = nullptr;

		FSteamCalls SteamworksCalls()
		{
			FSteamCalls C;
			C.SetAchievement = [](const FString& Id) { return SteamUserStats()->SetAchievement(TCHAR_TO_UTF8(*Id)); };
			C.GetAchievement = [](const FString& Id, bool& bOut) { return SteamUserStats()->GetAchievement(TCHAR_TO_UTF8(*Id), &bOut); };
			C.SetStatInt = [](const FString& Id, int32 V) { return SteamUserStats()->SetStat(TCHAR_TO_UTF8(*Id), V); };
			C.SetStatFloat = [](const FString& Id, float V) { return SteamUserStats()->SetStat(TCHAR_TO_UTF8(*Id), V); };
			C.GetStatInt = [](const FString& Id, int32& Out) { return SteamUserStats()->GetStat(TCHAR_TO_UTF8(*Id), &Out); };
			C.GetStatFloat = [](const FString& Id, float& Out) { return SteamUserStats()->GetStat(TCHAR_TO_UTF8(*Id), &Out); };
			C.StoreStats = [] { return SteamUserStats()->StoreStats(); };
			C.IndicateProgress = [](const FString& Id, uint32 Cur, uint32 Max)
			{
				return SteamUserStats()->IndicateAchievementProgress(TCHAR_TO_UTF8(*Id), Cur, Max);
			};
			C.ResetAllStats = [](bool bAchievements) { return SteamUserStats()->ResetAllStats(bAchievements); };
			C.SetRichPresence = [](const FString& K, const FString& V)
			{
				return SteamFriends()->SetRichPresence(TCHAR_TO_UTF8(*K), TCHAR_TO_UTF8(*V));
			};
			C.ClearRichPresence = [] { SteamFriends()->ClearRichPresence(); };
			C.FileWrite = [](const FString& Name, const TArray<uint8>& Bytes)
			{
				return SteamRemoteStorage()->FileWrite(TCHAR_TO_UTF8(*Name), Bytes.GetData(), Bytes.Num());
			};
			C.RunCallbacks = [] { SteamAPI_RunCallbacks(); };
			C.Shutdown = []
			{
				delete GListener;
				GListener = nullptr;
				SteamAPI_Shutdown();
			};
			return C;
		}
	}
#endif

	TUniquePtr<IPlatformBackend> MakePlatformBackend(const TSharedRef<FJsonObject>& Defs, const FString& DataDir, bool bAutomated)
	{
#if GAMEKIT_STEAM
		TUniquePtr<FSteamPlatformBackend> Backend = MakeSteamBackend(Defs, DataDir, bAutomated, [bAutomated]
		{
			const bool bOk = SteamAPI_Init();
			if (!bOk && !bAutomated)
			{
				UE_LOG(LogGameKitShell, Warning, TEXT("platform: built with Steam, but Steam did not start: the null backend runs"));
			}
			return bOk;
		}, [] { return SteamworksCalls(); });
		if (Backend.IsValid())
		{
			GListener = new FOverlayListener();
			GListener->Backend = Backend.Get();
		}
		return Backend;
#else
		return nullptr;   // the null backend: this build has no Steam
#endif
	}
}
