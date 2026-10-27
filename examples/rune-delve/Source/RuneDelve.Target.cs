using UnrealBuildTool;
public class RuneDelveTarget : TargetRules
{
	public RuneDelveTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("RuneDelve");
	}
}
