// ---------------------------------------------------------------------------
// GameKitJson.cpp
// Purpose : Implementation of the JSON helpers (see GameKitJson.h).
// Usage   : compiled into the GameKitShell module; call through GameKitJson.h.
// Notes   : Parsing is the engine's FJsonSerializer. Writing is done here, character by character, because
//           the engine writer's number format is fixed at %.17g. Nothing here logs.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitJson.h"

#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace GameKit::Json
{
	namespace
	{
		bool CaseSensitiveLess(const FString& A, const FString& B)
		{
			return A.Compare(B, ESearchCase::CaseSensitive) < 0;
		}

		void WriteString(FString& Out, const FString& Text)
		{
			Out.AppendChar(TEXT('"'));
			for (const TCHAR C : Text)
			{
				switch (C)
				{
				case TEXT('"'):  Out.Append(TEXT("\\\"")); break;
				case TEXT('\\'): Out.Append(TEXT("\\\\")); break;
				case TEXT('\n'): Out.Append(TEXT("\\n")); break;
				case TEXT('\r'): Out.Append(TEXT("\\r")); break;
				case TEXT('\t'): Out.Append(TEXT("\\t")); break;
				case TEXT('\b'): Out.Append(TEXT("\\b")); break;
				case TEXT('\f'): Out.Append(TEXT("\\f")); break;
				default:
					if (static_cast<uint32>(C) < 0x20)
					{
						Out.Appendf(TEXT("\\u%04x"), static_cast<uint32>(C));   // other control characters
					}
					else
					{
						Out.AppendChar(C);
					}
				}
			}
			Out.AppendChar(TEXT('"'));
		}

		void NewLine(FString& Out, int32 Indent, int32 Depth)
		{
			if (Indent > 0)
			{
				Out.AppendChar(TEXT('\n'));
				Out.Append(FString::ChrN(Indent * Depth, TEXT(' ')));
			}
		}

		void WriteValue(FString& Out, const TSharedPtr<FJsonValue>& Value, int32 Indent, int32 Depth)
		{
			if (!Value.IsValid())
			{
				Out.Append(TEXT("null"));
				return;
			}
			switch (Value->Type)
			{
			case EJson::Boolean:
				Out.Append(Value->AsBool() ? TEXT("true") : TEXT("false"));
				return;
			case EJson::Number:
				Out.Append(FormatNumber(Value->AsNumber()));
				return;
			case EJson::String:
				WriteString(Out, Value->AsString());
				return;
			case EJson::Array:
			{
				const TArray<TSharedPtr<FJsonValue>>& Items = Value->AsArray();
				if (Items.IsEmpty())
				{
					Out.Append(TEXT("[]"));
					return;
				}
				Out.AppendChar(TEXT('['));
				for (int32 I = 0; I < Items.Num(); ++I)
				{
					if (I > 0)
					{
						Out.AppendChar(TEXT(','));
					}
					NewLine(Out, Indent, Depth + 1);
					WriteValue(Out, Items[I], Indent, Depth + 1);
				}
				NewLine(Out, Indent, Depth);
				Out.AppendChar(TEXT(']'));
				return;
			}
			case EJson::Object:
			{
				const TSharedPtr<FJsonObject>& Obj = Value->AsObject();
				if (!Obj.IsValid() || Obj->Values.IsEmpty())
				{
					Out.Append(TEXT("{}"));
					return;
				}
				Out.AppendChar(TEXT('{'));
				bool bFirst = true;
				for (const FString& Key : SortedKeys(*Obj))
				{
					if (!bFirst)
					{
						Out.AppendChar(TEXT(','));
					}
					bFirst = false;
					NewLine(Out, Indent, Depth + 1);
					WriteString(Out, Key);
					Out.Append(Indent > 0 ? TEXT(": ") : TEXT(":"));
					WriteValue(Out, Obj->TryGetField(Key), Indent, Depth + 1);
				}
				NewLine(Out, Indent, Depth);
				Out.AppendChar(TEXT('}'));
				return;
			}
			default:   // EJson::Null and EJson::None
				Out.Append(TEXT("null"));
			}
		}

		FString Show(const TSharedPtr<FJsonValue>& Value)
		{
			return Write(Value, 0);
		}
	}

	TSharedPtr<FJsonValue> Parse(const FString& Text)
	{
		TSharedPtr<FJsonValue> Out;
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Out) || !Out.IsValid())
		{
			return nullptr;
		}
		return Out;
	}

	TSharedPtr<FJsonValue> Clone(const TSharedPtr<FJsonValue>& Value)
	{
		if (!Value.IsValid())
		{
			return MakeNull();
		}
		switch (Value->Type)
		{
		case EJson::Boolean: return MakeBool(Value->AsBool());
		case EJson::Number:  return MakeNumber(Value->AsNumber());
		case EJson::String:  return MakeString(Value->AsString());
		case EJson::Array:
		{
			TArray<TSharedPtr<FJsonValue>> Items;
			for (const TSharedPtr<FJsonValue>& Item : Value->AsArray())
			{
				Items.Add(Clone(Item));
			}
			return MakeArray(Items);
		}
		case EJson::Object:  return MakeObject(CloneObject(Value->AsObject()));
		default:             return MakeNull();
		}
	}

	TSharedRef<FJsonObject> CloneObject(const TSharedPtr<FJsonObject>& Object)
	{
		TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		if (Object.IsValid())
		{
			for (const auto& Pair : Object->Values)
			{
				Out->SetField(FString(*Pair.Key), Clone(Pair.Value));
			}
		}
		return Out;
	}

	FString Write(const TSharedPtr<FJsonValue>& Value, int32 Indent)
	{
		FString Out;
		WriteValue(Out, Value, FMath::Max(Indent, 0), 0);
		return Out;
	}

	FString Write(const TSharedRef<FJsonObject>& Object, int32 Indent)
	{
		return Write(MakeObject(Object), Indent);
	}

	FString FormatNumber(double Value)
	{
		if (!FMath::IsFinite(Value))
		{
			return TEXT("null");   // JSON has no NaN or infinity
		}
		// 15 significant digits are enough for most doubles; 17 always read back exactly
		FString Text = FString::Printf(TEXT("%.15g"), Value);
		if (FCString::Atod(*Text) != Value)
		{
			Text = FString::Printf(TEXT("%.16g"), Value);
		}
		if (FCString::Atod(*Text) != Value)
		{
			Text = FString::Printf(TEXT("%.17g"), Value);
		}
		return Text;
	}

	TArray<FString> SortedKeys(const FJsonObject& Object)
	{
		TArray<FString> Keys;
		for (const auto& Pair : Object.Values)
		{
			Keys.Add(FString(*Pair.Key));
		}
		Keys.Sort(CaseSensitiveLess);
		return Keys;
	}

	FString Diff(const TSharedPtr<FJsonValue>& Got, const TSharedPtr<FJsonValue>& Want, double Tolerance, const FString& At)
	{
		const EJson GotType = Got.IsValid() ? Got->Type : EJson::Null;
		const EJson WantType = Want.IsValid() ? Want->Type : EJson::Null;
		if (GotType == EJson::Number && WantType == EJson::Number)
		{
			const double G = Got->AsNumber();
			const double W = Want->AsNumber();
			return FMath::Abs(G - W) <= Tolerance ? FString()
			                                      : FString::Printf(TEXT("%s: got %s, want %s"), *At, *Show(Got), *Show(Want));
		}
		if (GotType != WantType)
		{
			return FString::Printf(TEXT("%s: got %s, want %s"), *At, *Show(Got), *Show(Want));
		}
		if (WantType == EJson::Array)
		{
			const TArray<TSharedPtr<FJsonValue>>& G = Got->AsArray();
			const TArray<TSharedPtr<FJsonValue>>& W = Want->AsArray();
			if (G.Num() != W.Num())
			{
				return FString::Printf(TEXT("%s: %d items, want %d (got %s)"), *At, G.Num(), W.Num(), *Show(Got));
			}
			for (int32 I = 0; I < W.Num(); ++I)
			{
				const FString D = Diff(G[I], W[I], Tolerance, FString::Printf(TEXT("%s[%d]"), *At, I));
				if (!D.IsEmpty())
				{
					return D;
				}
			}
			return FString();
		}
		if (WantType == EJson::Object)
		{
			const TSharedPtr<FJsonObject>& G = Got->AsObject();
			const TSharedPtr<FJsonObject>& W = Want->AsObject();
			for (const FString& Key : SortedKeys(*G))
			{
				if (!W->HasField(Key))
				{
					return FString::Printf(TEXT("%s.%s: not expected"), *At, *Key);
				}
			}
			for (const FString& Key : SortedKeys(*W))
			{
				if (!G->HasField(Key))
				{
					return FString::Printf(TEXT("%s.%s: missing"), *At, *Key);
				}
				const FString D = Diff(G->TryGetField(Key), W->TryGetField(Key), Tolerance, At + TEXT(".") + Key);
				if (!D.IsEmpty())
				{
					return D;
				}
			}
			return FString();
		}
		if (WantType == EJson::String)
		{
			return Got->AsString().Equals(Want->AsString(), ESearchCase::CaseSensitive)
			           ? FString()
			           : FString::Printf(TEXT("%s: got %s, want %s"), *At, *Show(Got), *Show(Want));
		}
		if (WantType == EJson::Boolean)
		{
			return Got->AsBool() == Want->AsBool() ? FString()
			                                       : FString::Printf(TEXT("%s: got %s, want %s"), *At, *Show(Got), *Show(Want));
		}
		return FString();   // both null
	}

	TSharedPtr<FJsonValue> Find(const TSharedPtr<FJsonObject>& Object, const FString& Key)
	{
		return Object.IsValid() ? Object->TryGetField(Key) : nullptr;
	}

	TSharedPtr<FJsonObject> FindObject(const TSharedPtr<FJsonObject>& Object, const FString& Key)
	{
		const TSharedPtr<FJsonValue> V = Find(Object, Key);
		return Is(V, EJson::Object) ? V->AsObject() : nullptr;
	}

	double GetNumber(const TSharedPtr<FJsonObject>& Object, const FString& Key, double Fallback)
	{
		const TSharedPtr<FJsonValue> V = Find(Object, Key);
		return Is(V, EJson::Number) ? V->AsNumber() : Fallback;
	}

	bool GetBool(const TSharedPtr<FJsonObject>& Object, const FString& Key, bool bFallback)
	{
		const TSharedPtr<FJsonValue> V = Find(Object, Key);
		return Is(V, EJson::Boolean) ? V->AsBool() : bFallback;
	}

	FString GetString(const TSharedPtr<FJsonObject>& Object, const FString& Key, const FString& Fallback)
	{
		const TSharedPtr<FJsonValue> V = Find(Object, Key);
		return Is(V, EJson::String) ? V->AsString() : Fallback;
	}

	TSharedPtr<FJsonValue> MakeStringArray(const TArray<FString>& Items)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		for (const FString& Item : Items)
		{
			Values.Add(MakeString(Item));
		}
		return MakeArray(Values);
	}
}

// {{FOOTER}}
