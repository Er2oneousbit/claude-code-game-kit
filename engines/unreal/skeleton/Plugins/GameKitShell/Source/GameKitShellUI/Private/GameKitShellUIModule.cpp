// ---------------------------------------------------------------------------
// GameKitShellUIModule.cpp
// Purpose : Registers the GameKitShellUI module and its log category, keeps the log tail the bug report and crash
//           files show, and writes a crash file on a fatal error while a shell runs (#275). In editor builds it
//           also refreshes data/credits.md from CREDITS.md (#278), so a packaged game ships its credits. The screens
//           themselves start from UGameKitShellSubsystem (when the project turns them on) or from your own code
//           (SGameKitShell).
// Usage   : nothing to call; Unreal loads the module when the plugin is enabled.
// Notes   : Why the credits copy happens here: the plugin's Config/Game.ini stages data/ with a packaged game, but
//           Unreal stages folders, not single files, and a Build.cs RuntimeDependencies entry for CREDITS.md fails
//           the package when the file is missing (an exists-check there goes stale: UBT caches the rules). Every
//           packaging route (dev.py package, the editor's Package Project, UAT BuildCookRun) cooks first, and the
//           cook is an editor-build process that loads this module, so the copy is fresh by the time data/ is
//           staged, and nothing fails when there is no CREDITS.md. data/credits.md is generated (and gitignored):
//           edit CREDITS.md.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); crash files and the log tail by Claude (Opus 5.5,
//           claude-opus-5-5)
// Updated : 2026-11-11 with Claude (Opus 5.5, claude-opus-5-5): the credits copy for packaged games (#278)
// ---------------------------------------------------------------------------
#include "GameKitShellLog.h"
#include "GameKitShellModel.h"
#include "GameKitShellReport.h"
#include "Misc/App.h"
#include "Misc/CoreDelegates.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY(LogGameKitShell);

class FGameKitShellUIModule final : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		GameKit::ShellReport::StartLogTail();
		ErrorHandle = FCoreDelegates::OnHandleSystemError.AddStatic(&GameKit::ShellReport::OnSystemError);
#if WITH_EDITOR
		SyncCredits();
#endif
	}

	virtual void ShutdownModule() override
	{
		FCoreDelegates::OnHandleSystemError.Remove(ErrorHandle);
		GameKit::ShellReport::StopLogTail();
	}

private:
	FDelegateHandle ErrorHandle;

#if WITH_EDITOR
	/** The editor, its commandlets and the cook: data/credits.md follows CREDITS.md. Never fails the run. */
	static void SyncCredits()
	{
		if (!FApp::HasProjectName())
		{
			return;   // no project (the project browser): no folder to write into
		}
		FString What;
		const bool bOk = FGameKitShellModel::SyncCreditsCopy(FPaths::ProjectDir(), What);
		UE_LOG(LogGameKitShell, Display, TEXT("credits copy: %s"), *What);
		if (!bOk)
		{
			UE_LOG(LogGameKitShell, Warning, TEXT("a packaged game may show old or no credits: %s"), *What);
		}
	}
#endif
};

IMPLEMENT_MODULE(FGameKitShellUIModule, GameKitShellUI)

// {{FOOTER}}
