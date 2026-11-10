// ---------------------------------------------------------------------------
// GameKitShellInput.cpp
// Purpose : The key table behind GameKitShellInput.h.
// Usage   : compiled into the GameKitShellUI module.
// Notes   : PadBrand reads the name FInputDeviceRegistry holds for the device (see GameKitShellInput.h).
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); pad makes by Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "GameKitShellInput.h"

#include "GenericPlatform/InputDeviceRegistry.h"

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

		// ---- Tunables: pad name hints (lower case, matched anywhere in the name) ----
		const TCHAR* const XboxHints[] = {TEXT("xbox"), TEXT("xinput"), TEXT("x-box")};
		const TCHAR* const SwitchHints[] = {TEXT("nintendo"), TEXT("switch"), TEXT("joy-con"), TEXT("joycon"),
		                                    TEXT("pro controller")};
		const TCHAR* const PlayStationHints[] = {TEXT("playstation"), TEXT("dualshock"), TEXT("dualsense"), TEXT("ps3"),
		                                         TEXT("ps4"), TEXT("ps5"), TEXT("wireless controller")};
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

	FString PadBrand(const FString& PadName)
	{
		const FString Lower = PadName.ToLower();
		const auto Has = [&Lower](const TCHAR* const* Hints, int32 N)
		{
			for (int32 I = 0; I < N; ++I)
			{
				if (Lower.Contains(Hints[I], ESearchCase::CaseSensitive))
				{
					return true;
				}
			}
			return false;
		};
		// Xbox first: "Xbox Wireless Controller" is Microsoft's name, "Wireless Controller" alone is Sony's
		if (Has(XboxHints, UE_ARRAY_COUNT(XboxHints)))
		{
			return TEXT("pad_xbox");
		}
		if (Has(SwitchHints, UE_ARRAY_COUNT(SwitchHints)))
		{
			return TEXT("pad_switch");
		}
		if (Has(PlayStationHints, UE_ARRAY_COUNT(PlayStationHints)))
		{
			return TEXT("pad_playstation");
		}
		return TEXT("pad_other");
	}

	FString PadName(FInputDeviceId DeviceId)
	{
		if (!DeviceId.IsValid())
		{
			return FString();
		}
		const TOptional<FInputDeviceDescriptor> Desc = FInputDeviceRegistry::FindDescriptor(DeviceId);
		if (!Desc.IsSet())
		{
			return FString();
		}
		const FString Interface = Desc->InputDeviceName.IsNone() ? FString() : Desc->InputDeviceName.ToString();
		const FString Hardware = Desc->HardwareDeviceIdentifier.IsNone() ? FString() : Desc->HardwareDeviceIdentifier.ToString();
		return (Interface + TEXT(" ") + Hardware).TrimStartAndEnd();
	}

	FString DeviceOf(const FKey& Key, FInputDeviceId DeviceId)
	{
		if (Key.IsGamepadKey())
		{
			return PadBrand(PadName(DeviceId));
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
