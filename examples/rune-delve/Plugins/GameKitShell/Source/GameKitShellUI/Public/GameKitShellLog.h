// ---------------------------------------------------------------------------
// GameKitShellLog.h
// Purpose : The log category of the shell's screens. Proof lines the scripted runs print (DRIVE_DONE,
//           SETTINGS_WRITTEN, ACCESS_*) go through it at Display level, so tools/dev.py finds them in the log.
// Usage   : UE_LOG(LogGameKitShell, Display, TEXT("DRIVE_DONE %s"), *Name);
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Logging/LogMacros.h"

GAMEKITSHELLUI_API DECLARE_LOG_CATEGORY_EXTERN(LogGameKitShell, Log, All);
