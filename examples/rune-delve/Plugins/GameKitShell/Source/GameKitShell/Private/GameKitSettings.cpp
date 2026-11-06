// ---------------------------------------------------------------------------
// GameKitSettings.cpp
// Purpose : Implementation of the settings defaults, schema and loader (see GameKitSettings.h).
// Usage   : compiled into the GameKitShell module; call through GameKitSettings.h.
// Notes   : One table (SettingsSchema) holds every field's rule, range and default, so the defaults and the
//           validation cannot drift apart. Add a setting there and in docs/GDD.md's settings list (and in the
//           reference, tools/golden_vectors.py, when the kit itself changes). Enum values compare
//           case-sensitively, like the reference: "Fullscreen" is a problem, not "fullscreen".
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitSettings.h"

#include "GameKitAtomicFile.h"
#include "GameKitBindings.h"
#include "GameKitI18n.h"
#include "GameKitJson.h"

namespace GameKit
{
	namespace
	{
		enum class ESettingRule : uint8
		{
			Num,    // a number, clamped to Lo..Hi
			Bool,   // true or false
			Enum,   // one of Choices (strings or numbers)
			Res,    // [width, height], whole numbers >= 1
		};

		struct FSettingField
		{
			FString Name;
			ESettingRule Rule = ESettingRule::Bool;
			TSharedPtr<FJsonValue> Default;
			double Lo = 0.0;
			double Hi = 0.0;
			TArray<TSharedPtr<FJsonValue>> Choices;
		};

		struct FSettingSection
		{
			FString Name;
			TArray<FSettingField> Fields;
		};

		FSettingField SchemaNum(const TCHAR* Name, double Default, double Lo, double Hi)
		{
			FSettingField F;
			F.Name = Name;
			F.Rule = ESettingRule::Num;
			F.Default = Json::MakeNumber(Default);
			F.Lo = Lo;
			F.Hi = Hi;
			return F;
		}

		FSettingField SchemaFlag(const TCHAR* Name, bool bDefault)
		{
			FSettingField F;
			F.Name = Name;
			F.Rule = ESettingRule::Bool;
			F.Default = Json::MakeBool(bDefault);
			return F;
		}

		template <int32 N>
		FSettingField SchemaOneOf(const TCHAR* Name, const TCHAR* Default, const TCHAR* const (&Values)[N])
		{
			FSettingField F;
			F.Name = Name;
			F.Rule = ESettingRule::Enum;
			F.Default = Json::MakeString(Default);
			for (const TCHAR* V : Values)
			{
				F.Choices.Add(Json::MakeString(V));
			}
			return F;
		}

		template <int32 N>
		FSettingField SchemaOneOfNumbers(const TCHAR* Name, double Default, const int32 (&Values)[N])
		{
			FSettingField F;
			F.Name = Name;
			F.Rule = ESettingRule::Enum;
			F.Default = Json::MakeNumber(Default);
			for (const int32 V : Values)
			{
				F.Choices.Add(Json::MakeNumber(V));
			}
			return F;
		}

		FSettingField SchemaResolution(const TCHAR* Name, int32 Width, int32 Height)
		{
			FSettingField F;
			F.Name = Name;
			F.Rule = ESettingRule::Res;
			F.Default = Json::MakeArray({Json::MakeNumber(Width), Json::MakeNumber(Height)});
			return F;
		}

