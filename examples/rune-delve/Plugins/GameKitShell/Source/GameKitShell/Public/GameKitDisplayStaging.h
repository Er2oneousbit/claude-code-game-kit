// ---------------------------------------------------------------------------
// GameKitDisplayStaging.h
// Purpose : The settings screen's Display tab with an Apply button (#308): Display changes wait for Apply, every
//           other tab applies at once. Engine-free: it never touches the window, it returns the (field, value)
//           calls the shell makes through its own set path.
// Usage   : FGameKitDisplayStaging St(DisplaySection);                     // settings.display as it is now
//           St.Stage(TEXT("resolution"), MakeArray({MakeNumber(1280), MakeNumber(720)}));   // the row shows St.Value()
//           for (const auto& Call : St.Apply()) { settings.display[Call.Key] = Call.Value; }   // then apply, save
//           each frame: St.Tick(RealDt)   (REAL seconds: not game time, not paused)   -> the revert's calls
//           St.Keep() / St.Revert() / St.Back()
// Notes   : tools/golden_vectors.py DisplayStaging is the spec, data/golden/shell.json's display_staging cases the
//           test (GameKitGoldenTests.cpp). Values compare as JSON (1 equals 1.0, [w, h] by value: GameKit::Json::Diff).
//           Rules:
//           - Stage(field, v): a pending change; staging the applied value drops it. "busy" while the confirm is open.
//           - Apply(): the pending fields that differ, in GameKit::DisplayApplyOrder (mode before resolution);
//             remembers the values they replace; a change to mode or resolution opens the confirm (DisplayConfirmS).
//           - Tick(dt): the countdown; reaching 0 reverts. Seconds() is ceil(left) for "Reverting in N s".
//           - Keep(): closes the confirm. Revert(): puts back exactly what the last Apply replaced.
//           - Back(): during the confirm it reverts (a screen the player cannot see must never stick); with pending
//             changes the first Back warns, the second discards them; else it leaves.
//
// Pseudocode:
//   Apply : changed = pending fields != applied; replaced = their applied values; pending = {}; Set(changed);
//           changed has mode or resolution -> left = DisplayConfirmS
//   Set(v): for field in order: if in v -> applied[field] = v[field], call (field, v[field])
//   Tick  : left -= dt; left <= 0 -> Revert()
//   Back  : confirm open -> ("revert", Revert()) ; pending and not warned -> warned, ("warn") ; else discard, ("leave")
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitJson.h"

namespace GameKit
{
	// ---- Tunables ----
	/** The Display fields in the order Apply sets them: mode before resolution. */
	inline const TCHAR* const DisplayApplyOrder[5] = {TEXT("mode"), TEXT("resolution"), TEXT("vsync"), TEXT("frame_cap"), TEXT("ui_scale")};
	inline const TCHAR* const DisplayConfirmFields[2] = {TEXT("mode"), TEXT("resolution")};   // can black out the screen
	inline constexpr double DisplayConfirmS = 15.0;   // real seconds before an unanswered confirm reverts
}

class FGameKitDisplayStaging
{
public:
	using FCall = TPair<FString, TSharedPtr<FJsonValue>>;
	using FCalls = TArray<FCall>;

	/** Applied: the Display section as it is now (settings.display); copied. */
	explicit FGameKitDisplayStaging(const TSharedPtr<FJsonObject>& InApplied = nullptr)
		: Applied(GameKit::Json::CloneObject(InApplied))
	{
	}

	/** What a Display row shows: the pending value, else the applied one (null for a field the section lacks). */
	TSharedPtr<FJsonValue> Value(const FString& Field) const
	{
		if (const TSharedPtr<FJsonValue> P = Get(Pending, Field))
		{
			return P;
		}
		const TSharedPtr<FJsonValue> A = Get(Applied, Field);
		return A.IsValid() ? A : GameKit::Json::MakeNull();
	}

	/** "staged", or "busy" while the confirm is open. */
	FString Stage(const FString& Field, const TSharedPtr<FJsonValue>& V)
	{
		if (Left.IsSet())
		{
			return TEXT("busy");
		}
		const TSharedPtr<FJsonValue> A = Get(Applied, Field);
		if (A.IsValid() && Same(A, V))
		{
			Pending->RemoveField(Field);
		}
		else
		{
			Pending->SetField(Field, GameKit::Json::Clone(V));
		}
		bWarned = false;
		return TEXT("staged");
	}

