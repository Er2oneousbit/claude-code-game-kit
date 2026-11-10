// ---------------------------------------------------------------------------
// GameKitShellUIModule.cpp
// Purpose : Registers the GameKitShellUI module and its log category, keeps the log tail the bug report and crash
//           files show, and writes a crash file on a fatal error while a shell runs (#275). The screens themselves
//           start from UGameKitShellSubsystem (when the project turns them on) or from your own code (SGameKitShell).
// Usage   : nothing to call; Unreal loads the module when the plugin is enabled.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); crash files and the log tail by Claude (Opus 5.5,
//           claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitShellLog.h"
#include "GameKitShellReport.h"
#include "Misc/CoreDelegates.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogGameKitShell);

class FGameKitShellUIModule final : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		GameKit::ShellReport::StartLogTail();
		ErrorHandle = FCoreDelegates::OnHandleSystemError.AddStatic(&GameKit::ShellReport::OnSystemError);
	}

	virtual void ShutdownModule() override
	{
		FCoreDelegates::OnHandleSystemError.Remove(ErrorHandle);
		GameKit::ShellReport::StopLogTail();
	}

private:
	FDelegateHandle ErrorHandle;
};

IMPLEMENT_MODULE(FGameKitShellUIModule, GameKitShellUI)
