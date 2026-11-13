// ---------------------------------------------------------------------------
// GameKitShellModel.h
// Purpose : The shell's screens as data, with no widget in sight: a stack of screens (title, main menu,
//           settings with its five tabs, loading, play, pause, "What now?", dialogue history, credits), each a
//           list of rows (buttons, toggles, sliders, choices, bindings) with a focus, driven by the actions a
//           player presses (ui_up, ui_accept, pause ...). It reads and writes the player's settings through
//           GameKitSettings.h, rebinds through GameKitBindings.h, translates through GameKitI18n.h, keeps
//           the subtitle line, the dialogue history and the goal for "What now?", and says what the focused
//           control is (menu narration). SGameKitShell draws whatever this holds; the automation tests and
//           the scripted runs (GameKitShellDrive.h) drive it headless.
// Usage   : FGameKitShellModel::FOptions Opt;  Opt.ProjectDir = FPaths::ProjectDir();  Opt.DataDir = ...;
//           TSharedRef<FGameKitShellModel> Model = MakeShared<FGameKitShellModel>(Opt);
//           Model->Push(TEXT("title"));
//           Model->KeyPressed(TEXT("key:enter"), TEXT("keyboard"));   // what the widget does on a key
//           Model->Dispatch(TEXT("ui_down"));                          // or the action straight away
//           Model->Update(DeltaSeconds);                               // loading, subtitles, messages
//           Model->OnEvent = [](const FString& What) { ... };          // "play", "resume", "quit_title", "quit", "settings_changed"
// Notes   : Focus ids match the LÖVE and Godot shells ("tabs.audio", "audio.master", "pause" rows "resume",
//           "help", "history", "settings", "quit"), so one drive script reads the same on every engine.
//           Settings are applied at once (the Version counter bumps and OnEvent fires "settings_changed"), except
//           the Display tab's, which wait for its Apply row (#308: "display_applied" fires too, and a new window mode
//           or size asks to keep it for 15 real seconds); Back or cancel on the settings screen saves
//           <DataDir>/settings.json. The one-handed layouts
//           come from <ProjectDir>/data/input/presets.json, the colour palettes from
//           data/access/colours.json, the strings from data/i18n/<locale>.json, the credits from CREDITS.md
//           (a packaged game: its copy data/credits.md, see CreditsSource; either way its HTML comments
//           are dropped: StripHtmlComments, #279; its markdown marks go: CreditsText, #284).
//           Only the top screen takes input; a transparent screen (pause) is drawn over the one below.
//           Analog input for the game (#274, as the Bevy shell's Intent): Stick() (radial, rescaled deadzone and
//           invert_y, GameKitAnalog.h), Trigger(), HeldActions(); all zero outside play and the juice demo, so a
//           menu never leaks a held trigger into the game. Debug builds (FOptions::bDebugBuild) add the juice demo
//           to the main menu, the pseudo language, and the F8 bug report (#275).
//
// Pseudocode:
//   KeyPressed(binding, device): held += binding ; capture open -> rebind ; F8 (debug) -> bug report ;
//     title "any key" -> menu ; else for every action bound to it (sorted): a held subtitle takes ui_accept first,
//     else Top().Action(a)
//   KeyReleased(binding): held -= binding
//   StickMoved(axis, v, device): raw stick[axis] = v ; |v| under the deadzone = 0 ; a direction not held and past
//     max(StickOn, deadzone) -> held, KeyPressed("pad:dpad_<dir>") ; a held direction back under StickOff -> released
//   HeldActions: game active? the actions of every held binding (no ui_*) + the move_* the stick leans past
//     max(deadzone, StickHoldMin) ; Stick: game active? AnalogStick(raw, deadzone, invert_y)
//   Dispatch(action): the top screen's rules (tabs, rows, pages, dialogs, the juice demo) -> true when used
//   Update(dt): loading progress, the juice demo, subtitle timer (held with subtitle_hold), messages, blink time
//   T(key): pseudo locale -> Pseudo(English text) with the placeholders filled after ; else the locale chain
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); analog input, the juice demo, the bug report and the
//           pseudo locale by Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): CreditsText, the markdown rule every engine shares (#284)
// Updated : 2026-11-13 with Claude (Opus 5.5, claude-opus-5-5): the Display tab waits for Apply (FGameKitDisplayStaging):
//           an Apply row, a Keep/Revert confirm counted down in real time (FPlatformTime, not Update's Dt), Back that
//           warns once (#308); disabled rows; HudScale(), HudFontSize() and the "hud_scale_changed" event (#309)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitBindings.h"
#include "GameKitDisplayStaging.h"
#include "GameKitI18n.h"

