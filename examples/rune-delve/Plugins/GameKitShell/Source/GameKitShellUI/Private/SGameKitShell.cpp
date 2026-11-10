// ---------------------------------------------------------------------------
// SGameKitShell.cpp
// Purpose : The Slate widgets behind SGameKitShell.h, one builder per screen.
// Usage   : compiled into the GameKitShellUI module.
// Notes   : Every colour and size comes from GameKitShellTheme.h; the access report (GameKitShellDrive.cpp)
//           describes the same numbers, so keep the two in step when restyling.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "SGameKitShell.h"

#include "Framework/Application/SlateApplication.h"
#include "GameKitShellInput.h"
#include "GameKitShellTheme.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SDPIScaler.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

using namespace GameKitTheme;

namespace
{
	const TCHAR* FocusMarker = TEXT(">");

	/** Placeholder arguments for Tr: one {name} -> value pair. */
	FGameKitTrArgs Args(const TCHAR* K, const FString& V)
	{
		FGameKitTrArgs M;
		M.Add(K, V);
		return M;
	}
	constexpr float MarkerW = 36.f;
	constexpr float TabPadX = 18.f, TabPadY = 8.f;
	constexpr float ListTop = 24.f;        // gap between the tab bar and the rows
	constexpr float PageLineGap = 6.f;
	constexpr int32 SubtitleOutlinePx = 2;

	const FSlateBrush* White() { return FCoreStyle::Get().GetBrush("WhiteBrush"); }
}

void SGameKitShell::Construct(const FArguments& InArgs, const TSharedRef<FGameKitShellModel>& InModel)
{
	Model = InModel;
	ChildSlot
	[
		SAssignNew(Scaler, SDPIScaler)
		.DPIScale_Lambda([this] { return Scale(); })
		[
			SAssignNew(Root, SOverlay)
		]
	];
	Rebuild();
}

void SGameKitShell::Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime)
{
	SCompoundWidget::Tick(AllottedGeometry, InCurrentTime, InDeltaTime);
	const FVector2D Size = AllottedGeometry.GetLocalSize();
	if (Size.X > 1.0 && Size.Y > 1.0)
	{
		CachedScale = FMath::Max(0.05f, static_cast<float>(FMath::Min(Size.X / DesignW, Size.Y / DesignH)));
	}
	Model->Update(InDeltaTime);
	if (Model->Version != BuiltVersion)
	{
		Rebuild();
	}
	if (bScrollPending && List.IsValid() && FocusedRow.IsValid())
	{
		List->ScrollDescendantIntoView(FocusedRow, false);
		bScrollPending = false;
	}
}

FReply SGameKitShell::OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	if (InKeyEvent.IsRepeat())
	{
		return FReply::Handled();
	}
	const FString Binding = GameKit::ShellInput::BindingOf(InKeyEvent.GetKey());
	if (Binding.IsEmpty())
	{
		return FReply::Unhandled();
	}
	return Model->KeyPressed(Binding, GameKit::ShellInput::DeviceOf(InKeyEvent.GetKey())) ? FReply::Handled() : FReply::Unhandled();
}

FReply SGameKitShell::OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FString Binding = GameKit::ShellInput::BindingOf(MouseEvent.GetEffectingButton());
	if (!Binding.IsEmpty() && Model->KeyPressed(Binding, TEXT("mouse")))
	{
		return FReply::Handled().SetUserFocus(AsShared(), EFocusCause::Mouse);
	}
	return FReply::Handled().SetUserFocus(AsShared(), EFocusCause::Mouse);
}

FReply SGameKitShell::OnFocusReceived(const FGeometry& MyGeometry, const FFocusEvent& InFocusEvent)
{
	return FReply::Handled();
}

// ---- Pieces ------------------------------------------------------------------------------------------------------
float SGameKitShell::Px(float DesignPx) const
{
	return DesignPx * static_cast<float>(Model->TextScale());
}

FSlateFontInfo SGameKitShell::Font(float DesignPx, bool bBold) const
{
	return GameKitTheme::Font(Px(DesignPx), Model->ReadableFont(), bBold);
}

TSharedRef<STextBlock> SGameKitShell::Text(const FString& S, float DesignPx, const FColor& Colour, bool bWrap, bool bBold) const
{
	return SNew(STextBlock)
		.Text(FText::FromString(S))
		.Font(Font(DesignPx, bBold))
		.ColorAndOpacity(FSlateColor(Linear(Colour)))
		.AutoWrapText(bWrap)
		.LineHeightPercentage(static_cast<float>(Model->LineSpacing()));
}

