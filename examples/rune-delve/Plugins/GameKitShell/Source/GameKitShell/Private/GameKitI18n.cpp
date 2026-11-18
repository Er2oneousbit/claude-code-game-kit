// ---------------------------------------------------------------------------
// GameKitI18n.cpp
// Purpose : Implementation of lookup, CLDR plurals, @clean variants, the word mask and the pseudo-locale (see
//           GameKitI18n.h).
// Usage   : compiled into the GameKitShell module; call through GameKitI18n.h.
// Notes   : FString is UTF-16: '{', '}' and '%' never appear inside a surrogate pair, so scanning code units
//           is safe, and only the length count needs to skip the second half of a pair. The accented
//           look-alikes are written as code points so the result does not depend on the source encoding.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-17 with Claude (Opus 5.5, claude-opus-5-5): CLDR 46 plural families, the .other fallback per
//           locale, @clean lookups, MaskWords and MatureWords (#207, #87)
// Updated : 2026-11-18 with Claude (Opus 5.5, claude-opus-5-5): CompileWords, MaskWordSet, TrSet, TrPluralSet and
//           FGameKitWordCache (#207)
// ---------------------------------------------------------------------------
#include "GameKitI18n.h"

#include "GameKitJson.h"

const FGameKitWordSet& FGameKitWordCache::Get(const FString& Locale)
{
	if (!bValid || !Locale.Equals(CachedLocale, ESearchCase::CaseSensitive))
	{
		TArray<FString> Words;
		for (const FString& Loc : GameKit::LocaleChain(Locale))
		{
			if (const TArray<FString>* List = Lists.Find(Loc))
			{
				Words.Append(*List);
			}
		}
		Set = GameKit::CompileWords(Words);
		CachedLocale = Locale;
		bValid = true;
		++FoldCount;
	}
	return Set;
}

namespace GameKit
{
	namespace
	{
		bool IsLowSurrogate(TCHAR C)
		{
			return static_cast<uint32>(C) >= 0xDC00 && static_cast<uint32>(C) <= 0xDFFF;
		}

		/** The index of the first '}' at or after From, or INDEX_NONE. */
		int32 FindClosingBrace(const FString& Text, int32 From)
		{
			for (int32 J = From; J < Text.Len(); ++J)
			{
				if (Text[J] == TEXT('}'))
				{
					return J;
				}
			}
			return INDEX_NONE;
		}

		/** Replaces {name} with Args[name]; unknown placeholders and lone braces stay as they are. */
		FString FillPlaceholders(const FString& Text, const FGameKitTrArgs& Args)
		{
			FString Out;
			int32 I = 0;
			while (I < Text.Len())
			{
				if (Text[I] == TEXT('{'))
				{
					const int32 J = FindClosingBrace(Text, I);
					if (J != INDEX_NONE)
					{
						if (const FString* Value = Args.Find(Text.Mid(I + 1, J - I - 1)))
						{
							Out += *Value;
							I = J + 1;
							continue;
						}
					}
				}
				Out.AppendChar(Text[I]);
				++I;
			}
			return Out;
		}

		/** The accented look-alike of an ASCII letter, or the character itself. */
		TCHAR PseudoChar(TCHAR C)
		{
			switch (C)
			{
			case TEXT('a'): return static_cast<TCHAR>(0x00E1);   // a acute
			case TEXT('e'): return static_cast<TCHAR>(0x00E9);
			case TEXT('i'): return static_cast<TCHAR>(0x00ED);
			case TEXT('o'): return static_cast<TCHAR>(0x00F3);
			case TEXT('u'): return static_cast<TCHAR>(0x00FA);
			case TEXT('c'): return static_cast<TCHAR>(0x00E7);   // c cedilla
			case TEXT('n'): return static_cast<TCHAR>(0x00F1);   // n tilde
			case TEXT('y'): return static_cast<TCHAR>(0x00FD);
			case TEXT('A'): return static_cast<TCHAR>(0x00C1);
			case TEXT('E'): return static_cast<TCHAR>(0x00C9);
			case TEXT('I'): return static_cast<TCHAR>(0x00CD);
			case TEXT('O'): return static_cast<TCHAR>(0x00D3);
			case TEXT('U'): return static_cast<TCHAR>(0x00DA);
			case TEXT('C'): return static_cast<TCHAR>(0x00C7);
			case TEXT('N'): return static_cast<TCHAR>(0x00D1);
			case TEXT('Y'): return static_cast<TCHAR>(0x00DD);
			default:        return C;
			}
		}

