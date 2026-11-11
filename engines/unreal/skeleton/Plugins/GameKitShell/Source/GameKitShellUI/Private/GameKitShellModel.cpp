// ---------------------------------------------------------------------------
// GameKitShellModel.cpp
// Purpose : Implementation of the headless screen model (see GameKitShellModel.h): the screens, their rows,
//           the input rules, settings rows per tab, subtitles, history and narration.
// Usage   : compiled into the GameKitShellUI module; call through GameKitShellModel.h.
// Notes   : Rows read and write the settings object directly through small closures, so a row's label and
//           value are always what the settings hold now (no copies to keep in step). The settings rows
//           follow the LÖVE shell's settings.lua one for one (same tabs, same order, same steps), so the
//           golden settings schema (GameKitSettings.cpp) is what the menu offers.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); analog input (#274), the juice demo, the bug report,
//           crash files and the pseudo locale (#275) by Claude (Opus 5.5, claude-opus-5-5); the i18n log line
//           (where the string tables came from, or that there were none) by Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): credits from data/credits.md in a packaged game,
//           the copy kept in step by SyncCreditsCopy (#278)
// ---------------------------------------------------------------------------
#include "GameKitShellModel.h"

#include "GameKitAnalog.h"
#include "GameKitAtomicFile.h"
#include "GameKitJson.h"
#include "GameKitJuiceDemo.h"
#include "GameKitSettings.h"
#include "GameKitShellLog.h"
#include "GameKitShellReport.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

const TCHAR* const FGameKitShellModel::BugKey = TEXT("key:f8");
const TCHAR* const FGameKitShellModel::PseudoLocale = TEXT("pseudo");
const TCHAR* const FGameKitShellModel::SettingsFile = TEXT("settings.json");
const TCHAR* const FGameKitShellModel::PresetsFile = TEXT("data/input/presets.json");
const TCHAR* const FGameKitShellModel::ColoursFile = TEXT("data/access/colours.json");
const TCHAR* const FGameKitShellModel::I18nDir = TEXT("data/i18n");
const TCHAR* const FGameKitShellModel::CreditsFile = TEXT("CREDITS.md");
const TCHAR* const FGameKitShellModel::CreditsCopyFile = TEXT("data/credits.md");
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

FGameKitShellModel::~FGameKitShellModel()
{
	if (bCrashArmed)
	{
		GameKit::ShellReport::ClearCrashTarget(this);
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
				Table.Add(FString(*Pair.Key), Pair.Value->AsString());
			}
		}
		Tables.Add(FPaths::GetBaseFilename(File), MoveTemp(Table));
	}
	// Say where the strings came from: a packaged game without data/ (Config/Game.ini stages it) shows keys
	const FString FullDir = FPaths::ConvertRelativePathToFull(Dir);
	if (Tables.Num() == 0)
	{
		UE_LOG(LogGameKitShell, Warning, TEXT("i18n: no string tables in %s: labels show their keys"), *FullDir);
		return;
	}
	TArray<FString> Names;
	Tables.GetKeys(Names);
	Names.Sort();
	UE_LOG(LogGameKitShell, Log, TEXT("i18n: string tables %s from %s"), *FString::Join(Names, TEXT(", ")), *FullDir);
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
	if (bCrashArmed)
	{
		GameKit::ShellReport::UpdateCrashSettings(this, Write(Settings));   // a crash file shows the settings of now
	}
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
	if (IsPseudo())
	{
		// the English text through Pseudo(), placeholders kept, then filled: "{name}" stays a name, not accented
		const FGameKitStringTable* English = Tables.Find(GameKit::FallbackLocale);
		const FString* Text = English ? English->Find(Key) : nullptr;
		if (!Text)
		{
			return Key;   // unbracketed on purpose: the pseudo check flags a missing string
		}
		FGameKitStringTables One;
		One.Add(PseudoLocale).Add(Key, GameKit::Pseudo(*Text));
		return GameKit::Tr(One, PseudoLocale, Key, Args);
	}
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
	if (Opt.bDebugBuild)
	{
		Out.AddUnique(PseudoLocale);   // a tester picks it in the Language tab, as on the other shells
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
	ScreenOpened(Name);
}