struct FGameKitJuiceDemo;

enum class EGameKitRowKind : uint8
{
	Button,    // accept runs it
	Toggle,    // accept, left or right flips it
	Slider,    // left and right step it
	Choice,    // left and right cycle the options, accept steps forward
	Binding,   // two cells (keyboard, gamepad); accept starts "press a key" for the focused cell
};

/** One focusable row of a screen: what it shows and what it does. Labels and values are read live. */
struct GAMEKITSHELLUI_API FGameKitRow
{
	FString Id;
	EGameKitRowKind Kind = EGameKitRowKind::Button;
	TFunction<FString()> Label;            // translated text
	TFunction<FString()> Value;            // the shown value ("" for buttons); binding rows: "<kb> | <pad>"
	TFunction<void(int32)> Step;           // -1 left, +1 right
	TFunction<void()> Accept;
	int32 Cell = 0;                        // binding rows: 0 keyboard, 1 gamepad
	TFunction<FString(int32)> CellText;    // binding rows: the label of one cell ("Space", "None")
	TFunction<bool(int32)> CellWarn;       // binding rows: the cell's binding clashes with another action
	TFunction<bool()> Enabled;             // unset = enabled; a disabled row is skipped by focus and shown dim (#308)

	bool IsEnabled() const { return !Enabled || Enabled(); }
};

/** A line the player saw (the subtitle bar), for "What now?" and the history page. */
struct FGameKitSaidLine
{
	FString Speaker;
	FString Text;
};

/** One screen on the stack. */
struct GAMEKITSHELLUI_API FGameKitScreen
{
	FString Name;                          // title, main_menu, settings, loading, play, pause, help, history, credits, juice_demo
	FString HeadingKey;                    // i18n key of the heading ("" for the game's name)
	TArray<FGameKitRow> Rows;
	int32 Focus = 0;
	bool bTransparent = false;             // drawn over the screen below (pause)
	// settings: the tab bar
	TArray<FString> Tabs;
	int32 TabIndex = 0;
	bool bOnTabs = false;                  // focus on the tab bar, not a row
	// title: the telemetry question; settings: "Keep these display settings?" (#308)
	TArray<FGameKitRow> Dialog;            // the consent buttons, or Keep and Revert, while the question is open
	int32 DialogFocus = 0;
	// text pages (credits, help, history)
	TArray<FString> Lines;
	int32 Scroll = 0;                      // lines scrolled past
	// loading
	int32 Steps = 0;
	int32 Done = 0;
	int32 Frames = 0;
	FString Next;                          // the screen loading opens
	double Time = 0.0;

	const FGameKitRow* Focused() const;
	FString FocusId() const;
	FString Tab() const { return Tabs.IsValidIndex(TabIndex) ? Tabs[TabIndex] : FString(); }
};

class GAMEKITSHELLUI_API FGameKitShellModel : public TSharedFromThis<FGameKitShellModel>
{
public:
	struct FOptions
	{
		FString ProjectDir;                // holds data/ and CREDITS.md (FPaths::ProjectDir())
		FString DataDir;                   // where settings.json is read and written
		FString GameName;                  // shown on the title
		FString Version;                   // shown on the title
		FString Locale;                    // a locale override (--locale), "" for the setting
		bool bAutomated = false;           // a smoke run: loading counts frames, nothing blinks
		bool bDebugBuild = false;          // the juice demo on the main menu, the pseudo language, F8 bug reports
	};