		bool IsPrintfPlaceholder(TCHAR C)
		{
			return C == TEXT('s') || C == TEXT('d') || C == TEXT('i') || C == TEXT('f') || C == TEXT('%');
		}
	}

	int32 CodePointLength(const FString& Text)
	{
		int32 N = 0;
		for (const TCHAR C : Text)
		{
			N += IsLowSurrogate(C) ? 0 : 1;
		}
		return N;
	}

	FString BaseLanguage(const FString& Locale)
	{
		int32 Dash = INDEX_NONE;
		const FString First = Locale.FindChar(TEXT('-'), Dash) ? Locale.Left(Dash) : Locale;
		int32 Underscore = INDEX_NONE;
		return First.FindChar(TEXT('_'), Underscore) ? First.Left(Underscore) : First;
	}

	TArray<FString> LocaleChain(const FString& Locale, const FString& Fallback)
	{
		TArray<FString> Chain;
		for (const FString& Loc : {Locale, BaseLanguage(Locale), Fallback})
		{
			const bool bSeen = Chain.ContainsByPredicate([&Loc](const FString& C) { return C.Equals(Loc, ESearchCase::CaseSensitive); });
			if (!Loc.IsEmpty() && !bSeen)
			{
				Chain.Add(Loc);
			}
		}
		return Chain;
	}

	namespace
	{
		// One table's text for Key: Key@clean first when bClean, else Key; nullptr when neither
		const FString* Pick(const FGameKitStringTables& Tables, const FString& Loc, const FString& Key, bool bClean)
		{
			const FGameKitStringTable* Table = Tables.Find(Loc);
			if (!Table)
			{
				return nullptr;
			}
			if (bClean)
			{
				if (const FString* Clean = Table->Find(Key + CleanSuffix))
				{
					return Clean;
				}
			}
			return Table->Find(Key);
		}

		FString Finish(const FString& Text, const FGameKitTrArgs& Args, bool bClean, const FGameKitWordSet& Words)
		{
			const FString Out = FillPlaceholders(Text, Args);
			return bClean && Words.Num() > 0 ? MaskWordSet(Out, Words) : Out;
		}

		// CLDR 46 whole-number plural rules: family -> languages (the reference's PLURAL_LANGUAGES)
		const TCHAR* const PluralLanguages[][2] = {
			{TEXT("other"), TEXT("ja zh ko vi th id ms lo my km yo ig jv su")},
			{TEXT("one"), TEXT("en de nl sv da nb nn no fi et gl el hu tr bg eu af sq ka kk ky mn az uz ur sw ta te ml mr")},
			{TEXT("zero_one"), TEXT("hi bn fa gu kn hy")}, {TEXT("one_many"), TEXT("es it ca")},
			{TEXT("zero_one_many"), TEXT("fr pt")}, {TEXT("one_21"), TEXT("is mk")}, {TEXT("fil"), TEXT("fil tl")},
			{TEXT("east_slavic"), TEXT("ru uk be")}, {TEXT("pl"), TEXT("pl")}, {TEXT("cs"), TEXT("cs sk")},
			{TEXT("lt"), TEXT("lt")}, {TEXT("balkan"), TEXT("hr sr bs")}, {TEXT("ro"), TEXT("ro mo")},
			{TEXT("lv"), TEXT("lv")}, {TEXT("he"), TEXT("he")}, {TEXT("sl"), TEXT("sl")}, {TEXT("ga"), TEXT("ga")},
			{TEXT("ar"), TEXT("ar")}, {TEXT("cy"), TEXT("cy")},
		};

		// The rule family: the full locale (pt-PT) first, then its language, then English's rule
		FString PluralFamily(const FString& Locale)
		{
			const FString Norm = Locale.Replace(TEXT("_"), TEXT("-")).ToLower();
			if (Norm.Equals(TEXT("pt-pt")) || Norm.StartsWith(TEXT("pt-pt-")))
			{
				return TEXT("one_many");
			}
			int32 Dash = INDEX_NONE;
			const FString Lang = Norm.FindChar(TEXT('-'), Dash) ? Norm.Left(Dash) : Norm;
			for (const auto& Fam : PluralLanguages)
			{
				TArray<FString> Langs;
				FString(Fam[1]).ParseIntoArray(Langs, TEXT(" "));
				if (Langs.Contains(Lang))
				{
					return Fam[0];
				}
			}
			return TEXT("one");
		}

