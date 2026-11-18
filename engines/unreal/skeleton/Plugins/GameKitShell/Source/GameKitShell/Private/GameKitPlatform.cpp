// ---------------------------------------------------------------------------
// GameKitPlatform.cpp
// Purpose : The platform layer's rules, the null backend and the service (see GameKitPlatform.h).
// Usage   : see GameKitPlatform.h
// Notes   : Ported from tools/golden_vectors.py (achievements_load, Platform, NullBackend, cloud_partition,
//           overlay_action, platform_state_load). Every FString compare that decides a rule is case-sensitive.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): FPlatformRules::StoreFailed, FPlatformService::Update
// ---------------------------------------------------------------------------
#include "GameKitPlatform.h"

#include "GameKitAtomicFile.h"
#include "GameKitJson.h"
#include "Misc/Paths.h"

namespace GameKit
{
	namespace
	{
		using namespace GameKit::Json;
		using FValues = TArray<TSharedPtr<FJsonValue>>;

		bool Same(const FString& A, const FString& B)
		{
			return A.Equals(B, ESearchCase::CaseSensitive);
		}

		bool Has(const TArray<FString>& List, const FString& V)
		{
			return List.ContainsByPredicate([&V](const FString& X) { return Same(X, V); });
		}

		void RemoveOne(TArray<FString>& List, const FString& V)
		{
			const int32 I = List.IndexOfByPredicate([&V](const FString& X) { return Same(X, V); });
			if (I != INDEX_NONE)
			{
				List.RemoveAt(I);
			}
		}

		template <typename T>
		T* FindPair(TArray<TPair<FString, T>>& Pairs, const FString& Key)
		{
			for (TPair<FString, T>& P : Pairs)
			{
				if (Same(P.Key, Key))
				{
					return &P.Value;
				}
			}
			return nullptr;
		}

		template <typename T>
		const T* FindPair(const TArray<TPair<FString, T>>& Pairs, const FString& Key)
		{
			for (const TPair<FString, T>& P : Pairs)
			{
				if (Same(P.Key, Key))
				{
					return &P.Value;
				}
			}
			return nullptr;
		}

		bool IsNull(const TSharedPtr<FJsonValue>& V)
		{
			return !V.IsValid() || V->Type == EJson::Null;
		}

		/** A finite number (a JSON boolean is never one). */
		bool NumOk(const TSharedPtr<FJsonValue>& V)
		{
			return Is(V, EJson::Number) && FMath::IsFinite(V->AsNumber());
		}

		/** Whole by value, never by type (5.0 is 5). */
		bool Whole(const TSharedPtr<FJsonValue>& V)
		{
			return NumOk(V) && FMath::FloorToDouble(V->AsNumber()) == V->AsNumber();
		}

		bool OkFor(const FString& Kind, const TSharedPtr<FJsonValue>& V)
		{
			return Same(Kind, TEXT("int")) ? Whole(V) : NumOk(V);
		}

		/** Python's dict.get(key, default): a key holding null is null, not the default. */
		TSharedPtr<FJsonValue> Get(const TSharedPtr<FJsonObject>& Obj, const FString& Key, const TSharedPtr<FJsonValue>& Default)
		{
			if (!Obj.IsValid())
			{
				return Default;
			}
			const TSharedPtr<FJsonValue> Found = Obj->TryGetField(Key);
			return Found.IsValid() ? Found : Default;
		}

		FString Str(const TSharedPtr<FJsonValue>& V)
		{
			return Is(V, EJson::String) ? V->AsString() : FString();
		}

		double Num(const TSharedPtr<FJsonValue>& V)
		{
			return Is(V, EJson::Number) ? V->AsNumber() : 0.0;
		}

		double Clamp(const TSharedPtr<FJsonObject>& SDef, double V)
		{
			V = FMath::Max(V, Num(Get(SDef, TEXT("min"), MakeNumber(0))));
			const TSharedPtr<FJsonValue> Hi = Get(SDef, TEXT("max"), MakeNull());
			return IsNull(Hi) ? V : FMath::Min(V, Num(Hi));
		}

		double Initial(const TSharedPtr<FJsonObject>& SDef)
		{
			return Clamp(SDef, 0.0);
		}

		TSharedRef<FJsonObject> EmptyDefs()
		{
			TSharedRef<FJsonObject> D = MakeShared<FJsonObject>();
			D->SetNumberField(TEXT("version"), PlatformStateVersion);
			D->SetArrayField(TEXT("stats"), FValues());
			D->SetArrayField(TEXT("achievements"), FValues());
			return D;
		}

		FValues Strings(const TArray<FString>& List)
		{
			FValues Out;
			for (const FString& S : List)
			{
				Out.Add(MakeString(S));
			}
			return Out;
		}

		FValues Call(std::initializer_list<TSharedPtr<FJsonValue>> Items)
		{
			return FValues(Items);
		}

