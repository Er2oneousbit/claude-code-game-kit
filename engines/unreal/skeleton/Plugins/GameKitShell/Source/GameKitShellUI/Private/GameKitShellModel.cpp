// ---------------------------------------------------------------------------
// GameKitShellModel.cpp
// Purpose : Implementation of the headless screen model (see GameKitShellModel.h): the screens, their rows,
//           the input rules, settings rows per tab, subtitles, history and narration.
// Usage   : compiled into the GameKitShellUI module; call through GameKitShellModel.h.
// Notes   : Rows read and write the settings object directly through small closures, so a row's label and
//           value are always what the settings hold now (no copies to keep in step). The settings rows
//           follow the LÖVE shell's settings.lua one for one (same tabs, same order, same steps), so the
//           golden settings schema (GameKitSettings.cpp) is what the menu offers.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellModel.h"

#include "GameKitAtomicFile.h"
#include "GameKitJson.h"
#include "GameKitSettings.h"
#include "GameKitShellLog.h"
#include "HAL/FileManager.h"
#include "Misc/Paths.h"

const TCHAR* const FGameKitShellModel::SettingsFile = TEXT("settings.json");
const TCHAR* const FGameKitShellModel::PresetsFile = TEXT("data/input/presets.json");
const TCHAR* const FGameKitShellModel::ColoursFile = TEXT("data/access/colours.json");
const TCHAR* const FGameKitShellModel::I18nDir = TEXT("data/i18n");
const TCHAR* const FGameKitShellModel::CreditsFile = TEXT("CREDITS.md");
const TCHAR* FGameKitShellModel::SettingsTabs[5] = {TEXT("display"), TEXT("audio"), TEXT("controls"), TEXT("access"), TEXT("language")};
const TCHAR* FGameKitShellModel::GameActions[8] = {TEXT("move_left"), TEXT("move_right"), TEXT("move_up"), TEXT("move_down"),
                                                   TEXT("jump"), TEXT("attack"), TEXT("interact"), TEXT("pause")};
const TCHAR* FGameKitShellModel::PresetNames[2] = {TEXT("one_hand_left"), TEXT("one_hand_right")};
const TCHAR* FGameKitShellModel::HelpActions[6] = {TEXT("move_left"), TEXT("move_right"), TEXT("jump"), TEXT("attack"),
                                                   TEXT("interact"), TEXT("pause")};

namespace
{
	using namespace GameKit::Json;

	// ---- Tunables ----
	const int32 Resolutions[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}, {3840, 2160}};
	constexpr double SliderEps = 1e-9;

	/** Placeholder arguments for Tr: one or two {name} -> value pairs. */
	FGameKitTrArgs Args(const TCHAR* K1, const FString& V1, const TCHAR* K2 = nullptr, const FString& V2 = FString())
	{
		FGameKitTrArgs M;
		M.Add(K1, V1);
		if (K2)
		{
			M.Add(K2, V2);
		}
		return M;
	}

	/** Snaps V to the step grid inside [Lo, Hi] (0.1 steps on a float stay 0.1, not 0.1000000001). */
	double Snap(double V, double Lo, double Hi, double Step)
	{
		const double Snapped = FMath::RoundToDouble((V - Lo) / Step) * Step + Lo;
		return FMath::Clamp(FMath::RoundToDouble(Snapped * 1e6) / 1e6, Lo, Hi);
	}

	TArray<FString> StringArray(const TCHAR* const* Values, int32 Count)
	{
		TArray<FString> Out;
		for (int32 I = 0; I < Count; ++I)
		{
			Out.Add(Values[I]);
		}
		return Out;
	}

	/** (action, slot) pairs whose binding another action of the same group also holds. */
	TSet<FString> ConflictCells(const FGameKitBindings& B)
	{
		TMap<FString, FString> Seen;   // "<group>|<binding>" -> "<action>#<slot>"
		TSet<FString> Out;
		for (const FString& Action : GameKit::SortedActions(B))
		{
			const TArray<FString>& Slots = B[Action];
			for (int32 Slot = 0; Slot < Slots.Num(); ++Slot)
			{
				if (Slots[Slot].IsEmpty())
				{
					continue;
				}
				const FString Key = GameKit::GroupOf(Action) + TEXT("|") + Slots[Slot];
				const FString Cell = FString::Printf(TEXT("%s#%d"), *Action, Slot);
				if (const FString* First = Seen.Find(Key))
				{
					Out.Add(*First);
					Out.Add(Cell);
				}
				else
				{
					Seen.Add(Key, Cell);
				}
			}
		}
		return Out;
	}
}

// ---- Screen helpers --------------------------------------------------------------------------------------------
const FGameKitRow* FGameKitScreen::Focused() const
{
	if (Dialog.Num())
	{
		return Dialog.IsValidIndex(DialogFocus) ? &Dialog[DialogFocus] : nullptr;
	}
	if (bOnTabs)
	{
		return nullptr;
	}
	return Rows.IsValidIndex(Focus) ? &Rows[Focus] : nullptr;
}

FString FGameKitScreen::FocusId() const
{
	if (Name == TEXT("title"))
	{
		return Dialog.Num() ? TEXT("consent.") + (Dialog.IsValidIndex(DialogFocus) ? Dialog[DialogFocus].Id : FString()) : TEXT("title");
	}
	if (Name == TEXT("settings"))
	{
		if (bOnTabs)
		{
			return TEXT("tabs.") + Tab();
		}
		return Tab() + TEXT(".") + (Rows.IsValidIndex(Focus) ? Rows[Focus].Id : FString());
	}
	return Rows.IsValidIndex(Focus) ? Rows[Focus].Id : Name;
}