TSharedRef<SWidget> SGameKitShell::Panel(const FColor& Colour, const TSharedRef<SWidget>& Content, float Pad) const
{
	return SNew(SBorder)
		.BorderImage(White())
		.BorderBackgroundColor(Linear(Colour))
		.Padding(FMargin(Pad))
		[
			Content
		];
}

TSharedRef<SWidget> SGameKitShell::Hint(const FString& S, const FColor& Colour) const
{
	return SNew(SBox)
		.HAlign(HAlign_Center)
		.Padding(FMargin(PageMargin, 0.f, PageMargin, 24.f))
		[
			Text(S, SmallPx, Colour, true)
		];
}

TSharedRef<SWidget> SGameKitShell::RowWidget(const FGameKitRow& Row, bool bFocused, float LabelWidth, float ListWidth, bool bCenter)
{
	TSharedRef<SHorizontalBox> Line = SNew(SHorizontalBox);
	Line->AddSlot().AutoWidth().VAlign(VAlign_Center)
	[
		SNew(SBox).WidthOverride(MarkerW)
		[
			Text(bFocused ? FocusMarker : TEXT(""), BodyPx, Colour::Accent)
		]
	];
	const FString Label = Row.Label ? Row.Label() : FString();
	if (bCenter)
	{
		Line->AddSlot().FillWidth(1.f).HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			Text(Label, BodyPx, bFocused ? Colour::Accent : Colour::Text, true)
		];
		Line->AddSlot().AutoWidth()[SNew(SBox).WidthOverride(MarkerW)];
	}
	else
	{
		// a button row (Back, Reset, a layout) has no value: its label may take the whole row, so a sentence
		// still fits at 200 % text (the access sweep found "Reset controls to defaults" clipped in the label column)
		const bool bWide = Row.Kind == EGameKitRowKind::Button;
		Line->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SBox).WidthOverride((bWide ? ListWidth : LabelWidth) - MarkerW - 2 * RowPadX)
			[
				Text(Label, BodyPx, bFocused ? Colour::Accent : Colour::Text, true)
			]
		];
		if (Row.Kind == EGameKitRowKind::Binding && Row.CellText)
		{
			for (int32 Cell = 0; Cell < 2; ++Cell)
			{
				const bool bCellFocus = bFocused && Row.Cell == Cell;
				const bool bWarn = Row.CellWarn && Row.CellWarn(Cell);
				Line->AddSlot().FillWidth(1.f).Padding(FMargin(Cell ? RowGap : 0.f, 0.f, 0.f, 0.f)).VAlign(VAlign_Center)
				[
					SNew(SBorder)
					.BorderImage(White())
					.BorderBackgroundColor(bCellFocus ? Linear(Colour::Focus) : FLinearColor::Transparent)
					.Padding(FMargin(2.f))
					[
						SNew(SBorder)
						.BorderImage(White())
						.BorderBackgroundColor(Linear(bFocused ? Colour::RowFocus : Colour::Row))
						.Padding(FMargin(8.f, 2.f))
						[
							Text(Row.CellText(Cell), BodyPx, bWarn ? Colour::Warn : Colour::Text, true)
						]
					]
				];
			}
		}
		else if (Row.Value && !bWide)
		{
			Line->AddSlot().FillWidth(1.f).VAlign(VAlign_Center)
			[
				Text(Row.Value(), BodyPx, Colour::Text, true)
			];
		}
	}
	TSharedRef<SWidget> Widget = SNew(SBorder)
		.BorderImage(White())
		.BorderBackgroundColor(Linear(bFocused ? Colour::RowFocus : Colour::Row))
		.Padding(FMargin(RowPadX, RowPadY))
		[
			SNew(SBox).WidthOverride(ListWidth - 2 * RowPadX)
			[
				Line
			]
		];
	if (bFocused)
	{
		FocusedRow = Widget;
	}
	return Widget;
}

