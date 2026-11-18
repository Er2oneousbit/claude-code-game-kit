// ---------------------------------------------------------------------------
// GameKitPlatformTests.cpp
// Purpose : Checks the platform layer (GameKitPlatform.h) against every case of data/golden/platform.json, then the
//           FPlatformService the shell owns: the cached state file, the save hook, nothing written without
//           data/achievements.json.
// Usage   : python tools/dev.py test --filter GameKit.Golden.Platform     (GameKit.Platform for the service tests)
// Notes   : A case type this file does not know fails. A step's calls are what the rules sent to their backend
//           during that step; "fail_store" is the null backend's hook (its next store_stats fails). Expected values
//           are read from the file at test time. Numbers compare within the file's tolerance (GameKit::Json::Diff).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitAtomicFile.h"
#include "GameKitJson.h"
#include "GameKitPlatform.h"
#include "GameKitSaveStore.h"
#include "HAL/FileManager.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

namespace GameKitPlatformTests
{
	using namespace GameKit::Json;
	using FValues = TArray<TSharedPtr<FJsonValue>>;

	constexpr EAutomationTestFlags PlatformTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;
	constexpr const TCHAR* Sample = TEXT("{\"stats\": [{\"id\": \"kills\", \"max\": 100, \"increment_only\": true}], \"achievements\": [{\"id\": \"first\", \"name\": \"First\"}, {\"id\": \"kills_10\", \"name\": \"Ten\", \"stat\": \"kills\", \"threshold\": 10}]}");

	struct FRun
	{
		FAutomationTestBase& Test;
		double Tolerance = 1e-6;
		int32 Checks = 0;

		void Same(const TSharedPtr<FJsonValue>& Got, const TSharedPtr<FJsonValue>& Want, const FString& What)
		{
			++Checks;
			const FString D = Diff(Got, Want, Tolerance);
			if (!D.IsEmpty())
			{
				Test.AddError(FString::Printf(TEXT("%s: %s"), *What, *D));
			}
		}
	};

	TOptional<FString> OptionalText(const TSharedPtr<FJsonValue>& V)
	{
		return Is(V, EJson::String) ? TOptional<FString>(V->AsString()) : TOptional<FString>();
	}

	TSharedPtr<FJsonValue> Strings(const TArray<FString>& List)
	{
		return MakeStringArray(List);
	}

	GameKit::FPlatformOut Step(GameKit::FPlatformRules& P, GameKit::FNullPlatformBackend& Nb, const FValues& Op)
	{
		const FString Kind = Op[0]->AsString();
		auto S = [&Op](int32 N) { return Op[N]->AsString(); };
		if (Kind == TEXT("fail_store"))
		{
			++Nb.FailStores;
			return {MakeNull(), {}};
		}
		if (Kind == TEXT("overlay"))
		{
			return {MakeString(GameKit::OverlayAction(Op[1]->AsBool(), S(2))), {}};
		}
		if (Kind == TEXT("unlock")) return P.Unlock(S(1));
		if (Kind == TEXT("set_stat")) return P.SetStat(S(1), Op[2]);
		if (Kind == TEXT("add_stat")) return P.AddStat(S(1), Op[2]);
		if (Kind == TEXT("flush")) return P.Flush();
		if (Kind == TEXT("set_presence")) return P.SetPresence(Op[1], Op[2]);
		if (Kind == TEXT("clear_presence")) return P.ClearPresence();
		if (Kind == TEXT("saved")) return P.Saved(S(1));
		if (Kind == TEXT("connect")) return P.Connect(Op[1]->AsObject());
		if (Kind == TEXT("disconnect")) return P.Disconnect();
		if (Kind == TEXT("reset_all")) return P.ResetAll();
		return {MakeString(TEXT("unknown step ") + Kind), {}};
	}

