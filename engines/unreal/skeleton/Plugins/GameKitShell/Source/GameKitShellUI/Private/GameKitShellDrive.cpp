// ---------------------------------------------------------------------------
// GameKitShellDrive.cpp
// Purpose : The scenarios behind GameKitShellDrive.h: menus, show:<screen>, and the accessibility tour.
// Usage   : compiled into the GameKitShellUI module; run by the GameKit.Screens.Drive automation test, which
//           tools/dev.py smoke --drive starts.
// Notes   : Each helper returns false once the run has failed, and every scenario checks on the way, so a failure
//           stops the script where it happened and Error names the step. Add a scenario: a method here, its name
//           in Run() and IsKnown(), then document it in docs/ENGINE_FLOW.md.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellDrive.h"

#include "GameKitJson.h"
#include "GameKitSettings.h"
#include "GameKitShellTheme.h"

const TCHAR* FGameKitShellDrive::ShowScreens[9] = {TEXT("title"), TEXT("main_menu"), TEXT("settings"), TEXT("pause"), TEXT("help"),
                                                   TEXT("history"), TEXT("credits"), TEXT("loading"), TEXT("subtitle")};
const TCHAR* FGameKitShellDrive::AccessActions[7] = {TEXT("ui_up"), TEXT("ui_down"), TEXT("ui_left"), TEXT("ui_right"), TEXT("ui_accept"),
                                                     TEXT("ui_cancel"), TEXT("pause")};
const TCHAR* FGameKitShellDrive::PromptActions[6] = {TEXT("move_left"), TEXT("move_right"), TEXT("jump"), TEXT("attack"), TEXT("interact"),
                                                     TEXT("pause")};

namespace
{
	using namespace GameKit::Json;

	// the demo line the access tour shows as a subtitle (the kit's juice demo says it on the other engines)
	const TCHAR* DemoSpeaker = TEXT("Guide");
	const TCHAR* DemoLineKey = TEXT("juice.objective");

	TSharedPtr<FJsonValue> Text(const FString& S, float Px, const FColor& Fg, const FColor& Bg, bool bFits, const FString& Node,
	                            const TArray<TPair<FColor, double>>* OverGame = nullptr)
	{
		TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetStringField(TEXT("node"), Node);
		O->SetStringField(TEXT("text"), S.Left(60));
		O->SetStringField(TEXT("state"), TEXT(""));
		O->SetNumberField(TEXT("px"), Px);
		O->SetStringField(TEXT("fg"), GameKitTheme::Hex(Fg));
		if (OverGame)
		{
			TArray<TSharedPtr<FJsonValue>> Layers;
			for (const TPair<FColor, double>& Layer : *OverGame)
			{
				Layers.Add(MakeArray({MakeString(GameKitTheme::Hex(Layer.Key)), MakeNumber(Layer.Value)}));
			}
			O->SetArrayField(TEXT("over_game"), Layers);
		}
		else
		{
			O->SetStringField(TEXT("bg"), GameKitTheme::Hex(Bg));
		}
		O->SetBoolField(TEXT("fits"), bFits);
		O->SetBoolField(TEXT("covered"), false);
		return MakeObject(O);
	}
}

FGameKitShellDrive::FGameKitShellDrive(const TSharedRef<FGameKitShellModel>& InModel, FPrint InPrint)
	: Model(InModel)
	, Print(MoveTemp(InPrint))
{
}

bool FGameKitShellDrive::IsKnown(const FString& Name)
{
	if (Name == TEXT("menus") || Name == TEXT("access") || Name.StartsWith(TEXT("access:")))
	{
		return true;
	}
	if (Name.StartsWith(TEXT("show:")))
	{
		const FString Screen = Name.Mid(5);
		for (const TCHAR* S : ShowScreens)
		{
			if (Screen == S)
			{
				return true;
			}
		}
	}
	return false;
}

FString FGameKitShellDrive::KnownNames()
{
	TArray<FString> Shows;
	for (const TCHAR* S : ShowScreens)
	{
		Shows.Add(S);
	}
	return TEXT("menus, access[:res=WxH,scale=N,pad,read], show:<") + FString::Join(Shows, TEXT("|")) + TEXT(">");
}

// ---- Helpers -----------------------------------------------------------------------------------------------------
bool FGameKitShellDrive::Fail(const FString& Why)
{
	if (!bFailed)
	{
		bFailed = true;
		Error = Why;
		Print(TEXT("DRIVE_FAIL ") + Why);
	}
	return false;
}