TSharedRef<SWidget> SGameKitShell::Rows(const TArray<FGameKitRow>& RowList, int32 Focus, float LabelWidth, float ListWidth, bool bCenter, bool bScroll)
{
	TSharedRef<SVerticalBox> Column = SNew(SVerticalBox);
	for (int32 I = 0; I < RowList.Num(); ++I)
	{
		Column->AddSlot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, RowGap))
		[
			RowWidget(RowList[I], I == Focus, LabelWidth, ListWidth, bCenter)
		];
	}
	if (!bScroll)
	{
		return Column;
	}
	List = SNew(SScrollBox).ScrollBarVisibility(EVisibility::Collapsed);
	List->AddSlot()
	[
		Column
	];
	bScrollPending = true;
	return List.ToSharedRef();
}

// ---- Screens -----------------------------------------------------------------------------------------------------
FSlateColor SGameKitShell::BlinkColour() const
{
	if (Model->ReduceMotion() || Model->Options().bAutomated)
	{
		return FSlateColor(Linear(Colour::Text));
	}
	const double Wave = 0.5 + 0.5 * FMath::Cos(Model->Time * 2.0 * PI / BlinkPeriodS);
	FLinearColor C = Linear(Colour::Text);
	C.A = FMath::Lerp(BlinkMinAlpha, 1.f, static_cast<float>(Wave));
	return FSlateColor(C);
}

TSharedRef<SWidget> SGameKitShell::Title(const FGameKitScreen& S)
{
	TSharedRef<SOverlay> Over = SNew(SOverlay);
	Over->AddSlot().HAlign(HAlign_Center).VAlign(VAlign_Center)
	[
		SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 0.f, 0.f, 48.f))
		[
			Text(Model->Heading(S), TitlePx, Colour::Accent, true, true)
		]
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
		[
			SNew(STextBlock)
			.Text(FText::FromString(Model->T(TEXT("title.press_any"))))
			.Font(Font(BodyPx))
			.ColorAndOpacity_Lambda([this] { return BlinkColour(); })
		]
	];
	Over->AddSlot().HAlign(HAlign_Right).VAlign(VAlign_Bottom).Padding(FMargin(PanelPad))
	[
		Text(Model->T(TEXT("title.version"), Args(TEXT("version"), Model->Options().Version)), SmallPx, Colour::Dim)
	];
	if (S.Dialog.Num())
	{
		// the three answers as a column (as the LÖVE shell lists them): side by side they clip at 200 % text
		TSharedRef<SWidget> Buttons = Rows(S.Dialog, S.DialogFocus, ConsentW - 2 * PanelPad, ConsentW - 2 * PanelPad, true, false);
		Over->AddSlot().HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			SNew(SBox).WidthOverride(ConsentW)
			[
				Panel(Colour::Panel,
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 12.f))[Text(Model->T(TEXT("consent.title")), HeadingPx, Colour::Text, true, true)]
					+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, 18.f))[Text(Model->T(TEXT("consent.body")), BodyPx, Colour::Text, true)]
					+ SVerticalBox::Slot().AutoHeight()[Buttons],
					PanelPad)
			]
		];
	}
	return Over;
}

TSharedRef<SWidget> SGameKitShell::MainMenu(const FGameKitScreen& S)
{
	FString Glyph, Label;
	Model->Prompt(TEXT("ui_accept"), Glyph, Label);
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 96.f, 0.f, 48.f))
		[
			Text(Model->Heading(S), HeadingPx, Colour::Accent, true, true)
		]
		+ SVerticalBox::Slot().FillHeight(1.f).HAlign(HAlign_Center).VAlign(VAlign_Top)
		[
			Rows(S.Rows, S.Focus, MenuW, MenuW, true, true)
		]
		+ SVerticalBox::Slot().AutoHeight()
		[
			Hint(Label + TEXT("  ") + Model->T(TEXT("hint.select")), Colour::Dim)
		];
}

