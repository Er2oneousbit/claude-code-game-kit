// ---------------------------------------------------------------------------
// GameKitScreenTests.cpp
// Purpose : Tests of the shell's screens on the headless model (no window): every settings field has a row, the
//           keys walk the screens, Back saves the file, rebinding swaps, the one-handed layouts apply and reset,
//           text scale and the readable font take, a held subtitle waits for accept, "What now?" and the
//           history read back, every control says what it is, every row is reachable, hold-to-repeat timing,
//           the pad's make from its device name and the left stick as the d-pad (#267); analog stick, triggers and
//           held actions for the game (#274); the juice demo, the pseudo locale, the F8 bug report, crash files and
//           their drives (#275);
//           plus the scripted runs tools/dev.py starts: GameKit.Screens.Drive (--drive) and GameKit.Screens.Show
//           (--drive show:<screen> --screenshot).
// Usage   : python tools/dev.py test --filter GameKit.Screens          (or `test` for everything)
//           python tools/dev.py smoke --drive menus                     (GameKit.Screens.Drive with -GameKitDrive=)
//           python tools/dev.py smoke --drive show:settings --screenshot captures/settings.png
// Notes   : Each test reads data/i18n, data/input/presets.json and data/access/colours.json from the project
//           folder (they ship with every kit game) and writes settings into its own temp folder. The Drive test
//           takes -GameKitDrive=<name>, -GameKitDataDir=<folder> and -GameKitLocale=<tag> from the command line
//           (dev.py passes them) and runs `menus` into a temp folder when there are none, so `dev.py test` proves
//           the screens too. The Show test passes with a note when no -GameKitScreenshot=<path> is given, and
//           fails without a renderer when one is.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameKitAutoRepeat.h"
#include "Misc/App.h"
#include "GameKitBindings.h"
#include "GameKitSettings.h"
#include "GameKitShellCapture.h"
#include "GameKitShellDrive.h"
#include "GameKitAtomicFile.h"
#include "GameKitI18n.h"
#include "GameKitJuiceDemo.h"
#include "GameKitShellInput.h"
#include "GameKitShellLog.h"
#include "GameKitShellReport.h"
#include "GameKitShellModel.h"
#include "GameKitShellTheme.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "SGameKitShell.h"

namespace GameKitScreenTests
{
	// ---- Constants ----
	constexpr EAutomationTestFlags ScreenTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::ProductFilter;
	const FString TempFolderPrefix = FString(TEXT("gamekit-screens-")) + static_cast<TCHAR>(0x00CD);   // "I acute": narrow paths must cope
	constexpr int32 DefaultShotW = 1920, DefaultShotH = 1080;

	struct FTempFolder
	{
		FString Path;
		FTempFolder()
		{
			Path = FPaths::Combine(FPlatformProcess::UserTempDir(), TempFolderPrefix + TEXT("-") + FGuid::NewGuid().ToString());
			IFileManager::Get().MakeDirectory(*Path, true);
		}
		~FTempFolder() { IFileManager::Get().DeleteDirectory(*Path, false, true); }
		FTempFolder(const FTempFolder&) = delete;
		FTempFolder& operator=(const FTempFolder&) = delete;
	};

	/** A model on the project's data files, saving into Folder, already on the title (consent answered: Later). */
	TSharedRef<FGameKitShellModel> Fresh(const FString& Folder, bool bAnswerConsent = true)
	{
		FGameKitShellModel::FOptions Opt;
		Opt.ProjectDir = FPaths::ProjectDir();
		Opt.DataDir = Folder;
		Opt.GameName = TEXT("Test Game");
		Opt.Version = TEXT("0.0.0");
		Opt.bAutomated = true;
		TSharedRef<FGameKitShellModel> M = MakeShared<FGameKitShellModel>(Opt);
		M->Push(TEXT("title"));
		if (bAnswerConsent && M->Top()->Dialog.Num())
		{
			M->Dispatch(TEXT("ui_cancel"));
		}
		return M;
	}

	void ToMenu(FGameKitShellModel& M)
	{
		M.Dispatch(TEXT("ui_accept"));
	}

	/** Presses ui_down until the focus id is Id (at most the row count plus one). */
	bool FocusRow(FGameKitShellModel& M, const FString& Id)
	{
		for (int32 I = 0; I < 40; ++I)
		{
			if (M.FocusId() == Id)
			{
				return true;
			}
			M.Dispatch(TEXT("ui_down"));
		}
		return false;
	}

	/** Opens the settings screen from the main menu on tab Tab, focus on its first row. */
	void OpenTab(FGameKitShellModel& M, const FString& Tab)
	{
		FocusRow(M, TEXT("settings"));
		M.Dispatch(TEXT("ui_accept"));
		for (int32 I = 0; I < 6 && M.FocusId() != TEXT("tabs.") + Tab; ++I)
		{
			M.Dispatch(TEXT("ui_right"));
		}
		M.Dispatch(TEXT("ui_down"));
	}

	TArray<FString> RowIds(const FGameKitShellModel& M)
	{
		TArray<FString> Out;
		for (const FGameKitRow& R : M.Top()->Rows)
		{
			Out.Add(R.Id);
		}
		return Out;
	}

	/** One {name} -> value placeholder argument for T(). */
	FGameKitTrArgs Arg(const TCHAR* K, const FString& V)
	{
		FGameKitTrArgs A;
		A.Add(K, V);
		return A;
	}

	void Frames(FGameKitShellModel& M, int32 N)
	{
		for (int32 I = 0; I < N; ++I)
		{
			M.Update(1.0 / 60.0);
		}
	}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensSettingsRowsTest, "GameKit.Screens.SettingsRowsCoverTheSchema", ScreenTestFlags)
bool FGameKitScreensSettingsRowsTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	ToMenu(*M);
	const TSharedRef<FJsonObject> Defaults = GameKit::DefaultSettings();
	TMap<FString, FString> TabOf;   // settings section -> the tab that shows it
	TabOf.Add(TEXT("display"), TEXT("display"));
	TabOf.Add(TEXT("audio"), TEXT("audio"));
	TabOf.Add(TEXT("input"), TEXT("controls"));
	TabOf.Add(TEXT("access"), TEXT("access"));
	TabOf.Add(TEXT("telemetry"), TEXT("language"));
	TMap<FString, TArray<FString>> Rows;
	for (const TCHAR* Tab : FGameKitShellModel::SettingsTabs)
	{
		OpenTab(*M, Tab);
		Rows.Add(Tab, RowIds(*M));
		M->Dispatch(TEXT("ui_cancel"));
	}
	for (const auto& Section : TabOf)
	{
		const TSharedPtr<FJsonObject>* Fields = nullptr;
		if (!Defaults->TryGetObjectField(Section.Key, Fields))
		{
			AddError(TEXT("defaults have no section ") + Section.Key);
			continue;
		}
		for (const auto& Field : (*Fields)->Values)
		{
			const FString FieldName(*Field.Key);   // the JSON object's keys are shared strings
			if (FieldName == TEXT("bindings"))
			{
				for (const TCHAR* Action : FGameKitShellModel::GameActions)
				{
					TestTrue(FString::Printf(TEXT("controls has a row for %s"), Action), Rows[TEXT("controls")].Contains(TEXT("bind_") + FString(Action)));
				}
				continue;
			}
			TestTrue(FString::Printf(TEXT("tab %s has a row for %s.%s"), *Section.Value, *Section.Key, *FieldName), Rows[Section.Value].Contains(FieldName));
		}
	}
	TestTrue(TEXT("the language tab has the language row"), Rows[TEXT("language")].Contains(TEXT("language")));
	TestTrue(TEXT("the controls tab offers both one-handed layouts"), Rows[TEXT("controls")].Contains(TEXT("preset_one_hand_left"))
	                                                                 && Rows[TEXT("controls")].Contains(TEXT("preset_one_hand_right")));
	for (const auto& Pair : Rows)
	{
		TestEqual(TEXT("every tab ends with Back"), Pair.Value.Last(), FString(TEXT("back")));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensWalkAndSaveTest, "GameKit.Screens.KeysWalkTheScreensAndBackSaves", ScreenTestFlags)
bool FGameKitScreensWalkAndSaveTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path, false);
	TestEqual(TEXT("a first run asks about telemetry"), M->Top()->Dialog.Num(), 3);
	TestEqual(TEXT("Later has the focus"), M->FocusId(), FString(TEXT("consent.later")));
	M->KeyPressed(TEXT("key:escape"), TEXT("keyboard"));   // cancel = Later
	TestEqual(TEXT("Later keeps consent unset"), M->Str(TEXT("telemetry"), TEXT("consent")), FString(TEXT("unset")));
	TestEqual(TEXT("the title stays"), M->TopName(), FString(TEXT("title")));
	M->KeyPressed(TEXT("key:z"), TEXT("keyboard"));         // any key
	TestEqual(TEXT("any key opens the menu"), M->TopName(), FString(TEXT("main_menu")));
	TestEqual(TEXT("Play has the focus"), M->FocusId(), FString(TEXT("play")));
	M->KeyPressed(TEXT("pad:dpad_down"), TEXT("pad"));
	TestEqual(TEXT("the pad moves the focus"), M->FocusId(), FString(TEXT("settings")));
	M->KeyPressed(TEXT("pad:south"), TEXT("pad"));
	TestEqual(TEXT("south opens settings"), M->TopName(), FString(TEXT("settings")));
	TestEqual(TEXT("focus starts on the tab bar"), M->FocusId(), FString(TEXT("tabs.display")));
	M->Dispatch(TEXT("ui_right"));
	TestEqual(TEXT("right switches the tab"), M->FocusId(), FString(TEXT("tabs.audio")));
	M->Dispatch(TEXT("ui_down"));
	TestEqual(TEXT("down enters the rows"), M->FocusId(), FString(TEXT("audio.master")));
	M->Dispatch(TEXT("ui_left"));
	M->Dispatch(TEXT("ui_left"));
	TestEqual(TEXT("two steps left on master"), M->Num(TEXT("audio"), TEXT("master")), 0.8, 1e-9);
	M->Dispatch(TEXT("ui_up"));
	TestEqual(TEXT("up from the first row goes back to the tabs"), M->FocusId(), FString(TEXT("tabs.audio")));
	M->Dispatch(TEXT("ui_cancel"));
	TestEqual(TEXT("cancel leaves settings"), M->TopName(), FString(TEXT("main_menu")));
	const FGameKitSettingsLoad Saved = GameKit::SettingsLoadFile(M->SettingsPath());
	TestEqual(TEXT("the saved file is valid"), Saved.Problems.Num(), 0);
	TestEqual(TEXT("the saved file holds the new master"), GameKit::SettingNumber(*Saved.Settings, TEXT("audio"), TEXT("master")), 0.8, 1e-9);
	// play, pause, the pause pages
	FocusRow(*M, TEXT("play"));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("Play opens the loading screen"), M->TopName(), FString(TEXT("loading")));
	TestTrue(TEXT("loading swallows input"), M->Dispatch(TEXT("ui_cancel")));
	bool bPlayed = false;
	M->OnEvent = [&bPlayed](const FString& What) { bPlayed = bPlayed || What == TEXT("play"); };
	Frames(*M, 30);
	TestEqual(TEXT("loading hands over to play"), M->TopName(), FString(TEXT("play")));
	TestTrue(TEXT("the play event fired"), bPlayed);
	TestFalse(TEXT("play lets game actions through"), M->Dispatch(TEXT("jump")));
	M->KeyPressed(TEXT("key:escape"), TEXT("keyboard"));   // escape is ui_cancel and pause: play takes pause
	TestEqual(TEXT("escape pauses"), M->TopName(), FString(TEXT("pause")));
	TestEqual(TEXT("the pause menu has five rows"), M->Top()->Rows.Num(), 5);
	FocusRow(*M, TEXT("help"));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("What now? opens"), M->TopName(), FString(TEXT("help")));
	TestTrue(TEXT("without a goal it says so"), M->Top()->Lines[0] == M->T(TEXT("help.no_objective")));
	M->Dispatch(TEXT("ui_cancel"));
	FocusRow(*M, TEXT("history"));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("the history opens"), M->TopName(), FString(TEXT("history")));
	M->Dispatch(TEXT("ui_cancel"));
	FocusRow(*M, TEXT("quit"));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("Quit to title resets the stack"), M->TopName(), FString(TEXT("title")));
	TestEqual(TEXT("one screen on the stack"), M->Screens().Num(), 1);
	TestEqual(TEXT("the consent question is asked once per run"), M->Top()->Dialog.Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensRebindTest, "GameKit.Screens.RebindSwapsAndPresetsApply", ScreenTestFlags)
