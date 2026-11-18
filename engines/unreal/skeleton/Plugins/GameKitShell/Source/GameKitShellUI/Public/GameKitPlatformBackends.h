// ---------------------------------------------------------------------------
// GameKitPlatformBackends.h
// Purpose : Picks the platform layer's backend for this build (docs/PLATFORM.md): the null backend, which every game
//           runs by default.
// Usage   : GameKit::FPlatformService Service(DataDir, Text, GameKit::MakePlatformBackend(bAutomated));
// Notes   : nullptr means "the null backend" (FPlatformService makes one). An automated run never asks a store.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "GameKitPlatform.h"

namespace GameKit
{
	/** The store backend, or nullptr for the null backend. */
	GAMEKITSHELLUI_API TUniquePtr<IPlatformBackend> MakePlatformBackend(bool bAutomated);
}

// {{FOOTER}}