TSharedRef<SWidget> SGameKitShell::Settings(const FGameKitScreen& S)
{
	TSharedRef<SHorizontalBox> Tabs = SNew(SHorizontalBox);
	for (const FString& Tab : S.Tabs)
	{
		const bool bSelected = Tab == S.Tab();
		const bool bFocus = bSelected && S.bOnTabs;
		Tabs->AddSlot().AutoWidth().Padding(FMargin(RowGap, 0.f))
		[
			SNew(SBorder)
			.BorderImage(White())
			.BorderBackgroundColor(bFocus ? Linear(Colour::Focus) : FLinearColor::Transparent)
			.Padding(FMargin(2.f))
			[
				SNew(SBorder)
				.BorderImage(White())
				.BorderBackgroundColor(Linear(bSelected ? Colour::RowFocus : Colour::Row))
				.Padding(FMargin(TabPadX, TabPadY))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()[Text(Model->T(TEXT("settings.tab.") + Tab), SmallPx, bSelected ? Colour::Text : Colour::Dim)]
					+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 4.f, 0.f, 0.f))
					[
						SNew(SBox).HeightOverride(3.f)
						[
							SNew(SImage).Image(White()).ColorAndOpacity(bSelected ? Linear(Colour::Accent) : FLinearColor::Transparent)   // the open tab is underlined
						]
					]
				]
			]
		];
	}
	const bool bMessage = !Model->Message.IsEmpty();
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 24.f, 0.f, 12.f))
		[
			Text(Model->Heading(S), HeadingPx, Colour::Accent, true, true)
		]
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
		[
			Tabs
		]
		+ SVerticalBox::Slot().FillHeight(1.f).HAlign(HAlign_Center).Padding(FMargin(0.f, ListTop, 0.f, 12.f))
		[
			Rows(S.Rows, S.bOnTabs ? -1 : S.Focus, LabelW, ListW, false, true)
		]
		+ SVerticalBox::Slot().AutoHeight()
		[
			Hint(bMessage ? Model->Message : Model->T(TEXT("settings.hint")), bMessage ? Colour::Accent : Colour::Dim)
		];
}

TSharedRef<SWidget> SGameKitShell::Pause(const FGameKitScreen& S)
{
	return SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SImage).Image(White()).ColorAndOpacity(Linear(Colour::Overlay))
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			Panel(Colour::Panel,
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 0.f, 0.f, 18.f))[Text(Model->Heading(S), HeadingPx, Colour::Accent, true, true)]
				+ SVerticalBox::Slot().AutoHeight()[Rows(S.Rows, S.Focus, MenuW, MenuW, true, false)],
				PanelPad)
		];
}

TSharedRef<SWidget> SGameKitShell::Loading(const FGameKitScreen& S)
{
	const float Progress = S.Steps > 0 ? static_cast<float>(S.Done) / S.Steps : 1.f;
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot().FillHeight(1.f).HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 0.f, 0.f, 24.f))[Text(Model->Heading(S), BodyPx, Colour::Text)]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
			[
				SNew(SBox).WidthOverride(BarW).HeightOverride(BarH)
				[
					SNew(SProgressBar).Percent(Progress).FillColorAndOpacity(Linear(Colour::Accent))
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 12.f, 0.f, 0.f))
			[
				Text(Model->T(TEXT("value.percent"), Args(TEXT("n"), FString::FromInt(FMath::RoundToInt(Progress * 100.f)))), SmallPx, Colour::Dim)
			]
		];
}

TSharedRef<SWidget> SGameKitShell::TextPage(const FGameKitScreen& S)
{
	TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
	for (int32 I = S.Scroll; I < S.Lines.Num(); ++I)
	{
		Body->AddSlot().AutoHeight().Padding(FMargin(0.f, 0.f, 0.f, PageLineGap))
		[
			S.Lines[I].IsEmpty() ? StaticCastSharedRef<SWidget>(SNew(SSpacer).Size(FVector2D(1.f, Px(BodyPx))))
			                      : StaticCastSharedRef<SWidget>(Text(S.Lines[I], BodyPx, Colour::Text, true))
		];
	}
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 24.f, 0.f, 18.f))
		[
			Text(Model->Heading(S), HeadingPx, Colour::Accent, true, true)
		]
		+ SVerticalBox::Slot().FillHeight(1.f).Padding(FMargin(PageMargin, 0.f))
		[
			SAssignNew(Page, SScrollBox).ScrollBarVisibility(EVisibility::Collapsed)
			+ SScrollBox::Slot()
			[
				Body
			]
		]
		+ SVerticalBox::Slot().AutoHeight()
		[
			Hint(Model->T(TEXT("page.hint")), Colour::Dim)
		];
}