		// ---- Tunables: every validated setting, its default and its allowed values ----
		const TArray<FSettingSection>& SettingsSchema()
		{
			static const TArray<FSettingSection> Sections = []
			{
				TArray<FSettingSection> S;
				S.Add({TEXT("display"), {
					SchemaOneOf(TEXT("mode"), TEXT("windowed"), DisplayModes),
					SchemaFlag(TEXT("vsync"), true),
					SchemaOneOfNumbers(TEXT("frame_cap"), 0, FrameCaps),
					SchemaResolution(TEXT("resolution"), 1920, 1080),
					SchemaNum(TEXT("ui_scale"), 1.0, 0.75, 2.0),
				}});
				S.Add({TEXT("audio"), {
					SchemaNum(TEXT("master"), 1.0, 0.0, 1.0),
					SchemaNum(TEXT("music"), 0.8, 0.0, 1.0),
					SchemaNum(TEXT("sfx"), 1.0, 0.0, 1.0),
					SchemaNum(TEXT("ui"), 1.0, 0.0, 1.0),
					SchemaNum(TEXT("voice"), 1.0, 0.0, 1.0),
					SchemaFlag(TEXT("mono"), false),
				}});
				S.Add({TEXT("access"), {
					SchemaNum(TEXT("text_scale"), 1.0, 0.75, 2.0),
					SchemaFlag(TEXT("subtitles"), true),
					SchemaOneOf(TEXT("subtitle_size"), TEXT("medium"), SubtitleSizes),
					SchemaNum(TEXT("subtitle_background"), 0.6, 0.0, 1.0),
					SchemaFlag(TEXT("speaker_names"), true),
					SchemaFlag(TEXT("subtitle_barks"), false),
					SchemaFlag(TEXT("captions_sfx"), false),
					SchemaOneOf(TEXT("colorblind"), TEXT("none"), ColorblindModes),
					SchemaFlag(TEXT("reduce_motion"), false),
					SchemaNum(TEXT("shake_scale"), 1.0, 0.0, 1.0),
					SchemaFlag(TEXT("flash_limit"), true),
					SchemaFlag(TEXT("hold_to_toggle"), false),
					SchemaOneOf(TEXT("difficulty"), TEXT("normal"), Difficulties),
					SchemaNum(TEXT("game_speed"), 1.0, 0.5, 1.0),
					SchemaFlag(TEXT("readable_font"), false),
					SchemaNum(TEXT("line_spacing"), 1.0, 1.0, 2.0),
					SchemaFlag(TEXT("subtitle_hold"), false),
					SchemaNum(TEXT("timing_scale"), 1.0, 1.0, 3.0),
					SchemaFlag(TEXT("auto_repeat"), false),
				}});
				S.Add({TEXT("input"), {   // input.bindings is handled on its own (FixBindings)
					SchemaNum(TEXT("deadzone"), 0.2, 0.0, 0.9),
					SchemaFlag(TEXT("invert_y"), false),
					SchemaOneOf(TEXT("glyphs"), TEXT("auto"), GlyphSets),
				}});
				S.Add({TEXT("telemetry"), {
					SchemaOneOf(TEXT("consent"), TEXT("unset"), ConsentValues),
				}});
				return S;
			}();
			return Sections;
		}

		const FSettingField* FindSettingField(const FString& Section, const FString& Field)
		{
			for (const FSettingSection& S : SettingsSchema())
			{
				if (S.Name.Equals(Section, ESearchCase::CaseSensitive))
				{
					for (const FSettingField& F : S.Fields)
					{
						if (F.Name.Equals(Field, ESearchCase::CaseSensitive))
						{
							return &F;
						}
					}
				}
			}
			return nullptr;
		}

		bool IsWholeAtLeastOne(const TSharedPtr<FJsonValue>& V)
		{
			if (!Json::Is(V, EJson::Number))
			{
				return false;
			}
			const double N = V->AsNumber();
			return FMath::IsFinite(N) && N >= 1.0 && N == FMath::FloorToDouble(N);
		}

		struct FFixedSetting
		{
			TSharedPtr<FJsonValue> Value;
			bool bProblem = false;   // the file's value had to be replaced or clamped
		};

		/** One field's value after validation, and whether it had to be fixed. */
		FFixedSetting FixSettingField(const FSettingField& F, const TSharedPtr<FJsonValue>& Value)
		{
			switch (F.Rule)
			{
			case ESettingRule::Bool:
				if (Json::Is(Value, EJson::Boolean))
				{
					return {Json::Clone(Value), false};
				}
				break;
			case ESettingRule::Num:
				if (Json::Is(Value, EJson::Number) && !FMath::IsNaN(Value->AsNumber()))
				{
					const double V = Value->AsNumber();
					const double Clamped = FMath::Min(FMath::Max(V, F.Lo), F.Hi);
					return {Json::MakeNumber(Clamped), Clamped != V};
				}
				break;
			case ESettingRule::Enum:
				for (const TSharedPtr<FJsonValue>& Allowed : F.Choices)
				{
					const bool bNumbers = Json::Is(Allowed, EJson::Number) && Json::Is(Value, EJson::Number);
					const bool bStrings = Json::Is(Allowed, EJson::String) && Json::Is(Value, EJson::String);
					if ((bNumbers && Allowed->AsNumber() == Value->AsNumber()) ||
					    (bStrings && Allowed->AsString().Equals(Value->AsString(), ESearchCase::CaseSensitive)))
					{
						return {Json::Clone(Allowed), false};   // 60.0 in the file becomes the choice 60
					}
				}
				break;
			case ESettingRule::Res:
				if (Json::Is(Value, EJson::Array) && Value->AsArray().Num() == 2 && IsWholeAtLeastOne(Value->AsArray()[0]) &&
				    IsWholeAtLeastOne(Value->AsArray()[1]))
				{
					return {Json::MakeArray({Json::MakeNumber(Value->AsArray()[0]->AsNumber()),
					                         Json::MakeNumber(Value->AsArray()[1]->AsNumber())}), false};
				}
				break;
			}
			return {Json::Clone(F.Default), true};
		}

