// ---------------------------------------------------------------------------
// GameKitPlatformBackends.cpp
// Purpose : MakePlatformBackend (see GameKitPlatformBackends.h).
// Usage   : see GameKitPlatformBackends.h
// Notes   : The null backend for every build.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitPlatformBackends.h"

namespace GameKit
{
	TUniquePtr<IPlatformBackend> MakePlatformBackend(bool /*bAutomated*/)
	{
		return nullptr;
	}
}

// {{FOOTER}}