	// ---- Tunables ----
	static constexpr int32 MaxHistory = 50;           // lines the dialogue history keeps (#167)
	static constexpr double MessageS = 3.0;           // a settings message (rebound, reset) stays this long
	static constexpr double LoadingMinS = 0.6;        // the loading screen never flashes by faster
	static constexpr int32 LoadingMinFrames = 6;      // in an automated run
	static constexpr int32 LoadingFillerSteps = 4;    // placeholder steps so the bar visibly moves
	static constexpr double SubtitleSecondsPerChar = 0.06;   // a line without its own time: reading pace
	static constexpr double SubtitleMinS = 1.5;
	static constexpr double TextScaleMin = 0.75;
	static constexpr double TextScaleMax = 2.0;
	static constexpr double TextScaleStep = 0.25;
	static constexpr double StickOn = 0.5;            // the left stick presses a d-pad direction past this
	static constexpr double StickOff = 0.3;           // and lets it go under this (hysteresis, as the C++ shell)
	static constexpr double StickHoldMin = 0.2;       // raw stick lean that also holds a move_* action (#274)
	static constexpr double ToastS = 3.0;             // a toast ("Bug report saved.") stays this long
	static const TCHAR* const BugKey;                 // "key:f8": the bug report, in debug builds (#275)
	static const TCHAR* const PseudoLocale;           // "pseudo": every string accented, longer, in [ ] (debug builds)
	static const TCHAR* const SettingsFile;           // "settings.json" in DataDir
	static const TCHAR* const PresetsFile;            // "data/input/presets.json" under ProjectDir
	static const TCHAR* const ColoursFile;            // "data/access/colours.json"
	static const TCHAR* const I18nDir;                // "data/i18n"
	static const TCHAR* const CreditsFile;            // "CREDITS.md"
	static const TCHAR* const CreditsCopyFile;        // "data/credits.md": the copy a packaged game ships (#278)
	static const TCHAR* SettingsTabs[5];              // display, audio, controls, access, language
	static const TCHAR* GameActions[8];               // the rebindable actions, in menu order
	static const TCHAR* PresetNames[2];               // one_hand_left, one_hand_right
	static const TCHAR* HelpActions[6];               // the controls "What now?" lists

	explicit FGameKitShellModel(const FOptions& InOptions);
	~FGameKitShellModel();

	// ---- Credits (#278) ----
	/** The file the credits screen reads: <ProjectDir>/CREDITS.md when there is one (the editor), else
	 *  <ProjectDir>/data/credits.md (a packaged game, where only data/ is staged), else "" (the placeholder). */
	static FString CreditsSource(const FString& ProjectDir);
	/** Keeps data/credits.md a copy of CREDITS.md: written when it differs (data/ made if missing), left alone when
	 *  it matches, removed when CREDITS.md is gone. The module calls it in editor builds, so the editor and every
	 *  cook (dev.py package, the editor's Package Project, UAT) leave a fresh copy for staging. False only when a
	 *  file could not be read, written or removed; OutWhat says what happened, for the log. */
	static bool SyncCreditsCopy(const FString& ProjectDir, FString& OutWhat);

	// ---- Settings (always valid: GameKit::SettingsLoad fixed the file) ----
	TSharedRef<FJsonObject> Settings;
	TArray<FString> SettingsProblems;                 // what the loader fixed
	double Num(const TCHAR* Section, const TCHAR* Field) const;
	bool Flag(const TCHAR* Section, const TCHAR* Field) const;
	FString Str(const TCHAR* Section, const TCHAR* Field) const;
	void SetNum(const TCHAR* Section, const TCHAR* Field, double Value);
	void SetFlag(const TCHAR* Section, const TCHAR* Field, bool bValue);
	void SetStr(const TCHAR* Section, const TCHAR* Field, const FString& Value);
	FGameKitBindings Bindings() const;
	void SetBindings(const FGameKitBindings& NewBindings);
	/** Writes <DataDir>/settings.json; the path, or "" when it failed (logged). */
	FString SaveSettings();
	FString SettingsPath() const;
	/** Every setting applied: the Version bumps and OnEvent("settings_changed") fires. */
	void Changed();
	/** access.text_scale times display.ui_scale: what every font size is multiplied by. */
	double TextScale() const;