bool FGameKitScreensRebindTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	ToMenu(*M);
	OpenTab(*M, TEXT("controls"));
	TestTrue(TEXT("jump's row"), FocusRow(*M, TEXT("controls.bind_jump")));
	M->Dispatch(TEXT("ui_accept"));
	TestTrue(TEXT("accept starts the capture"), M->IsCapturing());
	TestEqual(TEXT("for the keyboard cell"), M->CaptureSlot(), 0);
	M->KeyPressed(TEXT("pad:north"), TEXT("pad"));
	TestTrue(TEXT("a pad button does not fill the keyboard cell"), M->IsCapturing());
	M->KeyPressed(TEXT("key:k"), TEXT("keyboard"));
	TestFalse(TEXT("a key ends the capture"), M->IsCapturing());
	TestEqual(TEXT("jump is on K"), M->Bindings()[TEXT("jump")][0], FString(TEXT("key:k")));
	TestEqual(TEXT("the message says so"), M->Message, M->T(TEXT("controls.bound"), Arg(TEXT("action"), M->T(TEXT("action.jump")))));
	// a key another action holds swaps
	M->Dispatch(TEXT("ui_accept"));
	M->KeyPressed(TEXT("key:j"), TEXT("keyboard"));   // attack's key
	TestEqual(TEXT("jump took J"), M->Bindings()[TEXT("jump")][0], FString(TEXT("key:j")));
	TestEqual(TEXT("attack got K (a swap)"), M->Bindings()[TEXT("attack")][0], FString(TEXT("key:k")));
	TestTrue(TEXT("the message names the swap"), M->Message.Contains(M->T(TEXT("action.attack"))));
	// the pad cell
	M->Dispatch(TEXT("ui_right"));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("right then accept captures the pad cell"), M->CaptureSlot(), 1);
	M->KeyPressed(TEXT("key:escape"), TEXT("keyboard"));
	TestFalse(TEXT("escape cancels the capture"), M->IsCapturing());
	TestEqual(TEXT("nothing changed on cancel"), M->Bindings()[TEXT("jump")][1], FString(TEXT("pad:south")));
	// one-handed layouts (#166)
	TestTrue(TEXT("the left layout's row"), FocusRow(*M, TEXT("controls.preset_one_hand_left")));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("attack moved to F"), M->Bindings()[TEXT("attack")][0], FString(TEXT("key:f")));
	TestEqual(TEXT("accept moved to L1"), M->Bindings()[TEXT("ui_accept")][1], FString(TEXT("pad:l1")));
	TestEqual(TEXT("the message says a layout was set"), M->Message, M->T(TEXT("controls.preset_done")));
	TestTrue(TEXT("the right layout's row"), FocusRow(*M, TEXT("controls.preset_one_hand_right")));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("attack moved to U"), M->Bindings()[TEXT("attack")][0], FString(TEXT("key:u")));
	TestTrue(TEXT("reset's row"), FocusRow(*M, TEXT("controls.reset")));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("reset gives the defaults back"), M->Bindings()[TEXT("attack")][0], FString(TEXT("key:j")));
	// the key table
	TestEqual(TEXT("space"), GameKit::ShellInput::BindingOf(EKeys::SpaceBar), FString(TEXT("key:space")));
	TestEqual(TEXT("a letter"), GameKit::ShellInput::BindingOf(EKeys::K), FString(TEXT("key:k")));
	TestEqual(TEXT("the bottom face button"), GameKit::ShellInput::BindingOf(EKeys::Gamepad_FaceButton_Bottom), FString(TEXT("pad:south")));
	TestEqual(TEXT("the left shoulder"), GameKit::ShellInput::BindingOf(EKeys::Gamepad_LeftShoulder), FString(TEXT("pad:l1")));
	TestEqual(TEXT("an axis is no binding"), GameKit::ShellInput::BindingOf(EKeys::Gamepad_LeftX), FString());
	TestTrue(TEXT("back from a string"), GameKit::ShellInput::KeyOf(TEXT("pad:start")).IsSet() && GameKit::ShellInput::KeyOf(TEXT("pad:start"))->GetFName() == TEXT("Gamepad_Special_Right"));
	TestTrue(TEXT("a letter back"), GameKit::ShellInput::KeyOf(TEXT("key:k")).IsSet() && GameKit::ShellInput::KeyOf(TEXT("key:k"))->GetFName() == TEXT("K"));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensTextTest, "GameKit.Screens.TextScaleFontAndSpacing", ScreenTestFlags)
bool FGameKitScreensTextTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	ToMenu(*M);
	OpenTab(*M, TEXT("access"));
	TestEqual(TEXT("text_scale first"), M->FocusId(), FString(TEXT("access.text_scale")));
	M->Dispatch(TEXT("ui_right"));
	TestEqual(TEXT("one step right is 1.25"), M->Num(TEXT("access"), TEXT("text_scale")), 1.25, 1e-9);
	TestEqual(TEXT("TextScale follows"), M->TextScale(), 1.25, 1e-9);
	for (int32 I = 0; I < 10; ++I)
	{
		M->Dispatch(TEXT("ui_right"));
	}
	TestEqual(TEXT("the slider stops at 200 %"), M->Num(TEXT("access"), TEXT("text_scale")), 2.0, 1e-9);
	TestEqual(TEXT("the value reads 2x"), M->Top()->Focused()->Value(), M->T(TEXT("value.times"), Arg(TEXT("n"), TEXT("2"))));
	TestTrue(TEXT("readable_font's row"), FocusRow(*M, TEXT("access.readable_font")));
	TestFalse(TEXT("off by default"), M->ReadableFont());
	M->Dispatch(TEXT("ui_accept"));
	TestTrue(TEXT("accept turns it on"), M->ReadableFont());
	const FString FontPath = GameKitTheme::ReadableFontPath();
	TestTrue(TEXT("the readable font ships with the plugin: ") + FontPath, !FontPath.IsEmpty() && FPaths::FileExists(FontPath));
	TestTrue(TEXT("the bold cut too"), FPaths::FileExists(GameKitTheme::ReadableFontPath(true)));
	const FSlateFontInfo Readable = GameKitTheme::Font(22.f, true);
	TestTrue(TEXT("Font() picks the file"), Readable.FontObject == nullptr && Readable.CompositeFont.IsValid());
	TestEqual(TEXT("22 px is 16.5 pt"), Readable.Size, 16.5f, 1e-3f);
	TestTrue(TEXT("line_spacing's row"), FocusRow(*M, TEXT("access.line_spacing")));
	M->Dispatch(TEXT("ui_right"));
	TestEqual(TEXT("one step is 1.25"), M->LineSpacing(), 1.25, 1e-9);
	TestTrue(TEXT("narration's row is there"), FocusRow(*M, TEXT("access.narration")));
	TestTrue(TEXT("timing_scale's row"), FocusRow(*M, TEXT("access.timing_scale")));
	M->Dispatch(TEXT("ui_right"));
	TestEqual(TEXT("timing steps by 0.5"), M->Num(TEXT("access"), TEXT("timing_scale")), 1.5, 1e-9);
	TestTrue(TEXT("colorblind's row"), FocusRow(*M, TEXT("access.colorblind")));
	M->Dispatch(TEXT("ui_right"));
	TestEqual(TEXT("right cycles to protanopia"), M->Str(TEXT("access"), TEXT("colorblind")), FString(TEXT("protanopia")));
	const FLinearColor Fallback(0.1f, 0.2f, 0.3f);
	TestEqual(TEXT("an unknown palette colour falls back"), M->PaletteColour(TEXT("no_such_colour"), Fallback), Fallback);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensSubtitleTest, "GameKit.Screens.SubtitleHoldHistoryAndWhatNow", ScreenTestFlags)
bool FGameKitScreensSubtitleTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	ToMenu(*M);
	FocusRow(*M, TEXT("play"));
	M->Dispatch(TEXT("ui_accept"));
	Frames(*M, 30);
	TestEqual(TEXT("in play"), M->TopName(), FString(TEXT("play")));
	M->SetObjective(TEXT("Find the key"));
	M->Say(TEXT("Guide"), TEXT("Hello there."), 1.0);
	TestTrue(TEXT("a line shows"), M->HasSubtitle());
	Frames(*M, 90);
	TestFalse(TEXT("without hold it leaves on time"), M->HasSubtitle());
	M->SetFlag(TEXT("access"), TEXT("subtitle_hold"), true);
	M->Say(TEXT("Guide"), TEXT("Take your time."), 1.0);
	Frames(*M, 90);
	TestTrue(TEXT("with hold it stays"), M->HasSubtitle());
	TestTrue(TEXT("and waits"), M->Holding());
	TestFalse(TEXT("jump does not dismiss it"), M->Dispatch(TEXT("jump")));
	M->KeyPressed(TEXT("pad:south"), TEXT("pad"));   // south is accept and jump: the line goes first
	TestFalse(TEXT("accept dismisses"), M->HasSubtitle());
	TestEqual(TEXT("two lines in the history"), M->History().Num(), 2);
	M->Dispatch(TEXT("pause"));
	FocusRow(*M, TEXT("help"));
	M->Dispatch(TEXT("ui_accept"));
	const TArray<FString>& Help = M->Top()->Lines;
	TestEqual(TEXT("the goal"), Help[0], M->T(TEXT("help.objective"), Arg(TEXT("text"), TEXT("Find the key"))));
	TestTrue(TEXT("the last line"), Help[1].Contains(TEXT("Take your time.")) && Help[1].Contains(TEXT("Guide")));
	TestEqual(TEXT("then the controls heading"), Help[2], M->T(TEXT("help.controls")));
	TestTrue(TEXT("the jump control with its pad button (the pad was used last): ") + Help[Help.Num() - 4], Help[Help.Num() - 4].Contains(M->T(TEXT("action.jump"))) && Help[Help.Num() - 4].Contains(TEXT("South")));
	M->Dispatch(TEXT("ui_cancel"));
	FocusRow(*M, TEXT("history"));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("the history lists both lines"), M->Top()->Lines.Num(), 2);
	TestTrue(TEXT("newest last"), M->Top()->Lines[1].Contains(TEXT("Take your time.")));
	TestEqual(TEXT("scrolled to the newest"), M->Top()->Scroll, 1);
	M->Dispatch(TEXT("ui_up"));
	TestEqual(TEXT("up scrolls"), M->Top()->Scroll, 0);
	for (int32 I = 0; I < 60; ++I)
	{
		M->Say(TEXT("N"), FString::FromInt(I));
	}
	TestEqual(TEXT("the history keeps the last 50"), M->History().Num(), FGameKitShellModel::MaxHistory);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensNarrationTest, "GameKit.Screens.EveryControlSaysWhatItIsAndIsReachable", ScreenTestFlags)
bool FGameKitScreensNarrationTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path, false);
	TArray<FString> Spoken;
	M->SetFlag(TEXT("access"), TEXT("narration"), true);
	M->OnNarrate = [&Spoken](const FString& Line) { Spoken.Add(Line); };
	auto CheckScreen = [&](const TArray<FGameKitRow>& Rows, const FString& Prefix)
	{
		TSet<FString> Seen;
		for (int32 I = 0; I <= Rows.Num(); ++I)
		{
			Seen.Add(M->FocusId());
			M->Dispatch(TEXT("ui_down"));
		}
		for (const FGameKitRow& R : Rows)
		{
			const FString Line = M->Describe(R);
			TestFalse(FString::Printf(TEXT("%s%s says '%s'"), *Prefix, *R.Id, *Line), Line.IsEmpty() || Line.StartsWith(TEXT("unlabelled")));
			TestTrue(FString::Printf(TEXT("%s%s is reachable with down"), *Prefix, *R.Id), Seen.Contains(Prefix + R.Id));
		}
	};
	CheckScreen(M->Top()->Dialog, TEXT("consent."));
	M->Dispatch(TEXT("ui_cancel"));
	ToMenu(*M);
	const FString ScreenRole = M->T(TEXT("narrate.screen"));
	TestTrue(TEXT("a new screen is announced"), Spoken.ContainsByPredicate([&ScreenRole](const FString& L) { return L.Contains(ScreenRole); }));
	CheckScreen(M->Top()->Rows, TEXT(""));
	for (const TCHAR* Tab : FGameKitShellModel::SettingsTabs)
	{
		OpenTab(*M, Tab);
		CheckScreen(M->Top()->Rows, FString(Tab) + TEXT("."));
		M->Dispatch(TEXT("ui_cancel"));
	}
	OpenTab(*M, TEXT("audio"));
	const FString Before = M->LastNarration;
	M->Dispatch(TEXT("ui_left"));
	TestTrue(TEXT("a changed value is said again: ") + M->LastNarration, M->LastNarration != Before && M->LastNarration.Contains(TEXT("90")));
	TestTrue(TEXT("the slider role is in it"), M->LastNarration.Contains(M->T(TEXT("narrate.slider"))));
	M->Dispatch(TEXT("ui_cancel"));
	FocusRow(*M, TEXT("play"));
	M->Dispatch(TEXT("ui_accept"));
	Frames(*M, 30);
	M->Dispatch(TEXT("pause"));
	CheckScreen(M->Top()->Rows, TEXT(""));
	TestTrue(TEXT("lines were spoken with narration on"), Spoken.Num() > 10);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensAutoRepeatTest, "GameKit.Screens.AutoRepeatTiming", ScreenTestFlags)