		FValues SortedPairs(TArray<TPair<FString, FString>> Pairs)
		{
			Pairs.Sort([](const TPair<FString, FString>& A, const TPair<FString, FString>& B)
			{
				return A.Key.Compare(B.Key, ESearchCase::CaseSensitive) < 0;
			});
			FValues Out;
			for (const TPair<FString, FString>& P : Pairs)
			{
				Out.Add(MakeArray({MakeString(P.Key), MakeString(P.Value)}));
			}
			return Out;
		}
	}

	const TArray<FString>& PlatformStatTypes()
	{
		static const TArray<FString> V{TEXT("int"), TEXT("float")};
		return V;
	}
	const TArray<FString>& PlatformCloudModes()
	{
		static const TArray<FString> V{TEXT("auto"), TEXT("api")};
		return V;
	}
	const TArray<FString>& CloudLocalNames()
	{
		static const TArray<FString> V{TEXT("settings.json"), PlatformStateFile, TEXT("telemetry.csv"), TEXT("log_tail.txt")};
		return V;
	}
	const TArray<FString>& CloudLocalSuffixes()
	{
		static const TArray<FString> V{TEXT(".tmp"), TEXT(".log")};
		return V;
	}
	const TArray<FString>& CloudLocalDirs()
	{
		static const TArray<FString> V{TEXT("logs"), TEXT("crashes"), TEXT("captures")};
		return V;
	}
	const TArray<FString>& OverlayPauseScreens()
	{
		static const TArray<FString> V{TEXT("play")};
		return V;
	}

	bool PlatformIdOk(const TSharedPtr<FJsonValue>& Value)
	{
		if (!Is(Value, EJson::String))
		{
			return false;
		}
		const FString S = Value->AsString();
		if (S.IsEmpty() || S.Len() > PlatformIdMax)
		{
			return false;
		}
		for (int32 I = 0; I < S.Len(); ++I)
		{
			const TCHAR C = S[I];
			const bool bLetter = (C >= 'A' && C <= 'Z') || (C >= 'a' && C <= 'z');
			if (I == 0 && !bLetter)
			{
				return false;
			}
			if (!(bLetter || (C >= '0' && C <= '9') || C == '_'))
			{
				return false;
			}
		}
		return true;
	}

