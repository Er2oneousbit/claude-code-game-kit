// ---------------------------------------------------------------------------
// GameKitI18n.cpp
// Purpose : Implementation of lookup, plurals and the pseudo-locale (see GameKitI18n.h).
// Usage   : compiled into the GameKitShell module; call through GameKitI18n.h.
// Notes   : FString is UTF-16: '{', '}' and '%' never appear inside a surrogate pair, so scanning code units
//           is safe, and only the length count needs to skip the second half of a pair. The accented
//           look-alikes are written as code points so the result does not depend on the source encoding.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitI18n.h"

#include "GameKitJson.h"

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

	FString Tr(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, const FGameKitTrArgs& Args)
	{
		for (const FString& Loc : LocaleChain(Locale))
		{
			const FGameKitStringTable* Table = Tables.Find(Loc);
			if (!Table)
			{
				continue;
			}
			if (const FString* Text = Table->Find(Key))
			{
				return FillPlaceholders(*Text, Args);
			}
		}
		return Key;
	}

	FString Plural(const FString& Locale, int64 N)
	{
		const FString Base = BaseLanguage(Locale);
		auto IsLang = [&Base](const TCHAR* Lang) { return Base.Equals(Lang, ESearchCase::CaseSensitive); };
		if (IsLang(TEXT("ja")) || IsLang(TEXT("zh")) || IsLang(TEXT("ko")))
		{
			return TEXT("other");
		}
		if (IsLang(TEXT("fr")))
		{
			return N == 0 || N == 1 ? TEXT("one") : TEXT("other");
		}
		return N == 1 ? TEXT("one") : TEXT("other");
	}

	FString TrPlural(const FGameKitStringTables& Tables, const FString& Locale, const FString& Key, int64 N,
	                 const FGameKitTrArgs& Args)
	{
		FGameKitTrArgs A = Args;
		A.Add(TEXT("n"), FString::Printf(TEXT("%lld"), static_cast<long long>(N)));
		return Tr(Tables, Locale, Key + TEXT(".") + Plural(Locale, N), A);
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
