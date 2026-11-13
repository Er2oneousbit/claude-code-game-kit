// ---------------------------------------------------------------------------
// GameKitShellDrive.cpp
// Purpose : The scenarios behind GameKitShellDrive.h: menus, show:<screen>, the accessibility tour, and crash, bug,
//           pseudo and the juice demo (#275).
// Usage   : compiled into the GameKitShellUI module; run by the GameKit.Screens.Drive automation test, which
//           tools/dev.py smoke --drive starts.
// Notes   : Each helper returns false once the run has failed, and every scenario checks on the way, so a failure
//           stops the script where it happened and Error names the step. Add a scenario: a method here, its name
//           in Run() and IsKnown(), then document it in docs/ENGINE_FLOW.md. The pseudo check reads the same text
//           list as the access report (Texts()): each text's column width, measured with Slate's font service.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); crash, bug, pseudo and the juice demo by Claude
//           (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the display drive (DRIVE_DISPLAY lines; the confirm
//           must revert on the wall clock), show:apply and show:confirm, the pseudo drive's Display checks, the
//           confirm and the play HUD in the text report, disabled rows not counted as controls (#308, #309)
// ---------------------------------------------------------------------------
#include "GameKitShellDrive.h"

#include "GameKitJson.h"
#include "GameKitJuiceDemo.h"
#include "GameKitSettings.h"
#include "GameKitShellReport.h"
#include "GameKitShellTheme.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/Paths.h"

const TCHAR* FGameKitShellDrive::ShowScreens[12] = {TEXT("title"), TEXT("main_menu"), TEXT("settings"), TEXT("pause"), TEXT("help"),
                                                    TEXT("history"), TEXT("credits"), TEXT("loading"), TEXT("subtitle"), TEXT("juice"),
                                                    TEXT("apply"), TEXT("confirm")};
const TCHAR* FGameKitShellDrive::AccessActions[7] = {TEXT("ui_up"), TEXT("ui_down"), TEXT("ui_left"), TEXT("ui_right"), TEXT("ui_accept"),
                                                     TEXT("ui_cancel"), TEXT("pause")};
const TCHAR* FGameKitShellDrive::PromptActions[6] = {TEXT("move_left"), TEXT("move_right"), TEXT("jump"), TEXT("attack"), TEXT("interact"),
                                                     TEXT("pause")};

namespace
{
	using namespace GameKit::Json;

	/** Placeholder arguments for Tr: one {name} -> value pair. */
	FGameKitTrArgs Args(const TCHAR* K, const FString& V)
	{
		FGameKitTrArgs M;
		M.Add(K, V);
		return M;
	}

	// the demo line the access tour shows as a subtitle (the kit's juice demo says it on the other engines)
	const TCHAR* DemoSpeaker = TEXT("Guide");
	const TCHAR* DemoLineKey = TEXT("juice.objective");
	const TCHAR* PlantedError = TEXT("drive crash: a planted error to prove the crash report (expected)");
	const TCHAR* const BugFiles[] = {TEXT("info.txt"), TEXT("log_tail.txt"), TEXT("settings.json")};
	const TCHAR* const PseudoTabs[] = {TEXT("display"), TEXT("audio"), TEXT("controls"), TEXT("access"), TEXT("language")};

	TSharedPtr<FJsonValue> TextEntry(const FString& S, float Px, const FColor& Fg, const FColor& Back, bool bFits, const FString& Node,
	                            const TArray<TPair<FColor, double>>* OverGame = nullptr, const FColor* Outline = nullptr)
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
			O->SetStringField(TEXT("bg"), GameKitTheme::Hex(Back));
		}
		if (Outline)
		{
			O->SetStringField(TEXT("outline"), GameKitTheme::Hex(*Outline));
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
	Model->bScripted = true;   // only the drive presses: a widget on this model ignores the real devices (#276)
}