bool FGameKitShellDrive::Frames(int32 N)
{
	for (int32 I = 0; I < N && !bFailed; ++I)
	{
		Model->Update(FrameS);
		if (++Frame > DriveLimit)
		{
			return Fail(FString::Printf(TEXT("the drive did not finish in %d frames"), DriveLimit));
		}
	}
	return !bFailed;
}

bool FGameKitShellDrive::WaitScreen(const FString& Name)
{
	for (int32 I = 0; I < WaitLimit && !bFailed; ++I)
	{
		if (Model->TopName() == Name)
		{
			return true;
		}
		Frames(1);
	}
	return Fail(FString::Printf(TEXT("timed out waiting for screen %s (on %s)"), *Name, *Model->TopName()));
}

bool FGameKitShellDrive::Press(const FString& Action)
{
	if (bFailed)
	{
		return false;
	}
	if (bPad)
	{
		// the gamepad-only run presses the action's pad button, as a player with no keyboard would
		const FGameKitBindings B = Model->Bindings();
		const TArray<FString>* Slots = B.Find(Action);
		FString Button;
		if (Slots)
		{
			for (const FString& S : *Slots)
			{
				if (S.StartsWith(TEXT("pad:")))
				{
					Button = S;
				}
			}
		}
		if (Button.IsEmpty())
		{
			return Fail(Action + TEXT(" has no gamepad button: a gamepad-only player cannot press it"));
		}
		Model->KeyPressed(Button, TEXT("pad"));
	}
	else
	{
		Model->Dispatch(Action);
	}
	return Frames(PressGap);
}

bool FGameKitShellDrive::Focus(const FString& Id, const FString& Step)
{
	for (int32 I = 0; I < FocusLimit && !bFailed; ++I)
	{
		if (Model->FocusId() == Id)
		{
			return true;
		}
		Press(Step);
	}
	return Fail(FString::Printf(TEXT("could not focus %s (focused: %s)"), *Id, *Model->FocusId()));
}

bool FGameKitShellDrive::Open(const FString& Item, const FString& Screen)
{
	return Focus(Item) && Press(TEXT("ui_accept")) && WaitScreen(Screen);
}

bool FGameKitShellDrive::ToMenu()
{
	if (!WaitScreen(TEXT("title")))
	{
		return false;
	}
	if (Model->Top()->Dialog.Num())
	{
		Press(TEXT("ui_cancel"));   // the consent question: Later
	}
	return Press(TEXT("ui_accept")) && WaitScreen(TEXT("main_menu"));
}

bool FGameKitShellDrive::ToTab(const FString& Tab)
{
	for (int32 I = 0; I < FocusLimit && !bFailed; ++I)
	{
		const FGameKitScreen* S = Model->Top();
		if (!S || S->Name != TEXT("settings"))
		{
			return Fail(TEXT("not on the settings screen"));
		}
		if (S->bOnTabs)
		{
			break;
		}
		Press(S->Focus == 0 ? TEXT("ui_up") : TEXT("ui_down"));
	}
	return Focus(TEXT("tabs.") + Tab, TEXT("ui_right"));
}

bool FGameKitShellDrive::SlideTo(const FString& What, TFunction<double()> Read, double Target)
{
	for (int32 I = 0; I < MaxSliderSteps && !bFailed; ++I)
	{
		const double Now = Read();
		if (FMath::IsNearlyEqual(Now, Target, 1e-9))
		{
			return true;
		}
		Press(Now > Target ? TEXT("ui_left") : TEXT("ui_right"));
	}
	if (!FMath::IsNearlyEqual(Read(), Target, 1e-9))
	{
		return Fail(FString::Printf(TEXT("%s did not reach %g (is %g)"), *What, Target, Read()));
	}
	return !bFailed;
}