TSharedRef<SWidget> SGameKitShell::Subtitle()
{
	const FGameKitSaidLine& Line = Model->CurrentSubtitle();
	const FString Size = Model->Str(TEXT("access"), TEXT("subtitle_size"));
	const TArray<FString> Sizes = {TEXT("small"), TEXT("medium"), TEXT("large"), TEXT("xl")};
	const float SubPx = SubtitlePx[FMath::Max(0, Sizes.IndexOfByKey(Size))];
	FLinearColor Back = Linear(Colour::Panel);
	Back.A = static_cast<float>(Model->Num(TEXT("access"), TEXT("subtitle_background")));
	// an outline on both texts: the panel's alpha is the player's choice, so over a bright game the outline is
	// what keeps the words at 4.5:1 (SOP-20, E158; the access report says "outline" for this text)
	FSlateFontInfo SpeakerFont = Font(SubPx, true), TextFont = Font(SubPx);
	SpeakerFont.OutlineSettings = FFontOutlineSettings(SubtitleOutlinePx, Linear(Colour::Outline));
	TextFont.OutlineSettings = SpeakerFont.OutlineSettings;
	TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
	if (Model->Flag(TEXT("access"), TEXT("speaker_names")) && !Line.Speaker.IsEmpty())
	{
		Row->AddSlot().AutoWidth().Padding(FMargin(0.f, 0.f, 12.f, 0.f))
		[
			SNew(STextBlock)
			.Text(FText::FromString(Model->T(TEXT("subtitle.speaker"), Args(TEXT("name"), Line.Speaker))))
			.Font(SpeakerFont)
			.ColorAndOpacity(FSlateColor(Linear(Colour::Accent)))
		];
	}
	Row->AddSlot().FillWidth(1.f)
	[
		SNew(STextBlock)
		.Text(FText::FromString(Line.Text))
		.Font(TextFont)
		.ColorAndOpacity(FSlateColor(Linear(Colour::Text)))
		.AutoWrapText(true)
		.LineHeightPercentage(static_cast<float>(Model->LineSpacing()))
	];
	return SNew(SBox).HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(PageMargin, 0.f, PageMargin, 42.f))
		[
			SNew(SBorder)
			.BorderImage(White())
			.BorderBackgroundColor(Back)
			.Padding(FMargin(16.f, 8.f))
			[
				SNew(SBox).MaxDesiredWidth(DesignW - 2 * PageMargin)
				[
					Row
				]
			]
		];
}

TSharedRef<SWidget> SGameKitShell::CapturePrompt()
{
	const FString Key = Model->CaptureSlot() == 0 ? TEXT("controls.press_key") : TEXT("controls.press_button");
	return SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SImage).Image(White()).ColorAndOpacity(Linear(Colour::Overlay))
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			Panel(Colour::Panel,
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 0.f, 0.f, 12.f))
				[
					Text(Model->T(Key, Args(TEXT("action"), Model->T(TEXT("action.") + Model->Capturing()))), BodyPx, Colour::Text, true)
				]
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
				[
					Text(Model->T(TEXT("controls.capture_cancel")), SmallPx, Colour::Dim)
				],
				PanelPad)
		];
}

TSharedRef<SWidget> SGameKitShell::Screen(const FGameKitScreen& S)
{
	if (S.Name == TEXT("title")) return Title(S);
	if (S.Name == TEXT("main_menu")) return MainMenu(S);
	if (S.Name == TEXT("settings")) return Settings(S);
	if (S.Name == TEXT("pause")) return Pause(S);
	if (S.Name == TEXT("loading")) return Loading(S);
	if (S.Name == TEXT("help") || S.Name == TEXT("history") || S.Name == TEXT("credits")) return TextPage(S);
	return SNew(SSpacer);   // play: the game shows through
}

void SGameKitShell::Rebuild()
{
	BuiltVersion = Model->Version;
	Root->ClearChildren();
	List.Reset();
	Page.Reset();
	FocusedRow.Reset();
	const TArray<FGameKitScreen>& Stack = Model->Screens();
	int32 First = Stack.Num() - 1;
	while (First > 0 && Stack[First].bTransparent)
	{
		--First;
	}
	for (int32 I = FMath::Max(0, First); I < Stack.Num(); ++I)
	{
		const FGameKitScreen& S = Stack[I];
		const bool bOpaque = !S.bTransparent && S.Name != TEXT("play");
		TSharedRef<SWidget> Content = Screen(S);
		Root->AddSlot()
		[
			bOpaque ? Panel(Colour::Bg, Content, 0.f) : Content
		];
	}
	if (Model->HasSubtitle() && Model->Flag(TEXT("access"), TEXT("subtitles")))
	{
		Root->AddSlot()[Subtitle()];
	}
	if (Model->IsCapturing())
	{
		Root->AddSlot()[CapturePrompt()];
	}
}