	// ---- A game HUD's text size (#309) ----
	/** The factor a HUD multiplies its font sizes by: display.ui_scale times access.text_scale (TextScale()).
	 *  OnEvent("hud_scale_changed") fires when it changes: text_scale at once, ui_scale on the Display tab's Apply. */
	double HudScale() const { return TextScale(); }
	/** A design font size at the player's text size: BasePx * Scale, never under 1. */
	static float HudFontSize(float BasePx, double Scale) { return FMath::Max(1.f, BasePx * static_cast<float>(Scale)); }
	float HudFontSize(float BasePx) const { return HudFontSize(BasePx, HudScale()); }

	// ---- The Display tab's Apply (#308) ----
	/** Display changes wait here until Apply (FGameKitDisplayStaging); the rows show and change its values. */
	const FGameKitDisplayStaging& DisplayStaging() const { return Staging; }
	/** "Keep these display settings? Reverting in N s" is open (its Keep and Revert are the settings screen's Dialog). */
	bool DisplayConfirming() const { return Staging.Confirming(); }
	/** Writes the changed Display fields through the settings, saves; true when it opened the confirm. */
	bool ApplyDisplay();
	void KeepDisplay();
	void RevertDisplay();
	/** Back from any settings tab: during the confirm reverts, with unapplied Display changes warns once, else saves
	 *  and leaves. */
	void SettingsBack();
	bool ReadableFont() const { return Flag(TEXT("access"), TEXT("readable_font")); }
	double LineSpacing() const { return Num(TEXT("access"), TEXT("line_spacing")); }
	bool ReduceMotion() const { return Flag(TEXT("access"), TEXT("reduce_motion")); }

	// ---- Text ----
	FString Locale() const;
	/** The pseudo locale is on: T() shows every string through GameKit::Pseudo (a string not in [ ] skipped T()). */
	bool IsPseudo() const { return Locale() == PseudoLocale; }
	/** A locale for this run only, as --locale gives (the pseudo drive switches to "pseudo"); "" for the setting. */
	void SetLocaleOverride(const FString& InLocale) { Opt.Locale = InLocale; ++Version; }
	FString T(const FString& Key, const FGameKitTrArgs& Args = FGameKitTrArgs()) const;
	/** A value the game made up (a name, a number) through the "{v}" template, so the pseudo check sees it. */
	FString Content(const FString& Text) const;
	/** CREDITS.md without HTML comments (tools/credits.py writes one, #279): one line or many, an unclosed one runs to
	 *  the end; a comment-only line goes, with one blank line after it when a blank line came before. LF joined.
	 *  tools/golden_vectors.py strip_html_comments is the spec, data/golden/credits.json the cases. */
	static FString StripHtmlComments(const FString& Text);
	/** CREDITS.md as every engine's credits screen shows it (#284): comments out, then per line a heading's marks
	 *  ('#' then a space, tab or the line end) or a list marker ('-', '*', '+' then a space or tab), every '*', and the
	 *  spaces and tabs at both ends; blank lines at the start and the end go. Empty when nothing is left.
	 *  tools/golden_vectors.py credits_text is the spec, data/golden/credits.json the cases. */
	static FString CreditsText(const FString& Markdown);
	/** CreditsText split into the credits page's lines; empty when nothing is left. */
	static TArray<FString> CreditsLinesFrom(const FString& Markdown);
	/** The label of a binding for a glyph set: glyph.<name> from the tables, or the key's own name ("Space"). */
	FString BindingLabel(const FString& GlyphName) const;
	FString GlyphSet() const;
	/** The prompt for an action right now: glyph name and label. */
	void Prompt(const FString& Action, FString& OutGlyph, FString& OutLabel) const;
	TArray<FString> Locales() const;

	// ---- Screens ----
	const FGameKitScreen* Top() const { return Stack.Num() ? &Stack.Last() : nullptr; }
	FGameKitScreen* Top() { return Stack.Num() ? &Stack.Last() : nullptr; }
	const TArray<FGameKitScreen>& Screens() const { return Stack; }
	FString TopName() const { return Top() ? Top()->Name : FString(); }
	FString FocusId() const { return Top() ? Top()->FocusId() : FString(); }
	void Push(const FString& Name);
	void Pop();
	void Replace(const FString& Name);
	void Reset(const FString& Name);
	/** The heading the screen shows (translated), for the view and the narrator. */
	FString Heading(const FGameKitScreen& Screen) const;