// ---- Scenarios ---------------------------------------------------------------------------------------------------
int32 FGameKitShellDrive::Run(const FString& Name)
{
	bFailed = false;
	Error.Empty();
	Frame = 0;
	if (Model->Screens().IsEmpty())
	{
		Model->Push(TEXT("title"));
	}
	bool bOk = false;
	if (Name == TEXT("menus"))
	{
		bOk = Menus();
	}
	else if (Name.StartsWith(TEXT("show:")))
	{
		bOk = Show(Name.Mid(5));
	}
	else if (Name == TEXT("access") || Name.StartsWith(TEXT("access:")))
	{
		bOk = Access(Name.StartsWith(TEXT("access:")) ? Name.Mid(7) : FString());
	}
	else
	{
		Fail(FString::Printf(TEXT("unknown drive %s (%s)"), *Name, *KnownNames()));
	}
	const int32 Code = bOk && !bFailed ? 0 : 1;
	Print(FString::Printf(TEXT("DRIVE_DONE %s"), *Name));
	return Code;
}

bool FGameKitShellDrive::Menus()
{
	if (!ToMenu() || !Open(TEXT("settings"), TEXT("settings")) || !ToTab(TEXT("audio")) || !Press(TEXT("ui_down"))
	    || !Focus(TEXT("audio.master")))
	{
		return false;
	}
	if (!SlideTo(TEXT("audio.master"), [this] { return Model->Num(TEXT("audio"), TEXT("master")); }, TargetMaster))
	{
		return false;
	}
	if (!ToTab(TEXT("access")) || !Press(TEXT("ui_down")) || !Focus(TEXT("access.reduce_motion")))
	{
		return false;
	}
	if (!Model->Flag(TEXT("access"), TEXT("reduce_motion")))
	{
		Press(TEXT("ui_accept"));
	}
	if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("main_menu")))   // back: saves settings.json
	{
		return false;
	}
	const FString Path = Model->SettingsPath();
	const FGameKitSettingsLoad Saved = GameKit::SettingsLoadFile(Path);
	if (Saved.Problems.Num() || !FMath::IsNearlyEqual(GameKit::SettingNumber(*Saved.Settings, TEXT("audio"), TEXT("master")), TargetMaster, 1e-9)
	    || !GameKit::SettingBool(*Saved.Settings, TEXT("access"), TEXT("reduce_motion")))
	{
		return Fail(FString::Printf(TEXT("settings.json does not hold master %g and reduce_motion true: %s"), TargetMaster, *Path));
	}
	Print(TEXT("SETTINGS_WRITTEN ") + Path);
	if (!Focus(TEXT("quit")) || !Press(TEXT("ui_accept")))
	{
		return false;
	}
	if (!Model->bQuitRequested)
	{
		return Fail(TEXT("quit did not end the run"));
	}
	return true;
}

bool FGameKitShellDrive::Show(const FString& Screen)
{
	if (Screen == TEXT("title"))
	{
		if (!WaitScreen(TEXT("title")))
		{
			return false;
		}
		if (Model->Top()->Dialog.Num())
		{
			Press(TEXT("ui_cancel"));
		}
		return Frames(10);
	}
	if (Screen == TEXT("main_menu"))
	{
		return ToMenu() && Frames(5);
	}
	if (Screen == TEXT("settings"))
	{
		return ToMenu() && Open(TEXT("settings"), TEXT("settings")) && ToTab(TEXT("audio")) && Press(TEXT("ui_down"))
		       && Focus(TEXT("audio.master")) && Press(TEXT("ui_left")) && Frames(5);
	}
	if (Screen == TEXT("credits"))
	{
		return ToMenu() && Open(TEXT("credits"), TEXT("credits")) && Frames(5);
	}
	if (Screen == TEXT("loading"))
	{
		return ToMenu() && Focus(TEXT("play")) && Press(TEXT("ui_accept")) && WaitScreen(TEXT("loading"));
	}
	// the rest start in play
	if (!ToMenu() || !Open(TEXT("play"), TEXT("loading")) || !WaitScreen(TEXT("play")) || !Frames(30))
	{
		return false;
	}
	if (Screen == TEXT("subtitle"))
	{
		Model->SetFlag(TEXT("access"), TEXT("speaker_names"), true);
		Model->Say(DemoSpeaker, Model->T(DemoLineKey));
		return Frames(5);
	}
	Model->Say(DemoSpeaker, Model->T(DemoLineKey));   // so "What now?" and the history have a line
	if (!Press(TEXT("pause")) || !WaitScreen(TEXT("pause")))
	{
		return false;
	}
	if (Screen == TEXT("pause"))
	{
		return Frames(5);
	}
	return Open(Screen, Screen) && Frames(5);   // help or history
}

