// ---------------------------------------------------------------------------
// GameKitShellModule.cpp
// Purpose : Registers the GameKitShell module. It has no start-up work: everything in it is plain C++ the
//           game calls directly (see the Public/ headers).
// Usage   : nothing to call; Unreal loads the module when the plugin is enabled.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Modules/ModuleManager.h"

IMPLEMENT_MODULE(FDefaultModuleImpl, GameKitShell)