	// ---- Input ----
	/** A key or button as the shell sees it ("key:enter", "pad:south", "mouse:left"); Device: keyboard, mouse,
	 *  pad_xbox, pad_playstation, pad_switch, pad_other (GameKit::ShellInput::DeviceOf). */
	bool KeyPressed(const FString& Binding, const FString& Device);
	/** The left stick as the d-pad: Axis "x" (right is +1) or "y" (up is +1, as Unreal's Gamepad_LeftY). Passing
	 *  StickOn (or input.deadzone, if larger) presses pad:dpad_<dir> once; it is released only under StickOff, so
	 *  a stick wavering at the edge never repeats. True when the press was used. */
	bool StickMoved(const FString& Axis, double Value, const FString& Device);
	/** An action as if a bound key was pressed (drives and tests). True when a screen used it. */
	bool Dispatch(const FString& Action);
	FString LastDevice = TEXT("keyboard");
	/** The rebind prompt: the action waiting for a key, or "" (Capturing(), CaptureSlot()). */
	FString Capturing() const { return CaptureAction; }
	int32 CaptureSlot() const { return CaptureSlotIndex; }
	bool IsCapturing() const { return !CaptureAction.IsEmpty(); }
	void CancelCapture();

	// ---- Analog input for the game (#274, the Bevy shell's Intent) ----
	/** A key or button let go: the actions bound to it are no longer held. */
	void KeyReleased(const FString& Binding);
	/** Everything let go (the widget lost focus, a menu opened over the game). */
	void ReleaseAll();
	/** A trigger's raw travel, 0 at rest to 1 (bRight: the right trigger). */
	void TriggerMoved(bool bRight, double Value);
	/** The game has the input: play, or the juice demo, on top. Outside it every value below is zero. */
	bool GameActive() const;
	/** The left stick for gameplay: input.deadzone (radial, rescaled) and input.invert_y applied; up is +Y. */
	FVector2D Stick() const;
	/** A trigger, 0 to 1, past GameKit::TriggerDeadzone. */
	double Trigger(bool bRight) const;
	/** The game actions held now (no ui_*), sorted: held keys and buttons, plus the move_* the stick leans to. */
	TArray<FString> HeldActions() const;
	bool IsHeld(const FString& Action) const;
	/** The move_* actions the raw stick holds: a lean past max(input.deadzone, StickHoldMin), invert_y honoured. */
	TArray<FString> StickActions() const;
	FVector2D RawStick = FVector2D::ZeroVector;       // as the pad reports it: -1..1, up is +Y
	double RawTrigger[2] = {0.0, 0.0};                // left, right: 0..1

	// ---- The juice demo (debug builds, #275) ----
	/** The demo while "juice_demo" is on the stack (null otherwise). */
	FGameKitJuiceDemo* Juice() const { return JuiceDemo.Get(); }

	// ---- Bug report and crash files (#275) ----
	/** Writes bug_<time>/ in DataDir: info.txt, log_tail.txt, settings.json, and screenshot.png through OnScreenshot.
	 *  Logs BUG_REPORT <folder> and shows a toast. Returns the folder, "" when it could not be written. */
	FString BugReport();
	/** Saves a picture of the screen to the path (the subsystem: the game viewport; the drive: the shell widget). */
	TFunction<void(const FString&)> OnScreenshot;
	FString LastBugReport;
	/** This model's data folder takes the crash file if the game hits a fatal error (GameKitShellReport.h). */
	void ArmCrashReports();
	FString Toast;                                    // a short notice over every screen, while ToastT > 0
	double ToastT = 0.0;
	void ShowToast(const FString& Text);

	// ---- Frame ----
	void Update(double Dt);
	uint32 Version = 1;                               // bumps whenever something to draw changed
	double Time = 0.0;

	// ---- Subtitles, history, the goal (#167) ----
	/** Shows a line as the subtitle (speaker may be ""); Seconds 0 = from its length. Recorded in the history. */
	void Say(const FString& Speaker, const FString& Text, double Seconds = 0.0);
	bool HasSubtitle() const { return !Subtitle.Text.IsEmpty(); }
	const FGameKitSaidLine& CurrentSubtitle() const { return Subtitle; }
	/** A finished line kept on screen by access.subtitle_hold, waiting for accept. */
	bool Holding() const { return bHeld; }
	void Dismiss();
	const TArray<FGameKitSaidLine>& History() const { return SaidLines; }
	void SetObjective(const FString& Text) { Objective = Text; ++Version; }
	FString Objective;
	FString Message;                                  // the settings screen's hint line, while MessageT > 0
	double MessageT = 0.0;

