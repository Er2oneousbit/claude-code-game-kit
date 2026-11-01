// ---------------------------------------------------------------------------
// GameKitBindings.h
// Purpose : Input bindings as data: the default action map, rebinding with conflict swaps, and which
//           button-prompt art to show (keyboard, Xbox, PlayStation, generic pad). Plain C++, no input system.
// Usage   : FGameKitBindings B = GameKit::BindingsFromJson(GameKit::Json::FindObject(Input, TEXT("bindings")));
//           if (TOptional<FGameKitRebindResult> R = GameKit::Rebind(B, TEXT("jump"), GameKit::KeyboardSlot, TEXT("key:k")))
//           {
//               B = R->Bindings;   // R->Conflicts lists the actions that gave the key up (tell the player)
//           }
//           const FString Set = GameKit::GlyphSet(GameKit::Json::GetString(Input, TEXT("glyphs"), TEXT("auto")), LastDevice);
//           const FString Art = GameKit::GlyphName(Set, GameKit::PromptBinding(B, TEXT("jump"), Set));   // "xbox_a"
// Notes   : A binding is "<kind>:<name>": key:space, mouse:left, pad:south (the bottom face button),
//           pad_axis:leftx- ; "" is an unbound slot. Slot 0 is keyboard and mouse, slot 1 the gamepad.
//           Your input code (Enhanced Input mappings, or a key-to-string table on FKey) turns presses into
//           these strings; this file never sees an FKey. Actions starting with "ui_" form one conflict group
//           (menus), the rest another (play), so Escape can be both ui_cancel and pause. Action names are
//           TMap keys, so case-insensitive here (the reference is case-sensitive). Matches
//           tools/golden_vectors.py (rebind, glyph_set, glyph_name, prompt_binding), checked against
//           data/golden/shell.json.
//
// Pseudocode:
//   Rebind(b, action, slot, binding):
//     old = b[action][slot] (or "" for a new slot); slot past the end -> unset
//     conflicts = every (other, s) in the same group holding binding, sorted by action then slot
//     b[action][slot] = binding ; every conflict gets old (a swap, or "" = unbound)
//   GlyphSet(setting, device): the setting, or for "auto" the last device's family
//   GlyphName(set, binding)  : key_x, mouse_x, or the pad button in the set's names (xbox_a, ps_cross, pad_south)
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/** action -> bindings by slot ("" = unbound). */
using FGameKitBindings = TMap<FString, TArray<FString>>;

struct FGameKitRebindResult
{
	FGameKitBindings Bindings;
	TArray<TPair<FString, int32>> Conflicts;   // (action, slot) that gave the binding up, sorted
};

namespace GameKit
{
	// ---- Constants ----
	inline constexpr int32 KeyboardSlot = 0;   // keyboard and mouse
	inline constexpr int32 PadSlot = 1;        // gamepad
	inline constexpr const TCHAR* UiActionPrefix = TEXT("ui_");
	/** Settings values for input.glyphs; "auto" follows the last device used. */
	inline constexpr const TCHAR* GlyphSets[] = {TEXT("auto"), TEXT("keyboard"), TEXT("xbox"), TEXT("playstation"), TEXT("generic")};

	/** The built-in action map (the default of settings input.bindings). */
	GAMEKITSHELL_API const FGameKitBindings& DefaultBindings();

	/** "ui" for ui_* actions, "game" for the rest. */
	GAMEKITSHELL_API FString GroupOf(const FString& Action);

	/** Action names in case-sensitive order (the order Rebind reports conflicts in). */
	GAMEKITSHELL_API TArray<FString> SortedActions(const FGameKitBindings& Bindings);

	/**
	 * Puts Binding into Action's Slot (Slot == the slot count appends one). Another action of the same group that
	 * used it gets this slot's old binding (a swap) or "" when there was none. Unset when Slot is past the end.
	 */
	GAMEKITSHELL_API TOptional<FGameKitRebindResult> Rebind(const FGameKitBindings& Bindings, const FString& Action, int32 Slot,
	                                                        const FString& Binding);

	/** Which prompt art to show: the setting, or for "auto" the last device ("keyboard", "mouse", "pad_xbox",
	 *  "pad_playstation"; anything else is "generic"). */
	GAMEKITSHELL_API FString GlyphSet(const FString& Setting, const FString& LastDevice);

	/** The prompt art name for one binding: key_space, mouse_left, xbox_a, ps_cross, pad_south, xbox_lstick, "unknown". */
	GAMEKITSHELL_API FString GlyphName(const FString& Set, const FString& Binding);

	/** The binding to show for Action: slot 0 for the keyboard set, slot 1 otherwise; "" when there is none. */
	GAMEKITSHELL_API FString PromptBinding(const FGameKitBindings& Bindings, const FString& Action, const FString& Set);

	/** From settings input.bindings (an object of string arrays); anything else in it is skipped. */
	GAMEKITSHELL_API FGameKitBindings BindingsFromJson(const TSharedPtr<FJsonObject>& Object);
	GAMEKITSHELL_API TSharedRef<FJsonObject> BindingsToJson(const FGameKitBindings& Bindings);
}

// {{FOOTER}}
