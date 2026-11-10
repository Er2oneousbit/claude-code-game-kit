// ---------------------------------------------------------------------------
// SGameKitShell.h
// Purpose : The Slate view of the shell: draws whatever FGameKitShellModel holds (the top screen, a transparent
//           pause over the game, the subtitle bar, the "press a key" prompt) and feeds keys, pad buttons and
//           mouse clicks to the model. Rebuilt only when the model's Version changes.
// Usage   : TSharedRef<SGameKitShell> W = SNew(SGameKitShell, Model);
//           GEngine->GameViewport->AddViewportWidgetContent(W, 100);  FSlateApplication::Get().SetAllUserFocus(W);
//           (UGameKitShellSubsystem does this for you when the project turns the screens on.)
// Notes   : Slate from C++, not UMG assets, so the screens live in text files Claude can edit and build in a
//           Blueprint-only project. The 1920x1080 design is scaled to the widget's size (SDPIScaler, the
//           smaller of the two ratios), so text sizes are design pixels times access.text_scale and
//           display.ui_scale; access.readable_font swaps every font for Atkinson Hyperlegible and
//           access.line_spacing stretches wrapped lines. Focus is never colour alone: the focused row gets a
//           ">" marker and a brighter row. Hover does nothing (keys and pad only; a click counts as "any key"
//           on the title). The widget ticks the model (Update) each frame. It also tells the model which keys are
//           held and where the left stick and the triggers are (#274), letting them through to the game; losing
//           focus lets everything go. The juice demo's world is painted live from the model (no rebuild per frame).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); analog input, the juice demo and the toast by
//           Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameKitShellModel.h"
#include "Widgets/SCompoundWidget.h"

class SDPIScaler;
class SOverlay;
class SScrollBox;
class STextBlock;
class SVerticalBox;

class GAMEKITSHELLUI_API SGameKitShell : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SGameKitShell) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, const TSharedRef<FGameKitShellModel>& InModel);

	virtual void Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime) override;
	virtual bool SupportsKeyboardFocus() const override { return true; }
	virtual FReply OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;
	virtual FReply OnKeyUp(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;
	virtual void OnFocusLost(const FFocusEvent& InFocusEvent) override;
	virtual FReply OnAnalogValueChanged(const FGeometry& MyGeometry, const FAnalogInputEvent& InAnalogInputEvent) override;
	virtual FReply OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnFocusReceived(const FGeometry& MyGeometry, const FFocusEvent& InFocusEvent) override;

	/** Rebuilds the widget tree from the model now (Tick does it when the model changed). */
	void Rebuild();
	TSharedRef<FGameKitShellModel> GetModel() const { return Model.ToSharedRef(); }

private:
	TSharedPtr<FGameKitShellModel> Model;
	TSharedPtr<SDPIScaler> Scaler;
	TSharedPtr<SOverlay> Root;
	TSharedPtr<SScrollBox> List;             // the current list, for scrolling the focused row into view
	TSharedPtr<SWidget> FocusedRow;
	TSharedPtr<SScrollBox> Page;             // a text page, scrolled by its line offset
	float CachedScale = 1.f;
	uint32 BuiltVersion = 0;
	bool bScrollPending = false;

	float Scale() const { return CachedScale; }
	float Px(float DesignPx) const;          // design px times the text scale
	FSlateFontInfo Font(float DesignPx, bool bBold = false) const;
	TSharedRef<STextBlock> Text(const FString& S, float DesignPx, const FColor& Colour, bool bWrap = false, bool bBold = false) const;
	TSharedRef<SWidget> Panel(const FColor& Colour, const TSharedRef<SWidget>& Content, float Pad) const;
	TSharedRef<SWidget> RowWidget(const FGameKitRow& Row, bool bFocused, float LabelWidth, float ListWidth, bool bCenter);
	TSharedRef<SWidget> Rows(const TArray<FGameKitRow>& RowList, int32 Focus, float LabelWidth, float ListWidth, bool bCenter, bool bScroll);
	TSharedRef<SWidget> Hint(const FString& S, const FColor& Colour) const;
	TSharedRef<SWidget> Screen(const FGameKitScreen& S);
	TSharedRef<SWidget> Title(const FGameKitScreen& S);
	TSharedRef<SWidget> MainMenu(const FGameKitScreen& S);
	TSharedRef<SWidget> Settings(const FGameKitScreen& S);
	TSharedRef<SWidget> Pause(const FGameKitScreen& S);
	TSharedRef<SWidget> Loading(const FGameKitScreen& S);
	TSharedRef<SWidget> TextPage(const FGameKitScreen& S);
	TSharedRef<SWidget> Subtitle();
	TSharedRef<SWidget> CapturePrompt();
	TSharedRef<SWidget> JuiceDemo(const FGameKitScreen& S);
	TSharedRef<SWidget> ToastWidget();
	FSlateColor BlinkColour() const;
};

// {{FOOTER}}
