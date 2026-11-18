// ---------------------------------------------------------------------------
// GameKitDotwork.Build.cs
// Purpose : Build rules for the GameKitDotwork runtime module: what Dotwork art needs at run time that Paper2D lacks
//           (#286), so far the animated tiles of an imported tile map.
// Usage   : Enabled with the plugin (GameKitShell in the .uproject); nothing to call: its world subsystem plays
//           every tile map in the world whose tiles say anim=<frames>@<fps> in their user data.
// Notes   : Paper2D is an engine plugin, on by default; the .uplugin lists it so the module loads after it.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnrealBuildTool;

public class GameKitDotwork : ModuleRules
{
	public GameKitDotwork(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "Paper2D" });
	}
}
