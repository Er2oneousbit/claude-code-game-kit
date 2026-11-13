// ---------------------------------------------------------------------------
// GameKitGoldenTests.cpp
// Purpose : Checks the plugin's juice, shell and audio logic against the kit's golden vectors (under the project
//           folder): data/golden/juice.json, shell.json, audio.json, music.json and access.json, one automation
//           test per case.
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
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the display_staging cases, the Display tab's Apply
//           and its keep-or-revert confirm (FGameKitDisplayStaging, #308); Coverage wants at least five of them
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitAtomicFile.h"
#include "GameKitAudioAccess.h"
#include "GameKitAudioDirector.h"
#include "GameKitBindings.h"
#include "GameKitCoyoteTimer.h"
#include "GameKitDisplayStaging.h"
#include "GameKitEase.h"
#include "GameKitFlashLimiter.h"
#include "GameKitFollowCamera.h"
#include "GameKitHitstop.h"
#include "GameKitI18n.h"
#include "GameKitInputBuffer.h"
#include "GameKitJson.h"
#include "GameKitMusicDirector.h"
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
	constexpr const TCHAR* AudioFile = TEXT("audio.json");     // written by tools/audio/wavesmith/audio_events.py
	constexpr const TCHAR* MusicFile = TEXT("music.json");     // tools/audio/wavesmith/music.py
	constexpr const TCHAR* AccessFile = TEXT("access.json");   // tools/audio/wavesmith/access.py

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

	/** A step's result as one JSON object, so SameValue compares key sets: a field the reference adds to
	 *  "expect" fails here instead of passing unchecked. */
	TSharedPtr<FJsonValue> Numbers(std::initializer_list<TPair<const TCHAR*, double>> Fields)
	{
		const TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		for (const TPair<const TCHAR*, double>& F : Fields)
		{
			O->SetField(F.Key, MakeNumber(F.Value));
		}
		return MakeObject(O);
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
				Run.SameValue(Numbers({{TEXT("x"), O.X}, {TEXT("y"), O.Y}, {TEXT("angle"), O.Angle}, {TEXT("trauma"), Shake.GetTrauma()}}),
				              Run.Field(Step, TEXT("expect")), StepLabel(I, TEXT("update")));
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
				Run.SameValue(Numbers({{TEXT("dt"), Dt}, {TEXT("remaining"), Hitstop.GetRemaining()}}), Run.Field(Step, TEXT("expect")),
				              StepLabel(I, TEXT("scaled_dt")));
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
				Run.SameValue(Numbers({{TEXT("x"), C.X}, {TEXT("y"), C.Y}}), Run.Field(Step, TEXT("expect")), StepLabel(I, TEXT("update")));
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
				Run.SameValue(Numbers({{TEXT("x"), X}, {TEXT("v"), Spring.V}}), Run.Field(Step, TEXT("expect")), StepLabel(I, TEXT("update")));
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

	void CheckNarration(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			Run.SameText(GameKit::NarrationLine(Run.TextAt(P, 0), Run.TextAt(P, 1), Run.TextAt(P, 2)), Run.At(P, 3),
				TEXT("narration ") + Write(P, 0));
		}
	}

	void CheckPseudo(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		for (const TSharedPtr<FJsonValue>& P : Run.List(Case, TEXT("points")))
		{
			Run.SameText(GameKit::Pseudo(Run.TextAt(P, 0)), Run.At(P, 1), TEXT("pseudo ") + Write(P, 0));
		}
	}

	// The Display tab's Apply (#308): every step's result and the state after it, as the reference records them
	void CheckDisplayStaging(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		Run.SameNumber(GameKit::DisplayConfirmS, Run.Field(Case, TEXT("confirm_s")), TEXT("confirm_s"));
		FGameKitDisplayStaging St(Run.Obj(Case, TEXT("applied")));
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const TSharedPtr<FJsonValue> Op = Run.Field(Step, TEXT("op"));
			const FString Kind = Run.TextAt(Op, 0);
			TSharedPtr<FJsonValue> Out = MakeNull();
			FGameKitDisplayStaging::FCalls Calls;
			if (Kind == TEXT("stage"))
			{
				Out = MakeString(St.Stage(Run.TextAt(Op, 1), Run.At(Op, 2)));
			}
			else if (Kind == TEXT("apply"))
			{
				Calls = St.Apply();
			}
			else if (Kind == TEXT("tick"))
			{
				Calls = St.Tick(Run.NumAt(Op, 1));
			}
			else if (Kind == TEXT("keep"))
			{
				St.Keep();
			}
			else if (Kind == TEXT("revert"))
			{
				Calls = St.Revert();
			}
			else if (Kind == TEXT("back"))
			{
				TPair<FString, FGameKitDisplayStaging::FCalls> B = St.Back();
				Out = MakeString(B.Key);
				Calls = MoveTemp(B.Value);
			}
			else
			{
				Run.Bad(TEXT("unknown display_staging op ") + Write(Op, 0));
				continue;
			}
			TArray<TSharedPtr<FJsonValue>> Called;
			for (const FGameKitDisplayStaging::FCall& C : Calls)
			{
				Called.Add(MakeArray({MakeString(C.Key), C.Value}));
			}
			const TSharedRef<FJsonObject> Shown = MakeShared<FJsonObject>();
			for (const TCHAR* F : GameKit::DisplayApplyOrder)
			{
				Shown->SetField(F, St.Value(F));
			}
			const TOptional<int32> Secs = St.Seconds();
			const FString What = TEXT("step ") + Write(Op, 0);
			Run.SameValue(Out, Run.Field(Step, TEXT("out")), What + TEXT(" out"));
			Run.SameValue(MakeArray(Called), Run.Field(Step, TEXT("calls")), What + TEXT(" calls"));
			Run.SameValue(MakeObject(St.PendingValues()), Run.Field(Step, TEXT("pending")), What + TEXT(" pending"));
			Run.SameValue(MakeObject(Shown), Run.Field(Step, TEXT("shown")), What + TEXT(" shown"));
			Run.SameValue(MakeObject(St.AppliedValues()), Run.Field(Step, TEXT("applied")), What + TEXT(" applied"));
			Run.SameValue(Secs.IsSet() ? MakeNumber(Secs.GetValue()) : MakeNull(), Run.Field(Step, TEXT("seconds")),
			              What + TEXT(" seconds"));
		}
	}

	// ---- audio.json, music.json, access.json (Wavesmith) ----------------------------------------

	TSharedPtr<FJsonValue> PlayAsJson(const FGameKitPlayDecision& D)
	{
		const TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		const TCHAR* Result = D.Result == EGameKitPlayResult::Played     ? TEXT("played")
		                      : D.Result == EGameKitPlayResult::Cooldown ? TEXT("cooldown")
		                      : D.Result == EGameKitPlayResult::Capped   ? TEXT("capped")
		                                                                 : TEXT("error");
		O->SetField(TEXT("result"), MakeString(Result));
		if (D.Result == EGameKitPlayResult::Played)
		{
			O->SetField(TEXT("variant"), MakeNumber(D.Variant));
			O->SetField(TEXT("pitch_semitones"), MakeNumber(D.PitchSemitones));
			O->SetField(TEXT("pitch_ratio"), MakeNumber(D.PitchRatio));
			O->SetField(TEXT("gain_db"), MakeNumber(D.GainDb));
			O->SetField(TEXT("voice"), MakeNumber(D.Voice));
			O->SetField(TEXT("stolen"), D.Stolen.IsSet() ? MakeNumber(D.Stolen.GetValue()) : MakeNull());
			O->SetField(TEXT("ends_ms"), MakeNumber(D.EndsMs));
		}
		return MakeObject(O);
	}

	TSharedPtr<FJsonValue> GainsAsJson(const TMap<FString, double>& Gains)
	{
		const TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		for (const TPair<FString, double>& G : Gains)
		{
			O->SetField(G.Key, MakeNumber(G.Value));
		}
		return MakeObject(O);
	}

	void CheckAudioDirector(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		FGameKitAudioDirector Director(Run.Obj(Case, TEXT("params")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FString Call = Run.Text(Step, TEXT("call"));
			const double T = Run.Num(Step, TEXT("t_ms"));
			if (Call == TEXT("play"))
			{
				Run.SameValue(PlayAsJson(Director.Play(Run.Text(Step, TEXT("event")), T)), Run.Field(Step, TEXT("expect")),
				              StepLabel(I, TEXT("play")));
			}
			else if (Call == TEXT("duck"))
			{
				Run.SameValue(GainsAsJson(Director.Duck(T)), Run.Field(Step, TEXT("expect")), StepLabel(I, TEXT("duck")));
			}
			else
			{
				Run.UnknownCall(Call);
			}
			++I;
		}
	}

	void CheckMusicGrid(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const int64 Got = GameKit::Audio::BeatSample(Run.Num(Step, TEXT("k")), Run.Num(Step, TEXT("bpm")), Run.Num(Step, TEXT("rate")));
			Run.SameNumber(static_cast<double>(Got), Run.Field(Step, TEXT("sample")), StepLabel(I++, TEXT("beat sample")));
		}
	}

	void CheckMusicPlan(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		const FGameKitMusicDirector Music(Run.Obj(Case, TEXT("params")));
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const FGameKitMusicPlan P = Music.Plan(Run.Text(Step, TEXT("from")), static_cast<int64>(Run.Num(Step, TEXT("since"))),
			                                       static_cast<int64>(Run.Num(Step, TEXT("entry"))), Run.Text(Step, TEXT("to")),
			                                       static_cast<int64>(Run.Num(Step, TEXT("now"))));
			const TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
			O->SetField(TEXT("switch_at"), MakeNumber(static_cast<double>(P.SwitchAt)));
			O->SetField(TEXT("from_stop_at"), MakeNumber(static_cast<double>(P.FromStopAt)));
			O->SetField(TEXT("fade"), MakeNumber(static_cast<double>(P.Fade)));
			O->SetField(TEXT("to_offset"), MakeNumber(static_cast<double>(P.ToOffset)));
			O->SetField(TEXT("to_start_at"), MakeNumber(static_cast<double>(P.ToStartAt)));
			O->SetField(TEXT("stinger"), P.Stinger.IsSet() ? MakeString(P.Stinger.GetValue()) : MakeNull());
			O->SetField(TEXT("stinger_at"), P.StingerAt.IsSet() ? MakeNumber(static_cast<double>(P.StingerAt.GetValue())) : MakeNull());
			if (!P.Error.IsEmpty()) { Run.Test.AddError(StepLabel(I, TEXT("plan")) + TEXT(" refused: ") + P.Error); }
			Run.SameValue(MakeObject(O), Run.Field(Step, TEXT("expect")), StepLabel(I++, TEXT("plan")));
		}
	}

	void CheckAccessGains(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const TSharedPtr<FJsonObject> Buses = Run.Obj(Step, TEXT("buses"));
			const TSharedPtr<FJsonObject> Sliders = Run.Obj(Step, TEXT("sliders"));
			Run.SameValue(GainsAsJson(GameKit::Audio::UserBusGains(Buses, Sliders)), Run.Field(Step, TEXT("expect")),
			              StepLabel(I++, TEXT("gains")));
		}
	}

	void CheckAccessArrow(FGoldenRun& Run, const TSharedPtr<FJsonObject>& Case)
	{
		int32 I = 0;
		for (const TSharedPtr<FJsonObject>& Step : Run.Steps(Case))
		{
			const double Dx = Run.Num(Step, TEXT("dx")), Dy = Run.Num(Step, TEXT("dy"));
			const double W = Run.Num(Step, TEXT("half_w")), H = Run.Num(Step, TEXT("half_h"));
			Run.SameNumber(GameKit::Audio::CaptionDirection(Dx, Dy, W, H), Run.Field(Step, TEXT("dir")), StepLabel(I, TEXT("dir")));
			Run.SameText(GameKit::Audio::CaptionArrow(Dx, Dy, W, H), Run.Field(Step, TEXT("arrow")), StepLabel(I, TEXT("arrow")));
			++I;
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
		{TEXT("narration"), CheckNarration}, {TEXT("display_staging"), CheckDisplayStaging},
	};
	constexpr int32 MinDisplayStagingCases = 5;   // the five Apply scripts of #308: a truncated file must not pass

	const FGoldenType AudioTypes[] = {{TEXT("audio_director"), CheckAudioDirector}};
	const FGoldenType MusicTypes[] = {{TEXT("music_grid"), CheckMusicGrid}, {TEXT("music_plan"), CheckMusicPlan}};
	const FGoldenType AccessTypes[] = {{TEXT("access_gains"), CheckAccessGains}, {TEXT("access_arrow"), CheckAccessArrow}};

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
		int32 Staging = 0;
		const TArray<TSharedPtr<FJsonValue>>& Cases = Root->GetArrayField(TEXT("cases"));
		for (const TSharedPtr<FJsonValue>& C : Cases)
		{
			const FString Type = Is(C, EJson::Object) ? GetString(C->AsObject(), TEXT("type"), FString()) : FString();
			Seen.Add(Type);
			Staging += Type == TEXT("display_staging") ? 1 : 0;
		}
		if (FCString::Strcmp(File, ShellFile) == 0)
		{
			Test.TestTrue(FString::Printf(TEXT("shell.json has at least %d display_staging cases (%d)"), MinDisplayStagingCases, Staging),
			              Staging >= MinDisplayStagingCases);
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

IMPLEMENT_COMPLEX_AUTOMATION_TEST(FGameKitGoldenAudioTest, "GameKit.Golden.Audio", GameKitGoldenTests::GoldenTestFlags)

void FGameKitGoldenAudioTest::GetTests(TArray<FString>& OutBeautifiedNames, TArray<FString>& OutTestCommands) const
{
	GameKitGoldenTests::ListGoldenCases(GameKitGoldenTests::AudioFile, OutBeautifiedNames, OutTestCommands);
}

bool FGameKitGoldenAudioTest::RunTest(const FString& Parameters)
{
	return GameKitGoldenTests::RunGoldenCase(*this, GameKitGoldenTests::AudioFile, GameKitGoldenTests::AudioTypes, Parameters);
}

IMPLEMENT_COMPLEX_AUTOMATION_TEST(FGameKitGoldenMusicTest, "GameKit.Golden.Music", GameKitGoldenTests::GoldenTestFlags)

void FGameKitGoldenMusicTest::GetTests(TArray<FString>& OutBeautifiedNames, TArray<FString>& OutTestCommands) const
{
	GameKitGoldenTests::ListGoldenCases(GameKitGoldenTests::MusicFile, OutBeautifiedNames, OutTestCommands);
}

bool FGameKitGoldenMusicTest::RunTest(const FString& Parameters)
{
	return GameKitGoldenTests::RunGoldenCase(*this, GameKitGoldenTests::MusicFile, GameKitGoldenTests::MusicTypes, Parameters);
}

IMPLEMENT_COMPLEX_AUTOMATION_TEST(FGameKitGoldenAccessTest, "GameKit.Golden.Access", GameKitGoldenTests::GoldenTestFlags)

void FGameKitGoldenAccessTest::GetTests(TArray<FString>& OutBeautifiedNames, TArray<FString>& OutTestCommands) const
{
	GameKitGoldenTests::ListGoldenCases(GameKitGoldenTests::AccessFile, OutBeautifiedNames, OutTestCommands);
}

bool FGameKitGoldenAccessTest::RunTest(const FString& Parameters)
{
	return GameKitGoldenTests::RunGoldenCase(*this, GameKitGoldenTests::AccessFile, GameKitGoldenTests::AccessTypes, Parameters);
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitGoldenCoverageTest, "GameKit.Golden.Coverage", GameKitGoldenTests::GoldenTestFlags)

bool FGameKitGoldenCoverageTest::RunTest(const FString&)
{
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::JuiceFile, GameKitGoldenTests::JuiceTypes);
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::ShellFile, GameKitGoldenTests::ShellTypes);
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::AudioFile, GameKitGoldenTests::AudioTypes);
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::MusicFile, GameKitGoldenTests::MusicTypes);
	GameKitGoldenTests::CheckCoverage(*this, GameKitGoldenTests::AccessFile, GameKitGoldenTests::AccessTypes);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitMusicPlanErrorsTest, "GameKit.Golden.MusicErrors", GameKitGoldenTests::GoldenTestFlags)

