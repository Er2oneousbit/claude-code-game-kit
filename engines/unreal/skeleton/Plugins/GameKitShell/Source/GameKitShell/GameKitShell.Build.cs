// ---------------------------------------------------------------------------
// GameKitShell.Build.cs
// Purpose : Build rules for the GameKitShell runtime module: the kit's juice and shell logic as plain C++.
// Usage   : Enable the plugin in the .uproject ({ "Name": "GameKitShell", "Enabled": true }), then add
//           "GameKitShell" to your game module's PublicDependencyModuleNames (docs/ENGINE_FLOW.md).
// Notes   : Core and Json only, so the logic builds in every target (game, editor, server) and its
//           automation tests need no world. Json is public because the settings and save headers hand
//           out FJsonObject.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnrealBuildTool;

public class GameKitShell : ModuleRules
{
	public GameKitShell(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "Json" });
	}
}

// {{FOOTER}}
