// ---------------------------------------------------------------------------
// GameKitShellUIModule.cpp
// Purpose : Registers the GameKitShellUI module and its log category. The screens themselves start from
//           UGameKitShellSubsystem (when the project turns them on) or from your own code (SGameKitShell).
// Usage   : nothing to call; Unreal loads the module when the plugin is enabled.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellLog.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogGameKitShell);

IMPLEMENT_MODULE(FDefaultModuleImpl, GameKitShellUI)
