// ---------------------------------------------------------------------------
// SGameKitShell.cpp
// Purpose : The Slate widgets behind SGameKitShell.h, one builder per screen.
// Usage   : compiled into the GameKitShellUI module.
// Notes   : Every colour and size comes from GameKitShellTheme.h; the access report (GameKitShellDrive.cpp)
//           describes the same numbers, so keep the two in step when restyling. The juice demo's world is one leaf
//           widget (SGameKitJuiceWorld) that paints boxes from the model every frame, in the LÖVE demo's 640x360
//           units scaled to the widget.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); analog input, the juice demo and the toast by
//           Claude (Opus 5.5, claude-opus-5-5)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): a scripted model's widget ignores the real
//           keyboard, mouse and pads (#276)
// ---------------------------------------------------------------------------
#include "SGameKitShell.h"

#include "Framework/Application/SlateApplication.h"
#include "GameKitEase.h"
#include "GameKitJuiceDemo.h"
#include "GameKitShellInput.h"
#include "GameKitShellTheme.h"
#include "GameKitSpring.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SDPIScaler.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/Layout/SWrapBox.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SLeafWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

using namespace GameKitTheme;

namespace
{
	// ---- Tunables: the juice demo's colours (sRGB, the LÖVE demo's fallback palette) ----
	const FColor JuicePlayer(242, 191, 77);
	const FColor JuiceTarget(89, 204, 115);
	const FColor JuiceHit(255, 77, 64);
	const FColor JuiceFloor(64, 69, 82);
	const FColor JuiceDeadzone(128, 153, 230, 89);
	constexpr float JuiceLine = 2.f;          // outline width, world units
	constexpr float JuiceRingMin = 10.f, JuiceRingGrow = 30.f;
	constexpr float JuiceFloorMark = 80.f;    // floor marks every this many units, so camera motion shows

	/** The juice demo's world, painted from the model each frame (FGameKitJuiceDemo holds the state). */
	class SGameKitJuiceWorld : public SLeafWidget
	{
	public:
		SLATE_BEGIN_ARGS(SGameKitJuiceWorld) {}
		SLATE_END_ARGS()

		void Construct(const FArguments& InArgs, const TSharedRef<FGameKitShellModel>& InModel)
		{
			Model = InModel;
		}

		virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(DesignW, DesignH); }

		virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geo, const FSlateRect& Cull, FSlateWindowElementList& Out,
		                      int32 Layer, const FWidgetStyle& Style, bool bParentEnabled) const override
		{
			const FGameKitJuiceDemo* J = Model.IsValid() ? Model->Juice() : nullptr;
			const FVector2f Size = Geo.GetLocalSize();
			Box(Out, Layer, Geo, 0.f, 0.f, Size.X, Size.Y, Colour::Bg);
			if (!J)
			{
				return Layer;
			}
			const float S = Size.X / static_cast<float>(FGameKitJuiceDemo::ViewW);   // world unit -> local
			// the camera, then the shake (offset and a turn about the centre)
			const float Ox = static_cast<float>(FGameKitJuiceDemo::ViewW / 2 - J->Cam.GetX() + J->Offset.X);
			const float Oy = static_cast<float>(FGameKitJuiceDemo::ViewH / 2 - J->Cam.GetY() + J->Offset.Y);
			const FGeometry World = Geo.MakeChild(FSlateRenderTransform(FQuat2D(static_cast<float>(J->Offset.Angle))));
			auto W = [&](double X, double Y, double Wd, double H, const FColor& C)
			{
				Box(Out, Layer + 1, World, (static_cast<float>(X) + Ox) * S, (static_cast<float>(Y) + Oy) * S, static_cast<float>(Wd) * S,
				    static_cast<float>(H) * S, C);
			};
			auto Ring = [&](double X, double Y, double Wd, double H, float Line, const FColor& C)
			{
				W(X, Y, Wd, Line, C);
				W(X, Y + H - Line, Wd, Line, C);
				W(X, Y, Line, H, C);
				W(X + Wd - Line, Y, Line, H, C);
			};
			const double Floor = FGameKitJuiceDemo::FloorY;
			W(-200.0, Floor, FGameKitJuiceDemo::WorldW + 400.0, 200.0, JuiceFloor);
			for (double X = 0.0; X <= FGameKitJuiceDemo::WorldW; X += JuiceFloorMark)
			{
				W(X, Floor + 6.0, 2.0, 8.0, Colour::PanelEdge);
			}
			const FVector2D Squash = GameKit::Squash(J->Spring.X);
			const double Tw = FGameKitJuiceDemo::TargetSize * Squash.X, Th = FGameKitJuiceDemo::TargetSize * Squash.Y;
			W(FGameKitJuiceDemo::TargetX + (FGameKitJuiceDemo::TargetSize - Tw) / 2, Floor - Th, Tw, Th, JuiceTarget);
			W(J->PX, J->PY, FGameKitJuiceDemo::PlayerSize, FGameKitJuiceDemo::PlayerSize, JuicePlayer);
			if (J->bGuard)
			{
				const double P = FGameKitJuiceDemo::PlayerSize;
				Ring(J->PX - P / 2, J->PY - P / 2, P * 2, P * 2, JuiceLine, JuicePlayer);
			}
			if (J->Pop > 0.0)   // an eased ring on the box
			{
				const double K = GameKit::Ease(EGameKitEase::OutBack, 1.0 - J->Pop / FGameKitJuiceDemo::PopS);
				const double R = JuiceRingMin + JuiceRingGrow * K;
				const double Cx = FGameKitJuiceDemo::TargetX + FGameKitJuiceDemo::TargetSize / 2, Cy = Floor - FGameKitJuiceDemo::TargetSize / 2;
				Ring(Cx - R, Cy - R, R * 2, R * 2, JuiceLine, JuiceHit);
			}
			Ring(J->Cam.GetX() - FGameKitJuiceDemo::CamDeadzoneW / 2, J->Cam.GetY() - FGameKitJuiceDemo::CamDeadzoneH / 2,
			     FGameKitJuiceDemo::CamDeadzoneW, FGameKitJuiceDemo::CamDeadzoneH, 1.f, JuiceDeadzone);
			if (J->Flash > 0.0)
			{
				FColor C = JuiceHit;
				C.A = static_cast<uint8>(FMath::Clamp(J->FlashPeak * (J->Flash / FGameKitJuiceDemo::FlashS), 0.0, 1.0) * 255.0);
				Box(Out, Layer + 2, Geo, 0.f, 0.f, Size.X, Size.Y, C);
			}
			return Layer + 2;
		}

	private:
		TSharedPtr<FGameKitShellModel> Model;

		static void Box(FSlateWindowElementList& Out, int32 Layer, const FGeometry& Geo, float X, float Y, float Wd, float H, const FColor& C)
		{
			FSlateDrawElement::MakeBox(Out, Layer, Geo.ToPaintGeometry(FVector2f(Wd, H), FSlateLayoutTransform(FVector2f(X, Y))),
			                           FCoreStyle::Get().GetBrush("WhiteBrush"), ESlateDrawEffect::None, Linear(C));
		}
	};
}

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
	if (InKeyEvent.IsRepeat() || Model->bScripted)   // #276: during a drive a real key reaches nothing
	{
		return FReply::Handled();
	}
	const FKey Key = InKeyEvent.GetKey();
	if (Key == EKeys::Gamepad_LeftStick_Up || Key == EKeys::Gamepad_LeftStick_Down || Key == EKeys::Gamepad_LeftStick_Left
	    || Key == EKeys::Gamepad_LeftStick_Right)
	{
		return FReply::Unhandled();   // the pad's own stick "buttons": OnAnalogValueChanged moves the focus instead
	}
	const FString Binding = GameKit::ShellInput::BindingOf(Key);
	if (Binding.IsEmpty())
	{
		return FReply::Unhandled();
	}
	const FString Device = GameKit::ShellInput::DeviceOf(InKeyEvent.GetKey(), InKeyEvent.GetInputDeviceId());
	return Model->KeyPressed(Binding, Device) ? FReply::Handled() : FReply::Unhandled();
}

FReply SGameKitShell::OnKeyUp(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	if (Model->bScripted)
	{
		return FReply::Handled();
	}
	const FString Binding = GameKit::ShellInput::BindingOf(InKeyEvent.GetKey());
	if (!Binding.IsEmpty())
	{
		Model->KeyReleased(Binding);   // no longer a held game action (#274)
	}
	return FReply::Unhandled();        // the game sees the release too
}

void SGameKitShell::OnFocusLost(const FFocusEvent& InFocusEvent)
{
	SCompoundWidget::OnFocusLost(InFocusEvent);
	Model->ReleaseAll();               // a key let go elsewhere never reaches OnKeyUp: nothing stays held
}