bool FGameKitShellDrive::IsKnown(const FString& Name)
{
	if (Name == TEXT("menus") || Name == TEXT("access") || Name.StartsWith(TEXT("access:")) || Name == TEXT("crash") || Name == TEXT("bug")
	    || Name == TEXT("pseudo") || Name == TEXT("pseudo-plant") || Name == TEXT("display"))
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
	return TEXT("menus, crash, bug, pseudo, pseudo-plant, display, access[:res=WxH,scale=N,pad,read], show:<") + FString::Join(Shows, TEXT("|")) + TEXT(">");
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
		Model->KeyPressed(Button, TEXT("pad_other"));   // a pad of no known make, as on the other engines
		Model->KeyReleased(Button);                      // a press, not a hold (#274)
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
	else if (Name == TEXT("crash"))
	{
		bOk = Crash();
	}
	else if (Name == TEXT("bug"))
	{
		bOk = Bug();
	}
	else if (Name == TEXT("pseudo") || Name == TEXT("pseudo-plant"))
	{
		bOk = Pseudo(Name == TEXT("pseudo-plant"));
	}
	else if (Name == TEXT("display"))
	{
		bOk = Display();
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
	if (Screen == TEXT("juice"))
	{
		return JuiceHit();
	}
	if (Screen == TEXT("apply") || Screen == TEXT("confirm"))   // #308: a Display change waiting, or its confirm
	{
		if (!ToMenu() || !Open(TEXT("settings"), TEXT("settings")) || !StageResolution() || !Focus(TEXT("display.apply")))
		{
			return false;
		}
		if (Screen == TEXT("confirm") && !Press(TEXT("ui_accept")))
		{
			return false;
		}
		return Frames(5);
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

// ---- #308: the Display tab's Apply -----------------------------------------------------------------------------------
bool FGameKitShellDrive::StageResolution()
{
	return ToTab(TEXT("display")) && Press(TEXT("ui_down")) && Focus(TEXT("display.resolution")) && Press(TEXT("ui_right"));
}

bool FGameKitShellDrive::Display()
{
	auto Setting = [this] { return Write(Find(FindObject(Model->Settings, TEXT("display")), TEXT("resolution")), 0); };
	auto Saved = [this]
	{
		const FGameKitSettingsLoad L = GameKit::SettingsLoadFile(Model->SettingsPath());
		return Write(Find(FindObject(L.Settings, TEXT("display")), TEXT("resolution")), 0);
	};
	auto Shown = [this] { return Write(Model->DisplayStaging().Value(TEXT("resolution")), 0); };
	if (!ToMenu() || !Open(TEXT("settings"), TEXT("settings")))
	{
		return false;
	}
	const FString Before = Setting();
	if (!StageResolution())
	{
		return false;
	}
	if (Shown() == Before || Setting() != Before)
	{
		return Fail(FString::Printf(TEXT("the window size row did not stage: shows %s, settings hold %s"), *Shown(), *Setting()));
	}
	Print(FString::Printf(TEXT("DRIVE_DISPLAY staged resolution %s (settings still %s)"), *Shown(), *Before));
	if (!Press(TEXT("ui_cancel")))   // Back with a change waiting: a warning, not a way out
	{
		return false;
	}
	if (Model->TopName() != TEXT("settings") || Model->Message != Model->T(TEXT("settings.unapplied")))
	{
		return Fail(FString::Printf(TEXT("Back with an unapplied Display change did not warn (screen %s)"), *Model->TopName()));
	}
	Print(TEXT("DRIVE_DISPLAY warned: ") + Model->Message);
	if (!Focus(TEXT("display.apply")) || !Press(TEXT("ui_accept")))
	{
		return false;
	}
	const TOptional<int32> Secs = Model->DisplayStaging().Seconds();
	if (!Secs.IsSet() || Setting() == Before || Saved() != Setting() || Model->FocusId() != TEXT("confirm.keep"))
	{
		return Fail(FString::Printf(TEXT("Apply did not set, save and confirm the window size (settings %s, file %s, focus %s)"),
		                            *Setting(), *Saved(), *Model->FocusId()));
	}
	const double AppliedAt = FPlatformTime::Seconds();
	const int32 AppliedFrame = Frame;
	Print(FString::Printf(TEXT("DRIVE_DISPLAY applied resolution %s, confirm %d s, focus on Keep"), *Setting(), Secs.GetValue()));
	// nobody answers: the confirm must revert by itself, on the wall clock (each frame here is a fixed 1/60 s of
	// model time, so a countdown on Update's Dt would end after 900 frames, whatever the clock says)
	while (Model->DisplayConfirming() && !bFailed)
	{
		if (FPlatformTime::Seconds() - AppliedAt > GameKit::DisplayConfirmS + RealSlackS)
		{
			return Fail(FString::Printf(TEXT("the display confirm was still open after %.1f real seconds"), FPlatformTime::Seconds() - AppliedAt));
		}
		FPlatformProcess::Sleep(RealWaitS);   // no need to spin the frames
		Frames(1);
	}
	const double Waited = FPlatformTime::Seconds() - AppliedAt;
	if (bFailed)
	{
		return false;
	}
	if (Setting() != Before || Saved() != Before)
	{
		return Fail(FString::Printf(TEXT("the confirm ran out but did not put back %s (settings %s, file %s)"), *Before, *Setting(), *Saved()));
	}
	if (Waited < GameKit::DisplayConfirmS - RealSlackS)
	{
		return Fail(FString::Printf(TEXT("the display confirm reverted after %.1f s: it must count real seconds"), Waited));
	}
	Print(FString::Printf(TEXT("DRIVE_DISPLAY reverted to %s after %.1f s real time (%d ticks)"), *Before, Waited, Frame - AppliedFrame));
	if (!StageResolution() || !Press(TEXT("ui_cancel")) || !Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("main_menu")))   // warns, then discards
	{
		return false;
	}
	if (Saved() != Before)
	{
		return Fail(TEXT("a discarded Display change reached settings.json: ") + Saved());
	}
	Print(TEXT("DRIVE_DISPLAY discarded: two Backs left the settings, the file holds ") + Before);
	return true;
}

// ---- #275: the juice demo, crash files, the bug report, the pseudo locale ------------------------------------------
bool FGameKitShellDrive::JuiceHit()
{
	if (!ToMenu())
	{
		return false;
	}
	if (!Model->Options().bDebugBuild)
	{
		return Fail(TEXT("the juice demo is in debug builds only"));
	}
	if (!Open(TEXT("juice"), TEXT("loading")) || !WaitScreen(TEXT("juice_demo")) || !Frames(JuiceSettleFrames))
	{
		return false;
	}
	if (!Press(TEXT("attack")))   // two frames later: still inside the hitstop, the flash still fading
	{
		return false;
	}
	const FGameKitJuiceDemo* J = Model->Juice();
	if (!J)
	{
		return Fail(TEXT("the juice demo did not start"));
	}
	TSharedRef<FJsonObject> R = MakeShared<FJsonObject>();
	R->SetNumberField(TEXT("hits"), J->Hits);
	R->SetNumberField(TEXT("trauma"), J->Shake.GetTrauma());
	R->SetBoolField(TEXT("frozen"), J->Hitstop.IsFrozen());
	R->SetNumberField(TEXT("squash"), J->Spring.X);
	R->SetNumberField(TEXT("flash"), J->Flash);
	R->SetNumberField(TEXT("ring"), J->Pop);
	R->SetNumberField(TEXT("camera_x"), J->Cam.GetX());
	R->SetBoolField(TEXT("on_floor"), J->bOnFloor);
	Print(TEXT("DRIVE_JUICE ") + Write(R, 0));
	if (J->Hits != 1 || J->Shake.GetTrauma() <= 0.0 || !J->Hitstop.IsFrozen() || J->Spring.X == 0.0 || J->Flash <= 0.0 || J->Pop <= 0.0)
	{
		return Fail(TEXT("the hit did not take: trauma, hitstop, squash, flash and ring must all be on (see DRIVE_JUICE)"));
	}
	return true;
}

bool FGameKitShellDrive::Crash()
{
	if (!ToMenu() || !Frames(2))
	{
		return false;
	}
	if (!GameKit::ShellReport::HasCrashTarget())
	{
		return Fail(TEXT("no crash target: the shell did not arm crash reports (FGameKitShellModel::ArmCrashReports)"));
	}
	// The handler OnHandleSystemError calls on a fatal error, with a planted one (see the header: no real crash)
	const FString Path = GameKit::ShellReport::WriteCrash(PlantedError);
	if (Path.IsEmpty() || !FPaths::FileExists(Path))
	{
		return Fail(TEXT("no crash file was written"));
	}
	return Fail(PlantedError);   // a crash fails the run, as on the other shells (dev.py says it is expected)
}

bool FGameKitShellDrive::Bug()
{
	if (!ToMenu())
	{
		return false;
	}
	if (!Model->Options().bDebugBuild)
	{
		return Fail(TEXT("the bug report key is in debug builds only"));
	}
	Model->LastBugReport.Empty();
	Model->KeyPressed(FGameKitShellModel::BugKey, TEXT("keyboard"));
	Model->KeyReleased(FGameKitShellModel::BugKey);
	if (!Frames(PressGap))
	{
		return false;
	}
	const FString Dir = Model->LastBugReport;
	if (Dir.IsEmpty())
	{
		return Fail(TEXT("F8 wrote no bug report"));
	}
	TArray<FString> Files;
	for (const TCHAR* F : BugFiles)
	{
		Files.Add(F);
	}
	if (Model->OnScreenshot)
	{
		Files.Add(TEXT("screenshot.png"));   // only when this run can draw (dev.py gives the bug drive a renderer)
	}
	for (const FString& F : Files)
	{
		if (!FPaths::FileExists(FPaths::Combine(Dir, F)))
		{
			return Fail(TEXT("the bug report lacks ") + F + TEXT(": ") + Dir);
		}
	}
	if (Model->Toast.IsEmpty())
	{
		return Fail(TEXT("no toast told the player the report was saved"));
	}
	Print(TEXT("DRIVE_BUG ") + Dir);
	return true;
}

void FGameKitShellDrive::Check(const FString& Name)
{
	using namespace GameKitTheme;
	TArray<TSharedPtr<FJsonValue>> Entries = Texts();
	if (bPlantLabel && Name == TEXT("main_menu"))
	{
		// one label too small for its text, as the LÖVE and Godot drives plant: the check must name it
		const FString S = Model->T(TEXT("menu.play"));
		const float W = Measure(S, Font(BodyPx * Model->TextScale(), Model->ReadableFont()));
		TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetStringField(TEXT("node"), TEXT("plant.too_small"));
		O->SetStringField(TEXT("text"), S);
		O->SetBoolField(TEXT("fits"), W >= 0.f && W <= PlantWidth);
		Entries.Add(MakeObject(O));
	}
	int32 Count = 0;
	TArray<FString> Found;
	for (const TSharedPtr<FJsonValue>& E : Entries)
	{
		const TSharedPtr<FJsonObject> O = E.IsValid() ? E->AsObject() : nullptr;
		const FString Text = GetString(O, TEXT("text"), FString());
		if (Text.IsEmpty())
		{
			continue;
		}
		++Count;
		const FString Node = GetString(O, TEXT("node"), TEXT("?"));
		if (!Text.StartsWith(TEXT("[")))
		{
			Found.Add(FString::Printf(TEXT("label %s: not passed through T() (\"%s\")"), *Node, *Text));
		}
		if (!GetBool(O, TEXT("fits"), true))
		{
			Found.Add(FString::Printf(TEXT("label %s: wider than its column (truncated) (\"%s\")"), *Node, *Text));
		}
	}
	++Checked;
	Labels += Count;
	Problems += Found.Num();
	Print(FString::Printf(TEXT("PSEUDO_SCREEN %s labels %d problems %d"), *Name, Count, Found.Num()));
	for (const FString& F : Found)
	{
		Print(FString::Printf(TEXT("PSEUDO_FAIL %s %s"), *Name, *F));
	}
}

bool FGameKitShellDrive::Pseudo(bool bPlant)
{
	using namespace GameKitTheme;
	bPlantLabel = bPlant;
	Checked = Labels = Problems = 0;
	if (!Model->IsPseudo())
	{
		Model->SetLocaleOverride(FGameKitShellModel::PseudoLocale);
		Print(TEXT("DRIVE_NOTE the pseudo drive switched the locale to pseudo (pass --locale pseudo next time)"));
	}
	if (Measure(TEXT("[x]"), Font(BodyPx, false)) < 0.f)
	{
		return Fail(TEXT("cannot measure text here (no Slate renderer): run it through dev.py smoke --drive pseudo"));
	}
	if (!WaitScreen(TEXT("title")))
	{
		return false;
	}
	if (Model->Top()->Dialog.Num())
	{
		Check(TEXT("consent"));
		Press(TEXT("ui_cancel"));
	}
	Check(TEXT("title"));
	if (!Press(TEXT("ui_accept")) || !WaitScreen(TEXT("main_menu")))
	{
		return false;
	}
	Check(TEXT("main_menu"));
	if (!Open(TEXT("settings"), TEXT("settings")))
	{
		return false;
	}
	for (const TCHAR* Tab : PseudoTabs)
	{
		if (!ToTab(Tab))
		{
			return false;
		}
		Check(FString(TEXT("settings.")) + Tab);
		if (!Press(TEXT("ui_down")) || !Focus(FString(Tab) + TEXT(".back")))   // the rows below the fold
		{
			return false;
		}
		Check(FString(TEXT("settings.")) + Tab + TEXT(".end"));
		if (FCString::Strcmp(Tab, TEXT("display")) == 0)   // #308: Apply enabled, then the confirm
		{
			if (!StageResolution())
			{
				return false;
			}
			Check(TEXT("settings.display.pending"));
			if (!Focus(TEXT("display.apply")) || !Press(TEXT("ui_accept")))
			{
				return false;
			}
			if (!Model->DisplayConfirming())
			{
				return Fail(TEXT("Apply on a new window size opened no confirm"));
			}
			Check(TEXT("settings.confirm"));
			if (!Press(TEXT("ui_cancel")))   // reverts at once
			{
				return false;
			}
		}
		if (FCString::Strcmp(Tab, TEXT("controls")) == 0)
		{
			if (!Focus(TEXT("controls.bind_jump")) || !Press(TEXT("ui_accept")))   // the "press a key" prompt
			{
				return false;
			}
			Check(TEXT("settings.capture"));
			Model->CancelCapture();
			Frames(PressGap);
		}
	}
	if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("main_menu")) || !Open(TEXT("credits"), TEXT("credits")))
	{
		return false;
	}
	Check(TEXT("credits"));
	if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("main_menu")))
	{
		return false;
	}
	if (Model->Options().bDebugBuild)
	{
		if (!Focus(TEXT("juice")) || !Press(TEXT("ui_accept")) || !WaitScreen(TEXT("loading")))
		{
			return false;
		}
		Check(TEXT("loading"));
		if (!WaitScreen(TEXT("juice_demo")) || !Frames(20))
		{
			return false;
		}
		Check(TEXT("juice_demo"));
		if (!Press(TEXT("attack")))
		{
			return false;
		}
		Check(TEXT("juice_demo.hit"));
		if (!Press(TEXT("pause")) || !WaitScreen(TEXT("pause")))
		{
			return false;
		}
		Check(TEXT("pause.juice"));
		if (!Open(TEXT("quit"), TEXT("title")) || !Press(TEXT("ui_accept")) || !WaitScreen(TEXT("main_menu")))
		{
			return false;
		}
	}
	if (!Open(TEXT("play"), TEXT("loading")) || !WaitScreen(TEXT("play")) || !Frames(5))
	{
		return false;
	}
	Model->Say(DemoSpeaker, Model->T(DemoLineKey));   // a subtitle line, so its text is checked too
	Frames(2);
	Check(TEXT("play"));
	if (!Press(TEXT("pause")) || !WaitScreen(TEXT("pause")))
	{
		return false;
	}
	Check(TEXT("pause"));
	for (const TCHAR* Page : {TEXT("help"), TEXT("history")})
	{
		if (!Open(Page, Page))
		{
			return false;
		}
		Check(Page);
		if (!Press(TEXT("ui_cancel")) || !WaitScreen(TEXT("pause")))
		{
			return false;
		}
	}
	if (!Open(TEXT("quit"), TEXT("title")))
	{
		return false;
	}
	if (Problems == 0)
	{
		Print(FString::Printf(TEXT("PSEUDO_PASS %d screens, %d labels, nothing truncated or untranslated"), Checked, Labels));
		return true;
	}
	Print(FString::Printf(TEXT("PSEUDO_FAILED %d problem(s) on %d screens"), Problems, Checked));
	return Fail(FString::Printf(TEXT("%d label problem(s); see the PSEUDO_FAIL lines"), Problems));
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
	auto Add = [&](const FString& Str, float Px, const FColor& Fg, const FColor& Back, float Width, const FString& Node)
	{
		if (!Str.IsEmpty())
		{
			Out.Add(TextEntry(Str, Px * Scale, Fg, Back, Fits(Str, Px, Width), Node));
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
			const FColor Back = bFocus ? Colour::RowFocus : Base;
			const FString Node = Prefix + R.Id;
			const bool bWide = R.Kind == EGameKitRowKind::Button;   // a button's label spans the row (no value column)
			Add(R.Label ? R.Label() : FString(), BodyPx, bFocus ? Colour::Accent : Colour::Text, Back, (bWide ? ListWidth : LabelWidth) - 2 * RowPadX - MarkerW,
			    Node + TEXT(".label"));
			const float ValueW = ListWidth - LabelWidth - 2 * RowPadX;
			if (R.Kind == EGameKitRowKind::Binding && R.CellText)
			{
				for (int32 Cell = 0; Cell < 2; ++Cell)
				{
					Add(R.CellText(Cell), BodyPx, R.CellWarn && R.CellWarn(Cell) ? Colour::Warn : Colour::Text, Back, (ValueW - RowGap) / 2,
					    Node + FString::Printf(TEXT(".slot%d"), Cell));
				}
			}
			else if (R.Value && !bWide)
			{
				Add(R.Value(), BodyPx, Colour::Text, Back, ValueW, Node + TEXT(".value"));
			}
		}
	};
	const FString Name = S->Name;
	const FString Heading = Model->Heading(*S);
	if (Name == TEXT("title"))
	{
		Add(Heading, TitlePx, Colour::Accent, Colour::Bg, Wide, TEXT("title.name"));
		Add(Model->T(TEXT("title.press_any")), BodyPx, Colour::Text, Colour::Bg, Wide, TEXT("title.prompt"));
		Add(Model->T(TEXT("title.version"), Args(TEXT("version"), Model->Options().Version)), SmallPx, Colour::Dim, Colour::Bg, Wide, TEXT("title.version"));
		if (S->Dialog.Num())
		{
			Add(Model->T(TEXT("consent.title")), HeadingPx, Colour::Text, Colour::Panel, ConsentW - 2 * PanelPad, TEXT("consent.title"));
			Out.Add(TextEntry(Model->T(TEXT("consent.body")), BodyPx * Scale, Colour::Text, Colour::Panel, true, TEXT("consent.body")));   // wrapped
			Rows(S->Dialog, S->DialogFocus, ConsentW - 2 * PanelPad, ConsentW - 2 * PanelPad, Colour::Panel, TEXT("consent."));
		}
	}
	else if (Name == TEXT("main_menu"))
	{
		Add(Heading, HeadingPx, Colour::Accent, Colour::Bg, Wide, TEXT("menu.title"));
		Rows(S->Rows, S->Focus, MenuW, MenuW, Colour::Row, TEXT("menu."));
		FString Glyph, Label;
		Model->Prompt(TEXT("ui_accept"), Glyph, Label);
		Add(Label + TEXT("  ") + Model->T(TEXT("hint.select")), SmallPx, Colour::Dim, Colour::Bg, Wide, TEXT("menu.hint"));
	}
	else if (Name == TEXT("settings"))
	{
		Add(Heading, HeadingPx, Colour::Accent, Colour::Bg, Wide, TEXT("settings.title"));
		for (const FString& Tab : S->Tabs)
		{
			const bool bSelected = Tab == S->Tab();
			Add(Model->T(TEXT("settings.tab.") + Tab), SmallPx, bSelected ? Colour::Text : Colour::Dim, bSelected ? Colour::RowFocus : Colour::Row, Wide / 5, TEXT("settings.tab.") + Tab);
		}
		Rows(S->Rows, S->bOnTabs || S->Dialog.Num() ? -1 : S->Focus, ListW, LabelW, Colour::Row, TEXT("settings.") + S->Tab() + TEXT("."));
		// the Display tab's hint says its changes wait for Apply (#308); as the view, SGameKitShell::Settings
		const FString HintKey = S->Tab() == TEXT("display") ? TEXT("settings.display_hint") : TEXT("settings.hint");
		Add(Model->Message.IsEmpty() ? Model->T(HintKey) : Model->Message, SmallPx, Model->Message.IsEmpty() ? Colour::Dim : Colour::Accent, Colour::Bg, Wide,
		    TEXT("settings.hint"));
		if (S->Dialog.Num())   // "Keep these display settings? Reverting in N s" (wrapped in its panel)
		{
			FGameKitTrArgs A;
			A.Add(TEXT("secs"), FString::FromInt(Model->DisplayStaging().Seconds().Get(0)));
			Out.Add(TextEntry(Model->T(TEXT("settings.confirm"), A), BodyPx * Scale, Colour::Text, Colour::Panel, true, TEXT("confirm.text")));
			Rows(S->Dialog, S->DialogFocus, ConsentW - 2 * PanelPad, ConsentW - 2 * PanelPad, Colour::Panel, TEXT("confirm."));
		}
	}
	else if (Name == TEXT("play"))
	{
		// the starter HUD's pause prompt (SGameKitShell::PlayHud, #309): a panel that grows with its text
		FString Glyph, Label;
		Model->Prompt(TEXT("pause"), Glyph, Label);
		Out.Add(TextEntry(Label + TEXT("  ") + Model->T(TEXT("hint.pause")), SmallPx * Scale, Colour::Text, Colour::Panel, true, TEXT("play.hud")));
	}
	else if (Name == TEXT("pause"))
	{
		Add(Heading, HeadingPx, Colour::Accent, Colour::Panel, MenuW, TEXT("pause.title"));
		Rows(S->Rows, S->Focus, MenuW, MenuW, Colour::Panel, TEXT("pause."));
	}
	else if (Name == TEXT("loading"))
	{
		Add(Heading, BodyPx, Colour::Text, Colour::Bg, Wide, TEXT("loading.title"));
		Add(Model->T(TEXT("value.percent"), Args(TEXT("n"), TEXT("0"))), SmallPx, Colour::Dim, Colour::Bg, Wide, TEXT("loading.percent"));
	}
	else if (Name == TEXT("help") || Name == TEXT("history") || Name == TEXT("credits"))
	{
		Add(Heading, HeadingPx, Colour::Accent, Colour::Bg, Wide, Name + TEXT(".title"));
		for (int32 I = 0; I < S->Lines.Num(); ++I)
		{
			if (!S->Lines[I].IsEmpty())
			{
				Out.Add(TextEntry(S->Lines[I], BodyPx * Scale, Colour::Text, Colour::Bg, true, FString::Printf(TEXT("%s.line%d"), *Name, I + 1)));   // wrapped
			}
		}
		Add(Model->T(TEXT("page.hint")), SmallPx, Colour::Dim, Colour::Bg, Wide, Name + TEXT(".hint"));
	}
	else if (Name == TEXT("juice_demo") && Model->Juice())
	{
		// the demo's HUD (SGameKitShell::JuiceHud): outlined text over the game, the controls and stats wrap
		const FGameKitJuiceDemo& J = *Model->Juice();
		TArray<TPair<FColor, double>> Over;
		Add(Heading, HeadingPx, Colour::Accent, Colour::Bg, Wide, TEXT("juice.title"));
		for (const TCHAR* A : PromptActions)
		{
			FString Glyph, Label;
			Model->Prompt(A, Glyph, Label);
			Out.Add(TextEntry(Label, SmallPx * Scale, Colour::Text, Colour::Panel, true, FString(TEXT("juice.glyph.")) + A));
			Out.Add(TextEntry(Model->T(FString(TEXT("action.")) + A), SmallPx * Scale, Colour::Dim, Colour::Bg, true,
			                  FString(TEXT("juice.action.")) + A, &Over, &Colour::Outline));
		}
		Out.Add(TextEntry(J.Stats(*Model), SmallPx * Scale, Colour::Dim, Colour::Bg, true, TEXT("juice.stats"), &Over, &Colour::Outline));
		if (J.bGuard)
		{
			Out.Add(TextEntry(Model->T(TEXT("juice.guard")), SmallPx * Scale, Colour::Accent, Colour::Bg, true, TEXT("juice.guard"), &Over, &Colour::Outline));
		}
	}
	if (Model->IsCapturing())
	{
		const FString Key = Model->CaptureSlot() == 0 ? TEXT("controls.press_key") : TEXT("controls.press_button");
		Out.Add(TextEntry(Model->T(Key, Args(TEXT("action"), Model->T(TEXT("action.") + Model->Capturing()))), BodyPx * Scale, Colour::Text,
		                  Colour::Panel, true, TEXT("capture.prompt")));   // wrapped in a panel that grows
		Add(Model->T(TEXT("controls.capture_cancel")), SmallPx, Colour::Dim, Colour::Panel, ConsentW, TEXT("capture.cancel"));
	}
	if (Model->HasSubtitle() && Model->Flag(TEXT("access"), TEXT("subtitles")))
	{
		const FString Size = Model->Str(TEXT("access"), TEXT("subtitle_size"));
		const int32 Index = FMath::Max(0, static_cast<int32>(TArray<FString>({TEXT("small"), TEXT("medium"), TEXT("large"), TEXT("xl")}).IndexOfByKey(Size)));
		TArray<TPair<FColor, double>> Layers;
		Layers.Emplace(Colour::Panel, Model->Num(TEXT("access"), TEXT("subtitle_background")));
		const FGameKitSaidLine& Line = Model->CurrentSubtitle();
		// the speaker as the view shows it, through subtitle.speaker ("{name}:"), then the line
		const FString Shown = (Model->Flag(TEXT("access"), TEXT("speaker_names")) && !Line.Speaker.IsEmpty()
		                           ? Model->T(TEXT("subtitle.speaker"), Args(TEXT("name"), Line.Speaker)) + TEXT(" ") : FString()) + Line.Text;
		Out.Add(TextEntry(Shown, SubtitlePx[Index] * Scale, Colour::Text, Colour::Panel, true, TEXT("subtitle.text"), &Layers, &Colour::Outline));
	}
	if (!Model->Toast.IsEmpty())
	{
		Out.Add(TextEntry(Model->Toast, SmallPx * Scale, Colour::Text, Colour::Panel, true, TEXT("toast")));   // a panel that grows
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
		Prefix = S->Name == TEXT("settings") ? TEXT("confirm.") : TEXT("consent.");
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
			if (R.IsEnabled())   // a disabled row (Apply with nothing waiting, #308) is not a control to reach
			{
				Want.Add(Prefix + R.Id);
			}
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