		// code point ranges that are never part of a word (the reference's MASK_BOUNDARY_RANGES)
		const uint32 MaskBoundaryRanges[][2] = {
			{0x0080, 0x00BF}, {0x00D7, 0x00D7}, {0x00F7, 0x00F7}, {0x2000, 0x2BFF}, {0x2E00, 0x2E7F},
			{0x3000, 0x303F}, {0xFE00, 0xFE0F}, {0xFE10, 0xFE1F}, {0xFE30, 0xFE6F}, {0xFEFF, 0xFEFF},
			{0xFF00, 0xFF0F}, {0xFF1A, 0xFF20}, {0xFF3B, 0xFF40}, {0xFF5B, 0xFF65}, {0x1F000, 0x1FAFF},
		};

		bool IsWordChar(uint32 Cp)
		{
			if (Cp < 0x80)
			{
				return (Cp >= 0x30 && Cp <= 0x39) || (Cp >= 0x41 && Cp <= 0x5A) || (Cp >= 0x61 && Cp <= 0x7A);
			}
			for (const auto& R : MaskBoundaryRanges)
			{
				if (Cp >= R[0] && Cp <= R[1])
				{
					return false;
				}
			}
			return true;
		}

		// The pinned case fold (the reference's fold_char): one code point to one code point
		uint32 FoldChar(uint32 Cp)
		{
			if ((Cp >= 0x41 && Cp <= 0x5A) || (Cp >= 0xC0 && Cp <= 0xDE && Cp != 0xD7)) return Cp + 0x20;
			if (Cp == 0x130) return 0x69;
			if (Cp == 0x178) return 0xFF;
			if (((Cp >= 0x100 && Cp <= 0x12F) || (Cp >= 0x132 && Cp <= 0x137) || (Cp >= 0x14A && Cp <= 0x177)) && Cp % 2 == 0) return Cp + 1;
			if (((Cp >= 0x139 && Cp <= 0x148) || (Cp >= 0x179 && Cp <= 0x17E)) && Cp % 2 == 1) return Cp + 1;
			if (Cp >= 0x391 && Cp <= 0x3AB && Cp != 0x3A2) return Cp + 0x20;
			if (Cp == 0x386) return 0x3AC;
			if (Cp >= 0x388 && Cp <= 0x38A) return Cp + 0x25;
			if (Cp == 0x38C) return 0x3CC;
			if (Cp == 0x38E || Cp == 0x38F) return Cp + 0x3F;
			if (Cp == 0x3C2) return 0x3C3;
			if (Cp >= 0x400 && Cp <= 0x40F) return Cp + 0x50;
			if (Cp >= 0x410 && Cp <= 0x42F) return Cp + 0x20;
			return Cp;
		}

		// The code point at I (a surrogate pair is one) and how many UTF-16 units it takes
		uint32 CodePointAt(const FString& S, int32 I, int32& Units)
		{
			const uint32 C = static_cast<uint32>(S[I]);
			if (C >= 0xD800 && C <= 0xDBFF && I + 1 < S.Len())
			{
				const uint32 Low = static_cast<uint32>(S[I + 1]);
				if (Low >= 0xDC00 && Low <= 0xDFFF)
				{
					Units = 2;
					return 0x10000 + ((C - 0xD800) << 10) + (Low - 0xDC00);
				}
			}
			Units = 1;
			return C;
		}

		// A word (folded code points as a key) or a gap (empty key), its first unit and its length in units
		struct FWordPart
		{
			int32 Start = 0;
			int32 Len = 0;
			FString Key;
			int32 Count = 0;
		};

		TArray<FWordPart> Scan(const FString& Text)
		{
			TArray<FWordPart> Parts;
			int32 I = 0;
			while (I < Text.Len())
			{
				int32 Units = 1;
				uint32 Cp = CodePointAt(Text, I, Units);
				if (!IsWordChar(Cp))
				{
					Parts.Add({I, Units, FString(), 0});
					I += Units;
					continue;
				}
				FWordPart W;
				W.Start = I;
				while (I < Text.Len())
				{
					Cp = CodePointAt(Text, I, Units);
					if (!IsWordChar(Cp))
					{
						break;
					}
					W.Key += FString::Printf(TEXT("%u,"), FoldChar(Cp));
					W.Count++;
					I += Units;
				}
				W.Len = I - W.Start;
				Parts.Add(MoveTemp(W));
			}
			return Parts;
		}
	}

	const FString* Lookup(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, bool bClean)
	{
		for (const FString& Loc : LocaleChain(Locale))
		{
			if (const FString* Text = Pick(Tables, Loc, Key, bClean))
			{
				return Text;
			}
		}
		return nullptr;
	}