bool FGameKitScreensAutoRepeatTest::RunTest(const FString& Parameters)
{
	FGameKitAutoRepeat R;
	int32 Repeats = 0;
	for (int32 I = 0; I < 100; ++I)   // one second held, 10 ms steps
	{
		Repeats += R.Update(0.01, true) ? 1 : 0;
	}
	// first at 0.35 s, then every 0.15 s: 0.35, 0.50, 0.65, 0.80, 0.95
	TestEqual(TEXT("five repeats in a held second"), Repeats, 5);
	TestFalse(TEXT("release resets"), R.Update(0.01, false));
	int32 Early = 0;
	for (int32 I = 0; I < 30; ++I)
	{
		Early += R.Update(0.01, true) ? 1 : 0;
	}
	TestEqual(TEXT("nothing in the first 0.3 s after a release"), Early, 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensPadBrandTest, "GameKit.Screens.PadBrandFromDeviceName", ScreenTestFlags)
bool FGameKitScreensPadBrandTest::RunTest(const FString& Parameters)
{
	using GameKit::ShellInput::PadBrand;
	struct FCase
	{
		const TCHAR* Name;
		const TCHAR* Device;
	};
	// What Unreal's input plugins register (interface name, then hardware id) and SDL's names on Linux (#267)
	const FCase Cases[] = {
		{TEXT("XInputInterface XInputController"), TEXT("pad_xbox")},
		{TEXT("GameInput XboxOne"), TEXT("pad_xbox")},
		{TEXT("GameInput Xbox360"), TEXT("pad_xbox")},
		{TEXT("Xbox Wireless Controller"), TEXT("pad_xbox")},   // Microsoft's, despite "wireless controller"
		{TEXT("WinDualShock DualSense"), TEXT("pad_playstation")},
		{TEXT("DUALSHOCK 4"), TEXT("pad_playstation")},
		{TEXT("PS5 Controller"), TEXT("pad_playstation")},
		{TEXT("Wireless Controller"), TEXT("pad_playstation")},  // Sony's own name for the DualShock 4
		{TEXT("Nintendo Switch Pro Controller"), TEXT("pad_switch")},
		{TEXT("Joy-Con (L/R)"), TEXT("pad_switch")},
		{TEXT("GameInput Hid"), TEXT("pad_other")},
		{TEXT("8BitDo Pro 2"), TEXT("pad_other")},
		{TEXT(""), TEXT("pad_other")},                           // a device the registry does not know
	};
	for (const FCase& C : Cases)
	{
		TestEqual(FString::Printf(TEXT("\"%s\""), C.Name), PadBrand(C.Name), FString(C.Device));
	}
	TestEqual(TEXT("an unknown device id has no name"), GameKit::ShellInput::PadName(FInputDeviceId()), FString());
	TestEqual(TEXT("a pad button from an unknown device is pad_other"),
	          GameKit::ShellInput::DeviceOf(EKeys::Gamepad_FaceButton_Bottom), FString(TEXT("pad_other")));
	TestEqual(TEXT("a key stays the keyboard"), GameKit::ShellInput::DeviceOf(EKeys::SpaceBar), FString(TEXT("keyboard")));
	// the make picks the prompt set
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	const FCase Sets[] = {   // Name = the device, Device = the glyph set it shows
		{TEXT("pad_xbox"), TEXT("xbox")}, {TEXT("pad_playstation"), TEXT("playstation")},
		{TEXT("pad_switch"), TEXT("generic")}, {TEXT("pad_other"), TEXT("generic")}, {TEXT("keyboard"), TEXT("keyboard")},
	};
	for (const FCase& S : Sets)
	{
		M->LastDevice = S.Name;
		TestEqual(FString::Printf(TEXT("%s shows the %s prompts"), S.Name, S.Device), M->GlyphSet(), FString(S.Device));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensStickTest, "GameKit.Screens.LeftStickMovesFocusWithHysteresis", ScreenTestFlags)
bool FGameKitScreensStickTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	M->StickMoved(TEXT("y"), -0.9, TEXT("pad_playstation"));   // the title: a push is "any button"
	TestEqual(TEXT("a stick push leaves the title"), M->TopName(), FString(TEXT("main_menu")));
	M->StickMoved(TEXT("y"), 0.0, TEXT("pad_playstation"));
	TestEqual(TEXT("Play has the focus"), M->FocusId(), FString(TEXT("play")));
	M->StickMoved(TEXT("y"), -0.6, TEXT("pad_playstation"));
	TestEqual(TEXT("down on the stick moves the focus down"), M->FocusId(), FString(TEXT("settings")));
	TestEqual(TEXT("the stick's pad picks the prompts"), M->GlyphSet(), FString(TEXT("playstation")));
	// held, and wavering around the press point: no repeat until it comes back under StickOff
	for (const double V : {-0.9, -0.45, -0.55, -0.35, -0.6, -0.31, -1.0})
	{
		M->StickMoved(TEXT("y"), V, TEXT("pad_playstation"));
	}
	TestEqual(TEXT("a held, wavering stick moves once"), M->FocusId(), FString(TEXT("settings")));
	M->StickMoved(TEXT("y"), -0.25, TEXT("pad_playstation"));   // released
	M->StickMoved(TEXT("y"), -0.55, TEXT("pad_playstation"));   // pushed again
	TestNotEqual(TEXT("a second push moves again"), M->FocusId(), FString(TEXT("settings")));
	M->StickMoved(TEXT("y"), 0.0, TEXT("pad_playstation"));
	M->StickMoved(TEXT("y"), 0.7, TEXT("pad_playstation"));     // up (Unreal's LeftY is positive up)
	TestEqual(TEXT("up on the stick moves the focus back"), M->FocusId(), FString(TEXT("settings")));
	M->StickMoved(TEXT("y"), 0.0, TEXT("pad_playstation"));
	TestTrue(TEXT("the stick at rest does nothing"), !M->StickMoved(TEXT("y"), 0.1, TEXT("pad_playstation")));
	// left and right on the settings tabs
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("settings open on the tab bar"), M->FocusId(), FString(TEXT("tabs.display")));
	M->StickMoved(TEXT("x"), 0.8, TEXT("pad_xbox"));
	M->StickMoved(TEXT("x"), 0.4, TEXT("pad_xbox"));
	M->StickMoved(TEXT("x"), 0.9, TEXT("pad_xbox"));
	TestEqual(TEXT("right on the stick switches the tab once"), M->FocusId(), FString(TEXT("tabs.audio")));
	M->StickMoved(TEXT("x"), 0.0, TEXT("pad_xbox"));
	M->StickMoved(TEXT("x"), -0.8, TEXT("pad_xbox"));
	TestEqual(TEXT("left on the stick switches back"), M->FocusId(), FString(TEXT("tabs.display")));
	M->StickMoved(TEXT("x"), 0.0, TEXT("pad_xbox"));
	// a wide deadzone raises the press point
	M->SetNum(TEXT("input"), TEXT("deadzone"), 0.8);
	M->StickMoved(TEXT("x"), 0.7, TEXT("pad_xbox"));
	TestEqual(TEXT("inside a 0.8 deadzone the stick does nothing"), M->FocusId(), FString(TEXT("tabs.display")));
	M->StickMoved(TEXT("x"), 0.0, TEXT("pad_xbox"));
	M->StickMoved(TEXT("x"), 0.85, TEXT("pad_xbox"));
	TestEqual(TEXT("past the deadzone it moves"), M->FocusId(), FString(TEXT("tabs.audio")));
	TestFalse(TEXT("the right stick and other axes are not menu input"), M->StickMoved(TEXT("z"), 1.0, TEXT("pad_xbox")));
	return true;
}

/** A model like Fresh(), as a debug build (the juice demo, the pseudo language, F8). */
TSharedRef<FGameKitShellModel> FreshDebug(const FString& Folder)
{
	FGameKitShellModel::FOptions Opt;
	Opt.ProjectDir = FPaths::ProjectDir();
	Opt.DataDir = Folder;
	Opt.GameName = TEXT("Test Game");
	Opt.Version = TEXT("1.2.3");
	Opt.bAutomated = true;
	Opt.bDebugBuild = true;
	TSharedRef<FGameKitShellModel> M = MakeShared<FGameKitShellModel>(Opt);
	M->Push(TEXT("title"));
	if (M->Top()->Dialog.Num())
	{
		M->Dispatch(TEXT("ui_cancel"));
	}
	return M;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensAnalogTest, "GameKit.Screens.AnalogStickTriggersAndHeldActions", ScreenTestFlags)
bool FGameKitScreensAnalogTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = Fresh(Folder.Path);
	M->SetNum(TEXT("input"), TEXT("deadzone"), 0.2);
	ToMenu(*M);
	M->StickMoved(TEXT("x"), 0.6, TEXT("pad_xbox"));        // the main menu: right does nothing on a button row
	M->TriggerMoved(true, 0.525);
	M->KeyPressed(TEXT("key:space"), TEXT("keyboard"));   // jump: no menu use, and space stays down
	TestEqual(TEXT("still the main menu"), M->TopName(), FString(TEXT("main_menu")));
	TestTrue(TEXT("on the menus the stick reads zero"), M->Stick().IsZero());
	TestEqual(TEXT("and the triggers"), M->Trigger(true), 0.0);
	TestEqual(TEXT("and nothing is held for the game"), M->HeldActions().Num(), 0);
	M->KeyReleased(TEXT("key:space"));
	M->StickMoved(TEXT("x"), 0.0, TEXT("pad_xbox"));
	FocusRow(*M, TEXT("play"));
	M->Dispatch(TEXT("ui_accept"));
	Frames(*M, 30);
	TestTrue(TEXT("in play the game has the input"), M->GameActive());
	M->StickMoved(TEXT("x"), 0.6, TEXT("pad_xbox"));
	TestEqual(TEXT("0.6 with a 0.2 deadzone is 0.5 (radial, rescaled)"), M->Stick().X, 0.5, 1e-6);
	M->StickMoved(TEXT("y"), 0.15, TEXT("pad_xbox"));
	TestTrue(TEXT("the stick's direction is kept"), M->Stick().Y > 0.0 && M->Stick().Y < M->Stick().X);
	M->SetFlag(TEXT("input"), TEXT("invert_y"), true);
	TestTrue(TEXT("invert_y flips up"), M->Stick().Y < 0.0);
	M->SetFlag(TEXT("input"), TEXT("invert_y"), false);
	TestEqual(TEXT("the right trigger halfway past its deadzone is 0.5"), M->Trigger(true), 0.5, 1e-6);
	TestEqual(TEXT("the left one rests"), M->Trigger(false), 0.0);
	TestTrue(TEXT("the stick leaning right holds move_right"), M->IsHeld(TEXT("move_right")));
	TestFalse(TEXT("a small lean up does not hold move_up"), M->IsHeld(TEXT("move_up")));
	M->KeyPressed(TEXT("key:space"), TEXT("keyboard"));
	M->KeyPressed(TEXT("pad:west"), TEXT("pad_xbox"));
	TArray<FString> Held = M->HeldActions();
	TestTrue(TEXT("space holds jump: ") + FString::Join(Held, TEXT(",")), Held.Contains(TEXT("jump")));
	TestFalse(TEXT("no ui_* action is a held game action"), Held.ContainsByPredicate([](const FString& A) { return A.StartsWith(TEXT("ui_")); }));
	TestTrue(TEXT("sorted"), Held == [&Held] { TArray<FString> S = Held; S.Sort(); return S; }());
	M->KeyReleased(TEXT("key:space"));
	TestFalse(TEXT("released, jump is no longer held"), M->IsHeld(TEXT("jump")));
	// the stick's own d-pad presses (menu focus) never become held d-pad buttons
	M->StickMoved(TEXT("y"), -0.9, TEXT("pad_xbox"));
	M->StickMoved(TEXT("y"), 0.0, TEXT("pad_xbox"));
	M->StickMoved(TEXT("x"), 0.0, TEXT("pad_xbox"));
	TestFalse(TEXT("a stick back at rest holds no move_down"), M->IsHeld(TEXT("move_down")));
	M->Dispatch(TEXT("pause"));
	TestEqual(TEXT("paused: zero again"), M->Trigger(true), 0.0);
	M->Dispatch(TEXT("pause"));
	M->ReleaseAll();
	TestEqual(TEXT("ReleaseAll lets everything go"), M->HeldActions().Num(), 0);
	TestEqual(TEXT("and the trigger"), M->Trigger(true), 0.0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensJuiceTest, "GameKit.Screens.JuiceDemo", ScreenTestFlags)
bool FGameKitScreensJuiceTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> Release = Fresh(Folder.Path);
	ToMenu(*Release);
	TestFalse(TEXT("a release build has no juice demo"), RowIds(*Release).Contains(TEXT("juice")));
	TSharedRef<FGameKitShellModel> M = FreshDebug(Folder.Path);
	ToMenu(*M);
	TestTrue(TEXT("a debug build lists the juice demo"), FocusRow(*M, TEXT("juice")));
	M->Dispatch(TEXT("ui_accept"));
	TestEqual(TEXT("through the loading screen"), M->TopName(), FString(TEXT("loading")));
	Frames(*M, 30);
	TestEqual(TEXT("into the demo"), M->TopName(), FString(TEXT("juice_demo")));
	const FGameKitJuiceDemo* J = M->Juice();
	if (!TestNotNull(TEXT("the demo runs"), J))
	{
		return false;
	}
	TestEqual(TEXT("its goal is set for What now?"), M->Objective, M->T(TEXT("juice.objective")));
	TestTrue(TEXT("the guide says it"), M->HasSubtitle());
	TestTrue(TEXT("attack is the demo's"), M->Dispatch(TEXT("attack")));
	TestEqual(TEXT("the box was in reach"), J->Hits, 1);
	TestTrue(TEXT("trauma"), J->Shake.GetTrauma() > 0.0);
	TestTrue(TEXT("hitstop"), J->Hitstop.IsFrozen());
	TestTrue(TEXT("squash"), J->Spring.X > 0.0);
	TestTrue(TEXT("a flash"), J->Flash > 0.0);
	const double Squash = J->Spring.X;
	Frames(*M, 2);
	TestEqual(TEXT("the hitstop freezes game time: the spring waits"), J->Spring.X, Squash, 1e-12);
	Frames(*M, 30);
	TestTrue(TEXT("after it the spring moves"), J->Spring.X != Squash);
	for (int32 I = 0; I < 4; ++I)
	{
		M->Dispatch(TEXT("attack"));
	}
	TestTrue(TEXT("the flash limiter holds some flashes back"), J->Refused > 0);
	M->Dispatch(TEXT("jump"));
	Frames(*M, 15);   // past the last hitstop, still rising
	TestTrue(TEXT("a buffered jump leaves the floor"), J->Jumps == 1 && !J->bOnFloor);
	M->KeyPressed(TEXT("key:d"), TEXT("keyboard"));   // move_right held
	const double X0 = J->PX;
	Frames(*M, 20);
	TestTrue(TEXT("a held move_right walks right"), J->PX > X0);
	M->KeyReleased(TEXT("key:d"));
	M->SetFlag(TEXT("access"), TEXT("reduce_motion"), true);
	M->Dispatch(TEXT("attack"));
	Frames(*M, 10);
	TestEqual(TEXT("reduce motion: no shake offset"), J->Offset.X, 0.0);
	M->Dispatch(TEXT("pause"));
	TestEqual(TEXT("pause opens over the demo"), M->TopName(), FString(TEXT("pause")));
	const double Frozen = J->RealTime;
	Frames(*M, 10);
	TestEqual(TEXT("paused, the demo does not run"), J->RealTime, Frozen);
	FocusRow(*M, TEXT("quit"));
	M->Dispatch(TEXT("ui_accept"));
	TestNull(TEXT("quit to title ends the demo"), M->Juice());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensPseudoTest, "GameKit.Screens.PseudoLocale", ScreenTestFlags)