	FCalls Apply()
	{
		const TSharedRef<FJsonObject> Changed = MakeShared<FJsonObject>();
		Replaced = MakeShared<FJsonObject>();
		for (const TCHAR* F : GameKit::DisplayApplyOrder)
		{
			const TSharedPtr<FJsonValue> P = Get(Pending, F);
			const TSharedPtr<FJsonValue> A = Get(Applied, F);
			if (P.IsValid() && (!A.IsValid() || !Same(A, P)))
			{
				Changed->SetField(F, P);
				Replaced->SetField(F, A.IsValid() ? GameKit::Json::Clone(A) : GameKit::Json::MakeNull());
			}
		}
		Pending = MakeShared<FJsonObject>();
		bWarned = false;
		FCalls Calls = Set(Changed);
		for (const TCHAR* F : GameKit::DisplayConfirmFields)
		{
			if (Changed->HasField(F))
			{
				Left = GameKit::DisplayConfirmS;
			}
		}
		return Calls;
	}

	/** ceil(seconds left) while the confirm is open. */
	TOptional<int32> Seconds() const
	{
		return Left.IsSet() ? TOptional<int32>(FMath::CeilToInt(Left.GetValue())) : TOptional<int32>();
	}

	/** Dt in REAL seconds. Returns the revert's calls on the frame the countdown runs out. */
	FCalls Tick(double Dt)
	{
		if (!Left.IsSet())
		{
			return FCalls();
		}
		Left = Left.GetValue() - Dt;
		return Left.GetValue() <= 0.0 ? Revert() : FCalls();
	}

	void Keep()
	{
		Left.Reset();
		Replaced = MakeShared<FJsonObject>();
	}

	FCalls Revert()
	{
		FCalls Calls = Set(Replaced);
		Left.Reset();
		Replaced = MakeShared<FJsonObject>();
		return Calls;
	}

	/** ("revert", calls) during the confirm, ("warn", {}) the first time with pending changes, else ("leave", {}). */
	TPair<FString, FCalls> Back()
	{
		if (Left.IsSet())
		{
			return {TEXT("revert"), Revert()};
		}
		if (Pending->Values.Num() > 0 && !bWarned)
		{
			bWarned = true;
			return {TEXT("warn"), FCalls()};
		}
		Pending = MakeShared<FJsonObject>();
		bWarned = false;
		return {TEXT("leave"), FCalls()};
	}

	bool Confirming() const { return Left.IsSet(); }
	bool HasPending() const { return Pending->Values.Num() > 0; }
	const TSharedRef<FJsonObject>& PendingValues() const { return Pending; }
	const TSharedRef<FJsonObject>& AppliedValues() const { return Applied; }

	/** Two JSON values equal by value (1 equals 1.0, arrays item by item). */
	static bool Same(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B)
	{
		return GameKit::Json::Diff(A, B, 0.0).IsEmpty();
	}

private:
	TSharedRef<FJsonObject> Applied;
	TSharedRef<FJsonObject> Pending = MakeShared<FJsonObject>();
	TSharedRef<FJsonObject> Replaced = MakeShared<FJsonObject>();   // field -> the value the last Apply replaced
	TOptional<double> Left;                                          // the confirm's countdown, unset when closed
	bool bWarned = false;

	/** The field's value, or null when the object lacks it (FJsonObject's own lookup, whatever its key type). */
	static TSharedPtr<FJsonValue> Get(const TSharedRef<FJsonObject>& Object, const FString& Field)
	{
		return GameKit::Json::Find(Object, Field);
	}

	FCalls Set(const TSharedRef<FJsonObject>& Values)
	{
		FCalls Calls;
		for (const TCHAR* F : GameKit::DisplayApplyOrder)
		{
			if (const TSharedPtr<FJsonValue> V = Get(Values, F))
			{
				Applied->SetField(F, GameKit::Json::Clone(V));
				Calls.Add(FCall(F, V));
			}
		}
		return Calls;
	}
};
