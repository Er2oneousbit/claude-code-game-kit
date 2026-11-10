// ---------------------------------------------------------------------------
// GameKitShellTheme.cpp
// Purpose : Fonts and text measuring for the shell's theme (see GameKitShellTheme.h).
// Usage   : compiled into the GameKitShellUI module.
// Notes   : The readable font is loaded from its file as a standalone composite font, so no font asset is
//           needed; the path comes from the plugin's own folder through IPluginManager.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellTheme.h"

#include "Fonts/CompositeFont.h"
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
				// One composite font per file, kept for the run: Slate caches glyphs by the composite font's address
				static TMap<FString, TSharedPtr<const FCompositeFont>> Loaded;
				TSharedPtr<const FCompositeFont>& Composite = Loaded.FindOrAdd(Path);
				if (!Composite.IsValid())
				{
					Composite = MakeShared<FStandaloneCompositeFont>(FName(*FPaths::GetBaseFilename(Path)), Path, EFontHinting::Default,
					                                                 EFontLoadingPolicy::LazyLoad);
				}
				return FSlateFontInfo(Composite, Points);
			}
		}
		return FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Points);
	}

	float Measure(const FString& S, const FSlateFontInfo& FontInfo)
	{
		if (!FSlateApplication::IsInitialized())
		{
			return -1.f;
		}
		FSlateRenderer* Renderer = FSlateApplication::Get().GetRenderer();
		if (!Renderer)
		{
			return -1.f;
		}
		return static_cast<float>(Renderer->GetFontMeasureService()->Measure(S, FontInfo).X);
	}
}

// {{FOOTER}}
