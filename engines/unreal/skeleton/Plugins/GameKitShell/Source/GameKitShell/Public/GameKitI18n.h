// ---------------------------------------------------------------------------
// GameKitI18n.h
// Purpose : Localization logic: string lookup through a locale fallback chain with {name} placeholders,
//           plural categories, and the pseudo-locale that finds untranslated, truncated and unsupported
//           text before a translator does. Plain C++ on FString, no FText.
// Usage   : const FGameKitStringTables Tables = GameKit::StringTablesFromJson(GameKit::Json::Parse(Text)->AsObject());
//           GameKit::Tr(Tables, TEXT("fr-CA"), TEXT("greet"), {{TEXT("name"), Player}})   // "Bonjour, Ana !"
//           GameKit::TrPlural(Tables, TEXT("fr"), TEXT("apples"), Count)               // key "apples.one" / "apples.other"
//           GameKit::Pseudo(GameKit::Tr(Tables, TEXT("en"), TEXT("menu.play")))        // "Play" accented, plus "~~", in [ ]
// Notes   : fr-CA falls back to fr, then en. A missing key returns the key itself, so it shows on screen
//           instead of an empty label. Plural rules cover one/other (English-like), French (0 and 1 are
//           "one") and Japanese, Chinese, Korean (always "other"); add a language's rule in Plural() when the
//           game ships it. This is the kit's own small system; Unreal's FText/StringTable localization
//           (the Localization Dashboard) is the alternative for bigger projects, record the choice in an ADR.
//           Table and argument keys are TMap keys, so case-insensitive here. Lengths count characters (code
//           points), not UTF-16 units. Matches tools/golden_vectors.py (tr, plural, pseudo), checked
//           against data/golden/shell.json.
//
// Pseudocode:
//   LocaleChain("fr-CA") = ["fr-CA", "fr", "en"] (duplicates and empty entries dropped)
//   Tr: the first table in the chain that has key, with {name} replaced from args; else key
//   Pseudo: every letter -> accented look-alike, placeholders ({x} %s %d %i %f %%) unchanged,
//           then ceil(visible characters * PseudoGrowth) tildes, all inside [ ]
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

using FGameKitStringTable = TMap<FString, FString>;               // key -> text
using FGameKitStringTables = TMap<FString, FGameKitStringTable>;  // locale -> table
using FGameKitTrArgs = TMap<FString, FString>;                    // placeholder name -> value

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr const TCHAR* FallbackLocale = TEXT("en");
	inline constexpr double PseudoGrowth = 0.40;   // pseudo text is 40 % longer (translated English runs about that long, SOP-19)

	/** Number of characters (code points) in Text: a surrogate pair counts once. */
	GAMEKITSHELL_API int32 CodePointLength(const FString& Text);

	/** "fr-CA" -> "fr", "pt_BR" -> "pt". */
	GAMEKITSHELL_API FString BaseLanguage(const FString& Locale);

	/** The locales to try in order: Locale, its language, then the fallback. */
	GAMEKITSHELL_API TArray<FString> LocaleChain(const FString& Locale, const FString& Fallback = FallbackLocale);

	/** The text for Key in the first locale of the chain that has it, placeholders filled; Key itself when none has it. */
	GAMEKITSHELL_API FString Tr(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key,
	                            const FGameKitTrArgs& Args = FGameKitTrArgs());

	/** The plural category of N for Locale: "one" or "other". */
	GAMEKITSHELL_API FString Plural(const FString& Locale, int64 N);

	/** Tr() of "<Key>.<category>" with {n} set to N. */
	GAMEKITSHELL_API FString TrPlural(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, int64 N,
	                                  const FGameKitTrArgs& Args = FGameKitTrArgs());

	/** The pseudo-locale version of Text (see Notes). */
	GAMEKITSHELL_API FString Pseudo(const FString& Text);

	/** From JSON {"en": {"menu.play": "Play", ...}, "fr": {...}}; non-string entries are skipped. */
	GAMEKITSHELL_API FGameKitStringTables StringTablesFromJson(const TSharedPtr<FJsonObject>& Object);
}

// {{FOOTER}}
