// ---------------------------------------------------------------------------
// GameKitShellUI.Build.cs
// Purpose : Build rules for the GameKitShellUI runtime module: the shell's screens (title, main menu, settings,
//           pause, credits, loading) as Slate widgets over the GameKitShell logic module.
// Usage   : Enabled with the plugin (the .uproject entry turns both modules on). A game that only wants the
//           logic can delete this folder and the module entry in GameKitShell.uplugin.
// Notes   : Slate, not UMG assets: every screen is C++ in this module, so there is no .uasset to hand-edit and
//           the screens build and run in a Blueprint-only project too. UMG is still a dependency for
//           FWidgetRenderer, which draws a screen to a PNG for `dev.py smoke --drive show:<screen>
//           --screenshot`. Projects gives the plugin's folder (the readable font under Resources/Fonts).
//           The font is read from disk at runtime, so it is a runtime dependency: a packaged game gets
//           Resources/Fonts (with its OFL licence) as loose files. The project's data/ folder is staged by the
//           plugin's Config/Game.ini instead, read when the game is staged, so files added to data/ later ship
//           without a rebuild of these rules.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// Updated : 2026-11-10 with Claude (Opus 5.5, claude-opus-5-5): the readable font staged with a packaged game
// ---------------------------------------------------------------------------
using UnrealBuildTool;

public class GameKitShellUI : ModuleRules
{
	public GameKitShellUI(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "Json", "GameKitShell", "Slate", "SlateCore" });
		PrivateDependencyModuleNames.AddRange(new string[] { "ApplicationCore", "InputCore", "UMG", "RenderCore", "RHI", "Projects", "DeveloperSettings", "EngineSettings" });
		// The readable font and its licence, staged loose next to the packaged game (GameKitShellTheme.cpp reads it)
		RuntimeDependencies.Add("$(PluginDir)/Resources/Fonts/...", StagedFileType.NonUFS);
	}
}
