// ---------------------------------------------------------------------------
// GameKitGoldenTests.cpp
// Purpose : Checks the plugin's juice and shell logic against the kit's golden vectors, data/golden/juice.json
//           and data/golden/shell.json (under the project folder), one automation test per case.
// Usage   : python tools/dev.py test                                  (runs GameKit.* with the game's tests)
//           python tools/dev.py test --filter GameKit.Golden.Shell     (one file; or GameKit.Golden.Juice.shake)
// Notes   : The vectors are written by tools/golden_vectors.py, the reference implementation every engine port
//           is held to. Expected values are read from the files at test time, never copied here. The case list
//           is read when the editor lists its tests: a missing or broken file shows up as a failing
//           GameKit.Golden.<File>.load test, and GameKit.Golden.Coverage fails when a vector type has no case.
//           A case type this file does not know fails its test, so a new vector type cannot be skipped
//           silently. Numbers compare within the file's tolerance (an int 0 equals a float 0.0), arrays in
//           order, objects as key sets (GameKit::Json::Diff).
//
// Pseudocode:
//   GetTests: load the file -> one entry per case ("<type> <name>", command = the case index)
//   RunTest : load the file -> the case -> the checker for its type (or fail) -> run its steps or points
//             through the plugin -> compare every result with the expected value
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitAtomicFile.h"
#include "GameKitBindings.h"
#include "GameKitCoyoteTimer.h"
#include "GameKitEase.h"
#include "GameKitFlashLimiter.h"
#include "GameKitFollowCamera.h"
#include "GameKitHitstop.h"
#include "GameKitI18n.h"
#include "GameKitInputBuffer.h"
#include "GameKitJson.h"
#include "GameKitSaveStore.h"
#include "GameKitSettings.h"
#include "GameKitShake.h"
#include "GameKitSpring.h"
#include "Misc/Paths.h"

// A named namespace (not an anonymous one): the using-directive must not leak into other files of a unity build
namespace GameKitGoldenTests
{
	using namespace GameKit::Json;

	// ---- Constants ----
	constexpr EAutomationTestFlags GoldenTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;
	constexpr int32 GoldenFormat = 1;                      // the golden file "version" this test understands
	constexpr double GoldenDefaultTolerance = 1e-6;        // used only when a file has no "tolerance"
	constexpr const TCHAR* GoldenFolder = TEXT("data/golden");   // under the project folder
	constexpr const TCHAR* GoldenLoadCommand = TEXT("load");     // the entry that reports a missing or broken file
	constexpr const TCHAR* JuiceFile = TEXT("juice.json");
	constexpr const TCHAR* ShellFile = TEXT("shell.json");