// ---- The accessibility sweep (#91, #85) ----------------------------------------------------------------------------
TArray<TSharedPtr<FJsonValue>> FGameKitShellDrive::Texts() const
{
	using namespace GameKitTheme;
	TArray<TSharedPtr<FJsonValue>> Out;
	const FGameKitScreen* S = Model->Top();
	if (!S)
	{
		return Out;
	}
	const double Scale = Model->TextScale();
	const bool bReadable = Model->ReadableFont();
	auto Fits = [&](const FString& Str, float Px, float Width)
	{
		const float Measured = Measure(Str, Font(Px * Scale, bReadable));
		return Measured < 0.f || Measured <= Width;
	};
	auto Add = [&](const FString& Str, float Px, const FColor& Fg, const FColor& Bg, float Width, const FString& Node)
	{
		if (!Str.IsEmpty())
		{
			Out.Add(Text(Str, Px * Scale, Fg, Bg, Fits(Str, Px, Width), Node));
		}
	};
	const float Wide = DesignW - 2 * PageMargin;
	const float MarkerW = 36.f;   // the ">" focus marker before a row's label
	auto Rows = [&](const TArray<FGameKitRow>& List, int32 Focused, float ListWidth, float LabelWidth, const FColor& Base, const FString& Prefix)
	{
		for (int32 I = 0; I < List.Num(); ++I)
		{
			const FGameKitRow& R = List[I];
			const bool bFocus = I == Focused;
			const FColor Bg = bFocus ? RowFocus : Base;
			const FString Node = Prefix + R.Id;
			Add(R.Label ? R.Label() : FString(), BodyPx, bFocus ? Accent : Text, Bg, LabelWidth - 2 * RowPadX - MarkerW, Node + TEXT(".label"));
			const float ValueW = ListWidth - LabelWidth - 2 * RowPadX;
			if (R.Kind == EGameKitRowKind::Binding && R.CellText)
			{
				for (int32 Cell = 0; Cell < 2; ++Cell)
				{
					Add(R.CellText(Cell), BodyPx, R.CellWarn && R.CellWarn(Cell) ? Warn : Text, Bg, (ValueW - RowGap) / 2,
					    Node + FString::Printf(TEXT(".slot%d"), Cell));
				}
			}
			else if (R.Value)
			{
				Add(R.Value(), BodyPx, Text, Bg, ValueW, Node + TEXT(".value"));
			}
		}
	};
	const FString Name = S->Name;
	const FString Heading = Model->Heading(*S);
	if (Name == TEXT("title"))
	{
		Add(Heading, TitlePx, Accent, Bg, Wide, TEXT("title.name"));
		Add(Model->T(TEXT("title.press_any")), BodyPx, Text, Bg, Wide, TEXT("title.prompt"));
		Add(Model->T(TEXT("title.version"), {{TEXT("version"), Model->Options().Version}}), SmallPx, Dim, Bg, Wide, TEXT("title.version"));
		if (S->Dialog.Num())
		{
			Add(Model->T(TEXT("consent.title")), HeadingPx, Text, Panel, ConsentW - 2 * PanelPad, TEXT("consent.title"));
			Out.Add(Text(Model->T(TEXT("consent.body")), BodyPx * Scale, Text, Panel, true, TEXT("consent.body")));   // wrapped
			Rows(S->Dialog, S->DialogFocus, ConsentW / 3, ConsentW / 3, Panel, TEXT("consent."));
		}
	}
	else if (Name == TEXT("main_menu"))
	{
		Add(Heading, HeadingPx, Accent, Bg, Wide, TEXT("menu.title"));
		Rows(S->Rows, S->Focus, MenuW, MenuW, Row, TEXT("menu."));
		FString Glyph, Label;
		Model->Prompt(TEXT("ui_accept"), Glyph, Label);
		Add(Label + TEXT("  ") + Model->T(TEXT("hint.select")), SmallPx, Dim, Bg, Wide, TEXT("menu.hint"));
	}
	else if (Name == TEXT("settings"))
	{
		Add(Heading, HeadingPx, Accent, Bg, Wide, TEXT("settings.title"));
		for (const FString& Tab : S->Tabs)
		{
			const bool bSelected = Tab == S->Tab();
			Add(Model->T(TEXT("settings.tab.") + Tab), SmallPx, bSelected ? Text : Dim, bSelected ? RowFocus : Row, Wide / 5, TEXT("settings.tab.") + Tab);
		}
		Rows(S->Rows, S->bOnTabs ? -1 : S->Focus, ListW, LabelW, Row, TEXT("settings.") + S->Tab() + TEXT("."));
		Add(Model->Message.IsEmpty() ? Model->T(TEXT("settings.hint")) : Model->Message, SmallPx, Model->Message.IsEmpty() ? Dim : Accent, Bg, Wide,
		    TEXT("settings.hint"));
	}
	else if (Name == TEXT("pause"))
	{
		Add(Heading, HeadingPx, Accent, Panel, MenuW, TEXT("pause.title"));
		Rows(S->Rows, S->Focus, MenuW, MenuW, Panel, TEXT("pause."));
	}
	else if (Name == TEXT("loading"))
	{
		Add(Heading, BodyPx, Text, Bg, Wide, TEXT("loading.title"));
		Add(Model->T(TEXT("value.percent"), {{TEXT("n"), TEXT("0")}}), SmallPx, Dim, Bg, Wide, TEXT("loading.percent"));
	}
	else if (Name == TEXT("help") || Name == TEXT("history") || Name == TEXT("credits"))
	{
		Add(Heading, HeadingPx, Accent, Bg, Wide, Name + TEXT(".title"));
		for (int32 I = 0; I < S->Lines.Num(); ++I)
		{
			if (!S->Lines[I].IsEmpty())
			{
				Out.Add(Text(S->Lines[I], BodyPx * Scale, Text, Bg, true, FString::Printf(TEXT("%s.line%d"), *Name, I + 1)));   // wrapped
			}
		}
		Add(Model->T(TEXT("page.hint")), SmallPx, Dim, Bg, Wide, Name + TEXT(".hint"));
	}
	if (Model->HasSubtitle() && Model->Flag(TEXT("access"), TEXT("subtitles")))
	{
		const FString Size = Model->Str(TEXT("access"), TEXT("subtitle_size"));
		const int32 Index = FMath::Max(0, StaticCast<int32>(TArray<FString>({TEXT("small"), TEXT("medium"), TEXT("large"), TEXT("xl")}).IndexOfByKey(Size)));
		const TArray<TPair<FColor, double>> Layers = {{Panel, Model->Num(TEXT("access"), TEXT("subtitle_background"))}};
		const FGameKitSaidLine& Line = Model->CurrentSubtitle();
		const FString Shown = (Model->Flag(TEXT("access"), TEXT("speaker_names")) && !Line.Speaker.IsEmpty() ? Line.Speaker + TEXT(": ") : FString()) + Line.Text;
		Out.Add(Text(Shown, SubtitlePx[Index] * Scale, Text, Panel, true, TEXT("subtitle.text"), &Layers));
	}
	return Out;
}

