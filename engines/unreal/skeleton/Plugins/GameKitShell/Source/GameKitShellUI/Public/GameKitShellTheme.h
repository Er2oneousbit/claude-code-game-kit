// ---------------------------------------------------------------------------
// GameKitShellTheme.h
// Purpose : The built-in look of the shell's screens (colours, text sizes, widths) in one place, shared by the
//           Slate view (SGameKitShell) and the accessibility report the scripted runs print, so what the sweep
//           checks is what the screen draws. Fonts: the engine's default, or Atkinson Hyperlegible (OFL, in
//           Plugins/GameKitShell/Resources/Fonts) with access.readable_font on.
// Usage   : SNew(STextBlock).Font(GameKitTheme::Font(GameKitTheme::BodyPx * Scale, bReadable))
//           GameKitTheme::Hex(GameKitTheme::Colour::Text)   // "#ebedf5", what the access report prints
// Notes   : The design is 1920x1080; SGameKitShell scales it to the window (SDPIScaler), so every size here is
//           in design pixels. Body text is 22 px (18 px is the floor at 1080p, F36) and the smallest text 18 px,
//           which lands on 12 px at 1280x800, the Steam Deck recommendation (E75). Colours are sRGB bytes (as
//           on the other shells) and turned into linear colours for Slate; the amber accent and the grey
//           panels read in every colour-blind mode, so the menus never need a palette swap (#169). Sizes are
//           given in pixels and turned into Slate's points (96 dpi) in Font().
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Fonts/SlateFontInfo.h"
#include "Math/Color.h"

namespace GameKitTheme
{
	// ---- Tunables ----
	constexpr float DesignW = 1920.f, DesignH = 1080.f;
	constexpr float BodyPx = 22.f;        // UI text at text_scale 1
	constexpr float SmallPx = 18.f;       // hints and the version line
	constexpr float HeadingPx = 36.f;
	constexpr float TitlePx = 56.f;
	constexpr float SubtitlePx[4] = {18.f, 22.f, 30.f, 38.f};   // small, medium, large, xl
	constexpr float RowPadX = 14.f, RowPadY = 6.f, RowGap = 4.f;
	constexpr float ListW = 1000.f;       // the settings list
	constexpr float LabelW = 520.f;       // its label column
	constexpr float MenuW = 480.f;        // main menu and pause buttons
	constexpr float PageMargin = 96.f;    // credits, help, history
	constexpr float PanelPad = 24.f;
	constexpr float ConsentW = 760.f;
	constexpr float BarW = 540.f, BarH = 18.f;
	constexpr float BlinkPeriodS = 1.2f;
	constexpr float BlinkMinAlpha = 0.35f;
	constexpr float PointsPerPixel = 72.f / 96.f;   // Slate font sizes are points at 96 dpi

	// sRGB, as the LÖVE and Godot shells define them
	namespace Colour
	{
	const FColor Bg(18, 20, 28);
	const FColor Panel(33, 38, 51);
	const FColor PanelEdge(77, 87, 107);
	const FColor Row(41, 46, 61);
	const FColor RowFocus(66, 77, 102);
	const FColor Text(235, 237, 245);
	const FColor Dim(158, 166, 184);
	const FColor Accent(250, 199, 82);   // amber: reads in every colour-blind mode
	const FColor Focus(255, 255, 255);
	const FColor Warn(255, 115, 89);
	const FColor Bar(102, 179, 255);
	const FColor Overlay(0, 0, 0, 158);  // 0.62 alpha
	}

	/** A theme colour for Slate (linear space). */
	inline FLinearColor Linear(const FColor& C) { return FLinearColor(C); }

	/** "#rrggbb" for the access report. */
	inline FString Hex(const FColor& C) { return FString::Printf(TEXT("#%02x%02x%02x"), C.R, C.G, C.B); }

	/** The font for Px design pixels: the engine's default, or the readable font when bReadable. */
	GAMEKITSHELLUI_API FSlateFontInfo Font(float Px, bool bReadable, bool bBold = false);

	/** The readable font file (Resources/Fonts of the plugin), "" when the plugin folder is unknown. */
	GAMEKITSHELLUI_API FString ReadableFontPath(bool bBold = false);

	/** The width of Text drawn with Font, in design pixels; -1 when Slate cannot measure here (no application). */
	GAMEKITSHELLUI_API float Measure(const FString& Text, const FSlateFontInfo& Font);
}

// {{FOOTER}}