	FString GoldenPath(const TCHAR* File)
	{
		return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), GoldenFolder, File));
	}

	/** The parsed vector file, or null with OutError set. */
	TSharedPtr<FJsonObject> LoadGolden(const TCHAR* File, FString& OutError)
	{
		const FString Path = GoldenPath(File);
		FString ReadError;
		const TOptional<FString> Text = GameKit::ReadTextFile(Path, &ReadError);
		if (!Text.IsSet())
		{
			OutError = ReadError.IsEmpty() ? FString::Printf(TEXT("%s not found (data/golden ships with every kit game)"), *Path) : ReadError;
			return nullptr;
		}
		const TSharedPtr<FJsonValue> Root = Parse(Text.GetValue());
		if (!Is(Root, EJson::Object))
		{
			OutError = FString::Printf(TEXT("%s is not a JSON object"), *Path);
			return nullptr;
		}
		const TSharedPtr<FJsonObject> Obj = Root->AsObject();
		if (GetNumber(Obj, TEXT("version"), -1.0) != GoldenFormat)
		{
			OutError = FString::Printf(TEXT("%s has vector format %s; this test reads format %d"), *Path,
			                           *Write(Find(Obj, TEXT("version")), 0), GoldenFormat);
			return nullptr;
		}
		const TSharedPtr<FJsonValue> Cases = Find(Obj, TEXT("cases"));
		if (!Is(Cases, EJson::Array) || Cases->AsArray().IsEmpty())
		{
			OutError = FString::Printf(TEXT("%s has no cases"), *Path);
			return nullptr;
		}
		return Obj;
	}

	/** One case's run: where errors go, the file's tolerance, and readers that fail loudly on bad case data. */
	struct FGoldenRun
	{
		FAutomationTestBase& Test;
		double Tolerance = GoldenDefaultTolerance;
		int32 Checks = 0;

		void SameValue(const TSharedPtr<FJsonValue>& Got, const TSharedPtr<FJsonValue>& Want, const FString& What)
		{
			++Checks;
			const FString D = Diff(Got, Want, Tolerance);
			if (!D.IsEmpty())
			{
				Test.AddError(What + TEXT(" ") + D);
			}
		}
		void SameNumber(double Got, const TSharedPtr<FJsonValue>& Want, const FString& What) { SameValue(MakeNumber(Got), Want, What); }
		void SameBool(bool bGot, const TSharedPtr<FJsonValue>& Want, const FString& What) { SameValue(MakeBool(bGot), Want, What); }
		void SameText(const FString& Got, const TSharedPtr<FJsonValue>& Want, const FString& What) { SameValue(MakeString(Got), Want, What); }

		void Bad(const FString& Why)
		{
			Test.AddError(TEXT("case data: ") + Why);
		}

		TSharedPtr<FJsonValue> Field(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
		{
			const TSharedPtr<FJsonValue> V = Find(O, Key);
			if (!V.IsValid())
			{
				Bad(FString::Printf(TEXT("no \"%s\""), Key));
				return MakeNull();
			}
			return V;
		}
		double Num(const TSharedPtr<FJsonObject>& O, const TCHAR* Key) { return AsNum(Field(O, Key), Key); }
		bool Flag(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
		{
			const TSharedPtr<FJsonValue> V = Field(O, Key);
			if (!Is(V, EJson::Boolean))
			{
				Bad(FString::Printf(TEXT("\"%s\" is not true/false"), Key));
				return false;
			}
			return V->AsBool();
		}
		FString Text(const TSharedPtr<FJsonObject>& O, const TCHAR* Key) { return AsText(Field(O, Key), Key); }
		TSharedPtr<FJsonObject> Obj(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
		{
			const TSharedPtr<FJsonValue> V = Field(O, Key);
			if (!Is(V, EJson::Object))
			{
				Bad(FString::Printf(TEXT("\"%s\" is not an object"), Key));
				return MakeShared<FJsonObject>();
			}
			return V->AsObject();
		}
		const TArray<TSharedPtr<FJsonValue>>& List(const TSharedPtr<FJsonObject>& O, const TCHAR* Key) { return AsList(Field(O, Key), Key); }

		// Items of a "points" row: [input, ..., expected]
		TSharedPtr<FJsonValue> At(const TSharedPtr<FJsonValue>& Row, int32 I)
		{
			const TArray<TSharedPtr<FJsonValue>>& Items = AsList(Row, TEXT("point"));
			if (!Items.IsValidIndex(I))
			{
				Bad(FString::Printf(TEXT("point %s has no item %d"), *Write(Row, 0), I));
				return MakeNull();
			}
			return Items[I];
		}
		double NumAt(const TSharedPtr<FJsonValue>& Row, int32 I) { return AsNum(At(Row, I), TEXT("point item")); }
		FString TextAt(const TSharedPtr<FJsonValue>& Row, int32 I) { return AsText(At(Row, I), TEXT("point item")); }

		double AsNum(const TSharedPtr<FJsonValue>& V, const TCHAR* What)
		{
			if (!Is(V, EJson::Number))
			{
				Bad(FString::Printf(TEXT("%s %s is not a number"), What, *Write(V, 0)));
				return 0.0;
			}
			return V->AsNumber();
		}
		FString AsText(const TSharedPtr<FJsonValue>& V, const TCHAR* What)
		{
			if (!Is(V, EJson::String))
			{
				Bad(FString::Printf(TEXT("%s %s is not a string"), What, *Write(V, 0)));
				return FString();
			}
			return V->AsString();
		}
		const TArray<TSharedPtr<FJsonValue>>& AsList(const TSharedPtr<FJsonValue>& V, const TCHAR* What)
		{
			static const TArray<TSharedPtr<FJsonValue>> Empty;
			if (!Is(V, EJson::Array))
			{
				Bad(FString::Printf(TEXT("%s %s is not a list"), What, *Write(V, 0)));
				return Empty;
			}
			return V->AsArray();
		}

		/** The steps of a case, as objects with a "call". */
		TArray<TSharedPtr<FJsonObject>> Steps(const TSharedPtr<FJsonObject>& Case)
		{
			TArray<TSharedPtr<FJsonObject>> Out;
			for (const TSharedPtr<FJsonValue>& S : List(Case, TEXT("steps")))
			{
				Out.Add(Is(S, EJson::Object) ? S->AsObject() : MakeShared<FJsonObject>());
			}
			return Out;
		}

		void UnknownCall(const FString& Call)
		{
			Bad(FString::Printf(TEXT("unknown step call \"%s\""), *Call));
		}
	};

	FString StepLabel(int32 Index, const TCHAR* What)
	{
		return FString::Printf(TEXT("step %d %s:"), Index, What);
	}

	// ---- juice.json --------------------------------------------------------------------------

	void CheckNoise(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			const double Got = GameKit::Noise(static_cast<int64>(Run.NumAt(P, 0)), Run.NumAt(P, 1), static_cast<int64>(Run.NumAt(P, 2)));
			Run.SameNumber(Got, Run.At(P, 3), TEXT("noise ") + Write(P, 0));
		}
	}

	void CheckShake(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const TSharedPtr<FJsonObject> K = Run.Obj(Case, TEXT("params"));
		FGameKitShake Shake(Run.Num(K, TEXT("max_offset")), Run.Num(K, TEXT("max_angle")), Run.Num(K, TEXT("decay")),
		                    Run.Num(K, TEXT("frequency")), static_cast<int64>(Run.Num(K, TEXT("seed"))));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("add_trauma"))
			{
				Shake.AddTrauma(Run.Num(Step, TEXT("a")));
			}
			else if (Call == TEXT("update"))
			{
				const FGameKitShakeOffset O = Shake.Update(Run.Num(Step, TEXT("dt")), Run.Num(Step, TEXT("intensity")));
				const TSharedPtr<FJsonObject> E = Run.Obj(Step, TEXT("expect"));
				Run.SameNumber(O.X, Run.Field(E, TEXT("x")), StepLabel(I, TEXT("x")));
				Run.SameNumber(O.Y, Run.Field(E, TEXT("y")), StepLabel(I, TEXT("y")));
				Run.SameNumber(O.Angle, Run.Field(E, TEXT("angle")), StepLabel(I, TEXT("angle")));
				Run.SameNumber(Shake.GetTrauma(), Run.Field(E, TEXT("trauma")), StepLabel(I, TEXT("trauma")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckHitstop(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		FGameKitHitstop Hitstop(Run.Num(Run.Obj(Case, TEXT("params")), TEXT("max_s")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("hit"))
			{
				Hitstop.Hit(Run.Num(Step, TEXT("duration")));
			}
			else if (Call == TEXT("scaled_dt"))
			{
				const double Dt = Hitstop.ScaledDt(Run.Num(Step, TEXT("dt")));
				const TSharedPtr<FJsonObject> E = Run.Obj(Step, TEXT("expect"));
				Run.SameNumber(Dt, Run.Field(E, TEXT("dt")), StepLabel(I, TEXT("dt")));
				Run.SameNumber(Hitstop.GetRemaining(), Run.Field(E, TEXT("remaining")), StepLabel(I, TEXT("remaining")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckEase(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			const FString Name = Run.TextAt(P, 0);
			const TOptional<double> Got = GameKit::EaseByName(Name, Run.NumAt(P, 1));
			if (!Got.IsSet())
			{
				Run.Test.AddError(FString::Printf(TEXT("no easing named \"%s\""), *Name));
				continue;
			}
			Run.SameNumber(Got.GetValue(), Run.At(P, 2), TEXT("ease ") + Write(P, 0));
		}
	}

	void CheckFollow(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const TSharedPtr<FJsonObject> K = Run.Obj(Case, TEXT("params"));
		FGameKitFollowCamera Follow(Run.Num(K, TEXT("deadzone_w")), Run.Num(K, TEXT("deadzone_h")), Run.Num(K, TEXT("lookahead")),
		                            Run.Num(K, TEXT("smoothing")), Run.Num(K, TEXT("x")), Run.Num(K, TEXT("y")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("update"))
			{
				const FVector2D C = Follow.Update(Run.Num(Step, TEXT("dt")), Run.Num(Step, TEXT("tx")), Run.Num(Step, TEXT("ty")),
				                                  Run.Num(Step, TEXT("vx")), Run.Num(Step, TEXT("vy")));
				const TSharedPtr<FJsonObject> E = Run.Obj(Step, TEXT("expect"));
				Run.SameNumber(C.X, Run.Field(E, TEXT("x")), StepLabel(I, TEXT("x")));
				Run.SameNumber(C.Y, Run.Field(E, TEXT("y")), StepLabel(I, TEXT("y")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckInputBuffer(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		FGameKitInputBuffer Buffer(Run.Num(Run.Obj(Case, TEXT("params")), TEXT("window_s")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("press"))
			{
				Buffer.Press(FName(*Run.Text(Step, TEXT("action"))));
			}
			else if (Call == TEXT("update"))
			{
				Buffer.Update(Run.Num(Step, TEXT("dt")));
			}
			else if (Call == TEXT("consume"))
			{
				const bool bGot = Buffer.Consume(FName(*Run.Text(Step, TEXT("action"))));
				Run.SameBool(bGot, Run.Field(Run.Obj(Step, TEXT("expect")), TEXT("result")), StepLabel(I, TEXT("consume")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckCoyote(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		FGameKitCoyoteTimer Coyote(Run.Num(Run.Obj(Case, TEXT("params")), TEXT("window_s")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("update"))
			{
				Coyote.Update(Run.Num(Step, TEXT("dt")), Run.Flag(Step, TEXT("on_floor")));
			}
			else if (Call == TEXT("consume"))
			{
				Coyote.Consume();
			}
			else if (Call == TEXT("can_jump"))
			{
				Run.SameBool(Coyote.CanJump(), Run.Field(Run.Obj(Step, TEXT("expect")), TEXT("result")), StepLabel(I, TEXT("can_jump")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckSpring(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const TSharedPtr<FJsonObject> K = Run.Obj(Case, TEXT("params"));
		FGameKitSpring Spring(Run.Num(K, TEXT("frequency")), Run.Num(K, TEXT("damping")));
		Spring.X = Run.Num(K, TEXT("x"));
		Spring.V = Run.Num(K, TEXT("v"));
		Spring.Target = Run.Num(K, TEXT("target"));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("update"))
			{
				const double X = Spring.Update(Run.Num(Step, TEXT("dt")));
				const TSharedPtr<FJsonObject> E = Run.Obj(Step, TEXT("expect"));
				Run.SameNumber(X, Run.Field(E, TEXT("x")), StepLabel(I, TEXT("x")));
				Run.SameNumber(Spring.V, Run.Field(E, TEXT("v")), StepLabel(I, TEXT("v")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckSquash(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			const FVector2D S = GameKit::Squash(Run.NumAt(P, 0));
			Run.SameNumber(S.X, Run.At(P, 1), TEXT("squash width ") + Write(P, 0));
			Run.SameNumber(S.Y, Run.At(P, 2), TEXT("squash height ") + Write(P, 0));
		}
	}

	void CheckFlashLimiter(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const TSharedPtr<FJsonObject> K = Run.Obj(Case, TEXT("params"));
		FGameKitFlashLimiter Flashes(static_cast<int32>(Run.Num(K, TEXT("max_flashes"))), Run.Num(K, TEXT("window_s")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			if (Call == TEXT("request"))
			{
				const bool bGot = Flashes.Request(Run.Num(Step, TEXT("now")));
				Run.SameBool(bGot, Run.Field(Run.Obj(Step, TEXT("expect")), TEXT("result")), StepLabel(I, TEXT("request")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	// ---- shell.json --------------------------------------------------------------------------

	/** A JSON string as text, null as "no file". */
	TOptional<FString> OptionalText(FGoldenRun& Run, const TSharedPtr<FJsonValue>& V)
	{
		if (Is(V, EJson::Null))
		{
			return {};
		}
		return Run.AsText(V, TEXT("file text"));
	}

	void CheckDefaults(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		Run.SameValue(MakeObject(GameKit::DefaultSettings()), Run.Field(Case, TEXT("expect")), TEXT("defaults"));
	}

	void CheckSettingsLoad(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const FGameKitSettingsLoad L = GameKit::SettingsLoad(OptionalText(Run, Run.Field(Case, TEXT("input"))));
		Run.SameValue(MakeObject(L.Settings), Run.Field(Case, TEXT("expect")), TEXT("settings"));
		Run.SameNumber(L.Problems.Num(), Run.Field(Case, TEXT("problems")),
		               FString::Printf(TEXT("problem count (%s):"), *FString::Join(L.Problems, TEXT(", "))));
		Run.SameNumber(GameKit::EffectiveShake(*L.Settings), Run.Field(Case, TEXT("effective_shake")), TEXT("effective_shake"));
		Run.SameBool(GameKit::TelemetryAllowed(*L.Settings), Run.Field(Case, TEXT("telemetry_allowed")), TEXT("telemetry_allowed"));
	}

	void CheckRebind(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const FGameKitBindings Before = GameKit::BindingsFromJson(Run.Obj(Case, TEXT("bindings")));
		const TOptional<FGameKitRebindResult> R = GameKit::Rebind(Before, Run.Text(Case, TEXT("action")),
		                                                          static_cast<int32>(Run.Num(Case, TEXT("slot"))), Run.Text(Case, TEXT("binding")));
		if (!R.IsSet())
		{
			Run.Test.AddError(TEXT("Rebind refused the slot"));
			return;
		}
		const TSharedPtr<FJsonObject> E = Run.Obj(Case, TEXT("expect"));
		Run.SameValue(MakeObject(GameKit::BindingsToJson(R->Bindings)), Run.Field(E, TEXT("bindings")), TEXT("bindings"));
		TArray<TSharedPtr<FJsonValue>> Conflicts;
		for (const TPair<FString, int32>& C : R->Conflicts)
		{
			Conflicts.Add(MakeArray({MakeString(C.Key), MakeNumber(C.Value)}));
		}
		Run.SameValue(MakeArray(Conflicts), Run.Field(E, TEXT("conflicts")), TEXT("conflicts"));
	}

	void CheckGlyphSet(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			Run.SameText(GameKit::GlyphSet(Run.TextAt(P, 0), Run.TextAt(P, 1)), Run.At(P, 2), TEXT("glyph_set ") + Write(P, 0));
		}
	}

	void CheckGlyphName(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			Run.SameText(GameKit::GlyphName(Run.TextAt(P, 0), Run.TextAt(P, 1)), Run.At(P, 2), TEXT("glyph_name ") + Write(P, 0));
		}
	}

	void CheckPromptBinding(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const FGameKitBindings B = GameKit::BindingsFromJson(Run.Obj(Case, TEXT("bindings")));
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			Run.SameText(GameKit::PromptBinding(B, Run.TextAt(P, 0), Run.TextAt(P, 1)), Run.At(P, 2), TEXT("prompt_binding ") + Write(P, 0));
		}
	}

	void CheckSaveLoad(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		Run.SameNumber(GameKit::SaveVersion, Run.Field(Case, TEXT("current_version")), TEXT("SaveVersion"));
		const FGameKitSaveLoad L = GameKit::SaveLoad(OptionalText(Run, Run.Field(Case, TEXT("primary"))),
		                                             OptionalText(Run, Run.Field(Case, TEXT("backup"))));
		const TSharedPtr<FJsonObject> E = Run.Obj(Case, TEXT("expect"));
		Run.SameValue(L.Envelope.IsValid() ? MakeObject(L.Envelope) : MakeNull(), Run.Field(E, TEXT("envelope")), TEXT("envelope"));
		Run.SameText(L.Source, Run.Field(E, TEXT("source")), TEXT("source"));
		Run.SameNumber(L.Problems.Num(), Run.Field(E, TEXT("problems")),
		               FString::Printf(TEXT("problem count (%s):"), *FString::Join(L.Problems, TEXT(", "))));
	}

	/** Placeholder values as the reference prints them (str()): strings as they are, numbers in short form. */
	FGameKitTrArgs ArgsFrom(const TSharedPtr<FJsonValue>& V)
	{
		FGameKitTrArgs Args;
		if (Is(V, EJson::Object))
		{
			for (const auto& Pair : V->AsObject()->Values)
			{
				Args.Add(FString(*Pair.Key), Is(Pair.Value, EJson::String) ? Pair.Value->AsString() : Write(Pair.Value, 0));
			}
		}
		return Args;
	}

	void CheckTr(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const FGameKitStringTables Tables = GameKit::StringTablesFromJson(Run.Obj(Case, TEXT("tables")));
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			const FString Got = GameKit::Tr(Tables, Run.TextAt(P, 0), Run.TextAt(P, 1), ArgsFrom(Run.At(P, 2)));
			Run.SameText(Got, Run.At(P, 3), TEXT("tr ") + Write(P, 0));
		}
	}

	void CheckPlural(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const FGameKitStringTables Tables = GameKit::StringTablesFromJson(Run.Obj(Case, TEXT("tables")));
		const FString Key = Run.Text(Case, TEXT("key"));
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			const FString Locale = Run.TextAt(P, 0);
			const int64 N = static_cast<int64>(Run.NumAt(P, 1));
			Run.SameText(GameKit::Plural(Locale, N), Run.At(P, 2), TEXT("plural ") + Write(P, 0));
			Run.SameText(GameKit::TrPlural(Tables, Locale, Key, N), Run.At(P, 3), TEXT("tr_plural ") + Write(P, 0));
		}
	}

	void CheckPseudo(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			Run.SameText(GameKit::Pseudo(Run.TextAt(P, 0)), Run.At(P, 1), TEXT("pseudo ") + Write(P, 0));
		}
	}

	// ---- Case types per file: a type missing here fails its cases ----
	using FGoldenCheck = void (*)(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case);

	struct FGoldenType
	{
		const TCHAR* Type;
		FGoldenCheck Check;
	};

	const FGoldenType JuiceTypes[] = {
		{TEXT("noise"), CheckNoise}, {TEXT("shake"), CheckShake}, {TEXT("hitstop"), CheckHitstop}, {TEXT("ease"), CheckEase},
		{TEXT("follow"), CheckFollow}, {TEXT("input_buffer"), CheckInputBuffer}, {TEXT("coyote"), CheckCoyote},
		{TEXT("spring"), CheckSpring}, {TEXT("squash"), CheckSquash}, {TEXT("flash_limiter"), CheckFlashLimiter},
	};

	const FGoldenType ShellTypes[] = {
		{TEXT("defaults"), CheckDefaults}, {TEXT("settings_load"), CheckSettingsLoad}, {TEXT("rebind"), CheckRebind},
		{TEXT("glyph_set"), CheckGlyphSet}, {TEXT("glyph_name"), CheckGlyphName}, {TEXT("prompt_binding"), CheckPromptBinding},
		{TEXT("save_load"), CheckSaveLoad}, {TEXT("tr"), CheckTr}, {TEXT("plural"), CheckPlural}, {TEXT("pseudo"), CheckPseudo},
	};

	template <int32 N>
	const FGoldenType* FindGoldenType(const FGoldenType (&Types)[N], const FString& Type)
	{
		for (const FGoldenType& T : Types)
		{
			if (Type.Equals(T.Type, ESearchCase::CaseSensitive))
			{
				return &T;
			}
		}
		return nullptr;
	}

	/** A test name part the dev.py filter accepts: letters, digits, spaces, - and _. */
	FString TestNamePart(const FString& Text)
	{
		FString Out;
		for (const TCHAR C : Text)
		{
			Out.AppendChar(FChar::IsAlnum(C) || C == TEXT('-') || C == TEXT('_') ? C : TEXT(' '));
		}
		while (Out.ReplaceInline(TEXT("  "), TEXT(" ")) > 0)
		{
		}
		return Out.TrimStartAndEnd();
	}

	void ListGoldenCases(const TCHAR* File, TArray<FString>& OutNames, TArray<FString>& OutCommands)
	{
		FString Error;
		const TSharedPtr<FJsonObject> Root = LoadGolden(File, Error);
		if (!Root.IsValid())
		{
			OutNames.Add(GoldenLoadCommand);   // runs, and fails with the reason
			OutCommands.Add(GoldenLoadCommand);
			return;
		}
		TSet<FString> Used;
		const TArray<TSharedPtr<FJsonValue>>& Cases = Root->GetArrayField(TEXT("cases"));
		for (int32 I = 0; I < Cases.Num(); ++I)
		{
			const TSharedPtr<FJsonObject> Case = Is(Cases[I], EJson::Object) ? Cases[I]->AsObject() : nullptr;
			FString Name = TestNamePart(FString::Printf(TEXT("%s %s"), *GetString(Case, TEXT("type"), TEXT("case")),
			                                            *GetString(Case, TEXT("name"), FString::FromInt(I))));
			if (Used.Contains(Name))
			{
				Name += FString::Printf(TEXT(" %d"), I);   // two cases with one name still get a test each
			}
			Used.Add(Name);
			OutNames.Add(Name);
			OutCommands.Add(FString::FromInt(I));
		}
	}

	template <int32 N>
	bool RunGoldenCase(FAutomationTestBase& Test, const TCHAR* File, const FGoldenType (&Types)[N], const FString& Command)
	{
		FString Error;
		const TSharedPtr<FJsonObject> Root = LoadGolden(File, Error);
		if (!Root.IsValid())
		{
			Test.AddError(Error);
			return false;
		}
		if (Command == GoldenLoadCommand)
		{
			Test.AddError(FString::Printf(TEXT("%s could not be read when the tests were listed; run the tests again"), File));
			return false;
		}
		const TArray<TSharedPtr<FJsonValue>>& Cases = Root->GetArrayField(TEXT("cases"));
		const int32 Index = FCString::Atoi(*Command);
		if (!Cases.IsValidIndex(Index) || !Is(Cases[Index], EJson::Object))
		{
			Test.AddError(FString::Printf(TEXT("%s has no case %d (the file changed since the tests were listed)"), File, Index));
			return false;
		}
		const TSharedPtr<FJsonObject> Case = Cases[Index]->AsObject();
		const FString Type = GetString(Case, TEXT("type"), FString());
		const FGoldenType* Checker = FindGoldenType(Types, Type);
		if (!Checker)
		{
			Test.AddError(FString::Printf(TEXT("unknown case type \"%s\" in %s: add a checker in GameKitGoldenTests.cpp"), *Type, File));
			return false;
		}
		FGoldenRun Run{Test, GetNumber(Root, TEXT("tolerance"), GoldenDefaultTolerance)};
		Checker->Check(Run, Case);
		if (Run.Checks == 0)
		{
			Test.AddError(TEXT("the case checked nothing (no points or steps with an expected value)"));
		}
		Test.AddInfo(FString::Printf(TEXT("%s case %d (%s): %d values checked"), File, Index, *Type, Run.Checks));
		return !Test.HasAnyErrors();
	}

	/** Every vector type this port implements has at least one case, so a truncated file cannot pass. */
	template <int32 N>
	void CheckCoverage(FAutomationTestBase& Test, const TCHAR* File, const FGoldenType (&Types)[N])
	{
		FString Error;
		const TSharedPtr<FJsonObject> Root = LoadGolden(File, Error);
		if (!Root.IsValid())
		{
			Test.AddError(Error);
			return;
		}
		TSet<FString> Seen;
		const TArray<TSharedPtr<FJsonValue>>& Cases = Root->GetArrayField(TEXT("cases"));
		for (const TSharedPtr<FJsonValue>& C : Cases)
		{
			Seen.Add(Is(C, EJson::Object) ? GetString(C->AsObject(), TEXT("type"), FString()) : FString());
		}
		for (const FGoldenType& T : Types)
		{
			Test.TestTrue(FString::Printf(TEXT("%s has a \"%s\" case"), File, T.Type), Seen.Contains(T.Type));
		}
		if (FCString::Strcmp(File, ShellFile) == 0)
		{
			Test.TestEqual(TEXT("shell.json save_version is this build's SaveVersion"),
			               static_cast<int32>(GetNumber(Root, TEXT("save_version"), -1.0)), GameKit::SaveVersion);
		}
		Test.AddInfo(FString::Printf(TEXT("%s: %d cases, %d types"), File, Cases.Num(), Seen.Num()));
	}
}

IMPLEMENT_COMPLEX_AUTOMATION_TEST(FGameKitGoldenJuiceTest, "GameKit.Golden.Juice", GameKitGoldenTests::GoldenTestFlags)

void FGameKitGoldenJuiceTest::GetTests(TArray<FString>& OutBeautifiedNames, TArray<FString>& OutTestCommands) const
{
	GameKitGoldenTests::ListGoldenCases(GameKitGoldenTests::JuiceFile, OutBeautifiedNames, OutTestCommands);
}

bool FGameKitGoldenJuiceTest::RunTest(const FString& Parameters)
{
	return GameKitGoldenTests::RunGoldenCase(*this, GameKitGoldenTests::JuiceFile, GameKitGoldenTests::JuiceTypes, Parameters);
}

IMPLEMENT_COMPLEX_AUTOMATION_TEST(FGameKitGoldenShellTest, "GameKit.Golden.Shell", GameKitGoldenTests::GoldenTestFlags)

void FGameKitGoldenShellTest::GetTests(TArray<FString>& OutBeautifiedNames, TArray<FString>& OutTestCommands) const
{
	GameKitGoldenTests::ListGoldenCases(GameKitGoldenTests::ShellFile, OutBeautifiedNames, OutTestCommands);
}

bool FGameKitGoldenShellTest::RunTest(const FString& Parameters)
{
	return GameKitGoldenTests::RunGoldenCase(*this, GameKitGoldenTests::ShellFile, GameKitGoldenTests::ShellTypes, Parameters);
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitGoldenCoverageTest, "GameKit.Golden.Coverage", GameKitGoldenTests::GoldenTestFlags)

bool FGameKitGoldenCoverageTest::RunTest(const FString&)
{
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::JuiceFile, GameKitGoldenTests::JuiceTypes);
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::ShellFile, GameKitGoldenTests::ShellTypes);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
