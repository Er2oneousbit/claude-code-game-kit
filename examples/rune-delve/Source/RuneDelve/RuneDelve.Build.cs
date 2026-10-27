// ---------------------------------------------------------------------------
// RuneDelve.Build.cs
// Purpose : Module dependencies. GAS (GameplayAbilities, GameplayTags, GameplayTasks), AI (AIModule,
//           NavigationSystem), Enhanced Input, and DeveloperSettings for the ini-backed tunables.
// Notes   : Add a module here before including its headers, or the link fails (docs/ENGINE.md gotcha 4).
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
using UnrealBuildTool;

public class RuneDelve : ModuleRules
{
	public RuneDelve(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput",
			"GameplayAbilities", "GameplayTags", "GameplayTasks",
			"AIModule", "NavigationSystem", "DeveloperSettings"
		});
		if (Target.bBuildEditor)
		{
			PrivateDependencyModuleNames.Add("UnrealEd");   // smoke tests drive Play In Editor
		}
	}
}