void FGameKitShellModel::ScreenOpened(const FString& Name)
{
	if (Name == TEXT("juice_demo"))
	{
		JuiceDemo = MakeUnique<FGameKitJuiceDemo>();
		JuiceDemo->Enter(*this);
	}
	else if (JuiceDemo.IsValid() && !Stack.ContainsByPredicate([](const FGameKitScreen& S) { return S.Name == TEXT("juice_demo"); }))
	{
		JuiceDemo.Reset();   // the demo left the stack (quit to title)
	}
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
		if (JuiceDemo.IsValid() && !Stack.ContainsByPredicate([](const FGameKitScreen& S) { return S.Name == TEXT("juice_demo"); }))
		{
			JuiceDemo.Reset();
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
		B.Add(FString(*Pair.Key), Slots);
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
			const FString Name = Loc == PseudoLocale ? Loc : GameKit::Tr(Tables, Loc, TEXT("language.name"));
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
		if (Opt.bDebugBuild)
		{
			S.Rows.Add(ButtonRow(TEXT("juice"), TEXT("menu.juice"), [this]   // #275: the juice demo, debug builds only
			{
				Push(TEXT("loading"));
				Top()->Next = TEXT("juice_demo");
			}));
		}
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
	else if (Name == TEXT("juice_demo"))
	{
		S.HeadingKey = TEXT("juice.title");   // ScreenOpened starts the demo itself
	}
	else if (Name != TEXT("play"))
	{
		UE_LOG(LogGameKitShell, Error, TEXT("no screen named %s"), *Name);
	}
	return S;
}

FString FGameKitShellModel::CreditsSource(const FString& ProjectDir)
{
	// The project's own CREDITS.md first (the editor, a dev run: always the file you just edited), then the copy
	// under data/ that a packaged game ships (#278); "" when there is neither
	for (const TCHAR* Rel : {CreditsFile, CreditsCopyFile})
	{
		const FString Path = FPaths::Combine(ProjectDir, Rel);
		if (IFileManager::Get().FileExists(*Path))
		{
			return Path;
		}
	}
	return FString();
}

bool FGameKitShellModel::SyncCreditsCopy(const FString& ProjectDir, FString& OutWhat)
{
	IFileManager& Files = IFileManager::Get();
	const FString Source = FPaths::Combine(ProjectDir, CreditsFile);
	const FString Copy = FPaths::Combine(ProjectDir, CreditsCopyFile);
	if (!Files.FileExists(*Source))
	{
		if (!Files.FileExists(*Copy))
		{
			OutWhat = FString::Printf(TEXT("no %s, nothing to copy"), CreditsFile);
			return true;
		}
		// The copy is generated (and gitignored): with CREDITS.md gone it would ship credits nobody has any more
		if (!Files.Delete(*Copy, /*RequireExists*/ false, /*EvenReadOnly*/ true, /*Quiet*/ true))
		{
			OutWhat = FString::Printf(TEXT("could not remove %s (CREDITS.md is gone)"), *Copy);
			return false;
		}
		OutWhat = FString::Printf(TEXT("removed %s: there is no %s any more"), CreditsCopyFile, CreditsFile);
		return true;
	}
	TArray<uint8> Want, Have;
	if (!FFileHelper::LoadFileToArray(Want, *Source))
	{
		OutWhat = FString::Printf(TEXT("could not read %s"), *Source);
		return false;
	}
	if (FFileHelper::LoadFileToArray(Have, *Copy, FILEREAD_Silent) && Have == Want)
	{
		OutWhat = FString::Printf(TEXT("%s is up to date"), CreditsCopyFile);
		return true;   // untouched: no new timestamp, nothing for a cook or a backup to pick up
	}
	Files.MakeDirectory(*FPaths::GetPath(Copy), /*Tree*/ true);   // a project without data/ gets one for the copy
	if (!FFileHelper::SaveArrayToFile(Want, *Copy))
	{
		OutWhat = FString::Printf(TEXT("could not write %s"), *Copy);
		return false;
	}
	OutWhat = FString::Printf(TEXT("copied %s to %s (%d bytes)"), CreditsFile, CreditsCopyFile, Want.Num());
	return true;
}

TArray<FString> FGameKitShellModel::CreditsLines() const
{
	TArray<FString> Out;
	const FString Path = CreditsSource(Opt.ProjectDir);
	const TOptional<FString> Text = Path.IsEmpty() ? TOptional<FString>() : GameKit::ReadTextFile(Path);
	// Whichever file it is (CREDITS.md, or the data/credits.md copy a packaged game reads), its HTML comments go (#279)
	const TArray<FString> Lines = Text.IsSet() ? CreditsLinesFrom(Text.GetValue()) : TArray<FString>();
	if (Lines.IsEmpty())
	{
		// Says where it looked, so a packaged game without credits is one log line to explain
		if (Path.IsEmpty())
		{
			UE_LOG(LogGameKitShell, Display, TEXT("credits: none (no %s or %s in %s), the placeholder shows"), CreditsFile,
			       CreditsCopyFile, *FPaths::ConvertRelativePathToFull(Opt.ProjectDir));
		}
		else
		{
			UE_LOG(LogGameKitShell, Display, TEXT("credits: only blanks or comments in %s, the placeholder shows"),
			       *FPaths::ConvertRelativePathToFull(Path));
		}
		Out.Add(T(TEXT("credits.placeholder")));
	}
	else
	{
		UE_LOG(LogGameKitShell, Display, TEXT("credits: %d lines from %s"), Lines.Num(), *FPaths::ConvertRelativePathToFull(Path));
	}
	for (const FString& Line : Lines)
	{
		Out.Add(Content(Line));
	}
	Out.Add(FString());
	Out.Add(T(TEXT("credits.engine")));
	return Out;
}

TArray<FString> FGameKitShellModel::CreditsLinesFrom(const FString& Markdown)
{
	TArray<FString> Out;
	const FString Text = StripHtmlComments(Markdown);
	if (Text.TrimStartAndEnd().IsEmpty())
	{
		return Out;
	}
	TArray<FString> Lines;
	Text.Replace(TEXT("\r"), TEXT("")).ParseIntoArray(Lines, TEXT("\n"), /*CullEmpty*/ false);
	for (FString Line : Lines)
	{
		if (Line.StartsWith(TEXT("#")))
		{
			Line = Line.Replace(TEXT("#"), TEXT("")).TrimStartAndEnd();   // heading marks off, the text stays
		}
		Out.Add(Line.TrimEnd());
	}
	return Out;
}

namespace GameKitCreditsText
{
	const TCHAR* const CommentOpen = TEXT("<!--");
	const TCHAR* const CommentClose = TEXT("-->");

	/** Only spaces and tabs (every port counts these two; Unicode whitespace differs between languages). */
	bool Blank(const FString& Line)
	{
		for (const TCHAR C : Line)
		{
			if (C != TEXT(' ') && C != TEXT('\t'))
			{
				return false;
			}
		}
		return true;
	}

	/** Needle in Hay at From or later, or INDEX_NONE. FString::Find clamps a start past the end to the last
	 *  character, which would find a one-character needle there again. */
	int32 FindFrom(const FString& Hay, const TCHAR* Needle, int32 From)
	{
		if (From >= Hay.Len())
		{
			return INDEX_NONE;
		}
		return Hay.Find(Needle, ESearchCase::CaseSensitive, ESearchDir::FromStart, From);
	}
}

FString FGameKitShellModel::StripHtmlComments(const FString& Text)
{
	using namespace GameKitCreditsText;
	const int32 OpenLen = FCString::Strlen(CommentOpen);
	const int32 CloseLen = FCString::Strlen(CommentClose);
	TArray<FString> Out;
	bool bInComment = false;
	bool bSkipBlank = false;                         // the blank line after a dropped comment-only line
	const FString Unix = Text.Replace(TEXT("\r\n"), TEXT("\n"));
	int32 LineStart = 0;
	while (LineStart <= Unix.Len())
	{
		int32 LineEnd = FindFrom(Unix, TEXT("\n"), LineStart);
		if (LineEnd == INDEX_NONE)
		{
			LineEnd = Unix.Len();
		}
		const FString Line = Unix.Mid(LineStart, LineEnd - LineStart);
		LineStart = LineEnd + 1;
		FString Kept;
		bool bHad = bInComment;
		int32 I = 0;
		while (true)
		{
			if (bInComment)
			{
				const int32 End = FindFrom(Line, CommentClose, I);
				if (End == INDEX_NONE)
				{
					break;                           // the comment goes on into the next line
				}
				bInComment = false;
				I = End + CloseLen;
			}
			else
			{
				const int32 Start = FindFrom(Line, CommentOpen, I);
				if (Start == INDEX_NONE)
				{
					Kept += Line.Mid(I);
					break;
				}
				Kept += Line.Mid(I, Start - I);
				bInComment = true;
				bHad = true;
				I = Start + OpenLen;
			}
		}
		if (bHad && Blank(Kept))
		{
			bSkipBlank = Out.IsEmpty() || Blank(Out.Last());
			continue;
		}
		if (bSkipBlank && Blank(Kept))
		{
			bSkipBlank = false;
			continue;
		}
		bSkipBlank = false;
		Out.Add(Kept);
	}
	return FString::Join(Out, TEXT("\n"));
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
	HeldBindings.Add(Binding);   // held until KeyReleased: the game's held actions (#274)
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
	if (Opt.bDebugBuild && Binding == BugKey)
	{
		BugReport();   // F8 on any screen, in debug builds (#275); never "any key" on the title
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

bool FGameKitShellModel::StickMoved(const FString& Axis, double Value, const FString& Device)
{
	const bool bX = Axis == TEXT("x");
	if (!bX && Axis != TEXT("y"))
	{
		return false;
	}
	(bX ? RawStick.X : RawStick.Y) = GameKit::AnalogFinite(Value);   // the game's analog stick (#274), shaped in Stick()
	static const TCHAR* const Dirs[4] = {TEXT("dpad_up"), TEXT("dpad_down"), TEXT("dpad_left"), TEXT("dpad_right")};
	const double Deadzone = FMath::Max(Num(TEXT("input"), TEXT("deadzone")), 0.05);
	const double V = FMath::Abs(Value) < Deadzone ? 0.0 : Value;
	const double On = FMath::Max(StickOn, Deadzone);
	bool bUsed = false;
	const auto Edge = [&](int32 Dir, bool bActive)
	{
		if (bActive && !StickHeld[Dir])
		{
			StickHeld[Dir] = true;
			const FString Binding = TEXT("pad:") + FString(Dirs[Dir]);
			const bool bPadHeld = HeldBindings.Contains(Binding);
			bUsed = KeyPressed(Binding, Device) || bUsed;
			if (!bPadHeld)
			{
				HeldBindings.Remove(Binding);   // a menu press, not a held d-pad: the stick holds move_* itself (StickActions)
			}
		}
		else if (!bActive && StickHeld[Dir])
		{
			StickHeld[Dir] = false;
		}
	};
	const int32 Neg = bX ? 2 : 1;   // left, or down (Unreal's LeftY is positive up)
	const int32 Pos = bX ? 3 : 0;   // right, or up
	Edge(Neg, V < -On || (StickHeld[Neg] && V < -StickOff));
	Edge(Pos, V > On || (StickHeld[Pos] && V > StickOff));
	return bUsed;
}

// ---- Analog input for the game (#274) ------------------------------------------------------------------------------
void FGameKitShellModel::KeyReleased(const FString& Binding)
{
	HeldBindings.Remove(Binding);
}

void FGameKitShellModel::ReleaseAll()
{
	HeldBindings.Empty();
	RawStick = FVector2D::ZeroVector;
	RawTrigger[0] = RawTrigger[1] = 0.0;
}

void FGameKitShellModel::TriggerMoved(bool bRight, double Value)
{
	RawTrigger[bRight ? 1 : 0] = FMath::Clamp(GameKit::AnalogFinite(Value), 0.0, 1.0);
}

bool FGameKitShellModel::GameActive() const
{
	const FString Name = TopName();
	return Name == TEXT("play") || Name == TEXT("juice_demo");
}

FVector2D FGameKitShellModel::Stick() const
{
	if (!GameActive())
	{
		return FVector2D::ZeroVector;
	}
	return GameKit::AnalogStick(RawStick.X, RawStick.Y, Num(TEXT("input"), TEXT("deadzone")), Flag(TEXT("input"), TEXT("invert_y")));
}

double FGameKitShellModel::Trigger(bool bRight) const
{
	return GameActive() ? GameKit::AnalogTrigger(RawTrigger[bRight ? 1 : 0]) : 0.0;
}

TArray<FString> FGameKitShellModel::StickActions() const
{
	TArray<FString> Out;
	const double On = FMath::Max(Num(TEXT("input"), TEXT("deadzone")), StickHoldMin);
	const double X = RawStick.X;
	const double Y = Flag(TEXT("input"), TEXT("invert_y")) ? -RawStick.Y : RawStick.Y;
	const TPair<const TCHAR*, double> Leans[] = {{TEXT("move_left"), -X}, {TEXT("move_right"), X}, {TEXT("move_up"), Y}, {TEXT("move_down"), -Y}};
	for (const TPair<const TCHAR*, double>& Lean : Leans)
	{
		if (Lean.Value > On)
		{
			Out.Add(Lean.Key);
		}
	}
	return Out;
}

TArray<FString> FGameKitShellModel::HeldActions() const
{
	TArray<FString> Out;
	if (!GameActive())
	{
		return Out;
	}
	for (const auto& Pair : Bindings())
	{
		if (Pair.Key.StartsWith(TEXT("ui_")))
		{
			continue;
		}
		for (const FString& Slot : Pair.Value)
		{
			if (!Slot.IsEmpty() && HeldBindings.Contains(Slot))
			{
				Out.AddUnique(Pair.Key);
			}
		}
	}
	for (const FString& Action : StickActions())
	{
		Out.AddUnique(Action);
	}
	Out.Sort();
	return Out;
}

bool FGameKitShellModel::IsHeld(const FString& Action) const
{
	return HeldActions().Contains(Action);
}

// ---- Bug report and crash files (#275) -----------------------------------------------------------------------------
void FGameKitShellModel::ShowToast(const FString& Text)
{
	Toast = Text;
	ToastT = ToastS;
	++Version;
}

void FGameKitShellModel::ArmCrashReports()
{
	GameKit::ShellReport::FCrashTarget Target;
	Target.DataDir = Opt.DataDir;
	Target.GameName = Opt.GameName;
	Target.Version = Opt.Version;
	Target.SettingsJson = Write(Settings);
	GameKit::ShellReport::SetCrashTarget(this, Target);
	bCrashArmed = true;
}

FString FGameKitShellModel::BugReport()
{
	using namespace GameKit::ShellReport;
	IFileManager::Get().MakeDirectory(*Opt.DataDir, /*Tree*/ true);
	const FString Dir = FPaths::ConvertRelativePathToFull(UniquePath(Opt.DataDir, TEXT("bug_"), Stamp(), FString()));
	TArray<FString> Info;
	Info.Add(Opt.GameName + TEXT(" ") + Opt.Version);
	Info.Add(TEXT("time: ") + FDateTime::UtcNow().ToIso8601());
	Info.Add(TEXT("screen: ") + (TopName().IsEmpty() ? FString(TEXT("none")) : TopName()));
	Info.Add(TEXT("locale: ") + Locale());
	Info.Add(TEXT("device: ") + LastDevice);
	Info.Add(TEXT("engine: ") + FEngineVersion::Current().ToString());
	Info.Add(TEXT("os: ") + FPlatformMisc::GetOSVersion());
	FString Error;
	const bool bOk = GameKit::WriteFileAtomic(FPaths::Combine(Dir, TEXT("info.txt")), FString::Join(Info, TEXT("\n")) + TEXT("\n"), &Error)
	                 && GameKit::WriteFileAtomic(FPaths::Combine(Dir, TEXT("log_tail.txt")), LogTail(BugTailLines) + TEXT("\n"), &Error)
	                 && GameKit::WriteFileAtomic(FPaths::Combine(Dir, TEXT("settings.json")), Write(Settings) + TEXT("\n"), &Error);
	if (!bOk)
	{
		UE_LOG(LogGameKitShell, Error, TEXT("bug report not saved: %s"), *Error);
		return FString();
	}
	if (OnScreenshot)
	{
		OnScreenshot(FPaths::Combine(Dir, TEXT("screenshot.png")));   // the game viewport may write it a frame later
	}
	LastBugReport = Dir;
	UE_LOG(LogGameKitShell, Display, TEXT("BUG_REPORT %s"), *Dir);
	ShowToast(T(TEXT("toast.bug_saved")));
	return Dir;
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
	if (Name == TEXT("juice_demo"))
	{
		if (Action == TEXT("pause"))
		{
			Push(TEXT("pause"));
			return true;
		}
		return JuiceDemo.IsValid() && JuiceDemo->Action(Action, *this);
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
	if (ToastT > 0.0)
	{
		ToastT -= Dt;
		if (ToastT <= 0.0)
		{
			Toast.Empty();
			++Version;
		}
	}
	if (JuiceDemo.IsValid() && TopName() == TEXT("juice_demo"))
	{
		JuiceDemo->Update(Dt, *this);   // paused under the pause menu: only the top screen runs; the view paints it live
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
