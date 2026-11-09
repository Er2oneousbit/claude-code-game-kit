// ---------------------------------------------------------------------------
// GameKitShellTheme.cpp
// Purpose : Fonts and text measuring for the shell's theme (see GameKitShellTheme.h).
// Usage   : compiled into the GameKitShellUI module.
// Notes   : The readable font is loaded by file path (Slate's legacy font constructor), so no font asset is
//           needed; the path comes from the plugin's own folder through IPluginManager.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellTheme.h"

#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Styling/CoreStyle.h"

namespace GameKitTheme
{
	FString ReadableFontPath(bool bBold)
	{
		const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("GameKitShell"));
		if (!Plugin.IsValid())
		{
			return FString();
		}
		return FPaths::Combine(Plugin->GetBaseDir(), TEXT("Resources/Fonts"),
		                       bBold ? TEXT("AtkinsonHyperlegible-Bold.ttf") : TEXT("AtkinsonHyperlegible-Regular.ttf"));
	}

	FSlateFontInfo Font(float Px, bool bReadable, bool bBold)
	{
		const float Points = FMath::Max(1.f, Px * PointsPerPixel);
		if (bReadable)
		{
			const FString Path = ReadableFontPath(bBold);
			if (!Path.IsEmpty() && FPaths::FileExists(Path))
			{
				return FSlateFontInfo(Path, Points);
			}
		}
		return FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Points);
	}

	float Measure(const FString& Text, const FSlateFontInfo& FontInfo)
	{
		if (!FSlateApplication::IsInitialized())
		{
			return -1.f;
		}
		const TSharedPtr<FSlateFontMeasure> Service = FSlateApplication::Get().GetRenderer()
			? FSlateApplication::Get().GetRenderer()->GetFontMeasureService() : nullptr;
		if (!Service.IsValid())
		{
			return -1.f;
		}
		return static_cast<float>(Service->Measure(Text, FontInfo).X);
	}
}

// {{FOOTER}}