// ---- Construction ------------------------------------------------------------------------------------------------
FGameKitShellModel::FGameKitShellModel(const FOptions& InOptions)
	: Settings(MakeShared<FJsonObject>())
	, Opt(InOptions)
{
	const FGameKitSettingsLoad Loaded = GameKit::SettingsLoadFile(SettingsPath());
	Settings = Loaded.Settings;
	SettingsProblems = Loaded.Problems;
	for (const FString& P : SettingsProblems)
	{
		UE_LOG(LogGameKitShell, Warning, TEXT("settings: fixed %s"), *P);
	}
	LoadTables();
	const TOptional<FString> ColourText = GameKit::ReadTextFile(FPaths::Combine(Opt.ProjectDir, ColoursFile));
	if (ColourText.IsSet())
	{
		const TSharedPtr<FJsonValue> Root = Parse(ColourText.GetValue());
		if (Is(Root, EJson::Object) && Is(Find(Root->AsObject(), TEXT("palettes")), EJson::Object))
		{
			Colours = Root->AsObject();
		}
		else
		{
			UE_LOG(LogGameKitShell, Warning, TEXT("%s is not a colour data file (palettes missing)"), ColoursFile);
		}
	}
}

void FGameKitShellModel::LoadTables()
{
	TArray<FString> Files;
	const FString Dir = FPaths::Combine(Opt.ProjectDir, I18nDir);
	IFileManager::Get().FindFiles(Files, *FPaths::Combine(Dir, TEXT("*.json")), /*Files*/ true, /*Directories*/ false);
	for (const FString& File : Files)
	{
		const TOptional<FString> Text = GameKit::ReadTextFile(FPaths::Combine(Dir, File));
		const TSharedPtr<FJsonValue> Root = Text.IsSet() ? Parse(Text.GetValue()) : nullptr;
		if (!Is(Root, EJson::Object))
		{
			UE_LOG(LogGameKitShell, Error, TEXT("i18n: %s is not a JSON object"), *File);
			continue;
		}
		FGameKitStringTable Table;
		for (const auto& Pair : Root->AsObject()->Values)
		{
			if (Is(Pair.Value, EJson::String))
			{
				Table.Add(Pair.Key, Pair.Value->AsString());
			}
		}
		Tables.Add(FPaths::GetBaseFilename(File), MoveTemp(Table));
	}
}

// ---- Settings ----------------------------------------------------------------------------------------------------
FString FGameKitShellModel::SettingsPath() const
{
	return FPaths::Combine(Opt.DataDir, SettingsFile);
}

double FGameKitShellModel::Num(const TCHAR* Section, const TCHAR* Field) const
{
	return GameKit::SettingNumber(*Settings, Section, Field);
}

bool FGameKitShellModel::Flag(const TCHAR* Section, const TCHAR* Field) const
{
	return GameKit::SettingBool(*Settings, Section, Field);
}

FString FGameKitShellModel::Str(const TCHAR* Section, const TCHAR* Field) const
{
	return GameKit::SettingString(*Settings, Section, Field);
}

void FGameKitShellModel::SetNum(const TCHAR* Section, const TCHAR* Field, double Value)
{
	Settings->GetObjectField(Section)->SetNumberField(Field, Value);
	Changed();
}

void FGameKitShellModel::SetFlag(const TCHAR* Section, const TCHAR* Field, bool bValue)
{
	Settings->GetObjectField(Section)->SetBoolField(Field, bValue);
	Changed();
}

void FGameKitShellModel::SetStr(const TCHAR* Section, const TCHAR* Field, const FString& Value)
{
	if (FCString::Strcmp(Section, TEXT("language")) == 0)
	{
		Settings->SetStringField(TEXT("language"), Value);   // the one top-level string
	}
	else
	{
		Settings->GetObjectField(Section)->SetStringField(Field, Value);
	}
	Changed();
}

FGameKitBindings FGameKitShellModel::Bindings() const
{
	return GameKit::BindingsFromJson(FindObject(FindObject(Settings, TEXT("input")), TEXT("bindings")));
}

void FGameKitShellModel::SetBindings(const FGameKitBindings& NewBindings)
{
	Settings->GetObjectField(TEXT("input"))->SetObjectField(TEXT("bindings"), GameKit::BindingsToJson(NewBindings));
	Changed();
}

FString FGameKitShellModel::SaveSettings()
{
	FString Error;
	const FString Path = SettingsPath();
	if (!GameKit::SettingsSaveFile(Path, Settings, &Error))
	{
		UE_LOG(LogGameKitShell, Error, TEXT("settings not saved: %s"), *Error);
		return FString();
	}
	UE_LOG(LogGameKitShell, Log, TEXT("settings saved %s"), *Path);
	return Path;
}

void FGameKitShellModel::Changed()
{
	++Version;
	Event(TEXT("settings_changed"));
}

double FGameKitShellModel::TextScale() const
{
	return Num(TEXT("access"), TEXT("text_scale")) * Num(TEXT("display"), TEXT("ui_scale"));
}

// ---- Text --------------------------------------------------------------------------------------------------------
FString FGameKitShellModel::Locale() const
{
	return Opt.Locale.IsEmpty() ? GameKit::SettingLanguage(*Settings) : Opt.Locale;
}

FString FGameKitShellModel::T(const FString& Key, const FGameKitTrArgs& Args) const
{
	return GameKit::Tr(Tables, Locale(), Key, Args);
}

FString FGameKitShellModel::Content(const FString& Text) const
{
	return T(TEXT("value.raw"), Args(TEXT("v"), Text));
}

FString FGameKitShellModel::Percent(double V) const
{
	return T(TEXT("value.percent"), Args(TEXT("n"), FString::FromInt(FMath::RoundToInt(V * 100.0))));
}

FString FGameKitShellModel::Times(double V) const
{
	return T(TEXT("value.times"), Args(TEXT("n"), FormatNumber(V)));
}

FString FGameKitShellModel::BindingLabel(const FString& GlyphName) const
{
	if (GlyphName == TEXT("unknown"))
	{
		return T(TEXT("controls.unbound"));
	}
	const FString Key = TEXT("glyph.") + GlyphName;
	const FString Found = T(Key);
	if (Found != Key)
	{
		return Found;
	}
	int32 Under = INDEX_NONE;
	FString Name = GlyphName.FindChar(TEXT('_'), Under) ? GlyphName.Mid(Under + 1) : GlyphName;
	Name.ReplaceInline(TEXT("_"), TEXT(" "));
	return Content(Name.Left(1).ToUpper() + Name.Mid(1));
}