// music.py raises on a quantize or stinger it does not know (a typo must not mean "phrase" or a one-bar stinger)
// and plans "stinger": "" as no stinger. The golden plans never reach these, so they run here on the golden params.
bool FGameKitMusicPlanErrorsTest::RunTest(const FString&)
{
	using namespace GameKit::Json;
	FString Error;
	const TSharedPtr<FJsonObject> Root = GameKitGoldenTests::LoadGolden(GameKitGoldenTests::MusicFile, Error);
	if (!Root.IsValid())
	{
		AddError(Error);
		return false;
	}
	TSharedPtr<FJsonObject> Params;
	for (const TSharedPtr<FJsonValue>& C : Root->GetArrayField(TEXT("cases")))
	{
		if (Is(C, EJson::Object) && GetString(C->AsObject(), TEXT("type"), FString()) == TEXT("music_plan"))
		{
			Params = FindObject(C->AsObject(), TEXT("params"));
		}
	}
	if (!Params.IsValid())
	{
		AddError(TEXT("music.json has no music_plan params"));
		return false;
	}
	// a rule change on a fresh copy of the params: the first transition matching From -> To gets Key = Value
	auto WithRule = [&Params](const FString& From, const FString& To, const TCHAR* Key, const FString& Value)
	{
		const TSharedPtr<FJsonObject> Copy = Parse(Write(Params.ToSharedRef(), 0))->AsObject();
		for (const TSharedPtr<FJsonValue>& R : Copy->GetArrayField(TEXT("transitions")))
		{
			const TSharedPtr<FJsonObject> Rule = R->AsObject();
			if (GetString(Rule, TEXT("from"), FString()) == From && GetString(Rule, TEXT("to"), FString()) == To)
			{
				Rule->SetStringField(Key, Value);
				break;
			}
		}
		return Copy;
	};
	const FGameKitMusicPlan Typo = FGameKitMusicDirector(WithRule(TEXT("combat"), TEXT("explore"), TEXT("quantize"), TEXT("bars")))
	                                   .Plan(TEXT("combat"), 5000, 0, TEXT("explore"), 50000);
	TestEqual(TEXT("quantize \"bars\" is refused"), Typo.Error, FString(TEXT("unknown quantize bars")));
	const FGameKitMusicPlan Unknown = FGameKitMusicDirector(WithRule(TEXT("*"), TEXT("waltz"), TEXT("stinger"), TEXT("alram")))
	                                      .Plan(TEXT("explore"), 0, 0, TEXT("waltz"), 70000);
	TestEqual(TEXT("an unknown stinger is refused"), Unknown.Error, FString(TEXT("unknown stinger alram")));
	const FGameKitMusicPlan Empty = FGameKitMusicDirector(WithRule(TEXT("*"), TEXT("waltz"), TEXT("stinger"), FString()))
	                                    .Plan(TEXT("explore"), 0, 0, TEXT("waltz"), 70000);
	TestTrue(TEXT("\"stinger\": \"\" plans without an error"), Empty.Error.IsEmpty());
	TestFalse(TEXT("\"stinger\": \"\" sets no stinger_at"), Empty.StingerAt.IsSet());
	TestEqual(TEXT("\"stinger\": \"\" enters the next track at the switch"), Empty.ToStartAt, Empty.SwitchAt);
	return !HasAnyErrors();
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitAudioDirectorErrorsTest, "GameKit.Golden.AudioErrors", GameKitGoldenTests::GoldenTestFlags)