	// ---- Narration (#165) ----
	/** The line a row says when it gets focus: "Music volume, slider, 70 percent". */
	FString Describe(const FGameKitRow& Row) const;
	FString LastNarration;
	TFunction<void(const FString&)> OnNarrate;        // called with every line while access.narration is on

	// ---- Colours (#169) ----
	/** A named colour of the palette for the current colour-blind setting (data/access/colours.json), or Fallback. */
	FLinearColor PaletteColour(const FString& Name, const FLinearColor& Fallback) const;

	// ---- Events ----
	TFunction<void(const FString&)> OnEvent;          // "play", "resume", "quit_title", "quit", "settings_changed", "consent",
	                                                  // "display_applied" (#308), "hud_scale_changed" (#309)
	bool bQuitRequested = false;
	bool bConsentAsked = false;
	/** A drive presses for this model (FGameKitShellDrive sets it, #276): a widget showing it takes no real keyboard,
	 *  mouse or pad input, so a stray key or a virtual pad cannot break the tour. KeyPressed() and Dispatch() still
	 *  work: they are what the drive calls. */
	bool bScripted = false;
	const FOptions& Options() const { return Opt; }

private:
	FOptions Opt;
	TArray<FGameKitScreen> Stack;
	FGameKitStringTables Tables;
	TSharedPtr<FJsonObject> Colours;
	FString CaptureAction;
	int32 CaptureSlotIndex = -1;
	bool StickHeld[4] = {false, false, false, false};   // dpad_up, dpad_down, dpad_left, dpad_right
	TSet<FString> HeldBindings;                        // keys and buttons down now ("key:a", "pad:south")
	TUniquePtr<FGameKitJuiceDemo> JuiceDemo;
	bool bCrashArmed = false;
	FGameKitSaidLine Subtitle;
	double SubtitleT = 0.0, SubtitleEnd = 0.0;
	bool bHeld = false;
	TArray<FGameKitSaidLine> SaidLines;
	FGameKitDisplayStaging Staging;                    // the Display tab's pending changes (#308)
	double LastRealTime = -1.0;                        // FPlatformTime::Seconds() at the last Update: the confirm's clock
	int32 LastConfirmSecs = -1;                        // the countdown redraws when its whole second changes
	double LastHudScale = 1.0;                         // hud_scale_changed fires when HudScale() leaves it (#309)

	void LoadTables();
	FGameKitScreen Build(const FString& Name);
	void BuildTab(FGameKitScreen& Screen);
	FGameKitRow Field(const TCHAR* Section, const TCHAR* Field, EGameKitRowKind Kind, double Lo = 0.0, double Hi = 1.0,
	                  double Step = 0.1, const TArray<FString>& Choices = TArray<FString>(), bool bTimes = false);
	FGameKitRow ButtonRow(const FString& Id, const FString& LabelKey, TFunction<void()> Accept);
	FGameKitRow BackRow();
	FGameKitRow BindingRow(const FString& Action);
	void SetDisplay(const FGameKitDisplayStaging::FCalls& Calls);   // writes Apply's or a revert's calls, applies, saves
	void CloseDisplayConfirm();
	double StagedNum(const FString& Field) const;
	bool StagedFlag(const FString& Field) const;
	FString StagedStr(const FString& Field) const;
	FIntPoint StagedResolution() const;
	void ApplyPreset(const FString& Preset);
	bool RowAction(FGameKitScreen& Screen, TArray<FGameKitRow>& Rows, int32& Focus, const FString& Action);
	void Event(const FString& What);
	void NarrateFocus();
	void NarrateScreen(const FGameKitScreen& Screen);
	void ScreenOpened(const FString& Name);
	TArray<FString> CreditsLines() const;
	TArray<FString> HelpLines() const;
	TArray<FString> HistoryLines() const;
	FString Percent(double V) const;
	FString Times(double V) const;
};
