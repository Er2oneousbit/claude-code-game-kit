// ---------------------------------------------------------------------------
// GameKitShellInput.cpp
// Purpose : The key table behind GameKitShellInput.h.
// Usage   : compiled into the GameKitShellUI module.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#include "GameKitShellInput.h"

namespace GameKit::ShellInput
{
	namespace
	{
		struct FKeyName
		{
			const TCHAR* Key;       // FKey name
			const TCHAR* Binding;   // the shell's string
		};

		// ---- Tunables: the named keys; letters, digits and function keys map by rule below ----
		const FKeyName Table[] = {
			{TEXT("SpaceBar"), TEXT("key:space")}, {TEXT("Enter"), TEXT("key:enter")}, {TEXT("Escape"), TEXT("key:escape")},
			{TEXT("Up"), TEXT("key:up")}, {TEXT("Down"), TEXT("key:down")}, {TEXT("Left"), TEXT("key:left")}, {TEXT("Right"), TEXT("key:right")},
			{TEXT("Tab"), TEXT("key:tab")}, {TEXT("BackSpace"), TEXT("key:backspace")}, {TEXT("Delete"), TEXT("key:delete")},
			{TEXT("LeftShift"), TEXT("key:lshift")}, {TEXT("RightShift"), TEXT("key:rshift")},
			{TEXT("LeftControl"), TEXT("key:lctrl")}, {TEXT("RightControl"), TEXT("key:rctrl")},
			{TEXT("LeftAlt"), TEXT("key:lalt")}, {TEXT("RightAlt"), TEXT("key:ralt")},
			{TEXT("Zero"), TEXT("key:0")}, {TEXT("One"), TEXT("key:1")}, {TEXT("Two"), TEXT("key:2")}, {TEXT("Three"), TEXT("key:3")},
			{TEXT("Four"), TEXT("key:4")}, {TEXT("Five"), TEXT("key:5")}, {TEXT("Six"), TEXT("key:6")}, {TEXT("Seven"), TEXT("key:7")},
			{TEXT("Eight"), TEXT("key:8")}, {TEXT("Nine"), TEXT("key:9")},
			{TEXT("LeftMouseButton"), TEXT("mouse:left")}, {TEXT("RightMouseButton"), TEXT("mouse:right")},
			{TEXT("MiddleMouseButton"), TEXT("mouse:middle")},
			{TEXT("Gamepad_FaceButton_Bottom"), TEXT("pad:south")}, {TEXT("Gamepad_FaceButton_Right"), TEXT("pad:east")},
			{TEXT("Gamepad_FaceButton_Left"), TEXT("pad:west")}, {TEXT("Gamepad_FaceButton_Top"), TEXT("pad:north")},
			{TEXT("Gamepad_DPad_Up"), TEXT("pad:dpad_up")}, {TEXT("Gamepad_DPad_Down"), TEXT("pad:dpad_down")},
			{TEXT("Gamepad_DPad_Left"), TEXT("pad:dpad_left")}, {TEXT("Gamepad_DPad_Right"), TEXT("pad:dpad_right")},
			{TEXT("Gamepad_LeftShoulder"), TEXT("pad:l1")}, {TEXT("Gamepad_RightShoulder"), TEXT("pad:r1")},
			{TEXT("Gamepad_LeftTrigger"), TEXT("pad:l2")}, {TEXT("Gamepad_RightTrigger"), TEXT("pad:r2")},
			{TEXT("Gamepad_LeftThumbstick"), TEXT("pad:l3")}, {TEXT("Gamepad_RightThumbstick"), TEXT("pad:r3")},
			{TEXT("Gamepad_Special_Right"), TEXT("pad:start")}, {TEXT("Gamepad_Special_Left"), TEXT("pad:select")},
		};
	}

	FString BindingOf(const FKey& Key)
	{
		if (!Key.IsValid() || Key.IsAxis1D() || Key.IsAxis2D() || Key.IsAxis3D())
		{
			return FString();
		}
		const FString Name = Key.GetFName().ToString();
		for (const FKeyName& Row : Table)
		{
			if (Name == Row.Key)
			{
				return Row.Binding;
			}
		}
		if (Key.IsGamepadKey())
		{
			return TEXT("pad:") + Name.Replace(TEXT("Gamepad_"), TEXT("")).ToLower();
		}
		if (Key.IsMouseButton())
		{
			return TEXT("mouse:") + Name.Replace(TEXT("MouseButton"), TEXT("")).ToLower();
		}
		return TEXT("key:") + Name.ToLower();   // letters, F1..F12 and the rest by their key name
	}

	FString DeviceOf(const FKey& Key)
	{
		if (Key.IsGamepadKey())
		{
			return TEXT("pad");
		}
		if (Key.IsMouseButton())
		{
			return TEXT("mouse");
		}
		return TEXT("keyboard");
	}

	TOptional<FKey> KeyOf(const FString& Binding)
	{
		for (const FKeyName& Row : Table)
		{
			if (Binding == Row.Binding)
			{
				return FKey(Row.Key);
			}
		}
		FString Kind, Name;
		if (!Binding.Split(TEXT(":"), &Kind, &Name) || Name.IsEmpty())
		{
			return {};
		}
		FString KeyName;
		if (Kind == TEXT("key"))
		{
			KeyName = Name.Len() == 1 ? Name.ToUpper() : Name.Left(1).ToUpper() + Name.Mid(1);   // "a" -> "A", "f5" -> "F5"
		}
		else if (Kind == TEXT("pad"))
		{
			KeyName = TEXT("Gamepad_") + Name;
		}
		else
		{
			return {};
		}
		const FKey Key(*KeyName);
		if (Key.IsValid() && EKeys::GetKeyDetails(Key).IsValid())
		{
			return Key;
		}
		return {};
	}
}

// {{FOOTER}}
