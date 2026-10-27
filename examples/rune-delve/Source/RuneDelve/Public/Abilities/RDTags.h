// ---------------------------------------------------------------------------
// RDTags.h
// Purpose : Native gameplay tags, defined in C++ so nothing needs the editor's tag manager.
// Usage   : ASC->HasMatchingGameplayTag(RDTags::State_Warded)
// Notes   : Cooldown.* are granted by URDEffect_Timed specs (DynamicGrantedTags); State.* likewise.
//           Data.* name SetByCaller magnitudes (damage, amount, duration). Data.Melee marks an orc swing.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#pragma once

#include "NativeGameplayTags.h"

namespace RDTags
{
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(Cooldown_Bolt);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(Cooldown_Dash);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(Cooldown_Ward);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(State_Warded);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(State_Staggered);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(State_Dashing);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(Data_Amount);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(Data_Duration);
	UE_DECLARE_GAMEPLAY_TAG_EXTERN(Data_Melee);
}
