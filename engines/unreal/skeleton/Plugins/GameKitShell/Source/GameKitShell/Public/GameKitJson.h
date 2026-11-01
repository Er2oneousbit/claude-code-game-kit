// ---------------------------------------------------------------------------
// GameKitJson.h
// Purpose : Small helpers on Unreal's Json module for the settings and save files: parse, deep copy, a
//           writer with tidy numbers and sorted keys, typed lookups that never log, and a structural compare.
// Usage   : const TSharedPtr<FJsonValue> V = GameKit::Json::Parse(Text);        // null when not JSON
//           const double Master = GameKit::Json::GetNumber(Audio, TEXT("master"), 1.0);
//           const FString Text = GameKit::Json::Write(Object);                  // pretty, keys sorted
//           const FString Why = GameKit::Json::Diff(Got, Want, 1e-6);           // "" when equal
// Notes   : Why not the engine's calls directly: FJsonValue::Duplicate drops null values, the engine writer
//           prints 0.8 as 0.80000000000000004 (%.17g), and AsString()/AsObject() on the wrong type log an
//           error, which fails any automation test that runs the code. Types are checked on Type here
//           (TryGetNumber also converts bools and numeric strings). Unreal's reader wants an object or an
//           array at the top level; a bare scalar ("5") does not parse. Object keys are case-insensitive
//           (FJsonObject is a TMap), unlike the Python reference: a file with both "Audio" and "audio"
//           keeps one of them.
//
// Pseudocode:
//   Write: objects with keys in case-sensitive order, numbers with the fewest digits (15, 16 or 17) that
//          read back to the same double, strings escaped per RFC 8259 (non-ASCII kept), Indent 0 = one line
//   Diff : numbers within tolerance, other scalars equal, arrays in order, objects as key sets -> first mismatch
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"

namespace GameKit::Json
{
	// ---- Tunables ----
	inline constexpr int32 DefaultIndent = 2;   // spaces per level in written files (players open them in an editor)

	/** Text as JSON, or null when it is not valid JSON. */
	GAMEKITSHELL_API TSharedPtr<FJsonValue> Parse(const FString& Text);

	/** Deep copies; a null input gives a JSON null (or an empty object). */
	GAMEKITSHELL_API TSharedPtr<FJsonValue> Clone(const TSharedPtr<FJsonValue>& Value);
	GAMEKITSHELL_API TSharedRef<FJsonObject> CloneObject(const TSharedPtr<FJsonObject>& Object);

	/** JSON text; Indent 0 writes one line. Keys sorted, numbers short (0.8, 1920), non-finite numbers as null. */
	GAMEKITSHELL_API FString Write(const TSharedPtr<FJsonValue>& Value, int32 Indent = DefaultIndent);
	GAMEKITSHELL_API FString Write(const TSharedRef<FJsonObject>& Object, int32 Indent = DefaultIndent);

	/** The shortest text that reads back as exactly this double ("0.8", "1e-06", "1920"). */
	GAMEKITSHELL_API FString FormatNumber(double Value);

	/** Keys of an object in case-sensitive order (Python's sorted()). */
	GAMEKITSHELL_API TArray<FString> SortedKeys(const FJsonObject& Object);

	/** "" when Got matches Want (numbers within Tolerance), else the path and the difference ("$.audio.master: ..."). */
	GAMEKITSHELL_API FString Diff(const TSharedPtr<FJsonValue>& Got, const TSharedPtr<FJsonValue>& Want, double Tolerance = 0.0,
	                              const FString& At = TEXT("$"));

	// ---- Typed lookups: nullptr / the fallback when the key is missing or holds another type ----
	inline bool Is(const TSharedPtr<FJsonValue>& Value, EJson Type) { return Value.IsValid() && Value->Type == Type; }
	GAMEKITSHELL_API TSharedPtr<FJsonValue> Find(const TSharedPtr<FJsonObject>& Object, const FString& Key);
	GAMEKITSHELL_API TSharedPtr<FJsonObject> FindObject(const TSharedPtr<FJsonObject>& Object, const FString& Key);
	GAMEKITSHELL_API double GetNumber(const TSharedPtr<FJsonObject>& Object, const FString& Key, double Fallback);
	GAMEKITSHELL_API bool GetBool(const TSharedPtr<FJsonObject>& Object, const FString& Key, bool bFallback);
	GAMEKITSHELL_API FString GetString(const TSharedPtr<FJsonObject>& Object, const FString& Key, const FString& Fallback);

	// ---- Value makers ----
	inline TSharedPtr<FJsonValue> MakeNumber(double Value) { return MakeShared<FJsonValueNumber>(Value); }
	inline TSharedPtr<FJsonValue> MakeString(const FString& Value) { return MakeShared<FJsonValueString>(Value); }
	inline TSharedPtr<FJsonValue> MakeBool(bool bValue) { return MakeShared<FJsonValueBoolean>(bValue); }
	inline TSharedPtr<FJsonValue> MakeNull() { return MakeShared<FJsonValueNull>(); }
	inline TSharedPtr<FJsonValue> MakeArray(const TArray<TSharedPtr<FJsonValue>>& Items) { return MakeShared<FJsonValueArray>(Items); }
	inline TSharedPtr<FJsonValue> MakeObject(const TSharedPtr<FJsonObject>& Value) { return MakeShared<FJsonValueObject>(Value); }
	GAMEKITSHELL_API TSharedPtr<FJsonValue> MakeStringArray(const TArray<FString>& Items);
}

// {{FOOTER}}