	bool RunCase(FRun& R, const TSharedPtr<FJsonObject>& C)
	{
		const FString Type = C->GetStringField(TEXT("type"));
		const FString Name = C->GetStringField(TEXT("name"));
		if (Type == TEXT("platform_format"))
		{
			TSharedRef<FJsonObject> Mine = CloneObject(C);
			Mine->SetStringField(TEXT("state_format"), GameKit::PlatformFormat);
			Mine->SetStringField(TEXT("state_file"), GameKit::PlatformStateFile);
			Mine->SetNumberField(TEXT("state_version"), GameKit::PlatformStateVersion);
			Mine->SetNumberField(TEXT("id_max"), GameKit::PlatformIdMax);
			Mine->SetField(TEXT("stat_types"), Strings(GameKit::PlatformStatTypes()));
			Mine->SetNumberField(TEXT("presence_max_keys"), GameKit::PresenceMaxKeys);
			Mine->SetNumberField(TEXT("presence_max_value_bytes"), GameKit::PresenceMaxValueBytes);
			Mine->SetField(TEXT("cloud_modes"), Strings(GameKit::PlatformCloudModes()));
			Mine->SetField(TEXT("cloud_local_names"), Strings(GameKit::CloudLocalNames()));
			Mine->SetField(TEXT("cloud_local_suffixes"), Strings(GameKit::CloudLocalSuffixes()));
			Mine->SetField(TEXT("cloud_local_dirs"), Strings(GameKit::CloudLocalDirs()));
			Mine->SetField(TEXT("overlay_pause_screens"), Strings(GameKit::OverlayPauseScreens()));
			R.Same(MakeObject(Mine), MakeObject(C), TEXT("format"));
		}
		else if (Type == TEXT("achievements_load"))
		{
			for (const TSharedPtr<FJsonValue>& P : C->GetArrayField(TEXT("points")))
			{
				const FValues& Pt = P->AsArray();
				int32 Problems = 0;
				const TSharedRef<FJsonObject> Defs = GameKit::AchievementsLoad(OptionalText(Pt[1]), Problems);
				R.Same(MakeObject(Defs), Pt[2], Pt[0]->AsString() + TEXT(": defs"));
				R.Same(MakeNumber(Problems), Pt[3], Pt[0]->AsString() + TEXT(": problems"));
			}
		}
		else if (Type == TEXT("cloud_partition"))
		{
			for (const TSharedPtr<FJsonValue>& P : C->GetArrayField(TEXT("points")))
			{
				const FValues& Pt = P->AsArray();
				R.Same(MakeString(GameKit::CloudPartition(Pt[0]->AsString())), Pt[1], TEXT("\"") + Pt[0]->AsString() + TEXT("\""));
			}
		}
		else if (Type == TEXT("overlay"))
		{
			for (const TSharedPtr<FJsonValue>& P : C->GetArrayField(TEXT("points")))
			{
				const FValues& Pt = P->AsArray();
				R.Same(MakeString(GameKit::OverlayAction(Pt[0]->AsBool(), Pt[1]->AsString())), Pt[2], Write(P, 0));
			}
		}
		else if (Type == TEXT("platform_script"))
		{
			GameKit::FNullPlatformBackend Nb;
			GameKit::FPlatformRules P(C->GetObjectField(TEXT("defs")).ToSharedRef(), &Nb, C->GetBoolField(TEXT("online")),
			                          C->GetStringField(TEXT("cloud")));
			int32 I = 0;
			for (const TSharedPtr<FJsonValue>& SV : C->GetArrayField(TEXT("steps")))
			{
				const TSharedPtr<FJsonObject> S = SV->AsObject();
				const FValues& Op = S->GetArrayField(TEXT("op"));
				const GameKit::FPlatformOut Out = Step(P, Nb, Op);
				const FString W = FString::Printf(TEXT("%s step %d %s"), *Name, I++, *Write(S->TryGetField(TEXT("op")), 0));
				R.Same(Out.Out, S->TryGetField(TEXT("out")), W + TEXT(": out"));
				R.Same(MakeArray(Out.Calls), S->TryGetField(TEXT("calls")), W + TEXT(": calls"));
				R.Same(MakeObject(P.State()), S->TryGetField(TEXT("state")), W + TEXT(": state"));
				R.Same(MakeArray(P.PresenceList()), S->TryGetField(TEXT("presence")), W + TEXT(": presence"));
				R.Same(MakeBool(P.IsOnline()), S->TryGetField(TEXT("online")), W + TEXT(": online"));
			}
		}
		else if (Type == TEXT("platform_state_load"))
		{
			const TSharedRef<FJsonObject> Defs = C->GetObjectField(TEXT("defs")).ToSharedRef();
			for (const TSharedPtr<FJsonValue>& P : C->GetArrayField(TEXT("points")))
			{
				const FValues& Pt = P->AsArray();
				int32 Problems = 0;
				const TSharedRef<FJsonObject> St = GameKit::PlatformStateLoad(Defs, OptionalText(Pt[1]), Problems);
				R.Same(MakeObject(St), Pt[2], Pt[0]->AsString() + TEXT(": state"));
				R.Same(MakeNumber(Problems), Pt[3], Pt[0]->AsString() + TEXT(": problems"));
			}
		}
		else if (Type == TEXT("null_backend"))
		{
			GameKit::FNullPlatformBackend Nb;
			int32 I = 0;
			for (const TSharedPtr<FJsonValue>& SV : C->GetArrayField(TEXT("sends")))
			{
				const FValues& S = SV->AsArray();
				const FValues& Call = S[0]->AsArray();
				TSharedPtr<FJsonValue> Got = MakeNull();
				if (Call.Num() == 1 && Call[0]->AsString() == TEXT("fail_next_store"))
				{
					++Nb.FailStores;
				}
				else
				{
					Got = MakeBool(Nb.Send(Call));
				}
				const FString W = FString::Printf(TEXT("send %d %s"), I++, *Write(S[0], 0));
				R.Same(Got, S[1], W + TEXT(": ok"));
				R.Same(MakeObject(Nb.Remote()), S[2], W + TEXT(": remote"));
				R.Same(MakeArray(Nb.PresenceList()), S[3], W + TEXT(": presence"));
				R.Same(MakeStringArray(Nb.Cloud), S[4], W + TEXT(": cloud"));
			}
			R.Same(MakeArray(Nb.Calls), C->TryGetField(TEXT("calls")), TEXT("calls"));
		}
		else
		{
			return false;
		}
		return true;
	}