		/** input.bindings: the defaults, with each action the file names replaced by its string entries. */
		TSharedRef<FJsonObject> FixBindings(const TSharedPtr<FJsonValue>& Value, TArray<FString>& Problems)
		{
			TSharedRef<FJsonObject> Out = BindingsToJson(DefaultBindings());
			if (!Json::Is(Value, EJson::Object))
			{
				Problems.Add(TEXT("input.bindings"));
				return Out;
			}
			for (const auto& Pair : Value->AsObject()->Values)
			{
				const FString Action(*Pair.Key);
				if (!Json::Is(Pair.Value, EJson::Array))
				{
					Problems.Add(TEXT("input.bindings.") + Action);
					continue;   // keeps the default for a known action
				}
				TArray<FString> Clean;
				for (const TSharedPtr<FJsonValue>& B : Pair.Value->AsArray())
				{
					if (Json::Is(B, EJson::String))
					{
						Clean.Add(B->AsString());
					}
				}
				if (Clean.Num() != Pair.Value->AsArray().Num())
				{
					Problems.Add(TEXT("input.bindings.") + Action);
				}
				Out->SetField(Action, Json::MakeStringArray(Clean));
			}
			return Out;
		}

		TSharedPtr<FJsonObject> SettingsSection(const FJsonObject& Settings, const FString& Section)
		{
			const TSharedPtr<FJsonValue> V = Settings.TryGetField(Section);
			return Json::Is(V, EJson::Object) ? V->AsObject() : nullptr;
		}

		FGameKitSettingsLoad DefaultsWithProblem(const TCHAR* Problem)
		{
			FGameKitSettingsLoad R;
			R.Settings = DefaultSettings();
			R.Problems.Add(Problem);
			return R;
		}
	}

	TSharedRef<FJsonObject> DefaultSettings()
	{
		TSharedRef<FJsonObject> S = MakeShared<FJsonObject>();
		S->SetNumberField(TEXT("version"), SettingsVersion);
		S->SetStringField(TEXT("language"), FallbackLocale);
		for (const FSettingSection& Section : SettingsSchema())
		{
			TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
			for (const FSettingField& F : Section.Fields)
			{
				Out->SetField(F.Name, Json::Clone(F.Default));
			}
			if (Section.Name == TEXT("input"))
			{
				Out->SetObjectField(TEXT("bindings"), BindingsToJson(DefaultBindings()));
			}
			S->SetObjectField(Section.Name, Out);
		}
		return S;
	}

	FGameKitSettingsLoad SettingsLoad(const TOptional<FString>& Text)
	{
		TSharedPtr<FJsonValue> Raw = Json::MakeObject(MakeShared<FJsonObject>());
		if (Text.IsSet())
		{
			Raw = Json::Parse(Text.GetValue());
			if (!Raw.IsValid())
			{
				return DefaultsWithProblem(TEXT("unreadable"));
			}
		}
		if (!Json::Is(Raw, EJson::Object))
		{
			return DefaultsWithProblem(TEXT("not an object"));
		}
		const TSharedPtr<FJsonObject> Src = Raw->AsObject();
		FGameKitSettingsLoad R;
		R.Settings = Json::CloneObject(Src);   // unknown top-level keys are kept
		R.Settings->SetNumberField(TEXT("version"), SettingsVersion);
		const TSharedPtr<FJsonValue> Lang = Json::Find(Src, TEXT("language"));
		const int32 LangLength = Json::Is(Lang, EJson::String) ? CodePointLength(Lang->AsString()) : 0;
		if (LangLength < LanguageMinLength || LangLength > LanguageMaxLength)
		{
			R.Settings->SetStringField(TEXT("language"), FallbackLocale);
			if (Lang.IsValid())
			{
				R.Problems.Add(TEXT("language"));
			}
		}
		for (const FSettingSection& Section : SettingsSchema())
		{
			TSharedPtr<FJsonObject> From = MakeShared<FJsonObject>();
			const TSharedPtr<FJsonValue> Found = Json::Find(Src, Section.Name);
			if (Found.IsValid())
			{
				if (Json::Is(Found, EJson::Object))
				{
					From = Found->AsObject();
				}
				else
				{
					R.Problems.Add(Section.Name);
				}
			}
			TSharedRef<FJsonObject> Out = Json::CloneObject(From);   // unknown keys inside a section are kept too
			for (const FSettingField& F : Section.Fields)
			{
				const TSharedPtr<FJsonValue> Value = Json::Find(From, F.Name);
				if (!Value.IsValid())
				{
					Out->SetField(F.Name, Json::Clone(F.Default));
					continue;
				}
				const FFixedSetting Fixed = FixSettingField(F, Value);
				if (Fixed.bProblem)
				{
					R.Problems.Add(Section.Name + TEXT(".") + F.Name);
				}
				Out->SetField(F.Name, Fixed.Value);
			}
			if (Section.Name == TEXT("input"))
			{
				const TSharedPtr<FJsonValue> Bindings = Json::Find(From, TEXT("bindings"));
				Out->SetObjectField(TEXT("bindings"), Bindings.IsValid() ? FixBindings(Bindings, R.Problems)
				                                                         : BindingsToJson(DefaultBindings()));
			}
			R.Settings->SetObjectField(Section.Name, Out);
		}
		return R;
	}

