// ---------------------------------------------------------------------------
// RDAbilities.cpp
// Purpose : See RDAbilities.h.
//
// Pseudocode:
//   activate -> CommitAbility (CheckCost + CheckCooldown, then ApplyCost + ApplyCooldown) -> Perform -> end
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
#include "Abilities/RDAbilities.h"

#include "AbilitySystemComponent.h"
#include "Abilities/RDAttributeSet.h"
#include "Abilities/RDEffects.h"
#include "Abilities/RDTags.h"
#include "Game/RDMage.h"
#include "Game/RDTuning.h"

URDAbility::URDAbility()
{
	InstancingPolicy = EGameplayAbilityInstancingPolicy::InstancedPerActor;
}

bool URDAbility::CheckCost(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
                           FGameplayTagContainer* OptionalRelevantTags) const
{
	const float Cost = CostOf(GetDefault<URDTuning>()->Numbers());
	const UAbilitySystemComponent* Asc = ActorInfo ? ActorInfo->AbilitySystemComponent.Get() : nullptr;
	return Asc && (Cost <= 0.f || Asc->GetNumericAttribute(URDAttributeSet::GetManaAttribute()) >= Cost);
}

void URDAbility::ApplyCost(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
                           const FGameplayAbilityActivationInfo ActivationInfo) const
{
	const float Cost = CostOf(GetDefault<URDTuning>()->Numbers());
	if (Cost > 0.f)
	{
		FGameplayEffectSpecHandle Spec = MakeOutgoingGameplayEffectSpec(URDEffect_Mana::StaticClass());
		Spec.Data->SetSetByCallerMagnitude(RDTags::Data_Amount, -Cost);
		ApplyGameplayEffectSpecToOwner(Handle, ActorInfo, ActivationInfo, Spec);
	}
}

void URDAbility::ApplyCooldown(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
                               const FGameplayAbilityActivationInfo ActivationInfo) const
{
	const float Seconds = CooldownOf(GetDefault<URDTuning>()->Numbers());
	if (Seconds > 0.f && CooldownTags.Num() > 0)
	{
		FGameplayEffectSpecHandle Spec = MakeOutgoingGameplayEffectSpec(URDEffect_Timed::StaticClass());
		Spec.Data->SetSetByCallerMagnitude(RDTags::Data_Duration, Seconds);
		Spec.Data->DynamicGrantedTags.AppendTags(CooldownTags);
		ApplyGameplayEffectSpecToOwner(Handle, ActorInfo, ActivationInfo, Spec);
	}
}

void URDAbility::ActivateAbility(const FGameplayAbilitySpecHandle Handle, const FGameplayAbilityActorInfo* ActorInfo,
                                 const FGameplayAbilityActivationInfo ActivationInfo, const FGameplayEventData* TriggerEventData)
{
	if (!CommitAbility(Handle, ActorInfo, ActivationInfo))
	{
		EndAbility(Handle, ActorInfo, ActivationInfo, true, true);
		return;
	}
	if (ARDMage* Mage = Cast<ARDMage>(ActorInfo->AvatarActor.Get()))
	{
		Perform(*Mage, GetDefault<URDTuning>()->Numbers());
	}
	EndAbility(Handle, ActorInfo, ActivationInfo, true, false);
}

URDAbility_Bolt::URDAbility_Bolt()
{
	CooldownTags.AddTag(RDTags::Cooldown_Bolt);
}

void URDAbility_Bolt::Perform(ARDMage& Mage, const FRDNumbers& N)
{
	Mage.FireBolt(N);
}

URDAbility_Ward::URDAbility_Ward()
{
	CooldownTags.AddTag(RDTags::Cooldown_Ward);
}

void URDAbility_Ward::Perform(ARDMage& Mage, const FRDNumbers& N)
{
	Mage.RaiseWard(N);
}

URDAbility_Dash::URDAbility_Dash()
{
	CooldownTags.AddTag(RDTags::Cooldown_Dash);
}

void URDAbility_Dash::Perform(ARDMage& Mage, const FRDNumbers& N)
{
	Mage.StartDash(N);
}