FReply SGameKitShell::OnAnalogValueChanged(const FGeometry& MyGeometry, const FAnalogInputEvent& InAnalogInputEvent)
{
	// the left stick moves the focus like the d-pad; the model keeps the hysteresis (StickMoved) and the raw value
	// for the game's Stick() (#274); the triggers feed Trigger(). Both also reach the game (unhandled). During a
	// drive a real stick or trigger reaches nothing (#276).
	if (Model->bScripted)
	{
		return FReply::Handled();
	}
	const FKey Key = InAnalogInputEvent.GetKey();
	if (Key == EKeys::Gamepad_LeftTriggerAxis || Key == EKeys::Gamepad_RightTriggerAxis)
	{
		Model->TriggerMoved(Key == EKeys::Gamepad_RightTriggerAxis, InAnalogInputEvent.GetAnalogValue());
		return FReply::Unhandled();
	}
	const bool bX = Key == EKeys::Gamepad_LeftX;
	if (!bX && Key != EKeys::Gamepad_LeftY)
	{
		return FReply::Unhandled();
	}
	const FString Device = GameKit::ShellInput::DeviceOf(Key, InAnalogInputEvent.GetInputDeviceId());
	const double Value = InAnalogInputEvent.GetAnalogValue();
	return Model->StickMoved(bX ? TEXT("x") : TEXT("y"), Value, Device) ? FReply::Handled() : FReply::Unhandled();
}

FReply SGameKitShell::OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	if (Model->bScripted)
	{
		return FReply::Handled();
	}
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

TSharedRef<SWidget> SGameKitShell::JuiceDemo(const FGameKitScreen& S)
{
	// the HUD: outlined text, so it reads over any part of the world; the controls wrap at long text sizes
	auto Outlined = [this](const FString& Str, float DesignPx, const FColor& C)
	{
		FSlateFontInfo F = Font(DesignPx);
		F.OutlineSettings = FFontOutlineSettings(1, Linear(Colour::Outline));
		return SNew(STextBlock).Text(FText::FromString(Str)).Font(F).ColorAndOpacity(FSlateColor(Linear(C))).AutoWrapText(true);
	};
	TSharedRef<SWrapBox> Controls = SNew(SWrapBox).UseAllottedSize(true).InnerSlotPadding(FVector2D(16.f, 6.f));
	for (const TCHAR* Action : {TEXT("move_left"), TEXT("move_right"), TEXT("jump"), TEXT("attack"), TEXT("interact"), TEXT("pause")})
	{
		FString Glyph, Label;
		Model->Prompt(Action, Glyph, Label);
		Controls->AddSlot()
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().Padding(FMargin(0.f, 0.f, 6.f, 0.f))
			[
				Panel(Colour::Panel, Text(Label, SmallPx, Colour::Text), 4.f)
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				Outlined(Model->T(TEXT("action.") + FString(Action)), SmallPx, Colour::Dim)
			]
		];
	}
	TSharedRef<FGameKitShellModel> M = Model.ToSharedRef();
	return SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SGameKitJuiceWorld, M)
		]
		+ SOverlay::Slot().HAlign(HAlign_Fill).VAlign(VAlign_Top).Padding(FMargin(PanelPad))
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()[Outlined(Model->Heading(S), HeadingPx, Colour::Accent)]
			+ SVerticalBox::Slot().AutoHeight().Padding(FMargin(0.f, 8.f))[Controls]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(STextBlock)
				.Font(Font(SmallPx))
				.ColorAndOpacity(FSlateColor(Linear(Colour::Dim)))
				.AutoWrapText(true)
				.Text_Lambda([M] { return FText::FromString(M->Juice() ? M->Juice()->Stats(*M) : FString()); })   // live
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(STextBlock)
				.Font(Font(SmallPx))
				.ColorAndOpacity(FSlateColor(Linear(Colour::Accent)))
				.Text(FText::FromString(Model->T(TEXT("juice.guard"))))
				.Visibility_Lambda([M] { return M->Juice() && M->Juice()->bGuard ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
			]
		];
}

TSharedRef<SWidget> SGameKitShell::ToastWidget()
{
	return SNew(SBox).HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(FMargin(0.f, 24.f))
		[
			Panel(Colour::Panel, Text(Model->Toast, SmallPx, Colour::Text, true), 12.f)
		];
}

TSharedRef<SWidget> SGameKitShell::Screen(const FGameKitScreen& S)
{
	if (S.Name == TEXT("juice_demo")) return JuiceDemo(S);
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
	if (!Model->Toast.IsEmpty())
	{
		Root->AddSlot()[ToastWidget()];   // "Bug report saved." over every screen (#275)
	}
}