	TSharedRef<FJsonObject> AchievementsLoad(const TOptional<FString>& Text, int32& OutProblems)
	{
		OutProblems = 0;
		if (!Text.IsSet() || Text.GetValue().IsEmpty())
		{
			return EmptyDefs();
		}
		const TSharedPtr<FJsonValue> Parsed = Parse(Text.GetValue());
		if (!Is(Parsed, EJson::Object))
		{
			OutProblems = 1;
			return EmptyDefs();
		}
		const TSharedPtr<FJsonObject> Raw = Parsed->AsObject();
		FValues Stats;
		TArray<TPair<FString, TSharedPtr<FJsonObject>>> ById;
		TSharedPtr<FJsonValue> RawStats = Get(Raw, TEXT("stats"), MakeArray({}));
		if (!Is(RawStats, EJson::Array))
		{
			RawStats = MakeArray({});
			++OutProblems;
		}
		for (const TSharedPtr<FJsonValue>& Item : RawStats->AsArray())
		{
			const TSharedPtr<FJsonObject> S = Is(Item, EJson::Object) ? Item->AsObject() : nullptr;
			bool bOk = S.IsValid() && PlatformIdOk(Get(S, TEXT("id"), nullptr)) && !FindPair(ById, Str(Get(S, TEXT("id"), nullptr)));
			TSharedPtr<FJsonValue> Kind, Lo, Hi, Inc;
			if (bOk)
			{
				Kind = Get(S, TEXT("type"), MakeString(TEXT("int")));
				Lo = Get(S, TEXT("min"), MakeNumber(0));
				Hi = Get(S, TEXT("max"), MakeNull());
				Inc = Get(S, TEXT("increment_only"), MakeBool(false));
				const FString K = Str(Kind);
				bOk = Is(Kind, EJson::String) && Has(PlatformStatTypes(), K) && OkFor(K, Lo) &&
				      (IsNull(Hi) || (OkFor(K, Hi) && Num(Hi) >= Num(Lo))) && Is(Inc, EJson::Boolean);
			}
			if (!bOk)
			{
				++OutProblems;
				continue;
			}
			TSharedRef<FJsonObject> SDef = MakeShared<FJsonObject>();
			SDef->SetStringField(TEXT("id"), Str(S->TryGetField(TEXT("id"))));
			SDef->SetStringField(TEXT("type"), Str(Kind));
			SDef->SetNumberField(TEXT("min"), Num(Lo));
			SDef->SetField(TEXT("max"), IsNull(Hi) ? MakeNull() : MakeNumber(Num(Hi)));
			SDef->SetBoolField(TEXT("increment_only"), Inc->AsBool());
			ById.Add({Str(S->TryGetField(TEXT("id"))), SDef});
			Stats.Add(MakeObject(SDef));
		}
		FValues Achievements;
		TArray<FString> Seen;
		TSharedPtr<FJsonValue> RawAch = Get(Raw, TEXT("achievements"), MakeArray({}));
		if (!Is(RawAch, EJson::Array))
		{
			RawAch = MakeArray({});
			++OutProblems;
		}
		for (const TSharedPtr<FJsonValue>& Item : RawAch->AsArray())
		{
			const TSharedPtr<FJsonObject> A = Is(Item, EJson::Object) ? Item->AsObject() : nullptr;
			const TSharedPtr<FJsonValue> Name = Get(A, TEXT("name"), nullptr);
			bool bOk = A.IsValid() && PlatformIdOk(Get(A, TEXT("id"), nullptr)) && !Has(Seen, Str(Get(A, TEXT("id"), nullptr))) &&
			           Is(Name, EJson::String) && !Name->AsString().IsEmpty() &&
			           Is(Get(A, TEXT("description"), MakeString(TEXT(""))), EJson::String);
			TSharedPtr<FJsonValue> Stat, Threshold, Every;
			TSharedPtr<FJsonObject> SDef;
			if (bOk)
			{
				Stat = Get(A, TEXT("stat"), MakeNull());
				Threshold = Get(A, TEXT("threshold"), MakeNull());
				Every = Get(A, TEXT("progress_every"), MakeNull());
				if (!IsNull(Stat))
				{
					if (Is(Stat, EJson::String))
					{
						if (TSharedPtr<FJsonObject>* Found = FindPair(ById, Stat->AsString()))
						{
							SDef = *Found;
						}
					}
					const FString K = SDef.IsValid() ? Str(SDef->TryGetField(TEXT("type"))) : FString(TEXT("float"));
					bOk = SDef.IsValid() && OkFor(K, Threshold) && Num(Threshold) > Initial(SDef) &&
					      (IsNull(Get(SDef, TEXT("max"), MakeNull())) || Num(Threshold) <= Num(SDef->TryGetField(TEXT("max")))) &&
					      (IsNull(Every) || (OkFor(K, Every) && Num(Every) > 0 && Num(Every) < Num(Threshold)));
				}
				else
				{
					bOk = IsNull(Threshold) && IsNull(Every);   // a threshold without a stat is a mistake
				}
			}
			if (!bOk)
			{
				++OutProblems;
				continue;
			}
			Seen.Add(Str(A->TryGetField(TEXT("id"))));
			TSharedRef<FJsonObject> ADef = MakeShared<FJsonObject>();
			ADef->SetStringField(TEXT("id"), Str(A->TryGetField(TEXT("id"))));
			ADef->SetStringField(TEXT("name"), Name->AsString());
			ADef->SetStringField(TEXT("description"), Str(Get(A, TEXT("description"), MakeString(TEXT("")))));
			ADef->SetField(TEXT("stat"), IsNull(Stat) ? MakeNull() : MakeString(Stat->AsString()));
			ADef->SetField(TEXT("threshold"), IsNull(Stat) ? MakeNull() : MakeNumber(Num(Threshold)));
			ADef->SetField(TEXT("progress_every"), IsNull(Every) ? MakeNull() : MakeNumber(Num(Every)));
			Achievements.Add(MakeObject(ADef));
		}
		TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("version"), PlatformStateVersion);
		Out->SetArrayField(TEXT("stats"), Stats);
		Out->SetArrayField(TEXT("achievements"), Achievements);
		return Out;
	}

	FString CloudPartition(const FString& Path)
	{
		TArray<FString> Parts;
		FString Part;
		auto EndPart = [&]()
		{
			if (!Part.IsEmpty() && !Same(Part, TEXT(".")))
			{
				Parts.Add(Part);
			}
			Part.Reset();
		};
		for (const TCHAR C : Path)
		{
			if (C == '/' || C == '\\')
			{
				EndPart();
			}
			else
			{
				Part.AppendChar(C >= 'A' && C <= 'Z' ? static_cast<TCHAR>(C + 32) : C);   // ASCII only, in every port
			}
		}
		EndPart();
		if (Parts.IsEmpty())
		{
			return TEXT("local");
		}
		const FString& Name = Parts.Last();
		if ((Parts.Num() > 1 && Has(CloudLocalDirs(), Parts[0])) || Has(CloudLocalNames(), Name))
		{
			return TEXT("local");
		}
		for (const FString& S : CloudLocalSuffixes())
		{
			if (Name.EndsWith(S, ESearchCase::CaseSensitive))
			{
				return TEXT("local");
			}
		}
		return TEXT("cloud");
	}

	FString OverlayAction(bool bActive, const FString& Screen)
	{
		return bActive && Has(OverlayPauseScreens(), Screen) ? TEXT("pause") : TEXT("none");
	}

	// ---- FNullPlatformBackend ----

	TSharedRef<FJsonObject> FNullPlatformBackend::Remote()
	{
		TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
		R->SetArrayField(TEXT("unlocked"), Strings(Unlocked));
		TSharedRef<FJsonObject> S = MakeShared<FJsonObject>();
		for (const TPair<FString, TSharedPtr<FJsonValue>>& P : Stats)
		{
			S->SetField(P.Key, P.Value);
		}
		R->SetObjectField(TEXT("stats"), S);
		return R;
	}

	TArray<TSharedPtr<FJsonValue>> FNullPlatformBackend::PresenceList() const
	{
		return SortedPairs(Presence);
	}

	bool FNullPlatformBackend::Send(const TArray<TSharedPtr<FJsonValue>>& InCall)
	{
		Calls.Add(MakeArray(InCall));
		const FString Name = Str(InCall[0]);
		auto Arg = [&InCall](int32 N) { return InCall.IsValidIndex(N) ? Str(InCall[N]) : FString(); };
		if (Same(Name, TEXT("set_achievement")))
		{
			if (!Has(StagedUnlocks, Arg(1)))
			{
				StagedUnlocks.Add(Arg(1));
			}
		}
		else if (Same(Name, TEXT("set_stat")))
		{
			if (TSharedPtr<FJsonValue>* V = FindPair(StagedStats, Arg(1)))
			{
				*V = InCall[2];
			}
			else
			{
				StagedStats.Add({Arg(1), InCall[2]});
			}
		}
		else if (Same(Name, TEXT("store_stats")))
		{
			if (FailStores > 0)
			{
				--FailStores;
				return false;
			}
			for (const FString& U : StagedUnlocks)
			{
				if (!Has(Unlocked, U))
				{
					Unlocked.Add(U);
				}
			}
			for (const TPair<FString, TSharedPtr<FJsonValue>>& P : StagedStats)
			{
				if (TSharedPtr<FJsonValue>* V = FindPair(Stats, P.Key))
				{
					*V = P.Value;
				}
				else
				{
					Stats.Add(P);
				}
			}
			StagedUnlocks.Reset();
			StagedStats.Reset();
		}
		else if (Same(Name, TEXT("reset_all_stats")))
		{
			Unlocked.Reset();
			Stats.Reset();
			StagedUnlocks.Reset();
			StagedStats.Reset();
		}
		else if (Same(Name, TEXT("set_presence")))
		{
			const FString K = Arg(1), V = Arg(2);
			Presence.RemoveAll([&K](const TPair<FString, FString>& P) { return Same(P.Key, K); });
			if (!V.IsEmpty())
			{
				Presence.Add({K, V});
			}
		}
		else if (Same(Name, TEXT("clear_presence")))
		{
			Presence.Reset();
		}
		else if (Same(Name, TEXT("cloud_write")) && !Has(Cloud, Arg(1)))
		{
			Cloud.Add(Arg(1));
		}
		return true;
	}

	// ---- FPlatformRules ----

	FPlatformRules::FPlatformRules(const TSharedRef<FJsonObject>& InDefs, IPlatformBackend* InBackend, bool bInOnline, const FString& InCloud)
		: DefsObj(InDefs), Backend(InBackend), bOnline(bInOnline), Cloud(InCloud)
	{
		for (const TSharedPtr<FJsonValue>& V : DefsObj->TryGetField(TEXT("stats")).IsValid() ? DefsObj->TryGetField(TEXT("stats"))->AsArray() : FValues())
		{
			StatDefs.Add(V->AsObject());
		}
		for (const TSharedPtr<FJsonValue>& V : DefsObj->TryGetField(TEXT("achievements")).IsValid() ? DefsObj->TryGetField(TEXT("achievements"))->AsArray() : FValues())
		{
			AchDefs.Add(V->AsObject());
		}
		ResetLocal();
	}

	TSharedPtr<FJsonObject> FPlatformRules::StatDef(const FString& Id) const
	{
		for (const TSharedPtr<FJsonObject>& S : StatDefs)
		{
			if (Same(Str(S->TryGetField(TEXT("id"))), Id))
			{
				return S;
			}
		}
		return nullptr;
	}

	bool FPlatformRules::HasAchievement(const FString& Id) const
	{
		return AchDefs.ContainsByPredicate([&Id](const TSharedPtr<FJsonObject>& A) { return Same(Str(A->TryGetField(TEXT("id"))), Id); });
	}

	double FPlatformRules::StatValue(const FString& Id) const
	{
		const double* V = FindPair(StatValues, Id);
		return V ? *V : 0.0;
	}

	void FPlatformRules::SetStatValue(const FString& Id, double Value)
	{
		if (double* V = FindPair(StatValues, Id))
		{
			*V = Value;
		}
	}

	void FPlatformRules::ResetLocal()
	{
		Unlocked.Reset();
		StatValues.Reset();
		for (const TSharedPtr<FJsonObject>& S : StatDefs)
		{
			StatValues.Add({Str(S->TryGetField(TEXT("id"))), Initial(S)});
		}
		PendingStats.Reset();
		PendingUnlocks.Reset();
		PendingCloud.Reset();
	}

	TSharedRef<FJsonObject> FPlatformRules::State() const
	{
		TSharedRef<FJsonObject> St = MakeShared<FJsonObject>();
		St->SetStringField(TEXT("format"), PlatformFormat);
		St->SetNumberField(TEXT("version"), PlatformStateVersion);
		St->SetArrayField(TEXT("unlocked"), Strings(Unlocked));
		TSharedRef<FJsonObject> Stats = MakeShared<FJsonObject>();
		TArray<FString> Ps;
		for (const TPair<FString, double>& P : StatValues)
		{
			Stats->SetNumberField(P.Key, P.Value);
			if (Has(PendingStats, P.Key))
			{
				Ps.Add(P.Key);
			}
		}
		St->SetObjectField(TEXT("stats"), Stats);
		TSharedRef<FJsonObject> Pending = MakeShared<FJsonObject>();
		Pending->SetArrayField(TEXT("stats"), Strings(Ps));
		Pending->SetArrayField(TEXT("unlocks"), Strings(PendingUnlocks));
		Pending->SetArrayField(TEXT("cloud"), Strings(PendingCloud));
		St->SetObjectField(TEXT("pending"), Pending);
		return St;
	}

	void FPlatformRules::Restore(const TSharedRef<FJsonObject>& InState)
	{
		auto List = [](const TSharedPtr<FJsonValue>& V)
		{
			TArray<FString> Out;
			if (Is(V, EJson::Array))
			{
				for (const TSharedPtr<FJsonValue>& X : V->AsArray())
				{
					Out.Add(Str(X));
				}
			}
			return Out;
		};
		Unlocked = List(InState->TryGetField(TEXT("unlocked")));
		const TSharedPtr<FJsonObject> Stats = FindObject(InState, TEXT("stats"));
		if (Stats.IsValid())
		{
			for (const auto& P : Stats->Values)
			{
				SetStatValue(FString(*P.Key), Num(P.Value));
			}
		}
		const TSharedPtr<FJsonObject> Pending = FindObject(InState, TEXT("pending"));
		PendingStats = List(Get(Pending, TEXT("stats"), nullptr));
		PendingUnlocks = List(Get(Pending, TEXT("unlocks"), nullptr));
		PendingCloud = List(Get(Pending, TEXT("cloud"), nullptr));
	}

	TArray<TSharedPtr<FJsonValue>> FPlatformRules::PresenceList() const
	{
		return SortedPairs(Presence);
	}

	bool FPlatformRules::Send(const TArray<TSharedPtr<FJsonValue>>& InCall)
	{
		Sent.Add(MakeArray(InCall));
		return Backend->Send(InCall);
	}

	FPlatformOut FPlatformRules::Done(const TCHAR* Word)
	{
		FPlatformOut R{MakeString(Word), MoveTemp(Sent)};
		Sent.Reset();
		return R;
	}

	void FPlatformRules::UnlockLocal(const FString& Id)
	{
		Unlocked.Add(Id);
		PendingUnlocks.Add(Id);
	}

	FPlatformOut FPlatformRules::Unlock(const FString& Id)
	{
		if (!HasAchievement(Id))
		{
			return Done(TEXT("unknown"));
		}
		if (Has(Unlocked, Id))
		{
			return Done(TEXT("already"));
		}
		UnlockLocal(Id);
		if (bOnline)
		{
			FlushInner();
		}
		return Done(TEXT("unlocked"));
	}

	bool FPlatformRules::Check(const FString& StatId, double Old, double Now, bool bNotify)
	{
		bool bDid = false;
		for (const TSharedPtr<FJsonObject>& A : AchDefs)
		{
			const FString Id = Str(A->TryGetField(TEXT("id")));
			const TSharedPtr<FJsonValue> Stat = A->TryGetField(TEXT("stat"));
			if (!Is(Stat, EJson::String) || !Same(Stat->AsString(), StatId) || Has(Unlocked, Id))
			{
				continue;
			}
			const double Threshold = Num(A->TryGetField(TEXT("threshold")));
			if (Now >= Threshold)
			{
				UnlockLocal(Id);
				bDid = true;
			}
			else if (bNotify && bOnline && !IsNull(A->TryGetField(TEXT("progress_every"))))
			{
				const double Step = Num(A->TryGetField(TEXT("progress_every")));
				if (FMath::FloorToDouble(Now / Step) > FMath::FloorToDouble(Old / Step))
				{
					Send(Call({MakeString(TEXT("indicate_progress")), MakeString(Id), MakeNumber(Now), MakeNumber(Threshold)}));
				}
			}
		}
		return bDid;
	}

	FPlatformOut FPlatformRules::SetStat(const FString& Id, const TSharedPtr<FJsonValue>& Value)
	{
		const TSharedPtr<FJsonObject> S = StatDef(Id);
		if (!S.IsValid())
		{
			return Done(TEXT("unknown"));
		}
		if (!OkFor(Str(S->TryGetField(TEXT("type"))), Value))
		{
			return Done(TEXT("refused"));
		}
		const double C = Clamp(S, Value->AsNumber());
		const double Old = StatValue(Id);
		if (S->TryGetField(TEXT("increment_only"))->AsBool() && C < Old)
		{
			return Done(TEXT("refused"));
		}
		if (C == Old)
		{
			return Done(TEXT("same"));
		}
		SetStatValue(Id, C);
		if (!Has(PendingStats, Id))
		{
			PendingStats.Add(Id);
		}
		if (Check(Id, Old, C, true) && bOnline)
		{
			FlushInner();
		}
		return Done(C != Value->AsNumber() ? TEXT("clamped") : TEXT("ok"));
	}

	FPlatformOut FPlatformRules::AddStat(const FString& Id, const TSharedPtr<FJsonValue>& Delta)
	{
		const TSharedPtr<FJsonObject> S = StatDef(Id);
		if (!S.IsValid())
		{
			return Done(TEXT("unknown"));
		}
		if (!OkFor(Str(S->TryGetField(TEXT("type"))), Delta))
		{
			return Done(TEXT("refused"));
		}
		return SetStat(Id, MakeNumber(StatValue(Id) + Delta->AsNumber()));
	}

	const TCHAR* FPlatformRules::FlushInner()
	{
		if (!bOnline)
		{
			return TEXT("offline");
		}
		if (PendingStats.IsEmpty() && PendingUnlocks.IsEmpty() && PendingCloud.IsEmpty())
		{
			return TEXT("nothing");
		}
		if (!PendingStats.IsEmpty() || !PendingUnlocks.IsEmpty())
		{
			for (const TPair<FString, double>& P : StatValues)
			{
				if (Has(PendingStats, P.Key))
				{
					Send(Call({MakeString(TEXT("set_stat")), MakeString(P.Key), MakeNumber(P.Value)}));
				}
			}
			for (const FString& Id : PendingUnlocks)
			{
				Send(Call({MakeString(TEXT("set_achievement")), MakeString(Id)}));
			}
			if (!Send(Call({MakeString(TEXT("store_stats"))})))
			{
				bOnline = false;   // the store said no: keep everything, wait for Connect()
				return TEXT("failed");
			}
			PendingStats.Reset();
			PendingUnlocks.Reset();
		}
		for (const FString& P : PendingCloud)
		{
			Send(Call({MakeString(TEXT("cloud_write")), MakeString(P)}));
		}
		PendingCloud.Reset();
		return TEXT("sent");
	}

	FPlatformOut FPlatformRules::Flush()
	{
		return Done(FlushInner());
	}

	FPlatformOut FPlatformRules::SetPresence(const TSharedPtr<FJsonValue>& Key, const TSharedPtr<FJsonValue>& Value)
	{
		if (!PlatformIdOk(Key) || !Is(Value, EJson::String) ||
		    FTCHARToUTF8(*Value->AsString()).Length() > PresenceMaxValueBytes)   // bytes, as Steam counts them
		{
			return Done(TEXT("refused"));
		}
		const FString K = Key->AsString();
		const FString V = Value->AsString();
		FString* Old = FindPair(Presence, K);
		if (V.IsEmpty())
		{
			if (!Old)
			{
				return Done(TEXT("same"));
			}
			Presence.RemoveAll([&K](const TPair<FString, FString>& P) { return Same(P.Key, K); });
		}
		else
		{
			if (Old && Same(*Old, V))
			{
				return Done(TEXT("same"));
			}
			if (!Old && Presence.Num() >= PresenceMaxKeys)
			{
				return Done(TEXT("refused"));
			}
			if (Old)
			{
				*Old = V;
			}
			else
			{
				Presence.Add({K, V});
			}
		}
		if (bOnline)
		{
			Send(Call({MakeString(TEXT("set_presence")), MakeString(K), MakeString(V)}));
		}
		return Done(TEXT("ok"));
	}

	FPlatformOut FPlatformRules::ClearPresence()
	{
		if (Presence.IsEmpty())
		{
			return Done(TEXT("same"));
		}
		Presence.Reset();
		if (bOnline)
		{
			Send(Call({MakeString(TEXT("clear_presence"))}));
		}
		return Done(TEXT("ok"));
	}

	FPlatformOut FPlatformRules::Saved(const FString& Path)
	{
		const FString Part = CloudPartition(Path);
		if (Same(Part, TEXT("cloud")) && Same(Cloud, TEXT("api")))
		{
			if (bOnline)
			{
				Send(Call({MakeString(TEXT("cloud_write")), MakeString(Path)}));
			}
			else if (!Has(PendingCloud, Path))
			{
				PendingCloud.Add(Path);
			}
		}
		return Done(*Part);
	}

	FPlatformOut FPlatformRules::Connect(const TSharedPtr<FJsonObject>& Remote)
	{
		bOnline = true;
		const TSharedPtr<FJsonValue> Ru = Get(Remote, TEXT("unlocked"), nullptr);
		if (Is(Ru, EJson::Array))
		{
			for (const TSharedPtr<FJsonValue>& V : Ru->AsArray())
			{
				if (!Is(V, EJson::String))
				{
					continue;
				}
				const FString Id = V->AsString();
				if (HasAchievement(Id) && !Has(Unlocked, Id))
				{
					Unlocked.Add(Id);
				}
				RemoveOne(PendingUnlocks, Id);
			}
		}
		const TSharedPtr<FJsonObject> Rs = Is(Get(Remote, TEXT("stats"), nullptr), EJson::Object) ? Remote->TryGetField(TEXT("stats"))->AsObject() : nullptr;
		for (const TSharedPtr<FJsonObject>& S : StatDefs)
		{
			const FString Sid = Str(S->TryGetField(TEXT("id")));
			const TSharedPtr<FJsonValue> R0 = Get(Rs, Sid, nullptr);
			if (!OkFor(Str(S->TryGetField(TEXT("type"))), R0))
			{
				continue;
			}
			const double R = Clamp(S, R0->AsNumber());
			const double Old = StatValue(Sid);
			const bool bPend = Has(PendingStats, Sid);
			double Now;
			if (S->TryGetField(TEXT("increment_only"))->AsBool())
			{
				if (R >= Old && bPend)
				{
					RemoveOne(PendingStats, Sid);
				}
				Now = FMath::Max(Old, R);
			}
			else
			{
				Now = bPend ? Old : R;
			}
			SetStatValue(Sid, Now);
			Check(Sid, Old, Now, false);
		}
		FlushInner();
		if (bOnline)
		{
			for (const TSharedPtr<FJsonValue>& P : PresenceList())
			{
				const FValues& Pair = P->AsArray();
				Send(Call({MakeString(TEXT("set_presence")), Pair[0], Pair[1]}));
			}
		}
		return Done(bOnline ? TEXT("online") : TEXT("failed"));
	}

	FPlatformOut FPlatformRules::Disconnect()
	{
		bOnline = false;
		return Done(TEXT("offline"));
	}

	FPlatformOut FPlatformRules::StoreFailed(const TArray<TSharedPtr<FJsonValue>>& Batch)
	{
		bOnline = false;
		for (const TSharedPtr<FJsonValue>& C : Batch)
		{
			const FValues& Call = C->AsArray();
			const FString Name = Str(Call[0]);
			const FString Id = Str(Call[1]);
			if (Same(Name, TEXT("set_stat")) && StatDef(Id).IsValid() && !Has(PendingStats, Id))
			{
				PendingStats.Add(Id);
			}
			else if (Same(Name, TEXT("set_achievement")) && Has(Unlocked, Id) && !Has(PendingUnlocks, Id))
			{
				PendingUnlocks.Add(Id);
			}
		}
		return Done(TEXT("failed"));
	}

	FPlatformOut FPlatformRules::ResetAll()
	{
		if (!bOnline)
		{
			return Done(TEXT("offline"));
		}
		ResetLocal();
		Send(Call({MakeString(TEXT("reset_all_stats")), MakeBool(true)}));
		return Done(TEXT("reset"));
	}

	TSharedRef<FJsonObject> PlatformStateLoad(const TSharedRef<FJsonObject>& Defs, const TOptional<FString>& Text, int32& OutProblems)
	{
		FNullPlatformBackend Nb;
		FPlatformRules P(Defs, &Nb);
		OutProblems = 0;
		if (!Text.IsSet() || Text.GetValue().IsEmpty())
		{
			return P.State();
		}
		const TSharedPtr<FJsonValue> Parsed = Parse(Text.GetValue());
		const TSharedPtr<FJsonObject> Raw = Is(Parsed, EJson::Object) ? Parsed->AsObject() : nullptr;
		if (!Raw.IsValid() || !Same(Str(Get(Raw, TEXT("format"), nullptr)), PlatformFormat) || !Whole(Get(Raw, TEXT("version"), nullptr)) ||
		    Num(Raw->TryGetField(TEXT("version"))) != PlatformStateVersion)
		{
			OutProblems = 1;
			return P.State();
		}
		int32 Bad = 0;
		auto Items = [&Bad](const TSharedPtr<FJsonValue>& V, EJson Kind) -> TSharedPtr<FJsonValue>
		{
			if (Is(V, Kind))
			{
				return V;
			}
			if (!IsNull(V))
			{
				++Bad;
			}
			return Kind == EJson::Array ? MakeArray({}) : MakeObject(MakeShared<FJsonObject>());
		};
		for (const TSharedPtr<FJsonValue>& V : Items(Get(Raw, TEXT("unlocked"), nullptr), EJson::Array)->AsArray())
		{
			if (Is(V, EJson::String) && P.HasAchievement(V->AsString()) && !Has(P.Unlocked, V->AsString()))
			{
				P.Unlocked.Add(V->AsString());
			}
			else
			{
				++Bad;
			}
		}
		const TSharedPtr<FJsonObject> Stats = Items(Get(Raw, TEXT("stats"), nullptr), EJson::Object)->AsObject();
		for (const auto& Kv : Stats->Values)
		{
			const FString Key(*Kv.Key);
			const TSharedPtr<FJsonObject> S = P.StatDef(Key);
			if (!S.IsValid() || !OkFor(Str(S->TryGetField(TEXT("type"))), Kv.Value))
			{
				++Bad;
				continue;
			}
			P.SetStatValue(Key, Clamp(S, Kv.Value->AsNumber()));
		}
		const TSharedPtr<FJsonObject> Pending = Items(Get(Raw, TEXT("pending"), nullptr), EJson::Object)->AsObject();
		for (const TSharedPtr<FJsonValue>& V : Items(Get(Pending, TEXT("stats"), nullptr), EJson::Array)->AsArray())
		{
			if (Is(V, EJson::String) && P.StatDef(V->AsString()).IsValid() && !Has(P.PendingStats, V->AsString()))
			{
				P.PendingStats.Add(V->AsString());
			}
			else
			{
				++Bad;
			}
		}
		for (const TSharedPtr<FJsonValue>& V : Items(Get(Pending, TEXT("unlocks"), nullptr), EJson::Array)->AsArray())
		{
			if (Is(V, EJson::String) && Has(P.Unlocked, V->AsString()) && !Has(P.PendingUnlocks, V->AsString()))
			{
				P.PendingUnlocks.Add(V->AsString());
			}
			else
			{
				++Bad;
			}
		}
		for (const TSharedPtr<FJsonValue>& V : Items(Get(Pending, TEXT("cloud"), nullptr), EJson::Array)->AsArray())
		{
			if (Is(V, EJson::String) && Same(CloudPartition(V->AsString()), TEXT("cloud")) && !Has(P.PendingCloud, V->AsString()))
			{
				P.PendingCloud.Add(V->AsString());
			}
			else
			{
				++Bad;
			}
		}
		OutProblems = Bad;
		return P.State();
	}

	// ---- FPlatformService ----

	namespace
	{
		TSharedRef<FJsonObject> LoadDefs(const TOptional<FString>& Text, TArray<FString>& Problems)
		{
			int32 N = 0;
			TSharedRef<FJsonObject> Defs = AchievementsLoad(Text, N);
			if (N > 0)
			{
				Problems.Add(FString::Printf(TEXT("%s: %d problem(s), those entries were dropped"), AchievementsFile, N));
			}
			return Defs;
		}
	}

	FPlatformService::FPlatformService(const FString& DataDir, const TOptional<FString>& AchievementsText,
	                                   TUniquePtr<IPlatformBackend> InBackend, const FString& InCloud)
		: File(FPaths::Combine(DataDir, PlatformStateFile)),
		  Backend(InBackend.IsValid() ? MoveTemp(InBackend) : MakeUnique<FNullPlatformBackend>()),
		  Rules(LoadDefs(AchievementsText, Problems), Backend.Get(), false, InCloud)
	{
		bActive = !Rules.Defs()->TryGetField(TEXT("stats"))->AsArray().IsEmpty() || !Rules.Defs()->TryGetField(TEXT("achievements"))->AsArray().IsEmpty();
		if (bActive)
		{
			const TOptional<FString> Text = ReadTextFile(File);
			int32 N = 0;
			const TSharedRef<FJsonObject> St = PlatformStateLoad(Rules.Defs(), Text, N);
			if (N > 0)
			{
				Problems.Add(FString::Printf(TEXT("%s: %d problem(s), the store's copy wins"), PlatformStateFile, N));
			}
			Rules.Restore(St);
			Last = Text.Get(FString());
		}
		if (Backend->Available())
		{
			Rules.Connect(Backend->Remote());
		}
		Persist();
	}

	FString FPlatformService::SetStat(const FString& Id, double Value)
	{
		return After(Rules.SetStat(Id, MakeNumber(Value)));
	}

	FString FPlatformService::AddStat(const FString& Id, double Delta)
	{
		return After(Rules.AddStat(Id, MakeNumber(Delta)));
	}

	FString FPlatformService::SetPresence(const FString& Key, const FString& Value)
	{
		return After(Rules.SetPresence(MakeString(Key), MakeString(Value)));
	}

	void FPlatformService::Persist()
	{
		if (!bActive)
		{
			return;
		}
		const FString Text = Write(Rules.State()) + TEXT("\n");
		if (Text.Equals(Last, ESearchCase::CaseSensitive))
		{
			return;
		}
		FString Error;
		if (WriteFileAtomic(File, Text, &Error))
		{
			Last = Text;
		}
		else
		{
			Problems.Add(FString::Printf(TEXT("%s not written: %s"), PlatformStateFile, *Error));
		}
	}

	TOptional<bool> FPlatformService::Update()
	{
		const TOptional<bool> Overlay = Backend->Update();
		for (TOptional<TArray<TSharedPtr<FJsonValue>>> Batch = Backend->TakeStoreFailure(); Batch.IsSet(); Batch = Backend->TakeStoreFailure())
		{
			Problems.Add(TEXT("a store the backend accepted failed later: kept for the next connect"));
			After(Rules.StoreFailed(Batch.GetValue()));
		}
		return Overlay;
	}

	FString FPlatformService::After(const FPlatformOut& R)
	{
		Persist();
		return Is(R.Out, EJson::String) ? R.Out->AsString() : FString();
	}
}

// {{FOOTER}}