TSharedRef<FJsonObject> FGameKitShellDrive::Reach()
{
	TSharedRef<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("start"), Model->FocusId());
	const FGameKitScreen* S = Model->Top();
	const TArray<FGameKitRow>* List = nullptr;
	FString Prefix;
	if (S && S->Dialog.Num())
	{
		List = &S->Dialog;
		Prefix = TEXT("consent.");
	}
	else if (S && S->Rows.Num())
	{
		List = &S->Rows;
		Prefix = S->Name == TEXT("settings") ? S->Tab() + TEXT(".") : FString();
	}
	TArray<TSharedPtr<FJsonValue>> Unreached;
	TSharedRef<FJsonObject> Narration = MakeShared<FJsonObject>();
	int32 Reached = 0, Controls = 0;
	if (List)
	{
		TArray<FString> Want;
		for (const FGameKitRow& R : *List)
		{
			Want.Add(Prefix + R.Id);
			Narration->SetStringField(Prefix + R.Id, Model->Describe(R));
		}
		TSet<FString> Seen;
		for (int32 I = 0; I <= List->Num() && !bFailed; ++I)
		{
			Seen.Add(Model->FocusId());
			Press(TEXT("ui_down"));
		}
		Controls = Want.Num();
		for (const FString& Id : Want)
		{
			if (Seen.Contains(Id))
			{
				++Reached;
			}
			else
			{
				Unreached.Add(MakeString(Id));
			}
		}
	}
	Out->SetNumberField(TEXT("controls"), Controls);
	Out->SetNumberField(TEXT("reached"), Reached);
	Out->SetArrayField(TEXT("unreached"), Unreached);
	Out->SetArrayField(TEXT("focus_like_hover"), {});   // focus follows the keys only; the mouse never highlights a row
	Out->SetObjectField(TEXT("narration"), Narration);
	return Out;
}

