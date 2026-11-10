// ---------------------------------------------------------------------------
// GameKitShellDrive.h
// Purpose : Scripted runs through the shell's screens (`python tools/dev.py smoke --drive <name>`): they press the
//           same actions a player would, frame by frame on the headless model, and print proof lines dev.py
//           echoes (SETTINGS_WRITTEN, ACCESS_*, DRIVE_DONE). The same scenarios, with the same names and
//           markers, as the Godot, LÖVE and web shells, so tools/access/sweep.py reads Unreal's output too.
// Usage   : menus            title -> settings: master volume 0.5, reduce motion on -> back (saves) -> quit;
//                            prints SETTINGS_WRITTEN <path> once the file holds the new values
//           show:<screen>    title | main_menu | settings | pause | help | history | credits | loading | subtitle |
//                            juice: opens it, then ends (dev.py smoke --screenshot draws it); juice hits the box and
//                            prints DRIVE_JUICE {hits, trauma, frozen, squash, flash, ...}: every primitive took
//           crash            a planted fatal error through the crash handler: CRASH_WRITTEN <path>, exit 1 (expected)
//           bug              F8 on the menu: the bug_<time>/ folder holds its files, DRIVE_BUG <path>
//           pseudo           (with --locale pseudo) every screen, each settings tab top and bottom, the rebind
//                            prompt, the juice demo: a label wider than its column or not through T() (no leading
//                            "[") prints PSEUDO_FAIL; PSEUDO_PASS when none
//           pseudo-plant     the same with one label too small for its text: must fail, naming plant.too_small
//           access[:opts]    the accessibility sweep's tour: every screen reported as ACCESS_SCREEN JSON, plus
//                            ACCESS_INPUT, ACCESS_PRESET, ACCESS_SUBTITLE, ACCESS_PROMPTS, ACCESS_HOLD;
//                            opts: res=WxH (noted; the report is in design pixels), scale=N (text), pad
//                            (gamepad buttons only), read (the readable font and double line spacing)
//           FGameKitShellDrive Drive(Model, [](const FString& L) { UE_LOG(LogGameKitShell, Display, TEXT("%s"), *L); });
//           const int32 Code = Drive.Run(TEXT("menus"));   // 0 pass, 1 fail (Drive.Error says why)
// Notes   : A run is synchronous: every wait steps the model a frame at a time (1/60 s) up to a limit, so a
//           broken menu fails instead of hanging. The access report lists each text of the top screen with its
//           size, colours and whether it fits its column (measured with Slate's font service when there is
//           one), and which rows the arrow keys reach, in the 1920x1080 design (scaling "exact": the view
//           scales the design to the window). The crash drive does not crash the editor: an unattended editor
//           crash runs Epic's crash reporter, which may send the report, so it calls the handler the engine's
//           system-error delegate calls (GameKit::ShellReport::WriteCrash) with a planted error instead.
//           Real input cannot reach a run: the drive presses its own model, which no on-screen widget feeds, and it
//           marks the model scripted, so even a widget drawn from it (the bug report's screenshot) drops real
//           keys, sticks and clicks (#276).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); crash, bug, pseudo and the juice demo by Claude
//           (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the model is marked scripted (#276)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitShellModel.h"

class GAMEKITSHELLUI_API FGameKitShellDrive
{
public:
	using FPrint = TFunction<void(const FString&)>;

	// ---- Tunables ----
	static constexpr double FrameS = 1.0 / 60.0;
	static constexpr int32 PressGap = 2;          // frames after each injected press
	static constexpr int32 WaitLimit = 900;       // frames a wait may take before the scenario fails
	static constexpr int32 FocusLimit = 40;       // presses to reach a menu item
	static constexpr int32 DriveLimit = 6000;     // frames for a whole scenario
	static constexpr int32 HoldLimit = 6000;      // frames for a subtitle to finish and hold
	static constexpr double TargetMaster = 0.5;   // menus drives the master volume here
	static constexpr int32 MaxSliderSteps = 40;
	static constexpr int32 JuiceSettleFrames = 90;   // into the juice demo before the drive attacks (the intro line is over)
	static constexpr int32 PlantWidth = 24;          // pseudo-plant: the planted label's column, in design pixels
	static const TCHAR* ShowScreens[10];          // what show:<screen> knows
	static const TCHAR* AccessActions[7];         // both devices must bind these
	static const TCHAR* PromptActions[6];         // ACCESS_PROMPTS lists these

	FGameKitShellDrive(const TSharedRef<FGameKitShellModel>& InModel, FPrint InPrint);

	/** Runs the scenario to its end and prints DRIVE_DONE <name>; the exit code (0 pass, 1 fail; Error says why). */
	int32 Run(const FString& Name);

	/** True for a name Run() knows (menus, crash, bug, pseudo, pseudo-plant, show:<screen>, access, access:<opts>). */
	static bool IsKnown(const FString& Name);
	static FString KnownNames();

	FString Error;
	bool bPad = false;                            // the access drive's gamepad-only run

private:
	TSharedRef<FGameKitShellModel> Model;
	FPrint Print;
	int32 Frame = 0;
	bool bFailed = false;

	bool Fail(const FString& Why);
	bool Frames(int32 N);
	bool WaitScreen(const FString& Name);
	bool Press(const FString& Action);
	bool Focus(const FString& Id, const FString& Step = TEXT("ui_down"));
	bool Open(const FString& Item, const FString& Screen);
	bool ToMenu();
	bool ToTab(const FString& Tab);
	bool SlideTo(const FString& What, TFunction<double()> Read, double Target);

	bool Menus();
	bool Show(const FString& Screen);
	bool Access(const FString& Options);
	bool Crash();
	bool Bug();
	bool Pseudo(bool bPlant);
	bool JuiceHit();
	void AccessScreen(const FString& Name);
	TSharedRef<FJsonObject> Reach();
	TArray<TSharedPtr<FJsonValue>> Texts() const;

	// the pseudo drive's tally
	int32 Checked = 0, Labels = 0, Problems = 0;
	bool bPlantLabel = false;
	void Check(const FString& Name);
};
