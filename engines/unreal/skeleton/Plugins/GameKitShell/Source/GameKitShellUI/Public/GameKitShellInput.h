// ---------------------------------------------------------------------------
// GameKitShellInput.h
// Purpose : Unreal keys as the shell's binding strings: FKey SpaceBar -> "key:space", Gamepad_FaceButton_Bottom
//           -> "pad:south", LeftMouseButton -> "mouse:left", and back. The settings' input.bindings hold these
//           strings (GameKitBindings.h), so the screens never store an FKey. Also which make of pad pressed a
//           button, for the prompt glyphs.
// Usage   : const FString Binding = GameKit::ShellInput::BindingOf(KeyEvent.GetKey());   // "" when unknown
//           Model->KeyPressed(Binding, GameKit::ShellInput::DeviceOf(KeyEvent.GetKey(), KeyEvent.GetInputDeviceId()));
//           const TOptional<FKey> Key = GameKit::ShellInput::KeyOf(TEXT("pad:l1"));     // Gamepad_LeftShoulder
//           GameKit::ShellInput::PadBrand(TEXT("DualSense Wireless Controller"));        // "pad_playstation"
// Notes   : Pad names follow the positional layout (south = the bottom face button, as GameKitBindings.cpp).
//           The pad's make comes from the name its input plugin registers for the device (FInputDeviceRegistry:
//           the interface name plus the hardware identifier), matched by the C++ shell's hints plus Nintendo
//           ones: Xbox first ("Xbox Wireless Controller" is Microsoft's, "Wireless Controller" alone is Sony's),
//           then Nintendo, then PlayStation, else "pad_other". Which name a pad gets depends on the input plugin:
//           on Windows XInput and GameInput report "XInputController" or "XboxOne" (so Xbox prompts, also for a
//           PlayStation pad behind Steam Input or DS4Windows, which pretend to be one); WinDualShock reports
//           Sony pads, and Linux passes SDL's own pad names. A Switch pad gets "pad_switch", which shows the
//           generic positional prompts (the kit ships no Nintendo set). Letters and digits map by their key name;
//           unknown keys give the lower-cased key name, so a game can bind them too.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1); pad makes by Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"

namespace GameKit::ShellInput
{
	/** "key:<name>", "mouse:<name>", "pad:<name>" for an Unreal key; "" for an axis or an invalid key. */
	GAMEKITSHELLUI_API FString BindingOf(const FKey& Key);

	/** "keyboard", "mouse" or a pad device (PadBrand of the device's name): what the prompt glyphs follow. */
	GAMEKITSHELLUI_API FString DeviceOf(const FKey& Key, FInputDeviceId DeviceId = FInputDeviceId());

	/** "pad_xbox", "pad_playstation", "pad_switch" or "pad_other" from a pad's name (any case). */
	GAMEKITSHELLUI_API FString PadBrand(const FString& PadName);

	/** The name the input plugin registered for a device ("XInputInterface XInputController"); "" when unknown. */
	GAMEKITSHELLUI_API FString PadName(FInputDeviceId DeviceId);

	/** The Unreal key for a binding string; unset when there is none. */
	GAMEKITSHELLUI_API TOptional<FKey> KeyOf(const FString& Binding);
}

// {{FOOTER}}
