using UnrealBuildTool;
public class RuneDelveEditorTarget : TargetRules
{
	public RuneDelveEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("RuneDelve");
	}
}