void FGameKitShellDrive::AccessScreen(const FString& Name)
{
	TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
	R->SetStringField(TEXT("screen"), Name);
	R->SetArrayField(TEXT("design"), {MakeNumber(GameKitTheme::DesignW), MakeNumber(GameKitTheme::DesignH)});
	R->SetStringField(TEXT("scaling"), TEXT("exact"));
	R->SetArrayField(TEXT("texts"), Texts());
	R->SetObjectField(TEXT("focus"), Reach());
	Print(TEXT("ACCESS_SCREEN ") + Write(R, 0));
}

bool FGameKitShellDrive::Access(const FString& Options)
{
	double Scale = 1.0;
	bool bRead = false;
	TArray<FString> Parts;
	Options.ParseIntoArray(Parts, TEXT(","), true);
	for (const FString& Part : Parts)
	{
		if (Part == TEXT("pad"))
		{
			bPad = true;
		}
		else if (Part == TEXT("read"))
		{
			bRead = true;   // the readable font and double line spacing (#167)
		}
		else if (Part.StartsWith(TEXT("scale=")))
		{
			Scale = FCString::Atod(*Part.Mid(6));
		}
		else if (Part.StartsWith(TEXT("res=")))
		{
			Print(TEXT("DRIVE_NOTE the report is in the 1920x1080 design; the window size scales it (") + Part + TEXT(")"));
		}
		else
		{
			return Fail(TEXT("unknown access option ") + Part + TEXT(" (res=WxH, scale=N, pad, read)"));
		}
	}
	{
		TSharedRef<FJsonObject> Actions = MakeShared<FJsonObject>();
		const FGameKitBindings B = Model->Bindings();
		for (const TCHAR* A : AccessActions)
		{
			bool bKb = false, bGp = false;
			if (const TArray<FString>* Slots = B.Find(A))
			{
				for (const FString& S : *Slots)
				{
					bKb = bKb || S.StartsWith(TEXT("key:"));
					bGp = bGp || S.StartsWith(TEXT("pad:"));
				}
			}
			TSharedRef<FJsonObject> Has = MakeShared<FJsonObject>();
			Has->SetBoolField(TEXT("keyboard"), bKb);
			Has->SetBoolField(TEXT("gamepad"), bGp);
			Actions->SetObjectField(A, Has);
		}
		TSharedRef<FJsonObject> Input = MakeShared<FJsonObject>();
		Input->SetBoolField(TEXT("pad"), bPad);
		Input->SetNumberField(TEXT("text_scale"), Scale);
		Input->SetObjectField(TEXT("actions"), Actions);
		Print(TEXT("ACCESS_INPUT ") + Write(Input, 0));
	}
	if (!WaitScreen(TEXT("title")))
	{
		return false;
	}
	if (Scale != 1.0 || bRead)
	{
		Model->SetNum(TEXT("access"), TEXT("text_scale"), Scale);
		if (bRead)
		{
			Model->SetFlag(TEXT("access"), TEXT("readable_font"), true);
			Model->SetNum(TEXT("access"), TEXT("line_spacing"), 2.0);
		}
		Frames(2);
	}
	AccessScreen(TEXT("title"));
	if (Model->Top()->Dialog.Num())
	{
		Press(TEXT("ui_cancel"));
	}
	if (!Press(TEXT("ui_accept")) || !WaitScreen(TEXT("main_menu")))
	{
		return false;
	}
	AccessScreen(TEXT("main_menu"));
	if (!Open(TEXT("settings"), TEXT("settings")))
	{
		return false;
	}
	for (const TCHAR* Tab : FGameKitShellModel::SettingsTabs)
	{
		if (!ToTab(Tab))
		{
			return false;
		}
		AccessScreen(FString(TEXT("settings/")) + Tab);
		if (FCString::Strcmp(Tab, TEXT("controls")) == 0)   // the one-handed layout (#166), live, then reset
		{
			if (!Focus(TEXT("controls.preset_one_hand_left")) || !Press(TEXT("ui_accept")))
			{
				return false;
			}
			const FGameKitBindings Applied = Model->Bindings();
			const bool bApplied = Applied.Contains(TEXT("attack")) && Applied[TEXT("attack")].Num() && Applied[TEXT("attack")][0] == TEXT("key:f");
			if (!Focus(TEXT("controls.reset")) || !Press(TEXT("ui_accept")))
			{
				return false;
			}
			const FGameKitBindings Reset = Model->Bindings();
			TSharedRef<FJsonObject> P = MakeShared<FJsonObject>();
			P->SetBoolField(TEXT("applied"), bApplied);
			P->SetBoolField(TEXT("reset"), Reset.Contains(TEXT("attack")) && Reset[TEXT("attack")].Num() && Reset[TEXT("attack")][0] == TEXT("key:j"));
			Print(TEXT("ACCESS_PRESET ") + Write(P, 0));
		}
	}
	if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("main_menu")) || !Open(TEXT("credits"), TEXT("credits")))
	{
		return false;
	}
	AccessScreen(TEXT("credits"));
	if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("main_menu")) || !Open(TEXT("play"), TEXT("loading")) || !WaitScreen(TEXT("play")))
	{
		return false;
	}
	Model->Say(DemoSpeaker, Model->T(DemoLineKey));
	Frames(5);
	AccessScreen(TEXT("play"));
	{
		TSharedRef<FJsonObject> Sub = MakeShared<FJsonObject>();
		const bool bVisible = Model->HasSubtitle() && Model->Flag(TEXT("access"), TEXT("subtitles"));
		Sub->SetBoolField(TEXT("visible"), bVisible);
		Sub->SetStringField(TEXT("text"), Model->CurrentSubtitle().Text);
		Sub->SetStringField(TEXT("speaker"), Model->CurrentSubtitle().Speaker);
		Sub->SetStringField(TEXT("id"), TEXT(""));
		Print(TEXT("ACCESS_SUBTITLE ") + Write(Sub, 0));
		TSharedRef<FJsonObject> Rows = MakeShared<FJsonObject>();
		for (const TCHAR* A : PromptActions)
		{
			const FString Kb = GameKit::PromptBinding(Model->Bindings(), A, TEXT("keyboard"));
			FString Glyph, Shown;
			Model->Prompt(A, Glyph, Shown);
			TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
			Row->SetStringField(TEXT("keyboard"), Model->BindingLabel(GameKit::GlyphName(TEXT("keyboard"), Kb)));
			Row->SetStringField(TEXT("shown"), Shown);
			Rows->SetObjectField(A, Row);
		}
		TSharedRef<FJsonObject> Prompts = MakeShared<FJsonObject>();
		Prompts->SetStringField(TEXT("device"), Model->LastDevice);
		Prompts->SetStringField(TEXT("glyphs"), Model->GlyphSet());
		Prompts->SetObjectField(TEXT("actions"), Rows);
		Print(TEXT("ACCESS_PROMPTS ") + Write(Prompts, 0));
	}
	// subtitle_hold (#167), live: a finished line stays until accept, then goes
	Model->SetFlag(TEXT("access"), TEXT("subtitle_hold"), true);
	Model->Dismiss();
	Model->Say(DemoSpeaker, Model->T(DemoLineKey));
	for (int32 I = 0; I < HoldLimit && !Model->Holding() && !bFailed; ++I)
	{
		Frames(1);
	}
	const bool bHeld = Model->Holding();
	Press(TEXT("ui_accept"));
	{
		TSharedRef<FJsonObject> Hold = MakeShared<FJsonObject>();
		Hold->SetBoolField(TEXT("held"), bHeld);
		Hold->SetBoolField(TEXT("dismissed"), !Model->HasSubtitle());
		Print(TEXT("ACCESS_HOLD ") + Write(Hold, 0));
	}
	Model->SetFlag(TEXT("access"), TEXT("subtitle_hold"), false);
	if (!Press(TEXT("pause")) || !WaitScreen(TEXT("pause")))
	{
		return false;
	}
	AccessScreen(TEXT("pause"));
	for (const TCHAR* Page : {TEXT("help"), TEXT("history")})   // #167: both reachable and readable
	{
		if (!Open(Page, Page))
		{
			return false;
		}
		AccessScreen(Page);
		if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("pause")))
		{
			return false;
		}
	}
	return Open(TEXT("quit"), TEXT("title"));
}

// {{FOOTER}}