bool FGameKitScreensPseudoTest::RunTest(const FString& Parameters)
{
	FTempFolder Folder;
	TSharedRef<FGameKitShellModel> M = FreshDebug(Folder.Path);
	TestTrue(TEXT("a debug build offers the pseudo language"), M->Locales().Contains(TEXT("pseudo")));
	TestFalse(TEXT("a release build does not"), Fresh(Folder.Path)->Locales().Contains(TEXT("pseudo")));
	M->SetLocaleOverride(TEXT("pseudo"));
	const FString Play = M->T(TEXT("menu.play"));
	TestTrue(TEXT("in brackets: ") + Play, Play.StartsWith(TEXT("[")) && Play.EndsWith(TEXT("]")));
	TestEqual(TEXT("GameKit::Pseudo of the English text"), Play, GameKit::Pseudo(TEXT("Play")));
	const FString Title = M->T(TEXT("title.name"), Arg(TEXT("name"), TEXT("Test Game")));
	TestTrue(TEXT("a placeholder is filled after, not accented: ") + Title, Title.Contains(TEXT("Test Game")) && Title.StartsWith(TEXT("[")));
	TestEqual(TEXT("a missing key comes back bare, so the check flags it"), M->T(TEXT("no.such.key")), FString(TEXT("no.such.key")));
	TestTrue(TEXT("a made-up value is bracketed too"), M->Content(TEXT("42")).StartsWith(TEXT("[")));
	M->SetLocaleOverride(FString());
	TestEqual(TEXT("back to English"), M->T(TEXT("menu.play")), FString(TEXT("Play")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensReportTest, "GameKit.Screens.BugReportAndCrashFile", ScreenTestFlags)
bool FGameKitScreensReportTest::RunTest(const FString& Parameters)
{
	using namespace GameKit::ShellReport;
	FTempFolder Folder;
	{
		TSharedRef<FGameKitShellModel> Release = Fresh(Folder.Path);
		ToMenu(*Release);
		Release->KeyPressed(FGameKitShellModel::BugKey, TEXT("keyboard"));
		TestTrue(TEXT("F8 does nothing in a release build"), Release->LastBugReport.IsEmpty());
	}
	TSharedRef<FGameKitShellModel> M = FreshDebug(Folder.Path);
	FString Shot;
	M->OnScreenshot = [&Shot](const FString& Path) { Shot = Path; };
	AddLogLine(TEXT("LogTemp: Display: a line before the report"));
	M->KeyPressed(FGameKitShellModel::BugKey, TEXT("keyboard"));
	TestEqual(TEXT("F8 is never 'any key' on the title"), M->TopName(), FString(TEXT("title")));
	const FString Dir = M->LastBugReport;
	TestTrue(TEXT("a bug_<time> folder in the data folder: ") + Dir, FPaths::GetCleanFilename(Dir).StartsWith(TEXT("bug_")) && FPaths::DirectoryExists(Dir));
	for (const TCHAR* F : {TEXT("info.txt"), TEXT("log_tail.txt"), TEXT("settings.json")})
	{
		TestTrue(FString::Printf(TEXT("it holds %s"), F), FPaths::FileExists(FPaths::Combine(Dir, F)));
	}
	TestEqual(TEXT("the screenshot is asked for inside it"), Shot, FPaths::Combine(Dir, TEXT("screenshot.png")));
	const TOptional<FString> Info = GameKit::ReadTextFile(FPaths::Combine(Dir, TEXT("info.txt")));
	TestTrue(TEXT("info names the version and the screen"), Info.IsSet() && Info->Contains(TEXT("1.2.3")) && Info->Contains(TEXT("screen: title")));
	const TOptional<FString> Tail = GameKit::ReadTextFile(FPaths::Combine(Dir, TEXT("log_tail.txt")));
	TestTrue(TEXT("the log tail holds the line"), Tail.IsSet() && Tail->Contains(TEXT("a line before the report")));
	TestEqual(TEXT("a toast says so"), M->Toast, M->T(TEXT("toast.bug_saved")));
	M->KeyPressed(FGameKitShellModel::BugKey, TEXT("keyboard"));
	TestNotEqual(TEXT("a second report in the same second gets its own folder"), M->LastBugReport, Dir);
	Frames(*M, 200);
	TestTrue(TEXT("the toast goes"), M->Toast.IsEmpty());
	// crash files
	TestEqual(TEXT("no target, no crash file"), WriteCrash(TEXT("boom")), FString());
	M->ArmCrashReports();
	M->SetNum(TEXT("audio"), TEXT("master"), 0.3);   // the snapshot follows the settings
	const FString Crash = WriteCrash(TEXT("boom"));
	TestTrue(TEXT("crashes/crash_<time>.txt: ") + Crash, Crash.Contains(TEXT("/crashes/crash_")) && FPaths::FileExists(Crash));
	const TOptional<FString> Text = GameKit::ReadTextFile(Crash);
	TestTrue(TEXT("version, error, log tail, settings"), Text.IsSet() && Text->Contains(TEXT("version: 1.2.3")) && Text->Contains(TEXT("error: boom"))
	                                                     && Text->Contains(TEXT("a line before the report")) && Text->Contains(TEXT("0.3")));
	TestNotEqual(TEXT("a second crash in the same second gets its own name"), WriteCrash(TEXT("again")), Crash);
	const FString Pure = CrashText({TEXT("D"), TEXT("Game"), TEXT("9"), TEXT("{}")}, FString(), FString(), TEXT("now"));
	TestTrue(TEXT("an empty error and tail still read"), Pure.Contains(TEXT("(no log lines)")) && Pure.Contains(TEXT("error: (none given")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensNewDrivesTest, "GameKit.Screens.ScenariosCrashBugJuicePseudo", ScreenTestFlags)
bool FGameKitScreensNewDrivesTest::RunTest(const FString& Parameters)
{
	auto RunDrive = [](const FString& Folder, const FString& Name, TArray<FString>& Lines, bool bArm = true)
	{
		TSharedRef<FGameKitShellModel> M = MakeShared<FGameKitShellModel>([&Folder] {
			FGameKitShellModel::FOptions Opt;
			Opt.ProjectDir = FPaths::ProjectDir();
			Opt.DataDir = Folder;
			Opt.GameName = TEXT("Test Game");
			Opt.Version = TEXT("1.2.3");
			Opt.bAutomated = true;
			Opt.bDebugBuild = true;
			return Opt;
		}());
		if (bArm)
		{
			M->ArmCrashReports();
		}
		FGameKitShellDrive Drive(M, [&Lines](const FString& L) { Lines.Add(L); });
		return Drive.Run(Name);
	};
	auto Has = [](const TArray<FString>& Lines, const FString& Start)
	{
		return Lines.ContainsByPredicate([&Start](const FString& L) { return L.StartsWith(Start); });
	};
	FTempFolder Folder;
	TArray<FString> Lines;
	TestEqual(TEXT("crash fails on purpose"), RunDrive(Folder.Path, TEXT("crash"), Lines), 1);
	TestTrue(TEXT("with a crash file"), Has(Lines, TEXT("DRIVE_FAIL drive crash: a planted error")));
	TArray<FString> Crashes;
	IFileManager::Get().FindFiles(Crashes, *FPaths::Combine(Folder.Path, TEXT("crashes"), TEXT("crash_*.txt")), true, false);
	TestEqual(TEXT("one crash file"), Crashes.Num(), 1);
	Lines.Empty();
	TestEqual(TEXT("crash without an armed shell names that"), RunDrive(Folder.Path, TEXT("crash"), Lines, false), 1);
	TestTrue(TEXT("no target"), Has(Lines, TEXT("DRIVE_FAIL no crash target")));
	Lines.Empty();
	TestEqual(TEXT("bug passes"), RunDrive(Folder.Path, TEXT("bug"), Lines), 0);
	TestTrue(TEXT("DRIVE_BUG <folder>"), Has(Lines, TEXT("DRIVE_BUG ")));
	Lines.Empty();
	TestEqual(TEXT("show:juice passes"), RunDrive(Folder.Path, TEXT("show:juice"), Lines), 0);
	TestTrue(TEXT("DRIVE_JUICE"), Has(Lines, TEXT("DRIVE_JUICE {")));
	if (GameKitTheme::Measure(TEXT("[x]"), GameKitTheme::Font(GameKitTheme::BodyPx, false)) < 0.f)
	{
		AddInfo(TEXT("no Slate renderer here: the pseudo drives are checked by dev.py smoke --drive pseudo"));
		return true;
	}
	Lines.Empty();
	const int32 Pseudo = RunDrive(Folder.Path, TEXT("pseudo"), Lines);
	for (const FString& L : Lines)
	{
		if (L.StartsWith(TEXT("PSEUDO_FAIL")))
		{
			AddError(L);
		}
	}
	TestEqual(TEXT("pseudo passes"), Pseudo, 0);
	TestTrue(TEXT("PSEUDO_PASS"), Has(Lines, TEXT("PSEUDO_PASS ")));
	Lines.Empty();
	TestEqual(TEXT("pseudo-plant fails on purpose"), RunDrive(Folder.Path, TEXT("pseudo-plant"), Lines), 1);
	TestTrue(TEXT("naming the planted label"), Has(Lines, TEXT("PSEUDO_FAIL main_menu label plant.too_small")));
	return true;
}

/** The marker lines a drive prints: Display level, so the log holds them for tools/dev.py. */
void PrintLine(const FString& Line)
{
	UE_LOG(LogGameKitShell, Display, TEXT("%s"), *Line);
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensDriveTest, "GameKit.Screens.Drive", ScreenTestFlags)
bool FGameKitScreensDriveTest::RunTest(const FString& Parameters)
{
	FString Name = TEXT("menus"), DataDir, Locale;
	FParse::Value(FCommandLine::Get(), TEXT("GameKitDrive="), Name, /*bShouldStopOnSeparator*/ false);
	FParse::Value(FCommandLine::Get(), TEXT("GameKitDataDir="), DataDir, /*bShouldStopOnSeparator*/ false);
	FParse::Value(FCommandLine::Get(), TEXT("GameKitLocale="), Locale, /*bShouldStopOnSeparator*/ false);
	if (!FGameKitShellDrive::IsKnown(Name))
	{
		AddError(FString::Printf(TEXT("unknown drive %s (%s)"), *Name, *FGameKitShellDrive::KnownNames()));
		return false;
	}
	TUniquePtr<FTempFolder> Temp;
	if (DataDir.IsEmpty())
	{
		Temp = MakeUnique<FTempFolder>();
		DataDir = Temp->Path;
	}
	FGameKitShellModel::FOptions Opt;
	Opt.ProjectDir = FPaths::ProjectDir();
	Opt.DataDir = DataDir;
	Opt.GameName = FApp::GetProjectName();
	Opt.Version = TEXT("dev");
	Opt.Locale = Locale;
	Opt.bAutomated = true;
	Opt.bDebugBuild = true;   // the juice demo, the pseudo language and F8, as in the editor and development builds
	TSharedRef<FGameKitShellModel> M = MakeShared<FGameKitShellModel>(Opt);
	M->ArmCrashReports();     // crash files go to the drive's data folder (#275)
	if (GameKit::ShellCapture::CanCapture())
	{
		// the bug report's screenshot: the shell drawn off-screen (dev.py gives the bug drive a renderer)
		TWeakPtr<FGameKitShellModel> Weak = M;
		M->OnScreenshot = [Weak](const FString& Path)
		{
			if (const TSharedPtr<FGameKitShellModel> Model = Weak.Pin())
			{
				FString Error;
				if (!GameKit::ShellCapture::SavePng(SNew(SGameKitShell, Model.ToSharedRef()), FIntPoint(DefaultShotW, DefaultShotH), Path, Error))
				{
					UE_LOG(LogGameKitShell, Error, TEXT("bug report screenshot: %s"), *Error);
				}
			}
		};
	}
	FGameKitShellDrive Drive(M, &PrintLine);
	const int32 Code = Drive.Run(Name);
	if (Code != 0)
	{
		AddError(FString::Printf(TEXT("drive %s failed: %s"), *Name, *Drive.Error));
	}
	return Code == 0;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FGameKitScreensShowTest, "GameKit.Screens.Show", ScreenTestFlags)
bool FGameKitScreensShowTest::RunTest(const FString& Parameters)
{
	FString Shot, Name = TEXT("show:title"), Size;
	if (!FParse::Value(FCommandLine::Get(), TEXT("GameKitScreenshot="), Shot, /*bShouldStopOnSeparator*/ false) || Shot.IsEmpty())
	{
		AddInfo(TEXT("no -GameKitScreenshot=<path>: nothing to draw (dev.py smoke --drive show:<screen> --screenshot gives one)"));
		return true;
	}
	FParse::Value(FCommandLine::Get(), TEXT("GameKitDrive="), Name, /*bShouldStopOnSeparator*/ false);
	if (!Name.StartsWith(TEXT("show:")) || !FGameKitShellDrive::IsKnown(Name))
	{
		AddError(FString::Printf(TEXT("a screenshot needs -GameKitDrive=show:<screen> (%s)"), *FGameKitShellDrive::KnownNames()));
		return false;
	}
	FIntPoint Dim(DefaultShotW, DefaultShotH);
	if (FParse::Value(FCommandLine::Get(), TEXT("GameKitSize="), Size, /*bShouldStopOnSeparator*/ false))
	{
		FString W, H;
		if (Size.Split(TEXT("x"), &W, &H))
		{
			Dim = FIntPoint(FCString::Atoi(*W), FCString::Atoi(*H));
		}
	}
	if (!GameKit::ShellCapture::CanCapture())
	{
		AddError(TEXT("no renderer for the screenshot: the editor must run without -NullRHI (dev.py adds -RenderOffScreen)"));
		return false;
	}
	FTempFolder Temp;
	FGameKitShellModel::FOptions Opt;
	Opt.ProjectDir = FPaths::ProjectDir();
	Opt.DataDir = Temp.Path;
	Opt.GameName = FApp::GetProjectName();
	Opt.Version = TEXT("dev");
	FParse::Value(FCommandLine::Get(), TEXT("GameKitLocale="), Opt.Locale, /*bShouldStopOnSeparator*/ false);
	Opt.bAutomated = true;
	Opt.bDebugBuild = true;   // show:juice
	TSharedRef<FGameKitShellModel> M = MakeShared<FGameKitShellModel>(Opt);
	FGameKitShellDrive Drive(M, &PrintLine);
	if (Drive.Run(Name) != 0)
	{
		AddError(TEXT("the drive failed before the capture: ") + Drive.Error);
		return false;
	}
	TSharedRef<SGameKitShell> Widget = SNew(SGameKitShell, M);
	FString Error;
	if (!GameKit::ShellCapture::SavePng(Widget, Dim, Shot, Error))
	{
		AddError(TEXT("screenshot failed: ") + Error);
		return false;
	}
	UE_LOG(LogGameKitShell, Display, TEXT("SCREENSHOT_WRITTEN %s"), *Shot);
	return true;
}

} // namespace GameKitScreenTests

#endif // WITH_DEV_AUTOMATION_TESTS

// {{FOOTER}}