	FString Tr(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, const FGameKitTrArgs& Args,
	           bool bClean, const TArray<FString>& Words)
	{
		return TrSet(Tables, Locale, Key, Args, bClean, bClean ? CompileWords(Words) : FGameKitWordSet());
	}

	FString TrSet(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, const FGameKitTrArgs& Args,
	              bool bClean, const FGameKitWordSet& Words)
	{
		const FString* Text = Lookup(Tables, Locale, Key, bClean);
		return Text ? Finish(*Text, Args, bClean, Words) : Key;
	}

	FGameKitWordSet CompileWords(const TArray<FString>& Words)
	{
		FGameKitWordSet Wanted;
		for (const FString& W : Words)
		{
			const TArray<FWordPart> Parts = Scan(W);
			if (Parts.Num() == 1 && !Parts[0].Key.IsEmpty())
			{
				Wanted.Add(Parts[0].Key);
			}
		}
		return Wanted;
	}

	FString MaskWords(const FString& Text, const TArray<FString>& Words)
	{
		return MaskWordSet(Text, CompileWords(Words));
	}

	FString MaskWordSet(const FString& Text, const FGameKitWordSet& Wanted)
	{
		if (Wanted.Num() == 0)
		{
			return Text;
		}
		const FString Mask = Grawlix;
		FString Out;
		for (const FWordPart& P : Scan(Text))
		{
			if (!P.Key.IsEmpty() && Wanted.Contains(P.Key))
			{
				for (int32 K = 0; K < P.Count; ++K)
				{
					Out.AppendChar(Mask[K % Mask.Len()]);
				}
			}
			else
			{
				Out += Text.Mid(P.Start, P.Len);
			}
		}
		return Out;
	}

	TArray<FString> MatureWords(const TSharedPtr<FJsonObject>& Object)
	{
		TArray<FString> Out;
		const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
		if (Object.IsValid() && Object->TryGetArrayField(TEXT("words"), List) && List)
		{
			for (const TSharedPtr<FJsonValue>& W : *List)
			{
				if (W.IsValid() && W->Type == EJson::String)
				{
					Out.Add(W->AsString());
				}
			}
		}
		return Out;
	}

	FString Plural(const FString& Locale, int64 Count)
	{
		const FString Fam = PluralFamily(Locale);
		const int64 N = Count < 0 ? -Count : Count;
		const int64 M10 = N % 10;
		const int64 M100 = N % 100;
		auto In = [](int64 V, int64 Lo, int64 Hi) { return V >= Lo && V <= Hi; };
		auto Is = [&Fam](const TCHAR* Name) { return Fam.Equals(Name, ESearchCase::CaseSensitive); };
		if (Is(TEXT("other"))) return TEXT("other");
		if (Is(TEXT("one"))) return N == 1 ? TEXT("one") : TEXT("other");
		if (Is(TEXT("zero_one"))) return N <= 1 ? TEXT("one") : TEXT("other");
		if (Is(TEXT("one_many")) || Is(TEXT("zero_one_many")))
		{
			if (N == 1 || (N == 0 && Is(TEXT("zero_one_many")))) return TEXT("one");
			return N != 0 && N % 1000000 == 0 ? TEXT("many") : TEXT("other");
		}
		if (Is(TEXT("one_21"))) return M10 == 1 && M100 != 11 ? TEXT("one") : TEXT("other");
		if (Is(TEXT("fil"))) return M10 == 4 || M10 == 6 || M10 == 9 ? TEXT("other") : TEXT("one");
		if (Is(TEXT("east_slavic")) || Is(TEXT("balkan")))
		{
			if (M10 == 1 && M100 != 11) return TEXT("one");
			if (In(M10, 2, 4) && !In(M100, 12, 14)) return TEXT("few");
			return Is(TEXT("east_slavic")) ? TEXT("many") : TEXT("other");
		}
		if (Is(TEXT("pl")))
		{
			if (N == 1) return TEXT("one");
			return In(M10, 2, 4) && !In(M100, 12, 14) ? TEXT("few") : TEXT("many");
		}
		if (Is(TEXT("cs"))) return N == 1 ? TEXT("one") : In(N, 2, 4) ? TEXT("few") : TEXT("other");
		if (Is(TEXT("lt")))
		{
			if (In(M100, 11, 19)) return TEXT("other");
			return M10 == 1 ? TEXT("one") : M10 >= 2 ? TEXT("few") : TEXT("other");
		}
		if (Is(TEXT("ro")))
		{
			if (N == 1) return TEXT("one");
			return N == 0 || In(M100, 1, 19) ? TEXT("few") : TEXT("other");
		}
		if (Is(TEXT("lv")))
		{
			if (M10 == 0 || In(M100, 11, 19)) return TEXT("zero");
			return M10 == 1 ? TEXT("one") : TEXT("other");
		}
		if (Is(TEXT("he"))) return N == 1 ? TEXT("one") : N == 2 ? TEXT("two") : TEXT("other");
		if (Is(TEXT("sl"))) return M100 == 1 ? TEXT("one") : M100 == 2 ? TEXT("two") : In(M100, 3, 4) ? TEXT("few") : TEXT("other");
		if (Is(TEXT("ga")))
		{
			return N == 1 ? TEXT("one") : N == 2 ? TEXT("two") : In(N, 3, 6) ? TEXT("few") : In(N, 7, 10) ? TEXT("many") : TEXT("other");
		}
		if (Is(TEXT("ar")))
		{
			if (N == 0) return TEXT("zero");
			if (N == 1) return TEXT("one");
			if (N == 2) return TEXT("two");
			return In(M100, 3, 10) ? TEXT("few") : M100 >= 11 ? TEXT("many") : TEXT("other");
		}
		if (Is(TEXT("cy")))
		{
			return N == 0 ? TEXT("zero") : N == 1 ? TEXT("one") : N == 2 ? TEXT("two") : N == 3 ? TEXT("few") : N == 6 ? TEXT("many") : TEXT("other");
		}
		return TEXT("other");
	}

