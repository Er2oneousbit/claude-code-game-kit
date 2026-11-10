// ---------------------------------------------------------------------------
// GameKitShellCapture.cpp
// Purpose : The render-target capture behind GameKitShellCapture.h.
// Usage   : compiled into the GameKitShellUI module.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellCapture.h"

#include "Engine/TextureRenderTarget2D.h"
#include "Framework/Application/SlateApplication.h"
#include "ImageUtils.h"
#include "Math/Float16Color.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "RHI.h"
#include "RenderingThread.h"
#include "Slate/WidgetRenderer.h"
#include "TextureResource.h"
#include "Widgets/SWidget.h"

namespace GameKit::ShellCapture
{
	// ---- Tunables ----
	constexpr float CaptureDeltaS = 1.f / 60.f;   // the frame time each draw pass advances the widget by

	bool CanCapture()
	{
		return GIsRHIInitialized && !GUsingNullRHI && FSlateApplication::IsInitialized();
	}

	bool SavePng(const TSharedRef<SWidget>& Widget, const FIntPoint& Size, const FString& Path, FString& OutError)
	{
		if (!CanCapture())
		{
			OutError = TEXT("no renderer: start the editor without -NullRHI (dev.py adds -RenderOffScreen for --screenshot)");
			return false;
		}
		if (Size.X < 1 || Size.Y < 1)
		{
			OutError = FString::Printf(TEXT("bad capture size %d x %d"), Size.X, Size.Y);
			return false;
		}
		// Slate draws linear colours. A float target keeps them exact (an 8-bit linear target crushes the dark theme),
		// and the sRGB encoding happens once, here, on the read-back: the renderer's own gamma option plus an sRGB
		// target encoded twice (a washed-out picture, seen on UE 5.8), and no gamma at all gave raw linear bytes.
		FWidgetRenderer Renderer(/*bUseGammaCorrection*/ false, /*bClearTarget*/ true);
		UTextureRenderTarget2D* Target = NewObject<UTextureRenderTarget2D>();
		Target->AddToRoot();
		Target->RenderTargetFormat = RTF_RGBA16f;
		Target->ClearColor = FLinearColor::Transparent;
		Target->InitAutoFormat(Size.X, Size.Y);
		Target->UpdateResourceImmediate(true);
		Renderer.DrawWidget(Target, Widget, FVector2D(Size), CaptureDeltaS);   // pass 1: layout
		Renderer.DrawWidget(Target, Widget, FVector2D(Size), CaptureDeltaS);   // pass 2: the laid-out frame
		FlushRenderingCommands();
		TArray<FFloat16Color> Linear;
		FTextureRenderTargetResource* Resource = Target->GameThread_GetRenderTargetResource();
		const bool bRead = Resource && Resource->ReadFloat16Pixels(Linear);
		Target->RemoveFromRoot();
		if (!bRead || Linear.Num() != Size.X * Size.Y)
		{
			OutError = TEXT("could not read the render target back");
			return false;
		}
		TArray<FColor> Pixels;
		Pixels.Reserve(Linear.Num());
		for (const FFloat16Color& L : Linear)
		{
			FColor C = FLinearColor(L.R.GetFloat(), L.G.GetFloat(), L.B.GetFloat(), 1.f).ToFColor(/*bSRGB*/ true);
			C.A = 255;   // the overlay's own alpha is not what a screenshot should carry
			Pixels.Add(C);
		}
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), /*Tree*/ true);
		TArray64<uint8> Png;
		FImageUtils::PNGCompressImageArray(Size.X, Size.Y, Pixels, Png);
		if (Png.IsEmpty() || !FFileHelper::SaveArrayToFile(Png, *Path))
		{
			OutError = TEXT("could not write ") + Path;
			return false;
		}
		return true;
	}
}
