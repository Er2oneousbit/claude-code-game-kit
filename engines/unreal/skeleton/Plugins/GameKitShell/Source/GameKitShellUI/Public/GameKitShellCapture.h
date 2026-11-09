// ---------------------------------------------------------------------------
// GameKitShellCapture.h
// Purpose : Draws a Slate widget (the shell) into a picture file without a game window: what
//           `python tools/dev.py smoke --drive show:<screen> --screenshot out.png` saves.
// Usage   : FString Error;
//           if (!GameKit::ShellCapture::SavePng(Widget, FIntPoint(1920, 1080), Path, Error)) { ... }
// Notes   : Needs a real renderer (the editor started with -RenderOffScreen, not -NullRHI): FWidgetRenderer draws
//           the widget to a render target, which is read back and written as PNG. The widget is drawn twice,
//           so the second pass has the layout the first one measured.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"

class SWidget;

namespace GameKit::ShellCapture
{
	/** True when a renderer is up (a picture is possible); with -NullRHI there is none. */
	GAMEKITSHELLUI_API bool CanCapture();

	/** Draws Widget at Size and writes Path (PNG); false with OutError set when it could not. */
	GAMEKITSHELLUI_API bool SavePng(const TSharedRef<SWidget>& Widget, const FIntPoint& Size, const FString& Path, FString& OutError);
}

// {{FOOTER}}
