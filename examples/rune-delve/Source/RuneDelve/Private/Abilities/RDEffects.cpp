// ---------------------------------------------------------------------------
// RDEffects.cpp
// Purpose : See RDEffects.h.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Abilities/RDEffects.h"

#include "Abilities/RDAttributeSet.h"
#include "Abilities/RDTags.h"

namespace
{
	FGameplayEffectModifierMagnitude SetByCaller(const FGameplayTag& Tag)
	{
		FSetByCallerFloat Value;
		Value.DataTag = Tag;
		return FGameplayEffectModifierMagnitude(Value);
	}

	FGameplayModifierInfo AddFromCaller(const FGameplayAttribute& Attribute)
	{
		FGameplayModifierInfo Mod;
		Mod.Attribute = Attribute;
		Mod.ModifierOp = EGameplayModOp::AddBase;
		Mod.ModifierMagnitude = SetByCaller(RDTags::Data_Amount);
		return Mod;
	}
}

URDEffect_Damage::URDEffect_Damage()
{
	DurationPolicy = EGameplayEffectDurationType::Instant;
	Modifiers.Add(AddFromCaller(URDAttributeSet::GetDamageAttribute()));
}

URDEffect_Mana::URDEffect_Mana()
{
	DurationPolicy = EGameplayEffectDurationType::Instant;
	Modifiers.Add(AddFromCaller(URDAttributeSet::GetManaAttribute()));
}

URDEffect_Heal::URDEffect_Heal()
{
	DurationPolicy = EGameplayEffectDurationType::Instant;
	Modifiers.Add(AddFromCaller(URDAttributeSet::GetHealthAttribute()));
}

URDEffect_Timed::URDEffect_Timed()
{
	DurationPolicy = EGameplayEffectDurationType::HasDuration;
	DurationMagnitude = SetByCaller(RDTags::Data_Duration);
}

URDEffect_ManaRegen::URDEffect_ManaRegen()
{
	DurationPolicy = EGameplayEffectDurationType::Infinite;
	Period = FScalableFloat(PeriodSeconds);
	Modifiers.Add(AddFromCaller(URDAttributeSet::GetManaAttribute()));
}
