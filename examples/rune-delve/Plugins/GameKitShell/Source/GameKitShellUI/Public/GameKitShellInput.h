// ---------------------------------------------------------------------------
// GameKitShellInput.h
// Purpose : Unreal keys as the shell's binding strings: FKey SpaceBar -> "key:space", Gamepad_FaceButton_Bottom
//           -> "pad:south", LeftMouseButton -> "mouse:left", and back. The settings' input.bindings hold these
//           strings (GameKitBindings.h), so the screens never store an FKey.
// Usage   : const FString Binding = GameKit::ShellInput::BindingOf(KeyEvent.GetKey());   // "" when unknown
//           Model->KeyPressed(Binding, GameKit::ShellInput::DeviceOf(KeyEvent.GetKey()));
//           const TOptional<FKey> Key = GameKit::ShellInput::KeyOf(TEXT("pad:l1"));     // Gamepad_LeftShoulder
// Notes   : Pad names follow the positional layout (south = the bottom face button, as GameKitBindings.cpp).
//           Unreal does not tell an Xbox pad from a PlayStation one without a platform plugin, so every pad
//           reports the device "pad", which GameKit::GlyphSet turns into the generic prompt set; a game that
//           knows the make can pass "pad_xbox" or "pad_playstation" itself. Letters and digits map by their
//           key name; unknown keys give the lower-cased key name, so a game can bind them too.
// Authored: Written with Claude (Fable 5.1, claude-fable-5-1)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"

namespace GameKit::ShellInput
{
	/** "key:<name>", "mouse:<name>", "pad:<name>" for an Unreal key; "" for an axis or an invalid key. */
	GAMEKITSHELLUI_API FString BindingOf(const FKey& Key);

	/** "keyboard", "mouse" or "pad" (what the prompt glyphs follow). */
	GAMEKITSHELLUI_API FString DeviceOf(const FKey& Key);

	/** The Unreal key for a binding string; unset when there is none. */
	GAMEKITSHELLUI_API TOptional<FKey> KeyOf(const FString& Binding);
}