FString FGameKitShellModel::GlyphSet() const
{
	return GameKit::GlyphSet(Str(TEXT("input"), TEXT("glyphs")), LastDevice);
}

void FGameKitShellModel::Prompt(const FString& Action, FString& OutGlyph, FString& OutLabel) const
{
	const FString Set = GlyphSet();
	const FString Binding = GameKit::PromptBinding(Bindings(), Action, Set);
	OutGlyph = Binding.IsEmpty() ? TEXT("unknown") : GameKit::GlyphName(Set, Binding);
	OutLabel = BindingLabel(OutGlyph);
}

TArray<FString> FGameKitShellModel::Locales() const
{
	TArray<FString> Out;
	Tables.GetKeys(Out);
	Out.Sort();
	if (Out.IsEmpty())
	{
		Out.Add(GameKit::FallbackLocale);
	}
	return Out;
}

// ---- Screens -----------------------------------------------------------------------------------------------------
FString FGameKitShellModel::Heading(const FGameKitScreen& Screen) const
{
	return Screen.HeadingKey.IsEmpty() ? T(TEXT("title.name"), Args(TEXT("name"), Opt.GameName)) : T(Screen.HeadingKey);
}

void FGameKitShellModel::Push(const FString& Name)
{
	Stack.Add(Build(Name));
	++Version;
	UE_LOG(LogGameKitShell, Log, TEXT("screen %s"), *Name);
	NarrateScreen(Stack.Last());
}

void FGameKitShellModel::Pop()
{
	if (Stack.Num())
	{
		Stack.Pop();
		++Version;
		if (Stack.Num())
		{
			NarrateScreen(Stack.Last());
		}
	}
}

void FGameKitShellModel::Replace(const FString& Name)
{
	if (Stack.Num())
	{
		Stack.Pop();
	}
	Push(Name);
}

void FGameKitShellModel::Reset(const FString& Name)
{
	Stack.Empty();
	Push(Name);
}

FGameKitRow FGameKitShellModel::ButtonRow(const FString& Id, const FString& LabelKey, TFunction<void()> Accept)
{
	FGameKitRow Row;
	Row.Id = Id;
	Row.Kind = EGameKitRowKind::Button;
	Row.Label = [this, LabelKey] { return T(LabelKey); };
	Row.Value = [] { return FString(); };
	Row.Accept = MoveTemp(Accept);
	return Row;
}

FGameKitRow FGameKitShellModel::BackRow()
{
	return ButtonRow(TEXT("back"), TEXT("settings.back"), [this]
	{
		SaveSettings();
		Pop();
	});
}

FGameKitRow FGameKitShellModel::Field(const TCHAR* Section, const TCHAR* FieldName, EGameKitRowKind Kind, double Lo, double Hi,
                                      double Step, const TArray<FString>& Choices, bool bTimes)
{
	FGameKitRow Row;
	Row.Id = FieldName;
	Row.Kind = Kind;
	const FString S = Section, F = FieldName;
	Row.Label = [this, S, F] { return T(FString::Printf(TEXT("settings.%s.%s"), *S, *F)); };
	switch (Kind)
	{
	case EGameKitRowKind::Toggle:
		Row.Value = [this, S, F] { return T(Flag(*S, *F) ? TEXT("value.on") : TEXT("value.off")); };
		Row.Step = [this, S, F](int32) { SetFlag(*S, *F, !Flag(*S, *F)); };
		Row.Accept = [this, S, F] { SetFlag(*S, *F, !Flag(*S, *F)); };
		break;
	case EGameKitRowKind::Slider:
		Row.Value = [this, S, F, bTimes] { return bTimes ? Times(Num(*S, *F)) : Percent(Num(*S, *F)); };
		Row.Step = [this, S, F, Lo, Hi, Step](int32 Dir) { SetNum(*S, *F, Snap(Num(*S, *F) + Dir * Step, Lo, Hi, Step)); };
		break;
	case EGameKitRowKind::Choice:
	{
		Row.Value = [this, S, F, Choices] { return T(FString::Printf(TEXT("opt.%s.%s"), *F, *Str(*S, *F))); };
		auto Cycle = [this, S, F, Choices](int32 Dir)
		{
			int32 Index = Choices.IndexOfByKey(Str(*S, *F));
			Index = Index == INDEX_NONE ? 0 : (Index + Dir + Choices.Num()) % Choices.Num();
			SetStr(*S, *F, Choices[Index]);
		};
		Row.Step = Cycle;
		Row.Accept = [Cycle] { Cycle(1); };
		break;
	}
	default:
		break;
	}
	return Row;
}

FGameKitRow FGameKitShellModel::BindingRow(const FString& Action)
{
	FGameKitRow Row;
	Row.Id = TEXT("bind_") + Action;
	Row.Kind = EGameKitRowKind::Binding;
	Row.Label = [this, Action] { return T(TEXT("action.") + Action); };
	Row.CellText = [this, Action](int32 Slot)
	{
		const FGameKitBindings B = Bindings();
		const TArray<FString>* Slots = B.Find(Action);
		const FString Binding = Slots && Slots->IsValidIndex(Slot) ? (*Slots)[Slot] : FString();
		if (Binding.IsEmpty())
		{
			return T(TEXT("controls.unbound"));
		}
		FString Set = Slot == 0 ? TEXT("keyboard") : GlyphSet();
		if (Slot == 1 && Set == TEXT("keyboard"))
		{
			Set = TEXT("generic");   // the keyboard set makes no sense for the pad column
		}
		return BindingLabel(GameKit::GlyphName(Set, Binding));
	};
	Row.CellWarn = [this, Action](int32 Slot) { return ConflictCells(Bindings()).Contains(FString::Printf(TEXT("%s#%d"), *Action, Slot)); };
	Row.Value = [CellText = Row.CellText] { return CellText(0) + TEXT(" | ") + CellText(1); };
	Row.Step = [this, Action](int32 Dir)
	{
		if (FGameKitScreen* Screen = Top())
		{
			for (FGameKitRow& R : Screen->Rows)
			{
				if (R.Id == TEXT("bind_") + Action)
				{
					R.Cell = FMath::Clamp(R.Cell + Dir, 0, 1);
					++Version;
				}
			}
		}
	};
	Row.Accept = [this, Action]
	{
		int32 Cell = 0;
		if (const FGameKitScreen* Screen = Top())
		{
			for (const FGameKitRow& R : Screen->Rows)
			{
				if (R.Id == TEXT("bind_") + Action)
				{
					Cell = R.Cell;
				}
			}
		}
		CaptureAction = Action;
		CaptureSlotIndex = Cell;
		++Version;
	};
	return Row;
}