	FString TrPlural(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, int64 N,
	                 const FGameKitTrArgs& Args, bool bClean, const TArray<FString>& Words)
	{
		return TrPluralSet(Tables, Locale, Key, N, Args, bClean, bClean ? CompileWords(Words) : FGameKitWordSet());
	}

	FString TrPluralSet(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, int64 N,
	                    const FGameKitTrArgs& Args, bool bClean, const FGameKitWordSet& Words)
	{
		FGameKitTrArgs A = Args;
		A.Add(TEXT("n"), FString::Printf(TEXT("%lld"), static_cast<long long>(N)));
		for (const FString& Loc : LocaleChain(Locale))
		{
			const FString Cat = Plural(Loc, N);
			const FString* Text = Pick(Tables, Loc, Key + TEXT(".") + Cat, bClean);
			if (!Text && !Cat.Equals(TEXT("other")))
			{
				Text = Pick(Tables, Loc, Key + TEXT(".other"), bClean);
			}
			if (Text)
			{
				return Finish(*Text, A, bClean, Words);
			}
		}
		return Key + TEXT(".") + Plural(Locale, N);
	}

	FString Pseudo(const FString& Text)
	{
		FString Out = TEXT("[");
		int32 Visible = 0;
		int32 I = 0;
		while (I < Text.Len())
		{
			const TCHAR C = Text[I];
			if (C == TEXT('{'))
			{
				const int32 J = FindClosingBrace(Text, I);
				if (J != INDEX_NONE)   // a {name} placeholder passes through and does not count
				{
					Out += Text.Mid(I, J - I + 1);
					I = J + 1;
					continue;
				}
			}
			if (C == TEXT('%') && I + 1 < Text.Len() && IsPrintfPlaceholder(Text[I + 1]))
			{
				Out += Text.Mid(I, 2);   // printf-style placeholder or a literal %%
				I += 2;
				continue;
			}
			Out.AppendChar(PseudoChar(C));
			Visible += IsLowSurrogate(C) ? 0 : 1;   // one visible character per code point
			++I;
		}
		Out += FString::ChrN(static_cast<int32>(FMath::CeilToDouble(Visible * PseudoGrowth)), TEXT('~'));
		Out += TEXT("]");
		return Out;
	}

	FGameKitStringTables StringTablesFromJson(const TSharedPtr<FJsonObject>& Object)
	{
		FGameKitStringTables Tables;
		if (!Object.IsValid())
		{
			return Tables;
		}
		for (const auto& Locale : Object->Values)
		{
			if (!Json::Is(Locale.Value, EJson::Object))
			{
				continue;
			}
			FGameKitStringTable& Table = Tables.Add(FString(*Locale.Key));
			for (const auto& Entry : Locale.Value->AsObject()->Values)
			{
				if (Json::Is(Entry.Value, EJson::String))
				{
					Table.Add(FString(*Entry.Key), Entry.Value->AsString());
				}
			}
		}
		return Tables;
	}
}