	FGameKitSettingsLoad SettingsLoadFile(const FString& File)
	{
		FString Error;
		const TOptional<FString> Text = ReadTextFile(File, &Error);
		if (!Text.IsSet() && !Error.IsEmpty())
		{
			return DefaultsWithProblem(TEXT("unreadable"));
		}
		return SettingsLoad(Text);
	}

	bool SettingsSaveFile(const FString& File, const TSharedRef<FJsonObject>& Settings, FString* OutError)
	{
		return WriteFileAtomic(File, Json::Write(Settings) + TEXT("\n"), OutError);
	}

	double EffectiveShake(const FJsonObject& Settings)
	{
		const TSharedPtr<FJsonObject> Access = SettingsSection(Settings, TEXT("access"));
		if (Json::GetBool(Access, TEXT("reduce_motion"), false))
		{
			return 0.0;
		}
		return Json::GetNumber(Access, TEXT("shake_scale"), 1.0);
	}

	bool TelemetryAllowed(const FJsonObject& Settings)
	{
		const TSharedPtr<FJsonObject> Telemetry = SettingsSection(Settings, TEXT("telemetry"));
		return Json::GetString(Telemetry, TEXT("consent"), FString()).Equals(TEXT("yes"), ESearchCase::CaseSensitive);
	}

	double SettingNumber(const FJsonObject& Settings, const FString& Section, const FString& Field)
	{
		const FSettingField* F = FindSettingField(Section, Field);
		const double Fallback = F && Json::Is(F->Default, EJson::Number) ? F->Default->AsNumber() : 0.0;
		return Json::GetNumber(SettingsSection(Settings, Section), Field, Fallback);
	}

	bool SettingBool(const FJsonObject& Settings, const FString& Section, const FString& Field)
	{
		const FSettingField* F = FindSettingField(Section, Field);
		const bool bFallback = F && Json::Is(F->Default, EJson::Boolean) && F->Default->AsBool();
		return Json::GetBool(SettingsSection(Settings, Section), Field, bFallback);
	}

	FString SettingString(const FJsonObject& Settings, const FString& Section, const FString& Field)
	{
		const FSettingField* F = FindSettingField(Section, Field);
		const FString Fallback = F && Json::Is(F->Default, EJson::String) ? F->Default->AsString() : FString();
		return Json::GetString(SettingsSection(Settings, Section), Field, Fallback);
	}

	FString SettingLanguage(const FJsonObject& Settings)
	{
		const TSharedPtr<FJsonValue> V = Settings.TryGetField(TEXT("language"));
		return Json::Is(V, EJson::String) ? V->AsString() : FString(FallbackLocale);
	}

	FIntPoint SettingResolution(const FJsonObject& Settings)
	{
		const TSharedPtr<FJsonValue> V = Json::Find(SettingsSection(Settings, TEXT("display")), TEXT("resolution"));
		const FSettingField* F = FindSettingField(TEXT("display"), TEXT("resolution"));
		const TSharedPtr<FJsonValue>& Use = FixSettingField(*F, V).bProblem ? F->Default : V;   // a bad value: the default
		const double MaxSide = static_cast<double>(MAX_int32);   // the reference takes any whole number; FIntPoint must not overflow
		return FIntPoint(static_cast<int32>(FMath::Min(Use->AsArray()[0]->AsNumber(), MaxSide)),
		                 static_cast<int32>(FMath::Min(Use->AsArray()[1]->AsNumber(), MaxSide)));
	}
}
