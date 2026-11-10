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
//           Settings are applied at once (the Version counter bumps and OnEvent fires "settings_changed");
//           Back or cancel on the settings screen saves <DataDir>/settings.json. The one-handed layouts
//           come from <ProjectDir>/data/input/presets.json, the colour palettes from
//           data/access/colours.json, the strings from data/i18n/<locale>.json, the credits from CREDITS.md.
//           Only the top screen takes input; a transparent screen (pause) is drawn over the one below.
//
// Pseudocode:
//   KeyPressed(binding, device): capture open -> rebind ; title "any key" -> menu ;
//     else for every action bound to it (sorted): a held subtitle takes ui_accept first, else Top().Action(a)
//   StickMoved(axis, v, device): |v| under the deadzone = 0 ; a direction not held and past max(StickOn, deadzone)
//     -> held, KeyPressed("pad:dpad_<dir>") ; a held direction back under StickOff -> released
//   Dispatch(action): the top screen's rules (tabs, rows, pages, dialogs) -> true when used
//   Update(dt): loading progress, subtitle timer (held with subtitle_hold), the settings message, blink time
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "GameKitBindings.h"
#include "GameKitI18n.h"

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
	FString Name;                          // title, main_menu, settings, loading, play, pause, help, history, credits
	FString HeadingKey;                    // i18n key of the heading ("" for the game's name)
	TArray<FGameKitRow> Rows;
	int32 Focus = 0;
	bool bTransparent = false;             // drawn over the screen below (pause)
	// settings: the tab bar
	TArray<FString> Tabs;
	int32 TabIndex = 0;
	bool bOnTabs = false;                  // focus on the tab bar, not a row
	// title: the telemetry question
	TArray<FGameKitRow> Dialog;            // the consent buttons while the question is open
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
		bool bDebugBuild = false;          // (reserved for a juice demo entry, as the other shells have)
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
	static const TCHAR* const SettingsFile;           // "settings.json" in DataDir
	static const TCHAR* const PresetsFile;            // "data/input/presets.json" under ProjectDir
	static const TCHAR* const ColoursFile;            // "data/access/colours.json"
	static const TCHAR* const I18nDir;                // "data/i18n"
	static const TCHAR* const CreditsFile;            // "CREDITS.md"
	static const TCHAR* SettingsTabs[5];              // display, audio, controls, access, language
	static const TCHAR* GameActions[8];               // the rebindable actions, in menu order
	static const TCHAR* PresetNames[2];               // one_hand_left, one_hand_right
	static const TCHAR* HelpActions[6];               // the controls "What now?" lists

	explicit FGameKitShellModel(const FOptions& InOptions);

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
	bool ReadableFont() const { return Flag(TEXT("access"), TEXT("readable_font")); }
	double LineSpacing() const { return Num(TEXT("access"), TEXT("line_spacing")); }
	bool ReduceMotion() const { return Flag(TEXT("access"), TEXT("reduce_motion")); }

	// ---- Text ----
	FString Locale() const;
	FString T(const FString& Key, const FGameKitTrArgs& Args = FGameKitTrArgs()) const;
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
	TFunction<void(const FString&)> OnEvent;          // "play", "resume", "quit_title", "quit", "settings_changed", "consent"
	bool bQuitRequested = false;
	bool bConsentAsked = false;
	const FOptions& Options() const { return Opt; }

private:
	FOptions Opt;
	TArray<FGameKitScreen> Stack;
	FGameKitStringTables Tables;
	TSharedPtr<FJsonObject> Colours;
	FString CaptureAction;
	int32 CaptureSlotIndex = -1;
	bool StickHeld[4] = {false, false, false, false};   // dpad_up, dpad_down, dpad_left, dpad_right
	FGameKitSaidLine Subtitle;
	double SubtitleT = 0.0, SubtitleEnd = 0.0;
	bool bHeld = false;
	TArray<FGameKitSaidLine> SaidLines;

	void LoadTables();
	FGameKitScreen Build(const FString& Name);
	void BuildTab(FGameKitScreen& Screen);
	FGameKitRow Field(const TCHAR* Section, const TCHAR* Field, EGameKitRowKind Kind, double Lo = 0.0, double Hi = 1.0,
	                  double Step = 0.1, const TArray<FString>& Choices = TArray<FString>(), bool bTimes = false);
	FGameKitRow ButtonRow(const FString& Id, const FString& LabelKey, TFunction<void()> Accept);
	FGameKitRow BackRow();
	FGameKitRow BindingRow(const FString& Action);
	void ApplyPreset(const FString& Preset);
	bool RowAction(FGameKitScreen& Screen, TArray<FGameKitRow>& Rows, int32& Focus, const FString& Action);
	void Event(const FString& What);
	void NarrateFocus();
	void NarrateScreen(const FGameKitScreen& Screen);
	FString Content(const FString& Text) const;
	TArray<FString> CreditsLines() const;
	TArray<FString> HelpLines() const;
	TArray<FString> HistoryLines() const;
	FString Percent(double V) const;
	FString Times(double V) const;
};

// {{FOOTER}}
