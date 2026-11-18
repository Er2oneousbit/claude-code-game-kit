// ---------------------------------------------------------------------------
// GameKitPlatformSteam.cpp
// Purpose : FSteamPlatformBackend (see GameKitPlatformSteam.h).
// Usage   : see GameKitPlatformSteam.h
// Notes   : No Steamworks types here: the SDK half lives in GameKitShellUI (GameKitPlatformBackends.cpp).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): StatsStored, TakeStoreFailure, MakeSteamBackend
// ---------------------------------------------------------------------------
#include "GameKitPlatformSteam.h"

#include "GameKitAtomicFile.h"
#include "GameKitJson.h"
#include "Misc/Paths.h"

namespace GameKit
{
	FSteamPlatformBackend::FSteamPlatformBackend(const TSharedRef<FJsonObject>& InDefs, const FString& InDataDir, FSteamCalls InCalls)
		: Defs(InDefs), DataDir(InDataDir), Calls(MoveTemp(InCalls))
	{
	}

	FSteamPlatformBackend::~FSteamPlatformBackend()
	{
		if (Calls.Shutdown)
		{
			Calls.Shutdown();
		}
	}

	bool FSteamPlatformBackend::IsInt(const FString& Id) const
	{
		for (const TSharedPtr<FJsonValue>& V : Defs->GetArrayField(TEXT("stats")))
		{
			const TSharedPtr<FJsonObject> S = V->AsObject();
			if (S->GetStringField(TEXT("id")).Equals(Id, ESearchCase::CaseSensitive))
			{
				return S->GetStringField(TEXT("type")) == TEXT("int");
			}
		}
		return false;
	}

	TSharedRef<FJsonObject> FSteamPlatformBackend::Remote()
	{
		TArray<FString> Unlocked;
		for (const TSharedPtr<FJsonValue>& V : Defs->GetArrayField(TEXT("achievements")))
		{
			const FString Id = V->AsObject()->GetStringField(TEXT("id"));
			bool bAchieved = false;
			if (Calls.GetAchievement(Id, bAchieved) && bAchieved)
			{
				Unlocked.Add(Id);
			}
		}
		TSharedRef<FJsonObject> Stats = MakeShared<FJsonObject>();
		for (const TSharedPtr<FJsonValue>& V : Defs->GetArrayField(TEXT("stats")))
		{
			const FString Id = V->AsObject()->GetStringField(TEXT("id"));
			if (IsInt(Id))
			{
				int32 I = 0;
				if (Calls.GetStatInt(Id, I))
				{
					Stats->SetNumberField(Id, I);
				}
			}
			else
			{
				float F = 0.0f;
				if (Calls.GetStatFloat(Id, F))
				{
					Stats->SetNumberField(Id, F);
				}
			}
		}
		TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
		R->SetField(TEXT("unlocked"), Json::MakeStringArray(Unlocked));
		R->SetObjectField(TEXT("stats"), Stats);
		return R;
	}

	bool FSteamPlatformBackend::Send(const TArray<TSharedPtr<FJsonValue>>& Call)
	{
		const FString Name = Call[0]->AsString();
		auto S = [&Call](int32 N) { return Call[N]->AsString(); };
		if (Name == TEXT("set_achievement") || Name == TEXT("set_stat"))
		{
			Staged.Add(Json::MakeArray(Call));
		}
		auto N = [&Call](int32 I) { return Call[I]->AsNumber(); };
		if (Name == TEXT("set_achievement"))
		{
			Calls.SetAchievement(S(1));
		}
		else if (Name == TEXT("set_stat"))
		{
			if (IsInt(S(1)))
			{
				Calls.SetStatInt(S(1), static_cast<int32>(N(2)));
			}
			else
			{
				Calls.SetStatFloat(S(1), static_cast<float>(N(2)));
			}
		}
		else if (Name == TEXT("store_stats"))
		{
			const bool bOk = Calls.StoreStats();
			if (bOk)
			{
				Inflight.Add(Staged);
			}
			Staged.Reset();
			return bOk;
		}
		else if (Name == TEXT("indicate_progress"))
		{
			Calls.IndicateProgress(S(1), static_cast<uint32>(N(2)), static_cast<uint32>(N(3)));
		}
		else if (Name == TEXT("reset_all_stats"))
		{
			Calls.ResetAllStats(Call[1]->AsBool());
		}
		else if (Name == TEXT("set_presence"))
		{
			Calls.SetRichPresence(S(1), S(2));
		}
		else if (Name == TEXT("clear_presence"))
		{
			Calls.ClearRichPresence();
		}
		else if (Name == TEXT("cloud_write"))
		{
			if (const TOptional<TArray<uint8>> Bytes = ReadFileBytes(FPaths::Combine(DataDir, S(1))))
			{
				Calls.FileWrite(S(1), Bytes.GetValue());
			}
		}
		return true;
	}

	void FSteamPlatformBackend::StatsStored(bool bOk)
	{
		if (Inflight.IsEmpty())
		{
			return;
		}
		TArray<TSharedPtr<FJsonValue>> Batch = Inflight[0];
		Inflight.RemoveAt(0);
		if (!bOk)
		{
			Failed.Add(MoveTemp(Batch));
		}
	}

	TOptional<TArray<TSharedPtr<FJsonValue>>> FSteamPlatformBackend::TakeStoreFailure()
	{
		if (Failed.IsEmpty())
		{
			return {};
		}
		TArray<TSharedPtr<FJsonValue>> Batch = Failed[0];
		Failed.RemoveAt(0);
		return Batch;
	}

	TUniquePtr<FSteamPlatformBackend> MakeSteamBackend(const TSharedRef<FJsonObject>& Defs, const FString& DataDir, bool bAutomated,
	                                                   TFunctionRef<bool()> Init, TFunctionRef<FSteamCalls()> MakeCalls)
	{
		if (bAutomated || !Init())
		{
			return nullptr;   // an automated run never asks a store; Init false: Steam did not start
		}
		return MakeUnique<FSteamPlatformBackend>(Defs, DataDir, MakeCalls());
	}

	TOptional<bool> FSteamPlatformBackend::Update()
	{
		if (Calls.RunCallbacks)
		{
			Calls.RunCallbacks();
		}
		const TOptional<bool> Out = Overlay;
		Overlay.Reset();
		return Out;
	}
}

// {{FOOTER}}