	FString Scratch()
	{
		const FString Dir = FPaths::Combine(FPaths::ProjectIntermediateDir(), TEXT("platform-test-Í-") + FGuid::NewGuid().ToString());
		IFileManager::Get().MakeDirectory(*Dir, true);
		return Dir;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitGoldenPlatformTest, "GameKit.Golden.Platform", GameKitPlatformTests::PlatformTestFlags)

bool FGameKitGoldenPlatformTest::RunTest(const FString& Parameters)
{
	using namespace GameKitPlatformTests;
	const FString Path = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("data/golden/platform.json")));
	const TOptional<FString> Text = GameKit::ReadTextFile(Path);
	if (!Text.IsSet())
	{
		AddError(Path + TEXT(" not found (data/golden ships with every kit game)"));
		return false;
	}
	const TSharedPtr<FJsonValue> Root = Parse(Text.GetValue());
	if (!Is(Root, EJson::Object))
	{
		AddError(Path + TEXT(" is not a JSON object"));
		return false;
	}
	FRun R{*this, GetNumber(Root->AsObject(), TEXT("tolerance"), 1e-6)};
	int32 Cases = 0;
	for (const TSharedPtr<FJsonValue>& C : Root->AsObject()->GetArrayField(TEXT("cases")))
	{
		if (!RunCase(R, C->AsObject()))
		{
			AddError(TEXT("unknown case type ") + C->AsObject()->GetStringField(TEXT("type")) + TEXT(": port it, then add it here"));
		}
		++Cases;
	}
	AddInfo(FString::Printf(TEXT("platform.json: %d cases, %d values checked"), Cases, R.Checks));
	TestTrue(TEXT("platform.json has its 19 cases or more"), Cases >= 19);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitPlatformServiceTest, "GameKit.Platform.Service", GameKitPlatformTests::PlatformTestFlags)

bool FGameKitPlatformServiceTest::RunTest(const FString& Parameters)
{
	using namespace GameKitPlatformTests;
	{
		const FString Dir = Scratch();
		GameKit::FPlatformService Ps(Dir, TOptional<FString>());
		TestFalse(TEXT("no achievements: inactive"), Ps.IsActive());
		TestEqual(TEXT("unknown"), Ps.Unlock(TEXT("first")), FString(TEXT("unknown")));
		TestEqual(TEXT("nothing"), Ps.Flush(), FString(TEXT("nothing")));
		TestEqual(TEXT("cloud"), Ps.Saved(TEXT("save_1.json")), FString(TEXT("cloud")));
		TArray<FString> Files;
		IFileManager::Get().FindFiles(Files, *FPaths::Combine(Dir, TEXT("*")), true, true);
		TestEqual(TEXT("no file without data/achievements.json"), Files.Num(), 0);
		IFileManager::Get().DeleteDirectory(*Dir, false, true);
	}
	{
		const FString Dir = Scratch();
		{
			GameKit::FPlatformService Ps(Dir, FString(Sample));
			TestEqual(TEXT("add"), Ps.AddStat(TEXT("kills"), 12), FString(TEXT("ok")));
			TestEqual(TEXT("unlock"), Ps.Unlock(TEXT("first")), FString(TEXT("unlocked")));
		}
		GameKit::FPlatformService Again(Dir, FString(Sample));
		const TArray<FString> Want{TEXT("kills_10"), TEXT("first")};
		TestTrue(TEXT("reloaded unlocks"), Again.GetRules().GetUnlocked() == Want);
		TestEqual(TEXT("already"), Again.Unlock(TEXT("first")), FString(TEXT("already")));
		TestFalse(TEXT("no .tmp"), IFileManager::Get().FileExists(*FPaths::Combine(Dir, TEXT("platform_state.json.tmp"))));
		IFileManager::Get().DeleteDirectory(*Dir, false, true);
	}
	{
		const FString Dir = Scratch();
		GameKit::FPlatformService Ps(Dir, FString(Sample), nullptr, TEXT("api"));
		FGameKitSaveStore Store(FPaths::Combine(Dir, TEXT("save_1.json")));
		TArray<FString> Seen;
		Store.OnSaved = [&Seen, &Ps](const FString& Name)
		{
			Seen.Add(Name);
			Ps.Saved(Name);
		};
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetNumberField(TEXT("level"), 1);
		TestTrue(TEXT("saved"), Store.Save(Data));
		TestTrue(TEXT("the hook saw save_1.json"), Seen.Num() == 1 && Seen[0] == TEXT("save_1.json"));
		const GameKit::FNullPlatformBackend& Nb = static_cast<GameKit::FNullPlatformBackend&>(Ps.GetBackend());
		TestTrue(TEXT("api mode: one cloud write"), Nb.Cloud.Num() == 1 && Nb.Cloud[0] == TEXT("save_1.json"));
		IFileManager::Get().DeleteDirectory(*Dir, false, true);
	}
	return true;
}

#endif   // WITH_DEV_AUTOMATION_TESTS

// {{FOOTER}}
