// ---------------------------------------------------------------------------
// GameKitBindings.cpp
// Purpose : Implementation of the action map, rebinding and button glyphs (see GameKitBindings.h).
// Usage   : compiled into the GameKitShell module; call through GameKitBindings.h.
// Notes   : Pad names follow the positional layout (south = A on Xbox, Cross on PlayStation), the same as
//           Unreal's Gamepad_FaceButton_Bottom. Add an action by adding it to the defaults below and to
//           docs/GDD.md's controls. String compares are case-sensitive, like the reference.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitBindings.h"

#include "GameKitJson.h"

namespace GameKit
{
	namespace
	{
		struct FNamePair
		{
			const TCHAR* From;
			const TCHAR* To;
		};

		struct FDefaultBinding
		{
			const TCHAR* Action;
			const TCHAR* Key;   // slot 0
			const TCHAR* Pad;   // slot 1
		};

		// ---- Tunables: the default controls ----
		const FDefaultBinding DefaultControls[] = {
			{TEXT("ui_up"), TEXT("key:up"), TEXT("pad:dpad_up")},
			{TEXT("ui_down"), TEXT("key:down"), TEXT("pad:dpad_down")},
			{TEXT("ui_left"), TEXT("key:left"), TEXT("pad:dpad_left")},
			{TEXT("ui_right"), TEXT("key:right"), TEXT("pad:dpad_right")},
			{TEXT("ui_accept"), TEXT("key:enter"), TEXT("pad:south")},
			{TEXT("ui_cancel"), TEXT("key:escape"), TEXT("pad:east")},
			{TEXT("move_left"), TEXT("key:a"), TEXT("pad:dpad_left")},
			{TEXT("move_right"), TEXT("key:d"), TEXT("pad:dpad_right")},
			{TEXT("move_up"), TEXT("key:w"), TEXT("pad:dpad_up")},
			{TEXT("move_down"), TEXT("key:s"), TEXT("pad:dpad_down")},
			{TEXT("jump"), TEXT("key:space"), TEXT("pad:south")},
			{TEXT("attack"), TEXT("key:j"), TEXT("pad:west")},
			{TEXT("interact"), TEXT("key:e"), TEXT("pad:north")},
			{TEXT("pause"), TEXT("key:escape"), TEXT("pad:start")},
		};

		// Pad button -> the name on the controller (prompt art files are named <prefix>_<name>)
		const FNamePair XboxNames[] = {
			{TEXT("south"), TEXT("a")}, {TEXT("east"), TEXT("b")}, {TEXT("west"), TEXT("x")}, {TEXT("north"), TEXT("y")},
			{TEXT("l1"), TEXT("lb")}, {TEXT("r1"), TEXT("rb")}, {TEXT("l2"), TEXT("lt")}, {TEXT("r2"), TEXT("rt")},
			{TEXT("start"), TEXT("menu")}, {TEXT("select"), TEXT("view")},
		};
		const FNamePair PlayStationNames[] = {
			{TEXT("south"), TEXT("cross")}, {TEXT("east"), TEXT("circle")}, {TEXT("west"), TEXT("square")},
			{TEXT("north"), TEXT("triangle")}, {TEXT("start"), TEXT("options")}, {TEXT("select"), TEXT("share")},
		};
		// Last device -> glyph set for "auto"
		const FNamePair DeviceSets[] = {
			{TEXT("keyboard"), TEXT("keyboard")}, {TEXT("mouse"), TEXT("keyboard")}, {TEXT("pad_xbox"), TEXT("xbox")},
			{TEXT("pad_playstation"), TEXT("playstation")},
		};

		template <int32 N>
		TOptional<FString> MapName(const FNamePair (&Table)[N], const FString& Name)
		{
			for (const FNamePair& Pair : Table)
			{
				if (Name.Equals(Pair.From, ESearchCase::CaseSensitive))
				{
					return FString(Pair.To);
				}
			}
			return {};
		}

		bool IsText(const FString& A, const TCHAR* B)
		{
			return A.Equals(B, ESearchCase::CaseSensitive);
		}
	}

	const FGameKitBindings& DefaultBindings()
	{
		// A function-local static, so code that runs during module start-up can call it safely
		static const FGameKitBindings Defaults = []
		{
			FGameKitBindings Out;
			for (const FDefaultBinding& Row : DefaultControls)
			{
				TArray<FString> Slots;
				Slots.Add(Row.Key);
				Slots.Add(Row.Pad);
				Out.Add(FString(Row.Action), MoveTemp(Slots));
			}
			return Out;
		}();
		return Defaults;
	}

	FString GroupOf(const FString& Action)
	{
		return Action.StartsWith(UiActionPrefix, ESearchCase::CaseSensitive) ? TEXT("ui") : TEXT("game");
	}

	TArray<FString> SortedActions(const FGameKitBindings& Bindings)
	{
		TArray<FString> Actions;
		Bindings.GetKeys(Actions);
		Actions.Sort([](const FString& A, const FString& B) { return A.Compare(B, ESearchCase::CaseSensitive) < 0; });
		return Actions;
	}