void FGameKitShellModel::ApplyPreset(const FString& Preset)
{
	const TOptional<FString> Text = GameKit::ReadTextFile(FPaths::Combine(Opt.ProjectDir, PresetsFile));
	const TSharedPtr<FJsonValue> Root = Text.IsSet() ? Parse(Text.GetValue()) : nullptr;
	const TSharedPtr<FJsonObject> Chosen = Is(Root, EJson::Object) ? FindObject(FindObject(Root->AsObject(), TEXT("presets")), Preset) : nullptr;
	const TSharedPtr<FJsonObject> Map = FindObject(Chosen, TEXT("bindings"));
	if (!Map.IsValid())
	{
		UE_LOG(LogGameKitShell, Warning, TEXT("%s has no preset %s"), PresetsFile, *Preset);
		return;
	}
	FGameKitBindings B = GameKit::DefaultBindings();
	for (const auto& Pair : Map->Values)
	{
		if (!Is(Pair.Value, EJson::Array))
		{
			continue;
		}
		TArray<FString> Slots;
		for (const TSharedPtr<FJsonValue>& V : Pair.Value->AsArray())
		{
			Slots.Add(Is(V, EJson::String) ? V->AsString() : FString());
		}
		B.Add(Pair.Key, Slots);
	}
	SetBindings(B);
	Message = T(TEXT("controls.preset_done"));
	MessageT = MessageS;
}