// Where audio_events.py raises, Play returns Error (not Capped) and changes nothing; the variant count is the number
// of files, as in the reference. The golden steps never reach these.
bool FGameKitAudioDirectorErrorsTest::RunTest(const FString&)
{
	using namespace GameKit::Json;
	auto Director = [this](const TCHAR* EventsJson)
	{
		const TSharedPtr<FJsonValue> V = Parse(FString::Printf(TEXT("{\"seed\": 1, \"events\": %s}"), EventsJson));
		TestTrue(TEXT("test params parse"), Is(V, EJson::Object));
		return FGameKitAudioDirector(V->AsObject());
	};
	FGameKitAudioDirector NoVoices = Director(TEXT("{\"x\": {\"bus\": \"sfx\", \"files\": [\"a.wav\"], \"lengths_ms\": [100], \"max_voices\": 0}}"));
	const FGameKitPlayDecision Zero = NoVoices.Play(TEXT("x"), 0.0);
	TestTrue(TEXT("max_voices 0 with steal oldest is an error"), Zero.Result == EGameKitPlayResult::Error);
	TestEqual(TEXT("max_voices 0: the reason"), Zero.Error, FString(TEXT("event x: max_voices must be 1 or more")));

	FGameKitAudioDirector TwoFiles = Director(TEXT("{\"x\": {\"bus\": \"sfx\", \"files\": [\"a\", \"b\"], \"lengths_ms\": [100, 100, 100], \"pick\": \"sequence\"}}"));
	const int32 Want[] = {0, 1, 0};
	for (int32 I = 0; I < 3; ++I)
	{
		TestEqual(FString::Printf(TEXT("sequence over two files, play %d"), I), TwoFiles.Play(TEXT("x"), 500.0 * I).Variant, Want[I]);
	}
	FGameKitAudioDirector Short = Director(TEXT("{\"x\": {\"bus\": \"sfx\", \"files\": [\"a\", \"b\", \"c\"], \"lengths_ms\": [100, 100]}}"));
	TestTrue(TEXT("fewer lengths than files is an error"), Short.Play(TEXT("x"), 0.0).Result == EGameKitPlayResult::Error);

	TestTrue(TEXT("an unknown event is an error"), TwoFiles.Play(TEXT("nope"), 2000.0).Result == EGameKitPlayResult::Error);
	const FGameKitPlayDecision Back = TwoFiles.Play(TEXT("x"), 10.0);
	TestTrue(TEXT("an earlier time is an error, not capped"), Back.Result == EGameKitPlayResult::Error);
	TestTrue(TEXT("an earlier time names the time order"), Back.Error.Contains(TEXT("time order")));
	FString DuckError;
	TwoFiles.Duck(10.0, &DuckError);
	TestTrue(TEXT("Duck at an earlier time sets the error"), DuckError.Contains(TEXT("time order")));
	return !HasAnyErrors();
}

#endif // WITH_DEV_AUTOMATION_TESTS
