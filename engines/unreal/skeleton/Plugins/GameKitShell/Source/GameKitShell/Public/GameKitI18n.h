// ---------------------------------------------------------------------------
// GameKitI18n.h
// Purpose : Localization logic: string lookup through a locale fallback chain with {name} placeholders,
//           CLDR plural categories, clean-language variants with a word mask, and the pseudo-locale that finds
//           untranslated, truncated and unsupported text before a translator does. Plain C++ on FString, no FText.
// Usage   : const FGameKitStringTables Tables = GameKit::StringTablesFromJson(GameKit::Json::Parse(Text)->AsObject());
//           GameKit::Tr(Tables, TEXT("fr-CA"), TEXT("greet"), {{TEXT("name"), Player}})   // "Bonjour, Ana !"
//           GameKit::TrPlural(Tables, TEXT("fr"), TEXT("apples"), Count)               // key "apples.one" / "apples.other"
//           GameKit::Pseudo(GameKit::Tr(Tables, TEXT("en"), TEXT("menu.play")))        // "Play" accented, plus "~~", in [ ]
//           GameKit::Tr(Tables, TEXT("en"), TEXT("guard.insult"), {}, true, Words)      // @clean line, words masked
// Notes   : fr-CA falls back to fr, then en. A missing key returns the key itself, so it shows on screen
//           instead of an empty label. Plural rules are CLDR 46's for whole numbers (tools/golden_vectors.py
//           PLURAL_FAMILIES); each locale of the chain uses its own rule and falls back to its .other. With clean
//           on (content.clean_language) each locale gives key@clean, then key, and the filled text goes through
//           MaskWords, which walks code points (a surrogate pair is one) with the reference's pinned ranges and
//           case fold. This is the kit's own small system; Unreal's FText/StringTable localization
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
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plurals with the .other fallback per locale,
//           @clean variants, MaskWords and MatureWords (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): CompileWords, MaskWordSet, Tr/TrPlural on a compiled
//           set and FGameKitWordCache, so the shell folds its word list once per locale and list (#207)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

using FGameKitStringTable = TMap<FString, FString>;               // key -> text
using FGameKitStringTables = TMap<FString, FGameKitStringTable>;  // locale -> table
using FGameKitTrArgs = TMap<FString, FString>;                    // placeholder name -> value
using FGameKitWordSet = TSet<FString>;                            // a word list folded once (CompileWords)

namespace GameKit
{
	// ---- Tunables ----
	inline constexpr const TCHAR* FallbackLocale = TEXT("en");
	inline constexpr double PseudoGrowth = 0.40;   // pseudo text is 40 % longer (translated English runs about that long, SOP-19)
	inline constexpr const TCHAR* CleanSuffix = TEXT("@clean");   // "guard.insult@clean": the line with clean language on
	inline constexpr const TCHAR* Grawlix = TEXT("#@$%");          // the mask: one character per code point, per word

	/** Number of characters (code points) in Text: a surrogate pair counts once. */
	GAMEKITSHELL_API int32 CodePointLength(const FString& Text);

	/** "fr-CA" -> "fr", "pt_BR" -> "pt". */
	GAMEKITSHELL_API FString BaseLanguage(const FString& Locale);

	/** The locales to try in order: Locale, its language, then the fallback. */
	GAMEKITSHELL_API TArray<FString> LocaleChain(const FString& Locale, const FString& Fallback = FallbackLocale);

	/** The raw text for Key through the chain (per locale Key@clean first when bClean), or nullptr. */
	GAMEKITSHELL_API const FString* Lookup(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key,
	                                       bool bClean = false);

	/** The text for Key in the first locale of the chain that has it (per locale Key@clean first when bClean),
	 *  placeholders filled, then masked with Words when bClean; Key itself when none has it. */
	GAMEKITSHELL_API FString Tr(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key,
	                            const FGameKitTrArgs& Args = FGameKitTrArgs(), bool bClean = false,
	                            const TArray<FString>& Words = TArray<FString>());

	/** The CLDR plural category of a whole number N for Locale: zero, one, two, few, many or other. */
	GAMEKITSHELL_API FString Plural(const FString& Locale, int64 N);

	/** "<Key>.<category>" through the chain, each locale with its own category, then its "<Key>.other"; {n} set to
	 *  N. Nothing anywhere: "<Key>.<category>" itself. */
	GAMEKITSHELL_API FString TrPlural(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, int64 N,
	                                  const FGameKitTrArgs& Args = FGameKitTrArgs(), bool bClean = false,
	                                  const TArray<FString>& Words = TArray<FString>());

	/** Text with every whole word that is in Words (case folded, code points) replaced by a same-length grawlix. */
	GAMEKITSHELL_API FString MaskWords(const FString& Text, const TArray<FString>& Words);

	/** A word list file's words (data/i18n/mature/<locale>.json: {"words": [...]}); anything else is no words. */
	GAMEKITSHELL_API TArray<FString> MatureWords(const TSharedPtr<FJsonObject>& Object);

	/** The folded set MaskWordSet matches against: build it once per word list (T() runs for every label every frame). */
	GAMEKITSHELL_API FGameKitWordSet CompileWords(const TArray<FString>& Words);

	/** MaskWords with the list compiled already. */
	GAMEKITSHELL_API FString MaskWordSet(const FString& Text, const FGameKitWordSet& Wanted);

	/** Tr() and TrPlural() with the words compiled already (the shell's cache). */
	GAMEKITSHELL_API FString TrSet(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key,
	                               const FGameKitTrArgs& Args, bool bClean, const FGameKitWordSet& Words);
	GAMEKITSHELL_API FString TrPluralSet(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key,
	                                     int64 N, const FGameKitTrArgs& Args, bool bClean, const FGameKitWordSet& Words);
}

/** The word lists per locale and the chain's folded set: Get() folds once per locale; SetLists() drops the fold. */
class GAMEKITSHELL_API FGameKitWordCache
{
public:
	void SetLists(TMap<FString, TArray<FString>> InLists) { Lists = MoveTemp(InLists); bValid = false; }
	const TMap<FString, TArray<FString>>& GetLists() const { return Lists; }
	/** The folded words of every locale in Locale's chain (a fallback line can come from any of them). */
	const FGameKitWordSet& Get(const FString& Locale);
	int32 Folds() const { return FoldCount; }   // how many times Get() folded (tests)

private:
	TMap<FString, TArray<FString>> Lists;
	FString CachedLocale;
	FGameKitWordSet Set;
	bool bValid = false;
	int32 FoldCount = 0;
};

namespace GameKit
{

	/** The pseudo-locale version of Text (see Notes). */
	GAMEKITSHELL_API FString Pseudo(const FString& Text);

	/** From JSON {"en": {"menu.play": "Play", ...}, "fr": {...}}; non-string entries are skipped. */
	GAMEKITSHELL_API FGameKitStringTables StringTablesFromJson(const TSharedPtr<FJsonObject>& Object);
}

// {{FOOTER}}