	TOptional<FGameKitRebindResult> Rebind(const FGameKitBindings& Bindings, const FString& Action, int32 Slot,
	                                       const FString& Binding)
	{
		FGameKitRebindResult R;
		R.Bindings = Bindings;
		R.Bindings.FindOrAdd(Action);   // a new action starts with no slots
		const TArray<FString>& Current = R.Bindings.FindChecked(Action);
		if (Slot < 0 || Slot > Current.Num())
		{
			return {};
		}
		const FString Old = Slot < Current.Num() ? Current[Slot] : FString();
		const FString Group = GroupOf(Action);
		if (!Binding.IsEmpty())
		{
			for (const FString& Other : SortedActions(R.Bindings))   // sorted by action, then slot
			{
				if (GroupOf(Other) != Group)
				{
					continue;
				}
				const TArray<FString>& Names = R.Bindings.FindChecked(Other);
				for (int32 S = 0; S < Names.Num(); ++S)
				{
					const bool bSameSlot = Other.Equals(Action, ESearchCase::CaseSensitive) && S == Slot;
					if (!bSameSlot && Names[S].Equals(Binding, ESearchCase::CaseSensitive))
					{
						R.Conflicts.Emplace(Other, S);
					}
				}
			}
		}
		TArray<FString>& List = R.Bindings.FindChecked(Action);
		if (Slot == List.Num())
		{
			List.Add(Binding);
		}
		else
		{
			List[Slot] = Binding;
		}
		for (const TPair<FString, int32>& Conflict : R.Conflicts)
		{
			R.Bindings.FindChecked(Conflict.Key)[Conflict.Value] = Old;   // the swap: the other action takes the old binding
		}
		return R;
	}

	FString GlyphSet(const FString& Setting, const FString& LastDevice)
	{
		if (!IsText(Setting, TEXT("auto")))
		{
			return Setting;
		}
		return MapName(DeviceSets, LastDevice).Get(TEXT("generic"));   // an unknown pad: generic pad art
	}

	FString GlyphName(const FString& Set, const FString& Binding)
	{
		int32 Colon = INDEX_NONE;
		Binding.FindChar(TEXT(':'), Colon);
		const FString Kind = Colon == INDEX_NONE ? Binding : Binding.Left(Colon);
		FString Name = Colon == INDEX_NONE ? FString() : Binding.Mid(Colon + 1);
		if (IsText(Kind, TEXT("key")))
		{
			return TEXT("key_") + Name;
		}
		if (IsText(Kind, TEXT("mouse")))
		{
			return TEXT("mouse_") + Name;
		}
		if (IsText(Kind, TEXT("pad_axis")))
		{
			Name = Name.StartsWith(TEXT("left"), ESearchCase::CaseSensitive) ? TEXT("lstick") : TEXT("rstick");
		}
		else if (!IsText(Kind, TEXT("pad")))
		{
			return TEXT("unknown");
		}
		if (IsText(Set, TEXT("xbox")))
		{
			return TEXT("xbox_") + MapName(XboxNames, Name).Get(Name);
		}
		if (IsText(Set, TEXT("playstation")))
		{
			return TEXT("ps_") + MapName(PlayStationNames, Name).Get(Name);
		}
		return TEXT("pad_") + Name;
	}

	FString PromptBinding(const FGameKitBindings& Bindings, const FString& Action, const FString& Set)
	{
		const TArray<FString>* List = Bindings.Find(Action);
		const int32 Slot = IsText(Set, TEXT("keyboard")) ? KeyboardSlot : PadSlot;
		return List && Slot < List->Num() ? (*List)[Slot] : FString();
	}

	FGameKitBindings BindingsFromJson(const TSharedPtr<FJsonObject>& Object)
	{
		FGameKitBindings Out;
		if (!Object.IsValid())
		{
			return Out;
		}
		for (const auto& Pair : Object->Values)
		{
			if (!Json::Is(Pair.Value, EJson::Array))
			{
				continue;
			}
			TArray<FString>& Names = Out.Add(FString(*Pair.Key));
			for (const TSharedPtr<FJsonValue>& Item : Pair.Value->AsArray())
			{
				if (Json::Is(Item, EJson::String))
				{
					Names.Add(Item->AsString());
				}
			}
		}
		return Out;
	}

	static FString OneLine(const FString& Text)
	{
		TArray<FString> Words;
		Text.ParseIntoArrayWS(Words);
		return FString::Join(Words, TEXT(" "));
	}

	FString NarrationLine(const FString& Label, const FString& Role, const FString& Value)
	{
		TArray<FString> Parts;
		Parts.Add(OneLine(Label).IsEmpty() ? FString(TEXT("unlabelled")) : OneLine(Label));
		if (!OneLine(Role).IsEmpty()) { Parts.Add(OneLine(Role)); }
		if (!OneLine(Value).IsEmpty()) { Parts.Add(OneLine(Value)); }
		return FString::Join(Parts, TEXT(", "));
	}

	TSharedRef<FJsonObject> BindingsToJson(const FGameKitBindings& Bindings)
	{
		TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
		for (const TPair<FString, TArray<FString>>& Pair : Bindings)
		{
			Out->SetField(Pair.Key, Json::MakeStringArray(Pair.Value));
		}
		return Out;
	}
}

// {{FOOTER}}