void FGameKitShellModel::BuildTab(FGameKitScreen& Screen)
{
	Screen.Rows.Empty();
	Screen.Focus = 0;
	const FString Tab = Screen.Tab();
	TArray<FGameKitRow>& Rows = Screen.Rows;
	if (Tab == TEXT("display"))
	{
		Rows.Add(Field(TEXT("display"), TEXT("mode"), EGameKitRowKind::Choice, 0, 0, 0, StringArray(GameKit::DisplayModes, UE_ARRAY_COUNT(GameKit::DisplayModes))));
		Rows.Add(Field(TEXT("display"), TEXT("vsync"), EGameKitRowKind::Toggle));
		FGameKitRow Cap;
		Cap.Id = TEXT("frame_cap");
		Cap.Kind = EGameKitRowKind::Choice;
		Cap.Label = [this] { return T(TEXT("settings.display.frame_cap")); };
		Cap.Value = [this]
		{
			const int32 V = FMath::RoundToInt(Num(TEXT("display"), TEXT("frame_cap")));
			return V == 0 ? T(TEXT("opt.frame_cap.0")) : T(TEXT("value.fps"), Args(TEXT("n"), FString::FromInt(V)));
		};
		auto CycleCap = [this](int32 Dir)
		{
			const int32 N = UE_ARRAY_COUNT(GameKit::FrameCaps);
			int32 Index = 0;
			for (int32 I = 0; I < N; ++I)
			{
				if (GameKit::FrameCaps[I] == FMath::RoundToInt(Num(TEXT("display"), TEXT("frame_cap"))))
				{
					Index = I;
				}
			}
			SetNum(TEXT("display"), TEXT("frame_cap"), GameKit::FrameCaps[(Index + Dir + N) % N]);
		};
		Cap.Step = CycleCap;
		Cap.Accept = [CycleCap] { CycleCap(1); };
		Rows.Add(Cap);
		FGameKitRow Res;
		Res.Id = TEXT("resolution");
		Res.Kind = EGameKitRowKind::Choice;
		Res.Label = [this] { return T(TEXT("settings.display.resolution")); };
		Res.Value = [this]
		{
			const FIntPoint R = GameKit::SettingResolution(*Settings);
			return T(TEXT("value.resolution"), Args(TEXT("w"), FString::FromInt(R.X), TEXT("h"), FString::FromInt(R.Y)));
		};
		auto CycleRes = [this](int32 Dir)
		{
			const int32 N = UE_ARRAY_COUNT(Resolutions);
			const FIntPoint Now = GameKit::SettingResolution(*Settings);
			int32 Index = 0;
			for (int32 I = 0; I < N; ++I)
			{
				if (Resolutions[I][0] == Now.X && Resolutions[I][1] == Now.Y)
				{
					Index = I;
				}
			}
			const int32* Pick = Resolutions[(Index + Dir + N) % N];
			Settings->GetObjectField(TEXT("display"))->SetArrayField(TEXT("resolution"), {MakeNumber(Pick[0]), MakeNumber(Pick[1])});
			Changed();
		};
		Res.Step = CycleRes;
		Res.Accept = [CycleRes] { CycleRes(1); };
		Rows.Add(Res);
		Rows.Add(Field(TEXT("display"), TEXT("ui_scale"), EGameKitRowKind::Slider, 0.75, 2.0, 0.25, {}, true));
	}
	else if (Tab == TEXT("audio"))
	{
		for (const TCHAR* Bus : {TEXT("master"), TEXT("music"), TEXT("sfx"), TEXT("ui"), TEXT("voice")})
		{
			Rows.Add(Field(TEXT("audio"), Bus, EGameKitRowKind::Slider, 0.0, 1.0, 0.1));
		}
		Rows.Add(Field(TEXT("audio"), TEXT("mono"), EGameKitRowKind::Toggle));
	}
	else if (Tab == TEXT("controls"))
	{
		for (const TCHAR* Action : GameActions)
		{
			Rows.Add(BindingRow(Action));
		}
		Rows.Add(Field(TEXT("input"), TEXT("glyphs"), EGameKitRowKind::Choice, 0, 0, 0, StringArray(GameKit::GlyphSets, UE_ARRAY_COUNT(GameKit::GlyphSets))));
		Rows.Add(Field(TEXT("input"), TEXT("deadzone"), EGameKitRowKind::Slider, 0.0, 0.9, 0.05));
		Rows.Add(Field(TEXT("input"), TEXT("invert_y"), EGameKitRowKind::Toggle));
		Rows.Add(ButtonRow(TEXT("reset"), TEXT("controls.reset"), [this]
		{
			SetBindings(GameKit::DefaultBindings());
			Message = T(TEXT("controls.reset_done"));
			MessageT = MessageS;
		}));
		for (const TCHAR* Preset : PresetNames)   // one-handed layouts (#166, motor access)
		{
			const FString Name = Preset;
			Rows.Add(ButtonRow(TEXT("preset_") + Name, TEXT("controls.preset.") + Name, [this, Name] { ApplyPreset(Name); }));
		}
	}
	else if (Tab == TEXT("access"))
	{
		Rows.Add(Field(TEXT("access"), TEXT("text_scale"), EGameKitRowKind::Slider, TextScaleMin, TextScaleMax, TextScaleStep, {}, true));
		Rows.Add(Field(TEXT("access"), TEXT("subtitles"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("subtitle_size"), EGameKitRowKind::Choice, 0, 0, 0, StringArray(GameKit::SubtitleSizes, UE_ARRAY_COUNT(GameKit::SubtitleSizes))));
		Rows.Add(Field(TEXT("access"), TEXT("subtitle_background"), EGameKitRowKind::Slider, 0.0, 1.0, 0.1));
		Rows.Add(Field(TEXT("access"), TEXT("speaker_names"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("subtitle_barks"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("captions_sfx"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("colorblind"), EGameKitRowKind::Choice, 0, 0, 0, StringArray(GameKit::ColorblindModes, UE_ARRAY_COUNT(GameKit::ColorblindModes))));
		Rows.Add(Field(TEXT("access"), TEXT("reduce_motion"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("shake_scale"), EGameKitRowKind::Slider, 0.0, 1.0, 0.25));
		Rows.Add(Field(TEXT("access"), TEXT("flash_limit"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("hold_to_toggle"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("difficulty"), EGameKitRowKind::Choice, 0, 0, 0, StringArray(GameKit::Difficulties, UE_ARRAY_COUNT(GameKit::Difficulties))));
		Rows.Add(Field(TEXT("access"), TEXT("game_speed"), EGameKitRowKind::Slider, 0.5, 1.0, 0.1));
		Rows.Add(Field(TEXT("access"), TEXT("readable_font"), EGameKitRowKind::Toggle));          // #167: cognitive access
		Rows.Add(Field(TEXT("access"), TEXT("line_spacing"), EGameKitRowKind::Slider, 1.0, 2.0, 0.25, {}, true));
		Rows.Add(Field(TEXT("access"), TEXT("subtitle_hold"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("timing_scale"), EGameKitRowKind::Slider, 1.0, 3.0, 0.5, {}, true));   // #166: motor access
		Rows.Add(Field(TEXT("access"), TEXT("auto_repeat"), EGameKitRowKind::Toggle));
		Rows.Add(Field(TEXT("access"), TEXT("narration"), EGameKitRowKind::Toggle));              // #165: menu narration
	}
	else if (Tab == TEXT("language"))
	{
		FGameKitRow Lang;
		Lang.Id = TEXT("language");
		Lang.Kind = EGameKitRowKind::Choice;
		Lang.Label = [this] { return T(TEXT("settings.language.language")); };
		Lang.Value = [this]
		{
			const FString Loc = Locale();
			const FString Name = GameKit::Tr(Tables, Loc, TEXT("language.name"));
			return Content(Name == TEXT("language.name") ? Loc : Name);
		};
		auto CycleLang = [this](int32 Dir)
		{
			const TArray<FString> All = Locales();
			int32 Index = All.IndexOfByKey(Locale());
			Index = Index == INDEX_NONE ? 0 : (Index + Dir + All.Num()) % All.Num();
			Opt.Locale.Empty();   // the player's choice beats --locale from here on
			SetStr(TEXT("language"), TEXT(""), All[Index]);
		};
		Lang.Step = CycleLang;
		Lang.Accept = [CycleLang] { CycleLang(1); };
		Rows.Add(Lang);
		Rows.Add(Field(TEXT("telemetry"), TEXT("consent"), EGameKitRowKind::Choice, 0, 0, 0, StringArray(GameKit::ConsentValues, UE_ARRAY_COUNT(GameKit::ConsentValues))));
	}
	Rows.Add(BackRow());
}

FGameKitScreen FGameKitShellModel::Build(const FString& Name)
{
	FGameKitScreen S;
	S.Name = Name;
	if (Name == TEXT("title"))
	{
		if (!bConsentAsked && Str(TEXT("telemetry"), TEXT("consent")) == TEXT("unset"))
		{
			bConsentAsked = true;
			auto Answer = [this](const FString& Value)
			{
				return [this, Value]
				{
					SetStr(TEXT("telemetry"), TEXT("consent"), Value);
					if (Value != TEXT("unset"))
					{
						SaveSettings();
					}
					UE_LOG(LogGameKitShell, Log, TEXT("telemetry consent %s"), *Value);
					if (FGameKitScreen* Screen = Top())
					{
						Screen->Dialog.Empty();
						++Version;
					}
					Event(TEXT("consent"));
				};
			};
			S.Dialog.Add(ButtonRow(TEXT("yes"), TEXT("consent.yes"), Answer(TEXT("yes"))));
			S.Dialog.Add(ButtonRow(TEXT("no"), TEXT("consent.no"), Answer(TEXT("no"))));
			S.Dialog.Add(ButtonRow(TEXT("later"), TEXT("consent.later"), Answer(TEXT("unset"))));
			S.DialogFocus = 2;   // Later: the choice that changes nothing
		}
	}
	else if (Name == TEXT("main_menu"))
	{
		S.Rows.Add(ButtonRow(TEXT("play"), TEXT("menu.play"), [this]
		{
			Push(TEXT("loading"));
			Top()->Next = TEXT("play");
		}));
		S.Rows.Add(ButtonRow(TEXT("settings"), TEXT("menu.settings"), [this] { Push(TEXT("settings")); }));
		S.Rows.Add(ButtonRow(TEXT("credits"), TEXT("menu.credits"), [this] { Push(TEXT("credits")); }));
		S.Rows.Add(ButtonRow(TEXT("quit"), TEXT("menu.quit"), [this]
		{
			bQuitRequested = true;
			UE_LOG(LogGameKitShell, Log, TEXT("quit"));
			Event(TEXT("quit"));
		}));
	}
	else if (Name == TEXT("settings"))
	{
		S.HeadingKey = TEXT("settings.title");
		S.Tabs = StringArray(SettingsTabs, UE_ARRAY_COUNT(SettingsTabs));
		S.bOnTabs = true;
		BuildTab(S);
	}
	else if (Name == TEXT("loading"))
	{
		S.HeadingKey = TEXT("loading.title");
		S.Steps = LoadingFillerSteps;
		S.Next = TEXT("play");
	}
	else if (Name == TEXT("pause"))
	{
		S.HeadingKey = TEXT("pause.title");
		S.bTransparent = true;
		S.Rows.Add(ButtonRow(TEXT("resume"), TEXT("pause.resume"), [this] { Pop(); Event(TEXT("resume")); }));
		S.Rows.Add(ButtonRow(TEXT("help"), TEXT("pause.help"), [this] { Push(TEXT("help")); }));           // #167
		S.Rows.Add(ButtonRow(TEXT("history"), TEXT("pause.history"), [this] { Push(TEXT("history")); }));
		S.Rows.Add(ButtonRow(TEXT("settings"), TEXT("menu.settings"), [this] { Push(TEXT("settings")); }));
		S.Rows.Add(ButtonRow(TEXT("quit"), TEXT("pause.quit"), [this] { Reset(TEXT("title")); Event(TEXT("quit_title")); }));
	}
	else if (Name == TEXT("help"))
	{
		S.HeadingKey = TEXT("help.title");
		S.Lines = HelpLines();
	}
	else if (Name == TEXT("history"))
	{
		S.HeadingKey = TEXT("history.title");
		S.Lines = HistoryLines();
		S.Scroll = FMath::Max(0, S.Lines.Num() - 1);   // the newest line
	}
	else if (Name == TEXT("credits"))
	{
		S.HeadingKey = TEXT("credits.title");
		S.Lines = CreditsLines();
	}
	else if (Name != TEXT("play"))
	{
		UE_LOG(LogGameKitShell, Error, TEXT("no screen named %s"), *Name);
	}
	return S;
}

TArray<FString> FGameKitShellModel::CreditsLines() const
{
	TArray<FString> Out;
	const TOptional<FString> Text = GameKit::ReadTextFile(FPaths::Combine(Opt.ProjectDir, CreditsFile));
	if (!Text.IsSet() || Text.GetValue().TrimStartAndEnd().IsEmpty())
	{
		Out.Add(T(TEXT("credits.placeholder")));
	}
	else
	{
		TArray<FString> Lines;
		Text.GetValue().Replace(TEXT("\r"), TEXT("")).ParseIntoArray(Lines, TEXT("\n"), /*CullEmpty*/ false);
		for (FString Line : Lines)
		{
			if (Line.StartsWith(TEXT("#")))
			{
				Line = Line.Replace(TEXT("#"), TEXT("")).TrimStartAndEnd();   // heading marks off, the text stays
			}
			Out.Add(Content(Line.TrimEnd()));
		}
	}
	Out.Add(FString());
	Out.Add(T(TEXT("credits.engine")));
	return Out;
}

TArray<FString> FGameKitShellModel::HelpLines() const
{
	TArray<FString> Out;
	Out.Add(Objective.IsEmpty() ? T(TEXT("help.no_objective")) : T(TEXT("help.objective"), Args(TEXT("text"), Objective)));
	if (SaidLines.Num())
	{
		Out.Add(T(TEXT("help.last_line"), Args(TEXT("name"), Content(SaidLines.Last().Speaker), TEXT("text"), Content(SaidLines.Last().Text))));
	}
	Out.Add(T(TEXT("help.controls")));
	for (const TCHAR* Action : HelpActions)
	{
		FString Glyph, Label;
		Prompt(Action, Glyph, Label);
		Out.Add(T(TEXT("action.") + FString(Action)) + TEXT(": ") + Label);
	}
	return Out;
}

TArray<FString> FGameKitShellModel::HistoryLines() const
{
	TArray<FString> Out;
	if (SaidLines.IsEmpty())
	{
		Out.Add(T(TEXT("history.empty")));
	}
	for (const FGameKitSaidLine& Line : SaidLines)
	{
		Out.Add(T(TEXT("help.last_line"), Args(TEXT("name"), Content(Line.Speaker), TEXT("text"), Content(Line.Text))));
	}
	return Out;
}

// ---- Input ------------------------------------------------------------------------------------------------------
void FGameKitShellModel::CancelCapture()
{
	CaptureAction.Empty();
	CaptureSlotIndex = -1;
	++Version;
}

bool FGameKitShellModel::KeyPressed(const FString& Binding, const FString& Device)
{
	LastDevice = Device;
	if (IsCapturing())
	{
		if (Binding == TEXT("key:escape") || Binding == TEXT("pad:east"))
		{
			CancelCapture();
			return true;
		}
		const bool bPad = Binding.StartsWith(TEXT("pad:"));
		if (bPad != (CaptureSlotIndex == GameKit::PadSlot))
		{
			return true;   // a key for the pad column (or a button for the keyboard one): wait for the right kind
		}
		const FString Action = CaptureAction;
		const int32 Slot = CaptureSlotIndex;
		CancelCapture();
		if (const TOptional<FGameKitRebindResult> R = GameKit::Rebind(Bindings(), Action, Slot, Binding))
		{
			SetBindings(R->Bindings);
			if (R->Conflicts.Num())
			{
				Message = T(TEXT("controls.swapped"), Args(TEXT("action"), T(TEXT("action.") + R->Conflicts[0].Key)));
			}
			else
			{
				Message = T(TEXT("controls.bound"), Args(TEXT("action"), T(TEXT("action.") + Action)));
			}
			MessageT = MessageS;
		}
		return true;
	}
	const FGameKitScreen* TopScreen = Top();
	if (TopScreen && TopScreen->Name == TEXT("title") && TopScreen->Dialog.IsEmpty())
	{
		// "press any key or button": everything but the cancel key opens the menu
		if (Binding != TEXT("key:escape") && Binding != TEXT("pad:east"))
		{
			Push(TEXT("main_menu"));
			return true;
		}
		return false;
	}
	TArray<FString> Actions;
	for (const auto& Pair : Bindings())
	{
		if (Pair.Value.Contains(Binding))
		{
			Actions.Add(Pair.Key);
		}
	}
	Actions.Sort([](const FString& A, const FString& B) { return FCString::Strcmp(*A, *B) < 0; });
	// a held subtitle line (#167) takes the accept first: on a gamepad, south is accept and jump, and the line
	// must go before the game jumps
	if (bHeld && Actions.Contains(TEXT("ui_accept")))
	{
		Dismiss();
		return true;
	}
	for (const FString& Action : Actions)
	{
		if (Dispatch(Action))
		{
			return true;
		}
	}
	return false;
}

bool FGameKitShellModel::RowAction(FGameKitScreen& Screen, TArray<FGameKitRow>& Rows, int32& Focus, const FString& Action)
{
	if (Rows.IsEmpty())
	{
		return false;
	}
	if (Action == TEXT("ui_down") || Action == TEXT("ui_up"))
	{
		Focus = (Focus + (Action == TEXT("ui_down") ? 1 : Rows.Num() - 1)) % Rows.Num();
		++Version;
		NarrateFocus();
		return true;
	}
	// Copies of the row's callbacks: a callback that pushes or pops a screen can move or free the row it came
	// from (the stack array grows), so the running lambda must own its captures, not borrow the row's
	const FGameKitRow& Row = Rows[FMath::Clamp(Focus, 0, Rows.Num() - 1)];
	const TFunction<void(int32)> Step = Row.Step;
	const TFunction<void()> Accept = Row.Accept;
	const FString ScreenName = Screen.Name;
	const int32 Depth = Stack.Num();
	if (Action == TEXT("ui_left") || Action == TEXT("ui_right"))
	{
		if (Step)
		{
			Step(Action == TEXT("ui_left") ? -1 : 1);
			++Version;
			NarrateFocus();
			return true;
		}
		return false;
	}
	if (Action == TEXT("ui_accept"))
	{
		if (Accept)
		{
			Accept();
			++Version;
			if (Stack.Num() == Depth && Top() && Top()->Name == ScreenName)
			{
				NarrateFocus();
			}
		}
		return true;
	}
	return false;
}

bool FGameKitShellModel::Dispatch(const FString& Action)
{
	if (bHeld && Action == TEXT("ui_accept"))
	{
		Dismiss();   // accept first dismisses a subtitle line waiting for the player (access.subtitle_hold, #167)
		return true;
	}
	FGameKitScreen* S = Top();
	if (!S)
	{
		return false;
	}
	const FString Name = S->Name;
	if (Name == TEXT("title"))
	{
		if (S->Dialog.Num())
		{
			if (Action == TEXT("ui_cancel"))
			{
				S->DialogFocus = S->Dialog.Num() - 1;   // cancel = Later
				const TFunction<void()> Later = S->Dialog.Last().Accept;   // a copy: Later empties the dialog
				Later();
				return true;
			}
			return RowAction(*S, S->Dialog, S->DialogFocus, Action);
		}
		if (Action == TEXT("ui_accept"))
		{
			Push(TEXT("main_menu"));
			return true;
		}
		return false;
	}
	if (Name == TEXT("main_menu"))
	{
		if (Action == TEXT("ui_cancel"))
		{
			Pop();
			return true;
		}
		return RowAction(*S, S->Rows, S->Focus, Action);
	}
	if (Name == TEXT("settings"))
	{
		if (Action == TEXT("ui_cancel"))
		{
			SaveSettings();
			Pop();
			return true;
		}
		if (S->bOnTabs)
		{
			if (Action == TEXT("ui_left") || Action == TEXT("ui_right"))
			{
				const int32 N = S->Tabs.Num();
				S->TabIndex = (S->TabIndex + (Action == TEXT("ui_left") ? N - 1 : 1)) % N;
				BuildTab(*S);
				++Version;
				LastNarration = GameKit::NarrationLine(T(TEXT("settings.tab.") + S->Tab()), T(TEXT("narrate.button")));
				if (Flag(TEXT("access"), TEXT("narration")) && OnNarrate)
				{
					OnNarrate(LastNarration);
				}
				return true;
			}
			if (Action == TEXT("ui_down") || Action == TEXT("ui_accept"))
			{
				S->bOnTabs = false;
				S->Focus = 0;
				++Version;
				NarrateFocus();
				return true;
			}
			return Action == TEXT("ui_up");
		}
		if (Action == TEXT("ui_up") && S->Focus == 0)
		{
			S->bOnTabs = true;
			++Version;
			return true;
		}
		return RowAction(*S, S->Rows, S->Focus, Action);
	}
	if (Name == TEXT("loading"))
	{
		return true;   // no input while loading
	}
	if (Name == TEXT("play"))
	{
		if (Action == TEXT("pause"))
		{
			Push(TEXT("pause"));
			return true;
		}
		return false;
	}
	if (Name == TEXT("pause"))
	{
		if (Action == TEXT("pause") || Action == TEXT("ui_cancel"))
		{
			Pop();
			Event(TEXT("resume"));
			return true;
		}
		return RowAction(*S, S->Rows, S->Focus, Action);
	}
	if (Name == TEXT("help") || Name == TEXT("history") || Name == TEXT("credits"))
	{
		if (Action == TEXT("ui_cancel") || Action == TEXT("ui_accept"))
		{
			Pop();
			return true;
		}
		if (Action == TEXT("ui_down"))
		{
			S->Scroll = FMath::Min(S->Scroll + 1, FMath::Max(0, S->Lines.Num() - 1));
			++Version;
			return true;
		}
		if (Action == TEXT("ui_up"))
		{
			S->Scroll = FMath::Max(0, S->Scroll - 1);
			++Version;
			return true;
		}
		return false;
	}
	return false;
}

// ---- Frame -------------------------------------------------------------------------------------------------------
void FGameKitShellModel::Update(double Dt)
{
	Time += Dt;
	if (MessageT > 0.0)
	{
		MessageT -= Dt;
		if (MessageT <= 0.0)
		{
			Message.Empty();
			++Version;
		}
	}
	if (FGameKitScreen* S = Top())
	{
		S->Time += Dt;
		if (S->Name == TEXT("loading"))
		{
			++S->Frames;
			if (S->Done < S->Steps)
			{
				++S->Done;   // a game's own load steps go here, one per frame
				++Version;
			}
			else if (Opt.bAutomated ? S->Frames >= LoadingMinFrames : S->Time >= LoadingMinS)
			{
				const FString Next = S->Next;
				Replace(Next);
				if (Next == TEXT("play"))
				{
					Event(TEXT("play"));
				}
			}
		}
	}
	if (HasSubtitle() && !bHeld)
	{
		SubtitleT += Dt;
		if (SubtitleT >= SubtitleEnd)
		{
			if (Flag(TEXT("access"), TEXT("subtitle_hold")))
			{
				bHeld = true;   // the line waits for the player (#167)
			}
			else
			{
				Subtitle = FGameKitSaidLine();
			}
			++Version;
		}
	}
}

// ---- Subtitles ---------------------------------------------------------------------------------------------------
void FGameKitShellModel::Say(const FString& Speaker, const FString& Text, double Seconds)
{
	Subtitle.Speaker = Speaker;
	Subtitle.Text = Text;
	SubtitleT = 0.0;
	SubtitleEnd = Seconds > 0.0 ? Seconds : FMath::Max(SubtitleMinS, GameKit::CodePointLength(Text) * SubtitleSecondsPerChar);
	bHeld = false;
	SaidLines.Add({Speaker, Text});   // the history for "What now?" and the history page (#167)
	if (SaidLines.Num() > MaxHistory)
	{
		SaidLines.RemoveAt(0);
	}
	++Version;
}

void FGameKitShellModel::Dismiss()
{
	Subtitle = FGameKitSaidLine();
	bHeld = false;
	++Version;
}

// ---- Narration ---------------------------------------------------------------------------------------------------
FString FGameKitShellModel::Describe(const FGameKitRow& Row) const
{
	const TCHAR* Role = TEXT("narrate.button");
	switch (Row.Kind)
	{
	case EGameKitRowKind::Toggle: Role = TEXT("narrate.toggle"); break;
	case EGameKitRowKind::Slider: Role = TEXT("narrate.slider"); break;
	case EGameKitRowKind::Choice: Role = TEXT("narrate.choice"); break;
	default: break;
	}
	FString Value = Row.Value ? Row.Value() : FString();
	if (Row.Kind == EGameKitRowKind::Binding && Row.CellText)
	{
		Value = Row.CellText(0) + TEXT(", ") + Row.CellText(1);
	}
	return GameKit::NarrationLine(Row.Label ? Row.Label() : FString(), T(Role), Value);
}

void FGameKitShellModel::NarrateFocus()
{
	const FGameKitScreen* S = Top();
	const FGameKitRow* Row = S ? S->Focused() : nullptr;
	if (!Row)
	{
		return;
	}
	const FString Line = Describe(*Row);
	if (Line == LastNarration)
	{
		return;
	}
	LastNarration = Line;
	if (Flag(TEXT("access"), TEXT("narration")) && OnNarrate)
	{
		OnNarrate(Line);
	}
}

void FGameKitShellModel::NarrateScreen(const FGameKitScreen& Screen)
{
	LastNarration = GameKit::NarrationLine(Heading(Screen), T(TEXT("narrate.screen")));
	if (Flag(TEXT("access"), TEXT("narration")) && OnNarrate)
	{
		OnNarrate(LastNarration);
	}
}

// ---- Colours -----------------------------------------------------------------------------------------------------
FLinearColor FGameKitShellModel::PaletteColour(const FString& Name, const FLinearColor& Fallback) const
{
	if (!Colours.IsValid())
	{
		return Fallback;
	}
	const TSharedPtr<FJsonObject> Palettes = FindObject(Colours, TEXT("palettes"));
	TSharedPtr<FJsonObject> Palette = FindObject(Palettes, Str(TEXT("access"), TEXT("colorblind")));
	if (!Palette.IsValid())
	{
		Palette = FindObject(Palettes, TEXT("none"));   // a mode without its own palette uses "none"
	}
	const FString Hex = GetString(Palette, Name, FString());
	if (Hex.IsEmpty())
	{
		return Fallback;
	}
	return FLinearColor(FColor::FromHex(Hex));
}

// ---- Events ------------------------------------------------------------------------------------------------------
void FGameKitShellModel::Event(const FString& What)
{
	if (OnEvent)
	{
		OnEvent(What);
	}
}

// {{FOOTER}}
